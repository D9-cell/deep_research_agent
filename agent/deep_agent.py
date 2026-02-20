"""
AlgoMentor — Root Agent  (all phases)

The RootAgent class is the only public interface; main.py only
ever instantiates and calls this class.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_mistralai import ChatMistralAI

from agent.prompts import (
    CODE_GEN_SYSTEM_PROMPT,
    MEMORY_CONTEXT_TEMPLATE,
    ORCHESTRATOR_SYNTHESIS_PROMPT,
    ROOT_SYSTEM_PROMPT,
)
from config.settings import DEFAULT_MODEL, MISTRAL_API_KEY, MODEL_TEMPERATURE
from tools.internet_search import internet_search
from tools.leetcode_scraper import leetcode_scraper

# ── Optional Phase-2 imports (graceful degradation) ───────────────────────────
try:
    from agent.subagents import (
        PatternAgent,
        ProblemAcquisitionAgent,
        SimilarityAgent,
        SolutionMiningAgent,
        StrategyOptimizationAgent,
    )
    _PHASE2_AVAILABLE = True
except ImportError:
    _PHASE2_AVAILABLE = False

# ── Optional Phase-3 imports (graceful degradation) ───────────────────────────
try:
    from memory.store import MemoryStore
    from tools.memory_store_tool import memory_store_tool
    _PHASE3_AVAILABLE = True
except ImportError:
    _PHASE3_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# Internal: bare agentic loop
# ═══════════════════════════════════════════════════════════════════════════════

class _AgentRunner:
    """
    Minimal tool-calling loop for a ChatMistralAI model.

    Keeps running until the model produces a response with no pending
    tool calls, then returns the final text content.
    """

    def __init__(self, model: ChatMistralAI, tools: list, system_prompt: str) -> None:
        self._tool_map: dict[str, Any] = {t.name: t for t in tools}
        self._model = model.bind_tools(tools)
        self._system = system_prompt

    def run(self, user_message: str, extra_context: str = "") -> str:
        messages: list = [SystemMessage(content=self._system)]
        if extra_context:
            messages.append(SystemMessage(content=extra_context))
        messages.append(HumanMessage(content=user_message))

        max_iterations = 10
        for _ in range(max_iterations):
            response: AIMessage = self._model.invoke(messages)
            messages.append(response)

            if not getattr(response, "tool_calls", None):
                # No more tool calls → final answer
                return response.content or ""

            # Execute every tool call the model requested
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_obj = self._tool_map.get(tool_name)
                if tool_obj is None:
                    result = f"ERROR: unknown tool '{tool_name}'"
                else:
                    try:
                        result = tool_obj.invoke(tool_args)
                    except Exception as exc:          # noqa: BLE001
                        result = f"Tool error: {exc}"

                messages.append(
                    ToolMessage(
                        content=json.dumps(result) if not isinstance(result, str) else result,
                        tool_call_id=tc["id"],
                    )
                )

        return "⚠️  Agent reached iteration limit without a final answer."


# ═══════════════════════════════════════════════════════════════════════════════
# Public: RootAgent
# ═══════════════════════════════════════════════════════════════════════════════

class RootAgent:
    """
    Orchestrates the full AlgoMentor pipeline.

    Capabilities grow automatically based on which phases are installed:
    always available (LeetCode scraper + Tavily fallback)
    enabled when agent/subagents.py is present
    enabled when memory/store.py is present
    """

    def __init__(self) -> None:
        self._llm = ChatMistralAI(
            api_key=MISTRAL_API_KEY,
            model=DEFAULT_MODEL,
            temperature=MODEL_TEMPERATURE,
        )
        self._phase2 = _PHASE2_AVAILABLE
        self._phase3 = _PHASE3_AVAILABLE

        # Phase 3 memory
        self._memory: MemoryStore | None = None
        if self._phase3:
            self._memory = MemoryStore()

    # ── Phase 1: research a problem ───────────────────────────────────────────

    def research_problem(self, problem_name: str) -> str:
        """
        Explain the problem and produce pseudocode.

        Phase 1: single-agent loop.
        Phase 2: parallel subagents + synthesis.
        Phase 3: memory context prepended.
        """
        memory_ctx = self._build_memory_context(problem_name)

        if self._phase2:
            return self._phase2_research(problem_name, memory_ctx)
        return self._phase1_research(problem_name, memory_ctx)

    def _phase1_research(self, problem_name: str, memory_ctx: str) -> str:
        tools = [leetcode_scraper, internet_search]
        if self._phase3:
            tools.append(memory_store_tool)   # type: ignore[arg-type]
        runner = _AgentRunner(
            model=self._llm,
            tools=tools,
            system_prompt=ROOT_SYSTEM_PROMPT,
        )
        prompt = (
            f"Teach me the following problem: **{problem_name}**\n"
            "Fetch the problem statement, explain it, and write pseudocode."
        )
        return runner.run(prompt, extra_context=memory_ctx)

    # ── Phase 2: subagent orchestration ──────────────────────────────────────

    def _phase2_research(self, problem_name: str, memory_ctx: str) -> str:
        """Fire all 5 subagents, then synthesise with the root LLM."""
        print("\n  ⚙  Spawning subagents…")

        problem_agent   = ProblemAcquisitionAgent(self._llm)
        similarity_agent = SimilarityAgent(self._llm)
        pattern_agent   = PatternAgent(self._llm)
        solution_agent  = SolutionMiningAgent(self._llm)
        strategy_agent  = StrategyOptimizationAgent(self._llm)

        # Step 1 — fetch problem (needed by others)
        print("  📥  Problem Acquisition Agent…")
        problem_data = problem_agent.run(problem_name)

        tags_str = ", ".join(problem_data.get("tags", [])) if isinstance(problem_data, dict) else ""

        # Steps 2-4 — logically depends on problem data; run sequentially for
        # simplicity (could be parallelised with threading if latency matters)
        print("  🔍  Similarity Discovery Agent…")
        similar = similarity_agent.run(problem_name, tags_str)

        print("  🧩  Pattern Classification Agent…")
        pattern = pattern_agent.run(
            str(problem_data.get("description", problem_name)), tags_str
        )

        print("  ⛏   Solution Mining Agent…")
        solutions = solution_agent.run(problem_name, pattern)

        print("  🏆  Strategy Optimization Agent…")
        strategy = strategy_agent.run(solutions, pattern)

        # Step 5 — root synthesises everything
        print("  🔗  Synthesising results…\n")
        synthesis_input = (
            f"Problem: {problem_name}\n\n"
            f"PROBLEM DATA:\n{json.dumps(problem_data, indent=2)}\n\n"
            f"SIMILAR PROBLEMS:\n{similar}\n\n"
            f"PATTERN REPORT:\n{pattern}\n\n"
            f"SOLUTION APPROACHES:\n{solutions}\n\n"
            f"STRATEGY REPORT:\n{strategy}\n"
        )
        runner = _AgentRunner(
            model=self._llm,
            tools=[],  # synthesis needs no tools
            system_prompt=ORCHESTRATOR_SYNTHESIS_PROMPT,
        )
        return runner.run(synthesis_input, extra_context=memory_ctx)

    # ── Phase 1 + 2: code generation (after human gate) ──────────────────────

    def generate_code(
        self,
        problem_name: str,
        language: str,
        research_output: str,
    ) -> str:
        """
        Produce a full, commented solution in the requested language.

        Args:
            problem_name:    e.g. 'Number of Islands'
            language:        e.g. 'Python', 'Java', 'C++'
            research_output: The explanation + pseudocode produced by research_problem()
        """
        system = CODE_GEN_SYSTEM_PROMPT.replace("{language}", language).replace(
            "{language_lower}", language.lower()
        )
        runner = _AgentRunner(
            model=self._llm,
            tools=[],  # no tools needed for pure code gen
            system_prompt=system,
        )
        prompt = (
            f"Problem: **{problem_name}**\n\n"
            f"Agreed approach and pseudocode:\n{research_output}\n\n"
            f"Generate the complete solution in **{language}**."
        )
        result = runner.run(prompt)

        # Phase 3: update memory after successful code generation
        if self._memory:
            self._memory.record_solved(
                problem_name=problem_name,
                language=language,
                research_output=research_output,
            )
        return result

    # ── Phase 3: memory helpers ───────────────────────────────────────────────

    def _build_memory_context(self, problem_name: str) -> str:
        """Return a formatted memory-context string, or '' if Phase 3 is off."""
        if not self._memory:
            return ""
        snapshot = self._memory.snapshot()
        if not snapshot.get("solved_problems"):
            return ""  # nothing to show yet
        return MEMORY_CONTEXT_TEMPLATE.format(
            solved_count=snapshot["solved_count"],
            weak_patterns=", ".join(snapshot.get("weak_patterns", [])) or "none identified",
            strong_patterns=", ".join(snapshot.get("strong_patterns", [])) or "none identified",
            preferred_language=snapshot.get("preferred_language", "not set"),
            recent_topics=", ".join(snapshot.get("recent_topics", [])) or "none",
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def build_root_agent() -> RootAgent:
    """Instantiate and return a fully configured RootAgent."""
    return RootAgent()

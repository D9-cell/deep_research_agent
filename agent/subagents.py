"""
AlgoMentor Phase 2 — Specialised Subagents

Each subagent wraps a narrow _AgentRunner with its own system prompt and
tool set. The RootAgent in deep_agent.py orchestrates all of them.

Total subagents: 5
  1. ProblemAcquisitionAgent
  2. SimilarityAgent
  3. PatternAgent
  4. SolutionMiningAgent
  5. StrategyOptimizationAgent
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_mistralai import ChatMistralAI

from agent.prompts import (
    PATTERN_CLASSIFICATION_PROMPT,
    PROBLEM_ACQUISITION_PROMPT,
    SIMILARITY_DISCOVERY_PROMPT,
    SOLUTION_MINING_PROMPT,
    STRATEGY_OPTIMIZATION_PROMPT,
)
from skills.pattern_classifier import PatternClassifierSkill
from skills.complexity import ComplexityAnalysisSkill
from skills.ranking import StrategyRankingSkill
from tools.internet_search import internet_search
from tools.leetcode_scraper import leetcode_scraper
from tools.similarity import similarity_scoring
from tools.content_extractor import content_extractor


# ── Shared agentic runner (duplicated here to avoid circular imports) ─────────

class _SubAgentRunner:
    """Single-turn, tool-calling agent loop."""

    def __init__(
        self,
        model: ChatMistralAI,
        tools: list,
        system_prompt: str,
        max_iterations: int = 8,
    ) -> None:
        self._tool_map: dict[str, Any] = {t.name: t for t in tools}
        self._model = model.bind_tools(tools) if tools else model
        self._system = system_prompt
        self._max_iters = max_iterations

    def run(self, user_message: str) -> str:
        messages: list = [
            SystemMessage(content=self._system),
            HumanMessage(content=user_message),
        ]
        for _ in range(self._max_iters):
            response: AIMessage = self._model.invoke(messages)
            messages.append(response)

            if not getattr(response, "tool_calls", None):
                return response.content or ""

            for tc in response.tool_calls:
                tool_obj = self._tool_map.get(tc["name"])
                if tool_obj is None:
                    result = f"ERROR: unknown tool '{tc['name']}'"
                else:
                    try:
                        result = tool_obj.invoke(tc["args"])
                    except Exception as exc:  # noqa: BLE001
                        result = f"Tool error: {exc}"

                messages.append(
                    ToolMessage(
                        content=json.dumps(result) if not isinstance(result, str) else result,
                        tool_call_id=tc["id"],
                    )
                )
        return "⚠️  Subagent reached iteration limit."


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Problem Acquisition Agent
# ═══════════════════════════════════════════════════════════════════════════════

class ProblemAcquisitionAgent:
    """
    Fetches and normalises the full problem statement.
    Returns a dict (or a string if JSON parsing fails).
    """

    def __init__(self, model: ChatMistralAI) -> None:
        self._runner = _SubAgentRunner(
            model=model,
            tools=[leetcode_scraper, internet_search, content_extractor],
            system_prompt=PROBLEM_ACQUISITION_PROMPT,
        )

    def run(self, problem_name: str) -> dict | str:
        raw = self._runner.run(
            f"Fetch the complete problem statement for: {problem_name}"
        )
        try:
            # Try to extract a JSON block if the agent wrapped it in markdown
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            return json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            return {"description": raw, "tags": [], "difficulty": "Unknown"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Similarity Discovery Agent
# ═══════════════════════════════════════════════════════════════════════════════

class SimilarityAgent:
    """
    Finds structurally similar problems on LeetCode and Codeforces.
    Returns a raw string (formatted list) for synthesis.
    """

    def __init__(self, model: ChatMistralAI) -> None:
        self._runner = _SubAgentRunner(
            model=model,
            tools=[internet_search, similarity_scoring],
            system_prompt=SIMILARITY_DISCOVERY_PROMPT,
        )

    def run(self, problem_name: str, tags: str) -> str:
        return self._runner.run(
            f"Problem: {problem_name}\nTopic tags: {tags}\n"
            "Find up to 5 structurally similar problems from LeetCode and Codeforces."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Pattern Classification Agent
# ═══════════════════════════════════════════════════════════════════════════════

class PatternAgent:
    """
    Identifies algorithmic patterns.
    Augments LLM reasoning with the deterministic PatternClassifierSkill.
    """

    def __init__(self, model: ChatMistralAI) -> None:
        self._runner = _SubAgentRunner(
            model=model,
            tools=[internet_search],
            system_prompt=PATTERN_CLASSIFICATION_PROMPT,
        )
        self._skill = PatternClassifierSkill()

    def run(self, description: str, tags: str) -> str:
        # Skill-based fast classification first
        skill_result = self._skill.classify(description + " " + tags)

        prompt = (
            f"Problem description:\n{description}\n\n"
            f"Topic tags: {tags}\n\n"
            f"Skill pre-classification: {json.dumps(skill_result)}\n\n"
            "Confirm or refine the classification. Return JSON."
        )
        return self._runner.run(prompt)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Solution Mining Agent
# ═══════════════════════════════════════════════════════════════════════════════

class SolutionMiningAgent:
    """
    Mines known solution approaches from the web.
    Returns a raw string describing 2-4 approaches.
    """

    def __init__(self, model: ChatMistralAI) -> None:
        self._runner = _SubAgentRunner(
            model=model,
            tools=[internet_search, content_extractor],
            system_prompt=SOLUTION_MINING_PROMPT,
        )

    def run(self, problem_name: str, pattern_report: str) -> str:
        return self._runner.run(
            f"Problem: {problem_name}\n"
            f"Identified pattern: {pattern_report}\n\n"
            "Search for and extract 2-4 distinct solution approaches. "
            "Include time/space complexity for each."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Strategy Optimization Agent
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyOptimizationAgent:
    """
    Selects and refines the best strategy.
    Augments LLM reasoning with ComplexityAnalysisSkill + StrategyRankingSkill.
    """

    def __init__(self, model: ChatMistralAI) -> None:
        self._runner = _SubAgentRunner(
            model=model,
            tools=[],
            system_prompt=STRATEGY_OPTIMIZATION_PROMPT,
        )
        self._complexity_skill = ComplexityAnalysisSkill()
        self._ranking_skill = StrategyRankingSkill()

    def run(self, solution_approaches: str, pattern_report: str) -> str:
        # Skills enrich the prompt
        complexity_hints = self._complexity_skill.analyse(solution_approaches)
        ranked = self._ranking_skill.rank(solution_approaches, complexity_hints)

        prompt = (
            f"Identified pattern:\n{pattern_report}\n\n"
            f"Candidate approaches:\n{solution_approaches}\n\n"
            f"Complexity analysis (skill output):\n{json.dumps(complexity_hints, indent=2)}\n\n"
            f"Skill-ranked strategies:\n{json.dumps(ranked, indent=2)}\n\n"
            "Select the optimal strategy, justify the choice, and produce refined pseudocode."
        )
        return self._runner.run(prompt)

# AlgoMentor — Architecture

---

## Layer Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Transport Layer                          │
│           CLI (app/cli.py)   │   Telegram (app/telegram_bot.py) │
└───────────────────────────────┬─────────────────────────────────┘
                                │  AsyncIterator[AgentEvent]
┌───────────────────────────────▼─────────────────────────────────┐
│                        Agent Layer                              │
│   AgentService (core/agent_service.py)                          │
│   ├── handle_message_stream()  — streaming entry point          │
│   ├── _stream_idle()           — drives research pipeline       │
│   ├── _stream_approval()       — human-in-the-loop gate         │
│   └── _stream_language()       — code generation                │
│                                                                 │
│   RootAgent (agent/deep_agent.py)                               │
│   ├── research_problem()       — Phase 1 or Phase 2 path        │
│   └── generate_code()          — language-targeted synthesis    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
┌─────────▼──────────┐ ┌───────▼────────┐ ┌──────────▼──────────┐
│   Subagent Layer   │ │   Skill Layer  │ │    Memory Layer     │
│                    │ │                │ │                     │
│ ProblemAcquisition │ │ PatternClassif │ │ MemoryStore         │
│ SimilarityAgent    │ │ ComplexityAnal │ │ (memory/store.py)   │
│ PatternAgent       │ │ StrategyRankin │ │                     │
│ SolutionMining     │ │ ExampleSimulat │ │ Backed by           │
│ StrategyOptim      │ │                │ │ memory/memory.json  │
└─────────┬──────────┘ └───────┬────────┘ └──────────┬──────────┘
          │                   │                       │
┌─────────▼───────────────────▼───────────────────────▼──────────┐
│                         Tool Layer                              │
│  leetcode_scraper  │  internet_search  │  similarity_scoring   │
│  content_extractor │  memory_store_tool                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Transport Layer

### CLI (`app/cli.py`)

- Synchronous REPL driven by `input()`.
- Each user message goes through `asyncio.run(_run_stream(...))`.
- Events rendered in-order: progress banners → section blocks → divider.
- Never buffers the full response; each section prints as it arrives.

### Telegram Bot (`app/telegram_bot.py`)

- `python-telegram-bot` v20+ async polling.
- On first `AgentEvent` with `stage in STAGE_MESSAGES`, sends a placeholder message.
- Subsequent progress events **edit** that placeholder (no new messages until sections arrive).
- On first `section` event, the placeholder is deleted; sections are sent as individual messages.
- Large sections (> 4 096 chars) are split on newline boundaries before sending.
- Error events delete the placeholder and send a formatted error message.

---

## Agent Layer

### AgentService (`core/agent_service.py`)

Central orchestrator. Responsibilities:

| Responsibility | Mechanism |
|---|---|
| Session state | Per-user `_Session` dataclass (IDLE / AWAITING_APPROVAL / AWAITING_LANGUAGE) |
| Request correlation | UUID v4 generated at `handle_message_stream()` entry |
| Progress streaming | `asyncio.wait` with timeouts on six stage checkpoints |
| Section parsing | Regex split on recognised markdown headings |
| Structured logging | `log_event()` + `StageTimer` at every stage boundary |
| Thread isolation | All blocking agent calls via `asyncio.to_thread` |

### RootAgent (`agent/deep_agent.py`)

- **Phase 1**: single `_AgentRunner` loop with LeetCode scraper + Tavily.
- **Phase 2**: sequential 5-subagent fan-out, synthesised by root LLM.
- **Phase 3**: memory context prepended to every research call.

---

## Event Flow

```
User message
    │
    ▼
AgentService.handle_message_stream(user_id, message)
    │
    ├─► request_id = uuid4()
    ├─► session state lookup
    │
    ▼   [IDLE state]
asyncio.to_thread(agent.research_problem)  ──► background thread
    │
    ├─── t=0s  ──► yield AgentEvent(stage="fetch")
    ├─── t=8s  ──► yield AgentEvent(stage="similar")
    ├─── t=16s ──► yield AgentEvent(stage="patterns")
    ├─── t=24s ──► yield AgentEvent(stage="solutions")
    ├─── t=32s ──► yield AgentEvent(stage="strategy")
    ├─── t=40s ──► yield AgentEvent(stage="synthesis")
    │   (or earlier if thread finishes before timer fires)
    │
    ▼
research complete
    │
    ├─── _parse_sections(text)
    │       ├─► yield AgentEvent(stage="section", title="Problem")
    │       ├─► yield AgentEvent(stage="section", title="Intuition")
    │       ├─► yield AgentEvent(stage="section", title="Pseudocode")
    │       ├─► yield AgentEvent(stage="section", title="Complexity")
    │       ├─► yield AgentEvent(stage="section", title="Similar Problems")
    │       ├─► yield AgentEvent(stage="section", title="Pattern")
    │       └─► yield AgentEvent(stage="section", title="Learning Context")
    │
    └─► yield AgentEvent(stage="complete")
```

All events carry `user_id`, `request_id`, `timestamp`.

---

## Tool Layer

| Tool | File | Used by |
|---|---|---|
| `leetcode_scraper` | `tools/leetcode_scraper.py` | ProblemAcquisitionAgent, Phase 1 runner |
| `internet_search` | `tools/internet_search.py` | ProblemAcquisitionAgent, SimilarityAgent, PatternAgent, SolutionMiningAgent |
| `similarity_scoring` | `tools/similarity.py` | SimilarityAgent |
| `content_extractor` | `tools/content_extractor.py` | ProblemAcquisitionAgent, SolutionMiningAgent |
| `memory_store_tool` | `tools/memory_store_tool.py` | Phase 1 runner (Phase 3 only) |

---

## Skill Layer

Skills are deterministic Python functions that augment LLM reasoning without
requiring an API call.

| Skill | File | Augments |
|---|---|---|
| `PatternClassifierSkill` | `skills/pattern_classifier.py` | PatternAgent pre-classification |
| `ComplexityAnalysisSkill` | `skills/complexity.py` | StrategyOptimizationAgent |
| `StrategyRankingSkill` | `skills/ranking.py` | StrategyOptimizationAgent |
| `ExampleSimulator` | `skills/simulator.py` | (available for future use) |

---

## Memory Layer

```
MemoryStore (memory/store.py)
    │
    ├── record_solved(problem, language, research_output)
    ├── snapshot() → {solved_count, weak_patterns, strong_patterns, …}
    └── Persists to memory/memory.json (JSON, append-safe)
```

Memory is injected as a context string into every `research_problem()` call via  
`RootAgent._build_memory_context()`.

---

## Logging Architecture

```
log_event() / StageTimer
    │
    ▼
algomentor (root Logger)
    ├── StreamHandler (stderr)     INFO+  human-readable
    ├── RotatingFileHandler        DEBUG+ JSON → algomentor.log (10 MB × 5)
    └── RotatingFileHandler        ERROR+ JSON → algomentor-error.log (5 MB × 3)
```

Every JSON record includes: `timestamp`, `level`, `logger`, `request_id`,
`user_id`, `agent`, `stage`, `duration_ms` (timed stages only), `message`.

---

## Scaling Strategy

| Concern | Current | Production path |
|---|---|---|
| Concurrency | Single-process asyncio | Uvicorn + multiple workers |
| Session state | In-process Python dict | Redis (TTL-backed) |
| Subagent execution | Sequential | ThreadPoolExecutor fan-out (5 workers) |
| Logs | Local rotating files | Fluentd / Loki aggregation |
| Metrics | None | Prometheus counter/histogram per stage |
| Tracing | UUID correlation only | OpenTelemetry spans per subagent |

---

## Failure Handling

| Failure point | Behaviour |
|---|---|
| `research_problem` raises | Session reset to IDLE; `AgentEvent(stage="error")` yielded; error logged with `exc_info` |
| `generate_code` raises | Session reset to IDLE; error event yielded |
| Telegram message edit fails | `BadRequest` caught; placeholder left as-is; sections still sent |
| Subagent reaches iteration limit | Returns sentinel string `"⚠️  Subagent reached iteration limit."`; pipeline continues to synthesis |
| Mistral API unreachable | Exception propagates to AgentService error handler; graceful error message sent to user |
| Missing env vars | `RuntimeError` raised at startup before any user request is accepted |

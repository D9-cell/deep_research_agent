# AlgoMentor

Production-grade AI algorithm tutor powered by a multi-agent pipeline built on Mistral AI.  
Delivers structured, incremental analysis of LeetCode problems via CLI and Telegram.

---

## Overview

AlgoMentor orchestrates five specialised subagents to research any competitive-programming problem end-to-end:

1. **Problem Acquisition** — scrapes LeetCode / falls back to Tavily web search
2. **Similarity Discovery** — surfaces structurally similar problems
3. **Pattern Classification** — identifies BFS, DP, two-pointer, graph, etc.
4. **Solution Mining** — extracts and ranks known approaches with complexity
5. **Strategy Optimisation** — selects the best strategy, refines pseudocode

A root LLM then synthesises all agent outputs into a structured response.  
Persistent memory (Phase 3) personalises future sessions based on past performance.

---

## Features

| Feature | Detail |
|---|---|
| Progressive streaming | Six stage banners emitted before final content arrives |
| Structured sections | Problem / Intuition / Pseudocode / Complexity / Similar Problems / Pattern / Learning Context |
| Human-in-the-loop | Code generation requires explicit user approval |
| Multi-language codegen | Python / Java / C++ / Go / TypeScript |
| Telegram UX | Progress placeholder edited in-place; sections sent individually |
| Structured JSON logs | Every stage logged with request_id, duration_ms, user_id |
| Request correlation | UUID v4 propagated through every log record |
| Persistent memory | Per-user problem history, weak/strong pattern tracking |
| Phase auto-detection | Capabilities activate based on installed modules |

---

## Environment Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Create `.env` at the project root:

```env
MISTRAL_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
TELEGRAM_BOT_TOKEN=<optional, only needed for Telegram mode>
```

---

## CLI Usage

```bash
# Interactive mode
python main.py

# With initial problem (non-interactive first turn)
python main.py "Number of Islands"
```

**In-session commands:**

| Input | Effect |
|---|---|
| `<problem name>` | Research the problem |
| `yes` / `no` | Approve or skip code generation |
| `python` / `java` / `cpp` / `go` / `typescript` | Select solution language |
| `/reset` | Reset session state |
| `quit` / `exit` / `q` | Exit |
| `help` | Show command list |

**Terminal output example:**

```
  📥  Fetching problem…
  🔍  Finding similar problems…
  🧩  Analyzing patterns…
  ⛏   Mining solutions…
  🏆  Optimizing strategy…
  🔗  Synthesizing response…

  ▌ PROBLEM
  Given an m x n grid of '1's (land) and '0's (water)…

  ▌ INTUITION
  Use BFS from each unvisited land cell…

  ▌ PSEUDOCODE
  function numIslands(grid):
    …

  ▌ COMPLEXITY
  Time O(m x n) | Space O(m x n)
```

---

## Telegram Usage

1. Set `TELEGRAM_BOT_TOKEN` in `.env`.
2. Start the bot: `python main.py telegram`
3. Open your bot in Telegram, send `/start`.
4. Send any LeetCode problem name.

The bot sends an editable progress message immediately (within 1 second) and  
updates it in-place as each pipeline stage completes. Each output section arrives  
as a separate message so large responses never hit Telegram's 4 096-character limit.

---

## Architecture Summary

```
CLI / Telegram
     |
     v
AgentService ---- generates request_id (UUID v4)
     |             emits AgentEvent stream
     |
     +-- research_problem()
     |       |
     |       +-- ProblemAcquisitionAgent
     |       +-- SimilarityAgent
     |       +-- PatternAgent
     |       +-- SolutionMiningAgent
     |       +-- StrategyOptimizationAgent
     |       +-- Root LLM synthesis
     |
     +-- generate_code()   (after human gate)
```

See [architecture.md](architecture.md) for the full layered breakdown with event flow and scaling strategy.

---

## Logging

Two rotating log files are written to the project root:

| File | Level | Rotation |
|---|---|---|
| `algomentor.log` | DEBUG+ | 10 MB x 5 backups |
| `algomentor-error.log` | ERROR+ | 5 MB x 3 backups |

Every record is a single-line JSON object:

```json
{
  "timestamp": "2026-02-20T14:10:00.123456+00:00",
  "level": "INFO",
  "logger": "algomentor.core.agent_service",
  "request_id": "a1b2c3d4-e5f6-...",
  "user_id": "123456789",
  "agent": "AgentService",
  "stage": "research",
  "duration_ms": 42310,
  "message": "Research complete"
}
```

Useful `jq` queries:

```bash
# All records for one request
cat algomentor.log | jq -r 'select(.request_id == "<uuid>")'

# All errors
cat algomentor-error.log | jq .

# Stage durations
cat algomentor.log | jq 'select(.duration_ms != null) | {stage, duration_ms}'
```

---

## Phase Activation

| Phase | Activates when | Adds |
|---|---|---|
| 1 | Always | LeetCode scraper, single-agent loop |
| 2 | `agent/subagents.py` importable | 5 specialised subagents |
| 3 | `memory/store.py` importable | Persistent memory, personalisation |

Startup banner: `[Phase 1 ✅  |  Phase 2 ✅  |  Phase 3 ✅]`

---

## Roadmap

- [ ] Async parallel subagent execution (ThreadPoolExecutor fan-out)
- [ ] WebSocket / SSE transport for browser front-end
- [ ] Redis-backed session store (multi-process scaling)
- [ ] Prometheus metrics endpoint (`/metrics`)
- [ ] LangSmith tracing integration
- [ ] Docker Compose deployment with log aggregation

# AlgoMentor

AI-powered algorithm tutor built in three progressive phases.

## Quick Start

```bash
# from the workspace root
cd algomentor
python main.py "Number of Islands"
```

Or interactively:
```bash
python main.py
AlgoMentor > Two Sum
AlgoMentor > quit
```

## Prerequisites

Add to `.env` (workspace root):
```
MISTRAL_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

## Architecture

```
Phase 1  ──  Single Agent  ──  LeetCode scraper + Tavily fallback
Phase 2  ──  7 Agents      ──  + similarity, pattern, solution, strategy subagents
Phase 3  ──  7 Agents      ──  + persistent memory / personalization
```

### Phase 1 — Core Reasoning Loop

| Component | File |
|---|---|
| CLI | `main.py` |
| Root Agent | `agent/deep_agent.py` |
| Prompts | `agent/prompts.py` |
| Tavily search | `tools/internet_search.py` |
| LeetCode scraper | `tools/leetcode_scraper.py` |
| Config | `config/settings.py` |

**Flow:**
```
User types problem → LeetCode scraper fetches statement
→ Agent explains + writes pseudocode
→ Human gate: "Generate code? Which language?"
→ Code produced
```

### Phase 2 — Multi-Agent Orchestration

New files added on top of Phase 1:

| Component | File |
|---|---|
| 5 Subagents | `agent/subagents.py` |
| Similarity tool | `tools/similarity.py` |
| Content extractor | `tools/content_extractor.py` |
| Pattern classifier | `skills/pattern_classifier.py` |
| Complexity analyser | `skills/complexity.py` |
| Example simulator | `skills/simulator.py` |
| Strategy ranker | `skills/ranking.py` |

**Agent graph:**
```
Root
 ├─ ProblemAcquisitionAgent   → fetches statement
 ├─ SimilarityAgent           → finds similar problems
 ├─ PatternAgent              → classifies BFS/DFS/DP/…
 ├─ SolutionMiningAgent       → mines approaches from web
 └─ StrategyOptimizationAgent → ranks + refines best strategy
```

All 5 subagents fire sequentially; Root synthesises the results.

### Phase 3 — Persistent Memory

New files added on top of Phase 2:

| Component | File |
|---|---|
| Memory schema | `memory/schema.py` |
| Memory store | `memory/store.py` |
| Memory tool | `tools/memory_store_tool.py` |

Memory persisted at: `memory/memory.json`

**What is remembered:**
- Problems solved + language used
- Pattern-level success/failure history
- Preferred language (auto-detected from usage)
- Recent topics
- Weak / strong patterns (for personalised nudges)

## File Tree

```
algomentor/
├── main.py
├── agent/
│   ├── deep_agent.py        # Root agent (all phases)
│   ├── prompts.py           # All system prompts
│   └── subagents.py         # Phase 2 subagents
├── tools/
│   ├── internet_search.py   # Tavily wrapper
│   ├── leetcode_scraper.py  # LeetCode GraphQL
│   ├── similarity.py        # Structural similarity scoring
│   ├── content_extractor.py # HTML → plain text fetcher
│   └── memory_store_tool.py # Phase 3 memory query tool
├── skills/
│   ├── pattern_classifier.py
│   ├── complexity.py
│   ├── simulator.py
│   └── ranking.py
├── memory/
│   ├── schema.py
│   └── store.py
└── config/
    └── settings.py
```

## Phase Activation

Phases activate automatically based on which modules are present:

| Phase | Activates when… |
|---|---|
| Phase 1 | Always (core files present) |
| Phase 2 | `agent/subagents.py` importable |
| Phase 3 | `memory/store.py` importable |

The startup banner shows: `[Phase 1 ✅ | Phase 2 ✅ | Phase 3 ✅]`

## Tests

**Test 1 — Number of Islands**
```
AlgoMentor > Number of Islands
# Expect: problem statement, intuition, BFS/DFS pseudocode
# Prompt: "Generate code? (yes/no)"
# Reply:  yes  →  Python solution produced
```

**Test 2 — DP problem**
```
AlgoMentor > Coin Change
# Expect: DP pattern detected, pseudocode, bottom-up approach ranked first
```

**Test 3 — Memory (Phase 3)**
```
# Solve "Number of Islands" twice
# Second run: agent mentions previous attempt in context
# Check: memory/memory.json updated with both sessions
```

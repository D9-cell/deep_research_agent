"""
Skill: ExampleSimulationSkill  (simulator.py)
Executes a simple step-by-step trace through a pseudocode-style algorithm
on a concrete input.  Used to produce an "intuition walkthrough" that makes
explanations tangible, especially for learners.

This is a symbolic/trace-based simulator — it does NOT execute arbitrary
Python code.  It understands a limited pseudocode vocabulary.
"""
from __future__ import annotations

import re
from typing import Any


# ── Trace entry ───────────────────────────────────────────────────────────────

class TraceStep:
    def __init__(self, step_no: int, description: str, state: dict | None = None) -> None:
        self.step_no = step_no
        self.description = description
        self.state = state or {}

    def to_dict(self) -> dict:
        return {
            "step": self.step_no,
            "description": self.description,
            "state": self.state,
        }


# ── Simulator ─────────────────────────────────────────────────────────────────

class ExampleSimulationSkill:
    """
    Produces a human-readable trace of a BFS/DFS algorithm on a small example.

    Supported pseudocode patterns (keyword-triggered):
        - BFS / level-order traversal on a grid or adjacency list
        - DFS / depth-first on a graph or grid
        - Two-pointer on a sorted array
        - Sliding window on an array

    If the pattern is not recognised, falls back to a generic step list.

    Usage:
        skill = ExampleSimulationSkill()
        trace = skill.simulate(
            pattern="BFS",
            example_input=[[1,1,1],[0,1,0],[1,1,1]],
            description="Number of Islands – count connected components"
        )
    """

    def simulate(
        self,
        pattern: str,
        example_input: Any,
        description: str = "",
    ) -> dict:
        """
        Simulate `pattern` on `example_input`.

        Returns:
            {
                "pattern": str,
                "input":   any,
                "trace":   list[{step, description, state}],
                "result":  any,
                "note":    str
            }
        """
        p = pattern.upper()

        dispatcher = {
            "BFS": self._simulate_bfs,
            "DFS": self._simulate_dfs,
            "TWO POINTERS": self._simulate_two_pointers,
            "TWO_POINTERS": self._simulate_two_pointers,
            "SLIDING WINDOW": self._simulate_sliding_window,
            "SLIDING_WINDOW": self._simulate_sliding_window,
        }

        fn = dispatcher.get(p, self._simulate_generic)
        return fn(example_input, description)

    # ── BFS on grid ──────────────────────────────────────────────────────────

    def _simulate_bfs(self, grid: Any, description: str) -> dict:
        if not isinstance(grid, list) or not grid or not isinstance(grid[0], list):
            return self._simulate_generic(grid, description)

        from collections import deque

        rows, cols = len(grid), len(grid[0])
        visited = [[False] * cols for _ in range(rows)]
        trace: list[TraceStep] = []
        step = 0
        islands = 0

        for r in range(rows):
            for c in range(cols):
                if grid[r][c] == 1 and not visited[r][c]:
                    islands += 1
                    queue: deque = deque([(r, c)])
                    visited[r][c] = True
                    step += 1
                    trace.append(TraceStep(step, f"Start BFS island #{islands} from ({r},{c})", {"queue": [(r, c)]}))

                    while queue:
                        cr, cc = queue.popleft()
                        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nr, nc = cr + dr, cc + dc
                            if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] == 1 and not visited[nr][nc]:
                                visited[nr][nc] = True
                                queue.append((nr, nc))
                                step += 1
                                trace.append(TraceStep(step, f"  Visit ({nr},{nc}), queue size={len(queue)}"))

        return {
            "pattern": "BFS",
            "input": grid,
            "trace": [s.to_dict() for s in trace[:20]],  # cap at 20 steps
            "result": islands,
            "note": f"Found {islands} island(s). Trace capped at 20 steps.",
        }

    # ── DFS on grid ──────────────────────────────────────────────────────────

    def _simulate_dfs(self, grid: Any, description: str) -> dict:
        if not isinstance(grid, list) or not grid or not isinstance(grid[0], list):
            return self._simulate_generic(grid, description)

        rows, cols = len(grid), len(grid[0])
        visited = [[False] * cols for _ in range(rows)]
        trace: list[TraceStep] = []
        step_counter = [0]
        components = [0]

        def dfs(r: int, c: int) -> None:
            visited[r][c] = True
            step_counter[0] += 1
            if step_counter[0] <= 20:
                trace.append(TraceStep(step_counter[0], f"  DFS visit ({r},{c})"))
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] == 1 and not visited[nr][nc]:
                    dfs(nr, nc)

        for r in range(rows):
            for c in range(cols):
                if grid[r][c] == 1 and not visited[r][c]:
                    components[0] += 1
                    step_counter[0] += 1
                    trace.append(TraceStep(step_counter[0], f"Start DFS component #{components[0]} from ({r},{c})"))
                    dfs(r, c)

        return {
            "pattern": "DFS",
            "input": grid,
            "trace": [s.to_dict() for s in trace[:20]],
            "result": components[0],
            "note": f"Found {components[0]} component(s). Trace capped at 20 steps.",
        }

    # ── Two Pointers ─────────────────────────────────────────────────────────

    def _simulate_two_pointers(self, arr: Any, description: str) -> dict:
        if not isinstance(arr, list):
            return self._simulate_generic(arr, description)

        lo, hi = 0, len(arr) - 1
        trace: list[TraceStep] = []
        step = 0
        # Generic: find pair summing to target (default target = arr[0]+arr[-1] for demo)
        target = (arr[0] + arr[-1]) if arr else 0

        while lo < hi:
            step += 1
            s = arr[lo] + arr[hi]
            state = {"lo": lo, "hi": hi, "arr[lo]": arr[lo], "arr[hi]": arr[hi], "sum": s}
            if s == target:
                trace.append(TraceStep(step, f"Pair found: arr[{lo}]+arr[{hi}]={s}=target", state))
                break
            elif s < target:
                trace.append(TraceStep(step, f"sum={s}<target, move lo right", state))
                lo += 1
            else:
                trace.append(TraceStep(step, f"sum={s}>target, move hi left", state))
                hi -= 1

        return {
            "pattern": "Two Pointers",
            "input": {"array": arr, "target": target},
            "trace": [s.to_dict() for s in trace],
            "result": [arr[lo], arr[hi]] if lo < hi else "No pair",
            "note": "Demo target = arr[0]+arr[-1].",
        }

    # ── Sliding Window ────────────────────────────────────────────────────────

    def _simulate_sliding_window(self, arr: Any, description: str) -> dict:
        if not isinstance(arr, list):
            return self._simulate_generic(arr, description)

        k = max(2, min(3, len(arr) // 2))  # window size for demo
        window_sum = sum(arr[:k])
        max_sum = window_sum
        trace: list[TraceStep] = []

        trace.append(TraceStep(1, f"Initial window [0..{k-1}] sum={window_sum}", {"window": arr[:k], "sum": window_sum}))

        for i in range(k, len(arr)):
            window_sum += arr[i] - arr[i - k]
            max_sum = max(max_sum, window_sum)
            trace.append(
                TraceStep(
                    i - k + 2,
                    f"Slide to [{i-k+1}..{i}] sum={window_sum}",
                    {"window": arr[i - k + 1 : i + 1], "sum": window_sum, "max_so_far": max_sum},
                )
            )

        return {
            "pattern": "Sliding Window",
            "input": {"array": arr, "window_size": k},
            "trace": [s.to_dict() for s in trace],
            "result": max_sum,
            "note": f"Max sum of any sub-array of size {k}.",
        }

    # ── Generic fallback ──────────────────────────────────────────────────────

    def _simulate_generic(self, example_input: Any, description: str) -> dict:
        return {
            "pattern": "Generic",
            "input": example_input,
            "trace": [
                {"step": 1, "description": f"Input received: {example_input}", "state": {}},
                {"step": 2, "description": "Apply algorithm logic (pattern not natively simulated).", "state": {}},
                {"step": 3, "description": description or "No description provided.", "state": {}},
            ],
            "result": "See pseudocode for full trace.",
            "note": "Detailed simulation not available for this pattern; use BFS/DFS/TwoPointers/SlidingWindow.",
        }

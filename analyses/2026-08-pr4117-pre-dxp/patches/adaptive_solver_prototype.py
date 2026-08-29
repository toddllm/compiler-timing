"""Prototype adaptive-solver policy for the #4117 first follow-up.

Out-of-tree monkey patch applied by the harness (NOT a torch-spyre
source change). Reads the following env vars:

  ADAPTIVE_SOLVER_ENABLE=1
      Enables the policy. Default: not installed.

  ADAPTIVE_SOLVER_THRESHOLD_OPS=<int>
      Threshold in `len(graph.operations)` at the entry to
      `scratchpad_planning`. When configured solver is `cpsat` AND
      `n_operations > threshold`, fall back to a greedy allocator.
      Default: 512 (arbitrary starting point; test a range).

  ADAPTIVE_SOLVER_FALLBACK_RELAYOUT=<0|1>
      Whether the greedy fallback preserves LX relayout support.
      Since greedy already supports paired buffers and CP-SAT does
      not, "relayout ON in the fallback" changes behavior compared
      to "just use greedy as a cheaper equivalent". This flag exists
      so §5 (correctness A vs B) can test both explicitly.
      0 = disable relayout for the fallback compile (arm B: cleaner
          solver-only comparison).
      1 = leave relayout at whatever config.lx_planner_relayout
          currently says (arm A: greedy's normal behavior).
      Default: leave as-is (behavior A).

Uses solver-independent `len(graph.operations)` at the entry to
`scratchpad_planning`. Records the policy decision in the timing
recorder so downstream analysis can attribute compile time to the
right arm.
"""

from __future__ import annotations

import os


def install_adaptive_solver_prototype() -> None:
    """Install the adaptive-solver policy monkey patch. Idempotent."""
    if os.environ.get("ADAPTIVE_SOLVER_ENABLE") != "1":
        return
    try:
        from torch_spyre._inductor.scratchpad import allocator as _alloc
    except ImportError:
        return
    if getattr(_alloc, "_adaptive_solver_installed", False):
        return

    threshold = int(os.environ.get("ADAPTIVE_SOLVER_THRESHOLD_OPS", "512"))
    fallback_relayout_env = os.environ.get(
        "ADAPTIVE_SOLVER_FALLBACK_RELAYOUT", "as-is"
    )

    _orig_scratchpad_planning = _alloc.scratchpad_planning
    _orig_select_allocator = _alloc.select_allocator

    try:
        from torch_spyre._inductor import timing_recorder as _tr
    except ImportError:
        class _NullTr:
            @staticmethod
            def stage(name, **meta):
                class _Noop:
                    def __enter__(self):
                        return None
                    def __exit__(self, *a):
                        return False
                return _Noop()
        _tr = _NullTr()  # type: ignore[assignment]

    def _resolved_solver_name() -> str:
        try:
            from torch_spyre._inductor import config as _c
            return _c.layout_solver
        except Exception:
            return "<unknown>"

    def _patched_scratchpad_planning(graph, allocator=None):
        n_ops = 0
        try:
            n_ops = len(graph.operations)
        except Exception:
            pass

        configured = _resolved_solver_name()
        chosen = configured
        fell_back = False

        if allocator is None and configured == "cpsat" and n_ops > threshold:
            # Build the fallback greedy allocator via the same factory
            # select_allocator uses, but pin layout_solver='greedy' for the
            # duration and optionally toggle relayout to disentangle
            # solver-only cost vs relayout enablement.
            from torch_spyre._inductor import config as _c
            from torch_spyre._inductor.scratchpad.greedy_solver import (
                GreedyLayoutSolver,
            )

            with _tr.stage(
                "adaptive_solver_fallback",
                configured=configured, chosen="greedy",
                n_operations=n_ops, threshold=threshold,
                fallback_relayout=fallback_relayout_env,
            ):
                orig_solver = _c.layout_solver
                orig_relayout = _c.lx_planner_relayout
                _c.layout_solver = "greedy"
                if fallback_relayout_env == "0":
                    _c.lx_planner_relayout = False
                elif fallback_relayout_env == "1":
                    _c.lx_planner_relayout = True
                # "as-is" leaves whatever the caller set.
                try:
                    allocator = _orig_select_allocator()
                finally:
                    _c.layout_solver = orig_solver
                    _c.lx_planner_relayout = orig_relayout
            chosen = "greedy"
            fell_back = True

        with _tr.stage(
            "scratchpad_planning_entry",
            configured_solver=configured,
            chosen_solver=chosen,
            n_operations=n_ops,
            threshold=threshold,
            fell_back=fell_back,
        ):
            return _orig_scratchpad_planning(graph, allocator=allocator)

    _alloc.scratchpad_planning = _patched_scratchpad_planning
    _alloc._adaptive_solver_installed = True


__all__ = ["install_adaptive_solver_prototype"]

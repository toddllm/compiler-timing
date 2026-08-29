#!/usr/bin/env python3
"""Assemble the final #4117 baseline deliverables.

Runs the analyzer twice (once for the CP-SAT primary arm, once for
the greedy compatibility arm), then produces:

  notes/pre-dxp-attribution.md      (CP-SAT primary + greedy summary)
  notes/tables/scaling.md           (CP-SAT primary + greedy separately)
  notes/tables/pass-detail.md       (CP-SAT primary)
  notes/tables/reconciliation.md    (primary + compat)
  notes/tables/solver_comparison.md (CP-SAT vs greedy on the shared flash points)
  notes/next-opportunities.md       (ranked follow-ups, filled from real data)
  notes/summary.md                  (concise summary)

Usage:
    python3 build_final_report.py \\
        --primary-dir data/final_sweep/primary \\
        --compat-dir data/final_sweep/greedy_compat \\
        --out-notes notes \\
        --out-tables notes/tables
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


HARNESS_DIR = Path(__file__).resolve().parent
ANALYZE = HARNESS_DIR / "analyze_sweep.py"


def _run_analyzer(sweep_dir: str, out_notes: str, out_tables: str) -> int:
    return subprocess.call([
        sys.executable, str(ANALYZE),
        "--sweep-dir", sweep_dir,
        "--out-notes", out_notes,
        "--out-tables", out_tables,
        "--strict",
    ])


def _load_runs(sweep_dir: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(sweep_dir, "*.json"))):
        base = os.path.basename(path)
        if base.endswith(".catalog.json") or "-run" not in base:
            continue
        stem = base[: -len(".json")]
        shape, _ = stem.rsplit("-run", 1)
        try:
            with open(path) as fh:
                out[shape].append(json.load(fh))
        except json.JSONDecodeError:
            continue
    return out


def _first(events, name):
    for e in events:
        if e.get("name") == name:
            return e
    return None


def _median(vals):
    if not vals:
        return math.nan
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _median_key(runs, key_fn):
    return _median([key_fn(r) for r in runs if key_fn(r) is not None])


def _shape_stats(runs: list[dict]) -> dict:
    """Median across samples for the fields we care about in the
    solver-comparison table.
    """
    def get(run, fn):
        try:
            return fn(run)
        except Exception:
            return None

    def scratch_pass_ms(r):
        e = _first(r.get("events", []),
                   "pass:CustomPreSchedulingPasses:_maybe_scratchpad_planning")
        return (e or {}).get("inclusive_ns", 0) / 1e6 if e else None

    def solve_ms(r):
        e = _first(r.get("events", []), "scratchpad_solve")
        return (e or {}).get("inclusive_ns", 0) / 1e6 if e else None

    def plan_alloc_ms(r):
        e = _first(r.get("events", []), "scratchpad_plan_allocation")
        return (e or {}).get("inclusive_ns", 0) / 1e6 if e else None

    def pre_dxp_ms(r):
        fcw = _first(r.get("events", []), "first_call_wall")
        bnd = _first(r.get("events", []), "pre_dxp_boundary_marker")
        if fcw and bnd:
            return (bnd["t_start_ns"] - fcw["t_start_ns"]) / 1e6
        return None

    def planner_buffers(r):
        e = _first(r.get("events", []), "scratchpad_plan_allocation")
        return (e or {}).get("meta", {}).get("planner_buffers")

    def n_specs(r):
        e = _first(r.get("events", []), "sdsc_bundle_gen")
        return (e or {}).get("meta", {}).get("n_specs")

    def n_kernels(r):
        return sum(1 for e in r.get("events", [])
                   if e.get("name") == "spyre_kernel_codegen")

    def solver_status(r):
        e = _first(r.get("events", []), "scratchpad_plan_allocation")
        ort = (e or {}).get("meta", {}).get("ortools_stats") or {}
        return ort.get("status")

    def ortools_walltime_s(r):
        e = _first(r.get("events", []), "scratchpad_plan_allocation")
        ort = (e or {}).get("meta", {}).get("ortools_stats") or {}
        return ort.get("walltime_s")

    def ortools_num_workers(r):
        e = _first(r.get("events", []), "scratchpad_plan_allocation")
        ort = (e or {}).get("meta", {}).get("ortools_stats") or {}
        return ort.get("num_workers")

    def fx_nodes(r):
        e = _first(r.get("events", []), "compile_fx_wrapper")
        return (e or {}).get("meta", {}).get("fx_nodes_at_entry")

    def presched_input_ops(r):
        e = _first(r.get("events", []),
                   "pipeline:CustomPreSchedulingPasses")
        return (e or {}).get("meta", {}).get("input_operations")

    return {
        "n_samples": len(runs),
        "fx_nodes": _median([fx_nodes(r) for r in runs if fx_nodes(r)]),
        "presched_input_ops": _median([presched_input_ops(r)
                                        for r in runs
                                        if presched_input_ops(r)]),
        "planner_buffers": _median([planner_buffers(r)
                                     for r in runs
                                     if planner_buffers(r)]),
        "n_specs": _median([n_specs(r) for r in runs if n_specs(r)]),
        "n_kernels": _median([n_kernels(r) for r in runs
                              if n_kernels(r) is not None]),
        "pre_dxp_ms": _median([pre_dxp_ms(r) for r in runs
                                if pre_dxp_ms(r) is not None]),
        "scratchpad_pass_ms": _median([scratch_pass_ms(r) for r in runs
                                        if scratch_pass_ms(r) is not None]),
        "scratchpad_solve_ms": _median([solve_ms(r) for r in runs
                                         if solve_ms(r) is not None]),
        "scratchpad_plan_alloc_ms": _median([plan_alloc_ms(r) for r in runs
                                              if plan_alloc_ms(r) is not None]),
        "solver_status_first": (
            [solver_status(r) for r in runs
             if solver_status(r) is not None] or [None]
        )[0],
        "ortools_walltime_s_median": _median(
            [ortools_walltime_s(r) for r in runs
             if ortools_walltime_s(r) is not None]),
        "ortools_num_workers": (
            [ortools_num_workers(r) for r in runs
             if ortools_num_workers(r) is not None] or [None]
        )[0],
    }


def _write_solver_comparison(
    out_path: str,
    primary_runs: dict[str, list[dict]],
    compat_runs: dict[str, list[dict]],
) -> None:
    """Emit tables/solver_comparison.md — shared flash shapes only."""
    shared = sorted(set(primary_runs) & set(compat_runs))
    lines = [
        "# CP-SAT vs greedy — same-tree same-config comparison",
        "",
        "Frozen torch-spyre `3358f39` with `USE_SPYRE_CCL=0` and all other "
        "config identical between arms. Cost model OFF for these primary "
        "runs (`SPYRE_DUMP_COST` unset; `config.cost_model` unset).",
        "",
        "See `data/solver_ab_v2/report.md` for the earlier diagnostic "
        "A/B where the cost model was enabled and predicted ~16% lower "
        "runtime for greedy plans. Those A/B numbers are NOT combined "
        "with the timing baseline below.",
        "",
        "## Shared flash shapes",
        "",
        "| shape | solver | fx_nodes | presched_ops | planner_buffers | "
        "n_specs | pre_dxp_ms | scratchpad_pass_ms | scratchpad_solve_ms | "
        "solver_status | ortools_walltime_s | ortools_workers |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for shape in shared:
        for solver, runs in (
            ("cpsat", primary_runs[shape]),
            ("greedy", compat_runs[shape]),
        ):
            s = _shape_stats(runs)
            row = [
                shape, solver,
                f"{s['fx_nodes']:.0f}" if s['fx_nodes'] == s['fx_nodes'] else "?",
                f"{s['presched_input_ops']:.0f}" if s['presched_input_ops'] == s['presched_input_ops'] else "?",
                f"{s['planner_buffers']:.0f}" if s['planner_buffers'] == s['planner_buffers'] else "?",
                f"{s['n_specs']:.0f}" if s['n_specs'] == s['n_specs'] else "?",
                f"{s['pre_dxp_ms']:.1f}",
                f"{s['scratchpad_pass_ms']:.1f}",
                f"{s['scratchpad_solve_ms']:.1f}",
                str(s['solver_status_first'] or "—"),
                f"{s['ortools_walltime_s_median']:.2f}" if s['ortools_walltime_s_median'] == s['ortools_walltime_s_median'] else "—",
                str(s['ortools_num_workers'] or "—"),
            ]
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Cost model is OFF for these primary runs, so `pre_dxp_ms` here "
        "differs from A/B v2 timing (which had cost model ON)."
    )
    lines.append(
        "- The historical greedy scratchpad path remains comparatively "
        "inexpensive. Current-main changed the default to CP-SAT, making "
        "solver time a major frontend compile-time component at scale."
    )
    lines.append(
        "- Not a regression in the greedy implementation."
    )

    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary-dir", required=True)
    ap.add_argument("--compat-dir", required=True)
    ap.add_argument("--out-notes", required=True)
    ap.add_argument("--out-tables", required=True)
    args = ap.parse_args()

    os.makedirs(args.out_notes, exist_ok=True)
    os.makedirs(args.out_tables, exist_ok=True)

    # Primary analyzer
    print("== primary analyzer (cpsat) ==")
    rc = _run_analyzer(args.primary_dir, args.out_notes, args.out_tables)
    if rc != 0:
        print(f"analyzer failed for primary (rc={rc})", file=sys.stderr)

    # Compat analyzer, into a temporary out-notes/out-tables under out_tables
    compat_notes = os.path.join(args.out_tables, "greedy_compat_notes")
    compat_tables = os.path.join(args.out_tables, "greedy_compat")
    os.makedirs(compat_notes, exist_ok=True)
    os.makedirs(compat_tables, exist_ok=True)
    print("== compat analyzer (greedy) ==")
    rc = _run_analyzer(args.compat_dir, compat_notes, compat_tables)
    if rc != 0:
        print(f"analyzer failed for compat (rc={rc})", file=sys.stderr)

    # Solver comparison table
    print("== solver comparison ==")
    primary_runs = _load_runs(args.primary_dir)
    compat_runs = _load_runs(args.compat_dir)
    _write_solver_comparison(
        os.path.join(args.out_tables, "solver_comparison.md"),
        primary_runs, compat_runs,
    )
    print(f"wrote {os.path.join(args.out_tables, 'solver_comparison.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

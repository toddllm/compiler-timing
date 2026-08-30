#!/usr/bin/env python3
"""Analyze structural sweep for #4139 predictor-discovery study.

Reads:
  * data/structural_sweep/{shape}-{solver}.json for cpsat and greedy
    at each shape, all with SPYRE_LX_PLANNER_RELAYOUT=0.

Emits:
  * per-shape structural metrics (same universe for both arms)
  * greedy internal-work counters
  * CP-SAT model geometry
  * per-shape solve wall time (cpsat vs greedy) and which arm is
    cheaper
  * search across simple candidate predictors for one that
    correctly signs the solver-cost delta on all measured shapes

No classifier training — this is a manual search over source-motivated
candidates.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict


def load(path):
    with open(path) as fh:
        return json.load(fh)


def _first(events, name):
    for e in events:
        if e.get("name") == name:
            return e
    return None


def _sum(events, name):
    return sum(e.get("inclusive_ns", 0) for e in events if e.get("name") == name)


def _get(doc, key):
    events = doc.get("events") or []
    ev = _first(events, "scratchpad_plan_allocation")
    if not ev:
        return None
    return (ev.get("meta") or {}).get(key)


def _solve_ms(doc):
    return _sum(doc.get("events") or [], "scratchpad_solve") / 1e6


def _shape_from(fn):
    stem = fn[:-5] if fn.endswith(".json") else fn
    for suffix in ("-cpsat", "-greedy"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)], suffix[1:]
    return None, None


def load_sweep(data_dir):
    """Return {shape: {"cpsat": doc, "greedy": doc}}."""
    out = defaultdict(dict)
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".json") or fn.endswith(".catalog.json"):
            continue
        shape, solver = _shape_from(fn)
        if shape is None:
            continue
        try:
            out[shape][solver] = load(os.path.join(data_dir, fn))
        except Exception as e:
            print(f"skip {fn}: {e}", file=sys.stderr)
    return dict(out)


def _family_of(shape):
    if shape.startswith("flash-"):
        return "flash"
    if shape.startswith("mlp-"):
        return "mlp"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sweep = load_sweep(args.data_dir)
    shapes = sorted(sweep)

    lines = ["# Structural predictor study (#4139)", ""]
    lines.append(
        "Same planner-buffer universe both arms "
        "(`SPYRE_LX_PLANNER_RELAYOUT=0`). Structural metrics are pure "
        "functions of that shared buffer set; greedy work counters and "
        "CP-SAT model geometry are recorded per-solver."
    )
    lines.append("")

    # ---- Solve-time comparison ----
    lines.append("## Solve time — which solver wins")
    lines.append("")
    lines.append(
        "| shape | family | cpsat_solve_ms | greedy_solve_ms | winner | ratio (greedy/cpsat) |"
    )
    lines.append("|---|---|---:|---:|:---:|---:|")
    rows = []
    for shape in shapes:
        docs = sweep[shape]
        cs = docs.get("cpsat")
        gs = docs.get("greedy")
        if cs is None or gs is None:
            lines.append(f"| {shape} | {_family_of(shape)} | ? | ? | ? | ? |")
            continue
        c_ms = _solve_ms(cs)
        g_ms = _solve_ms(gs)
        winner = "greedy" if g_ms < c_ms else "cpsat"
        ratio = g_ms / c_ms if c_ms > 0 else float("inf")
        rows.append({"shape": shape, "family": _family_of(shape),
                     "cpsat_solve_ms": c_ms, "greedy_solve_ms": g_ms,
                     "winner": winner, "ratio": ratio,
                     "cpsat_doc": cs, "greedy_doc": gs})
        lines.append(
            f"| {shape} | {_family_of(shape)} | {c_ms:.1f} | {g_ms:.1f} | "
            f"{winner} | {ratio:.3f} |"
        )
    lines.append("")

    # ---- Structural metrics table ----
    lines.append("## Structural metrics (from the shared buffer universe)")
    lines.append("")
    struct_keys = [
        "planner_buffers", "placeable_buffers", "barred_buffers_prep",
        "n_transition_points", "max_live_count", "mean_live_count",
        "live_set_area", "max_live_bytes", "mean_live_bytes",
        "n_overlap_pairs", "overlap_density", "in_place_edges",
        "size_median", "size_p90", "size_max", "transition_x_placeable",
    ]
    lines.append("| shape | " + " | ".join(struct_keys) + " |")
    lines.append("|---" + "|---:" * len(struct_keys) + "|")
    for r in rows:
        sm = (_get(r["cpsat_doc"], "structural_metrics") or {})
        def _fmt(v):
            if v is None:
                return "?"
            if isinstance(v, float):
                return f"{v:.3f}" if v < 1000 else f"{v:.1f}"
            return str(v)
        lines.append(
            f"| {r['shape']} | " +
            " | ".join(_fmt(sm.get(k)) for k in struct_keys) + " |"
        )
    lines.append("")

    # ---- Greedy internal work ----
    lines.append("## Greedy internal work counters")
    lines.append("")
    greedy_keys = [
        "n_find_free_block_calls", "sum_live_set_size_entering_find",
        "max_live_set_size_entering_find", "n_try_allocate_one_calls",
        "n_in_place_parent_probes", "n_in_place_reuses",
        "n_try_deallocate_calls", "n_occupied_spans_calls",
        "sum_usage_entering_occupied_spans", "n_transition_times",
        "n_alloc_transition_iterations",
    ]
    lines.append("| shape | " + " | ".join(greedy_keys) + " |")
    lines.append("|---" + "|---:" * len(greedy_keys) + "|")
    for r in rows:
        gc = (_get(r["greedy_doc"], "greedy_counters") or {})
        lines.append(
            f"| {r['shape']} | " +
            " | ".join(str(gc.get(k, "?")) for k in greedy_keys) + " |"
        )
    lines.append("")

    # ---- CP-SAT model geometry ----
    lines.append("## CP-SAT model geometry")
    lines.append("")
    cpsat_keys = [
        "num_variables", "num_constraints", "num_no_overlap_2d",
        "num_no_overlap", "num_interval", "proto_bytes",
        "num_tensors", "num_forced_reasons",
    ]
    solve_keys = ["walltime_s", "num_branches", "num_conflicts",
                  "num_booleans"]
    lines.append(
        "| shape | " + " | ".join(cpsat_keys) + " | " +
        " | ".join(solve_keys) + " |"
    )
    lines.append("|---" + "|---:" * (len(cpsat_keys) + len(solve_keys)) + "|")
    for r in rows:
        cd = r["cpsat_doc"]
        ev = _first(cd.get("events") or [], "scratchpad_plan_allocation")
        m = (ev.get("meta") if ev else {}) or {}
        ms = m.get("cpsat_model_size") or {}
        solves = m.get("ortools_all_solves") or [{}]
        s = solves[0] if solves else {}
        lines.append(
            f"| {r['shape']} | " +
            " | ".join(str(ms.get(k, "?")) for k in cpsat_keys) + " | " +
            " | ".join(str(s.get(k, "?")) for k in solve_keys) + " |"
        )
    lines.append("")

    # ---- Simple predictor search ----
    lines.append("## Simple predictor candidates")
    lines.append("")
    lines.append(
        "Predictors evaluated: pick a structural quantity that "
        "separates flash-wins-greedy from mlp-wins-cpsat. For each "
        "shape, compute the predictor and its sign relative to "
        "the actual solver-cost sign (`greedy_solve < cpsat_solve`)."
    )
    lines.append("")

    def _sm(r, key):
        return ((_get(r["cpsat_doc"], "structural_metrics") or {}).get(key) or 0)

    def _gc(r, key):
        return ((_get(r["greedy_doc"], "greedy_counters") or {}).get(key) or 0)

    def _cpsat_vars(r):
        ev = _first(r["cpsat_doc"].get("events") or [],
                    "scratchpad_plan_allocation")
        m = (ev.get("meta") if ev else {}) or {}
        return (m.get("cpsat_model_size") or {}).get("num_variables") or 0

    candidates = [
        ("planner_buffers",              lambda r: _sm(r, "planner_buffers")),
        ("placeable_buffers",            lambda r: _sm(r, "placeable_buffers")),
        ("live_set_area",                lambda r: _sm(r, "live_set_area")),
        ("overlap_density",              lambda r: _sm(r, "overlap_density")),
        ("n_overlap_pairs",              lambda r: _sm(r, "n_overlap_pairs")),
        ("max_live_count",               lambda r: _sm(r, "max_live_count")),
        ("mean_live_count",              lambda r: _sm(r, "mean_live_count")),
        ("in_place_edges",               lambda r: _sm(r, "in_place_edges")),
        ("transition_x_placeable",       lambda r: _sm(r, "transition_x_placeable")),
        ("greedy_find_free_calls",       lambda r: _gc(r, "n_find_free_block_calls")),
        ("greedy_alloc_iterations",      lambda r: _gc(r, "n_alloc_transition_iterations")),
        ("greedy_occupied_span_calls",   lambda r: _gc(r, "n_occupied_spans_calls")),
        ("cpsat_num_variables",          lambda r: _cpsat_vars(r)),
        # Motivated ratios
        (
            "greedy_alloc_iter / cpsat_vars^2",
            lambda r: (
                _gc(r, "n_alloc_transition_iterations")
                / max(1, _cpsat_vars(r) ** 2)
            ),
        ),
        (
            "overlap_density x placeable_buffers",
            lambda r: (
                _sm(r, "overlap_density") * _sm(r, "placeable_buffers")
            ),
        ),
        (
            "live_set_area / planner_buffers",
            lambda r: (
                _sm(r, "live_set_area") / max(1, _sm(r, "planner_buffers"))
            ),
        ),
        (
            "n_overlap_pairs / n_transition_points",
            lambda r: (
                _sm(r, "n_overlap_pairs")
                / max(1, _sm(r, "n_transition_points"))
            ),
        ),
    ]

    lines.append(
        "For each candidate: show shape values and check whether "
        "**a single threshold** on that candidate correctly labels "
        "flash-wins-greedy vs mlp-wins-cpsat on this measured set."
    )
    lines.append("")
    lines.append("| candidate | " + " | ".join(r["shape"] for r in rows) +
                 " | threshold splits? |")
    lines.append("|---" + "|---:" * len(rows) + "|:---:|")
    for name, fn in candidates:
        vals = [fn(r) for r in rows]
        # Sort by value; check if there is any threshold that separates
        # winner=='greedy' from winner=='cpsat'.
        pairs = sorted(zip(vals, [r["winner"] for r in rows]))
        # A single threshold works if all one winner is below and the
        # other above (in either direction).
        ok_low_greedy = all(
            (pairs[i][1] == "greedy") == (pairs[i][0] < pairs[-1][0])
            for i in range(len(pairs))
        )
        # Simpler: does the sorted list yield a contiguous block of
        # each winner?
        winners_sorted = [w for _, w in pairs]
        n = len(winners_sorted)
        # find run boundaries
        distinct_runs = 1
        for i in range(1, n):
            if winners_sorted[i] != winners_sorted[i - 1]:
                distinct_runs += 1
        splits = "YES" if distinct_runs == 2 else "NO"
        def _fmt(v):
            if isinstance(v, float):
                return f"{v:.3g}"
            return str(v)
        lines.append(
            f"| {name} | " + " | ".join(_fmt(v) for v in vals) +
            f" | {splits} |"
        )
    lines.append("")

    with open(args.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compare CP-SAT vs greedy runs under SPYRE_LX_PLANNER_RELAYOUT=0.

Given a data directory with per-shape per-solver JSON dumps, emit:

  1. Planner-buffer input-signature comparison per shape:
     assert cpsat and greedy see identical buffer universes.
  2. Placement outcome comparison: placed/spilled counts and bytes,
     placed/spilled name sets (symmetric difference).
  3. CP-SAT phase decomposition per shape:
     wrap / add_inplace / add_core_div / add_no_overlap_2d /
     each Solve() / extract.
  4. CP-SAT model-size scaling:
     num_variables, num_constraints, num_no_overlap_2d, proto_bytes.
  5. Cross-shape empirical exponents for phase timings, for the
     shapes we ran.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict


def first_event(events, name):
    for e in events:
        if e.get("name") == name:
            return e
    return None


def sum_inclusive(events, name):
    return sum(e.get("inclusive_ns", 0) for e in events if e.get("name") == name)


def find_all(events, name):
    return [e for e in events if e.get("name") == name]


def load(path):
    with open(path) as fh:
        return json.load(fh)


def canonical_signature_hash(sig_list) -> str:
    """Stable hash over the planner_buffer_signature list."""
    if sig_list is None:
        return "<missing>"
    # Sort by name to make hash order-independent within a run (buffer
    # order is deterministic in prep — this is a defensive canonicalize).
    dumped = json.dumps(
        sorted(sig_list, key=lambda b: b.get("name", "")),
        sort_keys=True,
    )
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:16]


def load_arm(data_dir, solver):
    """Return {shape: {events, meta, sig_hash, sig_list}}."""
    out = {}
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(f"-{solver}.json") or fn.endswith(".catalog.json"):
            continue
        path = os.path.join(data_dir, fn)
        try:
            doc = load(path)
        except Exception as e:
            print(f"skip {path}: {e}", file=sys.stderr)
            continue
        shape = fn[: -len(f"-{solver}.json")]
        meta = doc.get("meta") or {}
        events = doc.get("events") or []
        plan_ev = first_event(events, "scratchpad_plan_allocation")
        plan_meta = (plan_ev.get("meta") or {}) if plan_ev else {}
        sig = plan_meta.get("planner_buffer_signature")
        out[shape] = {
            "events": events,
            "meta": meta,
            "plan_meta": plan_meta,
            "sig_list": sig,
            "sig_hash": canonical_signature_hash(sig),
            "resolved_solver": (
                (meta.get("resolved_spyre_config") or {}).get("layout_solver")
            ),
            "path": path,
        }
    return out


def signature_diff(a_sig, b_sig):
    if not a_sig or not b_sig:
        return "one or both missing"
    a_by_name = {b["name"]: b for b in a_sig}
    b_by_name = {b["name"]: b for b in b_sig}
    only_a = sorted(set(a_by_name) - set(b_by_name))
    only_b = sorted(set(b_by_name) - set(a_by_name))
    diff = []
    for name in sorted(set(a_by_name) & set(b_by_name)):
        if a_by_name[name] != b_by_name[name]:
            diff.append(name)
    return {
        "only_a": only_a[:10],
        "only_b": only_b[:10],
        "diverging_common": diff[:10],
        "n_only_a": len(only_a),
        "n_only_b": len(only_b),
        "n_diverging_common": len(diff),
    }


def phase_ms(events, name):
    return sum_inclusive(events, name) / 1e6


def cpsat_phase_row(events, plan_meta):
    solves = plan_meta.get("ortools_all_solves") or []
    return {
        "cpsat_plan_layout_generic_ms": phase_ms(events, "cpsat_plan_layout_generic"),
        "cpsat_add_inplace_relaxation_ms": phase_ms(events, "cpsat_add_inplace_relaxation"),
        "cpsat_add_core_division_ms": phase_ms(events, "cpsat_add_core_division"),
        "cpsat_add_no_overlap_2d_ms": phase_ms(events, "cpsat_add_no_overlap_2d"),
        "cpsat_extract_ms": phase_ms(events, "cpsat_extract"),
        "cpsat_solve_1_ms": phase_ms(events, "cpsat_solve[1]"),
        "cpsat_solve_2_ms": phase_ms(events, "cpsat_solve[2]"),
        "cpsat_solve_3_ms": phase_ms(events, "cpsat_solve[3]"),
        "cpsat_n_solves": len(solves),
        "cpsat_solves": solves,
        "cpsat_model_size": plan_meta.get("cpsat_model_size"),
    }


def scaling_slopes(rows, x_key, y_key):
    xs = []
    ys = []
    for r in rows:
        x = r.get(x_key)
        y = r.get(y_key)
        if x and y and x > 0 and y > 0:
            xs.append(x)
            ys.append(y)
    if len(xs) < 2:
        return math.nan
    lx = [math.log(v) for v in xs]
    ly = [math.log(v) for v in ys]
    n = len(xs)
    mx = sum(lx) / n
    my = sum(ly) / n
    num = sum((a - mx) * (b - my) for a, b in zip(lx, ly))
    den = sum((a - mx) ** 2 for a in lx)
    return num / den if den else math.nan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cpsat = load_arm(args.data_dir, "cpsat")
    greedy = load_arm(args.data_dir, "greedy")
    shapes = sorted(set(cpsat) & set(greedy))

    lines = ["# CP-SAT investigation report", ""]
    lines.append(
        "Frozen torch-spyre `3358f39` with **SPYRE_LX_PLANNER_RELAYOUT=0**. "
        "Under this config both cpsat and greedy call the same "
        "`_generate_buffers(graph)` path in `_prepare_buffers`, so the "
        "planner-buffer universe is identical between arms.")
    lines.append("")

    # ---- §1 canonical signature check ----
    lines.append("## Canonical planner-buffer signature (RELAYOUT=0)")
    lines.append("")
    lines.append("| shape | cpsat_sig_hash | greedy_sig_hash | match? | diff details |")
    lines.append("|---|---|---|---|---|")
    all_match = True
    for shape in shapes:
        a = cpsat[shape]
        b = greedy[shape]
        match = a["sig_hash"] == b["sig_hash"] and a["sig_hash"] != "<missing>"
        if not match:
            all_match = False
            d = signature_diff(a["sig_list"], b["sig_list"])
            d_desc = (
                f"only_a={d['n_only_a']} only_b={d['n_only_b']} "
                f"diverging_common={d['n_diverging_common']}"
            )
        else:
            d_desc = "—"
        lines.append(
            f"| {shape} | {a['sig_hash']} | {b['sig_hash']} | "
            f"{'YES' if match else 'NO'} | {d_desc} |"
        )
    lines.append("")
    if all_match:
        lines.append("**Invariant confirmed**: cpsat and greedy see the same "
                     "planner-buffer input universe under RELAYOUT=0.")
    else:
        lines.append("**Invariant FAILED** — see per-shape diff details above.")
    lines.append("")

    # ---- Placement outcome ----
    lines.append("## Placement outcome comparison")
    lines.append("")
    lines.append("| shape | solver | planner_buffers | eligible | placed | spilled | bytes_placed | bytes_spilled | scratchpad_pass_ms | solve_ms |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for shape in shapes:
        for solver, arm in (("cpsat", cpsat), ("greedy", greedy)):
            pm = arm[shape]["plan_meta"]
            events = arm[shape]["events"]
            scratch = phase_ms(events, "pass:CustomPreSchedulingPasses:_maybe_scratchpad_planning")
            solve = phase_ms(events, "scratchpad_solve")
            lines.append(
                f"| {shape} | {solver} | "
                f"{pm.get('planner_buffers')} | "
                f"{pm.get('eligible_buffers')} | "
                f"{pm.get('placed_in_lx')} | "
                f"{pm.get('spilled_from_lx')} | "
                f"{pm.get('bytes_placed_in_lx')} | "
                f"{pm.get('bytes_spilled_from_lx')} | "
                f"{scratch:.1f} | {solve:.1f} |"
            )
    lines.append("")

    # ---- Placed-set symmetric difference ----
    lines.append("## Placed-set symmetric difference (cpsat vs greedy)")
    lines.append("")
    lines.append("| shape | in cpsat only | in greedy only | agreed |")
    lines.append("|---|---:|---:|---:|")
    for shape in shapes:
        a_placed = set(
            tuple(pair)
            for pair in (cpsat[shape]["plan_meta"].get("placed_signature") or [])
        )
        b_placed = set(
            tuple(pair)
            for pair in (greedy[shape]["plan_meta"].get("placed_signature") or [])
        )
        only_a = len(a_placed - b_placed)
        only_b = len(b_placed - a_placed)
        agree = len(a_placed & b_placed)
        lines.append(f"| {shape} | {only_a} | {only_b} | {agree} |")
    lines.append("")

    # ---- CP-SAT phase decomposition ----
    lines.append("## CP-SAT phase decomposition (ms)")
    lines.append("")
    lines.append(
        "Per phase inside `CpSatLayoutSolver._plan_layout_generic → _run`. "
        "One sample per shape."
    )
    lines.append("")
    lines.append("| shape | plan_layout_generic | add_inplace | add_core_div | add_no_overlap_2d | solve[1] | solve[2] | solve[3] | extract |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    cpsat_rows = []
    for shape in shapes:
        events = cpsat[shape]["events"]
        pm = cpsat[shape]["plan_meta"]
        r = cpsat_phase_row(events, pm)
        r["shape"] = shape
        r["planner_buffers"] = pm.get("planner_buffers")
        cpsat_rows.append(r)
        lines.append(
            f"| {shape} | "
            f"{r['cpsat_plan_layout_generic_ms']:.1f} | "
            f"{r['cpsat_add_inplace_relaxation_ms']:.1f} | "
            f"{r['cpsat_add_core_division_ms']:.1f} | "
            f"{r['cpsat_add_no_overlap_2d_ms']:.1f} | "
            f"{r['cpsat_solve_1_ms']:.1f} | "
            f"{r['cpsat_solve_2_ms']:.1f} | "
            f"{r['cpsat_solve_3_ms']:.1f} | "
            f"{r['cpsat_extract_ms']:.1f} |"
        )
    lines.append("")

    # ---- CP-SAT per-Solve OR-Tools stats ----
    lines.append("## CP-SAT per-Solve() OR-Tools stats")
    lines.append("")
    lines.append("| shape | solve# | status | wall_s | branches | conflicts | booleans | bin_prop | int_prop | restarts |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for shape in shapes:
        pm = cpsat[shape]["plan_meta"]
        solves = pm.get("ortools_all_solves") or []
        for i, s in enumerate(solves, 1):
            lines.append(
                f"| {shape} | {i} | {s.get('status', '?')} | "
                f"{s.get('walltime_s', 0):.2f} | "
                f"{s.get('num_branches', 0)} | "
                f"{s.get('num_conflicts', 0)} | "
                f"{s.get('num_booleans', 0)} | "
                f"{s.get('num_binary_propagations', 0)} | "
                f"{s.get('num_integer_propagations', 0)} | "
                f"{s.get('num_restarts', 0)} |"
            )
    lines.append("")

    # ---- CP-SAT model size ----
    lines.append("## CP-SAT model size (post-build, single model for all Solve() calls)")
    lines.append("")
    lines.append("| shape | planner_buffers | num_variables | num_constraints | num_no_overlap_2d | num_no_overlap | num_interval | proto_bytes | num_tensors | num_forced_reasons |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for shape in shapes:
        pm = cpsat[shape]["plan_meta"]
        ms = pm.get("cpsat_model_size") or {}
        lines.append(
            f"| {shape} | "
            f"{pm.get('planner_buffers')} | "
            f"{ms.get('num_variables')} | "
            f"{ms.get('num_constraints')} | "
            f"{ms.get('num_no_overlap_2d')} | "
            f"{ms.get('num_no_overlap')} | "
            f"{ms.get('num_interval')} | "
            f"{ms.get('proto_bytes')} | "
            f"{ms.get('num_tensors')} | "
            f"{ms.get('num_forced_reasons')} |"
        )
    lines.append("")

    # ---- Scaling exponents across the measured shapes ----
    lines.append("## Empirical scaling exponents across the 4 measured shapes")
    lines.append("")
    lines.append("Log-log fit against planner_buffers. Only the shapes measured "
                 "here; not extrapolatable.")
    lines.append("")
    lines.append("| CP-SAT phase | slope (log-log vs planner_buffers) |")
    lines.append("|---|---:|")
    for phase in [
        "cpsat_plan_layout_generic_ms",
        "cpsat_add_inplace_relaxation_ms",
        "cpsat_add_core_division_ms",
        "cpsat_add_no_overlap_2d_ms",
        "cpsat_solve_1_ms",
        "cpsat_solve_2_ms",
        "cpsat_solve_3_ms",
        "cpsat_extract_ms",
    ]:
        slope = scaling_slopes(cpsat_rows, "planner_buffers", phase)
        lines.append(f"| {phase} | {slope:.2f} |")
    lines.append("")

    with open(args.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

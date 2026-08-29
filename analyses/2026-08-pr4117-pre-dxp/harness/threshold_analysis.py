#!/usr/bin/env python3
"""Threshold-prototype analysis for the first #4117 follow-up.

Reads:
  * baseline CP-SAT primary data (data/final_sweep/primary/)
  * arm-A greedy runs (data/threshold_data/arm_A_relayout_on/)
  * arm-B greedy runs (data/threshold_data/arm_B_relayout_off/)

Emits threshold_report.md with:
  * per-shape summary (n_operations, cpsat totals, greedy-A totals,
    greedy-B totals, kernel + spec differences, cost-model deltas)
  * per-threshold simulated total compile time under three policies:
      A. cpsat-only (baseline)
      B. cpsat + greedy-A fallback at threshold T (relayout normal)
      C. cpsat + greedy-B fallback at threshold T (relayout disabled)
  * threshold sweep table (savings vs baseline, % of shapes switched)
  * downstream graph difference between cpsat and greedy arms

Usage:
    python3 threshold_analysis.py \\
        --baseline-dir data/final_sweep/primary \\
        --greedy-a-dir data/threshold_data/arm_A_relayout_on \\
        --greedy-b-dir data/threshold_data/arm_B_relayout_off \\
        --out notes/tables/threshold_analysis.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict


def first(events, name):
    for e in events:
        if e.get("name") == name:
            return e
    return None


def sum_inclusive(events, name):
    return sum(e.get("inclusive_ns", 0) for e in events if e.get("name") == name)


def _load_json(path):
    with open(path) as fh:
        return json.load(fh)


def _shape_from(basename):
    """Extract shape stem from filenames like flash-512x1024-run1.json or
    flash-512x1024.json."""
    stem = basename
    if stem.endswith(".json"):
        stem = stem[:-5]
    if "-run" in stem:
        stem = stem.rsplit("-run", 1)[0]
    return stem


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def load_arm(data_dir, is_baseline=False):
    """Return {shape: {events_list, medians dict}}. baseline has 3
    samples per shape; other arms 1."""
    per_shape = defaultdict(list)
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".json") or fn.endswith(".catalog.json"):
            continue
        shape = _shape_from(fn)
        try:
            per_shape[shape].append(_load_json(os.path.join(data_dir, fn)))
        except Exception as e:
            print(f"skip {fn}: {e}", file=sys.stderr)
    out = {}
    for shape, runs in per_shape.items():
        pre_dxp_ms = []
        scratch_ms = []
        solve_ms = []
        n_ops = []
        planner_buffers = []
        n_specs = []
        n_kernels = []
        placed = []
        spilled = []
        placed_signatures = []
        for doc in runs:
            events = doc.get("events") or []
            fcw = first(events, "first_call_wall")
            bnd = first(events, "pre_dxp_boundary_marker")
            if fcw and bnd:
                pre_dxp_ms.append((bnd["t_start_ns"] - fcw["t_start_ns"]) / 1e6)
            scratch_ms.append(
                sum_inclusive(
                    events,
                    "pass:CustomPreSchedulingPasses:_maybe_scratchpad_planning",
                ) / 1e6
            )
            solve_ms.append(sum_inclusive(events, "scratchpad_solve") / 1e6)
            # n_operations captured at scratchpad_planning_entry when the
            # adaptive prototype was installed; else fall back to the
            # pass event's input_operations meta.
            entry = first(events, "scratchpad_planning_entry")
            if entry is not None:
                n_ops.append(entry.get("meta", {}).get("n_operations"))
            else:
                plan = first(events, "pipeline:CustomPreSchedulingPasses")
                if plan:
                    n_ops.append(plan.get("meta", {}).get("input_operations"))
            plan_alloc = first(events, "scratchpad_plan_allocation")
            if plan_alloc:
                pm = plan_alloc.get("meta") or {}
                planner_buffers.append(pm.get("planner_buffers"))
                placed.append(pm.get("placed_in_lx"))
                spilled.append(pm.get("spilled_from_lx"))
                placed_signatures.append(
                    tuple(sorted(
                        tuple(x) for x in
                        (pm.get("placed_signature") or [])
                    ))
                )
            bundle = first(events, "sdsc_bundle_gen")
            if bundle:
                n_specs.append(bundle.get("meta", {}).get("n_specs"))
            n_kernels.append(
                len([e for e in events
                     if e.get("name") == "spyre_kernel_codegen"])
            )
        out[shape] = {
            "n_samples": len(runs),
            "pre_dxp_ms": _median(pre_dxp_ms),
            "scratchpad_pass_ms": _median(scratch_ms),
            "scratchpad_solve_ms": _median(solve_ms),
            "n_operations": _median(n_ops),
            "planner_buffers": _median(planner_buffers),
            "placed_in_lx": _median(placed),
            "spilled_from_lx": _median(spilled),
            "n_specs": _median(n_specs),
            "n_kernels": _median(n_kernels),
            "placed_signatures": placed_signatures,
        }
    return out


def cross_arm_placed_diff(cpsat_sig, greedy_sig):
    """Two-sample comparison of placed_signature sets.

    Uses the first sample from each arm; different runs of the same
    solver can vary due to unattributed bundle nondeterminism, so
    treat any non-trivial difference as a signal.
    """
    if not cpsat_sig or not greedy_sig:
        return None
    a = set(cpsat_sig[0])
    b = set(greedy_sig[0])
    return {
        "only_cpsat": len(a - b),
        "only_greedy": len(b - a),
        "agreed": len(a & b),
    }


def simulate_threshold(shapes, baseline, greedy, threshold):
    """Return total_ms across all shapes if greedy is used when
    n_operations > threshold, else baseline.
    """
    total_baseline = 0.0
    total_adaptive = 0.0
    switched = 0
    for shape in shapes:
        b = baseline.get(shape)
        g = greedy.get(shape)
        if b is None or b["pre_dxp_ms"] is None:
            continue
        total_baseline += b["pre_dxp_ms"]
        n_ops = b.get("n_operations")
        use_greedy = (
            g is not None and g["pre_dxp_ms"] is not None
            and n_ops is not None and n_ops > threshold
        )
        if use_greedy:
            total_adaptive += g["pre_dxp_ms"]
            switched += 1
        else:
            total_adaptive += b["pre_dxp_ms"]
    return total_baseline, total_adaptive, switched


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-dir", required=True)
    ap.add_argument("--greedy-a-dir", required=True)
    ap.add_argument("--greedy-b-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    baseline = load_arm(args.baseline_dir, is_baseline=True)
    greedy_a = load_arm(args.greedy_a_dir)
    greedy_b = load_arm(args.greedy_b_dir)
    all_shapes = sorted(set(baseline) & set(greedy_a) & set(greedy_b))

    lines = ["# Threshold-prototype analysis (§3 + §4)", ""]
    lines.append(
        "Reads baseline CP-SAT primary data (3 cold samples per shape) "
        "and greedy-arm-A / greedy-arm-B data (1 sample per shape). "
        "Simulates the adaptive policy `if n_operations > T then greedy "
        "else cpsat` at several thresholds."
    )
    lines.append("")

    # ---- Per-shape numbers ----
    lines.append("## Per-shape summary")
    lines.append("")
    lines.append(
        "| shape | n_ops | cpsat_pre_dxp | greedyA_pre_dxp | greedyB_pre_dxp | "
        "cpsat_scratch | greedyA_scratch | greedyB_scratch | "
        "cpsat_n_specs | greedyA_n_specs | greedyB_n_specs | "
        "placed A vs cpsat | placed B vs cpsat |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"
    )
    for shape in all_shapes:
        b = baseline[shape]
        a = greedy_a[shape]
        c = greedy_b[shape]
        a_diff = cross_arm_placed_diff(
            b["placed_signatures"], a["placed_signatures"]
        )
        c_diff = cross_arm_placed_diff(
            b["placed_signatures"], c["placed_signatures"]
        )
        def _fmt_diff(d):
            if d is None:
                return "?"
            return f"only_c={d['only_cpsat']} only_g={d['only_greedy']} agreed={d['agreed']}"
        lines.append(
            f"| {shape} | "
            f"{b['n_operations']} | "
            f"{b['pre_dxp_ms']:.1f} | {a['pre_dxp_ms']:.1f} | {c['pre_dxp_ms']:.1f} | "
            f"{b['scratchpad_pass_ms']:.1f} | {a['scratchpad_pass_ms']:.1f} | {c['scratchpad_pass_ms']:.1f} | "
            f"{b['n_specs']} | {a['n_specs']} | {c['n_specs']} | "
            f"{_fmt_diff(a_diff)} | {_fmt_diff(c_diff)} |"
        )
    lines.append("")

    # ---- Threshold sweep ----
    lines.append("## Threshold sweep — simulated total compile time")
    lines.append("")
    lines.append(
        "Simulates the prototype policy `if config.layout_solver == 'cpsat' "
        "and n_operations > T, use greedy fallback; else keep cpsat`."
    )
    lines.append("")
    lines.append(
        "Two fallback flavors: **A** = greedy at pod-default "
        "SPYRE_LX_PLANNER_RELAYOUT=1 (greedy's normal behavior, "
        "includes LX-relayout paired-buffer expansion), **B** = "
        "SPYRE_LX_PLANNER_RELAYOUT=0 (solver-only fallback)."
    )
    lines.append("")
    thresholds = [0, 100, 200, 300, 500, 800, 1200, 2000, 3000, 10**9]
    lines.append(
        "| threshold_n_ops | baseline_total_s | armA_total_s | "
        "armA_savings_s | armA_savings_% | armA_switched | "
        "armB_total_s | armB_savings_s | armB_savings_% | armB_switched |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    n_shapes = len(all_shapes)
    for T in thresholds:
        b_total, a_total, a_switched = simulate_threshold(
            all_shapes, baseline, greedy_a, T
        )
        _, c_total, c_switched = simulate_threshold(
            all_shapes, baseline, greedy_b, T
        )
        a_sav = b_total - a_total
        c_sav = b_total - c_total
        lines.append(
            f"| {T} | {b_total/1000:.1f} | "
            f"{a_total/1000:.1f} | {a_sav/1000:.1f} | "
            f"{100*a_sav/b_total:.1f}% | {a_switched}/{n_shapes} | "
            f"{c_total/1000:.1f} | {c_sav/1000:.1f} | "
            f"{100*c_sav/b_total:.1f}% | {c_switched}/{n_shapes} |"
        )
    lines.append("")

    # ---- Downstream differences ----
    lines.append("## Downstream difference between arms")
    lines.append("")
    lines.append(
        "Same as the per-shape summary but focused on downstream "
        "differences that would ship: n_specs (kernels' spec count fed "
        "into SDSC) and placed-set overlap."
    )
    lines.append("")
    lines.append(
        "| shape | cpsat_n_specs | greedyA_n_specs | greedyB_n_specs | "
        "specs_delta_A | specs_delta_B | placed_agree_A | placed_agree_B |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---|---|")
    for shape in all_shapes:
        b = baseline[shape]
        a = greedy_a[shape]
        c = greedy_b[shape]
        a_diff = cross_arm_placed_diff(
            b["placed_signatures"], a["placed_signatures"]
        )
        c_diff = cross_arm_placed_diff(
            b["placed_signatures"], c["placed_signatures"]
        )

        def _delta(x, y):
            if x is None or y is None:
                return "?"
            return f"{y - x:+d}"

        def _agree_line(d):
            if d is None:
                return "?"
            return (
                f"only_cpsat={d['only_cpsat']} "
                f"only_greedy={d['only_greedy']} "
                f"agreed={d['agreed']}"
            )
        lines.append(
            f"| {shape} | {b['n_specs']} | {a['n_specs']} | {c['n_specs']} | "
            f"{_delta(b['n_specs'], a['n_specs'])} | "
            f"{_delta(b['n_specs'], c['n_specs'])} | "
            f"{_agree_line(a_diff)} | {_agree_line(c_diff)} |"
        )
    lines.append("")

    with open(args.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

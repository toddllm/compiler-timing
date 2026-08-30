#!/usr/bin/env python3
"""Analyze REAL adaptive-solver validation runs.

Reads:
  * data/adaptive_real_validation/baseline_cpsat/*.json   (3 samples/shape)
  * data/adaptive_real_validation/adaptive_greedy/*.json  (3 samples/shape)

Reports:
  * per-shape median pre-DXP for each arm and delta
  * chosen-solver check per arm (baseline: cpsat; adaptive: greedy fallback)
  * planner-buffer signature parity between arms
  * placed-set (name,size) parity
  * placed-set (name,size,address) parity — the address-level equivalence
    check that the earlier §1 evidence did NOT establish
  * spilled-set (name,size) parity
  * n_specs delta

Sample-level output makes cross-run bundle nondeterminism visible.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
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


def _sum_incl(events, name):
    return sum(e.get("inclusive_ns", 0) for e in events if e.get("name") == name)


def _sig(doc, key):
    events = doc.get("events") or []
    ev = _first(events, "scratchpad_plan_allocation")
    if not ev:
        return None
    return (ev.get("meta") or {}).get(key)


def _pre_dxp_ms(doc):
    events = doc.get("events") or []
    fcw = _first(events, "first_call_wall")
    bnd = _first(events, "pre_dxp_boundary_marker")
    if not (fcw and bnd):
        return None
    return (bnd["t_start_ns"] - fcw["t_start_ns"]) / 1e6


def _scratchpad_pass_ms(doc):
    return _sum_incl(
        doc.get("events") or [],
        "pass:CustomPreSchedulingPasses:_maybe_scratchpad_planning",
    ) / 1e6


def _solve_ms(doc):
    return _sum_incl(doc.get("events") or [], "scratchpad_solve") / 1e6


def _solver_used(doc):
    return _sig(doc, "solver_cls")


def _configured_solver(doc):
    return ((doc.get("meta") or {}).get("resolved_spyre_config") or {}).get(
        "layout_solver"
    )


def _n_specs(doc):
    ev = _first(doc.get("events") or [], "sdsc_bundle_gen")
    if not ev:
        return None
    return (ev.get("meta") or {}).get("n_specs")


def _n_operations(doc):
    ev = _first(doc.get("events") or [], "pipeline:CustomPreSchedulingPasses")
    if not ev:
        return None
    return (ev.get("meta") or {}).get("input_operations")


def load_arm(data_dir):
    """Return {shape: [docs]} for docs matching shape-runN.json."""
    out = defaultdict(list)
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".json") or fn.endswith(".catalog.json"):
            continue
        # shape-runN.json
        stem = fn[:-5]  # strip .json
        if "-run" not in stem:
            continue
        shape = stem.rsplit("-run", 1)[0]
        try:
            out[shape].append(load(os.path.join(data_dir, fn)))
        except Exception as e:
            print(f"skip {fn}: {e}", file=sys.stderr)
    return dict(out)


def compare_signatures(sigs_a, sigs_b):
    """Return worst-case (max symmetric-difference size) across all
    A x B pairings. Sample-level nondeterminism can move rows, so we
    report the min across pairings (best-case equivalence).
    """
    if not sigs_a or not sigs_b:
        return None
    results = []
    for a in sigs_a:
        for b in sigs_b:
            if a is None or b is None:
                results.append(None)
                continue
            sa, sb = set(map(tuple, a)), set(map(tuple, b))
            results.append((len(sa - sb), len(sb - sa), len(sa & sb)))
    concrete = [r for r in results if r is not None]
    if not concrete:
        return None
    # Report the pairing with minimal symmetric difference (best case)
    return min(concrete, key=lambda r: r[0] + r[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-dir", required=True)
    ap.add_argument("--adaptive-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    baseline = load_arm(args.baseline_dir)
    adaptive = load_arm(args.adaptive_dir)
    shapes = sorted(set(baseline) & set(adaptive))

    lines = ["# Adaptive-solver REAL validation", ""]
    lines.append(
        "3 cold samples per shape/arm. Both arms have configured "
        "`LAYOUT_SOLVER=cpsat`; the adaptive arm has "
        "`ADAPTIVE_SOLVER_THRESHOLD_OPS=500` set, so `scratchpad_planning` "
        "chooses the greedy fallback (with per-instance "
        "`enable_lx_relayout=False`) at every shape above threshold. "
        "Baseline is the exact existing CP-SAT-only behavior."
    )
    lines.append("")

    # ---- Chosen-solver sanity check ----
    lines.append("## Chosen solver per arm")
    lines.append("")
    lines.append(
        "| shape | n_ops | baseline configured | baseline chosen | "
        "adaptive configured | adaptive chosen |"
    )
    lines.append("|---|---:|---|---|---|---|")
    for shape in shapes:
        b0 = baseline[shape][0]
        a0 = adaptive[shape][0]
        lines.append(
            f"| {shape} | {_n_operations(b0)} | "
            f"{_configured_solver(b0)} | {_solver_used(b0)} | "
            f"{_configured_solver(a0)} | {_solver_used(a0)} |"
        )
    lines.append("")

    # ---- Per-shape median pre-DXP ----
    lines.append("## Per-shape median pre-DXP (ms)")
    lines.append("")
    lines.append(
        "| shape | n_ops | baseline_pre_dxp | adaptive_pre_dxp | "
        "delta_ms | delta_% | baseline_scratch | adaptive_scratch | "
        "baseline_solve | adaptive_solve |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    def _med(xs):
        xs = [x for x in xs if x is not None]
        return statistics.median(xs) if xs else None

    for shape in shapes:
        n_ops = _n_operations(baseline[shape][0])
        b_pre = _med([_pre_dxp_ms(d) for d in baseline[shape]])
        a_pre = _med([_pre_dxp_ms(d) for d in adaptive[shape]])
        b_scratch = _med([_scratchpad_pass_ms(d) for d in baseline[shape]])
        a_scratch = _med([_scratchpad_pass_ms(d) for d in adaptive[shape]])
        b_solve = _med([_solve_ms(d) for d in baseline[shape]])
        a_solve = _med([_solve_ms(d) for d in adaptive[shape]])
        delta = None
        delta_pct = None
        if b_pre is not None and a_pre is not None:
            delta = a_pre - b_pre
            delta_pct = 100 * delta / b_pre if b_pre else None
        lines.append(
            f"| {shape} | {n_ops} | "
            f"{b_pre:.1f} | {a_pre:.1f} | "
            f"{delta:+.1f} | {delta_pct:+.1f}% | "
            f"{b_scratch:.1f} | {a_scratch:.1f} | "
            f"{b_solve:.1f} | {a_solve:.1f} |"
        )
    lines.append("")

    # ---- Signature equivalence ----
    lines.append("## Signature equivalence (baseline vs adaptive)")
    lines.append("")
    lines.append(
        "Best-of-9 pairing (3 baseline samples × 3 adaptive samples). "
        "Cross-run bundle nondeterminism is documented in "
        "`notes/next-opportunities.md` — a nonzero delta here reflects "
        "either that or a real divergence."
    )
    lines.append("")
    lines.append(
        "| shape | planner_buffers ok | placed (name,size) diff | "
        "placed (name,size,address) diff | spilled (name,size) diff | "
        "baseline n_specs | adaptive n_specs | specs_delta |"
    )
    lines.append("|---|:---:|---|---|---|---:|---:|---:|")
    for shape in shapes:
        # planner-buffer count equality — cheap primary parity check
        b_pb = [_sig(d, "planner_buffers") for d in baseline[shape]]
        a_pb = [_sig(d, "planner_buffers") for d in adaptive[shape]]
        pb_ok = (
            None not in b_pb + a_pb
            and set(b_pb) == set(a_pb)
            and len(set(b_pb)) == 1
        )
        placed_ns = compare_signatures(
            [_sig(d, "placed_signature") for d in baseline[shape]],
            [_sig(d, "placed_signature") for d in adaptive[shape]],
        )
        placed_nsa = compare_signatures(
            [_sig(d, "placed_signature_with_address") for d in baseline[shape]],
            [_sig(d, "placed_signature_with_address") for d in adaptive[shape]],
        )
        spilled_ns = compare_signatures(
            [_sig(d, "spilled_signature") for d in baseline[shape]],
            [_sig(d, "spilled_signature") for d in adaptive[shape]],
        )

        def _fmt(t):
            if t is None:
                return "?"
            a, b, c = t
            if a == 0 and b == 0:
                return f"MATCH (agree={c})"
            return f"only_baseline={a} only_adaptive={b} agreed={c}"

        b_specs = _med([_n_specs(d) for d in baseline[shape]])
        a_specs = _med([_n_specs(d) for d in adaptive[shape]])
        delta_specs = None
        if b_specs is not None and a_specs is not None:
            delta_specs = int(a_specs - b_specs)
        lines.append(
            f"| {shape} | {'YES' if pb_ok else 'NO'} | "
            f"{_fmt(placed_ns)} | {_fmt(placed_nsa)} | {_fmt(spilled_ns)} | "
            f"{b_specs} | {a_specs} | {delta_specs:+d} |"
        )
    lines.append("")

    # ---- Sample-level pre-DXP variance ----
    lines.append("## Per-sample pre-DXP (for variance visibility)")
    lines.append("")
    lines.append("| shape | arm | run1 | run2 | run3 | median |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for shape in shapes:
        for label, arm in (("baseline", baseline), ("adaptive", adaptive)):
            vals = [_pre_dxp_ms(d) for d in arm[shape]]
            median = _med(vals)
            row_vals = [f"{v:.1f}" if v is not None else "?" for v in vals]
            while len(row_vals) < 3:
                row_vals.append("-")
            median_s = f"{median:.1f}" if median is not None else "?"
            lines.append(
                f"| {shape} | {label} | {row_vals[0]} | "
                f"{row_vals[1]} | {row_vals[2]} | {median_s} |"
            )
    lines.append("")

    with open(args.out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

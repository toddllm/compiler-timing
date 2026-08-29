#!/usr/bin/env python3
"""Phase 5 analyzer for the pre-DXP frontend investigation.

Reads a sweep directory produced by ``sweep_driver.sh`` (per-sample JSON
dumps from the ``timing_recorder``) and emits three artifacts under
the study's ``notes/`` and ``notes/tables/`` directories:

  * ``notes/pre-dxp-attribution.md`` — bucket-by-bucket wall-clock share
    at each shape, with median-of-N per row.
  * ``notes/tables/scaling.md`` — how each bucket grows as the graph
    grows, with fitted slopes on log-log.
  * ``notes/tables/pass-detail.md`` — top-K passes inside
    ``CustomPreSchedulingPasses`` per shape.

The recorder JSON schema (v1) is:

    {"meta": {..., "workload": ..., "Lq": ..., "Lk": ..., ...},
     "events": [{"name": ..., "ordinal": ..., "parent_ordinal": ...,
                 "inclusive_ns": ..., "self_ns": ..., "meta": {...}}, ...]}

Buckets (Phase 1 alignment):

  1. dynamo_aot         — everything before compile_fx_wrapper fires
                          (measured as: first_call_wall − compile_fx_wrapper
                          MINUS the SDSC/DXP total; then divided into
                          "pre-fx-wrapper prelude" using outer/inner
                          differences), reported as the residual against
                          first_call_wall for transparency.
  2. graphlowering_run  — upstream Inductor FX → IR lowering.
  3. custompresched     — CustomPreSchedulingPasses pipeline.
  4. scheduler_and_node — Scheduler.__init__, CustomPreFusionPasses,
                          upstream fusion, CustomPostFusionPasses.
                          Approximated as compile_to_fn − sdsc_total −
                          spyre_kernel_codegen − custompresched.
  5. spyre_kernel_codegen — per-kernel SpyreKernel.codegen_kernel calls.
  6. sdsc_bundle_gen    — generate_bundle inside SpyreAsyncCompile.sdsc.
  7. kernel_provenance  — build_kernel_provenance_descriptor.
  8. async_compile_wait — SpyreAsyncCompile.wait itself (excluding sdsc).

Anything not accounted for lands in ``unattributed``, printed
separately so it can't inflate a bucket by accident.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
from collections import defaultdict


def _load_runs(sweep_dir: str) -> dict[str, list[dict]]:
    """Group ``*.json`` under ``sweep_dir`` by workload-shape stem
    (everything before ``-runN.json``). Skips fidelity_report.json and
    other non-run files.
    """
    by: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(sweep_dir, "*.json"))):
        base = os.path.basename(path)
        if "-run" not in base or not base.endswith(".json"):
            continue
        stem = base[: -len(".json")]
        try:
            shape, _ = stem.rsplit("-run", 1)
        except ValueError:
            continue
        try:
            with open(path) as fh:
                by[shape].append(json.load(fh))
        except json.JSONDecodeError as exc:
            print(f"  skip {path}: {exc}")
    return by


def _events_by_name(run: dict, name: str) -> list[dict]:
    return [e for e in run.get("events", []) if e.get("name") == name]


def _first_event(run: dict, name: str) -> dict | None:
    events = _events_by_name(run, name)
    return events[0] if events else None


def _sum_events(run: dict, name: str, field: str = "inclusive_ns") -> int:
    return sum(e.get(field, 0) for e in _events_by_name(run, name))


def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else math.nan


def _bucket_ms(run: dict) -> dict[str, float]:
    """Return per-bucket inclusive milliseconds for one run."""
    ns = {}
    ns["first_call_wall"] = (
        _first_event(run, "first_call_wall") or {}
    ).get("inclusive_ns", 0)
    ns["compile_fx_wrapper"] = (
        _first_event(run, "compile_fx_wrapper") or {}
    ).get("inclusive_ns", 0)
    ns["graphlowering_run"] = _sum_events(run, "graphlowering_run")
    ns["graphlowering_compile_to_fn"] = _sum_events(
        run, "graphlowering_compile_to_fn"
    )
    ns["custompresched"] = _sum_events(run, "pipeline:CustomPreSchedulingPasses")
    ns["spyre_kernel_codegen"] = _sum_events(run, "spyre_kernel_codegen")
    ns["sdsc_total"] = _sum_events(run, "sdsc_total")
    ns["sdsc_bundle_gen"] = _sum_events(run, "sdsc_bundle_gen")
    ns["kernel_provenance"] = _sum_events(run, "kernel_provenance")
    ns["dxp_standalone"] = _sum_events(run, "dxp_standalone")
    ns["async_compile_wait"] = _sum_events(run, "async_compile_wait")

    # Derived: scheduler + fusion + wrapper codegen share of compile_to_fn.
    ns["scheduler_and_node"] = max(
        0,
        ns["graphlowering_compile_to_fn"]
        - ns["sdsc_total"]
        - ns["spyre_kernel_codegen"]
        - ns["custompresched"],
    )

    # Pre-DXP wall-clock target: everything upstream of dxp_standalone.
    ns["pre_dxp_total"] = max(0, ns["first_call_wall"] - ns["dxp_standalone"])
    # AOT/dynamo prelude before the compile_fx wrapper fires.
    ns["dynamo_aot_prelude"] = max(
        0,
        ns["first_call_wall"]
        - ns["compile_fx_wrapper"]
        - ns["dxp_standalone"]
        - ns["async_compile_wait"],
    )
    # Anything inside compile_fx_wrapper that no sub-bucket accounts for
    # (Dynamo/AOTAutograd inside the wrapper, non-Spyre codegen paths,
    # timing_recorder overhead itself). Non-negative by construction.
    accounted_in_wrapper = (
        ns["graphlowering_run"]
        + ns["custompresched"]
        + ns["scheduler_and_node"]
        + ns["spyre_kernel_codegen"]
        + ns["sdsc_total"]
    )
    ns["unattributed_wrapper"] = max(0, ns["compile_fx_wrapper"] - accounted_in_wrapper)

    return {k: v / 1e6 for k, v in ns.items()}


def _median_row(runs: list[dict]) -> dict[str, float]:
    per = [_bucket_ms(r) for r in runs]
    keys = per[0].keys()
    return {k: _median([r[k] for r in per]) for k in keys}


def _shape_meta(runs: list[dict]) -> dict:
    m = dict(runs[0].get("meta", {}))
    # Drop noisy fields for the report.
    for k in ("python_pid", "TORCHINDUCTOR_CACHE_DIR", "boundary_info"):
        m.pop(k, None)
    return m


def _fx_nodes(run: dict) -> int:
    ev = _first_event(run, "compile_fx_wrapper")
    if ev is None:
        return -1
    return int((ev.get("meta") or {}).get("fx_nodes_at_entry", -1))


def _presched_input_ops(run: dict) -> int:
    ev = _first_event(run, "pipeline:CustomPreSchedulingPasses")
    if ev is None:
        return -1
    return int((ev.get("meta") or {}).get("input_operations", -1))


def _per_pass_ms(run: dict) -> dict[str, float]:
    """Per-pass inclusive ms inside CustomPreSchedulingPasses."""
    prefix = "pass:CustomPreSchedulingPasses:"
    out: dict[str, float] = {}
    for e in run.get("events", []):
        name = e.get("name", "")
        if name.startswith(prefix):
            out[name[len(prefix):]] = e.get("inclusive_ns", 0) / 1e6
    return out


def _write_attribution(out_dir: str, medians: dict[str, dict[str, float]],
                       shape_meta: dict[str, dict], n_samples: dict[str, int]) -> str:
    """Bucket-by-bucket wall-clock share at each shape."""
    path = os.path.join(out_dir, "pre-dxp-attribution.md")
    lines: list[str] = []
    lines.append("# Pre-DXP time attribution")
    lines.append("")
    lines.append("Median-of-N cold samples, milliseconds. `pre_dxp_total` is `first_call_wall − dxp_standalone`.")
    lines.append("")
    header = [
        "shape",
        "N",
        "fx_nodes",
        "presched_ops",
        "first_call_wall",
        "pre_dxp_total",
        "dxp_standalone",
        "dynamo_aot_prelude",
        "graphlowering_run",
        "custompresched",
        "scheduler_and_node",
        "spyre_kernel_codegen",
        "sdsc_bundle_gen",
        "kernel_provenance",
        "async_compile_wait",
        "unattributed_wrapper",
    ]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for shape, med in sorted(medians.items()):
        meta = shape_meta[shape]
        n = n_samples[shape]
        fx_nodes = meta.get("_fx_nodes", -1)
        presched_ops = meta.get("_presched_input_ops", -1)
        row = [
            shape,
            str(n),
            str(fx_nodes),
            str(presched_ops),
            f"{med['first_call_wall']:.1f}",
            f"{med['pre_dxp_total']:.1f}",
            f"{med['dxp_standalone']:.1f}",
            f"{med['dynamo_aot_prelude']:.1f}",
            f"{med['graphlowering_run']:.1f}",
            f"{med['custompresched']:.1f}",
            f"{med['scheduler_and_node']:.1f}",
            f"{med['spyre_kernel_codegen']:.1f}",
            f"{med['sdsc_bundle_gen']:.1f}",
            f"{med['kernel_provenance']:.1f}",
            f"{med['async_compile_wait']:.1f}",
            f"{med['unattributed_wrapper']:.1f}",
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Per-shape percent-of-pre-DXP breakdown.
    lines.append("## Percent of pre-DXP total")
    lines.append("")
    pct_header = [
        "shape",
        "dynamo_aot_prelude",
        "graphlowering_run",
        "custompresched",
        "scheduler_and_node",
        "spyre_kernel_codegen",
        "sdsc_bundle_gen",
        "kernel_provenance",
        "async_compile_wait",
        "unattributed_wrapper",
    ]
    lines.append("| " + " | ".join(pct_header) + " |")
    lines.append("|" + "|".join(["---"] * len(pct_header)) + "|")
    for shape, med in sorted(medians.items()):
        denom = med["pre_dxp_total"] or 1.0
        row = [shape]
        for k in pct_header[1:]:
            row.append(f"{100.0 * med[k] / denom:.1f}%")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


def _fit_slope(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least-squares slope + intercept on log-log."""
    pts = [(x, y) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pts) < 2:
        return math.nan, math.nan
    lx = [math.log(x) for x, _ in pts]
    ly = [math.log(y) for _, y in pts]
    n = len(pts)
    mx = sum(lx) / n
    my = sum(ly) / n
    num = sum((a - mx) * (b - my) for a, b in zip(lx, ly))
    den = sum((a - mx) ** 2 for a in lx)
    if den == 0:
        return math.nan, math.nan
    m = num / den
    b = my - m * mx
    return m, b


def _write_scaling(out_dir: str, medians: dict[str, dict[str, float]],
                   shape_meta: dict[str, dict]) -> str:
    """Growth of each bucket vs graph size (fx_nodes)."""
    path = os.path.join(out_dir, "scaling.md")
    lines: list[str] = []
    lines.append("# Bucket scaling vs graph size")
    lines.append("")
    lines.append(
        "Log-log slope of bucket wall-clock (ms) against `fx_nodes_at_entry`, "
        "fit per workload family."
    )
    lines.append("")

    # Group shapes by workload family (prefix before the first '-').
    by_family: dict[str, list[str]] = defaultdict(list)
    for shape in medians:
        family = shape.split("-", 1)[0]
        by_family[family].append(shape)

    bucket_names = [
        "pre_dxp_total",
        "dynamo_aot_prelude",
        "graphlowering_run",
        "custompresched",
        "scheduler_and_node",
        "spyre_kernel_codegen",
        "sdsc_bundle_gen",
        "kernel_provenance",
        "async_compile_wait",
        "unattributed_wrapper",
    ]
    for family in sorted(by_family):
        shapes = sorted(by_family[family])
        xs = [shape_meta[s].get("_fx_nodes", -1) for s in shapes]
        if any(x <= 0 for x in xs):
            lines.append(f"## {family} — missing fx_nodes on some shapes, skipping")
            lines.append("")
            continue
        lines.append(f"## {family}  (n={len(shapes)} shapes)")
        lines.append("")
        lines.append("| bucket | slope (log-log) | ms at min fx_nodes | ms at max fx_nodes | ratio |")
        lines.append("|---|---|---|---|---|")
        min_x = min(xs)
        max_x = max(xs)
        for name in bucket_names:
            ys = [medians[s][name] for s in shapes]
            slope, _ = _fit_slope(xs, ys)
            ms_min = medians[shapes[xs.index(min_x)]][name]
            ms_max = medians[shapes[xs.index(max_x)]][name]
            ratio = (ms_max / ms_min) if ms_min > 0 else math.nan
            lines.append(
                f"| {name} | {slope:.2f} | {ms_min:.1f} | {ms_max:.1f} | "
                f"{ratio:.1f}× |"
            )
        lines.append("")
        lines.append(
            f"    fx_nodes range: {min_x} → {max_x}   "
            f"({max_x / min_x:.1f}× graph-size growth)"
        )
        lines.append("")

    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


def _write_pass_detail(out_dir: str, per_pass: dict[str, dict[str, float]],
                       shape_meta: dict[str, dict], top_k: int = 10) -> str:
    """Top-K passes inside CustomPreSchedulingPasses per shape."""
    path = os.path.join(out_dir, "pass-detail.md")
    lines: list[str] = []
    lines.append("# CustomPreSchedulingPasses — top passes per shape")
    lines.append("")
    lines.append(f"Top {top_k} passes by median inclusive ms.")
    lines.append("")
    for shape in sorted(per_pass):
        ps = sorted(per_pass[shape].items(), key=lambda kv: -kv[1])
        lines.append(f"## {shape}")
        lines.append("")
        lines.append("| rank | pass | ms |")
        lines.append("|---|---|---|")
        for i, (name, ms) in enumerate(ps[:top_k], 1):
            lines.append(f"| {i} | {name} | {ms:.1f} |")
        lines.append("")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-dir", required=True)
    ap.add_argument("--out-notes", required=True,
                    help="Directory to write pre-dxp-attribution.md")
    ap.add_argument("--out-tables", required=True,
                    help="Directory to write scaling.md and pass-detail.md")
    args = ap.parse_args()

    os.makedirs(args.out_notes, exist_ok=True)
    os.makedirs(args.out_tables, exist_ok=True)

    runs_by_shape = _load_runs(args.sweep_dir)
    if not runs_by_shape:
        print(f"no runs found under {args.sweep_dir}")
        return 2

    medians: dict[str, dict[str, float]] = {}
    per_pass_medians: dict[str, dict[str, float]] = {}
    shape_meta: dict[str, dict] = {}
    n_samples: dict[str, int] = {}
    for shape, runs in sorted(runs_by_shape.items()):
        medians[shape] = _median_row(runs)
        # Per-pass medians.
        per_pass_lists: dict[str, list[float]] = defaultdict(list)
        for r in runs:
            for k, v in _per_pass_ms(r).items():
                per_pass_lists[k].append(v)
        per_pass_medians[shape] = {k: _median(v) for k, v in per_pass_lists.items()}
        meta = _shape_meta(runs)
        meta["_fx_nodes"] = _median([_fx_nodes(r) for r in runs])
        meta["_presched_input_ops"] = _median([_presched_input_ops(r) for r in runs])
        shape_meta[shape] = meta
        n_samples[shape] = len(runs)

    attribution_path = _write_attribution(
        args.out_notes, medians, shape_meta, n_samples
    )
    scaling_path = _write_scaling(args.out_tables, medians, shape_meta)
    pass_detail_path = _write_pass_detail(args.out_tables, per_pass_medians, shape_meta)

    print(f"wrote {attribution_path}")
    print(f"wrote {scaling_path}")
    print(f"wrote {pass_detail_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Phase 5 analyzer for the pre-DXP frontend investigation.

Reads a sweep directory produced by ``sweep_driver.sh`` (per-sample JSON
dumps from ``timing_recorder``) and emits under the study's ``notes/``
and ``notes/tables/`` directories:

  * ``notes/pre-dxp-attribution.md`` — bucket-by-bucket wall-clock share
    at each shape, median-of-N per row.
  * ``notes/tables/scaling.md`` — how each bucket grows against
    natural per-bucket units.
  * ``notes/tables/pass-detail.md`` — top-K passes inside
    ``CustomPreSchedulingPasses`` per shape.
  * ``notes/tables/reconciliation.md`` — one row per run, showing
    residual, validation status, and any invalid runs.

## Accounting model (post-review corrections)

### Timeline sketch

    first_call_wall
      ├── compile_fx_wrapper                  ── produces compiled artifact
      │     ├── pre_compile_fx (residual)
      │     ├── graphlowering_run
      │     └── graphlowering_compile_to_fn
      │           ├── graphlowering_codegen
      │           │     ├── spyre_update_scheduler
      │           │     │     ├── recover_spyre_hints
      │           │     │     ├── pipeline:CustomPreSchedulingPasses
      │           │     │     │     ├── presched_pass_loop
      │           │     │     │     │     ├── pass:...:deadcode_elimination
      │           │     │     │     │     ├── ...
      │           │     │     │     ├── presched_cost_model
      │           │     │     │     ├── presched_cost_dump
      │           │     │     │     └── presched_finalize_work_division
      │           │     │     └── upstream_update_scheduler
      │           │     │           └── scheduler_init
      │           │     │                 ├── pipeline:CustomPreFusionPasses
      │           │     │                 ├── (upstream fusion)
      │           │     │                 └── pipeline:CustomPostFusionPasses
      │           │     └── scheduler_codegen
      │           │           └── (per kernel) spyre_kernel_codegen
      │           └── wrapper_codegen         (upstream PythonWrapperCodegen.generate)
      └── async_compile_wait                  ── during first invocation of compiled module
            └── (per kernel) sdsc_total
                  ├── sdsc_bundle_gen
                  ├── kernel_provenance
                  └── dxp_standalone          ── OUT OF SCOPE for pre-DXP total

`sdsc_total` fires from the generated wrapper module's initialization,
NOT from inside `compile_fx_wrapper`. `compile_fx_wrapper` and
`async_compile_wait` are TIME-DISJOINT siblings under
`first_call_wall`. Do not subtract SDSC from either.

### Primary pre-DXP total

Derived directly from timestamps:

    pre_dxp_total_ns = pre_dxp_boundary_marker.t_start_ns
                       - first_call_wall.t_start_ns

This is exactly "from first invocation start to the moment immediately
before the DXP subprocess would have run". The `first_call_wall`
event's `inclusive_ns` also includes a sentinel unwind, which is
reported separately as `sentinel_unwind_ms`.

If the run did not reach the boundary (`pre_dxp_boundary_reached=false`
in meta) the run is marked invalid and does not participate in the
aggregate tables.

### Bucket definitions

Where a bucket is directly bracketed, we use ``inclusive_ns``. Where a
bucket is derived, we compute it from parent inclusive minus the sum
of DIRECT-CHILDREN inclusive time. A negative derived interval is a
validation error, not silently clamped to zero.

| bucket | source |
|---|---|
| `pre_compile_fx` | `first_call_wall_self_ns` upstream of `compile_fx_wrapper`. Not "Dynamo/AOT" — neutrally named. |
| `graphlowering_run` | direct |
| `graphlowering_compile_to_fn_other` | `compile_to_fn.inclusive − sum(direct children we time)` |
| `graphlowering_codegen_other` | `graphlowering_codegen.inclusive − sum(direct children we time)` |
| `spyre_update_scheduler_other` | `spyre_update_scheduler.inclusive − children` |
| `recover_spyre_hints` | direct |
| `custompresched_total` | `pipeline:CustomPreSchedulingPasses.inclusive` (whole __call__ incl. cost model + finalize) |
| `presched_pass_loop` | direct (23-pass loop only) |
| `presched_cost_model` | direct |
| `presched_cost_dump` | direct |
| `presched_finalize_work_division` | direct |
| `upstream_update_scheduler` | direct (Scheduler ctor + fusion + post-fusion) |
| `scheduler_init` | direct (upstream Scheduler.__init__) |
| `scheduler_codegen` | direct |
| `spyre_kernel_codegen_total` | sum of per-kernel `spyre_kernel_codegen` events |
| `wrapper_codegen` | direct (upstream PythonWrapperCodegen.generate) |
| `async_compile_wait_other` | `async_compile_wait.inclusive − sum(sdsc_total events)` |
| `sdsc_bundle_gen_total` | sum |
| `kernel_provenance_total` | sum |
| `sentinel_unwind` | `first_call_wall.t_end − pre_dxp_boundary.t_start` |

Anything unclaimed is reported as `unattributed_pre_dxp` and included
in the reconciliation residual.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
from collections import defaultdict


# ---- schema/access helpers -------------------------------------------------

def _events_by_name(run: dict, name: str) -> list[dict]:
    return [e for e in run.get("events", []) if e.get("name") == name]


def _first_event(run: dict, name: str) -> dict | None:
    events = _events_by_name(run, name)
    return events[0] if events else None


def _sum_inclusive(run: dict, name: str) -> int:
    return sum(e.get("inclusive_ns", 0) for e in _events_by_name(run, name))


def _children_of(run: dict, parent_ordinal: int) -> list[dict]:
    return [e for e in run.get("events", []) if e.get("parent_ordinal") == parent_ordinal]


def _sum_children_inclusive(run: dict, ev: dict) -> int:
    return sum(c.get("inclusive_ns", 0) for c in _children_of(run, ev["ordinal"]))


def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else math.nan


# ---- reconciliation --------------------------------------------------------

class ValidationError(Exception):
    """Raised when a run fails hard reconciliation."""


def _validate_run(run: dict, source_path: str) -> dict:
    """Return a dict of per-run diagnostics, or raise ValidationError.

    Checks:
      - meta.pre_dxp_boundary_reached == True
      - meta.boundary_info.dxp_cmd_captured starts with 'dxp_standalone'
      - required top-level events exist
      - every event's children fit within inclusive_ns (no overlap escape)
      - no missing_parents / dangling ordinals
      - no unexpected_error in meta
    """
    meta = run.get("meta") or {}
    errors: list[str] = []

    if not meta.get("pre_dxp_boundary_reached", False):
        errors.append("pre_dxp_boundary_reached is false")
    binfo = meta.get("boundary_info") or {}
    cmd = binfo.get("dxp_cmd_captured") or []
    if not cmd or cmd[0] != "dxp_standalone":
        errors.append(f"captured DXP cmd wrong: {cmd!r}")
    if meta.get("unexpected_error"):
        errors.append(f"unexpected_error present: {meta['unexpected_error'][:200]}")

    required = ["first_call_wall", "compile_fx_wrapper", "pre_dxp_boundary_marker"]
    for name in required:
        if not _first_event(run, name):
            errors.append(f"required event missing: {name}")

    # Ordinal integrity + child ≤ parent inclusive.
    ords = {e.get("ordinal") for e in run.get("events", [])}
    for ev in run.get("events", []):
        parent = ev.get("parent_ordinal")
        if parent is not None and parent not in ords:
            errors.append(f"dangling parent_ordinal {parent} for {ev.get('name')}")
        # child sum ≤ parent inclusive
        s = _sum_children_inclusive(run, ev)
        if s > ev.get("inclusive_ns", 0) + 500_000:  # 0.5ms slack for clock jitter
            errors.append(
                f"children exceed parent for {ev.get('name')} "
                f"(children={s}ns, parent={ev.get('inclusive_ns')}ns)"
            )

    if errors:
        raise ValidationError(
            f"{source_path}:\n  " + "\n  ".join(errors)
        )
    return {"n_events": len(run.get("events", []))}


# ---- attribution -----------------------------------------------------------

def _bucket_ns(run: dict) -> dict[str, int]:
    """Return per-bucket inclusive/derived nanoseconds for one run.

    Any derived bucket that comes out negative raises ValidationError.
    """
    fcw = _first_event(run, "first_call_wall")
    cfw = _first_event(run, "compile_fx_wrapper")
    bnd = _first_event(run, "pre_dxp_boundary_marker")
    assert fcw and cfw and bnd

    ns: dict[str, int] = {}

    # Primary pre-DXP total from the boundary marker's absolute
    # start_ns minus first_call_wall's start_ns.
    ns["pre_dxp_total"] = bnd["t_start_ns"] - fcw["t_start_ns"]

    # Sentinel unwind: everything that happens after the boundary
    # inside first_call_wall (the raise + a couple of finallys).
    ns["sentinel_unwind"] = fcw["t_end_ns"] - bnd["t_start_ns"]

    # Direct-measurement buckets.
    ns["compile_fx_wrapper"] = cfw["inclusive_ns"]
    ns["graphlowering_run"] = _sum_inclusive(run, "graphlowering_run")
    ns["graphlowering_compile_to_fn"] = _sum_inclusive(run, "graphlowering_compile_to_fn")
    ns["graphlowering_codegen"] = _sum_inclusive(run, "graphlowering_codegen")
    ns["spyre_update_scheduler"] = _sum_inclusive(run, "spyre_update_scheduler")
    ns["recover_spyre_hints"] = _sum_inclusive(run, "recover_spyre_hints")
    ns["custompresched_total"] = _sum_inclusive(run, "pipeline:CustomPreSchedulingPasses")
    ns["presched_pass_loop"] = _sum_inclusive(run, "presched_pass_loop")
    ns["presched_cost_model"] = _sum_inclusive(run, "presched_cost_model")
    ns["presched_cost_dump"] = _sum_inclusive(run, "presched_cost_dump")
    ns["presched_finalize_work_division"] = _sum_inclusive(
        run, "presched_finalize_work_division"
    )
    ns["upstream_update_scheduler"] = _sum_inclusive(run, "upstream_update_scheduler")
    ns["scheduler_init"] = _sum_inclusive(run, "scheduler_init")
    ns["scheduler_codegen"] = _sum_inclusive(run, "scheduler_codegen")
    ns["custompref_fusion"] = _sum_inclusive(run, "pipeline:CustomPreFusionPasses")
    ns["custompost_fusion"] = _sum_inclusive(run, "pipeline:CustomPostFusionPasses")
    ns["spyre_kernel_codegen_total"] = _sum_inclusive(run, "spyre_kernel_codegen")
    ns["wrapper_codegen"] = _sum_inclusive(run, "wrapper_codegen")
    ns["async_compile_wait"] = _sum_inclusive(run, "async_compile_wait")
    ns["sdsc_total"] = _sum_inclusive(run, "sdsc_total")
    ns["sdsc_bundle_gen_total"] = _sum_inclusive(run, "sdsc_bundle_gen")
    ns["kernel_provenance_total"] = _sum_inclusive(run, "kernel_provenance")
    ns["dxp_standalone_total"] = _sum_inclusive(run, "dxp_standalone")

    # Derived residuals — must be non-negative. If not, that is a
    # nesting or accounting bug, not something to hide.
    def _derived(name: str, parent_ns: int, subtracted: list[str]) -> None:
        d = parent_ns - sum(ns[s] for s in subtracted)
        if d < -500_000:  # 0.5ms slack
            raise ValidationError(
                f"derived bucket '{name}' negative: {d}ns "
                f"(parent={parent_ns}, subtracted={subtracted})"
            )
        ns[name] = max(0, d)

    # compile_fx_wrapper "other" = wrapper − run − compile_to_fn
    _derived(
        "compile_fx_wrapper_other",
        ns["compile_fx_wrapper"],
        ["graphlowering_run", "graphlowering_compile_to_fn"],
    )
    # compile_to_fn interior "other" = compile_to_fn − codegen − wrapper_codegen (siblings)
    _derived(
        "compile_to_fn_other",
        ns["graphlowering_compile_to_fn"],
        ["graphlowering_codegen", "wrapper_codegen"],
    )
    # graphlowering_codegen "other" = codegen − update_scheduler − scheduler_codegen
    _derived(
        "graphlowering_codegen_other",
        ns["graphlowering_codegen"],
        ["spyre_update_scheduler", "scheduler_codegen"],
    )
    # spyre_update_scheduler "other" = − recover_hints − custompresched − upstream_update
    _derived(
        "spyre_update_scheduler_other",
        ns["spyre_update_scheduler"],
        [
            "recover_spyre_hints",
            "custompresched_total",
            "upstream_update_scheduler",
        ],
    )
    # scheduler_codegen "other" = codegen − kernel_codegen_total
    _derived(
        "scheduler_codegen_other",
        ns["scheduler_codegen"],
        ["spyre_kernel_codegen_total"],
    )
    # async_compile_wait "other" = wait − sdsc_total
    _derived(
        "async_compile_wait_other",
        ns["async_compile_wait"],
        ["sdsc_total"],
    )
    # Pre-compile-fx: from harness start to compile_fx_wrapper start. This
    # is Dynamo tracing + AOTAutograd prelude + anything else that runs
    # BEFORE the backend is invoked. Neutrally named because we do not
    # directly time Dynamo/AOT.
    ns["pre_compile_fx"] = cfw["t_start_ns"] - fcw["t_start_ns"]
    if ns["pre_compile_fx"] < 0:
        raise ValidationError(
            f"pre_compile_fx negative: {ns['pre_compile_fx']}ns "
            f"(compile_fx_wrapper starts before first_call_wall)"
        )

    # Gap between compile_fx completion and async_compile_wait: setup for
    # the first invocation of the compiled module (Python-level bookkeeping,
    # module import, etc). Also directly measured via timestamps.
    acw = _first_event(run, "async_compile_wait")
    if acw is not None:
        ns["between_compile_and_wait"] = acw["t_start_ns"] - cfw["t_end_ns"]
        if ns["between_compile_and_wait"] < 0:
            raise ValidationError(
                f"between_compile_and_wait negative: "
                f"{ns['between_compile_and_wait']}ns"
            )
    else:
        ns["between_compile_and_wait"] = 0

    return ns


def _residual(run: dict, ns: dict[str, int]) -> tuple[float, float]:
    """Return (residual_ns, residual_pct_of_pre_dxp) for one run.

    Residual = `pre_dxp_total` − sum(top-level buckets that span it).
    The top-level buckets that partition `pre_dxp_total` are:

      pre_compile_fx
        + compile_fx_wrapper
        + between_compile_and_wait
        + wait_pre_dxp (async_compile_wait region up to the boundary)

    where `wait_pre_dxp = boundary.t_start − async_compile_wait.t_start`.
    That last term already covers sdsc_bundle_gen + kernel_provenance +
    the prefix of dxp_standalone up to the sentinel; nothing else
    should be added.
    """
    fcw = _first_event(run, "first_call_wall")
    bnd = _first_event(run, "pre_dxp_boundary_marker")
    acw = _first_event(run, "async_compile_wait")
    assert fcw and bnd

    if acw is not None:
        wait_pre_dxp = bnd["t_start_ns"] - acw["t_start_ns"]
    else:
        # If wait was not measured (should not happen for a Spyre compile),
        # collapse this to zero so residual surfaces the missing region.
        wait_pre_dxp = 0
    ns["wait_pre_dxp"] = wait_pre_dxp

    accounted = (
        ns["pre_compile_fx"]
        + ns["compile_fx_wrapper"]
        + ns["between_compile_and_wait"]
        + wait_pre_dxp
    )
    residual_ns = ns["pre_dxp_total"] - accounted
    denom = ns["pre_dxp_total"] or 1
    return residual_ns, 100.0 * residual_ns / denom


# ---- I/O -------------------------------------------------------------------

def _load_runs(sweep_dir: str) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """Group ``*.json`` under sweep_dir by shape (everything before
    ``-runN.json``). Returns (runs_by_shape, paths_by_shape).
    """
    runs_by_shape: dict[str, list[dict]] = defaultdict(list)
    paths_by_shape: dict[str, list[str]] = defaultdict(list)
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
                runs_by_shape[shape].append(json.load(fh))
                paths_by_shape[shape].append(path)
        except json.JSONDecodeError as exc:
            print(f"  skip {path}: {exc}", file=sys.stderr)
    return runs_by_shape, paths_by_shape


def _per_pass_ns(run: dict) -> dict[str, int]:
    prefix = "pass:CustomPreSchedulingPasses:"
    out: dict[str, int] = {}
    for e in run.get("events", []):
        name = e.get("name", "")
        if name.startswith(prefix):
            out[name[len(prefix):]] = e.get("inclusive_ns", 0)
    return out


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


def _sched_input_nodes(run: dict) -> int:
    ev = _first_event(run, "scheduler_init")
    if ev is None:
        return -1
    return int((ev.get("meta") or {}).get("input_nodes", -1))


def _kernel_count(run: dict) -> int:
    return len(_events_by_name(run, "spyre_kernel_codegen"))


def _n_specs(run: dict) -> int:
    ev = _first_event(run, "sdsc_bundle_gen")
    if ev is None:
        return -1
    return int((ev.get("meta") or {}).get("n_specs", -1))


# ---- writers ---------------------------------------------------------------

_BUCKETS_MS = [
    "pre_compile_fx",
    "compile_fx_wrapper",
    "compile_fx_wrapper_other",
    "graphlowering_run",
    "graphlowering_compile_to_fn",
    "compile_to_fn_other",
    "graphlowering_codegen",
    "graphlowering_codegen_other",
    "spyre_update_scheduler",
    "spyre_update_scheduler_other",
    "recover_spyre_hints",
    "custompresched_total",
    "presched_pass_loop",
    "presched_cost_model",
    "presched_cost_dump",
    "presched_finalize_work_division",
    "upstream_update_scheduler",
    "scheduler_init",
    "custompref_fusion",
    "custompost_fusion",
    "scheduler_codegen",
    "scheduler_codegen_other",
    "spyre_kernel_codegen_total",
    "wrapper_codegen",
    "between_compile_and_wait",
    "wait_pre_dxp",
    "async_compile_wait",
    "async_compile_wait_other",
    "sdsc_bundle_gen_total",
    "kernel_provenance_total",
    "sentinel_unwind",
]

# The subset of top-level buckets that partition `pre_dxp_total`. Their
# sum should equal pre_dxp_total (± reconciliation_residual).
_ATTRIBUTION_BUCKETS = [
    "pre_compile_fx",
    "compile_fx_wrapper",
    "between_compile_and_wait",
    "wait_pre_dxp",
]


def _write_reconciliation(out_path: str, per_run: list[dict]) -> None:
    lines = [
        "# Per-run reconciliation",
        "",
        "One row per sample. `residual_pct` is the share of `pre_dxp_total` "
        "that no named bucket accounts for. Target: <1%. `invalid` runs are "
        "excluded from the aggregate tables.",
        "",
        "| shape | run | valid | pre_dxp_ms | residual_ms | residual_pct | reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in per_run:
        lines.append(
            "| {shape} | {run} | {valid} | {pre_dxp_ms:.1f} | "
            "{residual_ms:.2f} | {residual_pct:.2f}% | {reason} |".format(**row)
        )
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _write_attribution(
    out_path: str,
    shapes: list[str],
    medians: dict[str, dict[str, float]],
    shape_meta: dict[str, dict],
    n_samples: dict[str, int],
) -> None:
    lines = [
        "# Pre-DXP time attribution",
        "",
        "Median-of-N cold samples, milliseconds. `pre_dxp_total` is derived "
        "directly from timestamps as `pre_dxp_boundary_marker.t_start − "
        "first_call_wall.t_start`; nothing is subtracted from "
        "`compile_fx_wrapper` or `graphlowering_compile_to_fn`.",
        "",
    ]

    header = [
        "shape", "N", "fx_nodes", "presched_ops", "n_kernels", "n_specs",
        "pre_dxp_total",
        *_ATTRIBUTION_BUCKETS,
    ]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for shape in shapes:
        med = medians[shape]
        meta = shape_meta[shape]
        row = [
            shape, str(n_samples[shape]),
            str(meta["_fx_nodes"]), str(meta["_presched_input_ops"]),
            str(meta["_kernel_count"]), str(meta["_n_specs"]),
            f"{med['pre_dxp_total']:.1f}",
        ]
        row.extend(f"{med[b]:.1f}" for b in _ATTRIBUTION_BUCKETS)
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Percent of pre-DXP total")
    lines.append("")
    lines.append("| shape | " + " | ".join(_ATTRIBUTION_BUCKETS) + " |")
    lines.append("|" + "|".join(["---"] * (1 + len(_ATTRIBUTION_BUCKETS))) + "|")
    for shape in shapes:
        med = medians[shape]
        denom = med["pre_dxp_total"] or 1.0
        row = [shape]
        row.extend(f"{100 * med[b] / denom:.1f}%" for b in _ATTRIBUTION_BUCKETS)
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append("## Full bucket detail")
    lines.append("")
    lines.append(
        "Every measured bucket, including derived residuals. "
        "`sentinel_unwind` should be small (< 20 ms typically) — if it "
        "grows, that is stack-unwind overhead contaminating "
        "first_call_wall's inclusive time, and the primary `pre_dxp_total` "
        "column above already excludes it."
    )
    lines.append("")
    lines.append("| shape | " + " | ".join(_BUCKETS_MS) + " |")
    lines.append("|" + "|".join(["---"] * (1 + len(_BUCKETS_MS))) + "|")
    for shape in shapes:
        med = medians[shape]
        row = [shape]
        row.extend(f"{med[b]:.1f}" for b in _BUCKETS_MS)
        lines.append("| " + " | ".join(row) + " |")

    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _fit_slope(xs: list[float], ys: list[float]) -> tuple[float, float]:
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
    return num / den, my - (num / den) * mx


# Natural x-axis per bucket. Falls back to fx_nodes if the natural
# metric is not populated on any run.
_NATURAL_UNIT: dict[str, str] = {
    "graphlowering_run": "fx_nodes",
    "custompresched_total": "presched_ops",
    "presched_pass_loop": "presched_ops",
    "spyre_kernel_codegen_total": "kernels",
    "sdsc_bundle_gen_total": "n_specs",
    "kernel_provenance_total": "n_specs",
    "scheduler_init": "sched_nodes",
    "scheduler_codegen": "sched_nodes",
    "wrapper_codegen": "fx_nodes",
    "async_compile_wait_other": "kernels",
    # Defaults for anything else
}


def _write_scaling(
    out_path: str,
    shapes: list[str],
    medians: dict[str, dict[str, float]],
    shape_meta: dict[str, dict],
) -> None:
    lines = [
        "# Bucket scaling",
        "",
        "For each bucket, we fit a log-log slope against the natural "
        "per-bucket independent variable when available, else against "
        "`fx_nodes_at_entry`. Slope > 1 is a super-linear warning, not "
        "a gate. Per-unit drift (ms per natural unit) is reported "
        "alongside so linear buckets that dominate absolutely are still "
        "visible.",
        "",
    ]

    by_family: dict[str, list[str]] = defaultdict(list)
    for shape in shapes:
        family = shape.split("-", 1)[0]
        by_family[family].append(shape)

    for family in sorted(by_family):
        fam_shapes = by_family[family]
        lines.append(f"## {family} (n={len(fam_shapes)} shapes)")
        lines.append("")
        lines.append(
            "| bucket | unit | slope | ms/unit at max | ms at min | ms at max | ratio |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        buckets_to_scale = [
            "pre_dxp_total", "pre_compile_fx", "compile_fx_wrapper",
            "graphlowering_run", "graphlowering_compile_to_fn",
            "custompresched_total", "presched_pass_loop",
            "presched_cost_model", "presched_finalize_work_division",
            "upstream_update_scheduler", "scheduler_init", "scheduler_codegen",
            "spyre_kernel_codegen_total", "wrapper_codegen",
            "async_compile_wait_other", "sdsc_bundle_gen_total",
            "kernel_provenance_total",
        ]
        for name in buckets_to_scale:
            unit = _NATURAL_UNIT.get(name, "fx_nodes")
            xs = [shape_meta[s].get("_" + unit, -1) for s in fam_shapes]
            ys = [medians[s][name] for s in fam_shapes]
            if all(x <= 0 for x in xs):
                # Try fallback
                unit = "fx_nodes"
                xs = [shape_meta[s].get("_fx_nodes", -1) for s in fam_shapes]
            slope, _ = _fit_slope(xs, ys)
            # per-unit at max
            imax = xs.index(max(xs)) if xs else 0
            imin = xs.index(min(xs)) if xs else 0
            per_unit = ys[imax] / xs[imax] if xs and xs[imax] > 0 else math.nan
            ratio = (ys[imax] / ys[imin]) if ys[imin] > 0 else math.nan
            lines.append(
                f"| {name} | {unit} | {slope:.2f} | {per_unit:.4f} | "
                f"{ys[imin]:.1f} | {ys[imax]:.1f} | {ratio:.1f}× |"
            )
        lines.append("")

    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _write_pass_detail(
    out_path: str,
    shapes: list[str],
    per_pass_medians: dict[str, dict[str, float]],
    top_k: int = 12,
) -> None:
    lines = [
        "# CustomPreSchedulingPasses — top passes per shape",
        "",
        f"Top {top_k} passes by median inclusive ms.",
        "",
    ]
    for shape in shapes:
        ps = sorted(per_pass_medians[shape].items(), key=lambda kv: -kv[1])
        lines.append(f"## {shape}")
        lines.append("")
        lines.append("| rank | pass | ms |")
        lines.append("|---|---|---|")
        for i, (name, ms) in enumerate(ps[:top_k], 1):
            lines.append(f"| {i} | {name} | {ms:.1f} |")
        lines.append("")
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


# ---- main ------------------------------------------------------------------

def _median_row(ns_rows: list[dict[str, int]]) -> dict[str, float]:
    keys = ns_rows[0].keys()
    return {k: _median([r[k] for r in ns_rows]) / 1e6 for k in keys}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-dir", required=True)
    ap.add_argument("--out-notes", required=True)
    ap.add_argument("--out-tables", required=True)
    ap.add_argument(
        "--max-residual-pct", type=float, default=1.0,
        help="Runs with |residual| above this percent of pre_dxp_total "
             "are marked invalid and excluded from medians (default 1.0)."
    )
    ap.add_argument(
        "--strict", action="store_true",
        help="Fail (exit 4) if any run is invalid.",
    )
    args = ap.parse_args()

    os.makedirs(args.out_notes, exist_ok=True)
    os.makedirs(args.out_tables, exist_ok=True)

    runs_by_shape, paths_by_shape = _load_runs(args.sweep_dir)
    if not runs_by_shape:
        print(f"no runs found under {args.sweep_dir}", file=sys.stderr)
        return 2

    per_run_rows: list[dict] = []
    valid_ns_by_shape: dict[str, list[dict[str, int]]] = defaultdict(list)
    per_pass_by_shape: dict[str, list[dict[str, int]]] = defaultdict(list)
    shape_meta: dict[str, dict] = {}
    n_samples: dict[str, int] = {}
    any_invalid = False

    for shape, runs in sorted(runs_by_shape.items()):
        paths = paths_by_shape[shape]
        for run, path in zip(runs, paths):
            row = {
                "shape": shape,
                "run": os.path.basename(path).rsplit(".", 1)[0],
                "valid": "yes",
                "pre_dxp_ms": 0.0,
                "residual_ms": 0.0,
                "residual_pct": 0.0,
                "reason": "-",
            }
            try:
                _validate_run(run, path)
                ns = _bucket_ns(run)
                res_ns, res_pct = _residual(run, ns)
                row["pre_dxp_ms"] = ns["pre_dxp_total"] / 1e6
                row["residual_ms"] = res_ns / 1e6
                row["residual_pct"] = res_pct
                if abs(res_pct) > args.max_residual_pct:
                    row["valid"] = "no"
                    row["reason"] = (
                        f"|residual|={abs(res_pct):.2f}% > "
                        f"{args.max_residual_pct}%"
                    )
                    any_invalid = True
                else:
                    valid_ns_by_shape[shape].append(ns)
                    per_pass_by_shape[shape].append(_per_pass_ns(run))
            except ValidationError as e:
                row["valid"] = "no"
                row["reason"] = str(e).splitlines()[-1][:120]
                any_invalid = True
            except (AssertionError, KeyError) as e:
                row["valid"] = "no"
                row["reason"] = f"{type(e).__name__}: {e}"
                any_invalid = True
            per_run_rows.append(row)

        # Per-shape meta from any run (all should agree on graph size).
        first_valid = valid_ns_by_shape[shape][:1] and runs_by_shape[shape][0]
        example_run = runs_by_shape[shape][0]
        shape_meta[shape] = {
            "_fx_nodes": _fx_nodes(example_run),
            "_presched_ops": _presched_input_ops(example_run),
            "_presched_input_ops": _presched_input_ops(example_run),  # legacy alias
            "_sched_nodes": _sched_input_nodes(example_run),
            "_kernel_count": _kernel_count(example_run),
            "_n_specs": _n_specs(example_run),
        }
        n_samples[shape] = len(valid_ns_by_shape[shape])

    reconciliation_path = os.path.join(args.out_tables, "reconciliation.md")
    _write_reconciliation(reconciliation_path, per_run_rows)

    # Only shapes with ≥1 valid sample participate.
    valid_shapes = sorted(s for s, rows in valid_ns_by_shape.items() if rows)
    if not valid_shapes:
        print("no valid runs after validation — see reconciliation.md",
              file=sys.stderr)
        print(f"wrote {reconciliation_path}")
        return 4 if args.strict else 3

    medians: dict[str, dict[str, float]] = {}
    per_pass_medians: dict[str, dict[str, float]] = {}
    for shape in valid_shapes:
        medians[shape] = _median_row(valid_ns_by_shape[shape])
        # Per-pass median across valid runs.
        agg: dict[str, list[float]] = defaultdict(list)
        for pp in per_pass_by_shape[shape]:
            for k, v in pp.items():
                agg[k].append(v / 1e6)
        per_pass_medians[shape] = {k: _median(v) for k, v in agg.items()}

    attribution_path = os.path.join(args.out_notes, "pre-dxp-attribution.md")
    _write_attribution(
        attribution_path, valid_shapes, medians, shape_meta, n_samples
    )
    scaling_path = os.path.join(args.out_tables, "scaling.md")
    _write_scaling(scaling_path, valid_shapes, medians, shape_meta)
    pass_detail_path = os.path.join(args.out_tables, "pass-detail.md")
    _write_pass_detail(pass_detail_path, valid_shapes, per_pass_medians)

    print(f"wrote {attribution_path}")
    print(f"wrote {scaling_path}")
    print(f"wrote {pass_detail_path}")
    print(f"wrote {reconciliation_path}")
    if any_invalid:
        print("WARNING: at least one run was marked invalid; see reconciliation.md",
              file=sys.stderr)
        if args.strict:
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

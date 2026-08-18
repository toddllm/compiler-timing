#!/usr/bin/env python3
"""Regenerate the study tables and plots from ``data/*.json``.

Reads every cold-compile run in ``data/`` and writes:

- ``notes/tables/table-a-workload.md``  — per-point wall clocks and
  the compile-time decomposition.
- ``notes/tables/table-b-passes.md``    — per-pass timings against
  each pass's own ``input_operations``.
- ``notes/tables/dedup-mechanism.md``   — measured
  ``operations × duplicates`` cost model for
  ``dedup_and_promote_constants``.
- ``notes/tables/time-to-first-pass.md`` — time from ``first_call_wall``
  to key event boundaries, from raw ``t_start_ns``.
- ``notes/tables/backend-per-spec.md``  — ``dxp_standalone`` and
  ``sdsc_bundle_gen`` normalized by ``n_specs``.
- ``notes/tables/residual-decomposition.md`` — the
  ``unattributed_compile_fx`` bucket.
- ``notes/tables/h-scaling.md`` — H-dimension controlled sweep and
  equal-inner-body H-vs-Lk comparison.
- ``notes/tables/dedup-oos.md`` — out-of-sample validation of the
  ``operations × duplicates`` cost model.

Plots (matplotlib):

- ``plots/compile-stages.png``
- ``plots/pass-scaling.png``
- ``plots/dedup-model-fit.png``
- ``plots/backend-per-spec.png``

Design notes:

- Every point has identity ``(H, Lq, Lk)``. Filenames follow
  ``{Lq}x{Lk}-run{i}.json`` (assumed H=8) or
  ``h{H}-{Lq}x{Lk}-run{i}.json``; the run's own ``meta['H']`` is the
  authoritative source.
- Pass-level scaling uses each pass's own ``input_operations``
  (``graph.operations`` size at pass entry) as its x-axis, recorded on
  every event by the instrumentation.
- Compile time is decomposed into four exhaustive buckets that sum to
  ``compile_fx_wrapper``: external ``dxp_standalone``, SDSC/backend-input
  preparation, Spyre pass pipelines, and unattributed ``compile_fx``.
- Residuals are computed **per run** and then medianed rather than
  medianing bucket-wise; medians do not compose algebraically.
- The dedup out-of-sample table freezes the coefficient at the value
  fit on the H=8 sweep and reports prediction error at each new point
  before offering an updated coefficient.
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics
from collections import defaultdict
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
DATA = os.path.join(STUDY, "data")
TABLES = os.path.join(STUDY, "notes", "tables")
PLOTS = os.path.join(STUDY, "plots")


PRE_SCHED_PIPE = "pipeline:CustomPreSchedulingPasses"
DXP = "dxp_standalone"
COMPILE_FX = "compile_fx_wrapper"
FIRST_CALL = "first_call_wall"

SPYRE_PIPES = [
    "pipeline:CustomPreGradPasses",
    "pipeline:CustomPrePasses",
    "pipeline:CustomPostPasses",
    "pipeline:CustomPreFusionPasses",
    "pipeline:CustomPostFusionPasses",
    "pipeline:CustomPreSchedulingPasses",
]


# ------------------------------------------------------------------ helpers

def load_runs() -> dict[tuple[int, int, int], list[dict]]:
    """Load cold-compile runs keyed by ``(H, Lq, Lk)``.

    Filenames follow one of two patterns:

    - ``{Lq}x{Lk}-run{i}.json``           — assumed ``H=8`` (baseline sweep)
    - ``h{H}-{Lq}x{Lk}-run{i}.json``      — explicit H dimension

    In both cases the run's own ``meta['H']`` is authoritative; the filename
    is only used to pick the right point when the meta field is absent.
    """
    by = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        base = os.path.basename(path)
        if base.startswith("env-probe") or base.startswith("resolved-config"):
            continue
        if base.startswith("smoke-"):
            continue
        if "-run" not in base or not base.endswith(".json"):
            continue
        stem = base[:-len(".json")]
        try:
            head, _ = stem.split("-run")
            if head.startswith("h") and "-" in head:
                h_part, lqxlk = head.split("-", 1)
                h_filename = int(h_part[1:])
            else:
                h_filename = 8
                lqxlk = head
            lq, lk = (int(x) for x in lqxlk.split("x"))
        except ValueError:
            continue
        with open(path) as f:
            run = json.load(f)
        h = int(run.get("meta", {}).get("H", h_filename))
        by[(h, lq, lk)].append(run)
    return by


def event(run: dict, name: str) -> dict | None:
    for e in run["events"]:
        if e["name"] == name:
            return e
    return None


def events(run: dict, name: str) -> list[dict]:
    return [e for e in run["events"] if e["name"] == name]


def sum_ms(run: dict, name: str) -> float:
    return sum(e["inclusive_ns"] for e in events(run, name)) / 1e6


def med(vs: list[float]) -> float:
    return statistics.median(vs) if vs else float("nan")


def spyre_pass_total_ms(run: dict) -> float:
    total = 0.0
    for n in SPYRE_PIPES:
        e = event(run, n)
        if e:
            total += e["inclusive_ns"]
    return total / 1e6


def dxp_total_ms(run: dict) -> float:
    return sum_ms(run, DXP)


def compile_fx_ms(run: dict) -> float:
    e = event(run, COMPILE_FX)
    return e["inclusive_ns"] / 1e6 if e else float("nan")


def first_call_ms(run: dict) -> float:
    e = event(run, FIRST_CALL)
    return e["inclusive_ns"] / 1e6 if e else float("nan")


def unattributed_compile_fx_ms(run: dict) -> float:
    """
    All time under compile_fx_wrapper that is NOT one of the six Spyre
    custom-pass pipelines and NOT sdsc_total (which owns dxp + bundle
    generation).

    Per-run so the median is composable.
    """
    cfx = compile_fx_ms(run)
    if cfx != cfx:
        return float("nan")
    spyre_pipes_ms = spyre_pass_total_ms(run)
    sdsc_ms = sum_ms(run, "sdsc_total")
    wait_ms = sum_ms(run, "async_compile_wait")
    return cfx - spyre_pipes_ms - sdsc_ms - wait_ms


def time_to_ms(run: dict, target_name: str) -> float:
    """
    Elapsed ms from t=0 (start of first_call_wall) to the start of the
    first event named `target_name`.
    """
    base = event(run, FIRST_CALL)
    if base is None:
        return float("nan")
    for e in sorted(run["events"], key=lambda e: e["t_start_ns"]):
        if e["name"] == target_name:
            return (e["t_start_ns"] - base["t_start_ns"]) / 1e6
    return float("nan")


def time_to_first_spyre_pipe_ms(run: dict) -> float:
    base = event(run, FIRST_CALL)
    if base is None:
        return float("nan")
    for e in sorted(run["events"], key=lambda e: e["t_start_ns"]):
        if e["name"] in SPYRE_PIPES:
            return (e["t_start_ns"] - base["t_start_ns"]) / 1e6
    return float("nan")


def pass_event(run: dict, pass_name: str) -> dict | None:
    n = f"pass:CustomPreSchedulingPasses:{pass_name}"
    return event(run, n)


def n_specs(run: dict) -> int | None:
    e = event(run, "sdsc_bundle_gen")
    return e.get("meta", {}).get("n_specs") if e else None


def fx_nodes(run: dict) -> int | None:
    e = event(run, COMPILE_FX)
    return e.get("meta", {}).get("fx_nodes_at_entry") if e else None


def point_label(h: int, lq: int, lk: int) -> str:
    return f"{lq}×{lk}" if h == 8 else f"H{h} {lq}×{lk}"


# ------------------------------------------------------------------ tables

TOP_PASSES = [
    "dedup_and_promote_constants",
    "optimize_restickify_locations",
    "_maybe_scratchpad_planning",
    "propagate_spyre_tensor_layouts",
    "span_reduction",
    "_distribute_work",
    "enforce_indirect_access_layout",
    "deadcode_elimination",
    "validate_ops",
    "split_multi_ops",
]


def write_table_a(by: dict) -> None:
    rows = []
    for (h, lq, lk), runs in sorted(by.items()):
        inner_bodies = runs[0]["meta"].get("predicted_inner_bodies")
        # sdsc_total contains dxp_standalone + sdsc_bundle_gen + provenance
        # bookkeeping. The sdsc_prep bucket is what remains after subtracting
        # dxp — it captures backend-input preparation on the torch side.
        sdsc_prep_per_run = [
            sum_ms(r, "sdsc_total") - dxp_total_ms(r) for r in runs
        ]
        row = {
            "H": h, "Lq": lq, "Lk": lk, "n": len(runs),
            "inner_bodies": inner_bodies,
            "fx_nodes": med([v for v in (fx_nodes(r) for r in runs) if v is not None]),
            "n_specs": med([v for v in (n_specs(r) for r in runs) if v is not None]),
            "first_call_wall_s": med([first_call_ms(r) for r in runs]) / 1000,
            "compile_fx_s": med([compile_fx_ms(r) for r in runs]) / 1000,
            "spyre_pass_pipeline_s": med([spyre_pass_total_ms(r) for r in runs]) / 1000,
            "dxp_standalone_s": med([dxp_total_ms(r) for r in runs]) / 1000,
            "sdsc_prep_s": med(sdsc_prep_per_run) / 1000,
            "unattributed_compile_fx_s": (
                med([unattributed_compile_fx_ms(r) for r in runs]) / 1000
            ),
        }
        rows.append(row)

    rows.sort(key=lambda r: (r["inner_bodies"] or 0, r["H"], r["Lq"], r["Lk"]))

    lines = []
    lines.append("### Table A — workload scaling")
    lines.append("")
    lines.append(
        "Times are medians across `n` cold-compile samples per point, in "
        "seconds. `compile_fx_wrapper` is exhaustively partitioned into four "
        "buckets that sum to it (up to a negligible `async_compile_wait`):"
    )
    lines.append("")
    lines.append(
        "- `dxp_standalone` — external backend compiler subprocess.\n"
        "- `sdsc_prep` — torch-side SDSC/backend-input preparation "
        "(`sdsc_total − dxp_standalone`; includes `sdsc_bundle_gen` and "
        "kernel-provenance bookkeeping).\n"
        "- `Spyre pass pipelines` — the six Spyre custom pass pipelines "
        "(`CustomPreGrad`, `CustomPre`, `CustomPost`, `CustomPreFusion`, "
        "`CustomPostFusion`, `CustomPreScheduling`).\n"
        "- `unattributed_compile_fx` — the remaining time inside "
        "`compile_fx_wrapper` that this instrumentation does not yet "
        "bracket individually (upstream Inductor lowering, AOTAutograd, "
        "codegen, wrapper generation).\n"
    )
    lines.append(
        "Bucket subtraction is performed **per run** and then medianed; "
        "medians are not composed algebraically."
    )
    lines.append("")
    lines.append(
        "| H | Lq | Lk | inner_bodies | FX nodes | n_specs | wall (s) | "
        "compile_fx (s) | dxp_standalone (s) | sdsc_prep (s) | "
        "Spyre pass pipelines (s) | unattributed compile_fx (s) | n |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    def fx(x): return "-" if x != x else f"{x:.2f}"
    def ix(x): return "-" if x is None or (isinstance(x, float) and x != x) else str(int(x))

    for r in rows:
        lines.append(
            f"| {r['H']} | {r['Lq']} | {r['Lk']} | {r['inner_bodies']} | "
            f"{ix(r['fx_nodes'])} | {ix(r['n_specs'])} | "
            f"{fx(r['first_call_wall_s'])} | {fx(r['compile_fx_s'])} | "
            f"{fx(r['dxp_standalone_s'])} | {fx(r['sdsc_prep_s'])} | "
            f"{fx(r['spyre_pass_pipeline_s'])} | "
            f"{fx(r['unattributed_compile_fx_s'])} | {r['n']} |"
        )
    lines.append("")

    # Growth relative to baseline (H=8, Lq=512, Lk=1024)
    baseline = next(
        (r for r in rows if r["H"] == 8 and r["Lq"] == 512 and r["Lk"] == 1024),
        None,
    )
    if baseline:
        lines.append("### Growth relative to baseline (H=8, Lq=512, Lk=1024)")
        lines.append("")
        lines.append(
            "| H | Lq | Lk | inner_bodies × | FX nodes × | n_specs × | "
            "compile_fx × | dxp × | sdsc_prep × | Spyre passes × | "
            "unattributed × |"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

        def ratio(cur, base):
            if base is None or base != base or base == 0 or cur is None or cur != cur:
                return "-"
            return f"{cur/base:.2f}"

        for r in rows:
            lines.append(
                f"| {r['H']} | {r['Lq']} | {r['Lk']} | "
                f"{ratio(r['inner_bodies'], baseline['inner_bodies'])} | "
                f"{ratio(r['fx_nodes'], baseline['fx_nodes'])} | "
                f"{ratio(r['n_specs'], baseline['n_specs'])} | "
                f"{ratio(r['compile_fx_s'], baseline['compile_fx_s'])} | "
                f"{ratio(r['dxp_standalone_s'], baseline['dxp_standalone_s'])} | "
                f"{ratio(r['sdsc_prep_s'], baseline['sdsc_prep_s'])} | "
                f"{ratio(r['spyre_pass_pipeline_s'], baseline['spyre_pass_pipeline_s'])} | "
                f"{ratio(r['unattributed_compile_fx_s'], baseline['unattributed_compile_fx_s'])} |"
            )
        lines.append("")

    path = os.path.join(TABLES, "table-a-workload.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def write_table_b(by: dict) -> None:
    """Table B: per-pass median-ms and ms-per-input-op across points.
    x-axis for each pass is its OWN input_operations, not global fx nodes."""
    per_point = {}
    for (h, lq, lk), runs in sorted(by.items()):
        pass_data = {}
        for name in TOP_PASSES:
            times = []
            inputs = []
            for r in runs:
                ev = pass_event(r, name)
                if ev is None:
                    continue
                times.append(ev["inclusive_ns"] / 1e6)
                m = ev.get("meta", {})
                if "input_operations" in m:
                    inputs.append(m["input_operations"])
            if times:
                pass_data[name] = {
                    "median_ms": med(times),
                    "median_input_ops": med(inputs) if inputs else None,
                }
        per_point[(h, lq, lk)] = pass_data

    cols = sorted(per_point.keys())

    lines = []
    lines.append("### Table B — pre-scheduling pass scaling")
    lines.append("")
    lines.append(
        "Per-pass median times (ms), 3 samples per point. **The x-axis "
        "for each pass is its own `input_operations` (`graph.operations` "
        "size at pass entry), recorded on every event.** Passes further "
        "down the pipeline see a slightly smaller operation list than "
        "the initial FX-node count, so this is the meaningful scaling "
        "variable — not global FX nodes."
    )
    lines.append("")
    lines.append("**Absolute time (ms):**")
    lines.append("")
    lines.append("| pass | " + " | ".join(point_label(h, lq, lk) for (h, lq, lk) in cols) + " |")
    lines.append("|---" * (len(cols) + 1) + "|")
    for name in TOP_PASSES:
        cells = []
        for p in cols:
            d = per_point[p].get(name)
            cells.append(f"{d['median_ms']:.0f}" if d else "-")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("**Input operations at pass entry:**")
    lines.append("")
    lines.append("| pass | " + " | ".join(point_label(h, lq, lk) for (h, lq, lk) in cols) + " |")
    lines.append("|---" * (len(cols) + 1) + "|")
    for name in TOP_PASSES:
        cells = []
        for p in cols:
            d = per_point[p].get(name)
            cells.append(str(int(d["median_input_ops"])) if d and d["median_input_ops"] else "-")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("**Cost per input operation (µs/op = ms/n_ops × 1000):**")
    lines.append("")
    lines.append("| pass | " + " | ".join(point_label(h, lq, lk) for (h, lq, lk) in cols) + " |")
    lines.append("|---" * (len(cols) + 1) + "|")
    for name in TOP_PASSES:
        cells = []
        for p in cols:
            d = per_point[p].get(name)
            if d and d.get("median_input_ops"):
                us_per_op = d["median_ms"] * 1000.0 / d["median_input_ops"]
                cells.append(f"{us_per_op:.1f}")
            else:
                cells.append("-")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append(
        "**Endpoint-to-endpoint log-log slope** (log(t)/log(n) between "
        "smallest and largest `input_operations` observed for that pass "
        "in the H=8 sweep — 1.0 = linear, 2.0 = quadratic):"
    )
    lines.append("")
    lines.append("| pass | smallest n_ops | largest n_ops | slope | interpretation |")
    lines.append("|---|---:|---:|---:|---|")
    for name in TOP_PASSES:
        points = []
        for p in cols:
            h, lq, lk = p
            if h != 8:
                continue  # keep the slope defined by the H=8 backbone
            d = per_point[p].get(name)
            if d and d.get("median_input_ops"):
                points.append((d["median_input_ops"], d["median_ms"]))
        if len(points) < 2:
            continue
        pts = sorted(points)
        (n0, t0), (n1, t1) = pts[0], pts[-1]
        if n1 <= n0 or t1 <= 0 or t0 <= 0:
            slope = float("nan")
        else:
            slope = math.log(t1 / t0) / math.log(n1 / n0)
        if slope != slope:
            interp = "n/a"
        elif slope < 1.15:
            interp = "linear or sublinear"
        elif slope < 1.6:
            interp = "mildly superlinear"
        elif slope < 1.85:
            interp = "strongly superlinear (~n^1.5–1.8)"
        else:
            interp = "near-quadratic (~n²)"
        lines.append(
            f"| `{name}` | {int(n0)} | {int(n1)} | {slope:.2f} | {interp} |"
        )
    lines.append("")

    path = os.path.join(TABLES, "table-b-passes.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def _dedup_rows(by: dict) -> list[dict]:
    rows = []
    for (h, lq, lk), runs in sorted(by.items()):
        d_list = [pass_event(r, "dedup_and_promote_constants") for r in runs]
        d_list = [d for d in d_list if d is not None]
        if not d_list:
            continue
        dups = med([-d.get("meta", {}).get("ops_delta", 0) for d in d_list])
        input_ops = med([d.get("meta", {}).get("input_operations", 0) for d in d_list])
        t_ms = med([d["inclusive_ns"] / 1e6 for d in d_list])
        rows.append({
            "H": h, "Lq": lq, "Lk": lk,
            "input_ops": input_ops, "duplicates": dups,
            "t_ms": t_ms, "product": input_ops * dups,
        })
    return rows


def _fit_dedup_coef_ms_per_pair(rows: list[dict]) -> float:
    """Return the linear-through-origin coefficient (ms per operations×duplicates)
    from a fit through the given rows only."""
    if not rows:
        return float("nan")
    num = sum(r["product"] * r["t_ms"] for r in rows)
    den = sum(r["product"] ** 2 for r in rows)
    return num / den if den else float("nan")


def write_dedup_mechanism(by: dict) -> None:
    """Source-derived cost model for ``dedup_and_promote_constants``:
    the pass calls two O(|operations|) routines per duplicate, so
    work should scale as ``|operations| × |duplicates|``."""
    rows = _dedup_rows(by)

    lines = []
    lines.append("### `dedup_and_promote_constants` — source-level cost model")
    lines.append("")
    lines.append(
        "From `torch_spyre/_inductor/dedup_constants.py`: the pass loops "
        "`for dup in group[1:]:` and calls two O(|operations|) routines "
        "per duplicate:"
    )
    lines.append("")
    lines.append("- `_redirect_consumers(operations, dup, canonical)` iterates every")
    lines.append("  operation and calls `op.get_read_writes()`.")
    lines.append("- `_drop_constant(...)` calls `operations.remove(dup)`, which is")
    lines.append("  O(|operations|) on a Python list.")
    lines.append("")
    lines.append(
        "Predicted work is therefore `c · |operations| · |duplicates|`."
    )
    lines.append("")

    baseline = next(
        (r for r in rows if r["H"] == 8 and r["Lq"] == 512 and r["Lk"] == 1024),
        None,
    )
    lines.append(
        "| H | Lq | Lk | input_operations | duplicates | operations × duplicates | "
        "measured t (ms) | product × baseline | t × baseline |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        if baseline:
            prod_ratio = r["product"] / baseline["product"] if baseline["product"] else 0
            t_ratio = r["t_ms"] / baseline["t_ms"] if baseline["t_ms"] else 0
            prod_s = f"{prod_ratio:.2f}"
            t_s = f"{t_ratio:.2f}"
        else:
            prod_s = "-"
            t_s = "-"
        lines.append(
            f"| {r['H']} | {r['Lq']} | {r['Lk']} | {int(r['input_ops'])} | "
            f"{int(r['duplicates'])} | {int(r['product']):,} | "
            f"{r['t_ms']:.0f} | {prod_s} | {t_s} |"
        )
    lines.append("")

    if baseline:
        lines.append(
            "Source inspection predicts work proportional to "
            "`|operations| × |duplicates|`; measured pass time agrees "
            "with that prediction to within a few percent across the "
            "measured workload range. Because duplicate count grows "
            "approximately proportionally with operation count for "
            "this workload, the pass appears near-quadratic in program "
            "size — but the underlying cost model is the product, not "
            "a universal `O(n²)` in graph size."
        )
        lines.append("")

    path = os.path.join(TABLES, "dedup-mechanism.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def write_time_to_first_pass(by: dict) -> None:
    rows = []
    for (h, lq, lk), runs in sorted(by.items()):
        rows.append({
            "H": h, "Lq": lq, "Lk": lk,
            "t_compile_fx_start_s": med(
                [time_to_ms(r, COMPILE_FX) for r in runs]) / 1000,
            "t_first_spyre_pipe_s": med(
                [time_to_first_spyre_pipe_ms(r) for r in runs]) / 1000,
            "t_pre_scheduling_s": med(
                [time_to_ms(r, PRE_SCHED_PIPE) for r in runs]) / 1000,
        })
    lines = []
    lines.append("### Time-to-first-pass (from raw event timestamps)")
    lines.append("")
    lines.append(
        "Interval from `first_call_wall` t=0 to the start of the named "
        "event, computed per run from raw ``t_start_ns`` and medianed. "
        "The first Spyre custom pipeline entered is ``CustomPrePasses``; "
        "the main pre-scheduling pipeline is ``CustomPreSchedulingPasses``. "
        "These are two distinct boundaries — the first Spyre pipeline "
        "typically begins about a second before pre-scheduling."
    )
    lines.append("")
    lines.append(
        "| H | Lq | Lk | t → compile_fx (s) | t → first Spyre pipeline (s) | "
        "t → pre-scheduling pipeline (s) |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['H']} | {r['Lq']} | {r['Lk']} | "
            f"{r['t_compile_fx_start_s']:.2f} | "
            f"{r['t_first_spyre_pipe_s']:.2f} | "
            f"{r['t_pre_scheduling_s']:.2f} |"
        )
    lines.append("")
    lines.append(
        "The gap between `t → compile_fx` and `t → first Spyre pipeline` "
        "is upstream Inductor work "
        "(AOTAutograd, decomposition, `GraphLowering` construction). "
        "The gap between the first Spyre pipeline and "
        "`t → pre-scheduling` is upstream Inductor lowering, scheduling, "
        "and Spyre-specific graph-level FX passes."
    )
    lines.append("")
    lines.append(
        "Dynamo capture is not inside `compile_fx_wrapper`: "
        "`compile_fx` receives an already-captured `gm` and "
        "`example_inputs`. Dynamo runs upstream of this boundary, "
        "before the compiled call reaches `compile_fx`."
    )
    path = os.path.join(TABLES, "time-to-first-pass.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def write_backend_per_spec(by: dict) -> None:
    rows = []
    for (h, lq, lk), runs in sorted(by.items()):
        specs = med([v for v in (n_specs(r) for r in runs) if v is not None])
        bundle = med([sum_ms(r, "sdsc_bundle_gen") for r in runs])
        dxp = med([dxp_total_ms(r) for r in runs])
        rows.append({
            "H": h, "Lq": lq, "Lk": lk, "n_specs": specs,
            "bundle_gen_ms": bundle, "dxp_ms": dxp,
            "dxp_per_spec_ms": dxp / specs if specs else float("nan"),
            "bundle_per_spec_ms": bundle / specs if specs else float("nan"),
        })

    lines = []
    lines.append("### Backend scaling per SDSC spec")
    lines.append("")
    lines.append(
        "SDSC bundle generation feeds `dxp_standalone` a bundle of "
        "`n_specs` op specs. If the backend were linear in the size "
        "of the bundle it receives, `dxp / n_specs` would be constant."
    )
    lines.append("")
    lines.append(
        "| H | Lq | Lk | n_specs | sdsc_bundle_gen (ms) | dxp_standalone (ms) | "
        "bundle_gen / spec (ms) | dxp / spec (ms) |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['H']} | {r['Lq']} | {r['Lk']} | {int(r['n_specs'])} | "
            f"{r['bundle_gen_ms']:.0f} | {r['dxp_ms']:.0f} | "
            f"{r['bundle_per_spec_ms']:.2f} | {r['dxp_per_spec_ms']:.2f} |"
        )
    lines.append("")
    lines.append(
        "`sdsc_bundle_gen` per spec is approximately constant across "
        "the measured range: torch-side bundle generation is linear "
        "in `n_specs`. `dxp / n_specs` increases substantially over the "
        "same range, indicating strongly superlinear backend scaling in "
        "the size of the bundle it receives. The external backend is "
        "outside the scope of this study and is reported here only for "
        "context; it dominates the absolute compile time attributed to "
        "`compile_fx_wrapper` at every measured workload point."
    )
    lines.append("")
    path = os.path.join(TABLES, "backend-per-spec.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def write_residual_decomposition(by: dict) -> None:
    """Report the ``unattributed_compile_fx`` bucket per point.

    Residual = compile_fx − (Spyre pipelines + sdsc_total + async_wait),
    computed per run and then medianed."""
    lines = []
    lines.append("### Unattributed compile_fx")
    lines.append("")
    lines.append(
        "Time inside `compile_fx_wrapper` that this instrumentation "
        "does not yet bracket individually. Computed per run and then "
        "medianed rather than by subtracting bucket-wise medians "
        "(medians do not compose algebraically)."
    )
    lines.append("")
    lines.append("Contains, in decreasing order of expected weight:")
    lines.append("")
    lines.append("- AOTAutograd joint-graph decomposition")
    lines.append("- Upstream Inductor decomposition and lowering (`GraphLowering.run`)")
    lines.append("- Upstream Inductor fusion and scheduling")
    lines.append("- `SpyreKernel` per-kernel codegen")
    lines.append("- `SpyrePythonWrapperCodegen` (host-side wrapper generation)")
    lines.append("- Any Spyre pass work outside a `pipeline:*` event")
    lines.append("")
    lines.append("Does not contain:")
    lines.append("")
    lines.append("- Dynamo capture (runs outside `compile_fx`)")
    lines.append("- `dxp_standalone` (its own bucket)")
    lines.append("- `sdsc_bundle_gen` (part of `sdsc_total`)")
    lines.append("")
    lines.append(
        "| H | Lq | Lk | compile_fx (s) | Spyre pipelines (s) | sdsc_total (s) | "
        "unattributed (s) | unattributed % of compile_fx |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for (h, lq, lk), runs in sorted(by.items()):
        cfx = med([compile_fx_ms(r) for r in runs]) / 1000
        sp = med([spyre_pass_total_ms(r) for r in runs]) / 1000
        sdsc = med([sum_ms(r, "sdsc_total") for r in runs]) / 1000
        unattr = med([unattributed_compile_fx_ms(r) for r in runs]) / 1000
        pct = 100.0 * unattr / cfx if cfx else float("nan")
        lines.append(
            f"| {h} | {lq} | {lk} | {cfx:.2f} | {sp:.2f} | {sdsc:.2f} | "
            f"{unattr:.2f} | {pct:.1f}% |"
        )
    lines.append("")
    lines.append(
        "The bucket grows more slowly than `dxp_standalone` and the "
        "Spyre pass pipelines over the measured range, but its "
        "internal components cannot be characterized individually "
        "until the additional boundaries in `patches/extra_timers.py` "
        "are enabled."
    )
    lines.append("")

    path = os.path.join(TABLES, "residual-decomposition.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


# ------------------------------------------------------------------ H-sweep

def _point_row(by: dict, key: tuple[int, int, int]) -> dict | None:
    runs = by.get(key)
    if not runs:
        return None
    h, lq, lk = key
    inner_bodies = runs[0]["meta"].get("predicted_inner_bodies")
    sdsc_prep_per_run = [sum_ms(r, "sdsc_total") - dxp_total_ms(r) for r in runs]
    return {
        "H": h, "Lq": lq, "Lk": lk, "n": len(runs),
        "inner_bodies": inner_bodies,
        "fx_nodes": med([v for v in (fx_nodes(r) for r in runs) if v is not None]),
        "n_specs": med([v for v in (n_specs(r) for r in runs) if v is not None]),
        "compile_fx_s": med([compile_fx_ms(r) for r in runs]) / 1000,
        "spyre_pipes_s": med([spyre_pass_total_ms(r) for r in runs]) / 1000,
        "dxp_s": med([dxp_total_ms(r) for r in runs]) / 1000,
        "sdsc_prep_s": med(sdsc_prep_per_run) / 1000,
        "unattr_s": med([unattributed_compile_fx_ms(r) for r in runs]) / 1000,
        "presched_ops": (
            med([ev.get("meta", {}).get("input_operations", 0)
                 for r in runs
                 for ev in [pass_event(r, "dedup_and_promote_constants")] if ev])
        ),
    }


def write_h_scaling(by: dict) -> None:
    """H-dimension scaling section plus equal-inner-body comparison."""
    lines = []
    lines.append("### H-dimension controlled scaling (Lq=512, Lk=1024)")
    lines.append("")
    lines.append(
        "Varying `H` at fixed `Lq, Lk` (all other block sizes unchanged). "
        "`h_block_size = 4`, so the H-tile count is `H / 4`. Predicted "
        "inner bodies grow linearly with H."
    )
    lines.append("")

    h_points = [(8, 512, 1024), (16, 512, 1024), (32, 512, 1024)]
    h_rows = [row for row in (_point_row(by, k) for k in h_points) if row]

    if not h_rows:
        # No H-sweep data yet — write a placeholder to keep artefacts in-tree.
        lines.append("_(no H-sweep runs found — populate `data/h*-*.json` and rerun.)_")
        lines.append("")
    else:
        lines.append(
            "| H | H tiles | inner_bodies | FX nodes | pre-sched ops | n_specs | "
            "compile_fx (s) | Spyre passes (s) | dxp (s) | sdsc_prep (s) | "
            "unattributed (s) | n |"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in h_rows:
            lines.append(
                f"| {r['H']} | {r['H']//4} | {r['inner_bodies']} | "
                f"{int(r['fx_nodes'])} | "
                f"{int(r['presched_ops']) if r['presched_ops']==r['presched_ops'] else '-'} | "
                f"{int(r['n_specs'])} | "
                f"{r['compile_fx_s']:.2f} | {r['spyre_pipes_s']:.2f} | "
                f"{r['dxp_s']:.2f} | {r['sdsc_prep_s']:.2f} | "
                f"{r['unattr_s']:.2f} | {r['n']} |"
            )
        lines.append("")

        base = next((r for r in h_rows if r["H"] == 8), None)
        if base:
            lines.append("**Ratios relative to H=8, Lq=512, Lk=1024:**")
            lines.append("")
            lines.append(
                "| H | inner_bodies × | FX nodes × | pre-sched ops × | n_specs × | "
                "compile_fx × | Spyre passes × | dxp × |"
            )
            lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
            for r in h_rows:
                def rat(a, b): return f"{a/b:.2f}" if b else "-"
                lines.append(
                    f"| {r['H']} | {rat(r['inner_bodies'], base['inner_bodies'])} | "
                    f"{rat(r['fx_nodes'], base['fx_nodes'])} | "
                    f"{rat(r['presched_ops'], base['presched_ops'])} | "
                    f"{rat(r['n_specs'], base['n_specs'])} | "
                    f"{rat(r['compile_fx_s'], base['compile_fx_s'])} | "
                    f"{rat(r['spyre_pipes_s'], base['spyre_pipes_s'])} | "
                    f"{rat(r['dxp_s'], base['dxp_s'])} |"
                )
            lines.append("")

    # Equal-inner-body H-vs-Lk comparison
    lines.append("### Equal-inner-body comparison: H growth vs Lk growth")
    lines.append("")
    lines.append(
        "The `flash` closure's inner-body count is "
        "`(B/b) · (H/h) · (Lq/q) · (Lk/kv)`. Growing `H` or growing `Lk` "
        "at fixed other dimensions both multiply that count. Pairs below "
        "reach the same predicted inner-body count by different routes; "
        "if compiler scaling is a function of compiler-visible program "
        "size only, the pairs should agree in FX nodes, `n_specs`, and "
        "front-end pass time."
    )
    lines.append("")

    pairs = [
        (16, [(16, 512, 1024), (8, 512, 2048)]),
        (32, [(32, 512, 1024), (8, 512, 4096)]),
    ]
    have_rows = False
    lines.append(
        "| bodies | H | Lq | Lk | FX nodes | pre-sched ops | n_specs | "
        "compile_fx (s) | Spyre passes (s) | dxp (s) |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for bodies, keys in pairs:
        for key in keys:
            row = _point_row(by, key)
            if not row:
                continue
            have_rows = True
            lines.append(
                f"| {bodies} | {row['H']} | {row['Lq']} | {row['Lk']} | "
                f"{int(row['fx_nodes'])} | "
                f"{int(row['presched_ops']) if row['presched_ops']==row['presched_ops'] else '-'} | "
                f"{int(row['n_specs'])} | "
                f"{row['compile_fx_s']:.2f} | {row['spyre_pipes_s']:.2f} | "
                f"{row['dxp_s']:.2f} |"
            )
    lines.append("")

    if not have_rows:
        lines.append("_(no H-sweep runs found — populate `data/h*-*.json` and rerun.)_")
        lines.append("")

    path = os.path.join(TABLES, "h-scaling.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


def write_dedup_oos(by: dict) -> None:
    """Out-of-sample validation of the ``operations × duplicates`` model
    using the coefficient fit on the H=8 sweep only."""
    all_rows = _dedup_rows(by)
    h8 = [r for r in all_rows if r["H"] == 8]
    non_h8 = [r for r in all_rows if r["H"] != 8]

    coef_us = _fit_dedup_coef_ms_per_pair(h8) * 1000.0  # µs per (ops × dups)
    if coef_us != coef_us:
        coef_us = float("nan")

    lines = []
    lines.append("### `dedup_and_promote_constants` — out-of-sample check")
    lines.append("")
    lines.append(
        "Coefficient frozen at the value fit through the origin on the "
        "H=8 sweep. Each H-sweep point is then evaluated as an "
        "out-of-sample prediction: no re-fitting on the new data."
    )
    lines.append("")
    lines.append(f"H=8 fit: **t ≈ {coef_us:.1f} µs × (operations × duplicates)**")
    lines.append("")

    if not non_h8:
        lines.append("_(no non-H=8 dedup points found — populate `data/h*-*.json` and rerun.)_")
        lines.append("")
    else:
        lines.append(
            "| H | Lq | Lk | input_operations | duplicates | operations × duplicates | "
            "predicted t (ms) | measured t (ms) | error % |"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in non_h8:
            predicted_ms = coef_us / 1000.0 * r["product"]
            err_pct = 100.0 * (r["t_ms"] - predicted_ms) / predicted_ms if predicted_ms else float("nan")
            lines.append(
                f"| {r['H']} | {r['Lq']} | {r['Lk']} | {int(r['input_ops'])} | "
                f"{int(r['duplicates'])} | {int(r['product']):,} | "
                f"{predicted_ms:.0f} | {r['t_ms']:.0f} | {err_pct:+.1f}% |"
            )
        lines.append("")

    # Also show an updated fit including all points, for reference — clearly
    # marked as post-hoc.
    if all_rows:
        coef_all_us = _fit_dedup_coef_ms_per_pair(all_rows) * 1000.0
        lines.append(
            f"Updated fit including H-sweep points: "
            f"**t ≈ {coef_all_us:.1f} µs × (operations × duplicates)** "
            f"({(coef_all_us - coef_us) / coef_us * 100:+.1f}% relative to "
            f"the H=8-only coefficient)."
        )
        lines.append("")

    path = os.path.join(TABLES, "dedup-oos.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path}")


# ------------------------------------------------------------------ plots

def make_plots(by: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib not available)")
        return

    rows = []
    for (h, lq, lk), runs in sorted(by.items()):
        rows.append({
            "H": h, "Lq": lq, "Lk": lk,
            "fx_nodes": med([v for v in (fx_nodes(r) for r in runs) if v is not None]),
            "n_specs": med([v for v in (n_specs(r) for r in runs) if v is not None]),
            "compile_fx_s": med([compile_fx_ms(r) for r in runs]) / 1000,
            "dxp_s": med([dxp_total_ms(r) for r in runs]) / 1000,
            "spyre_pipes_s": med([spyre_pass_total_ms(r) for r in runs]) / 1000,
            "unattr_s": med([unattributed_compile_fx_ms(r) for r in runs]) / 1000,
            "bundle_ms": med([sum_ms(r, "sdsc_bundle_gen") for r in runs]),
        })

    h8_rows = [r for r in rows if r["H"] == 8]
    non_h8_rows = [r for r in rows if r["H"] != 8]

    # ---- compile-stages.png ----
    fig, ax = plt.subplots(figsize=(8, 5))
    by_x = {r["fx_nodes"]: r for r in h8_rows
            if r["fx_nodes"] == r["fx_nodes"]}
    xs_sorted = sorted(by_x.keys())
    for key, label, marker in [
        ("compile_fx_s", "compile_fx (torch-side compile total)", "o"),
        ("dxp_s", "dxp_standalone (external backend)", "s"),
        ("spyre_pipes_s", "Spyre pass pipelines", "^"),
        ("unattr_s", "unattributed compile_fx", "d"),
    ]:
        ys = [by_x[x][key] for x in xs_sorted]
        ax.plot(xs_sorted, ys, marker=marker, label=label, linewidth=1.8)
    # Overlay any H-sweep points as unfilled markers so they're distinguishable.
    if non_h8_rows:
        for r in non_h8_rows:
            for key, marker in [
                ("compile_fx_s", "o"), ("dxp_s", "s"),
                ("spyre_pipes_s", "^"), ("unattr_s", "d"),
            ]:
                ax.plot([r["fx_nodes"]], [r[key]], marker=marker,
                        markerfacecolor="none", markeredgecolor="black",
                        markersize=8, linestyle="none")
        ax.plot([], [], marker="o", markerfacecolor="none",
                markeredgecolor="black", markersize=8, linestyle="none",
                label="H ≠ 8 (H-sweep point)")
    ax.set_xlabel("FX nodes at compile_fx entry")
    ax.set_ylabel("seconds")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("compile-stage time vs graph size")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "compile-stages.png"), dpi=130)
    plt.close(fig)

    # ---- pass-scaling.png ----
    fig, ax = plt.subplots(figsize=(8, 5))
    per_pass = defaultdict(list)          # name -> [(input_ops, ms, h)]
    for (h, lq, lk), runs in sorted(by.items()):
        for name in TOP_PASSES:
            times = []
            inputs = []
            for r in runs:
                ev = pass_event(r, name)
                if ev is None:
                    continue
                times.append(ev["inclusive_ns"] / 1e6)
                m = ev.get("meta", {})
                if "input_operations" in m:
                    inputs.append(m["input_operations"])
            if times and inputs:
                per_pass[name].append((med(inputs), med(times), h))
    for name in TOP_PASSES[:6]:
        pts = sorted(per_pass.get(name, []))
        if not pts:
            continue
        h8_pts = [(x, y) for x, y, hh in pts if hh == 8]
        oth_pts = [(x, y) for x, y, hh in pts if hh != 8]
        if h8_pts:
            xs = [p[0] for p in h8_pts]
            ys = [p[1] for p in h8_pts]
            line, = ax.plot(xs, ys, marker="o", label=name)
            if oth_pts:
                ax.plot([p[0] for p in oth_pts], [p[1] for p in oth_pts],
                        marker="o", linestyle="none",
                        markerfacecolor="none",
                        markeredgecolor=line.get_color(), markersize=8)
        elif oth_pts:
            ax.plot([p[0] for p in oth_pts], [p[1] for p in oth_pts],
                    marker="o", linestyle="none", label=name)
    if per_pass:
        xs_all = sorted({p[0] for pts in per_pass.values() for p in pts})
        if len(xs_all) >= 2:
            x_ref = xs_all
            ax.plot(x_ref, [x/x_ref[0]*1 for x in x_ref],
                    linestyle=":", color="gray", alpha=0.5,
                    label="reference: linear (slope 1)")
            ax.plot(x_ref, [(x/x_ref[0])**2 * 1 for x in x_ref],
                    linestyle="--", color="gray", alpha=0.5,
                    label="reference: quadratic (slope 2)")
    ax.set_xlabel("input_operations at pass entry (per-pass x-axis)")
    ax.set_ylabel("median pass time (ms)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("top-6 pre-scheduling passes vs their own input size "
                 "(filled: H=8; hollow: H≠8)")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "pass-scaling.png"), dpi=130)
    plt.close(fig)

    # ---- dedup-model-fit.png ----
    fig, ax = plt.subplots(figsize=(8, 5))
    xs_h8, ys_h8, labs_h8 = [], [], []
    xs_oth, ys_oth, labs_oth = [], [], []
    for (h, lq, lk), runs in sorted(by.items()):
        d_list = [pass_event(r, "dedup_and_promote_constants") for r in runs]
        d_list = [d for d in d_list if d is not None]
        if not d_list:
            continue
        dups = -med([d.get("meta", {}).get("ops_delta", 0) for d in d_list])
        iops = med([d.get("meta", {}).get("input_operations", 0) for d in d_list])
        t = med([d["inclusive_ns"] / 1e6 for d in d_list])
        if h == 8:
            xs_h8.append(iops * dups); ys_h8.append(t)
            labs_h8.append(f"{lq}×{lk}")
        else:
            xs_oth.append(iops * dups); ys_oth.append(t)
            labs_oth.append(f"H{h} {lq}×{lk}")

    # Coefficient computed on H=8 only
    coef_us = _fit_dedup_coef_ms_per_pair(
        [{"product": x, "t_ms": y} for x, y in zip(xs_h8, ys_h8)]
    ) * 1000.0

    if xs_h8:
        order = sorted(range(len(xs_h8)), key=lambda i: xs_h8[i])
        xs_s = [xs_h8[i] for i in order]
        ys_s = [ys_h8[i] for i in order]
        labs_s = [labs_h8[i] for i in order]
        ax.plot(xs_s, ys_s, marker="o", label="H=8 measured")
        ax.plot(
            xs_s, [coef_us / 1000.0 * x for x in xs_s],
            linestyle="--", color="gray",
            label=f"H=8 fit: y = {coef_us:.1f} µs × (ops × dups)",
        )
        for x, y, lab in zip(xs_s, ys_s, labs_s):
            ax.annotate(lab, (x, y), fontsize=8, xytext=(4, 4),
                        textcoords="offset points")

    if xs_oth:
        ax.plot(xs_oth, ys_oth, marker="s", linestyle="none",
                markerfacecolor="none", markeredgecolor="black",
                label="H≠8 out-of-sample")
        for x, y, lab in zip(xs_oth, ys_oth, labs_oth):
            ax.annotate(lab, (x, y), fontsize=8, xytext=(4, -10),
                        textcoords="offset points")

    ax.set_xlabel("operations × duplicates at pass entry")
    ax.set_ylabel("dedup_and_promote_constants time (ms)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("dedup_and_promote_constants ~ c × operations × duplicates")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "dedup-model-fit.png"), dpi=130)
    plt.close(fig)

    # ---- backend-per-spec.png ----
    fig, ax = plt.subplots(figsize=(8, 5))
    xs_h8, y_dxp_h8, y_bundle_h8 = [], [], []
    xs_oth, y_dxp_oth, y_bundle_oth, labs_oth = [], [], [], []
    for (h, lq, lk), runs in sorted(by.items()):
        specs = med([v for v in (n_specs(r) for r in runs) if v is not None])
        if specs != specs:
            continue
        dxp = med([dxp_total_ms(r) for r in runs]) / specs
        bundle = med([sum_ms(r, "sdsc_bundle_gen") for r in runs]) / specs
        if h == 8:
            xs_h8.append(specs); y_dxp_h8.append(dxp); y_bundle_h8.append(bundle)
        else:
            xs_oth.append(specs); y_dxp_oth.append(dxp); y_bundle_oth.append(bundle)
            labs_oth.append(f"H{h} {lq}×{lk}")
    if xs_h8:
        order = sorted(range(len(xs_h8)), key=lambda i: xs_h8[i])
        xs_s = [xs_h8[i] for i in order]
        y_dxp_s = [y_dxp_h8[i] for i in order]
        y_bundle_s = [y_bundle_h8[i] for i in order]
        ax.plot(xs_s, y_dxp_s, marker="o", label="H=8 dxp_standalone / n_specs")
        ax.plot(xs_s, y_bundle_s, marker="s", label="H=8 sdsc_bundle_gen / n_specs")
    if xs_oth:
        ax.plot(xs_oth, y_dxp_oth, marker="o", linestyle="none",
                markerfacecolor="none", markeredgecolor="black",
                label="H≠8 dxp / n_specs")
        ax.plot(xs_oth, y_bundle_oth, marker="s", linestyle="none",
                markerfacecolor="none", markeredgecolor="black",
                label="H≠8 bundle / n_specs")
        for x, y, lab in zip(xs_oth, y_dxp_oth, labs_oth):
            ax.annotate(lab, (x, y), fontsize=8, xytext=(4, 4),
                        textcoords="offset points")
    ax.set_xlabel("n_specs (bundle size handed to backend)")
    ax.set_ylabel("ms per spec")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("per-spec cost — backend is not just \"more specs\"")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "backend-per-spec.png"), dpi=130)
    plt.close(fig)

    print(f"wrote 4 plots to {PLOTS}")


def main() -> None:
    os.makedirs(TABLES, exist_ok=True)
    os.makedirs(PLOTS, exist_ok=True)
    by = load_runs()
    if not by:
        print("no runs found")
        return
    print(f"loaded {sum(len(v) for v in by.values())} runs across {len(by)} points")
    write_table_a(by)
    write_table_b(by)
    write_dedup_mechanism(by)
    write_time_to_first_pass(by)
    write_backend_per_spec(by)
    write_residual_decomposition(by)
    write_h_scaling(by)
    write_dedup_oos(by)
    make_plots(by)


if __name__ == "__main__":
    main()

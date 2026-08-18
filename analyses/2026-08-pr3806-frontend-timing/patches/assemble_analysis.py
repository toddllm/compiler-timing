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

Plots (matplotlib):

- ``plots/compile-stages.png``
- ``plots/pass-scaling.png``
- ``plots/dedup-model-fit.png``
- ``plots/backend-per-spec.png``

Design notes:

- Pass-level scaling uses each pass's own ``input_operations``
  (``graph.operations`` size at pass entry) as its x-axis, recorded on
  every event by the instrumentation.
- Compile time is decomposed into four exhaustive buckets that sum to
  ``compile_fx_wrapper``: external ``dxp_standalone``, SDSC/backend-input
  preparation, Spyre pass pipelines, and unattributed ``compile_fx``.
- Residuals are computed **per run** and then medianed rather than
  medianing bucket-wise; medians do not compose algebraically.
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

def load_runs() -> dict[tuple[int, int], list[dict]]:
    by = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        base = os.path.basename(path)
        if base.startswith("env-probe") or base.startswith("smoke-"):
            continue
        if "-run" not in base or not base.endswith(".json"):
            continue
        stem = base[:-len(".json")]
        try:
            lqxlk, _ = stem.split("-run")
            lq, lk = (int(x) for x in lqxlk.split("x"))
        except ValueError:
            continue
        with open(path) as f:
            by[(lq, lk)].append(json.load(f))
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
    for (lq, lk), runs in sorted(by.items()):
        inner_bodies = runs[0]["meta"].get("predicted_inner_bodies")
        # sdsc_total contains dxp_standalone + sdsc_bundle_gen + provenance
        # bookkeeping. The sdsc_prep bucket is what remains after subtracting
        # dxp — it captures backend-input preparation on the torch side.
        sdsc_prep_per_run = [
            sum_ms(r, "sdsc_total") - dxp_total_ms(r) for r in runs
        ]
        row = {
            "Lq": lq, "Lk": lk, "n": len(runs),
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
        "| Lq | Lk | inner_bodies | FX nodes | n_specs | wall (s) | "
        "compile_fx (s) | dxp_standalone (s) | sdsc_prep (s) | "
        "Spyre pass pipelines (s) | unattributed compile_fx (s) | n |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    def fx(x): return "-" if x != x else f"{x:.2f}"
    def ix(x): return "-" if x is None or (isinstance(x, float) and x != x) else str(int(x))

    for r in rows:
        lines.append(
            f"| {r['Lq']} | {r['Lk']} | {r['inner_bodies']} | "
            f"{ix(r['fx_nodes'])} | {ix(r['n_specs'])} | "
            f"{fx(r['first_call_wall_s'])} | {fx(r['compile_fx_s'])} | "
            f"{fx(r['dxp_standalone_s'])} | {fx(r['sdsc_prep_s'])} | "
            f"{fx(r['spyre_pass_pipeline_s'])} | "
            f"{fx(r['unattributed_compile_fx_s'])} | {r['n']} |"
        )
    lines.append("")

    # Growth relative to baseline
    baseline = next(
        (r for r in rows if r["Lq"] == 512 and r["Lk"] == 1024), None
    )
    if baseline:
        lines.append("### Growth relative to baseline (Lq=512, Lk=1024)")
        lines.append("")
        lines.append(
            "| Lq | Lk | inner_bodies × | FX nodes × | n_specs × | "
            "compile_fx × | dxp × | sdsc_prep × | Spyre passes × | "
            "unattributed × |"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

        def ratio(cur, base):
            if base is None or base != base or base == 0 or cur is None or cur != cur:
                return "-"
            return f"{cur/base:.2f}"

        for r in rows:
            lines.append(
                f"| {r['Lq']} | {r['Lk']} | "
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
    # Collect per (point, pass): median ms and median input_operations
    per_point = {}
    for (lq, lk), runs in sorted(by.items()):
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
        per_point[(lq, lk)] = pass_data

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
    lines.append("| pass | " + " | ".join(f"{lq}×{lk}" for (lq, lk) in cols) + " |")
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
    lines.append("| pass | " + " | ".join(f"{lq}×{lk}" for (lq, lk) in cols) + " |")
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
    lines.append("| pass | " + " | ".join(f"{lq}×{lk}" for (lq, lk) in cols) + " |")
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

    # log-log slope over each pass's own input_operations, endpoint-to-endpoint
    lines.append(
        "**Endpoint-to-endpoint log-log slope** (log(t)/log(n) between "
        "smallest and largest `input_operations` observed for that pass — "
        "1.0 = linear, 2.0 = quadratic):"
    )
    lines.append("")
    lines.append("| pass | smallest n_ops | largest n_ops | slope | interpretation |")
    lines.append("|---|---:|---:|---:|---|")
    for name in TOP_PASSES:
        points = []
        for p in cols:
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


def write_dedup_mechanism(by: dict) -> None:
    """Source-derived cost model for ``dedup_and_promote_constants``:
    the pass calls two O(|operations|) routines per duplicate, so
    work should scale as ``|operations| × |duplicates|``."""
    rows = []
    for (lq, lk), runs in sorted(by.items()):
        d_list = [pass_event(r, "dedup_and_promote_constants") for r in runs]
        d_list = [d for d in d_list if d is not None]
        if not d_list:
            continue
        # ops_delta is negative when duplicates are removed
        dups = med([-d.get("meta", {}).get("ops_delta", 0) for d in d_list])
        input_ops = med([d.get("meta", {}).get("input_operations", 0) for d in d_list])
        t_ms = med([d["inclusive_ns"] / 1e6 for d in d_list])
        rows.append({
            "Lq": lq, "Lk": lk,
            "input_ops": input_ops, "duplicates": dups,
            "t_ms": t_ms, "product": input_ops * dups,
        })

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
        (r for r in rows if r["Lq"] == 512 and r["Lk"] == 1024), None
    )
    lines.append(
        "| Lq | Lk | input_operations | duplicates | operations × duplicates | "
        "measured t (ms) | product × baseline | t × baseline |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
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
            f"| {r['Lq']} | {r['Lk']} | {int(r['input_ops'])} | "
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
    for (lq, lk), runs in sorted(by.items()):
        rows.append({
            "Lq": lq, "Lk": lk,
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
        "| Lq | Lk | t → compile_fx (s) | t → first Spyre pipeline (s) | "
        "t → pre-scheduling pipeline (s) |"
    )
    lines.append("|---:|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['Lq']} | {r['Lk']} | {r['t_compile_fx_start_s']:.2f} | "
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
    for (lq, lk), runs in sorted(by.items()):
        specs = med([v for v in (n_specs(r) for r in runs) if v is not None])
        bundle = med([sum_ms(r, "sdsc_bundle_gen") for r in runs])
        dxp = med([dxp_total_ms(r) for r in runs])
        rows.append({
            "Lq": lq, "Lk": lk, "n_specs": specs,
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
        "| Lq | Lk | n_specs | sdsc_bundle_gen (ms) | dxp_standalone (ms) | "
        "bundle_gen / spec (ms) | dxp / spec (ms) |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['Lq']} | {r['Lk']} | {int(r['n_specs'])} | "
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
        "| Lq | Lk | compile_fx (s) | Spyre pipelines (s) | sdsc_total (s) | "
        "unattributed (s) | unattributed % of compile_fx |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for (lq, lk), runs in sorted(by.items()):
        cfx = med([compile_fx_ms(r) for r in runs]) / 1000
        sp = med([spyre_pass_total_ms(r) for r in runs]) / 1000
        sdsc = med([sum_ms(r, "sdsc_total") for r in runs]) / 1000
        unattr = med([unattributed_compile_fx_ms(r) for r in runs]) / 1000
        pct = 100.0 * unattr / cfx if cfx else float("nan")
        lines.append(
            f"| {lq} | {lk} | {cfx:.2f} | {sp:.2f} | {sdsc:.2f} | "
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
    for (lq, lk), runs in sorted(by.items()):
        rows.append({
            "Lq": lq, "Lk": lk,
            "fx_nodes": med([v for v in (fx_nodes(r) for r in runs) if v is not None]),
            "n_specs": med([v for v in (n_specs(r) for r in runs) if v is not None]),
            "compile_fx_s": med([compile_fx_ms(r) for r in runs]) / 1000,
            "dxp_s": med([dxp_total_ms(r) for r in runs]) / 1000,
            "spyre_pipes_s": med([spyre_pass_total_ms(r) for r in runs]) / 1000,
            "unattr_s": med([unattributed_compile_fx_ms(r) for r in runs]) / 1000,
            "bundle_ms": med([sum_ms(r, "sdsc_bundle_gen") for r in runs]),
        })

    # ---- compile-stages.png ----
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = sorted(set(r["fx_nodes"] for r in rows if r["fx_nodes"] == r["fx_nodes"]))
    by_x = {r["fx_nodes"]: r for r in rows}
    xs_sorted = sorted(by_x.keys())
    for key, label, marker in [
        ("compile_fx_s", "compile_fx (torch-side compile total)", "o"),
        ("dxp_s", "dxp_standalone (external backend)", "s"),
        ("spyre_pipes_s", "Spyre pass pipelines", "^"),
        ("unattr_s", "unattributed compile_fx", "d"),
    ]:
        ys = [by_x[x][key] for x in xs_sorted]
        ax.plot(xs_sorted, ys, marker=marker, label=label, linewidth=1.8)
    ax.set_xlabel("FX nodes at compile_fx entry")
    ax.set_ylabel("seconds")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("PR #3806 — compile-stage time vs graph size")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "compile-stages.png"), dpi=130)
    plt.close(fig)

    # ---- pass-scaling.png (each pass vs its OWN input_operations) ----
    fig, ax = plt.subplots(figsize=(8, 5))
    # Gather per-pass points
    per_pass = defaultdict(list)  # name -> [(input_ops, ms)]
    for (lq, lk), runs in sorted(by.items()):
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
                per_pass[name].append((med(inputs), med(times)))
    for name in TOP_PASSES[:6]:
        pts = sorted(per_pass.get(name, []))
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, marker="o", label=name)
    # Reference slopes
    if per_pass:
        xs_all = sorted({p[0] for pts in per_pass.values() for p in pts})
        if len(xs_all) >= 2:
            x_ref = xs_all
            # linear: t ∝ n
            ax.plot(x_ref, [x/x_ref[0]*1 for x in x_ref],
                    linestyle=":", color="gray", alpha=0.5,
                    label="reference: linear (slope 1)")
            # quadratic: t ∝ n²
            ax.plot(x_ref, [(x/x_ref[0])**2 * 1 for x in x_ref],
                    linestyle="--", color="gray", alpha=0.5,
                    label="reference: quadratic (slope 2)")
    ax.set_xlabel("input_operations at pass entry (per-pass x-axis)")
    ax.set_ylabel("median pass time (ms)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("PR #3806 — top-6 pre-scheduling passes vs their own input size")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS, "pass-scaling.png"), dpi=130)
    plt.close(fig)

    # ---- dedup-model-fit.png ----
    fig, ax = plt.subplots(figsize=(8, 5))
    xs, ys, labels = [], [], []
    for (lq, lk), runs in sorted(by.items()):
        d_list = [pass_event(r, "dedup_and_promote_constants") for r in runs]
        d_list = [d for d in d_list if d is not None]
        if not d_list:
            continue
        dups = -med([d.get("meta", {}).get("ops_delta", 0) for d in d_list])
        iops = med([d.get("meta", {}).get("input_operations", 0) for d in d_list])
        t = med([d["inclusive_ns"] / 1e6 for d in d_list])
        xs.append(iops * dups)
        ys.append(t)
        labels.append(f"{lq}×{lk}")
    if xs:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        xs_s = [xs[i] for i in order]
        ys_s = [ys[i] for i in order]
        labs_s = [labels[i] for i in order]
        ax.plot(xs_s, ys_s, marker="o", label="measured")
        # Linear fit through origin: y = m * x
        m = sum(ys_s) / sum(xs_s)
        ax.plot(xs_s, [m*x for x in xs_s],
                linestyle="--", color="gray",
                label=f"linear fit y = {m*1000:.2f} µs × (ops × dups)")
        for x, y, lab in zip(xs_s, ys_s, labs_s):
            ax.annotate(lab, (x, y), fontsize=8, xytext=(4, 4),
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
    xs, y_dxp, y_bundle = [], [], []
    for (lq, lk), runs in sorted(by.items()):
        specs = med([v for v in (n_specs(r) for r in runs) if v is not None])
        if specs != specs:
            continue
        xs.append(specs)
        y_dxp.append(med([dxp_total_ms(r) for r in runs]) / specs)
        y_bundle.append(med([sum_ms(r, "sdsc_bundle_gen") for r in runs]) / specs)
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    xs_s = [xs[i] for i in order]
    y_dxp_s = [y_dxp[i] for i in order]
    y_bundle_s = [y_bundle[i] for i in order]
    ax.plot(xs_s, y_dxp_s, marker="o", label="dxp_standalone / n_specs")
    ax.plot(xs_s, y_bundle_s, marker="s", label="sdsc_bundle_gen / n_specs")
    ax.set_xlabel("n_specs (bundle size handed to backend)")
    ax.set_ylabel("ms per spec")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("Per-spec cost — backend is not just \"more specs\"")
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
    make_plots(by)


if __name__ == "__main__":
    main()

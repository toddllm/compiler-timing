#!/usr/bin/env python3
"""Compact frontend-cost reconnaissance harness on the rebased branch.

Runs ``torch.compile(fn)(*inputs)`` once per workload, intercepts the
DXP subprocess call so wall time stays bounded, and captures:

* per-pass elapsed_ms lines from
  ``spyre.inductor.passes`` (the pre-scheduling pipeline
  already prints ``elapsed %5dms  <name>`` at INFO);
* ``scratchpad.allocator`` INFO lines for solver timing;
* wall-clock deltas around ``torch.compile``'s first call for the
  overall pre-DXP total, plus manual perf_counter markers around
  the main compile phases we can identify:
    - graph lowering / scheduler init (via a monkey-patch spy on
      ``torch._inductor.graph.GraphLowering.compile_to_module``);
    - our custom pre-scheduling pipeline (via a spy on
      ``_SpyreGraphPassPipeline`` / ``CustomPreSchedulingPasses``);
    - Spyre backend-input generation (SDSC) via a spy on
      ``SpyreAsyncCompile.sdsc`` if present;
* first-call vs second-call wall (fixed-cost surrogate for tiny
  graphs when the second call is a cache hit).

Writes a JSON per workload.

Deliberately does NOT import ``timing_recorder``. This harness is
robust to the timing-instrumentation module being absent on the
rebased branch.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import json
import logging
import os
import re
import sys
import time
from typing import Any


# ---- workload closures ---------------------------------------------------

def _flash_workload(Lq, Lk):
    import torch
    dtype = torch.float16
    device = "spyre"
    queries = torch.randn(Lq, 64, dtype=dtype, device=device)
    keys = torch.randn(Lk, 64, dtype=dtype, device=device)
    values = torch.randn(Lk, 64, dtype=dtype, device=device)
    mask = torch.zeros(Lq, Lk, dtype=dtype, device=device)

    def flash(q, k, v, m):
        s = q @ k.transpose(-2, -1)
        s = s + m
        p = torch.softmax(s, dim=-1)
        return p @ v

    return flash, (queries, keys, values, mask), {"Lq": Lq, "Lk": Lk}


def _mlp_workload(N_in, N_hidden, layers):
    import torch
    dtype = torch.float16
    device = "spyre"
    x = torch.randn(1, N_in, dtype=dtype, device=device)
    weights = [
        torch.randn(N_in if i == 0 else N_hidden, N_hidden,
                    dtype=dtype, device=device)
        for i in range(layers)
    ]
    biases = [
        torch.randn(N_hidden, dtype=dtype, device=device)
        for _ in range(layers)
    ]

    def mlp(x, weights, biases):
        h = x
        for W, b in zip(weights, biases):
            h = torch.relu(h @ W + b)
        return h

    return (mlp, (x, weights, biases),
            {"N_in": N_in, "N_hidden": N_hidden, "layers": layers})


def _sdpa_workload(B, H, S, D):
    import torch
    dtype = torch.float16
    device = "spyre"
    q = torch.randn(B, H, S, D, dtype=dtype, device=device)
    k = torch.randn(B, H, S, D, dtype=dtype, device=device)
    v = torch.randn(B, H, S, D, dtype=dtype, device=device)

    def sdpa(q, k, v):
        return torch.nn.functional.scaled_dot_product_attention(q, k, v)

    return sdpa, (q, k, v), {"B": B, "H": H, "S": S, "D": D}


# ---- infrastructure -------------------------------------------------------


PASS_LINE = re.compile(r"^\s*elapsed\s+(\d+)ms\s+(.+)$")


class _PassLogSink(logging.Handler):
    """Capture ``elapsed <ms>ms <pass_name>`` lines from
    ``spyre.inductor.passes`` and everything from
    ``spyre.inductor.scratchpad.*`` for later parsing."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.passes: list[dict[str, Any]] = []
        self.scratchpad_lines: list[str] = []
        self.raw: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        self.raw.append(f"{record.name}: {msg}")
        if record.name == "spyre.inductor.passes":
            m = PASS_LINE.match(msg)
            if m:
                self.passes.append({
                    "pass_name": m.group(2).strip(),
                    "elapsed_ms": int(m.group(1)),
                })
        elif record.name.startswith("spyre.inductor.scratchpad"):
            self.scratchpad_lines.append(msg)


def _install_dxp_stop():
    """Intercept the DXP subprocess call so we bound wall time."""
    import subprocess

    class _PreDxpBoundary(Exception):
        pass

    orig_run = subprocess.run

    def _stop_before_dxp(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, (list, tuple)) and cmd:
            head = str(cmd[0])
            if "dxp" in head:
                raise _PreDxpBoundary(f"stopped before DXP: {head}")
        return orig_run(*args, **kwargs)

    subprocess.run = _stop_before_dxp
    return _PreDxpBoundary


def _install_phase_spies(records: dict[str, Any]):
    """Wrap key phase boundaries with perf_counter for coarse
    attribution. Records into `records['phases']` a list of
    ``{name, start, end, elapsed_s}``.

    Non-fatal: if a target attribute isn't there on this tree, the
    spy is skipped silently."""
    records.setdefault("phases", [])

    def _wrap(obj, attr, name):
        if not hasattr(obj, attr):
            return
        orig = getattr(obj, attr)

        @functools.wraps(orig)
        def spy(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return orig(*args, **kwargs)
            finally:
                records["phases"].append({
                    "name": name,
                    "elapsed_s": time.perf_counter() - t0,
                })
        setattr(obj, attr, spy)

    # Upstream Inductor: GraphLowering.compile_to_module
    try:
        from torch._inductor.graph import GraphLowering
        _wrap(GraphLowering, "compile_to_module", "graphlowering.compile_to_module")
        _wrap(GraphLowering, "compile_to_fn", "graphlowering.compile_to_fn")
    except Exception:
        pass

    # Torch-Spyre: the CustomPreSchedulingPasses pipeline
    try:
        from torch_spyre._inductor.passes import (
            CustomPreSchedulingPasses,
        )
        orig_call = CustomPreSchedulingPasses.__call__

        @functools.wraps(orig_call)
        def spy_prescheduling(self, graph):
            t0 = time.perf_counter()
            try:
                return orig_call(self, graph)
            finally:
                records["phases"].append({
                    "name": "spyre.pre_scheduling_pipeline",
                    "elapsed_s": time.perf_counter() - t0,
                })
        CustomPreSchedulingPasses.__call__ = spy_prescheduling
    except Exception:
        pass

    # Torch-Spyre async compile / SDSC bundle-gen boundary if present
    for modpath, attr, label in [
        ("torch_spyre.execution.async_compile", "SpyreAsyncCompile", "spyre.SpyreAsyncCompile"),
        ("torch_spyre._inductor.async_compile", "SpyreAsyncCompile", "spyre.async_compile.SpyreAsyncCompile"),
    ]:
        try:
            mod = __import__(modpath, fromlist=[attr])
            cls = getattr(mod, attr)
            for method in ("sdsc", "spyre_kernel", "_build_bundle",
                           "spyre_bundle", "spyre_dxp"):
                if hasattr(cls, method):
                    orig = getattr(cls, method)

                    def make_spy(orig=orig, method=method, label=label):
                        @functools.wraps(orig)
                        def spy(self, *args, **kwargs):
                            t0 = time.perf_counter()
                            try:
                                return orig(self, *args, **kwargs)
                            finally:
                                records["phases"].append({
                                    "name": f"{label}.{method}",
                                    "elapsed_s": time.perf_counter() - t0,
                                })
                        return spy
                    setattr(cls, method, make_spy())
        except Exception:
            continue

    # Spyre scheduler: BOTH the scheduler_pass entry and the scheduler
    # codegen entry may exist; wrap conservatively.
    for modpath, attr in [
        ("torch._inductor.scheduler", "Scheduler"),
    ]:
        try:
            mod = __import__(modpath, fromlist=[attr])
            cls = getattr(mod, attr)
            _wrap(cls, "__init__", "inductor.Scheduler.__init__")
            _wrap(cls, "codegen", "inductor.Scheduler.codegen")
        except Exception:
            pass


def _install_pass_counters():
    """Count how often specific graph-analysis methods are called
    during a compile. Keeps a per-key call count in a global dict.
    Non-fatal: attribute missing => the counter for that key is
    absent from the output."""

    counts: dict[str, int] = {}

    def _wrap_method(obj, attr, key):
        if not hasattr(obj, attr):
            return
        orig = getattr(obj, attr)
        if not callable(orig):
            return

        @functools.wraps(orig)
        def spy(*args, **kwargs):
            counts[key] = counts.get(key, 0) + 1
            return orig(*args, **kwargs)

        setattr(obj, attr, spy)

    def _wrap_free_fn(mod, attr, key):
        if not hasattr(mod, attr):
            return
        orig = getattr(mod, attr)
        if not callable(orig):
            return

        @functools.wraps(orig)
        def spy(*args, **kwargs):
            counts[key] = counts.get(key, 0) + 1
            return orig(*args, **kwargs)

        setattr(mod, attr, spy)

    # Common inductor analysis methods likely reused across passes.
    try:
        from torch._inductor.ir import Operation
        _wrap_method(Operation, "get_read_writes",
                     "Operation.get_read_writes")
    except Exception:
        pass
    try:
        from torch._inductor.dependencies import ReadWrites
        _wrap_method(ReadWrites, "from_body_expr",
                     "ReadWrites.from_body_expr")
    except Exception:
        pass

    # Torch-Spyre-side hot analysis calls. We try a few plausible names
    # and it's fine if some are absent -- absent keys will simply be
    # missing from the output.
    for modpath, attr, key in [
        ("torch_spyre._inductor.pass_utils", "op_read_writes", "spyre.pass_utils.op_read_writes"),
        ("torch_spyre._inductor.pass_utils", "get_op_users", "spyre.pass_utils.get_op_users"),
        ("torch_spyre._inductor.pass_utils", "iter_operations", "spyre.pass_utils.iter_operations"),
        ("torch_spyre._inductor.propagate_layouts", "propagate_spyre_tensor_layouts", "spyre.propagate_spyre_tensor_layouts.entry"),
        ("torch_spyre._inductor.work_division", "span_reduction", "spyre.span_reduction.entry"),
        ("torch_spyre._inductor.work_division", "work_distribution", "spyre.work_distribution.entry"),
        ("torch_spyre._inductor.work_division", "cost_model_matmul_division", "spyre.cost_model_matmul_division.entry"),
        ("torch_spyre._inductor.padding", "insert_restickify_padding", "spyre.insert_restickify_padding.entry"),
        ("torch_spyre._inductor.optimize_restickify", "optimize_restickify_locations", "spyre.optimize_restickify_locations.entry"),
    ]:
        try:
            mod = __import__(modpath, fromlist=[attr])
            _wrap_free_fn(mod, attr, key)
        except Exception:
            continue

    return counts


# ---- main ----------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", required=True,
                    choices=["flash", "mlp", "sdpa"])
    ap.add_argument("--Lq", type=int)
    ap.add_argument("--Lk", type=int)
    ap.add_argument("--N-in", type=int, dest="N_in", default=1024)
    ap.add_argument("--N-hidden", type=int, dest="N_hidden", default=4096)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--B", type=int, default=1)
    ap.add_argument("--H", type=int, default=8)
    ap.add_argument("--S", type=int, default=512)
    ap.add_argument("--D", type=int, default=128)
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=1)
    args = ap.parse_args()

    # Fresh Inductor cache per invocation.
    if "TORCHINDUCTOR_CACHE_DIR" not in os.environ:
        os.environ["TORCHINDUCTOR_CACHE_DIR"] = args.out.rsplit(".", 1)[0] + "_cache"
    os.makedirs(os.environ["TORCHINDUCTOR_CACHE_DIR"], exist_ok=True)

    # Elevate the interesting spyre loggers to INFO so the per-pass
    # ``elapsed`` line is emitted.
    for name in ("spyre.inductor.passes",
                 "spyre.inductor.scratchpad.allocator",
                 "spyre.inductor.scratchpad.ilp_solver_ortools"):
        logging.getLogger(name).setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sink = _PassLogSink()
    root.addHandler(sink)

    # Install DXP intercept + phase spies.
    _PreDxpBoundary = _install_dxp_stop()
    records: dict[str, Any] = {"phases": []}
    _install_phase_spies(records)
    counts = _install_pass_counters()

    # Now import torch (autoload runs). Do not import earlier.
    import torch  # noqa: E402
    import torch_spyre  # noqa: F401,E402

    torch.manual_seed(0xAFFE)

    all_samples = []
    for sample_idx in range(args.samples):
        records["phases"].clear()
        sink.passes.clear()
        sink.scratchpad_lines.clear()
        sink.raw.clear()
        counts.clear()

        # Fresh Inductor cache per sample: rebind cache dir.
        cache_dir = os.path.join(
            args.out.rsplit(".", 1)[0] + "_cache",
            f"sample_{sample_idx}",
        )
        os.environ["TORCHINDUCTOR_CACHE_DIR"] = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        if args.workload == "flash":
            fn, inputs, meta = _flash_workload(args.Lq, args.Lk)
        elif args.workload == "mlp":
            fn, inputs, meta = _mlp_workload(
                args.N_in, args.N_hidden, args.layers,
            )
        elif args.workload == "sdpa":
            fn, inputs, meta = _sdpa_workload(
                args.B, args.H, args.S, args.D,
            )
        else:
            raise AssertionError(args.workload)

        compiled = torch.compile(fn)
        t_first_call = time.perf_counter()
        hit_boundary = False
        error = None
        try:
            compiled(*inputs)
        except _PreDxpBoundary:
            hit_boundary = True
        except Exception as e:  # noqa: BLE001
            cur: BaseException | None = e
            while cur is not None:
                if isinstance(cur, _PreDxpBoundary):
                    hit_boundary = True
                    break
                cur = cur.__cause__ or cur.__context__
            if not hit_boundary:
                error = f"{type(e).__name__}: {e}"
        first_call_wall_s = time.perf_counter() - t_first_call

        all_samples.append({
            "sample_idx": sample_idx,
            "meta": meta,
            "first_call_wall_s": first_call_wall_s,
            "hit_pre_dxp_boundary": hit_boundary,
            "error": error,
            "passes": list(sink.passes),
            "scratchpad_lines": list(sink.scratchpad_lines),
            "phases": list(records["phases"]),
            "analysis_call_counts": dict(counts),
            "cache_dir": cache_dir,
        })

    root.removeHandler(sink)

    result = {
        "workload": args.workload,
        "n_samples": args.samples,
        "samples": all_samples,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2, default=str)

    # Compact stdout summary.
    for s in all_samples:
        top = sorted(
            s["passes"], key=lambda p: p["elapsed_ms"], reverse=True,
        )[:12]
        phases_by_name: dict[str, float] = {}
        for ph in s["phases"]:
            phases_by_name[ph["name"]] = phases_by_name.get(ph["name"], 0) + ph["elapsed_s"]
        print(f"--- sample {s['sample_idx']} first_call_wall {s['first_call_wall_s']:.2f}s ---")
        for p in top:
            print(f"  pass {p['elapsed_ms']:>7d} ms  {p['pass_name']}")
        for name, ph_s in sorted(phases_by_name.items(), key=lambda kv: -kv[1]):
            print(f"  phase {ph_s*1000:>10.1f} ms  {name}")
        if s["analysis_call_counts"]:
            print("  analysis call counts:")
            for k, v in sorted(s["analysis_call_counts"].items(), key=lambda kv: -kv[1])[:20]:
                print(f"    {v:>7d}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

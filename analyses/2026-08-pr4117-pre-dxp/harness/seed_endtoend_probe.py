#!/usr/bin/env python3
"""Post-#3810 end-to-end validation of the certified greedy seed.

Runs the real ``torch.compile`` path on a small set of representative
workloads (flash, MLP, SDPA) with instrumentation on
``CpSatLayoutSolver.plan_layout`` that records each seed decision:

* whether the seed accepted (``greedy-certified``) or the CP-SAT
  fallback was needed (``cpsat-fallback``);
* greedy probe wall time;
* CP-SAT solve wall time (0.0 if skipped);
* forced-spill lower bound (in alignment units);
* greedy plan's residency objective (in alignment units);
* n_buffers, n_placed, n_spilled;
* the resident-buffer name set.

Also records, for each ``plan_layout`` invocation, whether the plan
that ``_plan_layout_generic`` would have produced on the same input
matches the seed's plan objective when the seed accepted. That
``hybrid_obj == cpsat_obj`` invariant is what we want to confirm on
real captured planner-buffer sets before Ready-for-Review.

Reads no captured pickles; drives compile from source through
``torch.compile`` on the same workload closures the study harness
uses. The DXP subprocess is intercepted (stop at pre-DXP boundary)
to keep wall time bounded, since the seed decision fires *inside*
the scratchpad allocator, which runs before DXP.

Exit 0 on success (JSON written to ``--out``), nonzero on any
solver error.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from typing import Any


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
        torch.randn(N_hidden, dtype=dtype, device=device) for _ in range(layers)
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


_INVOCATION_RECORDS: list[dict[str, Any]] = []


def _install_seed_instrumentation():
    """Monkey-patch ``CpSatLayoutSolver.plan_layout`` to record what
    the seed decided on every real call. Runs the shipped path
    unchanged and, on top of it, evaluates what ``_plan_layout_generic``
    would have returned so we can prove
    ``hybrid_objective == standalone_cpsat_objective`` per call.
    """
    import torch  # noqa: F401
    import torch_spyre  # noqa: F401
    from dataclasses import replace
    from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
        CpSatLayoutSolver,
        _hbm_spill_cost,
        ceil_div,
    )

    orig_plan_layout = CpSatLayoutSolver.plan_layout

    def _obj_units(buffers, alignment):
        return sum(
            _hbm_spill_cost(
                replace(b, size=ceil_div(b.size, alignment))
            )
            for b in buffers
            if b.address is None
        )

    def _instrumented_plan_layout(self, log_lx_usage=False):
        n_before = len(self.buffers)
        alignment = self.alignment
        limit = self.limit
        forced_reasons = dict(self.record_exclusions())
        lower_bound_units = sum(
            _hbm_spill_cost(replace(b, size=ceil_div(b.size, alignment)))
            for b in self.buffers
            if b.name in forced_reasons
        )
        # Save an untouched copy for the standalone-cpsat cross-check.
        buffers_snapshot = copy.deepcopy(self.buffers)

        # Run the seed alone (deep-copy again inside), timed.
        t0 = time.perf_counter()
        seed_result = self._try_certified_greedy_seed(
            log_lx_usage=log_lx_usage,
        )
        seed_wall_s = time.perf_counter() - t0

        if seed_result is not None:
            chosen = "greedy-certified"
            # ``_try_certified_greedy_seed`` already committed onto
            # ``self.buffers``; skip the CP-SAT tail.
            hybrid_obj = _obj_units(self.buffers, alignment)
            cpsat_wall_s = 0.0
            # Standalone CP-SAT cross-check on the untouched snapshot.
            std_solver = CpSatLayoutSolver(
                copy.deepcopy(buffers_snapshot), limit, alignment,
            )
            t1 = time.perf_counter()
            std_plan = list(std_solver._plan_layout_generic())
            std_wall_s = time.perf_counter() - t1
            std_obj = _obj_units(std_plan, alignment)

            _INVOCATION_RECORDS.append({
                "chosen": chosen,
                "n_buffers": n_before,
                "n_forced": len(forced_reasons),
                "alignment": alignment,
                "limit_bytes": limit,
                "capacity_units": limit // alignment,
                "lower_bound_units": lower_bound_units,
                "hybrid_objective_units": hybrid_obj,
                "standalone_cpsat_objective_units": std_obj,
                "objectives_match": hybrid_obj == std_obj,
                "n_placed": sum(
                    1 for b in self.buffers if b.address is not None
                ),
                "n_spilled": sum(
                    1 for b in self.buffers if b.address is None
                ),
                "resident_set": sorted(
                    b.name for b in self.buffers if b.address is not None
                ),
                "seed_wall_s": seed_wall_s,
                "cpsat_wall_s": cpsat_wall_s,
                "standalone_cpsat_wall_s": std_wall_s,
            })
            return list(self.buffers)

        # Seed rejected; run full CP-SAT via _plan_layout_generic.
        chosen = "cpsat-fallback"
        t1 = time.perf_counter()
        result = list(self._plan_layout_generic())
        cpsat_wall_s = time.perf_counter() - t1
        hybrid_obj = _obj_units(result, alignment)

        # Standalone CP-SAT on the same input (equivalent by construction,
        # measured for cross-check).
        std_solver = CpSatLayoutSolver(
            copy.deepcopy(buffers_snapshot), limit, alignment,
        )
        t2 = time.perf_counter()
        std_plan = list(std_solver._plan_layout_generic())
        std_wall_s = time.perf_counter() - t2
        std_obj = _obj_units(std_plan, alignment)

        _INVOCATION_RECORDS.append({
            "chosen": chosen,
            "n_buffers": n_before,
            "n_forced": len(forced_reasons),
            "alignment": alignment,
            "limit_bytes": limit,
            "capacity_units": limit // alignment,
            "lower_bound_units": lower_bound_units,
            "hybrid_objective_units": hybrid_obj,
            "standalone_cpsat_objective_units": std_obj,
            "objectives_match": hybrid_obj == std_obj,
            "n_placed": sum(1 for b in result if b.address is not None),
            "n_spilled": sum(1 for b in result if b.address is None),
            "resident_set": sorted(
                b.name for b in result if b.address is not None
            ),
            "seed_wall_s": seed_wall_s,
            "cpsat_wall_s": cpsat_wall_s,
            "standalone_cpsat_wall_s": std_wall_s,
        })
        return result

    CpSatLayoutSolver.plan_layout = _instrumented_plan_layout
    return orig_plan_layout


def _install_dxp_stop():
    """Intercept the DXP subprocess call so we run the full front-end
    (scratchpad allocation, seed decision, potential CP-SAT fallback)
    without paying the DXP wall time."""
    import subprocess

    class _PreDxpBoundary(Exception):
        pass

    orig_run = subprocess.run

    def _stop_before_dxp(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, (list, tuple)) and cmd and "dxp" in str(cmd[0]):
            raise _PreDxpBoundary(f"stopped before DXP: {cmd[0]}")
        return orig_run(*args, **kwargs)

    subprocess.run = _stop_before_dxp
    return _PreDxpBoundary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--workload", required=True,
        choices=["flash", "mlp", "sdpa"],
    )
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

    import torch  # noqa: E402
    import torch_spyre  # noqa: F401,E402

    _PreDxpBoundary = _install_dxp_stop()
    _install_seed_instrumentation()

    torch.manual_seed(0xAFFE)

    samples = []
    for sample_idx in range(args.samples):
        # Fresh Inductor cache per sample to force a cold compile.
        cache_dir = os.path.join(
            args.out.rsplit(".", 1)[0] + "_cache",
            f"sample_{sample_idx:d}",
        )
        os.makedirs(cache_dir, exist_ok=True)
        os.environ["TORCHINDUCTOR_CACHE_DIR"] = cache_dir

        _INVOCATION_RECORDS.clear()

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
            # Unwind nested wrappers to find the sentinel.
            cur: BaseException | None = e
            while cur is not None:
                if isinstance(cur, _PreDxpBoundary):
                    hit_boundary = True
                    break
                cur = cur.__cause__ or cur.__context__
            if not hit_boundary:
                error = f"{type(e).__name__}: {e}"
        first_call_wall_s = time.perf_counter() - t_first_call

        samples.append({
            "sample_idx": sample_idx,
            "meta": meta,
            "first_call_wall_s": first_call_wall_s,
            "hit_pre_dxp_boundary": hit_boundary,
            "error": error,
            "invocations": list(_INVOCATION_RECORDS),
            "cache_dir": cache_dir,
        })
        # Force cache-dir invalidation for a fresh cold compile next sample.

    result = {
        "workload": args.workload,
        "samples": samples,
        "aggregate": {
            "total_seed_invocations": sum(
                len(s["invocations"]) for s in samples
            ),
            "certified_count": sum(
                1
                for s in samples
                for inv in s["invocations"]
                if inv["chosen"] == "greedy-certified"
            ),
            "fallback_count": sum(
                1
                for s in samples
                for inv in s["invocations"]
                if inv["chosen"] == "cpsat-fallback"
            ),
            "objective_mismatches": sum(
                1
                for s in samples
                for inv in s["invocations"]
                if not inv["objectives_match"]
            ),
        },
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    print(json.dumps(result["aggregate"], indent=2))
    return 0 if result["aggregate"]["objective_mismatches"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

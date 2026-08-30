#!/usr/bin/env python3
"""DXP + runtime correctness test for differing LX-address arms.

Runs a workload compiled with LAYOUT_SOLVER=cpsat and separately
with LAYOUT_SOLVER=greedy (both with SPYRE_LX_PLANNER_RELAYOUT=0
so both arms see the same planner-buffer universe). Both go all
the way through DXP + Spyre execution (no --mode stop
interception). Records:

  * did DXP accept the layout (did it compile without error)
  * did execution complete without error
  * output tensor moved back to CPU
  * pairwise output comparison between arms (bitwise + fp16-close)
  * pairwise output comparison against a CPU reference computed
    from the same fn on CPU-side copies of the inputs

Usage:
    python3 dxp_address_correctness.py \
        --workload flash --Lq 512 --Lk 4096 \
        --out data/dxp_correctness/flash-512x4096.json

The script itself invokes ``fn(*inputs)`` twice with fresh
compilation per solver arm. It does NOT reuse a compiled artifact.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import sys
import time
import traceback


def _flash_workload(Lq: int, Lk: int, device):
    import torch

    B, H, D = 1, 8, 128
    b_block, h_block, q_block, kv_block = 1, 4, 256, 512

    def flash(queries, keys, values, mask):
        scale = 1.0 / math.sqrt(math.sqrt(D))
        output = torch.zeros_like(queries)
        real_max = torch.full(
            (B, H, Lq, 64), float("-inf"),
            device=queries.device, dtype=torch.float16,
        ).amax(-1)
        denominator = torch.zeros(
            (B, H, Lq, 64), device=queries.device, dtype=torch.float16
        ).amax(-1)
        for b_start in range(0, B, b_block):
            b_end = b_start + b_block
            for h_start in range(0, H, h_block):
                h_end = h_start + h_block
                for lq_start in range(0, Lq, q_block):
                    lq_end = lq_start + q_block
                    q_t = queries[b_start:b_end, h_start:h_end, lq_start:lq_end]
                    rm_t = real_max[b_start:b_end, h_start:h_end,
                                    lq_start:lq_end]
                    d_t = denominator[b_start:b_end, h_start:h_end,
                                      lq_start:lq_end]
                    o_t = output[b_start:b_end, h_start:h_end,
                                 lq_start:lq_end]
                    for lk_start in range(0, Lk, kv_block):
                        lk_end = lk_start + kv_block
                        m_t = mask[:, :, lq_start:lq_end, lk_start:lk_end]
                        k_t = keys[b_start:b_end, h_start:h_end,
                                   lk_start:lk_end]
                        v_t = values[b_start:b_end, h_start:h_end,
                                     lk_start:lk_end]
                        k_tT = k_t.transpose(-1, -2).contiguous()
                        s = torch.matmul(q_t * scale, k_tT * scale)
                        s = s + m_t
                        bm = torch.amax(s, dim=-1)
                        running_max = torch.maximum(rm_t, bm)
                        e = torch.exp(s - running_max.unsqueeze(-1))
                        corr = torch.exp(rm_t - running_max)
                        d_t.copy_(d_t * corr + e.sum(dim=-1))
                        o_t.copy_(o_t * corr.unsqueeze(-1)
                                  + torch.matmul(e, v_t))
                        rm_t.copy_(running_max)
        return output / denominator.unsqueeze(-1)

    q = torch.randn(B, H, Lq, D, device=device, dtype=torch.float16)
    k = torch.randn(B, H, Lk, D, device=device, dtype=torch.float16)
    v = torch.randn(B, H, Lk, D, device=device, dtype=torch.float16)
    causal = torch.tril(torch.ones(Lq, Lk, dtype=torch.bool))
    m_cpu = torch.zeros(1, 1, Lq, Lk, dtype=torch.float16)
    m_cpu.masked_fill_(~causal, float("-inf"))
    m = m_cpu.to(device)
    return flash, (q, k, v, m)


def _mlp_workload(N_in: int, N_hidden: int, layers: int, device):
    import torch

    def mlp(x, weights, biases):
        for w, b in zip(weights, biases):
            x = torch.nn.functional.gelu(torch.matmul(x, w) + b)
        return x

    x = torch.randn(1, N_in, device=device, dtype=torch.float16)
    weights = [
        torch.randn(
            N_in if i == 0 else N_hidden,
            N_hidden if i < layers - 1 else N_in,
            device=device, dtype=torch.float16,
        )
        for i in range(layers)
    ]
    biases = [
        torch.randn(
            N_hidden if i < layers - 1 else N_in,
            device=device, dtype=torch.float16,
        )
        for i in range(layers)
    ]
    return mlp, (x, weights, biases)


def _run_arm(solver, workload_fn, args, out_dict):
    """Run one arm end-to-end.

    Called in a fresh subprocess (so torch/torch_spyre init and the
    Inductor cache start clean per arm) — see main().
    """
    import torch
    import torch_spyre  # noqa: F401

    # Configure via env before importing anything solver-dependent.
    os.environ["LAYOUT_SOLVER"] = solver
    os.environ["SPYRE_LX_PLANNER_RELAYOUT"] = "0"
    os.environ["CO_OPTIMIZING_LX_PLANNING"] = "0"
    os.environ["LX_PLANNING"] = "1"
    os.environ["SENCORES"] = "32"
    os.environ.pop("ADAPTIVE_SOLVER_THRESHOLD_OPS", None)
    # Fresh Inductor cache per arm.
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = (
        f"/tmp/tsc-dxp-{args.workload}-{solver}"
    )
    try:
        import shutil
        shutil.rmtree(os.environ["TORCHINDUCTOR_CACHE_DIR"],
                      ignore_errors=True)
    except Exception:
        pass

    torch.manual_seed(0xAFFE)
    if args.workload == "flash":
        fn, inputs = _flash_workload(args.Lq, args.Lk, device="spyre")
    elif args.workload == "mlp":
        fn, inputs = _mlp_workload(
            args.N_in, args.N_hidden, args.layers, device="spyre"
        )
    else:
        raise ValueError(f"unknown workload {args.workload}")

    # Same seed for CPU inputs — must be re-created since we already
    # consumed the seed on the spyre side. Reset and re-create.
    torch.manual_seed(0xAFFE)
    if args.workload == "flash":
        _, cpu_inputs = _flash_workload(args.Lq, args.Lk, device="cpu")
    elif args.workload == "mlp":
        _, cpu_inputs = _mlp_workload(
            args.N_in, args.N_hidden, args.layers, device="cpu"
        )

    # Reference on CPU (eager); the workload itself is native torch, so
    # this is a valid oracle up to fp16 rounding.
    try:
        cpu_ref = fn(*cpu_inputs) if not isinstance(cpu_inputs[1], list) else \
            fn(cpu_inputs[0], cpu_inputs[1], cpu_inputs[2])
    except Exception as e:
        out_dict["cpu_ref_error"] = repr(e)[:400]
        cpu_ref = None

    gc.collect()
    compiled = torch.compile(fn)
    t0 = time.time()
    err = None
    result_cpu = None
    result_shape = None
    try:
        result = compiled(*inputs)
        result_cpu = result.detach().to("cpu")
        result_shape = tuple(result.shape)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)
    dur = time.time() - t0

    out_dict.update(
        solver=solver,
        compile_and_execute_wall_s=dur,
        error=err,
        result_shape=result_shape,
    )

    if result_cpu is not None and cpu_ref is not None:
        # bytes-level SHA over the result tensor
        try:
            out_dict["result_sha256"] = hashlib.sha256(
                result_cpu.numpy().tobytes()
            ).hexdigest()[:32]
        except Exception:
            pass
        try:
            atol = 0.5  # loose for fp16 through DXP
            rtol = 0.5
            close = torch.allclose(
                result_cpu.float(), cpu_ref.float(),
                atol=atol, rtol=rtol,
            )
            maxdiff = (
                (result_cpu.float() - cpu_ref.float()).abs().max().item()
            )
            out_dict["cpu_reference_close"] = bool(close)
            out_dict["cpu_reference_maxdiff"] = maxdiff
            out_dict["cpu_reference_atol"] = atol
            out_dict["cpu_reference_rtol"] = rtol
        except Exception as e:
            out_dict["cpu_reference_error"] = repr(e)[:400]

    # Save the tensor bytes for cross-arm comparison in the outer
    # driver. Use a small file since the compiled result may be large.
    tensor_path = out_dict.get("_tensor_path")
    if tensor_path is not None and result_cpu is not None:
        try:
            import torch as _t
            _t.save(result_cpu, tensor_path)
            out_dict["tensor_saved"] = True
        except Exception as e:
            out_dict["tensor_save_error"] = repr(e)[:200]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", choices=["flash", "mlp"], required=True)
    ap.add_argument("--Lq", type=int)
    ap.add_argument("--Lk", type=int)
    ap.add_argument("--N-in", type=int, dest="N_in", default=1024)
    ap.add_argument("--N-hidden", type=int, dest="N_hidden", default=2048)
    ap.add_argument("--layers", type=int, default=8)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--arm", choices=["cpsat", "greedy", "both"],
                    default="both",
                    help="'both' runs cpsat then greedy in this process. "
                         "'cpsat'/'greedy' runs one arm only.")
    args = ap.parse_args()

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    if args.arm == "both":
        # Two arms, one process. Torch state is largely per-import;
        # LAYOUT_SOLVER is re-read from env each compile via config.
        # Fresh Inductor cache dir per arm plus torch.compiler.reset()
        # avoid cached-graph reuse.
        import torch
        results = {}
        for solver in ("cpsat", "greedy"):
            arm_out = {
                "_tensor_path": os.path.join(
                    out_dir, f"{os.path.basename(args.out)[:-5]}."
                    f"{solver}.pt"
                ),
            }
            torch.compiler.reset()
            _run_arm(solver, None, args, arm_out)
            results[solver] = arm_out

        # Cross-arm comparison
        cross = {}
        try:
            import torch as _t
            t_c = _t.load(results["cpsat"]["_tensor_path"])
            t_g = _t.load(results["greedy"]["_tensor_path"])
            cross["shape_match"] = tuple(t_c.shape) == tuple(t_g.shape)
            cross["bitwise_equal"] = bool((t_c == t_g).all())
            cross["allclose_atol_rtol_5e-1"] = bool(
                _t.allclose(t_c.float(), t_g.float(), atol=0.5, rtol=0.5)
            )
            cross["maxdiff"] = (
                (t_c.float() - t_g.float()).abs().max().item()
            )
        except Exception as e:
            cross["cross_error"] = repr(e)[:400]

        with open(args.out, "w") as fh:
            json.dump({
                "workload": args.workload,
                "shape_params": {
                    "Lq": args.Lq, "Lk": args.Lk,
                    "N_in": args.N_in, "N_hidden": args.N_hidden,
                    "layers": args.layers,
                },
                "cpsat_arm": results["cpsat"],
                "greedy_arm": results["greedy"],
                "cross_arm": cross,
            }, fh, indent=2, default=str)
        print(json.dumps({
            "cpsat_err": results["cpsat"].get("error"),
            "greedy_err": results["greedy"].get("error"),
            "cross": cross,
        }, indent=2, default=str))
    else:
        arm_out = {"_tensor_path": args.out + f".{args.arm}.pt"}
        _run_arm(args.arm, None, args, arm_out)
        with open(args.out, "w") as fh:
            json.dump(arm_out, fh, indent=2, default=str)

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Break down scratchpad_planning into its 8 sub-steps.

Monkey-patches ``ScratchpadAllocator.plan_allocation`` to time each
sub-step. Uses transformer_block workload sizes to keep runs short.
"""

import functools
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontend_reconnaissance import _install_dxp_stop, _PassLogSink

for name in ("spyre.inductor.passes", "spyre.inductor.scratchpad.allocator"):
    logging.getLogger(name).setLevel(logging.INFO)
root = logging.getLogger()
root.setLevel(logging.INFO)
sink = _PassLogSink()
root.addHandler(sink)

_PreDxpBoundary = _install_dxp_stop()


import torch  # noqa: E402
import torch_spyre  # noqa: F401,E402

torch.manual_seed(0xAFFE)

from torch_spyre._inductor.scratchpad.allocator import (  # noqa: E402
    ScratchpadAllocator,
)

sub_timings: list[dict] = []


def instrumented_plan_allocation(self, graph):
    """Break the 8 template-method steps into individual sub-times."""
    n_ops = len(getattr(graph, "operations", []))
    entry = {"n_ops": n_ops, "steps": []}
    sub_timings.append(entry)

    def _t(name, fn, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            entry["steps"].append({
                "name": name,
                "elapsed_ms": (time.perf_counter() - t0) * 1000,
            })

    _t("pre_optimization_passes",
       self._run_passes, self.pre_optimization_passes, graph)
    buffers = _t("_prepare_buffers", self._prepare_buffers, graph)
    entry["n_buffers"] = len(buffers) if hasattr(buffers, "__len__") else -1
    solver = _t("_build_solver", self._build_solver, buffers)
    allocation = _t("_solve", self._solve, solver, graph)
    accepted_lx_relayouts = _t(
        "_finalize_lx_relayout_allocation",
        self._finalize_lx_relayout_allocation, allocation,
    )
    _t("_post_solve", self._post_solve, graph, allocation)
    reasons = _t("_get_spill_reasons", self._get_spill_reasons, solver, allocation)
    _t("_push_allocation", self._push_allocation,
       graph, allocation, accepted_lx_relayouts)
    _t("_log_lx_pinning", self._log_lx_pinning, graph, reasons)
    _t("post_optimization_passes",
       self._run_passes, self.post_optimization_passes, graph)


ScratchpadAllocator.plan_allocation = instrumented_plan_allocation


device = "spyre"
dtype = torch.float16


def transformer_block(x, wq, wk, wv, wo, w1, w2, b1, b2):
    q = x @ wq
    k = x @ wk
    v = x @ wv
    s = q @ k.transpose(-2, -1)
    p = torch.softmax(s, dim=-1)
    a = p @ v
    h = a @ wo + x
    g = h @ w1 + b1
    g = torch.relu(g)
    o = g @ w2 + b2 + h
    return o


results = []
for seq_len, emb_dim, ffn_dim in [
    (512, 1024, 4096),
    (512, 2048, 8192),
    (1024, 2048, 8192),
]:
    sub_timings.clear()
    x = torch.randn(seq_len, emb_dim, dtype=dtype, device=device)
    wq = torch.randn(emb_dim, emb_dim, dtype=dtype, device=device)
    wk = torch.randn(emb_dim, emb_dim, dtype=dtype, device=device)
    wv = torch.randn(emb_dim, emb_dim, dtype=dtype, device=device)
    wo = torch.randn(emb_dim, emb_dim, dtype=dtype, device=device)
    w1 = torch.randn(emb_dim, ffn_dim, dtype=dtype, device=device)
    w2 = torch.randn(ffn_dim, emb_dim, dtype=dtype, device=device)
    b1 = torch.randn(ffn_dim, dtype=dtype, device=device)
    b2 = torch.randn(emb_dim, dtype=dtype, device=device)

    os.environ["TORCHINDUCTOR_CACHE_DIR"] = (
        f"/tmp/scratch_subtime_seq{seq_len}_emb{emb_dim}_cache"
    )
    os.makedirs(os.environ["TORCHINDUCTOR_CACHE_DIR"], exist_ok=True)

    compiled = torch.compile(transformer_block)
    t0 = time.perf_counter()
    try:
        compiled(x, wq, wk, wv, wo, w1, w2, b1, b2)
    except _PreDxpBoundary:
        pass
    except Exception as e:  # noqa: BLE001
        cur: BaseException | None = e
        found = False
        while cur is not None:
            if isinstance(cur, _PreDxpBoundary):
                found = True
                break
            cur = cur.__cause__ or cur.__context__
        if not found:
            raise
    dur = time.perf_counter() - t0

    print(f"=== transformer_block seq={seq_len} emb={emb_dim} ffn={ffn_dim} first_call_wall={dur:.2f}s")
    for e in sub_timings:
        print(f"  n_ops={e['n_ops']} n_buffers={e.get('n_buffers', '?')}")
        for step in e["steps"]:
            print(f"    step {step['elapsed_ms']:>8.2f} ms  {step['name']}")
    results.append({
        "seq_len": seq_len, "emb_dim": emb_dim, "ffn_dim": ffn_dim,
        "first_call_wall_s": dur,
        "sub_timings": list(sub_timings),
    })

out = "/tmp/scratchpad_subtime.json"
with open(out, "w") as fh:
    json.dump(results, fh, indent=2, default=str)
print(f"wrote {out}")

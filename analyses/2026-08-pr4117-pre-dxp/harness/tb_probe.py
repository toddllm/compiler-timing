"""Transformer-block probe: bigger stand-alone graph than flash/mlp/sdpa."""

import functools
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontend_reconnaissance import (  # noqa: E402
    _install_dxp_stop,
    _install_phase_spies,
    _install_pass_counters,
    _PassLogSink,
)

for name in (
    "spyre.inductor.passes",
    "spyre.inductor.scratchpad.allocator",
    "spyre.inductor.scratchpad.ilp_solver_ortools",
):
    logging.getLogger(name).setLevel(logging.INFO)
root = logging.getLogger()
root.setLevel(logging.INFO)
sink = _PassLogSink()
root.addHandler(sink)

_PreDxpBoundary = _install_dxp_stop()
records: dict = {"phases": []}
_install_phase_spies(records)
counts = _install_pass_counters()

import torch  # noqa: E402
import torch_spyre  # noqa: F401,E402

torch.manual_seed(0xAFFE)
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


seq_len = int(os.environ.get("SEQ_LEN", 512))
emb_dim = int(os.environ.get("EMB_DIM", 1024))
ffn_dim = int(os.environ.get("FFN_DIM", 4096))

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
    f"/tmp/recon/tb_seq{seq_len}_emb{emb_dim}_cache"
)
os.makedirs(os.environ["TORCHINDUCTOR_CACHE_DIR"], exist_ok=True)

compiled = torch.compile(transformer_block)
t0 = time.perf_counter()
hit = False
err = None
try:
    compiled(x, wq, wk, wv, wo, w1, w2, b1, b2)
except _PreDxpBoundary:
    hit = True
except Exception as e:  # noqa: BLE001
    cur: BaseException | None = e
    while cur is not None:
        if isinstance(cur, _PreDxpBoundary):
            hit = True
            break
        cur = cur.__cause__ or cur.__context__
    if not hit:
        err = f"{type(e).__name__}: {e}"
dur = time.perf_counter() - t0

print(f"=== transformer_block seq_len={seq_len} emb_dim={emb_dim} ffn_dim={ffn_dim} ===")
print(f"first_call_wall {dur:.2f}s  hit_pre_dxp={hit}  err={err}")
print(f"passes captured: {len(sink.passes)}")
for p in sorted(sink.passes, key=lambda x: -x["elapsed_ms"])[:15]:
    print(f"  pass {p['elapsed_ms']:>7d} ms  {p['pass_name']}")
phase_totals: dict = {}
for ph in records["phases"]:
    phase_totals[ph["name"]] = phase_totals.get(ph["name"], 0) + ph["elapsed_s"]
for name, tot in sorted(phase_totals.items(), key=lambda kv: -kv[1]):
    print(f"  phase {tot*1000:>10.1f} ms  {name}")
print("analysis counts:")
for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:15]:
    print(f"  {v:>7d}  {k}")
print("--- scratchpad lines ---")
for line in sink.scratchpad_lines[:40]:
    print(f"  {line}")

result = {
    "meta": {"seq_len": seq_len, "emb_dim": emb_dim, "ffn_dim": ffn_dim},
    "first_call_wall_s": dur,
    "hit_pre_dxp": hit,
    "err": err,
    "passes": sink.passes,
    "phases": records["phases"],
    "analysis_call_counts": counts,
    "scratchpad_lines": sink.scratchpad_lines,
}
out = f"/tmp/recon/tb_seq{seq_len}_emb{emb_dim}.json"
with open(out, "w") as fh:
    json.dump(result, fh, indent=2, default=str)
print(f"wrote {out}")

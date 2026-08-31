"""Decompose SDSC/bundle-gen path.

Times: find_unimplemented, generate_bundle (both passes),
build_kernel_provenance_descriptor. Also counts n_specs per call
and the number of _compile_specs entries emitted.
"""

import functools
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontend_reconnaissance import _install_dxp_stop, _PassLogSink  # noqa: E402

for name in ("spyre.inductor.passes",):
    logging.getLogger(name).setLevel(logging.INFO)
root = logging.getLogger()
root.setLevel(logging.INFO)
sink = _PassLogSink()
root.addHandler(sink)
_PreDxpBoundary = _install_dxp_stop()

import torch  # noqa: E402
import torch_spyre  # noqa: F401,E402


records: dict = {"sdsc_calls": []}

from torch_spyre.execution.async_compile import SpyreAsyncCompile  # noqa: E402
from torch_spyre._inductor.codegen import bundle as bundle_mod  # noqa: E402
from torch_spyre._inductor import kernel_provenance as kp_mod  # noqa: E402
from torch_spyre._inductor.op_spec import find_unimplemented as _fu  # noqa: E402

orig_sdsc = SpyreAsyncCompile.sdsc
orig_generate_bundle = bundle_mod.generate_bundle
orig_kp = kp_mod.build_kernel_provenance_descriptor


def spy_sdsc(self, kernel_name, specs, pool_size=0):
    specs_list = list(specs)
    entry = {"kernel_name": kernel_name, "n_specs": len(specs_list),
             "steps": []}

    t_find_unimp = time.perf_counter()
    _ = _fu(specs_list)
    entry["steps"].append({"name": "find_unimplemented",
                           "elapsed_ms": (time.perf_counter() - t_find_unimp) * 1000})
    records["sdsc_calls"].append(entry)
    return orig_sdsc(self, kernel_name, specs_list, pool_size=pool_size)


def spy_generate_bundle(kernel_name, output_dir, specs, pool_size=0):
    specs_list = list(specs)
    entry = records["sdsc_calls"][-1]
    entry["output_dir"] = output_dir
    t0 = time.perf_counter()
    try:
        return orig_generate_bundle(kernel_name, output_dir, specs_list, pool_size=pool_size)
    finally:
        entry["steps"].append({"name": "generate_bundle",
                               "elapsed_ms": (time.perf_counter() - t0) * 1000})


def spy_kp(specs):
    entry = records["sdsc_calls"][-1]
    t0 = time.perf_counter()
    try:
        return orig_kp(specs)
    finally:
        entry["steps"].append({"name": "build_kernel_provenance_descriptor",
                               "elapsed_ms": (time.perf_counter() - t0) * 1000})


SpyreAsyncCompile.sdsc = spy_sdsc
bundle_mod.generate_bundle = spy_generate_bundle
kp_mod.build_kernel_provenance_descriptor = spy_kp

# Also time the two passes inside generate_bundle: _compile_specs and
# bundle.mlir emission. We do this by wrapping _compile_specs and by
# capturing the file-open around bundle.mlir.
orig_compile_specs = bundle_mod._compile_specs


def spy_compile_specs(*args, **kwargs):
    entry = records["sdsc_calls"][-1]
    t0 = time.perf_counter()
    try:
        return orig_compile_specs(*args, **kwargs)
    finally:
        entry["steps"].append({"name": "_compile_specs (Pass 1)",
                               "elapsed_ms": (time.perf_counter() - t0) * 1000})


bundle_mod._compile_specs = spy_compile_specs


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
for seq_len, emb_dim, ffn_dim in [(512, 1024, 4096)]:  # single working config
    records["sdsc_calls"].clear()
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
        f"/tmp/sdsc_subtime_seq{seq_len}_emb{emb_dim}_cache"
    )
    os.makedirs(os.environ["TORCHINDUCTOR_CACHE_DIR"], exist_ok=True)

    compiled = torch.compile(transformer_block)
    t0 = time.perf_counter()
    try:
        compiled(x, wq, wk, wv, wo, w1, w2, b1, b2)
    except _PreDxpBoundary:
        pass
    except Exception as e:
        cur = e
        found = False
        while cur is not None:
            if isinstance(cur, _PreDxpBoundary):
                found = True
                break
            cur = cur.__cause__ or cur.__context__
        if not found:
            raise
    dur = time.perf_counter() - t0

    print(f"=== transformer_block seq={seq_len} emb={emb_dim} wall={dur:.2f}s")
    for c in records["sdsc_calls"]:
        print(f"  sdsc call kernel={c['kernel_name']} n_specs={c['n_specs']}")
        for s in c["steps"]:
            print(f"    step {s['elapsed_ms']:>8.2f} ms  {s['name']}")

    results.append({
        "seq_len": seq_len, "emb_dim": emb_dim, "ffn_dim": ffn_dim,
        "first_call_wall_s": dur,
        "sdsc_calls": list(records["sdsc_calls"]),
    })

out = "/tmp/sdsc_subtime.json"
with open(out, "w") as fh:
    json.dump(results, fh, indent=2, default=str)
print(f"wrote {out}")

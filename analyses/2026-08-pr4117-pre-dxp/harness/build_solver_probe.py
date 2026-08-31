"""Isolate whether _build_solver's cost is one-time OR-Tools import
or per-call CpSatLayoutSolver construction."""

import logging
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontend_reconnaissance import _install_dxp_stop  # noqa: E402

for name in ("spyre.inductor.passes",):
    logging.getLogger(name).setLevel(logging.INFO)

_PreDxpBoundary = _install_dxp_stop()

import torch  # noqa: E402
import torch_spyre  # noqa: F401,E402

# --- Time the OR-Tools import in isolation ---
t0 = time.perf_counter()
from ortools.sat.python import cp_model, cp_model_helper  # noqa: F401,E402

t_ortools_import = time.perf_counter() - t0
print(f"ortools import (first): {t_ortools_import*1000:.2f} ms")

# Import again -- should be near-zero (module already cached)
t0 = time.perf_counter()
from ortools.sat.python import cp_model as _cp2  # noqa: F401,E402

t_ortools_reimport = time.perf_counter() - t0
print(f"ortools import (second): {t_ortools_reimport*1000:.2f} ms")

# --- Time CpSatLayoutSolver import in isolation ---
t0 = time.perf_counter()
from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (  # noqa: E402
    CpSatLayoutSolver,
)
t_ilp_import = time.perf_counter() - t0
print(f"ilp_solver_ortools import: {t_ilp_import*1000:.2f} ms")

# --- Time _make_cpsat_solver first vs second call ---
from torch_spyre._inductor.scratchpad.allocator import (  # noqa: E402
    _make_cpsat_solver,
)
from torch_spyre._inductor.scratchpad.plan_solver import (  # noqa: E402
    LifetimeBoundBuffer,
)

def _mk_buffers(n):
    return [
        LifetimeBoundBuffer(f"b{i}", 1024, [i, i + 2])
        for i in range(n)
    ]

for round_idx in range(3):
    bufs = _mk_buffers(30)
    t0 = time.perf_counter()
    solver = _make_cpsat_solver(bufs, 100_000)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"_make_cpsat_solver call {round_idx}: {elapsed:.2f} ms")

# --- What does compile_to_module trigger BEFORE the first plan_allocation? ---
# Force one torch.compile and time the first plan_allocation call.
from torch_spyre._inductor.scratchpad.allocator import (  # noqa: E402
    ScratchpadAllocator,
)

call_times: list = []
orig = ScratchpadAllocator.plan_allocation

def wrap(self, graph):
    t0 = time.perf_counter()
    try:
        return orig(self, graph)
    finally:
        call_times.append((time.perf_counter() - t0) * 1000)

ScratchpadAllocator.plan_allocation = wrap


device = "spyre"
dtype = torch.float16


def small_flash(q, k, v, m):
    s = q @ k.transpose(-2, -1) + m
    p = torch.softmax(s, dim=-1)
    return p @ v


q = torch.randn(256, 64, dtype=dtype, device=device)
k = torch.randn(256, 64, dtype=dtype, device=device)
v = torch.randn(256, 64, dtype=dtype, device=device)
m = torch.zeros(256, 256, dtype=dtype, device=device)

os.environ["TORCHINDUCTOR_CACHE_DIR"] = "/tmp/build_solver_probe_cache"
os.makedirs(os.environ["TORCHINDUCTOR_CACHE_DIR"], exist_ok=True)

compiled = torch.compile(small_flash)
t0 = time.perf_counter()
try:
    compiled(q, k, v, m)
except _PreDxpBoundary:
    pass
except Exception as e:
    cur = e
    while cur is not None:
        if isinstance(cur, _PreDxpBoundary):
            break
        cur = cur.__cause__ or cur.__context__
first_compile_wall = time.perf_counter() - t0

print(f"first_compile_wall: {first_compile_wall:.3f} s")
for i, t in enumerate(call_times):
    print(f"  plan_allocation call {i}: {t:.2f} ms")

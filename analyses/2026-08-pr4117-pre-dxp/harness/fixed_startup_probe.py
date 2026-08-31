"""Decompose the fixed per-compile cost.

Compiles a trivial 1-op function (torch.relu on a 1-element tensor)
and times every phase we can identify. This bounds the fixed cost
that ANY compile pays regardless of graph size.
"""

import functools
import logging
import os
import sys
import time

t_start_wall = time.perf_counter()

# Detailed step-by-step timing before any imports
def step(label):
    now = time.perf_counter()
    print(f"[{now - t_start_wall:6.3f}s] {label}")

step("starting")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontend_reconnaissance import _install_dxp_stop  # noqa: E402

step("frontend_reconnaissance imported")

for name in ("spyre.inductor.passes",):
    logging.getLogger(name).setLevel(logging.INFO)

_PreDxpBoundary = _install_dxp_stop()
step("DXP stop installed")

import torch
step("torch imported")

import torch_spyre  # noqa: F401
step("torch_spyre imported")

# Cold-import inductor pieces before compile
import torch._inductor  # noqa: F401
step("torch._inductor imported")

from torch._inductor.graph import GraphLowering  # noqa: F401
step("GraphLowering imported")

# Cold-import the pieces the compile will need
from torch_spyre._inductor.scratchpad.allocator import (  # noqa: F401,E402
    _make_cpsat_solver, scratchpad_planning,
)
step("scratchpad.allocator imported")

# Sub-time inside compile too
phases = {}


def wrap(cls, method, key):
    if not hasattr(cls, method):
        return
    orig = getattr(cls, method)

    @functools.wraps(orig)
    def spy(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return orig(*args, **kwargs)
        finally:
            phases.setdefault(key, []).append(
                (time.perf_counter() - t0) * 1000
            )

    setattr(cls, method, spy)


wrap(GraphLowering, "compile_to_module", "GraphLowering.compile_to_module")
wrap(GraphLowering, "_compile_to_module", "GraphLowering._compile_to_module")
wrap(GraphLowering, "codegen", "GraphLowering.codegen")
wrap(GraphLowering, "codegen_with_cpp_wrapper", "GraphLowering.codegen_with_cpp_wrapper")

from torch._inductor.scheduler import Scheduler  # noqa: E402
wrap(Scheduler, "__init__", "Scheduler.__init__")
wrap(Scheduler, "codegen", "Scheduler.codegen")

# Wrap async_compile if it exists
try:
    from torch_spyre.execution.async_compile import SpyreAsyncCompile
    for m in ("sdsc", "spyre_kernel", "_build_bundle", "spyre_bundle", "spyre_dxp"):
        wrap(SpyreAsyncCompile, m, f"SpyreAsyncCompile.{m}")
except Exception:
    pass

step("wrappers installed")

# The trivial function: no matmuls, no attention, one op
device = "spyre"
dtype = torch.float16
x = torch.randn(1, dtype=dtype, device=device)
step("input allocated")


def trivial(x):
    return torch.relu(x)


os.environ["TORCHINDUCTOR_CACHE_DIR"] = "/tmp/fixed_startup_probe_cache"
os.makedirs(os.environ["TORCHINDUCTOR_CACHE_DIR"], exist_ok=True)

compiled = torch.compile(trivial)
step("torch.compile wrapper created")

t0 = time.perf_counter()
try:
    compiled(x)
except _PreDxpBoundary:
    pass
except Exception as e:
    cur = e
    while cur is not None:
        if isinstance(cur, _PreDxpBoundary):
            break
        cur = cur.__cause__ or cur.__context__
first_call_wall = time.perf_counter() - t0
step(f"first compiled call done ({first_call_wall:.3f}s)")

# Second call: should be near-zero (cache)
t0 = time.perf_counter()
try:
    compiled(x)
except _PreDxpBoundary:
    pass
except Exception:
    pass
second_call_wall = time.perf_counter() - t0
step(f"second call ({second_call_wall*1000:.1f} ms)")

print()
print("--- phase breakdown ---")
for key in sorted(phases, key=lambda k: -sum(phases[k])):
    times = phases[key]
    print(f"  {sum(times):>10.1f} ms  ({len(times)} calls)  {key}")

print()
print(f"total wall since script start: {time.perf_counter() - t_start_wall:.3f} s")
print(f"first_call_wall: {first_call_wall:.3f} s")
print(f"second_call_wall: {second_call_wall*1000:.2f} ms")

# Copyright 2025-2026 The Torch-Spyre Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Additional timing boundaries for the parts of compile_fx that live
above the Spyre custom pass pipelines.

Wraps three methods at class level:

- ``torch._inductor.graph.GraphLowering.run`` — upstream Inductor
  FX → IR lowering. Records the input FX node count as event metadata.
- ``torch._inductor.graph.GraphLowering.compile_to_fn`` — upstream
  Inductor codegen (wrapper generation, kernel codegen dispatch).
  Records the number of operations in the lowered graph.
- ``torch_spyre._inductor.spyre_kernel.SpyreKernel.codegen_kernel`` —
  Spyre-specific per-kernel codegen invoked from compile_to_fn.

Gated on ``TORCH_SPYRE_TIMING=1``. When the flag is unset,
``install_extra_timers()`` is a no-op and none of the wrappers are
attached; the class-level methods remain the originals.

Together with the pipeline-level timers already recorded, these three
boundaries let ``unattributed_compile_fx`` be decomposed into upstream
lowering, upstream codegen, per-kernel codegen, and the AOTAutograd
prelude that runs before ``GraphLowering.run`` fires.
"""

from __future__ import annotations

import functools

from . import timing_recorder as _tr


_INSTALLED = False


def install_extra_timers() -> None:
    """Wrap GraphLowering.run, GraphLowering.compile_to_fn, and
    SpyreKernel.codegen_kernel with timing_recorder.stage(...) calls.

    Safe to call multiple times: the second call is a no-op.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    if not _tr.is_enabled():
        # No point installing wrappers that would compile to _NullRegion
        # (and no point paying attribute lookup on the hot path).
        _INSTALLED = True
        return

    from torch._inductor.graph import GraphLowering
    from torch_spyre._inductor.spyre_kernel import SpyreKernel

    _orig_run = GraphLowering.run

    @functools.wraps(_orig_run)
    def _timed_run(self, *args, **kwargs):
        n_nodes = 0
        try:
            n_nodes = len(list(self.module.graph.nodes))
        except Exception:
            pass
        with _tr.stage("graphlowering_run", n_fx_nodes=n_nodes):
            return _orig_run(self, *args, **kwargs)

    GraphLowering.run = _timed_run

    _orig_compile_to_fn = GraphLowering.compile_to_fn

    @functools.wraps(_orig_compile_to_fn)
    def _timed_compile_to_fn(self, *args, **kwargs):
        n_ops = 0
        try:
            n_ops = len(self.operations)
        except Exception:
            pass
        with _tr.stage("graphlowering_compile_to_fn", n_operations=n_ops):
            return _orig_compile_to_fn(self, *args, **kwargs)

    GraphLowering.compile_to_fn = _timed_compile_to_fn

    _orig_codegen_kernel = SpyreKernel.codegen_kernel

    @functools.wraps(_orig_codegen_kernel)
    def _timed_codegen_kernel(self, *args, **kwargs):
        with _tr.stage("spyre_kernel_codegen"):
            return _orig_codegen_kernel(self, *args, **kwargs)

    SpyreKernel.codegen_kernel = _timed_codegen_kernel

    _INSTALLED = True


__all__ = ["install_extra_timers"]

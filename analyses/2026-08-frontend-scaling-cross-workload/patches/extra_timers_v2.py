# Copyright 2025-2026 The Torch-Spyre Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
Additional timing hooks for upstream Inductor boundaries.

Wraps GraphLowering.run (AOTAutograd → IR lowering),
GraphLowering.codegen (scheduling + Spyre pipelines + kernel codegen +
wrapper generation), and SpyreKernel.codegen_kernel with
timing_recorder.stage(...) calls.

Gated on TORCH_SPYRE_TIMING=1 via the timing_recorder module. When the
flag is off, install_extra_timers() is a no-op and none of the
wrappers are attached.
"""

from __future__ import annotations

import functools

from . import timing_recorder as _tr


_INSTALLED = False


def install_extra_timers() -> None:
    """Wrap upstream Inductor boundaries with timing_recorder stages.

    Safe to call multiple times: the second call is a no-op.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    if not _tr.is_enabled():
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

    _orig_codegen = GraphLowering.codegen

    @functools.wraps(_orig_codegen)
    def _timed_codegen(self, *args, **kwargs):
        n_ops = 0
        try:
            n_ops = len(self.operations)
        except Exception:
            pass
        with _tr.stage("graphlowering_codegen", n_operations=n_ops):
            return _orig_codegen(self, *args, **kwargs)

    GraphLowering.codegen = _timed_codegen

    _orig_codegen_kernel = SpyreKernel.codegen_kernel

    @functools.wraps(_orig_codegen_kernel)
    def _timed_codegen_kernel(self, *args, **kwargs):
        with _tr.stage("spyre_kernel_codegen"):
            return _orig_codegen_kernel(self, *args, **kwargs)

    SpyreKernel.codegen_kernel = _timed_codegen_kernel

    _INSTALLED = True


__all__ = ["install_extra_timers"]

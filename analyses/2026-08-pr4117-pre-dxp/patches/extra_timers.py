# Copyright 2025-2026 The Torch-Spyre Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Additional timing boundaries for the parts of compile_fx that live
above the Spyre custom pass pipelines.

The custom pass pipelines are already instrumented from
``passes.py``; the wrappers here bracket upstream Inductor methods
plus torch-Spyre-side codegen so the analyzer never has to derive
an interval by subtraction.

Wrapped at class level (all no-ops when ``TORCH_SPYRE_TIMING`` is
unset):

- ``torch._inductor.graph.GraphLowering.run`` — upstream Inductor
  FX → IR lowering. Records the input FX node count.
- ``torch._inductor.graph.GraphLowering.compile_to_module`` —
  upstream Inductor codegen driver (calls ``codegen`` then produces
  the Python wrapper module). Records the number of operations in
  the lowered graph. Renamed from ``compile_to_fn`` in torch 2.13.
- ``torch._inductor.graph.GraphLowering._compile_to_module_lines`` —
  imports and executes the generated Python wrapper module (via
  ``PyCodeCache.load_by_key_path``). On this frozen torch-spyre
  build the wrapper's module body calls
  ``async_compile.sdsc(...)`` synchronously, so ``sdsc_total``,
  ``sdsc_bundle_gen``, ``kernel_provenance`` and ``dxp_standalone``
  all fire inside this bracket. Recorded as ``wrapper_module_exec``
  so the analyzer can attribute SDSC by timestamp containment
  rather than by hard-coded parentage.
- ``torch._inductor.graph.GraphLowering.codegen`` — the upstream
  method that calls ``_update_scheduler`` (Spyre pre-scheduling
  fires inside there) and then ``scheduler.codegen()``.
- ``torch._inductor.scheduler.Scheduler.__init__`` — Scheduler
  construction: also fires ``_pre_fusion_custom_pass`` (Spyre's
  ``CustomPreFusionPasses``), upstream fusion, and
  ``_post_fusion_custom_pass`` (Spyre's ``CustomPostFusionPasses``).
  Direct measurement so the analyzer does not have to derive it.
- ``torch._inductor.scheduler.Scheduler.codegen`` — Scheduler-driven
  per-node codegen dispatch.
- ``torch_spyre._inductor.spyre_kernel.SpyreKernel.codegen_kernel``
  — Spyre-specific per-kernel codegen invoked from
  ``Scheduler.codegen``.
- ``torch_spyre._inductor.wrapper.SpyrePythonWrapperCodegen.generate``
  — the Python wrapper module emission called from
  ``compile_to_module``.

Together these boundaries cover the "compile_to_module interior" that
the previous framework had to derive by subtraction.
"""

from __future__ import annotations

import functools

from . import timing_recorder as _tr


_INSTALLED = False


def install_extra_timers() -> None:
    """Wrap the timing boundaries listed in the module docstring.

    Safe to call multiple times: the second call is a no-op.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    if not _tr.is_enabled():
        _INSTALLED = True
        return

    from torch._inductor.graph import GraphLowering
    from torch._inductor.scheduler import Scheduler
    from torch_spyre._inductor.spyre_kernel import SpyreKernel

    # ---- GraphLowering.run ------------------------------------------------
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

    # ---- GraphLowering.compile_to_module -------------------------------------
    _orig_compile_to_module = GraphLowering.compile_to_module

    @functools.wraps(_orig_compile_to_module)
    def _timed_compile_to_module(self, *args, **kwargs):
        n_ops = 0
        try:
            n_ops = len(self.operations)
        except Exception:
            pass
        with _tr.stage("graphlowering_compile_to_module", n_operations=n_ops):
            return _orig_compile_to_module(self, *args, **kwargs)

    GraphLowering.compile_to_module = _timed_compile_to_module

    # ---- GraphLowering._compile_to_module_lines --------------------------
    # This is the point where PyCodeCache.load_by_key_path imports and
    # executes the generated Python wrapper module. That module's body
    # calls SpyreAsyncCompile.sdsc(...) at import time, so
    # sdsc_total / sdsc_bundle_gen / kernel_provenance / dxp_standalone
    # all fire inside this bracket.
    if hasattr(GraphLowering, "_compile_to_module_lines"):
        _orig_ctml = GraphLowering._compile_to_module_lines

        @functools.wraps(_orig_ctml)
        def _timed_ctml(self, *args, **kwargs):
            with _tr.stage("wrapper_module_exec"):
                return _orig_ctml(self, *args, **kwargs)

        GraphLowering._compile_to_module_lines = _timed_ctml

    # ---- GraphLowering.codegen -------------------------------------------
    _orig_gl_codegen = GraphLowering.codegen

    @functools.wraps(_orig_gl_codegen)
    def _timed_gl_codegen(self, *args, **kwargs):
        n_ops = 0
        try:
            n_ops = len(self.operations)
        except Exception:
            pass
        with _tr.stage("graphlowering_codegen", n_operations=n_ops):
            return _orig_gl_codegen(self, *args, **kwargs)

    GraphLowering.codegen = _timed_gl_codegen

    # ---- Scheduler.__init__ ----------------------------------------------
    # Fusion (upstream + CustomPreFusion + CustomPostFusion) happens here.
    _orig_sched_init = Scheduler.__init__

    @functools.wraps(_orig_sched_init)
    def _timed_sched_init(self, nodes, *args, **kwargs):
        n_nodes = 0
        try:
            n_nodes = len(nodes)
        except Exception:
            pass
        with _tr.stage("scheduler_init", input_nodes=n_nodes):
            return _orig_sched_init(self, nodes, *args, **kwargs)

    Scheduler.__init__ = _timed_sched_init

    # ---- Scheduler.codegen -----------------------------------------------
    _orig_sched_codegen = Scheduler.codegen

    @functools.wraps(_orig_sched_codegen)
    def _timed_sched_codegen(self, *args, **kwargs):
        n_nodes = 0
        try:
            n_nodes = len(self.nodes)
        except Exception:
            pass
        with _tr.stage("scheduler_codegen", scheduler_nodes=n_nodes):
            return _orig_sched_codegen(self, *args, **kwargs)

    Scheduler.codegen = _timed_sched_codegen

    # ---- SpyreKernel.codegen_kernel --------------------------------------
    _orig_codegen_kernel = SpyreKernel.codegen_kernel

    @functools.wraps(_orig_codegen_kernel)
    def _timed_codegen_kernel(self, *args, **kwargs):
        with _tr.stage("spyre_kernel_codegen"):
            return _orig_codegen_kernel(self, *args, **kwargs)

    SpyreKernel.codegen_kernel = _timed_codegen_kernel

    # ---- PythonWrapperCodegen.generate (upstream) ------------------------
    # Wrap the upstream base so both SpyrePythonWrapperCodegen and
    # SpyreSubgraphPythonWrapperCodegen instances are timed. In a Spyre
    # compile every wrapper is a Spyre subclass, so the "wrapper_codegen"
    # event unambiguously belongs to the Spyre path.
    try:
        from torch._inductor.codegen.wrapper import PythonWrapperCodegen

        _orig_wrapper_generate = PythonWrapperCodegen.generate

        @functools.wraps(_orig_wrapper_generate)
        def _timed_wrapper_generate(self, *args, **kwargs):
            with _tr.stage(
                "wrapper_codegen",
                wrapper_cls=type(self).__name__,
            ):
                return _orig_wrapper_generate(self, *args, **kwargs)

        PythonWrapperCodegen.generate = _timed_wrapper_generate
    except (ImportError, AttributeError):
        # If the class or method moves, do not fail — analyzer treats
        # an absent event as "not measured".
        pass

    # ---- ScratchpadAllocator.plan_allocation ------------------------------
    # For the A/B solver comparison we want to distinguish:
    #   * total scratchpad_planning time (already timed via passes.py pass
    #     event `_maybe_scratchpad_planning`);
    #   * per-phase inside plan_allocation: prepare_buffers, solve,
    #     post_solve. These are directly observable via the template method
    #     hooks in ScratchpadAllocator.plan_allocation.
    #   * chosen solver class + number of buffers.
    try:
        from torch_spyre._inductor.scratchpad.allocator import (
            ScratchpadAllocator,
        )
        _orig_plan_allocation = ScratchpadAllocator.plan_allocation

        @functools.wraps(_orig_plan_allocation)
        def _timed_plan_allocation(self, graph, *args, **kwargs):
            # Solver class comes from the layout_planning factory attached
            # to `self` — record it so the report doesn't have to look it
            # up from config.
            layout_planning = getattr(self, "layout_planning", None)
            solver_name = getattr(
                layout_planning, "__name__",
                type(layout_planning).__name__ if layout_planning else "<none>",
            )
            allocator_cls = type(self).__name__
            with _tr.stage(
                "scratchpad_plan_allocation",
                allocator_cls=allocator_cls,
                solver_factory=solver_name,
            ) as ev:
                # Override the hook methods on this instance so we can time
                # each phase. Save originals; restore in finally.
                orig_prepare = self._prepare_buffers
                orig_build = self._build_solver
                orig_solve = self._solve
                orig_post = self._post_solve
                captured = {"n_buffers": None, "solver_cls": None}

                def _timed_prepare(g):
                    with _tr.stage("scratchpad_prepare_buffers"):
                        bufs = orig_prepare(g)
                    try:
                        captured["n_buffers"] = len(bufs)
                    except Exception:
                        pass
                    return bufs

                def _timed_build(bufs):
                    with _tr.stage("scratchpad_build_solver"):
                        solver = orig_build(bufs)
                    captured["solver_cls"] = type(solver).__name__
                    return solver

                def _timed_solve(solver):
                    with _tr.stage(
                        "scratchpad_solve",
                        solver_cls=type(solver).__name__,
                    ):
                        return orig_solve(solver)

                def _timed_post(g, allocation):
                    with _tr.stage("scratchpad_post_solve"):
                        return orig_post(g, allocation)

                self._prepare_buffers = _timed_prepare
                self._build_solver = _timed_build
                self._solve = _timed_solve
                self._post_solve = _timed_post
                try:
                    result = _orig_plan_allocation(self, graph, *args, **kwargs)
                finally:
                    self._prepare_buffers = orig_prepare
                    self._build_solver = orig_build
                    self._solve = orig_solve
                    self._post_solve = orig_post
                if ev is not None:
                    ev.meta["n_buffers"] = captured["n_buffers"]
                    ev.meta["solver_cls"] = captured["solver_cls"]
                return result

        ScratchpadAllocator.plan_allocation = _timed_plan_allocation
    except (ImportError, AttributeError):
        pass

    _INSTALLED = True


__all__ = ["install_extra_timers"]

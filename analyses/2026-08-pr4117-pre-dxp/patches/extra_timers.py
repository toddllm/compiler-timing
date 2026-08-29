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
    #   * chosen solver class + planner_buffers + eligible/barred counts
    #   * placed vs spilled counts and bytes, from the solver's own state
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
                captured: dict = {}

                def _timed_prepare(g):
                    with _tr.stage("scratchpad_prepare_buffers"):
                        bufs = orig_prepare(g)
                    try:
                        captured["planner_buffers"] = len(bufs)
                    except Exception:
                        pass
                    # Canonical input signature — the buffer universe the
                    # solver sees, independent of solver identity.
                    # Under SPYRE_LX_PLANNER_RELAYOUT=0 both cpsat and greedy
                    # must observe the same signature; the A/B assertion
                    # tests this.
                    try:
                        sig = []
                        for b in bufs:
                            sig.append({
                                "name": b.name,
                                "size": b.size,
                                "uses": list(b.uses),
                                "first_use_is_read": b.first_use_is_read,
                                "residency_reason": b.residency_reason,
                                "in_place_parents": list(b.in_place_parents),
                                "lifetime_end_override": (
                                    b.lifetime_end_override
                                ),
                                "n_paired_with": len(b.paired_with),
                                "n_lx_relayout_plans": (
                                    len(b.lx_relayout_plans)
                                ),
                            })
                        captured["planner_buffer_signature"] = sig
                    except Exception as e:
                        captured["planner_signature_error"] = repr(e)[:200]
                    return bufs

                def _timed_build(bufs):
                    with _tr.stage("scratchpad_build_solver"):
                        solver = orig_build(bufs)
                    captured["solver_cls"] = type(solver).__name__
                    captured["lx_capacity_bytes"] = getattr(solver, "limit", None)
                    captured["alignment"] = getattr(solver, "alignment", None)
                    # Ask the solver to compute its own eligibility partition
                    # (this is the same partition() the greedy path uses; for
                    # CP-SAT the solve loop calls record_exclusions() itself,
                    # so a preview here is cheap and non-mutating).
                    try:
                        excluded = solver.record_exclusions()
                        captured["eligible_buffers"] = (
                            len(solver.buffers) - len(excluded)
                        )
                        captured["barred_buffers"] = len(excluded)
                        # Reset spill_reasons so we don't double-record; the
                        # solve loop rebuilds it.
                        solver.spill_reasons = {}
                    except Exception as e:
                        captured["eligibility_probe_error"] = repr(e)[:200]
                    return solver

                def _timed_solve(solver):
                    with _tr.stage(
                        "scratchpad_solve",
                        solver_cls=type(solver).__name__,
                    ):
                        allocation = orig_solve(solver)
                    # Placed / spilled counts and bytes come from the
                    # allocation and the solver's spill_reasons map.
                    try:
                        n_placed = sum(
                            1 for b in allocation if b.address is not None
                        )
                        n_spilled = sum(
                            1 for b in allocation if b.address is None
                        )
                        bytes_placed = sum(
                            b.size for b in allocation
                            if b.address is not None
                        )
                        bytes_spilled = sum(
                            b.size for b in allocation
                            if b.address is None
                        )
                        captured["placed_in_lx"] = n_placed
                        captured["spilled_from_lx"] = n_spilled
                        captured["bytes_placed_in_lx"] = bytes_placed
                        captured["bytes_spilled_from_lx"] = bytes_spilled
                        # Group spill reasons: the sentinel used by
                        # CP-SAT is "solver chose to spill this buffer";
                        # everything else is a pre-solve barred reason.
                        from collections import Counter
                        reason_counts = Counter(
                            (solver.spill_reasons or {}).values()
                        )
                        captured["spill_reason_histogram"] = dict(reason_counts)
                        # Placed / spilled name signature: two solvers can
                        # differ on WHICH buffers get in even if counts
                        # match. Record both as sorted (name, size) tuples
                        # so the diff between arms is inspectable.
                        placed = sorted(
                            (b.name, b.size) for b in allocation
                            if b.address is not None
                        )
                        spilled = sorted(
                            (b.name, b.size) for b in allocation
                            if b.address is None
                        )
                        captured["placed_signature"] = placed
                        captured["spilled_signature"] = spilled
                    except Exception as e:
                        captured["placement_probe_error"] = repr(e)[:200]
                    # For CP-SAT: pick up solver stats stashed by our
                    # _run wrapper below (if the solver class was patched).
                    stats = getattr(solver, "_ab_last_solver_stats", None)
                    if stats is not None:
                        captured["ortools_stats"] = stats
                    all_stats = getattr(
                        solver, "_ab_all_solver_stats", None
                    )
                    if all_stats is not None:
                        captured["ortools_all_solves"] = all_stats
                    model_size = getattr(solver, "_ab_model_size", None)
                    if model_size is not None:
                        captured["cpsat_model_size"] = model_size
                    return allocation

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
                    for k, v in captured.items():
                        ev.meta[k] = v
                return result

        ScratchpadAllocator.plan_allocation = _timed_plan_allocation
    except (ImportError, AttributeError):
        pass

    # ---- CpSatLayoutSolver phase decomposition ---------------------------
    # Instrument the CP-SAT model-build phases individually so we can see
    # whether the observed solve-time growth is in model construction,
    # OR-Tools presolve/propagation, or actual search.
    try:
        from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
            CpSatLayoutSolver,
        )
        from ortools.sat.python import cp_model  # noqa: F401

        # Wrap the model-construction phases.
        for _method_name, _stage_name in [
            ("_add_inplace_relaxation", "cpsat_add_inplace_relaxation"),
            ("_add_core_division", "cpsat_add_core_division"),
            ("_add_no_overlap_2d", "cpsat_add_no_overlap_2d"),
            ("_extract", "cpsat_extract"),
        ]:
            if not hasattr(CpSatLayoutSolver, _method_name):
                continue
            _orig_method = getattr(CpSatLayoutSolver, _method_name)

            def _make_timed(orig, stage):
                @functools.wraps(orig)
                def _timed(self, *args, **kwargs):
                    with _tr.stage(stage):
                        return orig(self, *args, **kwargs)
                return _timed

            setattr(CpSatLayoutSolver, _method_name,
                    _make_timed(_orig_method, _stage_name))

        # Wrap the buffer-wrapping loop (called as a dict comprehension in
        # _plan_layout_generic, so we instrument _plan_layout_generic itself
        # to bracket "cpsat_wrap_buffers" around the working-dict build).
        _orig_plan_generic = CpSatLayoutSolver._plan_layout_generic

        @functools.wraps(_orig_plan_generic)
        def _timed_plan_generic(self, *args, **kwargs):
            # Overlay _wrap with a timed version for the duration of this
            # call, so we get "cpsat_wrap_buffers" = total per-buffer wrap
            # time this compile. Also emits a model-size summary event once
            # every phase has built its constraints.
            orig_wrap = self._wrap
            wrap_stats = {"n_wrapped": 0}

            def _wrapper(model, buffer):
                wrap_stats["n_wrapped"] += 1
                return orig_wrap(model, buffer)

            # Time buffer-wrapping via a class-level attribute so the
            # dict-comprehension in the base method picks up our stub.
            self._wrap = _wrapper  # type: ignore[assignment]
            try:
                with _tr.stage(
                    "cpsat_plan_layout_generic",
                    n_buffers=len(self.buffers),
                ) as plan_ev:
                    # Manual timing around the wrap step: measure until
                    # forced_reasons is computed and model is created. The
                    # base _plan_layout_generic does:
                    #   forced_reasons = self.record_exclusions()
                    #   model = cp_model.CpModel()
                    #   working = {b.name: self._wrap(model, b) ...}
                    #   solved = self._run(model, working, forced_reasons)
                    # So we time cpsat_wrap_buffers by wrapping _run to fire
                    # its own stage first, capturing model-size right at the
                    # boundary between build and solve.
                    result = _orig_plan_generic(self, *args, **kwargs)
                # Best-effort: record how many buffers went through _wrap.
                if plan_ev is not None:
                    plan_ev.meta["n_wrapped"] = wrap_stats["n_wrapped"]
                return result
            finally:
                self._wrap = orig_wrap  # type: ignore[assignment]

        CpSatLayoutSolver._plan_layout_generic = _timed_plan_generic

        # Wrap _run to (a) time each Solve() individually, (b) capture
        # model-size metrics, (c) stash per-solve stats.
        _orig_cpsat_run = CpSatLayoutSolver._run

        @functools.wraps(_orig_cpsat_run)
        def _timed_cpsat_run(self, model, tensors, forced_reasons):
            from ortools.sat.python import cp_model
            solves: list[dict] = []
            _orig_solve_cls = cp_model.CpSolver.Solve

            def _tracked_solve(cp_solver, mdl):
                stats: dict = {}
                # Emit a per-Solve() stage event so wall/self time from the
                # timing recorder matches OR-Tools' own WallTime.
                phase = f"cpsat_solve[{len(solves) + 1}]"
                with _tr.stage(phase) as _ev:
                    status = _orig_solve_cls(cp_solver, mdl)
                try:
                    stats["status"] = cp_solver.StatusName(status)
                    stats["walltime_s"] = cp_solver.WallTime()
                    stats["usertime_s"] = cp_solver.UserTime()
                    stats["objective_value"] = cp_solver.ObjectiveValue()
                    try:
                        stats["best_objective_bound"] = (
                            cp_solver.BestObjectiveBound()
                        )
                    except Exception:
                        pass
                    for attr in (
                        "NumBranches", "NumConflicts",
                        "NumBooleans", "NumBinaryPropagations",
                        "NumIntegerPropagations", "NumRestarts",
                    ):
                        try:
                            stats[attr.lower().replace("num", "num_")] = (
                                getattr(cp_solver, attr)()
                            )
                        except Exception:
                            pass
                    try:
                        stats["deterministic_time"] = (
                            cp_solver.parameters.deterministic_time
                        )
                    except Exception:
                        pass
                    stats["num_workers"] = (
                        cp_solver.parameters.num_search_workers
                    )
                    stats["max_time_in_seconds"] = (
                        cp_solver.parameters.max_time_in_seconds
                    )
                except Exception as e:
                    stats["stats_error"] = repr(e)[:200]
                solves.append(stats)
                if _ev is not None:
                    _ev.meta["status"] = stats.get("status")
                    _ev.meta["walltime_s"] = stats.get("walltime_s")
                    _ev.meta["num_branches"] = stats.get("num_branches")
                    _ev.meta["num_conflicts"] = stats.get("num_conflicts")
                return status

            cp_model.CpSolver.Solve = _tracked_solve
            try:
                # Emit a model-size event just after _run's constraint
                # builders return, before the first Solve. To do that with
                # minimal invasion we peek at the model after _run finishes;
                # the numbers are cumulative (single model, all constraints
                # already added). If we can, capture pre-first-solve too.
                #
                # Simpler approach: attach a stage inside the wrap of
                # _add_no_overlap_2d that snapshots model size right after
                # it returns. That stage already brackets the last
                # constraint-add call, so capture there.
                return _orig_cpsat_run(self, model, tensors, forced_reasons)
            finally:
                cp_model.CpSolver.Solve = _orig_solve_cls
                # Save all per-solve stats + a model-size snapshot.
                model_size: dict = {}
                try:
                    proto = model.Proto()
                    model_size["num_variables"] = len(proto.variables)
                    model_size["num_constraints"] = len(proto.constraints)
                    # Serialized size as a proxy for total model bulk.
                    try:
                        model_size["proto_bytes"] = proto.ByteSize()
                    except Exception:
                        pass
                    # Count no_overlap_2d and no_overlap constraints
                    # separately — those are the placement rectangles.
                    n_nooverlap2d = 0
                    n_nooverlap = 0
                    n_interval = 0
                    n_bool_or = 0
                    for c in proto.constraints:
                        which = c.WhichOneof("constraint")
                        if which == "no_overlap_2d":
                            n_nooverlap2d += 1
                        elif which == "no_overlap":
                            n_nooverlap += 1
                        elif which == "interval":
                            n_interval += 1
                        elif which == "bool_or":
                            n_bool_or += 1
                    model_size["num_no_overlap_2d"] = n_nooverlap2d
                    model_size["num_no_overlap"] = n_nooverlap
                    model_size["num_interval"] = n_interval
                    model_size["num_bool_or"] = n_bool_or
                    model_size["num_tensors"] = len(tensors)
                    model_size["num_forced_reasons"] = len(forced_reasons)
                except Exception as e:
                    model_size["proto_error"] = repr(e)[:200]
                self._ab_last_solver_stats = solves[-1] if solves else {}
                self._ab_all_solver_stats = solves
                self._ab_model_size = model_size

        CpSatLayoutSolver._run = _timed_cpsat_run
    except (ImportError, AttributeError):
        # ortools unavailable or class moved — leave CP-SAT stats unrecorded.
        pass

    _INSTALLED = True


__all__ = ["install_extra_timers"]

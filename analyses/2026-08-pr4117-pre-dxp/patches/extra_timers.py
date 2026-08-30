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




def _compute_structural_metrics(buffers):
    """Deterministic structural metrics over a LifetimeBoundBuffer set.

    Computed once from the buffer universe both solvers see (arm B /
    RELAYOUT=0 makes this the same universe for cpsat and greedy). All
    quantities are pure functions of the buffer set — they do not depend
    on any solver decision.

    Returns a dict of scalar metrics; empty dict on any error.
    """
    try:
        n_buf = len(buffers)
        if n_buf == 0:
            return {"planner_buffers": 0}
        # -- times --
        times = set()
        for b in buffers:
            if not b.uses:
                continue
            times.add(b.start_time)
            times.add(b.end_time)
        sorted_times = sorted(times)
        n_transition = len(sorted_times)
        # -- lifetimes --
        spans = [(b.start_time, b.end_time, b.size) for b in buffers if b.uses]
        total_lifetime_ticks = sum(e - s for s, e, _ in spans)
        # -- simultaneously-live buffer count & bytes per tick --
        live_counts = []
        live_bytes = []
        for t in sorted_times:
            cnt = 0
            byt = 0
            for s, e, sz in spans:
                if s <= t < e:
                    cnt += 1
                    byt += sz
            live_counts.append(cnt)
            live_bytes.append(byt)
        max_live = max(live_counts) if live_counts else 0
        mean_live = (sum(live_counts) / len(live_counts)) if live_counts else 0.0
        max_live_bytes = max(live_bytes) if live_bytes else 0
        mean_live_bytes = (sum(live_bytes) / len(live_bytes)) if live_bytes else 0.0
        # live-set area — sum over transitions of (live_count *
        # tick_duration). Discrete integral of the live-count curve.
        live_area = 0
        for i, t in enumerate(sorted_times):
            width = (sorted_times[i + 1] - t) if i + 1 < len(sorted_times) else 1
            live_area += live_counts[i] * width
        # -- lifetime-overlap pairs (unordered pair count) --
        # Use a sweep: at each transition, add C(live,2) - C(prev_live,2)
        # is wrong for pair count; the correct count is the number of
        # unordered pairs (i, j) whose lifetimes overlap. Compute
        # directly by sweeping starts/ends.
        events = []
        for s, e, _ in spans:
            events.append((s, 0))  # start
            events.append((e, 1))  # end
        events.sort()
        cur_live = 0
        n_overlap_pairs = 0
        for tick, kind in events:
            if kind == 0:
                # a new buffer overlaps with all currently live
                n_overlap_pairs += cur_live
                cur_live += 1
            else:
                cur_live -= 1
        # -- overlap density = pairs / C(n, 2) --
        denom = n_buf * (n_buf - 1) / 2 if n_buf >= 2 else 0
        overlap_density = (n_overlap_pairs / denom) if denom else 0.0
        # -- in-place edges --
        in_place_edges = sum(len(b.in_place_parents) for b in buffers)
        # -- size distribution --
        sizes = sorted(b.size for b in buffers)
        median_size = sizes[len(sizes) // 2] if sizes else 0
        p90_size = sizes[int(0.9 * (len(sizes) - 1))] if sizes else 0
        max_size = sizes[-1] if sizes else 0
        # -- eligibility --
        placeable = sum(1 for b in buffers if b.residency_reason is None)
        barred = n_buf - placeable
        return {
            "planner_buffers": n_buf,
            "placeable_buffers": placeable,
            "barred_buffers_prep": barred,
            "n_transition_points": n_transition,
            "total_lifetime_ticks": total_lifetime_ticks,
            "max_live_count": max_live,
            "mean_live_count": mean_live,
            "live_set_area": live_area,
            "max_live_bytes": max_live_bytes,
            "mean_live_bytes": mean_live_bytes,
            "n_overlap_pairs": n_overlap_pairs,
            "overlap_density": overlap_density,
            "in_place_edges": in_place_edges,
            "size_median": median_size,
            "size_p90": p90_size,
            "size_max": max_size,
            # cross-product size — one motivated candidate cost proxy
            "transition_x_placeable": n_transition * placeable,
        }
    except Exception as e:
        return {"structural_probe_error": repr(e)[:200]}


def _wrap_greedy_solver_counters(solver):
    """Install per-instance counters on a GreedyLayoutSolver.

    Wraps _find_free_block, _try_allocate_one, _try_deallocate,
    _occupied_spans to count deterministic work quantities. Idempotent
    per instance; safe to call unconditionally — no-op for other solvers.
    """
    try:
        from torch_spyre._inductor.scratchpad.greedy_solver import (
            GreedyLayoutSolver,
        )
    except ImportError:
        return
    if not isinstance(solver, GreedyLayoutSolver):
        return
    if getattr(solver, "_ab_counters_installed", False):
        return
    counters = {
        "n_find_free_block_calls": 0,
        "sum_live_set_size_entering_find": 0,
        "max_live_set_size_entering_find": 0,
        "n_try_allocate_one_calls": 0,
        "n_in_place_parent_probes": 0,
        "n_in_place_reuses": 0,
        "n_try_deallocate_calls": 0,
        "n_occupied_spans_calls": 0,
        "sum_usage_entering_occupied_spans": 0,
        # transition-loop work: outer loops over placeable at each idx
        "n_alloc_transition_iterations": 0,
        "n_dealloc_transition_iterations": 0,
    }
    solver._ab_counters = counters

    _orig_find = solver._find_free_block
    _orig_alloc_one = solver._try_allocate_one
    _orig_dealloc = solver._try_deallocate
    _orig_spans = solver._occupied_spans

    def _find_free_block(size_needed):
        counters["n_find_free_block_calls"] += 1
        live = len(solver.usage)
        counters["sum_live_set_size_entering_find"] += live
        if live > counters["max_live_set_size_entering_find"]:
            counters["max_live_set_size_entering_find"] = live
        return _orig_find(size_needed)

    def _try_allocate_one(buffer):
        counters["n_try_allocate_one_calls"] += 1
        counters["n_in_place_parent_probes"] += len(
            getattr(buffer, "in_place_parents", []) or []
        )
        pre_addr = buffer.address
        _orig_alloc_one(buffer)
        # in-place reuse: buffer got an address without an entry in usage
        # being added by _find_free_block. Detect by whether the placed
        # buffer's address matches any *existing* usage entry's address.
        if buffer.address is not None and pre_addr is None:
            # Count as in-place reuse only if the address is shared with
            # another live buffer (parent). Otherwise it was a normal
            # gap allocation.
            matches = sum(
                1 for u in solver.usage
                if u is not buffer and u.address == buffer.address
            )
            if matches:
                counters["n_in_place_reuses"] += 1

    def _try_deallocate(bufs):
        counters["n_try_deallocate_calls"] += 1
        return _orig_dealloc(bufs)

    def _occupied_spans():
        counters["n_occupied_spans_calls"] += 1
        counters["sum_usage_entering_occupied_spans"] += len(solver.usage)
        return _orig_spans()

    solver._find_free_block = _find_free_block
    solver._try_allocate_one = _try_allocate_one
    solver._try_deallocate = _try_deallocate
    solver._occupied_spans = _occupied_spans

    # Wrap plan_layout to record the transition-loop iteration counts
    # (n_transition_times x n_placeable in both allocate and deallocate
    # loops). Overall solver time is timed separately in scratchpad_solve.
    _orig_plan_layout = solver.plan_layout

    def _plan_layout(log_lx_usage=False):
        try:
            placeable = sum(
                1 for b in solver.buffers if b.residency_reason is None
            )
            times = set()
            for b in solver.buffers:
                if b.residency_reason is None and b.uses:
                    times.add(b.start_time)
                    times.add(b.end_time)
            n_times = len(times)
            counters["n_transition_times"] = n_times
            counters["n_alloc_transition_iterations"] = n_times * placeable
            counters["n_dealloc_transition_iterations"] = n_times * placeable
        except Exception:
            pass
        return _orig_plan_layout(log_lx_usage=log_lx_usage)

    solver.plan_layout = _plan_layout
    solver._ab_counters_installed = True


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
                    # Structural metrics computed once on the shared
                    # planner-buffer universe (before any solver runs).
                    try:
                        captured["structural_metrics"] = (
                            _compute_structural_metrics(bufs)
                        )
                    except Exception as e:
                        captured["structural_metrics_error"] = repr(e)[:200]
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
                    # Install per-instance greedy counters (no-op for other
                    # solvers). Recorded in _timed_solve after the solve
                    # finishes so we see final counts.
                    try:
                        _wrap_greedy_solver_counters(solver)
                    except Exception as e:
                        captured["greedy_counters_error"] = repr(e)[:200]
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
                        # (name, size, address) placement signature for the
                        # adaptive-solver draft validation. Compare across
                        # arms to prove not just resident-set equality but
                        # byte-identical LX placement addresses.
                        placed_with_addr = sorted(
                            (b.name, b.size, b.address) for b in allocation
                            if b.address is not None
                        )
                        captured["placed_signature_with_address"] = placed_with_addr
                    except Exception as e:
                        captured["placement_probe_error"] = repr(e)[:200]
                    # For CP-SAT: pick up solver stats stashed by our
                    # _run wrapper below (if the solver class was patched).
                    stats = getattr(solver, "_ab_last_solver_stats", None)
                    if stats is not None:
                        captured["ortools_stats"] = stats
                    # For greedy: pick up per-instance work counters.
                    gcounters = getattr(solver, "_ab_counters", None)
                    if gcounters is not None:
                        captured["greedy_counters"] = dict(gcounters)
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

    # ---- CpSatLayoutSolver._run — stash OR-Tools status/walltime -----------
    try:
        from torch_spyre._inductor.scratchpad.ilp_solver_ortools import (
            CpSatLayoutSolver,
        )
        _orig_cpsat_run = CpSatLayoutSolver._run

        @functools.wraps(_orig_cpsat_run)
        def _timed_cpsat_run(self, model, tensors, forced_reasons):
            from ortools.sat.python import cp_model  # already available
            # We need to peek at the internal solver instance used by _run,
            # but the real _run creates it as a local. Wrap CpSolver.Solve
            # to snapshot at the end.
            last = {}

            _orig_solve_cls = cp_model.CpSolver.Solve

            def _tracked_solve(cp_solver, mdl):
                status = _orig_solve_cls(cp_solver, mdl)
                try:
                    last["status"] = cp_solver.StatusName(status)
                    last["walltime_s"] = cp_solver.WallTime()
                    last["usertime_s"] = cp_solver.UserTime()
                    last["objective_value"] = cp_solver.ObjectiveValue()
                    try:
                        last["best_objective_bound"] = (
                            cp_solver.BestObjectiveBound()
                        )
                    except Exception:
                        pass
                    try:
                        last["num_branches"] = cp_solver.NumBranches()
                    except Exception:
                        pass
                    try:
                        last["num_conflicts"] = cp_solver.NumConflicts()
                    except Exception:
                        pass
                    last["num_workers"] = (
                        cp_solver.parameters.num_search_workers
                    )
                    last["max_time_in_seconds"] = (
                        cp_solver.parameters.max_time_in_seconds
                    )
                except Exception as e:
                    last["stats_error"] = repr(e)[:200]
                return status

            cp_model.CpSolver.Solve = _tracked_solve
            try:
                return _orig_cpsat_run(self, model, tensors, forced_reasons)
            finally:
                cp_model.CpSolver.Solve = _orig_solve_cls
                # Save the LAST solve's stats (final lex step) plus meta.
                self._ab_last_solver_stats = last

        CpSatLayoutSolver._run = _timed_cpsat_run
    except (ImportError, AttributeError):
        # ortools unavailable or class moved — leave CP-SAT stats unrecorded.
        pass

    _INSTALLED = True


__all__ = ["install_extra_timers"]

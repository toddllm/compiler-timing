# Copyright 2025 The Torch-Spyre Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""dedup_and_promote_constants — E + batch-removal variant.

Change vs E-only:

  - Per-duplicate `operations.remove(dup)` is deferred to a final
    Step 3 filter+partition rebuild. Duplicates are marked in a
    `dead_ids: set[int]` populated inline with the same bookkeeping
    that E-only performs.

Every other semantic (grouping, canonical selection,
merge_provenance, removed_buffers/name_to_buffer/name_to_op cleanup,
name_to_users fold, output-name skip, non-ComputedBuffer raise,
front-load) is unchanged from E-only.

Batch-removal safety (recap; full argument in
notes/dedup-phase2-plan.md):

  * Constants front-loaded, original relative order preserved: the
    rebuild filters `operations` (topologically ordered) then
    partitions, preserving order in each partition.

  * SpyreConstantFallback corresponding to a name in
    `removed_buffers` is absent from `operations` at exit: enforced
    by `id(dup) not in dead_ids` in the survivor filter.

  * A previously-marked-dead dup still present in `operations` when
    a later dup is processed poses no problem: (a) the identity
    check `if op is dup or op is canonical: continue` inside the
    redirect loop excludes the current dup and canonical, and (b)
    dead dups from earlier groups are not readers of the current
    dup's name (SpyreConstantFallback has no inputs -> empty
    get_read_writes.reads set inherited from InputsKernel), so
    they would not be listed in `consumers_by_name[current_dup]`
    even if they weren't gated. Nothing patches them accidentally.
"""

import os
import time
from collections import defaultdict

import torch
from torch._inductor.graph import GraphLowering
from torch._inductor.ir import ComputedBuffer, Operation
from torch._inductor.virtualized import V

from .ir import SpyreConstantFallback
from .insert_restickify import NameSwapHandler
from .logging_utils import get_inductor_logger
from .provenance import merge_provenance

logger = get_inductor_logger("dedup_constants")


# Diagnostic instrumentation. Inert unless TORCH_SPYRE_DEDUP_DIAG=1.
# Uses the same recorder as E-only / the pristine diag patch.
try:
    from . import dedup_diagnostics as _diag  # type: ignore
    _diag_perf_counter_ns = time.perf_counter_ns
except ImportError:
    _diag = None  # type: ignore
    _diag_perf_counter_ns = time.perf_counter_ns


def _diag_enabled() -> bool:
    return _diag is not None and _diag.is_enabled()


def _constant_key(op: SpyreConstantFallback) -> tuple:
    """Normalised (value, dtype, device) identity key for a SpyreConstantFallback."""
    layout = op.layout
    dev = layout.device
    norm_dev = (
        torch.device(dev.type, dev.index)
        if dev.index is not None
        else torch.device(dev.type)
    )
    return (op.constant_args[0], layout.dtype, norm_dev)


def _patch_inner_fn(consumer: ComputedBuffer, name_map: dict[str, str]) -> None:
    """Wrap consumer's inner_fn to redirect duplicate constant reads to the canonical name."""
    orig_inner = consumer.data.inner_fn

    def _new_inner(*args, _map=name_map, _orig=orig_inner):
        with V.set_ops_handler(NameSwapHandler(V.ops, _map)):
            return _orig(*args)

    object.__setattr__(consumer.data, "inner_fn", _new_inner)
    ComputedBuffer.get_default_sizes_body.clear_cache(consumer)


def _build_reverse_consumer_index(
    operations: list[Operation],
    duplicate_names: set[str],
    _diag_record=None,
) -> dict[str, list[Operation]]:
    """See dedup_constants_E_only.py for the full docstring."""
    idx: dict[str, list[Operation]] = defaultdict(list)
    diag = _diag_record is not None
    if diag:
        by_type = _diag_record.n_get_read_writes_by_type
        get_rw_ns = 0
    for op in operations:
        if diag:
            t0 = _diag_perf_counter_ns()
            rw = op.get_read_writes()
            t1 = _diag_perf_counter_ns()
            get_rw_ns += (t1 - t0)
            _diag_record.n_get_read_writes_calls += 1
            tname = type(op).__name__
            by_type[tname] = by_type.get(tname, 0) + 1
        else:
            rw = op.get_read_writes()
        for dep in rw.reads:
            if dep.name in duplicate_names:
                idx[dep.name].append(op)
    if diag:
        _diag_record.get_read_writes_ns += get_rw_ns
    return idx


def _redirect_consumers_via_index(
    consumers: list[Operation],
    dup: SpyreConstantFallback,
    canonical: SpyreConstantFallback,
    _diag_record=None,
) -> None:
    """See dedup_constants_E_only.py for the full docstring."""
    D = dup.get_name()
    C = canonical.get_name()
    name_map = {D: C}

    if D in V.graph.get_output_names():
        logger.debug("dedup_and_promote_constants: skipping output constant %s", D)
        return

    diag = _diag_record is not None
    if diag:
        patch_ns = 0
    for op in consumers:
        if op is dup or op is canonical:
            continue
        if isinstance(op, ComputedBuffer):
            if diag:
                t0 = _diag_perf_counter_ns()
                _patch_inner_fn(op, name_map)
                t1 = _diag_perf_counter_ns()
                patch_ns += (t1 - t0)
                _diag_record.n_consumer_hits += 1
            else:
                _patch_inner_fn(op, name_map)
        else:
            raise AssertionError(
                f"dedup_and_promote_constants: unsupported consumer type "
                f"{type(op).__name__} reads constant {D!r} — cannot rewrite"
            )
    if diag:
        _diag_record.patch_inner_fn_ns += patch_ns


def _drop_constant_bookkeeping_only(
    dup: SpyreConstantFallback,
    canonical: SpyreConstantFallback,
    _diag_record=None,
) -> None:
    """Every bookkeeping mutation _drop_constant does, EXCEPT
    operations.remove(dup). The list removal is deferred to Step 3.
    """
    D = dup.get_name()
    C = canonical.get_name()
    op_name = dup.get_operation_name()
    diag = _diag_record is not None
    if diag:
        t_mp0 = _diag_perf_counter_ns()
    merge_provenance(
        [canonical, dup],
        canonical,
        pass_name="dedup_and_promote_constants",
        reason="duplicate constant",
    )
    if diag:
        t_mp1 = _diag_perf_counter_ns()
        _diag_record.merge_provenance_ns += (t_mp1 - t_mp0)
        t_bk0 = _diag_perf_counter_ns()
    V.graph.removed_buffers.add(D)
    V.graph.name_to_buffer.pop(D, None)
    V.graph.name_to_op.pop(op_name, None)
    extra_users = V.graph.name_to_users.pop(D, [])
    if extra_users:
        V.graph.name_to_users.setdefault(C, []).extend(extra_users)
    if diag:
        t_bk1 = _diag_perf_counter_ns()
        _diag_record.bookkeeping_ns += (t_bk1 - t_bk0)
    logger.debug("dedup_and_promote_constants: merged %s into canonical %s", D, C)


def dedup_and_promote_constants(graph: GraphLowering) -> None:
    """Deduplicate SpyreConstantFallback ops and move them to the head of operations.

    E + batch-removal variant. See module docstring for full rationale.
    """
    operations = graph.operations
    diag_on = _diag_enabled()
    rec = _diag.RECORDER.new_record(  # type: ignore
        graph_id=getattr(graph, "graph_id", None)
    ) if diag_on else None
    if diag_on:
        rec.n_ops_at_entry = len(operations)
        t_total_0 = _diag_perf_counter_ns()

    # --- Step 1: group by identity key ---
    if diag_on:
        t_g0 = _diag_perf_counter_ns()
    groups: dict[tuple, list[SpyreConstantFallback]] = {}
    for op in operations:
        if not isinstance(op, SpyreConstantFallback):
            continue
        key = _constant_key(op)
        groups.setdefault(key, []).append(op)
    if diag_on:
        t_g1 = _diag_perf_counter_ns()
        rec.grouping_ns = t_g1 - t_g0
        rec.n_constants = sum(len(g) for g in groups.values())
        rec.n_groups = len(groups)
        rec.n_groups_multi = sum(1 for g in groups.values() if len(g) > 1)
        rec.n_duplicates = sum(len(g) - 1 for g in groups.values() if len(g) > 1)

    duplicate_names: set[str] = set()
    for group in groups.values():
        if len(group) > 1:
            for dup in group[1:]:
                duplicate_names.add(dup.get_name())

    # --- Step 2: dedup, only when duplicates exist ---
    dead_ids: set[int] = set()
    if duplicate_names:
        if diag_on:
            t_idx0 = _diag_perf_counter_ns()
        consumers_by_name = _build_reverse_consumer_index(
            operations, duplicate_names, _diag_record=rec
        )
        if diag_on:
            t_idx1 = _diag_perf_counter_ns()
            rec.reverse_index_build_ns = t_idx1 - t_idx0
            rec.n_indexed_edges = sum(len(v) for v in consumers_by_name.values())
        if diag_on:
            t_r0 = _diag_perf_counter_ns()
        for key, group in groups.items():
            if len(group) <= 1:
                continue
            canonical = group[0]
            for dup in group[1:]:
                _redirect_consumers_via_index(
                    consumers_by_name.get(dup.get_name(), []),
                    dup,
                    canonical,
                    _diag_record=rec,
                )
                _drop_constant_bookkeeping_only(dup, canonical, _diag_record=rec)
                dead_ids.add(id(dup))
        if diag_on:
            t_r1 = _diag_perf_counter_ns()
            rec.redirect_ns = t_r1 - t_r0

    # --- Step 3: front-load surviving constants (filtering out dead dups). ---
    if diag_on:
        t_f0 = _diag_perf_counter_ns()
    if dead_ids:
        survivors = [op for op in operations if id(op) not in dead_ids]
    else:
        survivors = list(operations)

    constants = [op for op in survivors if isinstance(op, SpyreConstantFallback)]
    if not constants:
        # Rare path: no surviving constants at all. Preserve the ordering
        # of surviving non-constants.
        operations[:] = survivors
        if diag_on:
            t_f1 = _diag_perf_counter_ns()
            rec.front_load_ns = t_f1 - t_f0
            rec.dedup_total_ns = _diag_perf_counter_ns() - t_total_0
        return
    non_constants = [op for op in survivors if not isinstance(op, SpyreConstantFallback)]
    operations[:] = constants + non_constants
    if diag_on:
        t_f1 = _diag_perf_counter_ns()
        rec.front_load_ns = t_f1 - t_f0
        rec.dedup_total_ns = _diag_perf_counter_ns() - t_total_0
    logger.debug(
        "dedup_and_promote_constants: %d constant(s) promoted to front of operations",
        len(constants),
    )

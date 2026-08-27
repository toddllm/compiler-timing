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

"""dedup_and_promote_constants — E-only variant of the pass.

Change vs pristine a9316b381:

  - Replace the per-duplicate O(N) scan in `_redirect_consumers`
    with a single O(N) reverse-consumer index built once, scoped
    to duplicate buffer names, AFTER grouping determines that
    duplicates actually exist. When there are no duplicates the
    reverse-index scan is skipped entirely so a no-duplicate graph
    incurs no `get_read_writes` calls (preserving the current
    fast-path).

  - `_drop_constant` is unchanged (per-duplicate `operations.remove`
    preserved). Batch removal is a SEPARATE commit; keeping E-only
    isolated lets us measure the two changes independently.

  - All semantic bookkeeping preserved verbatim:
      * `merge_provenance`
      * `removed_buffers.add`
      * `name_to_buffer.pop`
      * `name_to_op.pop`
      * `name_to_users[D] → name_to_users[C]` fold
      * output-name skip
      * non-ComputedBuffer consumer raises AssertionError
      * canonical selection (group[0])
      * final constants-front-loaded order

Mutation-proof correctness argument (why building the index once
before any redirects is correct):

  * The index is a materialization of the same `get_read_writes()`
    read set the current algorithm consults, taken at pass entry.
    For each duplicate name D, `consumers_by_name[D]` is the exact
    set of ops that the old algorithm's inner scan would identify.

  * We never re-query `consumers_by_name[D]` for a D whose redirect
    has already fired: the outer loop iterates each duplicate
    exactly once.

  * `_patch_inner_fn` mutates a consumer's `inner_fn` and clears
    its `get_default_sizes_body` cache. Neither mutation changes
    the buffer NAMES that op currently reads until a live
    `get_read_writes` re-runs `inner_fn` under the swap handler
    at codegen time. During dedup we do not call get_read_writes
    on any op after patching it, so the index remains internally
    consistent.

  * Case: a single consumer reads multiple duplicate names
    (D1 and D2 in different groups). The pre-built index lists
    that consumer under both `consumers_by_name[D1]` and
    `consumers_by_name[D2]`. Processing D1 → C1 stacks a
    `NameSwapHandler({D1: C1})` on the consumer's inner_fn.
    Processing D2 → C2 stacks a second `NameSwapHandler({D2: C2})`
    on the already-wrapped inner_fn. Each handler translates only
    its own key at codegen time, so both redirects are honored.
    This is the same stacking pattern insert_bmm_padding's
    _rebuild_matmul uses over any prior name-swap.

  * Case: a duplicate's own TensorBox / operation itself would
    trivially be a "reader of D" under Buffer.get_read_names —
    the pass's existing `if op is dup or op is canonical: continue`
    check still applies inside the redirect loop, so the dup and
    canonical are never patched.
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


# ---------------------------------------------------------------------------
# Diagnostic instrumentation. Inert unless TORCH_SPYRE_DEDUP_DIAG=1.
# Kept in-file so E-only is self-contained; still writes into the same
# `dedup_diagnostics.RECORDER` process-wide store used by the pristine
# diag patch, so analyze_dedup_diag.py works against E-only records
# without change.
# ---------------------------------------------------------------------------

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
    """Build a name -> [Operations that read this name] index for the
    given set of duplicate buffer names.

    Runs one `op.get_read_writes()` per op in `operations`. Restricts
    the index to `duplicate_names` so both the memory footprint and
    the number of hash lookups scale with the actual work dedup has
    to do, not with the graph's overall read-edge count.

    Duplicate constants themselves may appear as "readers" of their
    own name (Buffer.get_read_names returns {self.get_name()} — see
    upstream torch/_inductor/ir.py:5278). The identity check
    `op is dup or op is canonical` in the redirect loop filters
    those out, so we do not need to exclude them here.
    """
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
    """Rewrite every ComputedBuffer consumer of dup to read canonical.

    `consumers` is `consumers_by_name[dup.get_name()]` — precomputed
    from the reverse index, so this function does not call
    `get_read_writes` and does not scan graph.operations. All other
    semantics (output-name skip, dup/canonical identity skip,
    non-ComputedBuffer AssertionError) are preserved.
    """
    D = dup.get_name()
    C = canonical.get_name()
    name_map = {D: C}

    # Do not dedup a constant that is itself a graph output.
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


def _drop_constant(
    operations: list[Operation],
    dup: SpyreConstantFallback,
    canonical: SpyreConstantFallback,
    _diag_record=None,
) -> None:
    """Remove a duplicate constant from the graph and update bookkeeping."""
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
        t_rm0 = _diag_perf_counter_ns()
    operations.remove(dup)
    if diag:
        t_rm1 = _diag_perf_counter_ns()
        _diag_record.operations_remove_ns += (t_rm1 - t_rm0)
        _diag_record.n_operations_remove_calls += 1
        t_bk0 = _diag_perf_counter_ns()
    V.graph.removed_buffers.add(D)
    V.graph.name_to_buffer.pop(D, None)
    V.graph.name_to_op.pop(op_name, None)
    # Merge the duplicate's users into the canonical's user list so that passes
    # which iterate name_to_users (e.g. scratchpad planning) see the full set.
    extra_users = V.graph.name_to_users.pop(D, [])
    if extra_users:
        V.graph.name_to_users.setdefault(C, []).extend(extra_users)
    if diag:
        t_bk1 = _diag_perf_counter_ns()
        _diag_record.bookkeeping_ns += (t_bk1 - t_bk0)
    logger.debug("dedup_and_promote_constants: merged %s into canonical %s", D, C)


def dedup_and_promote_constants(graph: GraphLowering) -> None:
    """Deduplicate SpyreConstantFallback ops and move them to the head of operations.

    Steps:
      1. Group SpyreConstantFallback ops by (value, dtype, device).
      2. If any group has >1 instance, build a reverse consumer index
         over all duplicate buffer names in a single O(N) sweep. For
         each duplicate, rewrite its ComputedBuffer consumers to read
         from canonical, then drop the duplicate.
      3. Move all surviving SpyreConstantFallback ops to the front of
         operations, preserving relative order.

    Mutates operations in place.
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

    # Determine the set of duplicate names up front. If there are no
    # duplicates, skip the expensive reverse-index scan and go
    # straight to the front-loading step.
    duplicate_names: set[str] = set()
    for group in groups.values():
        if len(group) > 1:
            for dup in group[1:]:
                duplicate_names.add(dup.get_name())

    # --- Step 2: dedup, only when duplicates exist ---
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
                _drop_constant(operations, dup, canonical, _diag_record=rec)
        if diag_on:
            t_r1 = _diag_perf_counter_ns()
            rec.redirect_ns = t_r1 - t_r0

    # --- Step 3: front-load surviving constants ---
    if diag_on:
        t_f0 = _diag_perf_counter_ns()
    constants = [op for op in operations if isinstance(op, SpyreConstantFallback)]
    if not constants:
        if diag_on:
            t_f1 = _diag_perf_counter_ns()
            rec.front_load_ns = t_f1 - t_f0
            rec.dedup_total_ns = _diag_perf_counter_ns() - t_total_0
        return
    non_constants = [
        op for op in operations if not isinstance(op, SpyreConstantFallback)
    ]
    operations[:] = constants + non_constants
    if diag_on:
        t_f1 = _diag_perf_counter_ns()
        rec.front_load_ns = t_f1 - t_f0
        rec.dedup_total_ns = _diag_perf_counter_ns() - t_total_0
    logger.debug(
        "dedup_and_promote_constants: %d constant(s) promoted to front of operations",
        len(constants),
    )

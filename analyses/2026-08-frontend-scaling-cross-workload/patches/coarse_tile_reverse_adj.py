"""Prototype: mutation-safe per-substage reverse adjacency.

Replaces the two dominant O(N × K) hotspot patterns in coarse-tile-hints
with a single O(N) walk per substage that builds two indexes:

  reads_by_op[op_id]     : set of buffer names this op reads
  readers_by_buffer[buf] : set of op names that read this buffer

The indexes are built AT SUBSTAGE ENTRY from the current `operations`
list and consumed within that substage only. They are never carried
across mutation boundaries (`_apply_plan`, `_insert_all_*`,
`replace_computed_buffer_body`), so cached ReadWrites cannot become
stale — the same failure mode that broke the naïve global-memoize
prototype in phase 10.

Applies to `torch_spyre/_inductor/wsr/coarse_tile.py`. Two substages
patched:

  - `_plan_tiling_propagation` (planning, pre-mutation): builds the
    index once at entry, passes it into `_find_outside_consumers_planned`.
  - `_patch_retiled_load_indexes` (resync tail, per group after mutations):
    builds a fresh index at entry (mutations of the previous group are
    already reflected in the shared `operations` list).

Idempotent — checks marker before applying/removing.
"""
from __future__ import annotations

import os
import sys

TARGET = os.environ.get(
    "COARSE_TILE_PATH",
    os.path.expanduser("~/pr3806/torch-spyre/torch_spyre/_inductor/wsr/coarse_tile.py"),
)

MARKER = "# PROTOTYPE reverse-adj patch"

# ---------------------------------------------------------------------
# Helper functions to inject once at module scope.
# ---------------------------------------------------------------------

HELPER_ANCHOR = "def _reads_buffer(op: ComputedBuffer, buf_name: str) -> bool:\n"
HELPER_BLOCK = f'''{MARKER} — begin
def _build_reads_indexes(operations):
    """One O(N) walk building both directions of the reads adjacency.

    reads_by_op[op_name]     -> set of buffer names this op reads
    readers_by_buffer[buf]   -> set of op names that read this buffer

    Only ComputedBuffer ops are indexed (matches _reads_buffer's filter).
    """
    reads_by_op = {{}}
    readers_by_buffer = {{}}
    for op in operations:
        if not isinstance(op, ComputedBuffer):
            continue
        op_name = op.get_name()
        try:
            rw = op.get_read_writes()
        except Exception:
            continue
        buf_names = set()
        for dep in rw.reads:
            name = getattr(dep, "name", None)
            if name is None:
                continue
            buf_names.add(name)
            readers_by_buffer.setdefault(name, set()).add(op_name)
        reads_by_op[op_name] = buf_names
    return reads_by_op, readers_by_buffer

{MARKER} — end
'''

# ---------------------------------------------------------------------
# Patch A: replace _find_outside_consumers_planned to accept an optional
# readers_by_buffer index and use it as fast path.
# ---------------------------------------------------------------------

OLD_FIND = '''def _find_outside_consumers_planned(
    buf_name: str,
    group_loop_id: tuple[int, ...],
    operations: list[Operation],
    name_to_group_outer_key: dict[str, int],
) -> tuple[list[str], bool]:
    """Planning-time analog of _find_outside_consumers.

    Same decision (does any op outside buf_name's own outermost loop group
    read it, or is it a graph output), but returns consumer *names* instead
    of objects (planning is zero-mutation, so there's no reason to carry
    object references past this stage -- see PropagationPlan's docstring on
    name stability), and looks up each candidate's outer loop-group key from
    name_to_group_outer_key (built once by the caller from the planned
    CoarseTileInfo dict) instead of a not-yet-stamped op.loop_info attribute.
    """
    outer_key = group_loop_id[0]
    consumer_names: list[str] = []
    for op in operations:
        if not isinstance(op, ComputedBuffer):
            continue
        if not _reads_buffer(op, buf_name):
            continue
        candidate_outer_key = name_to_group_outer_key.get(op.get_name())
        if candidate_outer_key is None or candidate_outer_key != outer_key:
            consumer_names.append(op.get_name())

    is_graph_output = buf_name in _graph_output_names()
    return consumer_names, is_graph_output'''

NEW_FIND = f'''def _find_outside_consumers_planned(
    buf_name: str,
    group_loop_id: tuple[int, ...],
    operations: list[Operation],
    name_to_group_outer_key: dict[str, int],
    readers_by_buffer: dict | None = None,   {MARKER}
) -> tuple[list[str], bool]:
    """Planning-time analog of _find_outside_consumers.

    Same decision (does any op outside buf_name's own outermost loop group
    read it, or is it a graph output), but returns consumer *names* instead
    of objects (planning is zero-mutation, so there's no reason to carry
    object references past this stage -- see PropagationPlan's docstring on
    name stability), and looks up each candidate's outer loop-group key from
    name_to_group_outer_key (built once by the caller from the planned
    CoarseTileInfo dict) instead of a not-yet-stamped op.loop_info attribute.

    Prototype fast path: if `readers_by_buffer` is provided by the caller,
    the O(N) walk is replaced with a dict lookup. See _build_reads_indexes.
    """
    outer_key = group_loop_id[0]
    consumer_names: list[str] = []
    if readers_by_buffer is not None:   {MARKER}
        for op_name in readers_by_buffer.get(buf_name, ()):
            candidate_outer_key = name_to_group_outer_key.get(op_name)
            if candidate_outer_key is None or candidate_outer_key != outer_key:
                consumer_names.append(op_name)
    else:
        for op in operations:
            if not isinstance(op, ComputedBuffer):
                continue
            if not _reads_buffer(op, buf_name):
                continue
            candidate_outer_key = name_to_group_outer_key.get(op.get_name())
            if candidate_outer_key is None or candidate_outer_key != outer_key:
                consumer_names.append(op.get_name())

    is_graph_output = buf_name in _graph_output_names()
    return consumer_names, is_graph_output'''

# ---------------------------------------------------------------------
# Patch B: _plan_tiling_propagation builds the index once and threads
# it into every _find_outside_consumers_planned call.
#
# We only need to modify the two call sites to accept the extra arg.
# The index build happens at the top of _plan_tiling_propagation.
# ---------------------------------------------------------------------

OLD_PLAN_ENTRY = '''def _plan_tiling_propagation(
    operations: list[Operation],
    groups: list[tuple],
    plan: dict[int, CoarseTileInfo],
) -> None:
'''

NEW_PLAN_ENTRY = f'''def _plan_tiling_propagation(
    operations: list[Operation],
    groups: list[tuple],
    plan: dict[int, CoarseTileInfo],
) -> None:
    {MARKER} — build reverse-adjacency once at substage entry
    _reads_by_op, _readers_by_buffer = _build_reads_indexes(operations)
'''

# Two call sites of _find_outside_consumers_planned inside _plan_tiling_propagation
OLD_CALL_1 = '''consumer_names, is_graph_output = _find_outside_consumers_planned(
                    buf_name, info.loop_group_id, operations, name_to_group_outer_key
                )'''

NEW_CALL_1 = f'''consumer_names, is_graph_output = _find_outside_consumers_planned(
                    buf_name, info.loop_group_id, operations, name_to_group_outer_key,
                    readers_by_buffer=_readers_by_buffer,   {MARKER}
                )'''

# ---------------------------------------------------------------------
# Patch C: _patch_retiled_load_indexes uses reads_by_op for _should_patch.
# ---------------------------------------------------------------------

OLD_PATCH_ENTRY = '''def _patch_retiled_load_indexes(
    group_id: tuple[int, ...],
    group_ops: list[Operation],
    retiled_infos: dict[str, _RetiledBufferInfo],
    operations: list[Operation],
) -> None:
    """Rewrite stale load indexes for consumers of buffers retiled by coarse tiling."""
    infos_by_name = {
        name: info
        for name, info in retiled_infos.items()
        if info.old_stride != info.new_stride
    }
    if not infos_by_name:
        return
'''

NEW_PATCH_ENTRY = f'''def _patch_retiled_load_indexes(
    group_id: tuple[int, ...],
    group_ops: list[Operation],
    retiled_infos: dict[str, _RetiledBufferInfo],
    operations: list[Operation],
) -> None:
    """Rewrite stale load indexes for consumers of buffers retiled by coarse tiling."""
    infos_by_name = {{
        name: info
        for name, info in retiled_infos.items()
        if info.old_stride != info.new_stride
    }}
    if not infos_by_name:
        return

    {MARKER} — build fresh reverse-adjacency at each per-group tail entry
    _reads_by_op, _readers_by_buffer = _build_reads_indexes(operations)
'''

# _should_patch_retiled_load_indexes call: replace with a direct reads_by_op check.
# The original is:  if not _should_patch_retiled_load_indexes(op, group_id, retiled_names): continue
# We shortcut by inlining the ComputedBuffer/loop_info/reads check.

OLD_SHOULD_PATCH_LOOP = '''    retiled_names = set(infos_by_name)
    for op in list(group_ops):
        if not _should_patch_retiled_load_indexes(op, group_id, retiled_names):
            continue'''

NEW_SHOULD_PATCH_LOOP = f'''    retiled_names = set(infos_by_name)
    for op in list(group_ops):   {MARKER}
        if not isinstance(op, ComputedBuffer):
            continue
        if not isinstance(op.data, (Pointwise, Reduction)):
            continue
        loop_info = getattr(op, "loop_info", None)
        if loop_info is None or loop_info.loop_group_id != group_id:
            continue
        _op_reads = _reads_by_op.get(op.get_name(), set())
        if not (_op_reads & retiled_names):
            continue'''


WRAPS = [
    (HELPER_ANCHOR, HELPER_BLOCK + HELPER_ANCHOR),
    (OLD_FIND, NEW_FIND),
    (OLD_PLAN_ENTRY, NEW_PLAN_ENTRY),
    (OLD_CALL_1, NEW_CALL_1),
    (OLD_PATCH_ENTRY, NEW_PATCH_ENTRY),
    (OLD_SHOULD_PATCH_LOOP, NEW_SHOULD_PATCH_LOOP),
]


def apply() -> None:
    text = open(TARGET).read()
    if MARKER in text:
        print(f"already patched: {TARGET}")
        return
    for old, new in WRAPS:
        c = text.count(old)
        if c == 0:
            print(f"FATAL: anchor missing:\n{old[:200]}", file=sys.stderr)
            sys.exit(2)
        if c > 1:
            print(f"FATAL: anchor ambiguous ({c}):\n{old[:200]}", file=sys.stderr)
            sys.exit(2)
        text = text.replace(old, new, 1)
    open(TARGET, "w").write(text)
    print(f"patched: {TARGET}")


def revert() -> None:
    text = open(TARGET).read()
    if MARKER not in text:
        print(f"not patched: {TARGET}")
        return
    for old, new in WRAPS:
        if new in text:
            text = text.replace(new, old, 1)
    open(TARGET, "w").write(text)
    print(f"reverted: {TARGET}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("apply", "revert"):
        print("usage: python coarse_tile_reverse_adj.py {apply|revert}", file=sys.stderr)
        sys.exit(2)
    (apply if sys.argv[1] == "apply" else revert)()

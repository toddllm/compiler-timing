"""Instrumentation patch: add sub-timers inside _coarse_tile_common.

Applies to `torch_spyre/_inductor/wsr/coarse_tile.py` on the pr3806 tree.
Adds `timing_recorder.stage` calls around the four substages that the
Phase-3 source analysis flagged as O(N × G):

    coarse_tile:plan_coarse_tile_groups
    coarse_tile:plan_tiling_propagation                (prime suspect)
    coarse_tile:apply_plan_loop                        (per-group _apply_plan)
    coarse_tile:plan_read_copies
    coarse_tile:insert_all_read_copy_ops
    coarse_tile:insert_all_reduction_ops
    coarse_tile:insert_all_write_copy_ops
    coarse_tile:resync_and_patch_load_indexes
    coarse_tile:validate_writer_tile_advance
    coarse_tile:validate_reader_tile_advance

Also records structural counters on each event:
    n_ops = |graph.operations|
    n_groups = len(groups)
    n_grouped_ops = sum(len(g[0]) for g in groups)

Applied by run_apply_substage_timing.sh on the pod. Not a source patch —
it does surgical string-replaces into coarse_tile.py after checking that
the target strings are present exactly once.
"""
from __future__ import annotations

import os
import sys

# Anchor strings (must appear exactly once in the target file). Each
# tuple: (find_anchor, wrap_start, wrap_end_marker).
# For the substages that are single function calls, we wrap the line.

TARGET_FILE = os.environ.get(
    "COARSE_TILE_PATH",
    os.path.expanduser("~/pr3806/torch-spyre/torch_spyre/_inductor/wsr/coarse_tile.py"),
)

# Wrap each substage call by prefixing it with a `with _tr.stage(...)` block.
# We inject an import at the top of the module and wrap the four dominant calls.
WRAPS = [
    # (unique existing line, replacement text)
    (
        "    plan = plan_coarse_tile_groups(operations, groups)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:plan_coarse_tile_groups',\n"
        "        n_ops=len(operations),\n"
        "        n_groups=len(groups),\n"
        "        n_grouped_ops=sum(len(g[0]) for g in groups),\n"
        "    ):\n"
        "        plan = plan_coarse_tile_groups(operations, groups)\n",
    ),
    (
        "    _plan_tiling_propagation(operations, groups, plan)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:plan_tiling_propagation',\n"
        "        n_ops=len(operations),\n"
        "        n_groups=len(groups),\n"
        "        n_grouped_ops=sum(len(g[0]) for g in groups),\n"
        "    ):\n"
        "        _plan_tiling_propagation(operations, groups, plan)\n",
    ),
    (
        "    retiled_infos_by_group: list[\n"
        "        tuple[tuple[int, ...], list[Operation], dict[str, _RetiledBufferInfo]]\n"
        "    ] = []\n"
        "    for group_idx, (group_ops, levels) in enumerate(groups, start=group_idx_offset):\n"
        "        group_id: tuple[int, ...] = (group_idx,)\n"
        "        op_to_position = {op.get_operation_name(): i for i, op in enumerate(operations)}\n"
        "        stamped_group_id = group_id + (0,) * (len(levels) - 1)\n"
        "        retiled_infos = _apply_plan(\n"
        "            group_ops, stamped_group_id, levels, op_to_position, plan\n"
        "        )\n"
        "        retiled_infos_by_group.append((stamped_group_id, group_ops, retiled_infos))\n",
        "    retiled_infos_by_group: list[\n"
        "        tuple[tuple[int, ...], list[Operation], dict[str, _RetiledBufferInfo]]\n"
        "    ] = []\n"
        "    with _tr.stage(\n"
        "        'coarse_tile:apply_plan_loop',\n"
        "        n_ops=len(operations),\n"
        "        n_groups=len(groups),\n"
        "    ):\n"
        "        for group_idx, (group_ops, levels) in enumerate(groups, start=group_idx_offset):\n"
        "            group_id: tuple[int, ...] = (group_idx,)\n"
        "            op_to_position = {op.get_operation_name(): i for i, op in enumerate(operations)}\n"
        "            stamped_group_id = group_id + (0,) * (len(levels) - 1)\n"
        "            retiled_infos = _apply_plan(\n"
        "                group_ops, stamped_group_id, levels, op_to_position, plan\n"
        "            )\n"
        "            retiled_infos_by_group.append((stamped_group_id, group_ops, retiled_infos))\n",
    ),
    (
        "    if run_read_copies:\n"
        "        read_copy_plans = _plan_read_copies(operations, retiled_infos_by_group)\n"
        "        _insert_all_read_copy_ops(operations, read_copy_plans)\n",
        "    if run_read_copies:\n"
        "        with _tr.stage(\n"
        "            'coarse_tile:plan_read_copies',\n"
        "            n_ops=len(operations),\n"
        "            n_groups=len(groups),\n"
        "        ):\n"
        "            read_copy_plans = _plan_read_copies(operations, retiled_infos_by_group)\n"
        "        with _tr.stage(\n"
        "            'coarse_tile:insert_all_read_copy_ops',\n"
        "            n_ops=len(operations),\n"
        "            n_plans=len(read_copy_plans),\n"
        "        ):\n"
        "            _insert_all_read_copy_ops(operations, read_copy_plans)\n",
    ),
    (
        "    _insert_all_reduction_ops(operations)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:insert_all_reduction_ops',\n"
        "        n_ops=len(operations),\n"
        "    ):\n"
        "        _insert_all_reduction_ops(operations)\n",
    ),
    (
        "    _insert_all_write_copy_ops(operations)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:insert_all_write_copy_ops',\n"
        "        n_ops=len(operations),\n"
        "    ):\n"
        "        _insert_all_write_copy_ops(operations)\n",
    ),
    (
        "    name_to_op = {\n"
        "        op.get_name(): op for op in operations if isinstance(op, ComputedBuffer)\n"
        "    }\n"
        "    for group_id, group_ops, retiled_infos in retiled_infos_by_group:\n"
        "        for idx, op in enumerate(group_ops):\n"
        "            if not isinstance(op, ComputedBuffer):\n"
        "                continue\n"
        "            group_ops[idx] = name_to_op.get(op.get_name(), op)\n"
        "        _patch_retiled_load_indexes(group_id, group_ops, retiled_infos, operations)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:resync_and_patch_load_indexes',\n"
        "        n_ops=len(operations),\n"
        "        n_groups=len(groups),\n"
        "    ):\n"
        "        name_to_op = {\n"
        "            op.get_name(): op for op in operations if isinstance(op, ComputedBuffer)\n"
        "        }\n"
        "        for group_id, group_ops, retiled_infos in retiled_infos_by_group:\n"
        "            for idx, op in enumerate(group_ops):\n"
        "                if not isinstance(op, ComputedBuffer):\n"
        "                    continue\n"
        "                group_ops[idx] = name_to_op.get(op.get_name(), op)\n"
        "            _patch_retiled_load_indexes(group_id, group_ops, retiled_infos, operations)\n",
    ),
    (
        "    _log_propagation_self_check(operations, predicted_kind_by_name)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:log_propagation_self_check',\n"
        "        n_ops=len(operations),\n"
        "    ):\n"
        "        _log_propagation_self_check(operations, predicted_kind_by_name)\n",
    ),
    (
        "    validate_writer_tile_advance(operations)\n"
        "    validate_reader_tile_advance(operations)\n",
        "    with _tr.stage(\n"
        "        'coarse_tile:validate_writer_tile_advance',\n"
        "        n_ops=len(operations),\n"
        "    ):\n"
        "        validate_writer_tile_advance(operations)\n"
        "    with _tr.stage(\n"
        "        'coarse_tile:validate_reader_tile_advance',\n"
        "        n_ops=len(operations),\n"
        "    ):\n"
        "        validate_reader_tile_advance(operations)\n",
    ),
]

IMPORT_ANCHOR = "from typing import"
IMPORT_INJECTION = "from .. import timing_recorder as _tr  # inserted by coarse_tile_substage_timing patch\n"


def apply() -> None:
    text = open(TARGET_FILE).read()

    # Idempotence check
    if "coarse_tile:plan_tiling_propagation" in text:
        print(f"already patched: {TARGET_FILE}")
        return

    # Inject import once at the top
    if IMPORT_INJECTION not in text:
        anchor_idx = text.find(IMPORT_ANCHOR)
        if anchor_idx < 0:
            print(f"FATAL: import anchor {IMPORT_ANCHOR!r} not found", file=sys.stderr)
            sys.exit(2)
        text = text[:anchor_idx] + IMPORT_INJECTION + text[anchor_idx:]

    # Apply each wrap
    for old, new in WRAPS:
        count = text.count(old)
        if count == 0:
            print(f"FATAL: could not find anchor in {TARGET_FILE}:\n{old[:200]}", file=sys.stderr)
            sys.exit(2)
        if count > 1:
            print(f"FATAL: anchor appears {count} times; ambiguous:\n{old[:200]}", file=sys.stderr)
            sys.exit(2)
        text = text.replace(old, new, 1)

    open(TARGET_FILE, "w").write(text)
    print(f"patched: {TARGET_FILE}")


def revert() -> None:
    text = open(TARGET_FILE).read()
    if IMPORT_INJECTION in text:
        text = text.replace(IMPORT_INJECTION, "")
    for old, new in WRAPS:
        if new in text:
            text = text.replace(new, old)
    open(TARGET_FILE, "w").write(text)
    print(f"reverted: {TARGET_FILE}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("apply", "revert"):
        print("usage: python coarse_tile_substage_timing.py {apply|revert}", file=sys.stderr)
        sys.exit(2)
    if sys.argv[1] == "apply":
        apply()
    else:
        revert()

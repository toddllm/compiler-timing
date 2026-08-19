"""Instrumentation patch: record beam-frontier evolution in
`optimize_restickify.beam_global_min_cost`.

Adds counters to trace beam explosion/pruning per-op:
- `pre_expand` = |frontier.states| entering the op
- `n_candidates` = |op.layouts|
- `post_expand` = |next_states| after expansion (before merge)
- `post_merge` = |next_states| after liveness merge
- `post_trim` = |frontier.states| after trim (≤ BEAM_WIDTH)

Emits a `beam_frontier_trace` event as a single _tr.stage at end of the
function whose meta contains a compact per-op array. Also emits summary
counters (max_pre_expand, sum_post_expand, ops_processed).

Applies to `torch_spyre/_inductor/optimize_restickify.py` on the pr3806
tree. Idempotent (checks marker).
"""
from __future__ import annotations

import os
import sys

TARGET_FILE = os.environ.get(
    "OPT_RESTICKIFY_PATH",
    os.path.expanduser("~/pr3806/torch-spyre/torch_spyre/_inductor/optimize_restickify.py"),
)

IMPORT_ANCHOR = "from . import config"
IMPORT_INJECTION = (
    "from . import timing_recorder as _tr  # inserted by restickify_beam_counters patch\n"
)

# Wrap the whole beam_global_min_cost body to collect per-op counters.
# We use surgical inserts anchored by unique markers rather than a full-body
# replace so this stays maintainable.

INIT_MARK = "    max_states = 1\n    merged_total = 0\n"
INIT_MARK_NEW = (
    "    max_states = 1\n    merged_total = 0\n"
    "    _beam_trace: list[dict] = []  # inserted by restickify_beam_counters\n"
    "    _beam_max_pre_expand = 0\n"
    "    _beam_max_post_expand = 0\n"
    "    _beam_max_post_merge = 0\n"
    "    _beam_max_post_trim = 0\n"
)

# Landmark: the line "        current_step = step_of[op.get_name()]" is right at
# the top of the per-op loop, unique in this function.
LOOP_TOP_MARK = "        current_step = step_of[op.get_name()]\n"
LOOP_TOP_NEW = (
    "        current_step = step_of[op.get_name()]\n"
    "        _pre_expand = len(frontier.states)\n"
)

# Landmark: `next_states = list(canon.values())` — right after liveness merge.
POST_MERGE_MARK = "        next_states = list(canon.values())\n"
POST_MERGE_NEW = (
    "        next_states = list(canon.values())\n"
    "        _post_merge = len(next_states)\n"
)

# Landmark: `frontier.states = next_states` — right before trim.
POST_EXPAND_CAPTURE_MARK = "        before_merge = len(next_states)\n"
POST_EXPAND_CAPTURE_NEW = (
    "        before_merge = len(next_states)\n"
    "        _post_expand = before_merge\n"
)

# Landmark: `max_states = max(max_states, len(frontier.states))` — right after trim.
POST_TRIM_MARK = "        max_states = max(max_states, len(frontier.states))\n"
POST_TRIM_NEW = (
    "        max_states = max(max_states, len(frontier.states))\n"
    "        _post_trim = len(frontier.states)\n"
    "        _n_candidates = len(op.layouts)\n"
    "        _beam_trace.append({\n"
    "            'op': op.get_name(),\n"
    "            'pre_expand': _pre_expand,\n"
    "            'n_candidates': _n_candidates,\n"
    "            'post_expand': _post_expand,\n"
    "            'post_merge': _post_merge,\n"
    "            'post_trim': _post_trim,\n"
    "        })\n"
    "        if _pre_expand > _beam_max_pre_expand: _beam_max_pre_expand = _pre_expand\n"
    "        if _post_expand > _beam_max_post_expand: _beam_max_post_expand = _post_expand\n"
    "        if _post_merge > _beam_max_post_merge: _beam_max_post_merge = _post_merge\n"
    "        if _post_trim > _beam_max_post_trim: _beam_max_post_trim = _post_trim\n"
)

# Landmark: the final `logger.info(...) beam search done` — insert stage emission just before.
FINAL_MARK = "    logger.info(\n        \"beam search done: max states = %d, best cost = %s, total liveness-merged = %d\","
FINAL_NEW = (
    "    with _tr.stage(\n"
    "        'restickify_beam_trace',\n"
    "        ops_processed=len(_beam_trace),\n"
    "        max_pre_expand=_beam_max_pre_expand,\n"
    "        max_post_expand=_beam_max_post_expand,\n"
    "        max_post_merge=_beam_max_post_merge,\n"
    "        max_post_trim=_beam_max_post_trim,\n"
    "        beam_width=BEAM_WIDTH,\n"
    "        merged_total=merged_total,\n"
    "        trace_head=_beam_trace[:16],\n"
    "        trace_tail=_beam_trace[-16:] if len(_beam_trace) > 16 else [],\n"
    "    ):\n"
    "        pass\n"
    "    logger.info(\n        \"beam search done: max states = %d, best cost = %s, total liveness-merged = %d\","
)

WRAPS = [
    (INIT_MARK, INIT_MARK_NEW),
    (LOOP_TOP_MARK, LOOP_TOP_NEW),
    (POST_EXPAND_CAPTURE_MARK, POST_EXPAND_CAPTURE_NEW),
    (POST_MERGE_MARK, POST_MERGE_NEW),
    (POST_TRIM_MARK, POST_TRIM_NEW),
    (FINAL_MARK, FINAL_NEW),
]


def apply() -> None:
    text = open(TARGET_FILE).read()
    if "restickify_beam_trace" in text:
        print(f"already patched: {TARGET_FILE}")
        return

    if IMPORT_INJECTION not in text:
        idx = text.find(IMPORT_ANCHOR)
        if idx < 0:
            print(f"FATAL: import anchor not found", file=sys.stderr)
            sys.exit(2)
        text = text[:idx] + IMPORT_INJECTION + text[idx:]

    for old, new in WRAPS:
        c = text.count(old)
        if c == 0:
            print(f"FATAL: anchor missing:\n{old[:200]}", file=sys.stderr); sys.exit(2)
        if c > 1:
            print(f"FATAL: anchor ambiguous ({c}):\n{old[:200]}", file=sys.stderr); sys.exit(2)
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
        print("usage: python restickify_beam_counters.py {apply|revert}", file=sys.stderr)
        sys.exit(2)
    (apply if sys.argv[1] == "apply" else revert)()

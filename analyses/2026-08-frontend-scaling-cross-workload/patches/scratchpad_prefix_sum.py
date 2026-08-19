"""Prototype: replace _extern_kernel_in_live_range's per-buffer O(range)
scan with an O(N)-once prefix-sum + O(1) range query.

Applies to `torch_spyre/_inductor/scratchpad/allocator.py`.

The current implementation walks `range(min(uses), max(uses)+1)` per
buffer and calls `isinstance(graph.operations[i], ExternKernel)` on
every op in the interval. Long-lived buffers (workload A carries)
force O(N) work per buffer, leading to n^~1.45 total scaling on
workload A.

The prototype:

1. Adds a helper `_build_extern_prefix(graph)` that returns an O(N)
   list where `prefix[i]` counts ExternKernel ops in `graph.operations[:i]`.
2. Adds a per-graph memoization slot on the GraphLowering instance
   (`_ts_extern_prefix_cache`) so repeated `_extern_kernel_in_live_range`
   calls within one `scratchpad_planning` invocation share the same
   prefix without rebuilding.
3. Rewrites `_extern_kernel_in_live_range` to use it. Result:
   `prefix[hi+1] - prefix[lo] > 0` — O(1) per buffer.

The cache is intentionally attached to the graph instance rather than
being module-global, so a second compile with a different graph
(fresh instance) does not read a stale prefix. Since `scratchpad_planning`
is called after all mutation is done (post-stickify pass), the graph's
`operations` list is stable during the pass — the cache is valid for
the duration of the pass.

Idempotent — checks marker before applying/removing.
"""
from __future__ import annotations

import os
import sys

TARGET = os.environ.get(
    "SCRATCHPAD_PATH",
    os.path.expanduser("~/pr3806/torch-spyre/torch_spyre/_inductor/scratchpad/allocator.py"),
)

MARKER = "# PROTOTYPE prefix-sum patch"

OLD = '''def _extern_kernel_in_live_range(graph: GraphLowering, uses: list[int]) -> bool:
    """True if an opaque extern kernel runs at any point while the buffer is live.

    The LX scratchpad is a fixed per-core resource shared by *every* compiled
    Spyre program, and it is not threaded through the generated wrapper as a
    tensor -- a resident buffer is handed from one kernel launch to the next by
    its LX offset alone. An extern kernel is opaque: its body can launch other
    compiled programs (a nested ``torch.compile``, or any eager op, which
    torch-spyre compiles standalone via ``compile_once``), and those programs
    allocate the same LX offsets. A buffer left resident across such a call is
    therefore silently overwritten, and its consumer reads the other program's
    data.

    Being *accessed by* the extern kernel is the narrow case (already fatal,
    since the value must be a real HBM tensor to be passed to it); merely being
    live *across* one is equally fatal and is not visible from ``uses``
    membership alone.
    """
    if not uses:
        return False
    return any(
        isinstance(graph.operations[i], ExternKernel)
        for i in range(min(uses), max(uses) + 1)
    )'''

NEW = f'''def _extern_kernel_in_live_range(graph: GraphLowering, uses: list[int]) -> bool:
    """True if an opaque extern kernel runs at any point while the buffer is live.

    The LX scratchpad is a fixed per-core resource shared by *every* compiled
    Spyre program, and it is not threaded through the generated wrapper as a
    tensor -- a resident buffer is handed from one kernel launch to the next by
    its LX offset alone. An extern kernel is opaque: its body can launch other
    compiled programs (a nested ``torch.compile``, or any eager op, which
    torch-spyre compiles standalone via ``compile_once``), and those programs
    allocate the same LX offsets. A buffer left resident across such a call is
    therefore silently overwritten, and its consumer reads the other program's
    data.

    Being *accessed by* the extern kernel is the narrow case (already fatal,
    since the value must be a real HBM tensor to be passed to it); merely being
    live *across* one is equally fatal and is not visible from ``uses``
    membership alone.
    """
    if not uses:
        return False
    {MARKER} — O(N)-once prefix-sum + O(1) range query per buffer.
    prefix = getattr(graph, "_ts_extern_prefix_cache", None)
    if prefix is None:
        n = len(graph.operations)
        prefix = [0] * (n + 1)
        for i, op in enumerate(graph.operations):
            prefix[i + 1] = prefix[i] + (1 if isinstance(op, ExternKernel) else 0)
        graph._ts_extern_prefix_cache = prefix
    lo = min(uses)
    hi = max(uses)
    return prefix[hi + 1] - prefix[lo] > 0'''

# The cache also needs to be invalidated at scratchpad_planning entry
# (in case a previous pass mutated graph.operations). Add a clear at
# the top of scratchpad_planning.
OLD_SP = '''def scratchpad_planning(
    graph: GraphLowering,
    allocator: Optional[ScratchpadAllocator] = None,
) -> None:'''

NEW_SP = f'''def scratchpad_planning(
    graph: GraphLowering,
    allocator: Optional[ScratchpadAllocator] = None,
) -> None:
    {MARKER} — invalidate prefix cache; mutations upstream may have changed graph.operations
    if hasattr(graph, "_ts_extern_prefix_cache"):
        try:
            delattr(graph, "_ts_extern_prefix_cache")
        except AttributeError:
            pass'''


WRAPS = [
    (OLD, NEW),
    (OLD_SP, NEW_SP),
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
        print("usage: python scratchpad_prefix_sum.py {apply|revert}", file=sys.stderr)
        sys.exit(2)
    (apply if sys.argv[1] == "apply" else revert)()

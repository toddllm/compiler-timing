# scratchpad_planning scaling comparison

Extracted from existing datasets (no new runs needed):

## Per-op cost across graph size

| workload | point | input_operations | scratchpad (ms) | µs/op |
|:---|:---|---:|---:|---:|
| B | n=2 | 51 | 295 | 5.8 |
| B | n=4 | 87 | 573 | 6.6 |
| B | n=8 | 159 | 1,101 | 6.9 |
| B | n=16 | 303 | 1,907 | 6.3 |
| A | 256×1024 (b=4) | 110 | 392 | 3.6 |
| A | 512×512 (b=4) | 132 | 431 | 3.3 |
| A | 512×1024 (b=8) | 260 | 962 | 3.7 |
| A | 1024×1024 (b=16) | 516 | 2,390 | 4.6 |
| A | 512×2048 (b=16) | 516 | 2,397 | 4.6 |
| A | 2048×1024 (b=32) | 1,028 | 6,714 | 6.5 |
| A | 512×4096 (b=32) | 1,028 | 6,737 | 6.5 |
| A | 512×8192 (b=64) | 2,052 | 20,993 | 10.2 |
| A | 1024×8192 (b=128) | 4,100 | 74,033 | **18.1** |

## Two very different scaling laws for the SAME code

- **Workload B**: cost per op is essentially FLAT at 5.8-6.9 µs.
  Scratchpad is **linear** in workload B (n^0.94 across the range).
- **Workload A**: cost per op grows 3.6 → 18.1 µs (5×) across a 37×
  graph range. Scratchpad is **superlinear** in workload A, matching
  the #3806 study's reported n^1.45 slope.

## Why the same code shows different scaling

`_extern_kernel_in_live_range` in `scratchpad/allocator.py:122`:

```python
def _extern_kernel_in_live_range(graph: GraphLowering, uses: list[int]) -> bool:
    ...
    return any(
        isinstance(graph.operations[i], ExternKernel)
        for i in range(min(uses), max(uses) + 1)
    )
```

Cost per buffer: O(max(uses) − min(uses) + 1). Total pass work is
Σ over B buffers of (max-min+1). Two extremes:

- All buffer live ranges are LOCAL (small max-min): total = O(B), linear.
- All buffer live ranges SPAN the graph (max-min ≈ N): total = O(B·N),
  quadratic — the n^1.45 behavior in workload A.

**Workload A (OpSpec) has long-lived carry buffers**: `running_max`,
`denominator`, `output` all thread through every inner loop. As Lq/Lk
grow (more inner_bodies), each carry's live range grows with the graph.
Every carry contributes O(N) work per pass call.

**Workload B (KV-chunked FA) has mostly local buffers**: each chunk's
scratch (block_max, exp_scores, weighted, correction) is produced and
consumed within a few ops. Only the top-level running_max/denom/acc
carry through the full loop, so long-lived buffer count is O(1) — the
pass stays linear.

## Priority for workload B

At n_chunks=16, scratchpad_planning = 1.9 s vs coarse_tile_hints = 53.1 s.
Scratchpad is **3.6% of pre-scheduling total**. Not a priority in this
workload family.

For workload A at 1024×8192, scratchpad = 74 s vs Spyre pipes total
~460 s. Scratchpad is **16% of pre-scheduling** — more significant, but
not the top hotspot.

## Recommended fix (LOW/MEDIUM priority; workload A gains only)

Replace the `range(min(uses), max(uses)+1)` scan with a precomputed
prefix-sum of ExternKernel-count. Once per pass:

```python
extern_prefix = [0] * (len(graph.operations) + 1)
for i, op in enumerate(graph.operations):
    extern_prefix[i+1] = extern_prefix[i] + (1 if isinstance(op, ExternKernel) else 0)

# per-buffer check becomes O(1):
def _extern_kernel_in_live_range(graph, uses):
    if not uses:
        return False
    lo, hi = min(uses), max(uses)
    return extern_prefix[hi+1] - extern_prefix[lo] > 0
```

Cost: one-time O(N) build, O(1) per buffer check, total O(N + B).
Compared to O(N · B) current worst case, this collapses the workload A
n^1.45 slope to n^1.0.

Expected impact: scratchpad drops from 74 s → ~4 s at workload A's
largest point. **70 seconds recovered** in the H=8, 1024×8192 case,
but that's a 1-sample preliminary point in the #3806 study.

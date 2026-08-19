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

## Initial hypothesis (subsequently refuted)

`_extern_kernel_in_live_range` in `scratchpad/allocator.py:122`:

```python
def _extern_kernel_in_live_range(graph: GraphLowering, uses: list[int]) -> bool:
    ...
    return any(
        isinstance(graph.operations[i], ExternKernel)
        for i in range(min(uses), max(uses) + 1)
    )
```

Cost per buffer is proportional to `max(uses) − min(uses) + 1`, so
buffers with wide live ranges pay O(N) per query. Two extremes are
possible:

- All buffer live ranges LOCAL (small max-min): total = O(B), linear.
- All buffer live ranges SPAN the graph (max-min ≈ N): total = O(B·N).

Combined with the observation that **workload A (OpSpec) has
long-lived carry buffers** (`running_max`, `denominator`, `output`
thread through every inner loop, so their live ranges grow with the
graph) and **workload B carries stay bounded per chunk**, this looked
like a source-level explanation for the different scaling laws.

**Prototype measurement disagreed.** A prefix-sum implementation that
turns the per-buffer scan into O(1) is in
[`../patches/scratchpad_prefix_sum.py`](../patches/scratchpad_prefix_sum.py).
Measured effect on `_maybe_scratchpad_planning`:

- 512×4096 (b=32): 6,722 ms → 6,594 ms (1.9%, within noise)
- 512×8192 (b=64): 21,037 ms → 20,833 ms (1.0%, within noise)

The `_extern_kernel_in_live_range` function is called, but the
`isinstance(op, ExternKernel)` check inside it is cheap enough that
even with wide live ranges it is not the pass hotspot. Full write-up
is in
[`scratchpad-prototype.md`](scratchpad-prototype.md).

## What is still true

- **The measured cross-workload difference is robust**: linear on
  workload B, n^1.45 on workload A. That is the finding worth
  carrying forward.
- **The per-op cost table above** is measurement, unaffected by the
  refutation.
- **The topology observation** (workload A carries are long-lived,
  workload B buffers are per-chunk) is a real graph-shape difference
  — it just isn't what makes `scratchpad_planning` slower on A.

## What is not yet known

The mechanism responsible for the workload-A n^1.45 slope is
**unattributed**. `scratchpad_planning` contains buffer construction,
several possible layout solvers (workload A's `cost_model=""` config
selects a default allocator), `plan_allocation` internals, and a
fallback greedy path. One of these is the actual hotspot; only
substage instrumentation *inside* `plan_allocation` can identify it.

## Priority for workload B

At n_chunks=16, scratchpad_planning = 1.9 s vs coarse_tile_hints = 53.1 s.
Scratchpad is **3.6% of pre-scheduling total**. Not a priority in this
workload family.

For workload A at 1024×8192, scratchpad = 74 s (preliminary, n=1)
vs Spyre pipes total ~460 s. Scratchpad is a meaningful minority
component at the largest workload-A points; identifying the real
driver would be worthwhile after the coarse-tile fix (opportunity #1)
lands.

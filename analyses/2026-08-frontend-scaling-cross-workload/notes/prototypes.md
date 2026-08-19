# Local prototypes — opportunity sizing

## Prototype #1 — memoize `_reads_buffer` via existing `op_read_writes` helper

**Status**: FAILED at first cold compile. Reverted. Not upstreamed.

### Hypothesis

`_reads_buffer` in `wsr/coarse_tile.py:1850` calls raw
`op.get_read_writes()` which re-runs sympy dep extraction on every
call. Swap it to the memoized `op_read_writes(op)` helper defined at
`pass_utils.py:96`. Expected impact: reduce per-op cost across three
substages of `_maybe_coarse_tile_hints` (74% + 22% of umbrella at
n_chunks=8), plus workload B's inflated dedup constant.

### Result

At workload B n_chunks=2 smoke run:

```
InductorError: RuntimeError: Failed to find buffer matching name buf31
```

### Cause

`op_read_writes`'s docstring explicitly warns: it caches only for
callers that don't cross op-mutation boundaries. The coarse-tile
substages mutate ops (`replace_computed_buffer_body`,
`_allocate_full_buffer`, `_insert_copy_op`) between calls, so a
memoized ReadWrites from an earlier call contains buffer names that
were rewritten in the meantime.

### What this tells us

A naïve single-line swap is unsafe. The correct fix is one of:

1. **Per-substage local memo**: build the cache INSIDE the substage
   function, discard on exit. Never crosses mutating passes.
2. **Cache invalidation on mutation**: mutating helpers invalidate
   `_ts_cached_read_writes` on touched ops. Broader refactor.
3. **Reverse-adjacency built once per substage**: replace
   "does op X read buf Y?" pairs with a single
   `{buf_name: set[op_names]}` walk of `operations`. All the
   `_find_outside_consumers*` sites become dict lookups. **Does not
   need memoization at all**; recomputable safely after each mutation.

Option 3 is what the source-audit recommended and what the "high
confidence fix #1" in [`findings.md`](findings.md) proposes.

### Value of the null result

- Confirmed the cost driver exists (the raw call IS invoked O(N × K)
  times per substage — that structural fact is unchanged).
- Ruled out a trivial one-liner. Any real fix has to respect
  mutation boundaries.
- Preserves the correctness of the pipeline while sizing the
  opportunity: at n_chunks=8, ~13 s of the 14 s `_maybe_coarse_tile_hints`
  is in the two substages that would benefit from option 3.

Patch preserved in `patches/reads_buffer_memoize.py` (in scratch, not
committed) as a negative-result artifact.

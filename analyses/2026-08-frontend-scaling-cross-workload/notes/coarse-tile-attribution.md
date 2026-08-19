# _maybe_coarse_tile_hints — full 100% substage attribution

Data: `data/workload-B-post-instr-v3/` — 4 runs (3× n=4, 1× n=8).
Instrumentation: `patches/coarse_tile_substage_timing.py` v3 (10 wraps
covering every non-trivial callsite in `_coarse_tile_common`).

## Full decomposition (medians)

| substage | n=4 (ms) | n=8 (ms) | 4→8 ratio | % of umbrella at n=8 |
|---|---:|---:|---:|---:|
| **resync_and_patch_load_indexes** | **2,752** | **10,259** | **3.73×** | **74.5%** |
| plan_tiling_propagation | 840 | 3,042 | 3.62× | 22.1% |
| insert_all_read_copy_ops | 358 | 265 | 0.74× | 1.9% |
| plan_coarse_tile_groups | 85 | 160 | 1.89× | 1.2% |
| plan_read_copies | 23 | 40 | 1.77× | 0.3% |
| apply_plan_loop | 5 | 10 | 1.84× | 0.1% |
| insert_all_write_copy_ops | 1.7 | 1.8 | 1.11× | 0.01% |
| log_propagation_self_check | 0.0 | 0.0 | — | 0% |
| validate_writer/reader | 0.1 | 0.1 | — | 0% |
| insert_all_reduction_ops | 0.0 | 0.0 | — | 0% |
| **SUM** | 4,064 | 13,779 | 3.39× | — |
| **UMBRELLA** | **4,068** | **13,779** | **3.39×** | — |
| unattributed (umbrella - sum) | 4 | 0 | — | ~0.0% |

## The two dominant substages

**Combined 96.6% of the pass at n_chunks=8.** Both scale near-quadratically.

### #1 — `resync_and_patch_load_indexes` (74.5%)

The resync tail block in `_coarse_tile_common` (lines 1483-1489):

```python
name_to_op = {op.get_name(): op for op in operations if isinstance(op, ComputedBuffer)}
for group_id, group_ops, retiled_infos in retiled_infos_by_group:
    for idx, op in enumerate(group_ops):
        if not isinstance(op, ComputedBuffer):
            continue
        group_ops[idx] = name_to_op.get(op.get_name(), op)
    _patch_retiled_load_indexes(group_id, group_ops, retiled_infos, operations)
```

Cost is dominated by ONE call to `_patch_retiled_load_indexes` (workload B has
`n_groups=1`). See `notes/08-patch-retiled-load-indexes.md` for the deep
source dive. Two cost drivers identified:

1. **`_reads_buffer` (coarse_tile.py:1913) calls raw
   `op.get_read_writes()` instead of the memoized `op_read_writes` helper**
   (pass_utils.py:97-111). Each call re-runs sympy dependency extraction.
2. **`replace_computed_buffer_body` (pass_utils.py:1342) uses
   `operations.index(op)`** — O(N) linear scan per splice.

Predicted asymptotic: Θ(N²). Predicted n=4 timing: 2.0 s (measured 2.75 s);
predicted n=8: 7.2 s (measured 10.3 s). Predicted 4→8 ratio: 3.6×
(measured 3.73×). Very close for a source-only prediction.

### #2 — `plan_tiling_propagation` (22.1%)

Same shape as originally hypothesized in `notes/02-coarse-tile-source-map.md`:
per grouped op, `_find_outside_consumers_planned(op)` walks all `operations`
calling `_reads_buffer` (which in turn calls raw `op.get_read_writes()`).

`n_grouped_ops × n_ops` product: 65×73 = 4745 at n=4; 129×137 = 17,673 at
n=8. Ratio = 3.72×. Measured pass ratio = 3.62×. Within 3%. Fits nearly
perfectly — the small residual is per-op sympy cost.

## Why the source predictions ranked wrong

- `plan_tiling_propagation` was the "prime suspect" in the static analysis
  because the loop structure was clearest. But `resync_and_patch_load_indexes`
  is bigger because it hits BOTH cost drivers (raw `get_read_writes()` inside
  `_reads_buffer` × several ops × sympy per-call cost, PLUS O(N) list splices
  from `replace_computed_buffer_body`), whereas `plan_tiling_propagation`
  mainly pays the first driver.
- `insert_all_read_copy_ops` was ranked as a co-quadratic candidate. Reality:
  workload B has only 1 read-copy plan (n_groups=1) with a small `entries`
  list, so the O(N)-per-entry `name_to_op` rebuild is amortized to near-zero.
  The prediction was correct in shape but wrong in scale for this workload.

## Why we couldn't guess this from source alone

`_patch_retiled_load_indexes` is not itself a nested op-scan — it processes
one group at a time. The blow-up is INSIDE `_reads_buffer` (cold sympy
extraction) and INSIDE `replace_computed_buffer_body` (O(N) splice). Both
hidden one level of indirection down. Only source-read plus per-substage
timing exposed the actual cost distribution.

## Highest-leverage local fix candidate

From `notes/08`:
1. **Fix 1**: swap `op.get_read_writes()` → `op_read_writes(op)` (memoized
   helper already exists in `pass_utils.py`). Removes the R-multiplier.
2. **Fix 2**: build a reverse-adjacency `buf_readers: dict[str, list[Op]]`
   once from `retiled_names`. Cuts the R-per-op scan to O(consumers).
3. **Fix 3**: precompute `op_to_position` (already used at
   `coarse_tile.py:1480`) and reuse for `replace_computed_buffer_body`
   splices. Removes the O(N) `operations.index()`.

Fixes 1+2+3 together should collapse `resync_and_patch_load_indexes` from
Θ(N²) to Θ(N). Since it's 74% of umbrella and umbrella grows near-quadratic,
this alone could turn 4×-per-doubling into 2×-per-doubling — a substantial
reduction of the reported 20/81/321 s curve.

Combined with a similar fix to `plan_tiling_propagation` (also 22% of
umbrella, same underlying `_reads_buffer` mechanism), the pass could
become fully linear in graph size.

## Instrumentation cost audit

Instrumented n_chunks=4 wall clock: 63 s median (baseline 60 s). ~5%
overhead — acceptable for a decomposition run.

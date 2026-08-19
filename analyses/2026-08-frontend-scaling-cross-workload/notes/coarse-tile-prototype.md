# Coarse-tile reverse-adjacency prototype — MEASURED

Prototype patch: [`patches/coarse_tile_reverse_adj.py`](../patches/coarse_tile_reverse_adj.py).

Applies a **mutation-safe per-substage reverse adjacency** to
`torch_spyre/_inductor/wsr/coarse_tile.py`. Builds one O(N)
`readers_by_buffer` + `reads_by_op` index at substage entry, uses it
inside the substage, discards on exit. Scoped so it cannot survive
mutations across substage boundaries — the same failure mode that
broke the earlier naïve global-memoize prototype
(`notes/prototypes.md`).

Two substages patched:

- `_plan_tiling_propagation` — planning, pre-mutation. Index built
  once at entry; used to replace the O(N × K) per-op walk in
  `_find_outside_consumers_planned` with a dict lookup.
- `_patch_retiled_load_indexes` — resync tail, per group after
  mutations of the previous group are visible. Index rebuilt fresh at
  each group entry; used to replace the `_should_patch_retiled_load_indexes`
  membership check with an O(1) set-intersection.

## Correctness

CPU reference `torch.testing.assert_close(equal_nan=True, atol=0.01,
rtol=0.1)` passes at n_chunks=2 smoke run (`meta.cpu_reference_ok=True`).

## Measured impact — workload B, 3 samples per point

| n_chunks | metric | baseline (post-fix) | reverse-adj patch | speedup |
|:---:|:---|---:|---:|---:|
| 4 | `_maybe_coarse_tile_hints` | 4.110 s | 1.403 s | **2.93×** |
| 4 | Spyre pipes total | 7.99 s | 5.24 s | 1.53× |
| 4 | `compile_fx_wrapper` | 42.18 s | 36.24 s | 1.16× |
| 4 | `dxp_standalone` | 23.32 s | 23.01 s | 1.01× (unchanged) |
| 4 | `dedup_and_promote_constants` | 0.662 s | 0.658 s | unchanged |
| 4 | `optimize_restickify_locations` | 1.049 s | 1.044 s | unchanged |
| 8 | `_maybe_coarse_tile_hints` | 14.464 s | 3.933 s | **3.68×** |
| 8 | Spyre pipes total | 23.30 s | 12.81 s | 1.82× |
| 8 | `compile_fx_wrapper` | 105.81 s | 91.12 s | 1.16× |
| 8 | `dxp_standalone` | 69.07 s | 69.07 s | 1.00× (unchanged) |
| 8 | `dedup_and_promote_constants` | 2.479 s | 2.490 s | unchanged |
| 8 | `optimize_restickify_locations` | 2.300 s | 2.294 s | unchanged |

## Scaling law shift

The critical measurement:

| variant | `_maybe_coarse_tile_hints` growth 4→8 |
|:---|:---:|
| baseline | **3.52×** (near-quadratic) |
| reverse-adj | **2.80×** |

Baseline was on track for ~4×-per-doubling at higher chunks (baseline
8→16 was 3.67×). The reverse-adj patched version at 4→8 is 2.80×,
substantially closer to the linear ideal of 2.0×. Extrapolating from
the current pair, patched behavior at n=16 would be `~11 s` vs the
baseline `53 s` — a ~5× reduction at the point that hurt most.

That prediction is currently extrapolation, not measurement — a
patched n=16 run would confirm. Given the 4→8 shift is already
`3.52× → 2.80×`, the direction of the scaling change is confirmed;
only the exact magnitude at n=16 is estimated.

## What did not change

- `dedup_and_promote_constants` — untouched (uses a separate code path
  in `_inductor/dedup_constants.py`). Its constant is still workload-B
  inflated by the same `get_read_writes` mechanism; that is a separate
  fix.
- `optimize_restickify_locations` — untouched.
- `dxp_standalone` — backend, unaffected as expected.
- Other Spyre passes — untouched.

## Backend still dominates absolute time

At n=8, patched Spyre-owned frontend is now 12.8 s while `dxp_standalone`
is 69 s. Backend is 5× the Spyre frontend after the fix; before, it was
3× the Spyre frontend. As predicted throughout this study, moving the
frontend needle at scale mostly shifts weight into the backend column
rather than reducing wall-clock proportionally. `compile_fx_wrapper`
speedup is a modest 1.16× at these workload sizes.

The backend-team-owned `dxp_standalone` growth remains the single
biggest absolute compile-time contributor at scale.

## Engineering-risk notes

- Naïve global memoization via `op_read_writes` broke correctness on
  first smoke — cached ReadWrites became stale across the mutation
  boundary between substages. This prototype avoids that by building
  the index inside each substage from a fresh snapshot of
  `operations`, and discarding it on substage exit. See
  `notes/prototypes.md` for the null-result documentation.
- The patch adds one `_build_reads_indexes(operations)` helper and
  wraps three source locations. No cross-file changes.
- `_should_patch_retiled_load_indexes` is inlined at its one call site
  in the prototype; a production PR would preserve that function's
  callable identity for testability.

## Files

- Patch: `patches/coarse_tile_reverse_adj.py` (apply / revert)
- Baseline data: `data/workload-B-post-fix/` (n_chunks=4 and 8 rows)
- Patched data: `data/workload-B-revadj/`

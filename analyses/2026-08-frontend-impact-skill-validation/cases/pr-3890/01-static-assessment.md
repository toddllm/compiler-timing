# Static assessment — PR #3890

**Written BEFORE any measurement.**

## Target

- Kind: pr
- Repo: torch-spyre/torch-spyre
- PR: #3890
- Base ref → head ref: main → 148de44b93
- URL: https://github.com/torch-spyre/torch-spyre/pull/3890
- Title: Fix 2 bugs in coarse_tile related to dimensions of size 1

## Diff summary

- Files changed: 2
- +222 / −21

Changed paths:
- `tests/inductor/test_coarse_tile_e2e.py` (adds regression coverage)
- `torch_spyre/_inductor/wsr/coarse_tile.py`

## Per-path static triage

| Path | Stage | Hot-path? | Confidence |
|---|---|---|---|
| tests/inductor/test_coarse_tile_e2e.py | test_only | no | high |
| torch_spyre/_inductor/wsr/coarse_tile.py | coarse_tile | yes | high |

## What the PR actually does

Fixes two correctness bugs in coarse-tile compile:

1. **Raw vs squeezed-dim mismatch** in `_tiled_dims_for_dep`
   (`coarse_tile.py`). `per_level_extents` is keyed by raw positional
   indices, but `dep.index`'s free symbols are squeezed. The fix adds
   a new function `_raw_to_squeezed_pos(ir_node)` that builds a
   translation table by mirroring `SpyreKernel._host_dim_to_index_symbol`'s
   squeeze arithmetic, then applies the translation before the
   `dep_dims` membership test.
2. **Wrong `active_full_sizes`** in `_insert_one_read_copy`. Previously
   used `dep.size[i]` (reader's tile-local extent) instead of the
   buffer's full/untiled size, silently making
   `compute_tile_stride`'s size//tile_size ratio 1 for every dim.
   Fix derives full sizes from active dims' stride ordering.

The PR body explicitly says these fixes address a **compile-time
crash** for coarse-tiled kernels — i.e. the pre-fix behavior was
`validate_writer_tile_advance` failure, not slow compilation.

## Applying the three-questions rule

1. **Does the changed code execute on the timed compile path in a
   sentinel workload?**
   - `_tiled_dims_for_dep` is called inside `_plan_tiling_propagation`
     — YES. On WB workload it runs O(K) times per pass with K = ops
     per coarse-tile group.
   - `_insert_one_read_copy` is called inside `_insert_all_read_copy_ops`
     — YES. Runs O(E) times per pass with E = read-copy plan entries.
   - Both are on hot paths in workload B.
2. **Hot inner loop or setup?**
   - Fix 1: adds `_raw_to_squeezed_pos(ir_node)` call inside
     `_tiled_dims_for_dep`. This builds a small dict once per call.
     Each call is O(dims × free_symbols).
   - Fix 2: `_insert_one_read_copy` rewrites the `active_full_sizes`
     computation with an O(active_dims × log(active_dims)) approach
     (sorting by stride). Was O(active_dims) list indexing — new
     approach is slightly heavier but still tiny.
3. **Alter collections/constants that made a pattern superlinear?**
   No. Both fixes are per-op constant work.

## Predicted affected compiler surface

- `_maybe_coarse_tile_hints` — should get **slightly slower** because
  each `_tiled_dims_for_dep` call now builds an extra dict, and each
  `_insert_one_read_copy` call now does slightly more computation.
  Effect magnitude: **small**. My rough estimate: additional
  ~5–20 µs per op per pass call.
- Total added cost at WB n=4 (n_ops ≈ 105, ~1–2 substage calls
  per op): ~1–5 ms per compile. Below measurement noise (WB n=4
  spread is 100+ ms sample-to-sample).
- Structural counters: **should not move**. The fixes correct
  arithmetic, not what work gets done on the valid-input path.

## Prediction

- **Direction**: mild regression on `_maybe_coarse_tile_hints` (from
  added computation), but small.
- **Magnitude class**: **small** — likely below measurement noise on
  WB n=4 and possibly detectable at WB n=8 where more calls
  accumulate.
- **Verdict class expected**: `NO_MEASURABLE_FRONTEND_IMPACT` at
  WB n=4; possibly `NO_MEASURABLE_FRONTEND_IMPACT` at WB n=8 too.
  If the extra dict-building is more expensive than estimated,
  `STRUCTURAL_CHANGE_NEUTRAL` or a small `FRONTEND_REGRESSION`.

**IMPORTANT**: this is a bug fix. If it's a small regression,
that's correctness cost, not a performance defect.

## Failure modes for this prediction

- If sentinel workloads DO trigger the bug, they would have been
  crashing pre-fix. Verified: current post-fix workload B compiles
  fine, and the pre-fix code path also compiled these workloads
  (verified across the entire cross-workload study). So neither
  bug affects the sentinel workloads' compile path.
- If the extra dict-building surprises us and is measurably slow,
  that's a real regression to flag.

## Confidence

**HIGH**. Both fixes are localized changes to per-op arithmetic on
correctness paths that were previously silently wrong for specific
shapes. Sentinel workloads didn't trigger the bugs so the change
should be near-neutral there.

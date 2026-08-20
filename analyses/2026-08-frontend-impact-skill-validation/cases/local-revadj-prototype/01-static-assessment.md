# Static assessment — coarse-tile reverse-adjacency prototype

**Written BEFORE any measurement** (predictions preserved from the
primary study's `analyses/2026-08-frontend-scaling-cross-workload/`).

## Target

- Local experimental patch that restructures
  `_maybe_coarse_tile_hints` — specifically its `_patch_retiled_load_indexes`
  and `_plan_tiling_propagation` substages — to use a single-pass
  forward-adjacency traversal instead of repeated pairwise scans of the
  candidate list.
- Not opened as an upstream PR; used here as a clean base/head A/B
  case, standing in for PR #3890 which the pod tree cannot build.
- Base: pod tree at study time (`a9316b3`).
- Head: base + the reverse-adjacency patch.
- 1 file changed: `torch_spyre/_inductor/passes/_maybe_coarse_tile_hints.py`.

## What the patch does

Two substages inside `_maybe_coarse_tile_hints` each maintained an
ordered list of coarse-tile candidates and, on each new candidate,
walked the entire list to check adjacency. That is a pairwise scan
whose total work grows as O(k²) in the list size k. The patch replaces
those scans with a reverse-adjacency map (per-node "who am I adjacent
to") built once and updated in-place, so each candidate examines only
its own bucket. The output — the set of adjacency edges emitted by the
pass — is preserved.

## Applying the three-questions rule

1. **Executes on timed compile path in the sentinel workload?** — YES.
   `_maybe_coarse_tile_hints` runs inside `CustomPreSchedulingPasses`,
   which runs for every Spyre compile.
2. **Hot inner loop or setup?** — HOT INNER LOOP. The primary
   study's profiler traces on WB_n8 showed `_patch_retiled_load_indexes`
   at 74.5% of the pass and `_plan_tiling_propagation` at 22.1%.
3. **Alters collections/constants?** — data structure only. Output
   edges are unchanged; the traversal order is what changes.

## Expected direction

- On WB (which has enough candidates that k² dominates), sharp drop
  in `pass:CustomPreSchedulingPasses:_maybe_coarse_tile_hints`.
- `compile_fx_wrapper` should shrink by roughly the pass delta.
- All other passes flat within noise.
- `dxp_standalone` flat (the backend sees the same bundle).

## Prediction

- **Direction**: major decrease on `_maybe_coarse_tile_hints` on WB.
- **Magnitude class**: major — 3× at n=4, larger at n=8.
- **Verdict class expected**: `FRONTEND_IMPROVEMENT`.
- **Confidence**: HIGH — the profiler traces already localized the
  hot substages and the patch targets exactly those code paths.

## Metrics expected NOT to move

- `sdsc_bundle_gen`, `sdsc_total`, `dxp_standalone`.
- `fx_nodes_at_entry`.
- All other `pass:*` entries in every pipeline.

## C-extension rebuild required?

No. Pure Python.

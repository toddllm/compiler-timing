# Experiment plan — PR #3890

**Written BEFORE any measurement.**

## Level decision

- **Chosen level**: **3** (SCALING_RUN) then reduced to targeted
  scaling pair.
- **Rationale**: static_triage returned Level 3 because coarse_tile
  is a known dominant WSR pass. However, the specific change is a
  correctness fix on non-sentinel-triggering paths, so a full
  SCALING_RUN is over-provisioned. Reduce to a WB_scaling_pair
  (n_chunks=4 and n_chunks=8) — enough to detect a scaling-law
  change if the fix has one, less device time than adding n=16.

## Sentinels selected

| Sentinel | Point | Samples | Paired? | Rationale |
|---|---|---:|:---:|---|
| WB_scaling_pair | n_chunks=4 | 3 base, 3 head | yes | Detects effect on hot path |
| WB_scaling_pair | n_chunks=8 | 3 base, 3 head | yes | Detects scaling-law change |

## Metrics expected to move

- `_maybe_coarse_tile_hints` — expect small regression (~1–5 ms per
  compile at n=4, ~2–10 ms at n=8) from added `_raw_to_squeezed_pos`
  dict-building and heavier `active_full_sizes` computation.
- Substage attribution (if we enable coarse-tile substage timing):
  - `plan_tiling_propagation` — `_raw_to_squeezed_pos` runs inside
    `_tiled_dims_for_dep` here → tiny per-op cost increase.
  - `insert_all_read_copy_ops` — `_insert_one_read_copy`'s new
    `active_full_sizes` computation → tiny per-entry cost increase.

## Metrics expected NOT to move

- `dedup_and_promote_constants` — different code path.
- `optimize_restickify_locations` — different code path.
- `_maybe_scratchpad_planning` — different pass.
- `propagate_spyre_tensor_layouts` — different pass.
- `dxp_standalone` — the generated program is unchanged for
  sentinel workloads because those workloads don't trigger the bug.

## Structural counters to record

- `fx_nodes_at_entry` — should be unchanged for sentinel workloads.
- `n_specs` — should be unchanged.
- If ANY of the structural counters change, the fix is affecting
  more workloads than expected → escalate to Level 4.

## C-extension rebuild required?

No. Pure Python change.

## Estimated device time

- Actual: 3×60 s + 3×60 s (base+head at n=4) + 3×125 s + 3×125 s
  (base+head at n=8) = 360 + 750 = 1110 s ≈ 18.5 min.
- Naive baseline: 27 min.
- Savings: ~8 min.

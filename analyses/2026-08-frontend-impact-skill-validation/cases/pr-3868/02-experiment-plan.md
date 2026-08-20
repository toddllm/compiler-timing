# Experiment plan — PR #3868

**Written BEFORE any measurement.**

## Level decision

- **Chosen level**: **1** (TARGETED_RUN), possibly extended to
  Level 2 if WB and WA disagree.
- **Rationale**: `codegen/bundle.py` is a single file, on the hot
  path (called for every compile), with a clear semantic change.
  A single sentinel at moderate size should reveal the direction
  of impact.

## A/B strategy

The diff applies cleanly to the pod tree (`git apply --check`
returned no errors). Use in-place patch swap:

- **Base**: pod tree as-is (`a9316b3` + our instrumentation).
- **Head**: pod tree + PR #3868's diff applied.
- Interleave samples base1/head1/base2/head2/base3/head3.

## Sentinels selected

| Sentinel | Point | Samples | Paired | Rationale |
|---|---|---:|:---:|---|
| WB_n4 | n_chunks=4 | 3 base, 3 head | yes | KV-chunked has structural repetition — expect cache hits. |
| WB_n8 | n_chunks=8 | 3 base, 3 head | yes | Doubles the number of repetitive ops, giving more cache hits. |

## Metrics expected to move

- `sdsc_bundle_gen` — decrease (fewer distinct sdsc_<idx>.json).
- `sdsc_total` — decrease.
- `dxp_standalone` — maybe decrease (backend sees smaller bundle).
- Possibly `compile_fx_wrapper` — since `sdsc_*` is inside it.

## Metrics expected NOT to move

- All pre-scheduling passes (`_maybe_coarse_tile_hints`, etc).
- `fx_nodes_at_entry`.

## Structural counters to record

- `n_specs` at `sdsc_bundle_gen` — MAY change (fewer distinct
  specs). If it decreases at head, verdict is
  `STRUCTURAL_CHANGE_NEUTRAL` (fewer specs means less backend
  work, not the same work faster).

## C-extension rebuild required?

No. Pure Python.

## Estimated device time

- Actual plan: (3×60s + 3×60s) at n=4 + (3×125s + 3×125s) at n=8
  = 360 + 750 = 1110 seconds ≈ 18.5 minutes.
- Naive baseline: ~27 minutes.
- Savings: ~8 min (we could have run WA too but the mechanism is
  KV-chunk-repetition-sensitive, so WB is targeted).

# Experiment plan — PR #3873

**Written BEFORE any measurement.**

## Level decision

- **Chosen level**: **1** (TARGETED_RUN)
- **Rationale**: layout_prop + ir_lowering hit the hot path, but
  the actual change is gated on `FixedTiledLayout` presence, which
  only occurs when user code passes `device_layout=`. Sentinel
  workloads don't use it. One cheap sentinel confirms the
  no-default-path-change prediction; the PR's own test verifies
  activated-path functionality.

## Sentinels selected

| Sentinel | Point | Samples | Paired? | Rationale |
|---|---|---:|:---:|---|
| WB_n4 | n_chunks=4 | 3 base, 3 head | yes (interleaved) | WSR/KV-chunked workload has multiple `torch.full` constant-fill ops per chunk (running_max, denom, acc). If the extra `isinstance` check moved anything, it would be measurable here more than in WA. |

## Metrics expected to move

None on default path.

## Metrics expected NOT to move

- `_maybe_scratchpad_planning`
- `propagate_spyre_tensor_layouts` (isinstance check is <100 ns per
  constant-fill op)
- `optimize_restickify_locations` (candidate set for constant-fills
  unchanged on default path: still 1 generic candidate)
- `_maybe_coarse_tile_hints`
- `dedup_and_promote_constants`
- `compile_fx_wrapper`
- `dxp_standalone`

## Structural counters to record

- `fx_nodes_at_entry` — the `_monkey_patch.py` layer might add an
  extra op node per `torch.full` call even when no `device_layout=`
  is provided (if the patch always routes through the custom op).
  If FX@entry changes, structural, not performance.
- `n_specs`

## C-extension rebuild required?

No. Pure Python.

## Estimated device time

- Actual: 6 × 60 s ≈ 6 min.
- Naive baseline: ~27 min.
- Savings: ~21 min.

## Notes

- The `_monkey_patch.py` file is currently classified as
  `other_torch_spyre` by static_triage.py. If measurement reveals
  it's on a hot path, add a rule for it.

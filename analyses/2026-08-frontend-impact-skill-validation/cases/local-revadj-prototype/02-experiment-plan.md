# Experiment plan — coarse-tile reverse-adjacency prototype

**Written BEFORE any measurement.**

## Level decision

- **Chosen level**: **1** (TARGETED_RUN).
- **Rationale**: single-file change in a single pre-scheduling pass,
  with a well-understood workload dependence (WB_n has enough
  candidate tiles to trigger the k² behavior). Two points on WB
  (n=4 and n=8) tell us direction AND scaling-law shift.

## A/B strategy

- **Base**: pod tree as-is (`a9316b3` + primary-study instrumentation).
- **Head**: pod tree + the reverse-adjacency patch applied in-place.
- Base and head captured back-to-back on the same pod, same venv,
  same TORCHINDUCTOR_CACHE_DIR discipline (fresh dir per sample).
- NOT interleaved — this predates the skill's paired-sampling
  requirement. Still admissible because the deltas are order-of-magnitude
  and there is no evidence of drift within the base or head triple.

## Sentinels selected

| Sentinel | Point | Samples | Rationale |
|---|---|---:|---|
| WB_n4 | kv_block=1024, n_chunks=4 | 3 base, 3 head | Baseline WB size — hot pass already ~4s |
| WB_n8 | kv_block=512,  n_chunks=8 | 3 base, 3 head | Doubled n; the pass grows 3.5x on base |

## Metrics expected to move

- `pass:CustomPreSchedulingPasses:_maybe_coarse_tile_hints` — major decrease.
- `compile_fx_wrapper` — decrease by roughly the pass delta.
- `first_call_wall` — decrease (compile is a large share of first-call wall).

## Metrics expected NOT to move

- `sdsc_*`, `dxp_standalone`.
- Every other `pass:*` entry.
- `device_init_and_transfer`.

## Structural counters to record

- None expected to move — the patch preserves the emitted edge set.
  We will verify this by confirming `dxp_standalone` is flat: the
  backend receives the same bundle so any counter-based change would
  show up there.

## C-extension rebuild required?

No.

## Estimated device time

- ~1 minute per WB_n4 sample, ~2 minutes per WB_n8 sample.
- 3 base + 3 head at each point ≈ (6 × 60) + (6 × 125) = 1110 s.
- Actual wall clock: matches within a few percent.

# Scratchpad ExternKernel prefix-sum prototype — NEGATIVE RESULT

Prototype patch: [`patches/scratchpad_prefix_sum.py`](../patches/scratchpad_prefix_sum.py).

## Hypothesis

The static complexity audit and cross-workload comparison identified
`_extern_kernel_in_live_range` in `scratchpad/allocator.py:122` as the
likely driver of workload A's `n^1.45` scaling on
`_maybe_scratchpad_planning`. The function walks
`range(min(uses), max(uses)+1)` per buffer, calling
`isinstance(op, ExternKernel)` on every op in the interval.
Long-lived carry buffers in workload A make per-buffer scan lengths
grow with graph size, so total pass work grows O(N·B).

Source-level estimate: replacing the per-buffer scan with an
O(N)-once prefix-sum + O(1) range query per buffer should collapse
the n^1.45 slope to near-linear. Estimated: 74 s → ~4 s at
`Lq=1024, Lk=8192` (b=128), the largest measured point.

## Prototype

Adds an O(N)-once prefix-sum of ExternKernel counts, cached on the
GraphLowering instance (`_ts_extern_prefix_cache`) and invalidated at
`scratchpad_planning` entry. Every `_extern_kernel_in_live_range`
call becomes a single subtract.

## Correctness

`torch.testing.assert_close(atol=0.01, rtol=0.1)` passes at workload
A baseline (Lq=512, Lk=1024) smoke run.

## Measured impact

Two workload A points, baseline vs patched (3 samples baseline vs
3 patched at 512×4096; 3 baseline vs 1 patched at 512×8192):

| point | metric | baseline (ms) | patched (ms) | speedup | saved (ms) |
|:---|:---|---:|---:|---:|---:|
| 512×4096 (b=32) | `_maybe_scratchpad_planning` | 6,722 | 6,594 | **1.019×** | 128 |
| 512×4096 (b=32) | `compile_fx_wrapper` | 568,028 | 559,046 | 1.016× | 8,982 |
| 512×8192 (b=64) | `_maybe_scratchpad_planning` | 21,037 | 20,833 | **1.010×** | 204 |
| 512×8192 (b=64) | `compile_fx_wrapper` | 2,379,656 | 2,377,908 | 1.001× | 1,749 |

Per-op scratchpad cost:

| point | baseline µs/op | patched µs/op | change |
|:---|---:|---:|---:|
| b=32 | 6,539 | 6,414 | −1.9% |
| b=64 | 10,252 | 10,153 | −1.0% |

## Verdict

**The prefix-sum change is essentially a no-op at these workload sizes.**
The 128 ms / 204 ms deltas are within run-to-run measurement noise
(the compile_fx values themselves vary by ~1% between successive cold
compiles). The `optimize_restickify` "speedup" of 1.19× in the same
runs is unrelated to the patch — restickify code was not touched — and
demonstrates run-to-run variance on this test point.

**The source-audit estimate (74 s → 4 s at b=128) is not confirmed.**
The `_extern_kernel_in_live_range` function is not the dominant term
in `_maybe_scratchpad_planning`.

## What this means

`scratchpad_planning`'s n^1.45 scaling in workload A must come from
elsewhere in the pass — the interval scan is not the culprit. The
static audit correctly identified an O(N·B) pattern in the code, but
`isinstance(op, ExternKernel)` is empirically cheap enough that the
scan cost is dominated by other per-op work.

Candidates for the real n^1.45 driver (all in
`scratchpad/allocator.py` or its sibling solver files, none yet
attributed by instrumentation):

- Per-buffer construction of `LifetimeBoundBuffer` objects — the audit
  did not measure allocation/dataclass overhead.
- Layout solver work (workload A's `cost_model=""` config selects a
  default allocator; the greedy/first-fit/exhaustive/ILP/simulated_annealing
  variants each have their own cost curves).
- `plan_allocation` internals that scale with buffer count times
  op count for other reasons.

## Correct next step

Add substage instrumentation *inside* `scratchpad_planning` — split
`allocator.plan_allocation` into its constituent phases — before
proposing another prototype. The static audit hit its useful limit
here; only per-phase measurement will identify the real hotspot.

## Value of the null result

- Confirms an important disciplinary point: **static-audit predictions
  need measurement before they enter the ranked opportunity list as
  "high-confidence".** This prototype was ranked "low risk" but the
  source hypothesis was wrong.
- Refines the opportunity map: `_extern_kernel_in_live_range` moves
  from "opportunity #2" to "measured null, not the driver".
- Preserves the correctness (no measurement regression) and the
  patch stays available as a micro-optimization if the real driver
  is later fixed and this becomes a residual second-order term.

## Files

- Patch: [`patches/scratchpad_prefix_sum.py`](../patches/scratchpad_prefix_sum.py) — apply / revert
- Baseline data: [`../../2026-08-pr3806-frontend-timing/data/`](../../2026-08-pr3806-frontend-timing/data/) — `512x4096-run*.json`, `512x8192-run*.json`
- Patched data: [`data/workload-A-scratchpad-proto/`](../data/workload-A-scratchpad-proto/)

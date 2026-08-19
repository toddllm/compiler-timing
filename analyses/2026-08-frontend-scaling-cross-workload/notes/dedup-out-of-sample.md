# Dedup out-of-sample validation on workload B

Data: `data/workload-B-post-fix/` — 10 samples across n_chunks ∈ {2, 4, 8, 16}.
No refitting: apply the pr3806 coefficient `t ≈ 201.8 µs × (ops × dups)`
without adjustment.

## Out-of-sample prediction using pr3806 coefficient

| n_chunks | n | input_ops | dups | ops×dups | predicted (ms) | measured (ms) | error |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 3 | 55 | 4 | 220 | 44 | 184 | **+316%** |
| 4 | 3 | 95 | 8 | 760 | 153 | 662 | **+332%** |
| 8 | 3 | 175 | 16 | 2,800 | 565 | 2,479 | **+339%** |
| 16 | 1 | 335 | 32 | 10,720 | 2,163 | 10,013 | **+363%** |

## The shape holds; the constant does not

Per-(ops × dups) cost within workload B:

| n_chunks | t / (ops × dups)  |
|---:|---:|
| 2 | 836 µs/pair |
| 4 | 871 µs/pair |
| 8 | 885 µs/pair |
| 16 | 934 µs/pair |

**Very stable — 836 → 934 (a 12% drift over an 8× range).** The
`t ∝ ops × dups` law holds cleanly WITHIN workload B, exactly as it did
within #3806.

## Least-squares refit on workload B

Coefficient = **930.6 µs / (ops × dups)** — 4.61× higher than #3806's
201.8 µs. The pr3806 coefficient does not transfer.

## Interpretation

The `ops × dups` structural cost model is a real invariant across
workloads. The per-op constant factor `C_op` — the cost of one
`op.get_read_writes()` and the enclosing `for op in operations` /
`operations.remove(dup)` bookkeeping — is workload-dependent.

Plausible drivers of a larger `C_op` in workload B vs A:
1. **Inner_fn complexity**: workload B ops carry richer inner_fn bodies
   (softmax reductions, matmul-plus-broadcast chains, restickify inserts).
   ComputedBuffer's uncached `get_read_writes` re-runs sympy dep
   extraction over the inner_fn every call, so a longer inner_fn = higher
   per-call cost.
2. **Consumer counts**: workload B constant-fill ops feed multiple
   consumers via the diamond pattern; `_redirect_consumers` walks each of
   them per duplicate.
3. **Wrap depth**: workload B has more layers of `MutationLayout`/
   `SqueezingCoordinatesLayout` wrapping than A's OpSpec tiles.

## What this pins for the study

- **Cost-model generalization is TIER-2**: shape (`ops × dups`) generalizes;
  coefficient does not. Any "predict compile time from static graph
  metrics" tool needs to fit `C_op` per workload family.
- **Dedup remains a fixable structural hotspot in both workloads.** In
  workload B at n_chunks=8, dedup is 2.5 s = 10% of umbrella
  `_maybe_coarse_tile_hints`. Fixing it to `Θ(N)` shape would remove 5-10s
  of frontend cost at chunks=16.
- The 4.6× workload-B coefficient underscores that per-op `get_read_writes`
  cost is a real, workload-dependent variable — **the same variable that
  drives the `_patch_retiled_load_indexes` and `_plan_tiling_propagation`
  substages** which each call the same uncached routine.

Fixing `get_read_writes` uncached-ness in `_reads_buffer` (via the memoized
`op_read_writes` helper) would benefit ALL THREE of these hotspots
simultaneously.

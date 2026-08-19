# Cross-workload frontend compiler scalability

Frontend compilation-time investigation across two distinct Torch-Spyre
FlashAttention workload families:

- **A — OpSpec / static tiled FlashAttention**. Graph expansion from
  statically unrolled tiled attention. Detailed measurement in the
  sibling study
  [`../2026-08-pr3806-frontend-timing/`](../2026-08-pr3806-frontend-timing/).
- **B — WSR / coarse-tiled KV-chunked FlashAttention**. Python-level K/V
  chunk loop unrolled into the graph, WSR H/Lq coarse tiling, active
  `_maybe_coarse_tile_hints`, exercises the layout beam optimizer with
  constant-fill diamonds.

## Questions this study answers

1. Which compiler stages dominate across distinct workload regimes?
2. Which costs are graph/IR-size driven, and which depend on tensor
   extents at fixed graph size?
3. Which arise from search-state / candidate-set explosion?
4. Which are linear, superlinear, quadratic, or combinatorial for
   identifiable source-level reasons?
5. Where would the next engineering work give the largest compile-time
   reduction, and with what confidence?
6. Which conclusions generalize across workloads and which are specific
   to OpSpec tiling, WSR/coarse tiling, or unrolled K/V chunking?

The primary artifact answering these questions is
[`notes/findings.md`](notes/findings.md). This README is methodology and
reproduction.

## What's new here vs the PR #3806 study

The PR #3806 study measured workload A exhaustively. This study:

- Adds workload B measurements (KV-chunked FA) at n_chunks ∈ {2, 4, 8, 16}
  pre-fix (where n=8/16 fail — the exact issue #3687 failure signature)
  and post-fix (where they succeed).
- Instruments the `_maybe_coarse_tile_hints` pass at substage
  granularity — Phase-3-level decomposition that closes 100% attribution
  and identifies `_patch_retiled_load_indexes` as the true dominant
  substage (74.5% of the pass at n=8), followed by
  `_plan_tiling_propagation` (22.1%).
- Extends the `dedup_and_promote_constants` cost model
  (`t ≈ c × operations × duplicates` from #3806) to workload B as an
  out-of-sample test. The shape generalizes tightly; the coefficient
  does not (4.6× larger on B due to richer per-op inner_fns).
- Instruments `optimize_restickify_locations`' beam frontier evolution
  under both pre-fix and post-fix layout candidates. Directly shows
  the constant-fill collapse mechanism.
- Isolates `Lq` and `Lk` extent effects at fixed chunk count. On this
  tree neither dimension drives compile cost at fixed n_chunks (a
  null result for the extent-scaling hypothesis).

## Datasets

Under [`data/`](data/):

- `workload-B-pre-fix/`  — 6 samples, n_chunks ∈ {2, 4} at 3 samples each.
  Pre-fix `_all_constant_layouts`. n_chunks=8 crashed with `buf112 no
  mechanism` at `optimize_restickify.py:704` — the exact issue #3687
  signature.
- `workload-B-post-fix/` — 10 samples, n_chunks ∈ {2, 4, 8} at 3 each +
  n_chunks=16 at 1. Post-fix `[generic_layout(op)]`. All succeed.
- `workload-B-post-instr-v3/` — 4 samples with coarse-tile substage
  instrumentation active; n_chunks=4 × 3 + n_chunks=8 × 1.
- `workload-B-beam-trace-prefix/` — 2 samples, n_chunks=2 and 4, with
  beam-frontier counters. n_chunks=8 crashed.
- `workload-B-beam-trace-postfix/` — 4 samples, n_chunks ∈ {2, 4, 8, 16},
  beam-frontier counters.
- `workload-B-lq-sweep/` — 7 samples at fixed n_chunks=4 with `lq_tiles=None`,
  varying Lq ∈ {64, 128, 256, 512, 1024, 2048, 4096}. Extent-independent.
- `workload-B-lq-tiled-sweep/` — 4 samples at fixed n_chunks=4 with
  `lq_tiles=2`, varying Lq ∈ {256, 512, 1024, 2048}. Also extent-independent.
- `workload-B-lk-sweep/` — 5 samples at fixed n_chunks=4, varying
  Lk ∈ {1024, 2048, 4096, 8192, 16384} (kv_block scaled to keep chunks fixed).
  Extent-independent.

## Reproduction

Prerequisites: same as the PR #3806 study — torch-spyre PR #3806 head
(`a9316b3`) or an equivalent main snapshot; the timing_recorder +
compile_fx_wrapper instrumentation in place.

Toggle between pre-fix and post-fix layouts using
[`patches/toggle_layout_fix.sh`](patches/toggle_layout_fix.sh). Toggle
substage timing on/off with
[`patches/coarse_tile_substage_timing.py`](patches/coarse_tile_substage_timing.py).
Beam-frontier counters live in
[`patches/restickify_beam_counters.py`](patches/restickify_beam_counters.py).
Run the sweeps with
[`patches/run_kvchunk_sweep.sh`](patches/run_kvchunk_sweep.sh) and
its Lq/Lk variants.

## Limitations

- **Single tree snapshot.** All measurements on pr3806-base main
  snapshot with the 1-line layout fix applied. PR #3812's other
  additions (`perm_layout_native.cpp`, expanded
  `span_overflow_hint_analysis.py`, scratchpad allocator revisions)
  are not exercised here.
- **The PR docstring's ">2 hour" extent-driven pathology does not
  reproduce on this tree.** Distinguishing "different code path" from
  "different C-extension" would require building the pr3812 tree
  separately.
- **Local prototypes are opportunity sizing, not upstream candidates.**
  The one prototype attempted (memoize `_reads_buffer`) broke correctness
  and was reverted; the correct fix requires cache invalidation on
  mutation. See [`notes/prototypes.md`](notes/prototypes.md).
- Workload B baseline uses 3 samples at n_chunks ∈ {2, 4, 8} and 1
  sample at n_chunks=16. Doubling ratios are more reliable at low
  chunk counts.

## Related work

- The PR #3806 study
  [`../2026-08-pr3806-frontend-timing/`](../2026-08-pr3806-frontend-timing/)
  for workload A methodology and detailed timings.
- torch-spyre PR #3812 for the constant-fill layout candidate change
  and its 8/16/32-chunk reference numbers.
- torch-spyre issue #3687 for the pre-fix `buf112` exponential-beam
  mechanism.

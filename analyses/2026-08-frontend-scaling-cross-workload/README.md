# Cross-workload frontend compiler scalability

Frontend compilation-time investigation across two Torch-Spyre
FlashAttention workload families:

- **Workload A — OpSpec / static tiled FlashAttention.** Detailed
  measurement lives in the sibling study
  [`../2026-08-pr3806-frontend-timing/`](../2026-08-pr3806-frontend-timing/).
- **Workload B — WSR / coarse-tiled KV-chunked FlashAttention, derived
  from PR #3812.** Measurements here were taken on the pr3806-base tree
  with the relevant constant-fill layout behavior toggled between the
  pre-fix and post-fix variants; this is not the full PR #3812 tree.

## Where to start (in order)

1. **[`SUMMARY.md`](SUMMARY.md)** — a 2-minute overview of what was
   investigated, the four independent scaling mechanisms identified,
   and the top four opportunities. Send this first to a technical
   lead.
2. **[`notes/engineering-opportunities.md`](notes/engineering-opportunities.md)**
   — ranked action list with evidence level and measured-vs-estimated
   labels. For anyone deciding what to work on.
3. **[`notes/findings.md`](notes/findings.md)** — full technical
   synthesis. For anyone who wants to challenge or reproduce.
4. Focused technical notes:
   - [`notes/coarse-tile-attribution.md`](notes/coarse-tile-attribution.md) — 100% substage decomposition of `_maybe_coarse_tile_hints`.
   - [`notes/restickify-beam-evolution.md`](notes/restickify-beam-evolution.md) — pre-vs-post-fix beam frontier data.
   - [`notes/dedup-out-of-sample.md`](notes/dedup-out-of-sample.md) — `ops × dups` cost model across workloads.
   - [`notes/extent-scaling.md`](notes/extent-scaling.md) — Lq / Lk extent independence at fixed chunk count.
   - [`notes/scratchpad-scaling.md`](notes/scratchpad-scaling.md) — same code, workload-dependent scaling.
   - [`notes/extra-timers-closure.md`](notes/extra-timers-closure.md) — 100% attribution of `compile_fx_wrapper`.
   - [`notes/coarse-tile-prototype.md`](notes/coarse-tile-prototype.md) and [`notes/scratchpad-prototype.md`](notes/scratchpad-prototype.md) — measured optimization prototypes.
   - [`notes/prototypes.md`](notes/prototypes.md) — negative-result documentation.
   - [`notes/methodology.md`](notes/methodology.md) — cold-compile hygiene, cache-path scheme, instrumentation overhead.

## Two figures worth 20 seconds each

- [`plots/workload-B-frontend-composition.png`](plots/workload-B-frontend-composition.png)
- [`plots/cross-workload-mechanism-matrix.png`](plots/cross-workload-mechanism-matrix.png)

## Datasets and instrumentation

Under [`data/`](data/) — 52+ sanitized JSON samples across 9 dataset
subdirs covering: pre-fix and post-fix baseline sweeps, coarse-tile
substage instrumentation, restickify beam-frontier traces, Lq extent
sweeps at two `lq_tiles` settings, Lk extent sweep at fixed n_chunks,
and extra-timers full-closure runs on both workloads.

Under [`patches/`](patches/) — the workload harness, driver scripts,
three instrumentation patches (coarse-tile substage timing, restickify
beam counters, upstream Inductor extra_timers), the layout-fix toggle,
and analyzers.

## Ground rules preserved from the PR #3806 study

- Cold compilation only. Warm runs are labeled and used only as sanity
  checks.
- Every timed sample carries its git SHA, an environment probe, the
  resolved compiler configuration, and the exact
  `TORCHINDUCTOR_CACHE_DIR` string the driver used.
- Instrumentation must reconcile to the enclosing wall-clock stage;
  every residual is reported explicitly.
- Spyre runs strictly serially — the device is exclusive per process.
- Committed drivers are the exact scripts that produced the committed
  data; no post-hoc rewriting of measurement metadata.

## Limitations

- All Workload B measurements on the pr3806-base main snapshot with the
  1-line layout fix toggled. PR #3812's other additions
  (`perm_layout_native.cpp`, expanded `span_overflow_hint_analysis.py`,
  scratchpad allocator revisions) are not exercised here.
- The PR docstring's ">2 hour" Lq=8192 pathology does not reproduce on
  this tree; see [`SUMMARY.md`](SUMMARY.md) open questions.
- Prototype measurements use n_chunks ≤ 8 for the coarse-tile
  prototype and 32/64-body workload-A points for the scratchpad
  prototype; the larger 128-body A point was preliminary (n=1) even in
  the primary study and is not the right validation target for either
  prototype.

## Related work

- Sibling study [`../2026-08-pr3806-frontend-timing/`](../2026-08-pr3806-frontend-timing/)
  for the workload A detailed measurements and methodology.
- torch-spyre PR #3812 for the constant-fill layout candidate change
  and its own reference numbers at 8/16/32 chunks.
- torch-spyre issue #3687 for the pre-fix `buf112` exponential-beam
  failure mechanism.

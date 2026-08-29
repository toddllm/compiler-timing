# Next material pre-DXP optimization targets

**Status: methodology + rules, pending pod data.** Once
`data/sweep/` is populated by `harness/sweep_driver.sh` and
`harness/analyze_sweep.py` has produced `pre-dxp-attribution.md` and
`tables/scaling.md`, fill in the ranked list at the bottom of this
document from those tables directly.

## Ranking criteria

A pre-DXP bucket is ranked material when **all three** hold:

1. **Absolute share ≥ 5% of pre-DXP total** at the study's largest
   flash shape (`flash-1024x8192`). Anything smaller has upper-bounded
   impact even if perfectly eliminated.
2. **Log-log slope > 0.6 against `fx_nodes_at_entry`**. Buckets that
   already scale near-linearly-or-better with graph size are the ones
   whose absolute cost grows fastest as models grow.
3. **A clean, torch-Spyre-side lever exists.** Upstream Inductor code
   is out of scope for this epic unless a torch-Spyre-side hook can
   change what the upstream call sees (as `enable_spyre_context` does
   for pre/post-grad passes today).

A bucket is ranked deferred when only 1 of the 3 holds; excluded when
none do.

## Non-optimization actions the study also produces

- **Baseline record.** `data/sweep/` is checked in raw so a future
  regression run can diff against a known-good pre-DXP shape.
- **Attribution reference.** Once populated, other reviewers can point
  at `pre-dxp-attribution.md` instead of re-instrumenting.
- **Scaling markers.** `tables/scaling.md` gives per-bucket log-log
  slopes; a bucket that turns from sub-linear to super-linear in a
  future run is a regression alert.

## Priors from PR #3806

The pre-scheduling passes with the largest wall-clock share on the
prior study's shapes were, in descending order:

- `optimize_restickify_locations`
- `insert_restickify`
- `dedup_and_promote_constants` (now optimized via PR #4113 — verify
  it dropped out of the top-K in the new sweep)
- `_maybe_coarse_tile_hints`
- `finalize_layouts`

`spyre_kernel_codegen` (upstream Inductor's per-kernel codegen
dispatch calling into `SpyreKernel.codegen_kernel`) is the largest
non-pass consumer of pre-DXP time in the same study. It scales with
the number of kernels emitted rather than FX node count, so it
appears near the top on split-kernel graphs and lower on
single-kernel ones.

## Investigation template per bucket

For each material bucket, before deciding whether it is a material
target, produce:

- **Time cost:** absolute ms + share at largest flash shape,
  absolute ms + share at smallest flash shape.
- **Growth:** log-log slope, plus which axis actually drives it
  (`fx_nodes_at_entry`, `input_operations`, kernel count, …). If
  slope vs. `fx_nodes` looks noisy, re-fit vs. the bucket's natural
  input size and see whether it tightens.
- **What the bucket does:** one-paragraph summary of the code the
  bucket brackets. File:line anchor.
- **Where the time actually goes inside it:** for
  `custompresched`, this is answered directly by
  `tables/pass-detail.md`. For other buckets, add a targeted
  sub-instrumentation follow-up rather than guessing.
- **Lever candidates:** 1-3 concrete things that could change what
  the bucket does. Include the argument for why the change is
  correctness-preserving.
- **Expected upside:** rough estimate of how much of the bucket's ms
  each lever could remove, and therefore how much of `pre_dxp_total`.
- **Cost:** implementation effort + review + risk. For each lever,
  is this a next-quarter thing or a next-week thing?

## Ranked opportunities

*(To be filled in from real data.)*

### Rank 1 — TBD
### Rank 2 — TBD
### Rank 3 — TBD

### Deferred

- Buckets that meet criterion 1 but not 2 (large but non-scaling):
  worth investigating only when the bucket is directly on the
  critical path for a specific user request.
- Buckets that meet criterion 2 but not 1 (scaling fast but small):
  worth a regression watch, not an active target.

### Explicitly excluded

- Anything past `dxp_standalone` — DXP itself is separate work.
- Anything already addressed by PR #4113 (dedup_and_promote_constants)
  — if it reappears in the pass-detail table, that's a regression
  signal, not a new opportunity.

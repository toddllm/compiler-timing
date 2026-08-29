# Next material pre-DXP optimization targets

**Status: methodology + rules, pending pod data.** Once
`data/sweep/` is populated and `harness/analyze_sweep.py` has
produced `pre-dxp-attribution.md`, `tables/scaling.md`,
`tables/pass-detail.md`, and `tables/reconciliation.md`, fill in the
ranked list at the bottom of this document from those tables
directly.

## Ranking philosophy

We rank buckets by **judgment across several axes**, not by a
hard AND-gate. A large sub-linear bucket can matter more than a tiny
super-linear one. A super-linear slope is a warning to investigate,
not a requirement.

Axes considered per bucket:

- **Absolute milliseconds** at the largest measured shape. A bucket
  that costs 20 ms perfectly eliminated cannot beat one that costs
  400 ms halved.
- **Share of pre-DXP time** at the largest measured shape. Same idea,
  normalized so we compare apples to apples across studies.
- **Scaling in natural units.** For every bucket, `scaling.md` fits
  the log-log slope against the bucket's natural independent
  variable (FX nodes, pre-scheduling ops, scheduler nodes, emitted
  kernel count, OpSpec count, etc.), and reports per-unit drift (ms
  per natural unit). Slope > 1 is a super-linear alarm — investigate
  regardless of current absolute cost.
- **Expected future work-unit growth.** Some units grow faster than
  others as models scale. If kernels-per-graph is growing quarter over
  quarter, per-kernel buckets deserve extra weight.
- **Confidence in attribution.** A directly-measured bucket has high
  confidence; a derived residual has lower. Derived residuals appear
  in the report but are ranked accordingly.
- **Existence of a practical lever.** Buckets bracketed by
  torch-Spyre-side code have obvious levers. Buckets whose time is
  entirely in upstream Inductor may still have a Spyre-side hook
  (e.g. `enable_spyre_context` for pre/post-grad passes), but the
  investigation may need to establish that first.
- **Correctness / review risk.** A change that touches
  `insert_restickify` is riskier than a change that touches a
  peripheral pass. Weight against that.

## Explicit exclusions

- **Anything past `dxp_standalone`.** DXP itself is separate work.
- **Anything already addressed by PR #4113.** If
  `dedup_and_promote_constants` reappears in the top-K
  (`tables/pass-detail.md`) at large shapes, that is a regression
  signal, not a new opportunity.
- **The restickify family.** Will is pursuing that track. We include
  restickify buckets in the tables as context, not as targets.

## Non-optimization deliverables the study produces

- **Baseline record.** `data/sweep/` is checked in raw at the
  frozen torch-spyre SHA so a future regression run can diff against
  a known-good pre-DXP shape.
- **Attribution reference.** Reviewers can point at
  `pre-dxp-attribution.md` instead of re-instrumenting.
- **Scaling markers.** `tables/scaling.md` gives per-bucket log-log
  slopes with per-unit drift; a bucket that turns from sub-linear to
  super-linear in a future run is a regression alert.
- **Reconciliation record.** `tables/reconciliation.md` shows the
  per-run residual so anyone reading a bucket number knows how much
  is attributed vs unaccounted-for.

## Investigation template per candidate bucket

Before proposing a bucket as a material target, produce:

- **Time cost:** absolute ms + share at largest flash shape and at
  smallest flash shape.
- **Growth:** slope against natural unit, per-unit drift, and which
  independent variable actually drives it. If slope vs `fx_nodes`
  looks noisy, re-fit against the bucket's natural input size and
  see whether the fit tightens.
- **What the bucket does:** one paragraph summary of the code the
  bucket brackets. File:line anchors at the frozen SHA.
- **Where the time actually goes inside it:** for
  `custompresched_total`, this is answered directly by
  `tables/pass-detail.md`. For other buckets, add a targeted
  sub-instrumentation follow-up rather than guessing.
- **Lever candidates:** 1-3 concrete things that could change what
  the bucket does. Include the argument for correctness-preservation
  and for review-tractability.
- **Expected upside:** rough estimate of how much of the bucket's ms
  each lever could remove, therefore how much of `pre_dxp_total`.
- **Cost:** implementation effort, review, risk. Next-quarter or
  next-week?
- **Confidence:** high / medium / low, with what would raise it.

## Ranked opportunities

*(To be filled in from real data.)*

### Rank 1 — TBD
### Rank 2 — TBD
### Rank 3 — TBD

### Deferred with reason
### Excluded with reason

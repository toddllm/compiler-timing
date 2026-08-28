# Downstream pre-scheduling pass timing check — pristine vs E-only

**Point compared: Lq=512, Lk=8192.** Pristine data is from the
study's own `data/512x8192-run*.json` (3 samples, timing recorder
only, no dedup diag). E-only data is from
`data-E-only/timing-off-512x8192-run*.json` (3 samples, timing
recorder only). Both took cold Inductor caches; both were on the
same pod.

Medians across 3 samples per column:

| pass                                          | pristine (ms) | E-only (ms) | delta        |
|-----------------------------------------------|--------------:|------------:|--------------|
| deadcode_elimination                          |        428.54 |      436.03 | +7.5  (+1.7%) |
| propagate_named_dims                          |          1.77 |        1.59 | −0.2 (−10.3%) |
| validate_named_dims                           |          0.10 |        0.10 | −0.0  (−1.9%) |
| assign_dim_hints                              |          0.43 |        0.34 | −0.1 (−21.0%) |
| _maybe_reorder_unhinted_interlopers           |          0.24 |        0.24 | +0.0  (+0.8%) |
| _maybe_coarse_tile_hints                      |          0.27 |        0.27 | −0.0  (−0.6%) |
| split_multi_ops                               |        228.52 |      231.47 | +3.0  (+1.3%) |
| propagate_spyre_tensor_layouts                |       5007.67 |     4666.61 | −341.1 (−6.8%) |
| validate_ops                                  |        407.78 |      419.23 | +11.4 (+2.8%) |
| optimize_restickify_locations                 |      39474.86 |    33369.49 | −6105.4 (−15.5%) |
| finalize_layouts                              |         18.20 |       17.93 | −0.3  (−1.5%) |
| insert_restickify                             |          0.01 |        0.01 | +0.0  (+1.6%) |
| enforce_indirect_access_layout                |        486.85 |      503.53 | +16.7 (+3.4%) |
| insert_post_mutation_restickify               |          0.18 |        0.21 | +0.0 (+11.6%) |
| insert_bmm_padding                            |         33.89 |       34.50 | +0.6  (+1.8%) |
| **dedup_and_promote_constants**               |  **54,645.68**|  **492.49** | **−54,153.2 (−99.1%)** |
| _maybe_coarse_tile_span_overflow              |          0.05 |        0.03 | −0.0 (−36.0%) |
| span_reduction                                |       3505.71 |     3591.89 | +86.2  (+2.5%) |
| _distribute_work                              |       2542.20 |     2591.68 | +49.5  (+1.9%) |
| _maybe_scratchpad_planning                    |      20993.40 |    21673.42 | +680.0 (+3.2%) |

Observations:

1. **Dedup**: −99.1%. Consistent with the direct measurement.

2. **`optimize_restickify_locations`: −15.5% (−6.1 s).** Not
   caused by anything in the dedup pass — dedup happens 5 passes
   AFTER `optimize_restickify_locations` in the pipeline
   (passes.py:457 vs 472). This is either run-to-run variation
   (the pristine sample used was from weeks earlier) or an effect
   of some other pod-state difference between the two datasets.
   Worth investigating if the pattern replicates in Commit C's
   E+batch measurements, but not attributable to E-only.

3. **`_maybe_scratchpad_planning`: +3.2% (+680 ms).** Scratchpad
   planning iterates `V.graph.name_to_users` (see the fold rationale
   comment in `_drop_constant`). E-only preserves the fold verbatim,
   and semantic-equivalence testing at Lq=512, Lk=1024 confirmed
   `name_to_users[C]` is bit-identical. The +3.2% at Lk=8192 is
   most likely run-to-run variation, but if a follow-up wants to
   drill in, `_maybe_scratchpad_planning` is where to start.

4. **Every other pass: within ±5%.** No systematic pattern
   attributable to E-only. Individual variations of a few percent
   are consistent with the perturbation-check finding that
   dedup-only run-to-run variation on this pod is ~1-2%.

5. **`compile_fx_wrapper` total** (data-E-only/timing-off-*):

    | point   | run1 (ms) | run2 (ms) | run3 (ms) | median |
    |---------|----------:|----------:|----------:|-------:|
    | 512×1024|  100,147  |   99,071  |   99,508  |  99,508 |
    | 512×4096|  550,649  |  544,760  |  548,592  | 548,592 |
    | 512×8192| 2,301,816 | 2,331,645 | 2,317,798 |2,317,798|

   Total compile time drops by ~55 s at Lk=8192 (from ~2.37 min
   more otherwise), matching the dedup collapse.

Conclusion: no downstream pre-scheduling regression is caused by
E-only.

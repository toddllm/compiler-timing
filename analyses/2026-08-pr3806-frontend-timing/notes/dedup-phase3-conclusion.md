# `dedup_and_promote_constants` — Phase 3 Conclusion

**Status: complete. Two candidate implementations measured (E-only,
E+batch). Both semantically equivalent to pristine `a9316b381` on
the PR #3806 test_flash workload. Recommendation for the next
step below.**

Companion to `notes/dedup-phase2-plan.md`. Reads bottom-up: source
facts → Phase 2 measured → E-only measured → E+batch measured →
remaining hypotheses → recommendation.

## Section 1 — Source-derived facts (not measured, just from reading)

These are properties of the pristine `a9316b381` implementation of
`dedup_and_promote_constants` and its dependencies. Empty of
performance claims; those come from measurement below.

1. **Pass structure.** Three steps. Step 1 groups
   `SpyreConstantFallback` ops by `(constant_args[0], layout.dtype,
   normalized_device)`. Step 2 iterates each duplicate in each
   group, calling `_redirect_consumers(operations, dup, canonical)`
   then `_drop_constant(operations, dup, canonical)`. Step 3
   filters `operations` into constants-first order.

2. **`_redirect_consumers` walks all of `graph.operations`** per
   duplicate, calling `op.get_read_writes()` on each op and
   patching any hit's `inner_fn` via `NameSwapHandler`. Source-
   derived cost: `O(N × D × f_grw)` where `f_grw` is the
   per-op cost of `get_read_writes()`.

3. **`_drop_constant` calls `operations.remove(dup)`** — an O(N)
   list scan — per duplicate. Adds an `O(N × D)` term to the
   pass cost. Also does `merge_provenance`, `removed_buffers.add`,
   `name_to_buffer.pop`, `name_to_op.pop`, and folds
   `name_to_users[D]` into `name_to_users[C]`.

4. **`ComputedBuffer.get_read_writes()` is uncached** at torch 2.13
   (`torch/_inductor/ir.py:5281`) and reruns
   `extract_read_writes(store_function, sizes)` — a MockHandler
   walk of the buffer's `inner_fn` — on every call.

5. **`GraphLowering.register_users_of`** at
   `torch/_inductor/graph.py:1128` operates only on the top-level
   `TensorBox` returned by `run_node`. It does NOT recursively
   visit `ComputedBuffer`s created inside a decomposed lowering.

6. **`SpyreConstantFallback` has empty `inputs`**, so its
   `get_read_writes()` (inherited from `InputsKernel`) returns an
   empty read set — cheap and irrelevant for consumer discovery.

7. **`insert_bmm_padding`** at `torch_spyre/_inductor/padding.py`
   calls `lower_pad_sequence`, which invokes
   `graph_lowering.run_node` on a `constant_pad_nd` FX node. That
   single `run_node` produces four IR operations inside a
   decomposition: an allocation `ComputedBuffer`, the
   `SpyreConstantFallback` fill constant, a fill Pointwise
   `ComputedBuffer` that reads the constant, and a copy Pointwise
   `ComputedBuffer` (`pass_utils.py:1215–1219` at `a9316b381`).

8. From (5) + (7): the fill Pointwise that reads the constant is
   an INTERNAL `ComputedBuffer` inside the decomposition. It never
   gets its own `register_users_of` call. Consequence:
   `name_to_users[<constant_name>]` for a padding-constant does
   NOT contain the fill Pointwise. This is a source-level
   observation confirmed by Phase 2 measurement below.

## Section 2 — Phase 2 measured facts

Full data at `data-diag/`. Measured on
`tdeshane-compiler-timing-dev-v2` (RHEL 9.6, Python 3.12.13, torch
2.13.0+cpu, torch-spyre `a9316b381` with diagnostic instrumentation
gated on `TORCH_SPYRE_DEDUP_DIAG=1`; the instrumented path is
inert with the env var unset). 3 cold samples per point.

1. **Pristine dedup wall-clock (medians):**
   - Lq=512, Lk=1024: **976.9 ms**
   - Lq=512, Lk=4096: **15,697.1 ms**
   - Lq=512, Lk=8192: **62,189.4 ms**

2. **Cost decomposition (median % of dedup_total):** `get_read_writes`
   99.1–99.2% at every point. `operations.remove` 0.02–0.03%.
   `merge_provenance` smaller still. Everything else <1%.

3. **Coefficient stability:** `total_ms · 1000 / (N × D)` = 221 /
   224 / 223 µs at the three points. `f_grw ≈ 228 µs` per op,
   independent of N.

4. **name_to_users evidence:** 624 / 624 duplicates across the
   sweep had their gold consumer absent from `name_to_users[D]`.
   The mechanism is exactly (5) + (7) + (8) above: the fill
   Pointwise reader is an internal node, not registered.

5. **Diagnostic perturbation:** median DIAG-ON vs DIAG-OFF at
   Lq=512, Lk=1024: +1.23%. Individual samples overlap.
   Diagnostic timers add negligible overhead. This CORRECTS an
   earlier draft that attributed a ~10% coefficient gap between
   the study's original 201.8 µs fit and Phase 2's ~222 µs fit to
   the timers; the gap is ordinary run/environment variation.

## Section 3 — E-only measured facts

Full data at `data-E-only/`. Same environment. E-only variant
swapped in for `torch_spyre/_inductor/dedup_constants.py`. Change
vs pristine: per-duplicate O(N) scan replaced with a single O(N)
reverse consumer index built once, scoped to duplicate names,
after grouping determined duplicates exist. Per-duplicate
`operations.remove(dup)` preserved. 3 DIAG-OFF + 3 DIAG-ON samples
per point.

1. **Dedup wall-clock (DIAG-OFF medians):**
   - Lq=512, Lk=1024: **60.0 ms** (**16.3×** vs pristine)
   - Lq=512, Lk=4096: **249.7 ms** (**62.9×** vs pristine)
   - Lq=512, Lk=8192: **492.5 ms** (**126.3×** vs pristine)

2. **Work-count collapse:** `get_read_writes` calls dropped from
   `N × D` to `N` at every point. `n_ops_scanned = 0` at every
   sample — the per-duplicate outer scan is gone. `n_consumer_hits
   = D` at every sample — every gold consumer found via the local
   reverse index.

3. **Model check:** predicted N · f_grw + D · O(1) + O(N).
   Predicted ~64 / 252 / 503 ms; measured 60.0 / 249.7 / 492.5 ms.
   Within 2% at every point.

4. **DIAG-OFF vs DIAG-ON perturbation within E-only:** +1.43% /
   +1.77% / −0.75% at the three points. Same order as pristine
   perturbation.

5. **Semantic equivalence** (Lq=512, Lk=1024, via
   `patches/semantic_equiv_harness.py` +
   `patches/diff_semantic_state.py`, comparing normalized
   `graph.operations`, surviving-constant identity keys,
   `removed_buffers`, `name_to_buffer` keys, `name_to_op` keys,
   `name_to_users` entries, per-consumer live reads, and provenance
   history): **EQUIVALENT**.

6. **Downstream pass timings:** every pre-scheduling pass other
   than dedup changed by ±5% or less at Lk=8192. No systematic
   regression attributable to E-only. Full breakdown in
   `data-E-only/downstream-pass-check.md`.

7. **Tests:** 11/11 pass (5 pristine + 5 new deterministic + 1 E2E
   padding). Zero skips.

## Section 4 — E+batch measured facts

Full data at `data-E-batch/`. Change vs E-only: per-duplicate
`operations.remove(dup)` replaced with a single Step-3
filter/rebuild via `dead_ids: set[int]`. Same 3+3 samples per
point.

1. **Dedup wall-clock (DIAG-OFF medians):**
   - Lq=512, Lk=1024: **61.3 ms** (+2.2% vs E-only)
   - Lq=512, Lk=4096: **254.1 ms** (+1.8% vs E-only)
   - Lq=512, Lk=8192: **494.8 ms** (+0.5% vs E-only)

2. **All deltas within noise** (perturbation-check finds run-to-run
   variation of ~1-2% on this pod).

3. **Mechanism:** `n_operations_remove_calls = 0` at every sample,
   `operations_remove_ns = 0` at every sample. Batch removal ran.

4. **Incremental value:** batch removal saves E-only's rm_ms (0.17
   / 2.09 / 8.19 ms) and adds a small dead-id filter cost to the
   final rebuild (~40–200 µs). Net saving at Lk=8192: ~8 ms of a
   ~492 ms dedup — ~1.5%.

5. **Semantic equivalence** (Lq=512, Lk=1024): EQUIVALENT to both
   pristine and E-only.

6. **Tests:** 11/11 pass. Zero skips.

## Section 5 — Remaining hypotheses (open, not resolved by this phase)

1. **Model constant `f_grw` on other workloads.** The `~228 µs`
   per-op cost of `ComputedBuffer.get_read_writes()` is only
   measured on this workload's Pointwise mixture. Workloads with
   Reduction-heavy inner functions or different loop-body sizes
   may exhibit different `f_grw`. Not a concern for landing E,
   but worth watching if we later profile a different flash
   variant.

2. **`_maybe_scratchpad_planning` +3.2%** at Lk=8192 vs the study's
   own baseline. The pass iterates `name_to_users`; E-only
   preserves the fold verbatim; semantic-equivalence at
   Lq=512, Lk=1024 confirmed the fold is bit-identical. The +3.2%
   is most likely run-to-run variation, but if further drilling
   is desired, this is the first candidate.

3. **`optimize_restickify_locations` −15.5%** in the same Lk=8192
   comparison. This pass runs BEFORE dedup in the pipeline, so it
   cannot be caused by E-only. Most likely pod-state / OS-cache
   variation across the weeks between the two datasets. Not
   attributable to the change.

4. **Output-name latent behavior bug.** Documented in `notes/
   dedup-source-analysis.md §8` and unchanged in Phase 2/3.
   Preserved verbatim by both E-only and E+batch — deliberately
   not fixed as part of this refactor.

5. **Upstream `register_users_of` cannot see internal decomposed
   readers.** This is the source-level fact behind Section 2.4.
   Fixing it upstream would make Option A viable — but that's an
   upstream Inductor change with a much broader population than
   the constant-dedup pass. Out of scope here.

6. **Same speedup on non-`test_flash` workloads.** Only measured
   on PR #3806 `test_flash`. Workloads without unaligned-K bmms
   or without `constant_pad_nd` decomposition paths won't show
   the same D scaling and therefore won't show the same speedup
   ratio. E-only is still no-worse than pristine there — the fast-
   path (§`test_no_duplicates_fast_path`) explicitly proves no
   `get_read_writes` calls happen when there are no duplicate
   groups.

## Section 6 — Recommendation

**Ship E-only. Do not ship batch removal as a headline change.**

Rationale:

- E-only alone delivers the entire measured speedup (16.3× / 62.9×
  / 126.3× at the three points).
- E-only's correctness argument is one paragraph: "the local
  reverse index is a materialization of the same
  `get_read_writes()` reads the current algorithm consults, so
  per-duplicate behavior is a subset of what the linear scan
  would have done."
- Batch removal on top of E-only saves within-noise time
  (~1.5% at Lk=8192, less at smaller points). It is a defensible
  cleanup but not a speedup. Attaching it to the same PR risks
  overselling the improvement or muddying the correctness proof
  (the `dead_ids` filter needs an identity-vs-equality argument
  that E-only doesn't need).
- If we later choose to ship batch removal as a separate PR (title:
  "dedup: defer per-duplicate operations.remove into Step 3
  rebuild"), the argument is preservable in a small commit with
  the same semantic-equivalence evidence.

**Do NOT ship both bundled unless a reviewer specifically requests
the O(N × D) tail be closed. Bundle only for a single upstream PR
where the reviewer wants "one clean commit." In that case the
commit message must clearly attribute the speedup to the reverse
index and the cleanup to batch removal.**

Concrete next step (for a follow-up phase):

- Open a torch-spyre PR titled roughly "dedup: replace per-dup
  consumer scan with local reverse index (~N×D → ~N
  `get_read_writes` calls)".
- Content: exactly the E-only diff plus the deterministic new
  tests (five pass-level tests: zero-consumer, one-duplicate-many-
  consumers, name_to_users fold, provenance, no-duplicate fast
  path; plus four unit tests for the reverse-index construction:
  op-with-two-deps-same-name, op-with-two-deps-different-names,
  op-with-no-duplicate-reads, multiple-ops-deterministic-order).
  `patches/dedup_constants_E_only.py` in this repo is the
  reference; strip the diagnostic instrumentation for the merged
  version (leave the fast-path gate, the reverse-index build, and
  the redirect-via-index call; drop the `_diag_record` wiring).
- Cite this repo's notes/dedup-phase2-plan.md and notes/
  dedup-phase3-conclusion.md as external evidence.
- Recommend Todd merge the phase-1/2/3 reports back into
  `torch-spyre/rfcs/` or a dedicated performance-note if the
  torch-spyre project has a preferred landing spot for
  optimization rationale.

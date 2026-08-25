# Consequence taxonomy — from 2.11 / 2.12 / 2.13 evidence

Union of categories that actually appeared in the three merged
upgrade PRs, plus the forward-compat skill's operational categories.
Not identical — one is "upgrade planning categories" and one is
"observed-failure categories" — but the union is the vocabulary a
readiness model needs.

## Categories that appear in ALL three upgrades

- `VERSION_BOOKKEEPING` — pyproject, workflow-comment version
  strings, docs strings, project-overview SKILL.md reference.
  Purely mechanical.
- `LOCKFILE_REGENERATION` — `uv.lock` + `requirements/*.txt`.
  Also mechanical, but requires network access to the wheel index.
- `REPO_HYGIENE_BUNDLING` — "used the excuse to update other deps."
  The team routinely bundles unrelated version bumps into the
  upgrade PR.

## Categories that appear in 2+ upgrades

- `PYTHON_API_BREAK` (2.11, 2.12)
  - 2.11: `add_lambda_guard` gained a required `user_stack` arg.
  - 2.12: `torch._C._dispatch_tls_is_dispatch_key_excluded` (still
    private-API dependence, not broken but continued technical debt).
- `INDUCTOR_API_BREAK` (2.12)
  - Multiple instances: `size_hint` → `optimization_hint` +
    `guarding_hint_or_throw`; Dynamo inlining of `.to` needing
    `allow_in_graph`.
- `PROFILER_CHANGE` (2.11 → 2.12 → 2.13)
  - 2.11: profiler infrastructure broke.
  - 2.12: new PrivateUse1 profiler API introduced (IBM-requested).
  - 2.13: inplace-ops + profiler test config polish.
- `CI_INFRASTRUCTURE_CHANGE` (2.11, 2.12, 2.13)
  - 2.11: multi-arch test images landed in parallel (PR #1997).
  - 2.12: pytorch commit tracking fix landed just before (PR #2274).
  - 2.13: upstream-tests-for-2.13 enablement requested.
- `DOWNSTREAM_DEPENDENCY_LAG` (2.11 → 2.12)
  - 2.11: profiler blocked pending 2.12.
  - 2.12: vLLM had not moved; resolved by spyre-inference#357
    architectural change that removed the coupling.
- `MERGE_HYGIENE` (2.11, 2.12)
  - 2.11: PR contained edits to since-removed codegen (bad merge).
  - 2.12: PR re-introduced a `convert_constant_with_graph_node`
    that had been pushed to LoopLevel IR (bad merge).
  - Long-running upgrade branches drift against fast-moving
    internals. The pattern is not a taxonomy category per se, but
    an operational hazard the review process catches.

## The severe categories that appeared in 2.12 AND 2.13

The original writeup collapsed three quite different cases under
one label. Split into a finer taxonomy so the readiness model can
target the right kind of check:

### `OBSERVED_SILENT_WRONG_OUTPUT`

No exception, no warning, wrong results actually produced at
runtime and observed by a test comparing values. This is the
category with the sharpest teeth.

- **2.12: Dynamo `.to` graph-break.** Silently fell back to eager
  and returned wrong D2D dtype casts (fp16↔bf16). Discovered by
  a dtype-cast test comparing against CPU reference. Fixed with
  `torch._dynamo.allow_in_graph(torch.Tensor.to)`. No API-signature
  change on either side.
- **2.13: LX loop-order accidental correctness.** Two reductions
  sharing an LX-resident buffer read a different core's slice
  than the producer wrote. No downstream check complained because
  the split factors still multiplied to the same core count.
  Discovered by a test failure — `ani300: "required for PT 2.13,
  otherwise CI is not green"`.

### `LATENT_CORRECTNESS_RISK`

Internal API contract changed in a way that WOULD have caused
wrong output, but was caught in review or during initial patching
before wrong output was observed.

- **2.12: `size_hint` split.** SDSC concretization could silently
  accept non-concrete values, producing wrong compilation. The
  bad replacement was caught by dgrove-oss reading the docstring
  during review; the initial patch used the wrong replacement.
  Never manifested as wrong output in a downstream test.

Counting this equivalent to `OBSERVED_SILENT_WRONG_OUTPUT` inflates
the severity count in a way that flatters the discovery process
that caught it early. Better to record it as its own category
so a readiness check can say "this is the kind of thing review
should look for" vs. "this is the kind of thing tests must catch."

### `REFERENCE_TOLERANCE_DRIFT`

Numeric reference itself changed in the new PyTorch version, not
a torch-spyre kernel change. Downstream test tolerances need
adjustment; the torch-spyre code itself did not silently miscompile.

- **2.12: three fp16 numerical edge cases drift by ~1 ULP.**
  PT 2.12 CPU-reference numerics changed. Fixed with three xfails
  (commit 3a2d482). Category is closer to
  `TEST_EXPECTATION_CHANGE` than to a torch-spyre silent
  miscompile — the Spyre kernel produced the same output; the
  reference moved.

### The categories together

**Only `OBSERVED_SILENT_WRONG_OUTPUT` is what "silent correctness"
should mean in the readiness model** — a case that actually
produced wrong runtime results and required someone to notice
numeric wrongness in a test run. That happened once in 2.12
(Dynamo `.to`) and once in 2.13 (LX loop-order). Two cases across
three upgrades, not three or four.

`LATENT_CORRECTNESS_RISK` is a review-catch category — good news
that the process works.

`REFERENCE_TOLERANCE_DRIFT` is a test-suite hygiene category —
the upstream reference moved.

All three are legitimately "an API-signature grep cannot catch
this," but they need different mitigations, so the taxonomy
distinguishes them.

## Categories that appear in exactly one upgrade

- `CXX_ABI_BREAK` (2.13)
  - `c10::impl::PyObjectSlot::load_pyobj_interpreter` removed.
  - Byte-identically what our historical-replay F6 case predicted.
- `INDUCTOR_SEMANTIC_BREAK` (2.12, 2.13)
  - 2.12: decompositions moved / broadened (K==1 mm/bmm; arange
    / tril / triu / isin / index_copy).
  - 2.13: `_try_reorder_loops_for_candidates` computed-then-discarded.
- `DECOMPOSITION_CHANGE` (2.12, subset of INDUCTOR_SEMANTIC_BREAK)
- `SYMBOLIC_SHAPE_CHANGE` (2.12)
- `RELEASE_ARTIFACT_NOT_READY` (2.12)
  - PT 2.12.1 patch release pending; upstream fix in flight but not
    in 2.12.0 at merge time.
- `REPO_HOUSEKEEPING` (2.11)
  - The upgrade skill was AUTHORED in the 2.11 upgrade PR.

## Categories from forward-compat taxonomy NOT observed in these three

- `REVERSE_ENTRYPOINT_HAZARD` — F3 was live on all three SHAs but
  was NOT part of any upgrade PR. It's a torch-spyre bug, not a
  PyTorch consequence.
- `PIPELINE_MISCONFIGURATION` — F5 was a build-script bug (double
  ccache), not upgrade-consequential.
- `PIPELINE_DEFECT` — F7, F9 were skill-side bugs.
- `NOT_TORCH_SPYRE` — none surfaced.
- `PRIVATEUSE1_API_CHANGE` — implicit in the profiler PrivateUse1
  change, but no dispatch-key change surfaced.
- `SCHEDULER_CHANGE` — 2.13's LX case was semantically scheduler-
  adjacent but was categorized as INDUCTOR_SEMANTIC_BREAK because
  the API didn't change.

## Composite taxonomy — the vocabulary a readiness model needs

Divided by discovery-mechanism, which is what determines when in
the release cycle each category is detectable:

### Static — visible before running anything

- `VERSION_BOOKKEEPING`
- `LOCKFILE_REGENERATION`
- `REPO_HYGIENE_BUNDLING`
- `CI_INFRASTRUCTURE_CHANGE` (parts of it — knowing that PR #1997
  needs to land is static)

### Grep-visible — visible from diffing PyTorch versions

- `PYTHON_API_BREAK` (removed / renamed symbols)
- `CXX_ABI_BREAK` (removed / renamed C++ symbols)
- Some `INDUCTOR_API_BREAK` (removed / renamed Python symbols)

### Compile-visible — visible from a rebuild attempt

- Rest of `CXX_ABI_BREAK` (signature-mismatched linkers)
- Rest of `INDUCTOR_API_BREAK` (missing lowering registrations)

### Run-visible — visible from an actual test run

- `DECOMPOSITION_CHANGE` (new decomps active or old ones missing)
- `SYMBOLIC_SHAPE_CHANGE` (guard behavior differs)
- `TEST_EXPECTATION_CHANGE`
- `INDUCTOR_SEMANTIC_BREAK` (assertion inside compile)
- `SCHEDULER_CHANGE`
- `PROFILER_CHANGE` (behavior differs)

### Silent-run-visible — visible only if a test COMPARES numerics

- `OBSERVED_SILENT_WRONG_OUTPUT` — only category with sharp teeth
  (2.12 Dynamo `.to`; 2.13 LX loop-order).
- `LATENT_CORRECTNESS_RISK` — caught in review (2.12 size_hint).
  Not silent-run-visible in the sense of firing during a test run
  because it was fixed before that would happen.
- `REFERENCE_TOLERANCE_DRIFT` — tolerance/xfail adjustment
  category (2.12 fp16 1-ULP). Test failure fires; the fix is
  tolerance/xfail rather than a torch-spyre code change.

### Downstream-visible — visible only after downstream projects try

- `DOWNSTREAM_DEPENDENCY_LAG`
- `RELEASE_ARTIFACT_NOT_READY`
- `PERFORMANCE_CHANGE` (would show up in `frontend-compiler-impact`)

## What this taxonomy suggests for the readiness model

- The upgrade-pytorch-version skill covers the **static** and
  **grep-visible** parts. That's what it was designed for. Its
  "Potential Breakage" section names the rest as manual watch
  items.
- The forward-compat skill covers the **compile-visible** and
  **run-visible** parts empirically. F3 / F6 / F8 all sit in this
  band.
- `OBSERVED_SILENT_WRONG_OUTPUT` is the category the current
  tooling is WEAKEST at. Two instances across three upgrades
  (2.12 Dynamo `.to`; 2.13 LX loop-order). A readiness model
  would specifically want a general
  `torch.compile(...) → CPU-oracle` differential test — that's
  the mitigation for the category as a whole.
- `LATENT_CORRECTNESS_RISK` is best mitigated by review discipline
  on any patch that touches a "returns hint" / "assumes concrete"
  API contract. Named review pattern rather than a check script.
- `REFERENCE_TOLERANCE_DRIFT` is mitigated by targeted numeric-diff
  tests at known-drift edge cases (fp16 corner values) that
  distinguish "our kernel drifted" from "the reference drifted"
  before applying an xfail.
- Downstream (vLLM, spyre-inference, hf-adapters, kineto) status
  is READY / NOT READY as a first-class dimension. The 2.12 case
  showed that a downstream architectural change can UNBLOCK the
  upgrade — not just gate it.

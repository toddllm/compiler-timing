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

## The severe category that appeared in 2.12 AND 2.13

`SILENT_CORRECTNESS_CHANGE` — no exception, no warning, just wrong
results.

- 2.12: three fp16 numerical edge cases drift by ~1 ULP (CPU
  reference numerics changed, not Spyre kernel).
- 2.12: Dynamo `.to` graph-break silently fell back to eager and
  returned wrong D2D dtype casts.
- 2.13: The LX loop-order accidental correctness case. Two
  reductions sharing an LX-resident buffer read a different
  core's slice than the producer wrote. No downstream check
  complained because the split factors still multiplied to the
  same core count.

**These are the failure modes an API-signature grep cannot catch.**
Both 2.12's `.to` graph-break and 2.13's LX loop-order case
required someone to notice numeric wrongness in a test run.

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

- `SILENT_CORRECTNESS_CHANGE`

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
- `SILENT_CORRECTNESS_CHANGE` is the category the current tooling
  is WEAKEST at. Both 2.12 and 2.13 hit at least one silent case.
  A readiness model would specifically want:
  - a targeted numeric-diff test against CPU reference at the fp16
    edge cases that historically drift;
  - a targeted "LX-resident buffer + two consumers with different
    dim orders" scenario;
  - a general `torch.compile(...) → CPU-oracle` differential test.
- Downstream (vLLM, spyre-inference, hf-adapters, kineto) status
  is READY / NOT READY as a first-class dimension. The 2.12 case
  showed that a downstream architectural change can UNBLOCK the
  upgrade — not just gate it.

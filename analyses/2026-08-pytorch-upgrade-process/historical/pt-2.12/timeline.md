# PT 2.12 upgrade — timeline

- **PR:** [`torch-spyre/torch-spyre#2218`](https://github.com/torch-spyre/torch-spyre/pull/2218)  
  "Upgrade to PT 2.12", author `ani300`.
- **Merged:** 2026-07-28T01:01:38Z.
- **Head branch:** `2.12-upgrade`.
- **Diff shape:** 39 files, +906 / −617.
- **Commits (linearized):**
  - "Upgrade to pytorch 2.12"
  - "Fix strict checks for dynamic shapes"
  - "Fix size_hint tests and comments, address PR comments"
  - three `Merge branch 'main' …` merges

## Files touched

Notably outside the mechanical set:

```
torch_spyre/_inductor/__init__.py
torch_spyre/_inductor/codegen/superdsc.py
torch_spyre/_inductor/customops.py
torch_spyre/_inductor/decompositions.py
torch_spyre/_inductor/insert_restickify.py
torch_spyre/_inductor/lowering.py
torch_spyre/_inductor/pass_utils.py
torch_spyre/_inductor/passes.py
torch_spyre/_inductor/patches.py
torch_spyre/_inductor/spyre_kernel.py
torch_spyre/_inductor/temp_passes.py
torch_spyre/_inductor/views.py
torch_spyre/_inductor/work_division.py
torch_spyre/_monkey_patch.py
torch_spyre/ops/eager.py
tests/dynamic_shapes/mark_dynamic.py
tests/inductor/test_coarse_tiling.py
tests/inductor/test_codegen.py
tests/inductor/test_dedup_constants.py
tests/inductor/test_inductor_dtype_scalars.py
tests/inductor/test_inductor_fx_passes.py
tests/inductor/test_inductor_ops.py
tests/inductor/test_scratchpad_use.py
tests/inductor/utils_inductor.py
tests/models/model_cases_loader.py
tests/models/test_model_ops.py
tests/oot_framework/oot_upstream_patcher.py
tests/scripts/oot_checker/parser.py
tests/tensor/test_tensor_layout.py
.github/scripts/ingest_xml.py
```

Fifteen files under `torch_spyre/_inductor/` — the compiler surface was
the primary point of contact with 2.12.

## What triggered

Team practice + explicit "IBM-requested features are now available in
2.12" (from @ani300's own comment: "these are all changes we (as IBM)
have requested from PyTorch").

Also unblocks the deferred PT 2.11 profiler breakage — the new
PrivateUse1 profiler API in 2.12 was designed for cases like this.

## Consequences that surfaced in the PR

### VERSION_BOOKKEEPING + LOCKFILE_REGENERATION (mechanical)

Same shape as 2.11 but includes `requirements/lint.txt` this time
(added between 2.11 and 2.12).

### INDUCTOR_API_BREAK — `size_hint` split

**Delta.** PT 2.12 removed `V.graph.sizevars.size_hint()` and split its
callers between `optimization_hint()` (returns a hint that may be
non-concrete) and `guarding_hint_or_throw()` (returns a concrete int,
throws if the value isn't statically known).

**Impact.** `torch_spyre/_inductor/codegen/superdsc.py:602`'s
`_concretize_for_sdsc` was called from what the docstring calls "the
final concretization point in the pipeline" — output MUST be a fully
concrete integer for the downstream DeepTools/SDSC compiler.

**Fix.** @ani300 initially used `optimization_hint`; @dgrove-oss caught
this in review pointing out that per PT 2.12's own docs
`optimization_hint` may not be concrete. Author switched to
`guarding_hint_or_throw` in the places where concretization is
required. This is `INDUCTOR_API_BREAK` compounded by
`SILENT_CORRECTNESS_CHANGE` risk — the code would compile and run,
but produce wrong results.

Category: `INDUCTOR_API_BREAK` with `SILENT_CORRECTNESS_CHANGE`
implications.

### INDUCTOR_SEMANTIC_BREAK — decompositions moved

**Delta.** PT 2.12 broadened `torch._inductor.decomposition.mm/bmm` to
decompose the K==1 (unit-contraction) case into a broadcast
`self * other`. Also added core-aten decompositions for arange, tril,
triu, isin, index_copy.out.

**Impact.** torch-spyre's fallbacks for those ops now conflict with
in-tree decompositions — Inductor's graph lowering auto-invokes
`make_fallback(op)` WITHOUT `override_decomp`, which asserts "both a
fallback and a decomp for same op."

**Fix.** New `register_fallback_over_decomp(fallback_ops)` helper in
`lowering.py` — pre-registers each such op's fallback with
`override_decomp=True`. And ban the new K==1 mm/bmm decomposition on
Spyre by adding them to `spyre_decompositions_to_exclude` in
`decompositions.py`.

Category: `INDUCTOR_SEMANTIC_BREAK` +
`DECOMPOSITION_CHANGE`. Discovered via failing compile assertions —
NOT via a signature grep.

**Author-driven upstream fix.** @bohnstingl posted:  
"my upstream correction to the decomposition handling landed in
PyTorch, see https://github.com/pytorch/pytorch/pull/185909.
Unfortunately, it will take another PyTorch release to become
effective."  
The team is actively landing fixes upstream to make future bumps
easier — the same person who ran the 2.11 upgrade is now shaping
PyTorch's own behavior.

### INDUCTOR_API_BREAK — Dynamo `.to` graph break

**Delta.** In PT 2.12 Dynamo now graph-breaks when inlining a Python
wrapper (`spyre_to`) that calls C++ `orig_to` — forcing the whole
region eager. `is_compiling()` guards do NOT help.

**Impact.** D2D dtype casts (e.g. fp16↔bf16) went eager → wrong results.

**Fix.** Mark `torch.Tensor.to` as `allow_in_graph`. Global side effect,
acceptable because torch-spyre already owns `.to` in-process (monkey-
patched). Author defended this in review against a "global side effect"
concern.

Category: `INDUCTOR_API_BREAK` +
`SILENT_CORRECTNESS_CHANGE`. Discovered when a compile silently returned
wrong dtype-converted output.

### PROFILER_CHANGE — new PrivateUse1 profiler API

**Delta.** PT 2.12 introduced a new profiler API for PrivateUse1
backends. This was IBM-requested per @ani300.

**Impact.** The 2.11 profiler breakage is finally resolved.

**Fix.** Coordinated with PR #1856 ("Move aiupti changes from kineto
plugin") — SilverSoldier confirmed on 2218: "Just tested your PR + our
changes in #1856 for enabling profiler with 2.12 and it works smoothly."

Category: `PROFILER_CHANGE` (an INTENDED feature, not a break).

### SYMBOLIC_SHAPE_CHANGE — new hints API

@ani300: "symbolic shapes hints have a new API as well". Detail scope
covered by the `optimization_hint` / `guarding_hint_or_throw` split
above, and by "Fix strict checks for dynamic shapes" commit.

### DOWNSTREAM_DEPENDENCY_LAG — vLLM

@tdoublep: "Just FYI upstream vLLM has NOT yet moved to PT 2.12 (draft
PR: vllm-project/vllm#42848). Will these changes ensure backwards
compatibility with PT 2.11? I am worried that merging this PR could
prevent spyre-inference from pulling in any latest changes from
torch-spyre side."

@ani300: "they in fact break backwards compatibility... I can refactor
to use both 2.11 and 2.12 APIs everywhere it needs to, but there are a
lot of breaking changes for 2.12 that affect us: decompositions,
profiling, symbolic shapes hints all have completely different paths."

Resolution: @tdoublep landed **spyre-inference#357** ("swap to
vllm-empty") to remove the dependency on precompiled CPU wheels of
upstream vLLM. After that, "Nothing blocking this anymore from our
side." This is an example of a **downstream project unblocking the
upgrade** rather than the upgrade waiting for the downstream project.

Category: `DOWNSTREAM_DEPENDENCY_LAG` + resolved via a separate
downstream architecture change.

### TEST_EXPECTATION_CHANGE — three fp16 xfails

**Delta.** Three pre-existing PT-2.12 fp16 numerical edge cases: a 3D
fp16 (8, 16, 256) `exp → sin (CPU fallback) → exp` case drifts a single
ULP; documented in commit `3a2d482` "Xfail three pre-existing PT 2.12
numerical edge cases".

**Fix.** xfail. Author defended in review: "It's a PT 2.12 CPU-reference
numerics change, not a Spyre kernel regression."

Category: `TEST_EXPECTATION_CHANGE` +
`SILENT_CORRECTNESS_CHANGE` at the reference side.

### RELEASE_ARTIFACT_NOT_READY — 2.12.1 patch release

@bohnstingl: "PyTorch is planning a patch release, PyTorch 2.12.1, with
the GA on June 17th. I try to get my decomposition PR cherry-picked."

This means the merged 2.12 upgrade was against a 2.12.x that DID NOT
yet include @bohnstingl's decomposition fix — so torch-spyre carried
the workaround (`spyre_decompositions_to_exclude`) even though the
upstream fix was in progress.

Category: `RELEASE_ARTIFACT_NOT_READY`.

### CI_INFRASTRUCTURE_CHANGE — pytorch commit tracking

Related PR #2274 "ci-cd: fix, checkout the correct pytorch commit if
it has been changed in pyproject.toml" landed 2026-05-26, between 2.11
and 2.12. The upgrade PR needed this fix in place so its CI would pick
up the right pytorch source commit after the pyproject bump.

Category: `CI_INFRASTRUCTURE_CHANGE`.

### PYTHON_API_BREAK — private symbol `_dispatch_tls_is_dispatch_key_excluded`

Author noted `torch._C._dispatch_tls_is_dispatch_key_excluded("Python")`
is a private symbol — used to detect being inside `no_dispatch()` from
within an op kernel because there's no public predicate. Ack'd as
technical debt.

Category: `PYTHON_API_BREAK` (private API usage; not broken here but a
recurring maintenance cost).

## Bundled work

- **Dependency-pass excuse.** From PR body: "I also used the excuse to
  do a dependency pass and update our other dependencies. If CI catches
  something we can decide if we want to avoid some of them." — unrelated
  version bumps bundled into the same PR.
- **`.pre-commit-config.yaml`** updated.
- **`.github/scripts/ingest_xml.py`** touched.

## Criteria used to say "ready to merge"

- Author: "at this point it's ready to merge!" (paraphrased from #3374
  final exchange; roughly the same pattern applied here).
- Explicit CI-green requirement was NOT waived — the LX loop-order fix
  (see PT 2.13 timeline) came LATER and was described by @ani300 as
  "required, otherwise CI is not green."
- Downstream vLLM/spyre-inference lag resolved by @tdoublep's
  independent #357 landing first.
- Multi-arch testing was NOT re-raised — presumably standing since 2.11.
- Two upstream-tests-red waivers from 2.11 were not called out again;
  ambient tolerance persists.

## Post-merge follow-ups

- @bohnstingl's `torch~=2.12` decomposition PR still needs cherry-pick
  to a 2.12.1 patch — pending 2026-06-17 GA.
- Test-tier updates cascaded into other tests/inductor/test_*.py files
  which are still stabilizing.

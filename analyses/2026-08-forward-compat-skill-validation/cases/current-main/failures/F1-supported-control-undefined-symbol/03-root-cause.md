# F1 — Root cause: pipeline shared source-tree between two builds

**Recorded:** 2026-08-21 (follow-up on original 2026-08-21 case)
**Status update:** the original diagnosis in `02-diagnosis-hypothesis.md`
prioritised the "pyproject pin is stale" hypothesis (H1). Direct
evidence collected from the persistent PVC after the case ran
**falsifies H1** and confirms Todd's alternative "mixed
headers/libraries" hypothesis — with a specific twist: the mixing
happened between the two venvs of the pipeline itself, not between
system and venv torch.

## Evidence

Symbol-provenance probe of the actual `.so` files left on disk (raw
output preserved at `03a-symbol-provenance.txt`):

`torch-spyre/torch_spyre/_C.so` undefined references:
```
U _ZNK3c1010TensorImpl15incref_pyobjectEv        # c10::TensorImpl::incref_pyobject
U _ZNK3c1010TensorImpl19try_incref_pyobjectEv    # c10::TensorImpl::try_incref_pyobject
U _ZNK3c1011StorageImpl15incref_pyobjectEv       # c10::StorageImpl::incref_pyobject
U _ZNK3c1011StorageImpl19try_incref_pyobjectEv   # c10::StorageImpl::try_incref_pyobject
U _ZNK4c10d7Backend15incref_pyobjectEv           # c10d::Backend::incref_pyobject
U _ZNK4c10d7Backend19try_incref_pyobjectEv       # c10d::Backend::try_incref_pyobject
```

`libtorch_cpu.so` exports:
- `.venv-supported` (torch 2.13.0+cpu): four `TensorImpl`/`StorageImpl`
  incref_pyobject entries only. **No `c10d::Backend::incref_pyobject`.**
- `.venv-latest` (torch 2.15.0.dev20260821+cpu nightly): the same four
  plus **`c10d::Backend::incref_pyobject`** and
  **`c10d::Backend::try_incref_pyobject`** as `T` (defined text).
- System (torch 2.11.0+cpu at `/usr/local/lib64/...`): four
  `TensorImpl`/`StorageImpl` entries only. No Backend entries.

Header check:
- `.venv-supported/.../torch/include/torch/csrc/distributed/c10d/Backend.hpp`:
  `grep -c incref_pyobject` = **0**.
- `.venv-latest/.../Backend.hpp`: `grep -c incref_pyobject` = **2**
  (declaration + comment).

Build timestamps:
```
2026-08-21 17:09:26  build_supported.log     ← end of SUPPORTED build
2026-08-21 17:16:06  build_latest.log        ← end of LATEST build
2026-08-21 17:16:05  torch_spyre/_C.so       ← _C.so on disk right now
```

## Mechanism

1. The pipeline's `canonical_build` helper runs the canonical torch-spyre
   install `pip install -e . --no-deps --no-build-isolation` **twice
   against the same `torch-spyre/` source tree** — once per venv.
2. `pip install -e .` writes an editable-install `.pth` in each venv's
   `site-packages` that points at `torch-spyre/torch_spyre/`.
3. Each build writes intermediate `.o` files under
   `torch-spyre/build/torch_spyre._C/` and the final `_C.so` at
   `torch-spyre/torch_spyre/_C.so`. **The second build overwrites the
   first build's `_C.so`.**
4. When the pipeline ran, the second (nightly) build finished at
   17:16:05, overwriting the 17:09-era `_C.so` that had been produced
   against torch 2.13.0 headers.
5. Stage 0 of `SUPPORTED_CONTROL` then activated `.venv-supported`
   (whose `.pth` still points at `torch-spyre/torch_spyre/`) and
   `import torch_spyre` dlopens the on-disk `_C.so`, which is the
   **nightly-built** one, which references `c10d::Backend::incref_pyobject`,
   which is undefined in `.venv-supported`'s libtorch_cpu.

The nightly build's `_C.so` was correct against nightly torch (the
symbol is a defined `T`). The supported build's `_C.so` never made it
to Stage 0 because it was overwritten before Stage 0 ran.

## Root cause classification

**PIPELINE_DEFECT (not a torch-spyre or torch compatibility break).**
The `pip install -e .` editable-mode + shared-source-tree combination
does not compose with two venvs targeting different torch ABIs.

## Effect on the skill's earlier findings

- The original hypothesis-1 in `02-diagnosis-hypothesis.md` (declared
  pyproject pin is stale) is falsified for this data. It may still
  be independently true (a full test would require SUPPORTED_CONTROL
  with a properly-isolated build tree) but is not what caused the
  observed failure.
- The classification of F1 as `C_EXTENSION_ABI_BREAK` was correct at
  the symptom level (`_C.so` had undefined c10d symbols at import) but
  the taxonomy did not have a term for "build-tree contamination
  between two pipeline configurations". `PIPELINE_DEFECT` needs to be
  added to the taxonomy for v0.2 with the diagnostic recipe
  "compare build_*.log timestamps against `_C.so` timestamp".
- The specific mixing hypothesis Todd flagged (§1 of the review) was
  correct: this is a mixed-headers/libraries scenario. The specific
  form was between the two pipeline venvs, not between system and
  venv torch.

## Fix — pipeline

`canonical_build` must give each venv its own source tree:

```bash
canonical_build() {
  local venv="$1" logfile="$2" tree="$3"    # NEW: caller passes tree
  # ... `( cd "$tree" && pip install -e . --no-deps --no-build-isolation ... )` ...
}

# Caller:
git clone ... torch-spyre-supported ; ( cd torch-spyre-supported && git checkout SHA )
git clone ... torch-spyre-latest    ; ( cd torch-spyre-latest    && git checkout SHA )
canonical_build .venv-supported build_supported.log torch-spyre-supported
canonical_build .venv-latest    build_latest.log    torch-spyre-latest
```

Alternative: `pip install .` (non-editable wheel install) — each venv
gets its own copy under site-packages. But that loses the ability to
edit the tree for patch iteration, which is core to the skill's
patching loop.

**Preferred fix**: separate source trees per venv, with a shared
top-level clone whose `.git/objects` is used as an alternate to keep
disk usage down.

## Fix — reference material

Add to `references/environment-policy.md` a new "Build isolation"
subsection listing:
- Every venv must have its own torch-spyre working tree.
- If disk pressure requires sharing objects, use `git clone --reference
  <shared> --dissociate <target>` so alternates don't leak state.
- After each build, capture `stat -c "%y %n" $tree/torch_spyre/_C.so`
  in the venv's build log — future runs can detect timestamp
  contamination before Stage 0.

Add to `references/failure-taxonomy.md` a new `PIPELINE_DEFECT`
category with the diagnostic recipe above.

## Followup (v0.2 rerun)

Once the pipeline is fixed with separated trees, rerun this case.
If SUPPORTED_CONTROL Stage 0 then passes cleanly, F1 is resolved and
Todd's DECLARED_PUBLIC_CONTROL vs CANONICAL_INTERNAL_CONTROL split is
not needed for this specific finding (the declared public control
works). If it still fails with the same undefined `Backend::incref_pyobject`,
the DECLARED_PUBLIC_CONTROL vs CANONICAL_INTERNAL_CONTROL question
becomes primary and requires an internal-torch-build baseline.

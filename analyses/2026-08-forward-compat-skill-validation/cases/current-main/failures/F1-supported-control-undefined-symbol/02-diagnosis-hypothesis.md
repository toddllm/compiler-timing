# F1 — Diagnosis hypothesis (BEFORE any patch)

**Status:** hypothesis, not yet verified against ground-truth. No patch
has been applied.

The three plausible root causes, in decreasing likelihood:

## H1 (most likely): torch-spyre's `pyproject.toml` pin `torch~=2.13.0` is not self-sufficient

torch-spyre@main is built and CI-tested against a torch build shipped
inside internal `torch-aiu-runtime-dev` image layers. That internal
torch carries an out-of-tree patch adding
`c10d::Backend::incref_pyobject()`. When someone installs
torch-spyre@main via the pyproject-declared path — `pip install torch
--index-url https://download.pytorch.org/whl/cpu` first, then `pip
install -e .` — the resulting torch does not carry the patch, and the
resulting `_C.so` cannot resolve `incref_pyobject`.

**Predictions this hypothesis makes (falsifiable):**

- Inside a `torch-aiu-runtime-dev:latest` image, the system torch at
  `/usr/local/lib64/python3.12/site-packages/torch` (version
  2.11.0+cpu per our environment.json) *should* expose
  `_ZNK4c10d7Backend15incref_pyobjectEv` when nm-inspected. If it does,
  H1 is confirmed and H2/H3 are unlikely.
- torch-spyre CI logs *should* show the CI job using this or a related
  image, and the CI job *should* NOT be pip-installing torch from the
  public CPU wheel index.
- The fix under H1 is to declare in torch-spyre docs (and, if
  possible, in `pyproject.toml` via a URL dependency or requirements
  extra) which torch install the source is actually compatible with.

## H2: The build produced an unconditional reference to a torch header
that only some torch builds satisfy

torch-spyre's C++ extension may include a header (perhaps
`torch/csrc/distributed/c10d/PyProcessGroup.hpp` or similar) that
references `incref_pyobject` unconditionally. If that header is
present in some torch builds but not others, and the compile succeeded
because a *system* torch (2.11.0) supplied the header while the *venv*
torch (2.13.0) supplied the runtime, the link-time resolution went
through the venv torch which does not have the symbol.

**Predictions:**

- Grep of torch-spyre C++ sources should reveal a header include or a
  direct reference to `incref_pyobject`.
- The fix under H2 is to guard the reference on a torch version macro
  or feature-test.

## H3: `incref_pyobject` is a torch release-candidate patch that will
land in a future release

The name `incref_pyobject` matches the pattern of the `torch.compile`
python-object reference-count management refactor that is in flight on
pytorch/main. If the symbol was in a specific release-candidate
lineage that got squashed before hitting main, torch-spyre may have
been developed against that lineage.

**Predictions:**

- `git log --all --oneline -S "incref_pyobject" torch/csrc/distributed/c10d/` on a
  pytorch checkout should surface at least one commit — likely on a
  feature branch or reverted.
- Under H3 the fix is either to wait for the symbol to land in an
  official release, or to move torch-spyre off the symbol.

## Cross-hypothesis tests

The single strongest disambiguation is:

```bash
oc exec tdeshane-forward-compat-2026-08-21 -n a5-deepview -- bash -lc '
  # System torch inside the image
  find /usr/local/lib64/python3.12/site-packages/torch -name "*.so" -exec nm -D {} 2>/dev/null \; | \
    grep incref_pyobject
'
```

- If it returns hits → H1 confirmed.
- If it returns zero hits → H1 falsified; investigate H2 next by
  grepping torch-spyre source for `incref_pyobject`.

That check was NOT run in the initial pipeline because the pod's
autoload path immediately triggers the flex-ABI PVC-contamination
issue. A future run should invoke `nm` from a shell that does not
`import torch` first, or bypass Python entirely.

## Next action (per patch-policy.md)

**No patch applied.** The skill's patch-policy requires:

1. Root cause established, or
2. Root cause hypothesis with a falsification path is written down
   AND SUPPORTED_CONTROL is stable *without* the hypothesised fix
   preventing verification.

Neither condition holds. The falsification test (nm check on system
torch) is the necessary next step, tracked as Task #29 for a follow-up
run.

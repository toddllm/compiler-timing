# F3 — Import-matrix probe upgrades F3 from harness bug to real torch-spyre finding

**Recorded:** 2026-08-21 follow-up
**Status update:** the original observation in `01-observation.md`
concluded that F3 was a `NOT_TORCH_SPYRE` harness issue (Stage 1's
cross-process re-import). Direct probing on the pod with a minimal
5-case matrix falsifies that conclusion — the double-registration is
reachable *without* any ladder harness, from a fresh `python -c` shell
importing torch_spyre with autoload ON.

## Matrix (on `.venv-latest`, torch 2.15.0.dev nightly)

Every case is a fresh `python -c` process on the pod. Env variables
are constant: `PYTHONNOUSERSITE=1`, `TORCH_DEVICE_BACKEND_AUTOLOAD` as
labelled.

| # | Import | Autoload | Result |
|---|---|---|---|
| A | `import torch` | ON | PASS |
| B | `import torch; import torch._inductor` | ON | PASS |
| C | `import torch_spyre` (no `torch` first) | ON | **FAIL** — `AttributeError: partially initialized module 'torch_spyre' has no attribute '_autoload'` (circular import inside torch's `_import_device_backends`) |
| D | `import torch_spyre` (no `torch` first) | OFF | PASS |
| E | `import torch; import torch_spyre` | ON | PASS |
| F | `import torch_spyre; import torch_spyre._inductor.lowering` (no `torch` first) | ON | **FAIL** — same circular import through autoload path |
| G | `import torch_spyre; import torch_spyre._inductor.lowering` (no `torch` first) | OFF | **FAIL** — `torch_spyre.ops.fallbacks` import fails partway through |
| H | `import torch; import torch._inductor; import torch_spyre; import torch_spyre._inductor.lowering` | ON | **PASS** |

## Interpretation

- **A, B**: torch state is fine on nightly.
- **C** (torch_spyre alone with autoload): entering torch_spyre's
  `__init__.py` triggers torch's `_import_device_backends()` (via the
  entry-point registration on install), which in turn calls
  `torch_spyre._autoload` — but torch_spyre's `__init__.py` hasn't
  finished executing yet, so `_autoload` doesn't exist on the module
  object. Circular import.
- **D**: with autoload disabled, torch_spyre's `__init__.py` runs to
  completion. PASS.
- **E**: with `import torch` first, torch's initialization completes
  before torch_spyre gets involved, and torch_spyre's own import can
  complete without re-triggering `_import_device_backends`.
- **F**: same as C mechanistically — the moment torch_spyre is
  imported first with autoload on, the entry point fires prematurely.
- **G**: with autoload OFF, torch_spyre imports, but importing
  `torch_spyre._inductor.lowering` chases a chain that needs
  `torch_spyre.ops.fallbacks`, which in turn needs torch state that
  hasn't been fully initialized because nothing has imported torch
  yet. Ordinary Python import-graph issue.
- **H**: the canonical order works.

## Root cause classification

**REAL_TORCH_SPYRE_ISSUE at Stage-0 layer + REVERSE_ENTRYPOINT_HAZARD.**
torch_spyre's entry point registers `torch_spyre._autoload` before
torch_spyre's own `__init__.py` has finished executing. If any caller
imports torch_spyre without first importing torch, the entry point
fires re-entrantly and the callback fails on a partially-initialized
module. This is not specific to nightly — it's structural.

## Why the original Stage-1 error looked different

The original Stage 1 crash reported `RuntimeError: Only a single
TORCH_LIBRARY can be used to register the namespace triton`. That IS a
downstream symptom of the same re-entrancy issue: when the failed
`_autoload` path is retried via `__import__` later in the same
process, torch's `TORCH_LIBRARY(triton)` from its own `__init__.py`
runs twice because the module object was partially initialized then
retried. My original hypothesis (that this was a cross-process
harness artifact) was wrong — the mechanism is intra-process and
happens even without a ladder.

## Implications

- The v0.2 harness change I proposed (merge Stage 0 and Stage 1) would
  have **masked** F3 rather than fixed it. Do not merge stages
  without also fixing the underlying `_autoload` re-entrancy.
- **The correct fix is torch-spyre-side**: either (a) make
  torch_spyre's entry point resilient to being called before
  `__init__.py` finishes (e.g. cache a promise; on re-entry, no-op),
  or (b) restructure `__init__.py` so `_autoload` is defined at the
  very top of the module before any other statement.
- **Failure taxonomy addition**: `REVERSE_ENTRYPOINT_HAZARD` — an
  entry-point callback fires before the module registering the entry
  point has finished initializing. Diagnostic recipe: run `python -c
  "import <backend>"` with the vendor's autoload ON without first
  importing torch. If it fails with `AttributeError: partially
  initialized module`, this is the category.

## Cross-check on `.venv-supported`

Not run yet because `.venv-supported` currently has the contaminated
`_C.so` (see F1's `03-root-cause.md`). Once F1's pipeline defect is
fixed with separated source trees, rerun this matrix on both venvs.
If C/F fail on both, F3 is a real dual-compat bug regardless of torch
version.

## Followup

Track as a proposed torch-spyre commit for a v0.2 case: minimal patch
to `torch_spyre/__init__.py` restructuring `_autoload` to be
importable at any point during module initialization. The skill's
patch-policy would first record the hypothesis, then apply the patch,
then re-verify the import matrix.

Do NOT apply the patch yet — Todd's §3 rule ("don't fix until you
understand what triggers the second registration") is satisfied at
the *understanding* level here, but the actual code fix still needs
`torch_spyre/__init__.py` inspection and a hypothesis-first record
that the skill has not yet produced. That work is Task #30.

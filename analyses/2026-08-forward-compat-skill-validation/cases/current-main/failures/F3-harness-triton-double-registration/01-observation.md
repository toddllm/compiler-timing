# F3 — Stage 1 harness `TORCH_LIBRARY(triton)` double registration

**Failure taxonomy:** `NOT_TORCH_SPYRE` — this is a defect in the
skill's own ladder harness, not a compatibility break in torch-spyre.
**Recorded:** 2026-08-21
**Case:** `current-main`

## What we saw

Under both `SUPPORTED_CONTROL` and `FORWARD_BEFORE_FIX`, Stage 1
(module import walk) crashes with:

```
RuntimeError: Only a single TORCH_LIBRARY can be used to register the namespace triton;
please put all of your definitions in a single TORCH_LIBRARY block.
If you were trying to specify implementations, consider using TORCH_LIBRARY_IMPL
(which can be duplicated).
Previous registration of TORCH_LIBRARY was registered at
  .../torch/__init__.py:3350;  (nightly)
  .../torch/__init__.py:2899;  (supported)
latest registration was registered at
  <same path>:3350
```

Sources:
- `../../data/forward_stage1.log`
- `../../data/supported_stage1.log`

Every module in the walk fails with the same registration error,
producing rc=139 for Stage 1 in both cases.

## Why this is not a compatibility break

The registration source-line is the same on both "previous" and
"latest" sides — `torch/__init__.py:3350` (nightly) or `:2899`
(supported). That means torch's own initialization is being run twice
in the same process. The most likely trigger is that Stage 0's
`import torch_spyre` autoloads and calls into torch's C-extension,
which registers `TORCH_LIBRARY(triton)`. When Stage 1 launches a fresh
`python3 -c` process, it should have a clean torch state — but Stage
0's `TORCH_DEVICE_BACKEND_AUTOLOAD=1` mode has caused the interpreter
we invoked to retain state via `.pyc` bytecode cache or similar.

Actually, on re-reading, each stage launches a `python3 -` heredoc as
a *separate* process. So the double-registration must be happening
*within* that single process. Two candidates:

1. torch's `__init__.py` runs `torch.library.Library("triton",
   "DEF")` unconditionally at import time. torch-spyre's autoload
   during `import torch_spyre` may somehow cause torch to be
   re-imported (perhaps via `torch_spyre._inductor.__init__.py:53` doing
   `from torch._inductor.compile_fx import compile_fx`, which forces
   an internal torch submodule re-init).
2. The stage's `__import__("torch_spyre._inductor.dedup_constants")`
   loop mixes torch-spyre modules that *also* register a triton
   namespace — but the error message specifically points at torch's
   own `__init__.py` file, so this seems unlikely.

## Fix approach (v0.2)

Two options:

**Option A: fewer stage boundaries.** Merge Stage 0 and Stage 1 into a
single `python3 -c` script that does the autoload probe AND the
module-list walk in one process. That eliminates the cross-process
re-import concern entirely.

**Option B: use `importlib.util.spec_from_file_location` for the
walk.** Import each torch-spyre submodule via `importlib` with
`sys.modules` snapshot/restore around each import. Preserves the
separate-process pattern for genuine isolation while avoiding the
torch-side double registration.

Option A is simpler and more robust for v0.2.

## Why this matters for F1

F3 masks part of F1's signal — Stage 1 fails in `SUPPORTED_CONTROL`
for a reason unrelated to the F1 undefined symbol. A reader
skimming the ladder JSON might think F1 and F3 are the same defect;
they are not. F1 is the SUPPORTED_CONTROL Stage 0 failure. F3 is a
harness-only crash that affects every Stage 1 regardless of
compatibility.

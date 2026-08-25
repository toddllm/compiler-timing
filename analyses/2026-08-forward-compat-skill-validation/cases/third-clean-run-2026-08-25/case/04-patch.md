# 04 — Patch

## Files touched

`torch_spyre/__init__.py` (one file).

## Concrete diff

`04-patch.diff` sits next to this file. Apply with

    git apply --index 04-patch.diff

from the root of the torch-spyre checkout. Two hunks: (1) insert the
early defer-and-invoke `def _autoload()` above `import torch`, and
(2) append the tail-invoke below the last module-scope statement.

## Applies cleanly against

torch-spyre `69bd7de188bae72843f234870cbcde802c4f24fa` (the SHA
resolved by `resolve_versions.sh` on this run).

Same defer-and-invoke pattern also verified DUAL_COMPAT on prior
SHAs in `../live-current-main-F3/` (8aba5bc) and
`../second-pod-repro-2026-08-24/` (69bd7de1 with slightly different
byte layout).

## Post-apply, the fix flow is

1. `import torch_spyre` starts.
2. Lines 1-19 run (unchanged).
3. New early `def _autoload()` binds at module scope (before line 20).
4. `import torch` at what is now line ~50 triggers
   `_import_device_backends()` → resolves the entrypoint →
   `torch_spyre._autoload()` is defined and returns harmlessly
   because `_autoload_impl` has not been bound yet
   (`_autoload._requested = True`).
5. Rest of `torch_spyre/__init__.py` runs. `_autoload_impl` is
   defined at its historical position.
6. Tail line at end of file: `if _autoload._requested: _autoload()`
   fires the real autoload now that `_autoload_impl` is bound.

Net behavior: exactly one `_autoload_impl()` execution per process,
identical to the intended semantics on any prior torch version, no
reentrant AttributeError.

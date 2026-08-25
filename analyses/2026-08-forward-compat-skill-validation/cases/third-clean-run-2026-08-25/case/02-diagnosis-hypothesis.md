# 02 — Diagnosis / Hypothesis

## Root cause

torch-spyre@69bd7de1 declares a `torch_spyre:_autoload` entrypoint via
its `pyproject.toml` `[project.entry-points."torch.backends"]` block,
so any `import torch` runs `torch._import_device_backends()`, which
resolves and invokes `torch_spyre._autoload()`.

The trouble is that torch-spyre's top-level `__init__.py` does
`import torch` on line 20 — while `torch_spyre` itself is still
mid-import. Under torch's device-backend autoload path, that resolves
the entrypoint `torch_spyre:_autoload` by iterating `getattr` down
the module chain. At that instant, `torch_spyre` is a
partially-initialized module: only lines 1-19 have executed, and
`_autoload` has not yet been bound. `getattr(torch_spyre,
"_autoload")` raises `AttributeError`, which torch's
`_import_device_backends()` catches and re-raises as
`RuntimeError: Failed to load the backend extension: torch_spyre.
You can disable extension auto-loading with
TORCH_DEVICE_BACKEND_AUTOLOAD=0.`

Category: `REVERSE_ENTRYPOINT_HAZARD` — a package's own entrypoint
fires re-entrantly during that package's own import.

torch-spyre has a partial guard in place at 69bd7de1 (a `_ran`
sentinel around `_autoload`), but it lives AFTER `import torch` in
the same file, so it never gets a chance to prevent the first call.
The guard only protects against the SECOND autoload, not the first.

## Failure mechanism, in order

1. Test harness (or any `python -c 'import torch_spyre'`) starts.
2. `torch_spyre/__init__.py` runs. Line 20: `import torch`.
3. `torch.__init__` at line ~3030 runs `_import_device_backends()`.
4. That resolves the `torch.backends` entrypoints, one of which is
   `torch_spyre:_autoload`. It walks
   `importlib.metadata.entry_points` and calls
   `functools.reduce(getattr, ["_autoload"], torch_spyre_module)`.
5. `torch_spyre` is only 19 lines in. `_autoload` is not yet bound.
6. AttributeError → RuntimeError → the `import torch_spyre` at
   step 1 raises.

## Why this hits SUPPORTED before FORWARD

Same code path fires under torch 2.13 (SUPPORTED) and torch 2.15
nightly (FORWARD). The break is not a forward-compat regression; it
was introduced at torch-spyre level ~a3128985 (per prior case
`../live-current-main-F3/`) and has been live on every torch-spyre
main commit since. FORWARD_BEFORE_FIX is red for the same reason
SUPPORTED_CONTROL is red — the ladder never even reaches the
forward-vs-supported comparison.

## Row 5 N/A because

The fix does not touch any tensor-producing code path. It reorders
module-scope statements in `torch_spyre/__init__.py` so that an
early stub for `_autoload` is bound before `import torch` fires the
autoload entrypoint. No lowering, no kernel, no dispatch key, no
dtype conversion changes. Row 5's tensor-correctness oracle would
have nothing meaningful to compare — every tensor path in the code
is downstream of the fix and is byte-identical before and after.

## Corroboration

- Failure reproduces deterministically on any fresh Python process:
  we saw it on three separate pods
  (tdeshane-fwdcompat-2026-08-24,
   tdeshane-fwdcompat-2026-08-24b,
   tdeshane-forward-compat-2026-08-25),
  at torch-spyre@8aba5bc, @e7bb29d, and @69bd7de1.
- The `AttributeError` on line 3030 of torch's `__init__.py` points
  directly at the getattr walk. The wrapper `RuntimeError`'s
  message names the entrypoint by module.

## Confidence

High. The three-pod byte-exact reproduction, the exact getattr
trace, and the fact that the same file is edited in the prior F3
case (`../live-current-main-F3/`) with the exact same defer-and-
invoke pattern all point at the same one-file reorder.

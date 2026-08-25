# 03 — Remediation Plan

## Chosen patch shape

Hoist a defer-and-invoke stub `def _autoload()` above the top-level
`import torch` in `torch_spyre/__init__.py`. The stub records that
autoload was requested when it fires reentrantly (i.e. before
`_autoload_impl` has been bound at module scope) and returns
harmlessly. A tail-invoke at the very bottom of the file runs it
once the module is fully loaded.

Keep the existing `_autoload_impl` and the existing `_ran` /
`_requested` sentinel semantics.

## Why the minimum patch is one file

The `AttributeError` in the traceback is `torch_spyre` missing
`_autoload`. Everything else — the trailing `RuntimeError` wrapper,
the failed `import` — is downstream of that one attribute lookup.
Adding the early stub in the same file is the smallest change that
inverts the failure.

We do NOT:

- Remove the existing `def _autoload()` block later in the file
  (the tests in the tree may exercise it directly by name).
- Add the entrypoint deferral in setuptools metadata (that would
  need a re-release and would also affect legitimate autoloads).
- Touch pytorch (the getattr walk in `_import_device_backends()`
  is not the wrong behavior; the reentrant entrypoint is).

## Neighbor set (for Row 2 of the verification matrix)

F3's fix touches ONLY the import-ordering path in
`torch_spyre/__init__.py`. The right neighbor tests are the ones
that exercise import and lazy-init behavior on their own — not the
inductor compile pipeline, which has independent 2.15-vs-2.13
concerns (see the F8 case for that axis). Three top-level tests
in `tests/` are dedicated to this:

- tests/test_spyre_lazy_init.py
- tests/test_spyre_lazy_silent.py
- tests/test_cpp_extension_available.py

## Broader smoke set (for Row 7 of the verification matrix)

Row 7 must have at least 3 tests spanning frontend / mid / backend.
For an import-ordering patch like F3, the broader smoke is again
weighted toward the paths that would surface if the import fix
broke a downstream import or lazy-init concern:

- tests/test_spyre_lazy_init.py
- tests/test_spyre_lazy_silent.py
- tests/test_cpp_extension_available.py

(Deliberately the same tests as Row 2 — F3 does not touch lowering,
so the compile-pipeline tests in `tests/inductor/` are not the
right broader smoke here.)

## Roll-forward / roll-back

The patch is a pure additive reorder in one file. `git apply -R` on
the diff cleanly restores the pre-patch behavior. No build artifact
or generated file changes; no C++ recompilation needed. That's the
right shape for a minimum forward-compat fix.

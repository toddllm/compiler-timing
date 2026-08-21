# F3 — Remediation plan (hypothesis-first, no patch applied)

**Recorded 2026-08-21.** This document is written BEFORE any patch is
applied, satisfying the skill's patch-policy discipline: hypothesis and
falsification plan must exist before the code edit.

## The mechanism (verified by exact traceback)

The circular-import happens in `torch_spyre/__init__.py`. The relevant
prefix at commit `a3128985`:

```python
# torch_spyre/__init__.py, top of file
import os
import threading
import types
import importlib

import torch                                              # ← triggers callback

from .constants import DEVICE_NAME, DISTRIBUTED_BACKEND_NAME
from . import memory
from . import profiler
# ... ~230 lines of _SpyreImpl class, helpers, ...
def _autoload():                                          # ← defined here
    ...
```

Traceback (Case C from `02-import-matrix.md`, run 2026-08-21):

```
Traceback (most recent call last):
  File ".../.venv-latest/lib64/python3.12/site-packages/torch/__init__.py", line 3489, in _import_device_backends
    entrypoint = backend_extension.load()
  File "/usr/lib64/python3.12/importlib/metadata/__init__.py", line 207, in load
    return functools.reduce(getattr, attrs, module)
AttributeError: partially initialized module 'torch_spyre' has no attribute '_autoload'
                                                                   (most likely due to a circular import)

The above exception was the direct cause of the following exception:
  File "<string>", line 2, in <module>
  File ".../torch-spyre/torch_spyre/__init__.py", line 20, in <module>
    import torch
  File ".../.venv-latest/lib64/python3.12/site-packages/torch/__init__.py", line 3536, in <module>
    _import_device_backends()
```

## Exactly what's happening

1. User: `import torch_spyre`.
2. Python starts executing `torch_spyre/__init__.py`.
3. Line 20: `import torch`.
4. torch's `__init__.py` runs its top-level statements. Near the end,
   it calls `_import_device_backends()` (torch line 3536).
5. That function iterates registered `torch.backends` entry points.
6. torch_spyre registered `torch_spyre:_autoload` as one of them.
7. `importlib.metadata` performs the load: `functools.reduce(getattr,
   ["_autoload"], torch_spyre_module)`.
8. `torch_spyre_module` at this instant is the still-executing module
   object — `torch_spyre/__init__.py` has only run through line 20 so
   far. `_autoload` doesn't exist on it yet.
9. `AttributeError`. torch catches it and re-raises as
   `RuntimeError: Failed to load the backend extension`.

## Hypothesis

**H1 (primary):** if `_autoload` is defined *before* line 20's `import
torch`, the entry-point resolution during `_import_device_backends()`
will succeed, and the backend will initialize normally.

**H2 (fallback):** if `_autoload` cannot be moved earlier (because it
depends on symbols not yet imported), a shim `_autoload = None` at line
5 followed by `_autoload = _real_autoload` at the current definition
point would let `getattr` succeed. Then the callback is called with a
None value and either fails-benignly-in-torch or noop.

H1 is architecturally cleaner and requires only a reordering; H2 is a
minimal shim.

## Falsification tests

Both hypotheses have the same falsification test:

```bash
cd /home/tdeshane/forward-compat-2026-08-21/torch-spyre-supported  # SEPARATE tree
# apply patch (see below)
source ../.venv-latest/bin/activate    # or .venv-supported
TORCH_DEVICE_BACKEND_AUTOLOAD=1 python -c 'import torch_spyre'
# Expected: no error, torch_spyre's autoload path completes.
```

Additionally re-run the 5-case import matrix from
`02-import-matrix.md`. Cases C and F must move from FAIL to PASS
without any regression in A, B, D, E, G, H.

## Proposed minimal patch (H1 form, not yet applied)

```python
# torch_spyre/__init__.py — reorder top of file
import os
import threading
import types
import importlib
import sys
import traceback

# Define _autoload FIRST so the entry-point resolution during `import torch`
# below can find it. The actual autoload work is deferred to _autoload_impl,
# which imports torch itself and needs it fully initialized.
def _autoload():
    """PyTorch entry point. Called by torch._import_device_backends()
    during `import torch`. Must be defined before this module's own
    `import torch` statement so the entry-point lookup does not hit a
    partially-initialized module."""
    if getattr(_autoload, "_ran", False):
        return
    _autoload._ran = True
    try:
        _autoload_impl()
    except BaseException:
        print(
            "torch_spyre backend autoload failed; underlying error follows:",
            file=sys.stderr,
        )
        traceback.print_exc()
        raise

# Now the rest of the module.
import torch  # will call _import_device_backends -> _autoload() -> _autoload_impl()

from .constants import DEVICE_NAME, DISTRIBUTED_BACKEND_NAME
# ...
```

`_autoload_impl` remains where it is (much later in the file). The
callback chain is:

1. `import torch` triggers `_import_device_backends`.
2. That calls `_autoload()`, which is now defined.
3. `_autoload()` calls `_autoload_impl()`.
4. `_autoload_impl` does `import torch  # noqa` — but torch is already
   the executing module now (mid-`_import_device_backends`), so this
   just gets the module object. No recursion.
5. `_autoload_impl` proceeds to `torch.utils.rename_privateuse1_backend`,
   `torch._register_device_module`, etc. — this may be the interesting
   spot: does torch have `torch.utils` at this point? Test says: yes,
   because torch's `__init__.py` runs `_import_device_backends()` at
   line 3536, near the END of its own execution.

## Why I am NOT applying this patch this session

Per patch-policy, patch application requires:

1. Hypothesis recorded (this file) ✓
2. Falsification test defined ✓
3. Working baseline (SUPPORTED_CONTROL green) — **not yet**. F1's
   pipeline defect must be fixed first, or SUPPORTED_CONTROL's Stage 0
   will continue to fail for a *different* reason and mask this F3
   patch's effect.

The correct order is:

1. Fix pipeline (F1 root-cause): separate source trees per venv.
2. Rerun. If SUPPORTED_CONTROL now passes Stage 0, we have a working
   baseline.
3. Apply this F3 patch on the separated `torch-spyre-latest/` tree.
4. Run Case C, F. Both should pass.
5. Rerun the ladder. Stage 1 should no longer produce the
   `TORCH_LIBRARY(triton)` error.
6. If SUPPORTED_CONTROL still fails Stage 0 after F1 pipeline fix,
   apply F3 there too. It's likely a DUAL_COMPAT_FIX.

## Related upstream question

`torch._import_device_backends` was introduced in PyTorch 2.6 (approx).
Before that, backends registered via device_module hooks rather than
entry points. `torch~=2.13.0` and later have the entry-point path.
Whether torch-spyre's `__init__.py` structure worked accidentally on
some earlier torch (because entry-points didn't fire during
`import torch`) is a related question but out of scope for this
skill run.

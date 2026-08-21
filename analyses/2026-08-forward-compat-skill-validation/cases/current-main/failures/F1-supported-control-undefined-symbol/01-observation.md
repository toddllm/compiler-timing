# F1 — SUPPORTED_CONTROL undefined C++ symbol at import time

**Failure taxonomy:** `C_EXTENSION_ABI_BREAK`
**Recorded:** 2026-08-21
**Case:** `current-main`
**Configuration:** `SUPPORTED_CONTROL` (torch-spyre@a3128985 + `torch~=2.13.0` from CPU wheel index)

## What we saw

Under `SUPPORTED_CONTROL`, torch-spyre@`a31289852145a59099edccc3e506cf5336e8e2e0`
built cleanly:

```
=== canonical build: --no-deps --no-build-isolation ===
  CXX=c++  (which c++: /usr/lib64/ccache/c++, gcc version: gcc (GCC) 14.3.1 20251022 (Red Hat 14.3.1-4))
...
Successfully built torch_spyre
Successfully installed torch_spyre-0.0.1
=== build exit rc=0 ===
```

(Source: `../../data/build_supported.log` line ~1930-1940.)

At Stage 0 (autoload probe), `import torch_spyre` fails with an
undefined C++ symbol:

```
torch_spyre backend autoload failed; underlying error follows:
Traceback (most recent call last):
  File ".../torch-spyre/torch_spyre/__init__.py", line 263, in _autoload
    _autoload_impl()
  File ".../torch-spyre/torch_spyre/__init__.py", line 291, in _autoload_impl
    import torch_spyre.ops.eager  # noqa: F401
  File ".../torch-spyre/torch_spyre/ops/eager.py", line 16, in <module>
    from torch_spyre._C import fill_tensor, copy_tensor, SpyreTensorLayout
ImportError: /home/tdeshane/forward-compat-2026-08-21/torch-spyre/torch_spyre/_C.so:
  undefined symbol: _ZNK4c10d7Backend15incref_pyobjectEv
```

(Source: `../../data/supported_stage0.log`.)

The C++ symbol demangles to `c10d::Backend::incref_pyobject() const`.

## Cross-checks against upstream

The symbol was NOT found in `torch/csrc/distributed/c10d/Backend.hpp`
on either:

- `pytorch@v2.13.0` (the declared pin baseline)
- `pytorch@main` (the forward pin)

Verified via:

```bash
curl -sf https://raw.githubusercontent.com/pytorch/pytorch/v2.13.0/torch/csrc/distributed/c10d/Backend.hpp | grep -c incref_pyobject
# → 0
curl -sf https://raw.githubusercontent.com/pytorch/pytorch/main/torch/csrc/distributed/c10d/Backend.hpp | grep -c incref_pyobject
# → 0
```

## Environment

- Pod: `tdeshane-forward-compat-2026-08-21` (namespace `a5-deepview`,
  node `p1-worker-48`)
- Image digest:
  `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev@sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`
- torch installed into `.venv-supported`: `torch 2.13.0+cpu` from
  `https://download.pytorch.org/whl/cpu`
- torch-spyre declared pin: `torch~=2.13.0` (from
  `torch-spyre@a3128985:pyproject.toml:13`)
- Compiler: `c++ (GCC) 14.3.1 20251022`, ccache-wrapped via
  `/usr/lib64/ccache/*`
- torch_spyre build: canonical `pip install -e . --no-deps
  --no-build-isolation -vvv --verbose` — succeeded, rc=0.

## What Stage 0 succeeded at

Under `FORWARD_BEFORE_FIX` (torch nightly `2.15.0.dev20260821+cpu`, git
`cef373b344057d8ed91bcf05d7921b2ca1d0d13c`), the same torch-spyre
source builds and imports cleanly and reports
`torch.spyre.device_count() == 1` (see F2). That confirms the failure
is **specific to torch 2.13.0+cpu**, not general to torch-spyre.

## Why the SKILL flagged this as `C_EXTENSION_ABI_BREAK` rather than a
`BUILD_FAILURE` or `PYTHON_API_BREAK`

- The compile and link succeeded (build rc=0). It is not a build
  failure.
- The failure is at `dlopen` of `_C.so`, before any Python-level
  torch-spyre code runs. It is not a Python API break.
- The missing symbol is a torch internal C++ ABI entry. That places it
  in the C-extension category.

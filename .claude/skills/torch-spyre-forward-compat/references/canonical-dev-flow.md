# Canonical torch-spyre dev-install flow

Authoritative summary of how torch-spyre is installed on an
`torch-aiu-runtime-dev` pod. All citations are to the internal IBM
`torch-spyre-docs` repo pinned at
`torch-spyre-docs@e48e00f10ac9549b5dbbea2548ae6fa4253e0466`. Setup
scripts and future forward-compat runs cite this file rather than
re-derive the flow.

## 1. Two install flows exist

torch-spyre-docs ships two install paths. The forward-compat skill
uses the **basic** path for both venvs (declared-supported control +
forward-compat experiment). The **dev** path is out of scope for
v0.1.

**Basic flow** — assumes the runtime image already ships a prebuilt
PyTorch of the pinned version plus prebuilt SENDNN/DEEPTOOLS. Only
`torch-spyre` is built from source.
- `torch-spyre-docs@e48e00f:docs/basic_install.md:7-9` — venv creation
- `torch-spyre-docs@e48e00f:docs/basic_install.md:35-37` — the single build command

**Dev flow** — full `DTI_PROJECT_ROOT` layout that rebuilds LLVM,
deeptools, senbfcc, torch-sendnn, PyTorch, and torch-spyre from
source, coordinated by `dev-env.sh`.
- `torch-spyre-docs@e48e00f:docs/dev_install.md:1-11` — overview and the DTI_PROJECT_ROOT contract
- `torch-spyre-docs@e48e00f:docs/dev_install.md:99-106` — the four AIU stack build scripts
- `torch-spyre-docs@e48e00f:docs/dev_install.md:108-122` — PyTorch install or build
- `torch-spyre-docs@e48e00f:docs/dev_install.md:124-136` — dev-flow torch-spyre build

v0.1 rationale: rebuilding the entire AIU software stack is a
separate, much larger experiment. The forward-compat question ("does
torch-spyre still build and import when PyTorch moves forward?")
lives entirely inside the basic flow — swap the PyTorch install in
the venv, then re-run the canonical build.

## 2. The image contract

Reference pod image tag pattern:
`torch-aiu-runtime-dev:dev-<datestamp>-pt<ver>`.
- `torch-spyre-docs@e48e00f:pods/pod_dd2.yaml:21` — concrete example
  `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:dev-2025_12_10-194600-pt2.9.1`
- `torch-spyre-docs@e48e00f:pods/pod_dd2.yaml:24-26` — `sleep infinity`
  keeps the container up for interactive builds

The image pre-installs one specific PyTorch version and pre-builds
SENDNN/DEEPTOOLS with that PyTorch's headers and libtorch. That is
the "image contract" — the entire toolchain (gcc-toolset, ccache,
cmake, python site-packages) was frozen against one libtorch ABI.

**Forward-compat surface.** Building torch-spyre against a
*different* PyTorch means asking the image's C++ toolchain to link
torch-spyre's C-extension (`torch_spyre/_C*.so`) against a libtorch
that wasn't present when the image was built. When ABI drift bites,
this is exactly where `C_EXTENSION_ABI_BREAK` shows up — either at
build (unresolved symbols) or at first `import torch_spyre`
(undefined-symbol dlopen error).

## 3. The canonical torch-spyre install command

Verbatim from `torch-spyre-docs@e48e00f:scripts/build-torch-spyre.sh:10-13`:

```sh
cd $DTI_PROJECT_ROOT/torch-spyre
export CXX="ccache $(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ | tail -1)"
pip install -e . --no-deps --no-build-isolation -vvv --verbose
unset CXX
```

The basic-flow variant drops `$DTI_PROJECT_ROOT/` and just uses `cd
torch-spyre`
(`torch-spyre-docs@e48e00f:docs/basic_install.md:35-37`); the pip
command itself is identical.

Flag-by-flag rationale:

- `--no-deps` — prevents pip from re-resolving torch-spyre's
  `install_requires` and reinstalling `torch`. Without it, pip would
  yank whatever torch the venv has (the image-baked one, or an
  experiment override) and install its own resolved torch — usually
  a CPU-only wheel from PyPI. That silently clobbers the venv's
  chosen torch version and, for the image-baked variant, breaks
  Spyre device visibility because the CPU wheel lacks the
  PrivateUse1 dispatch registrations SENDNN wired in. **Critical for
  forward-compat**: the whole experiment depends on the venv keeping
  the exact torch we chose to test.

- `--no-build-isolation` — makes setuptools run the build inside the
  venv's live site-packages instead of a fresh PEP 517 isolated
  environment. The build must see the venv's exact `torch` install
  because `setup.py` calls `torch.utils.cpp_extension` to discover
  libtorch's include and library paths, and links `_C.so` against
  those. In an isolated env, pip would download a *different* torch
  into a tempdir and the extension would link against that
  ephemeral libtorch — the resulting `.so` then fails to load
  against the venv's torch at runtime (`C_EXTENSION_ABI_BREAK` on
  first import).

- `-vvv --verbose` — full pip verbosity plus setuptools verbose.
  Required for the forward-compat taxonomy: we classify build
  failures by the linker's exact error text (undefined reference vs.
  redefinition vs. missing header vs. version-script mismatch), and
  that text only reaches stdout at `-vvv`.

- `CXX="ccache $(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ | tail -1)"`
  — pins the compiler to the newest gcc-toolset shipped in the
  image, wrapped in ccache. Falling back to system `/usr/bin/g++`
  produces `std::*` symbol mismatches because the image's libtorch
  was built with gcc-toolset-13 (or whichever the image ships) and
  system gcc is older.

## 4. Prerequisite pip installs

Two ordered install lists must precede the canonical build.

### 4.1 Basic-flow packages
From `torch-spyre-docs@e48e00f:docs/basic_install.md:19-24`:

```sh
pip install expecttest
pip install wheel
pip install psutil
pip install pytest
```

### 4.2 Dev-flow build tooling (also needed for basic flow's C++ build)
From `torch-spyre-docs@e48e00f:docs/dev_install.md:90-97`:

```sh
pip install nanobind==2.9.2
pip install ninja
pip install pybind11
pip install build
pip install cmake~=3.26
pip install regex
pip install wheel
```

The `nanobind==2.9.2` pin is load-bearing — torch-spyre's C-extension
uses nanobind headers and drift in nanobind's API shows up as a
`TORCH_SPYRE_BUILD_API_BREAK`, not an ABI break, so the pin
protects the classifier.

### 4.3 torch-spyre's own dev requirements, filtered
From `torch-spyre-docs@e48e00f:docs/dev_install.md:126-130`:

```sh
pip install -r <(grep -v -E '^(torch)' $DTI_PROJECT_ROOT/torch-spyre/requirements/dev.txt)
```

The `grep -v -E '^(torch)'` filter drops any `torch==...` line from
`requirements/dev.txt` so the experiment's chosen torch survives.
The setup scripts in this skill use the slightly tighter regex
`'^torch([[:space:]<>=!]|$)'` for the same purpose — it matches
`torch`, `torch==...`, `torch>=...`, etc., without accidentally
matching `torchvision` or `torch-sendnn`.

## 5. Venv creation form

From `torch-spyre-docs@e48e00f:docs/basic_install.md:7-9`:

```sh
python3 -m venv torch-spyre-venv --system-site-packages
```

`--system-site-packages` is required. The runtime image installs
SENDNN and DEEPTOOLS python bindings into the system interpreter's
site-packages (per the pre-baked AIU stack), and the venv inherits
them through this flag. Without it, `import torch_sendnn` inside the
venv fails, `torch_spyre` then can't register its PrivateUse1
backend, and the whole thing looks like a
`PYTHON_IMPORT_API_BREAK` when it's really a venv-configuration
bug.

For the dev flow the same pattern is used but under
`$DTI_PROJECT_ROOT/dti-venv`
(`torch-spyre-docs@e48e00f:docs/dev_install.md:57-60`) — the basic
flow's `torch-spyre-venv` is equivalent for our purposes.

## 6. Runtime env vars set by dev-env.sh

Set by the dev flow via `source dev-env.sh`
(`torch-spyre-docs@e48e00f:scripts/dev-env.sh:1-29`). The basic flow
does not need these to be set explicitly — the image already exports
equivalents at container start — but they are listed here for
completeness and for the taxonomy classifier.

- `DTI_PROJECT_ROOT` (`scripts/dev-env.sh:2`) — dev-flow root only;
  unused in basic flow
- `SEN_PROJECT_SRC` (`scripts/dev-env.sh:11`) — points at the source
  tree that holds `sentient/`; consumed by `build-deeptools.sh` etc.
- `SEN_PROJECT_BUILD` (`scripts/dev-env.sh:12`) — out-of-tree build
  root
- `SENTIENT_BASE_INSTALL_DIR` (`scripts/dev-env.sh:13`) — where the
  AIU stack installs to; runtime and deeptools live under it
- `PYTHONPATH` (`scripts/dev-env.sh:14`) — set to
  `${SENTIENT_BASE_INSTALL_DIR}/runtime/lib`; must contain the
  SENDNN python bindings dir or torch-spyre's device registration
  fails silently
- `DEEPTOOLS_INSTALL_DIR` (`scripts/dev-env.sh:15`) — consumed by
  torch-spyre's cmake for deeptools headers
- `SENDNN_DIR` and `SENDNN_INSTALL_DIR` (`scripts/dev-env.sh:17-18`)
  — same target directory, two env-var names, because different
  layers of the build read different ones
- `LLVM_PROJ_SRC` (`scripts/dev-env.sh:21`) — LLVM source dir for
  MLIR pieces; dev-flow only
- `MAX_JOBS=64` (`scripts/dev-env.sh:29`) — parallelism cap for the
  C++ build; the image has enough RAM headroom for 64 at
  torch-spyre's size

Additionally `PATH` and `LD_LIBRARY_PATH` are extended to include
`${SENTIENT_BASE_INSTALL_DIR}/runtime/bin`, `deeptools/bin`, and the
matching `lib` dirs (`scripts/dev-env.sh:26-27`). In the basic flow
these are pre-set inside the image, but the taxonomy classifier
should still record them because a corrupt image occasionally ships
with `LD_LIBRARY_PATH` unset — that presents as
`SUBSTRATE_FAILURE`.

## 7. Common failure modes, mapped to failure-taxonomy.md

Category names match `failure-taxonomy.md` in this same references
directory. Each row: symptom → root cause → category.

- **Missing gcc-toolset directory.** `ls
  /opt/rh/gcc-toolset-*/root/usr/bin/c++` prints nothing, `CXX`
  export in `build-torch-spyre.sh:11` sets `CXX="ccache "`, the
  build calls the empty string and fails immediately. Root cause:
  wrong or corrupt image (no gcc-toolset baked in). Category:
  `SUBSTRATE_FAILURE`.

- **`--no-deps` omitted.** pip resolves `torch-spyre`'s
  `install_requires`, pulls a CPU-only `torch` wheel from PyPI over
  the image-baked torch. Build often succeeds against the new
  wheel, then `import torch_spyre` fails to find the Spyre device
  because the CPU wheel has no PrivateUse1 dispatch registration.
  Presents as `PYTHON_IMPORT_API_BREAK` but is really
  `CORRECTNESS_REGRESSION` masquerading as one — the classifier
  must check `pip freeze | grep '^torch=='` against the intended
  version before accepting `PYTHON_IMPORT_API_BREAK`.

- **`--no-build-isolation` omitted.** PEP 517 sets up an isolated
  build env with pip's resolved torch. `_C.so` links against that
  ephemeral libtorch. First `import torch_spyre` after install
  fails with an undefined-symbol `dlopen` error against libtorch
  symbols. Category: `C_EXTENSION_ABI_BREAK`.

- **`CXX` wrong or unset.** Falls back to `/usr/bin/g++` (system
  gcc). Compilation succeeds but link fails with `std::*` version
  mismatches, or subtle segfaults on load because the C++ standard
  library ABI differs from libtorch's. Category:
  `TORCH_SPYRE_BUILD_API_BREAK` (build layer), or
  `C_EXTENSION_ABI_BREAK` if it links but crashes on load.

- **`nanobind` unpinned or wrong version.** Build errors reference
  `nb::` symbols. Category: `TORCH_SPYRE_BUILD_API_BREAK`.

- **`torch` filter regex missed.** `requirements/dev.txt` ships a
  torch pin, filter used `'^torch'` unanchored so `torch-sendnn`
  matched and got skipped (or the opposite: `torch` got installed
  and clobbered the venv's chosen version). Category:
  `TORCH_SPYRE_BUILD_API_BREAK` (build sees wrong torch) or
  `CORRECTNESS_REGRESSION` (runtime sees wrong torch). Use the
  anchored regex `'^torch([[:space:]<>=!]|$)'`.

- **`PYTHONPATH` missing SENDNN runtime.** `import torch_sendnn`
  fails or succeeds but with the wrong shared lib. Category:
  `PYTHON_IMPORT_API_BREAK` if it's a real API change,
  `SUBSTRATE_FAILURE` if the image is misconfigured.

## 8. Explicitly out of scope for v0.1

The forward-compat skill v0.1 does *not* attempt any of:

- **Full dev-flow install.** No `DTI_PROJECT_ROOT`, no
  `checkout-required-src.sh`, no `dev-env.sh` sourcing. Both venvs
  use the basic flow.
- **Rebuilding senbfcc, deeptools, or torch-sendnn from source.**
  The image's prebuilt AIU stack is treated as fixed. If a
  forward-compat failure lands squarely in the AIU stack (rather
  than torch-spyre proper), classify as `NOT_TORCH_SPYRE` and stop.
- **Building PyTorch from an exact upstream `main` SHA on-pod.**
  The v0.1 experiment installs a released PyTorch wheel newer than
  the image-baked pin. Building PyTorch from source on-pod (needed
  when the failure hypothesis is a specific `main` commit) is a
  v0.2 escalation: it needs the pytorch source checkout
  (`torch-spyre-docs@e48e00f:docs/dev_install.md:41-45`), the
  full `build-pytorch.sh` invocation, and a 3+ hour build ceiling.

If a v0.1 run points at any of these being necessary, log the
finding, mark the case `UNKNOWN` per
`failure-taxonomy.md`, and hand off to a v0.2 escalation.

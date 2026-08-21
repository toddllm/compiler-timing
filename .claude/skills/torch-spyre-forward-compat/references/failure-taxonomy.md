# Failure taxonomy — forward-compat runs

When torch-spyre is run against a newer PyTorch than it declares
support for (e.g. `torch~=2.13.0` in `pyproject.toml` at
torch-spyre@a3128985, exercised against pytorch main
@73961011bf64f1c04b3291bf90ac1dbbe197c2ca on 2026-08-21), the run
can fail at many different points. Different failures need different
responses. In particular: **most failures are NOT torch-spyre
issues, and MUST NOT be "fixed" by patching torch-spyre.**

## Rule zero — classify BEFORE editing

The skill refuses to patch torch-spyre until the failure is
classified and the classification points at a torch-spyre-side
issue. If the classification is not `TORCH_SPYRE_BUILD_API_BREAK`,
`PYTHON_IMPORT_API_BREAK`, `INDUCTOR_API_BREAK`,
`SEMANTIC_COMPILER_BREAK`, `GRAPH_STRUCTURE_BREAK`, or
`CORRECTNESS_REGRESSION` (the six torch-spyre-actionable categories
below), STOP. Recording the classification and its evidence in
`03-results.md` is the deliverable — a patch is not.

The four non-torch-spyre categories (`SUBSTRATE_FAILURE`,
`PYTORCH_BUILD_FAILURE`, `TEST_HARNESS_DRIFT`, `NOT_TORCH_SPYRE`)
and the deferred category `PERFORMANCE_REGRESSION` (a movement, not
a break) are recorded and escalated, not patched. `UNKNOWN` is
promoted through the checklist at the end of this file until it
lands in a real category.

## Categories

Each entry: **Definition** — 2–3 sentences. **Typical evidence** —
what the log looks like. **Response** — do NOT edit torch-spyre?
Which layer moves? **Example** — plausible, often invented.

### SUBSTRATE_FAILURE

**Definition.** The failure happens before any torch-spyre or
PyTorch code runs — the pod, container image, or its baked
dependencies are wrong or broken. Nothing about the two source
trees is under test yet. Any measurement or triage of the source
trees on this pod is invalid.

**Typical evidence.**
- Pod fails to schedule, `ImagePullBackOff`, wrong node label,
  wrong namespace.
- `ldd` on a baked `.so` misses libraries that the image is
  supposed to carry.
- `nvidia-smi` / `aiu-smi` / device-node probe fails at the
  container boundary.
- The base image digest recorded at pod creation does not match
  what's now in the registry (someone re-tagged `:latest`).

**Response.** Do NOT edit torch-spyre. Do NOT edit PyTorch.
Recreate the pod against a pinned image digest and re-record the
digest in `01-substrate.md`. If the failure reproduces on a fresh
pod with a fresh digest of the same tag, escalate to the image
owners; if it reproduces on a fresh pod with a known-good older
digest, escalate to cluster ops.

**Example.** Fresh pod `tdeshane-forward-compat-2026-08-21` in
`a5-deepview` shows `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`
in the pod spec but the running container's `/etc/aiu-release`
reports a build from March. The `:latest` tag was re-pointed
between pod creation and container start. → SUBSTRATE_FAILURE.
Recreate with `us.icr.io/.../torch-aiu-runtime-dev@sha256:<digest>`
where `<digest>` was resolved and recorded at pod creation.

### PYTORCH_BUILD_FAILURE

**Definition.** Building PyTorch from the target main SHA on the
fresh pod fails. torch-spyre has not been imported yet, so this
failure cannot be attributable to it. The build environment (glibc,
libstdc++, cmake, ninja, python headers, CUDA/AIU toolchain) or the
PyTorch source at that SHA is the subject.

**Typical evidence.**
- `python setup.py develop` / `pip install -e .` exits non-zero
  during the C++/CUDA compile step; the error is in a PyTorch
  source file (path under `pytorch/`), never under
  `torch_spyre/`.
- CMake configure fails locating a system dependency (libnuma,
  libuv, CUDA, ROCm, MKL).
- Linker errors reference symbols that do not exist in the
  system's stdlib (e.g. `GLIBCXX_3.4.32` when libstdc++ is older).
- The build enters an OOM-kill loop with dmesg confirming Killed.
- Build exceeds the 3h ceiling recorded in the substrate section.

**Response.** Do NOT edit torch-spyre. Do NOT patch PyTorch to
work around the substrate — a build workaround is a substrate
report, not a fix. Record:

- The exact command line and the last ~40 lines of build output
  in `03-results.md`.
- The pytorch commit and short-sha
  (`73961011bf64f1c04b3291bf90ac1dbbe197c2ca`, `7396101`).
- The substrate versions (`gcc --version`, `ld --version`,
  `python --version`, `cmake --version`, image digest).

Then either escalate to pytorch-side (open an issue upstream if
the build error reproduces on their supported substrate) or
substrate-side (request a newer base image). The forward-compat
run for this pod is TERMINATED — no torch-spyre measurement is
possible on this pod.

**Example.** Fresh pod build of pytorch@7396101 fails at
`aten/src/ATen/native/cuda/Some.cu` with `error: no matching
function for call to 'at::cuda::detail::foo(...)'`. The pod's
CUDA toolkit is 12.4; pytorch main dropped 12.4 support two
weeks ago and requires ≥12.6. → PYTORCH_BUILD_FAILURE.
Substrate mismatch; request a newer base image and re-provision.

### TORCH_SPYRE_BUILD_API_BREAK

**Definition.** PyTorch built successfully, but building
`torch_spyre` against it fails at the C++/C-extension boundary.
PyTorch changed a public C++/pybind API that `torch_spyre/csrc/`
uses. torch-spyre code that was correct against `torch~=2.13.0`
is now incorrect against the newer torch.

**Typical evidence.**
- `pip install -e .` on the torch-spyre tree fails during the
  C++ compile of `torch_spyre/csrc/*.cpp` — the error path is
  under `torch_spyre/csrc/`, the referenced type/function is
  under `torch/`.
- Compiler errors of the form "no member named X in namespace
  torch::…", "incompatible pointer to function", "cannot convert
  `torch::TensorOptions` to `at::TensorOptions`".
- Linker errors after compile succeeds referencing removed
  symbols in `libtorch.so`.

**Response.** This IS a torch-spyre-side action, but the action
is documenting the API break and its minimum patch — not a
distributed refactor. Follow `SKILL.md` §"Hypothesis-before-fix":

1. Cite the torch-spyre line
   (`torch-spyre@a3128985:torch_spyre/csrc/<file>:<line>`) and
   the pytorch line
   (`https://github.com/pytorch/pytorch/blob/7396101/<file>#L<line>`).
2. Write down which pytorch commit changed the API (bisect if
   necessary).
3. Author the minimum patch on torch-spyre that compiles against
   the new signature AND preserves the old-torch code path via a
   `TORCH_VERSION_MAJOR/MINOR` guard.
4. Verify the patch still builds against `torch~=2.13.0`
   (declared-supported control).

**Example.** `torch_spyre/csrc/aten_ops.cpp:412` calls
`at::native::_reshape_alias_copy(t, sizes, strides)`. On
pytorch main the third positional argument was renamed and the
symbol was moved from `at::native::` to `at::_ops::`. Compile
fails with `error: no member named '_reshape_alias_copy' in
namespace 'at::native'`. → TORCH_SPYRE_BUILD_API_BREAK. Minimum
patch is a preprocessor branch on `TORCH_VERSION_MAJOR/MINOR`
that dispatches to the new `at::_ops::` overload when built
against ≥2.14, keeping the `at::native::` call for
`torch~=2.13.0`.

### PYTHON_IMPORT_API_BREAK

**Definition.** Both trees built. `python -c "import torch_spyre"`
fails at import time because a torch Python-side symbol that
torch-spyre imports has been removed, renamed, or moved. No
compilation has started yet.

**Typical evidence.**
- `ImportError: cannot import name 'X' from 'torch._Y'`.
- `AttributeError: module 'torch._Y' has no attribute 'X'` from a
  top-level assignment in `torch_spyre/**/__init__.py` or one of
  the modules it imports at package load.
- The stack trace terminates in a torch-spyre file whose import
  line references a `torch._dynamo`, `torch._inductor`,
  `torch.fx`, or `torch._C` name.
- Nothing in the trace is under `_inductor/pipeline` — this is
  earlier than any pass runs.

**Response.** Torch-spyre-side, minimum-patch: replace the removed
name with the new one, guarded by a version check if the old name
is still needed for `torch~=2.13.0`. Cite both sides per the
hypothesis-before-fix template.

**Example.** `torch_spyre/_inductor/__init__.py:12` does
`from torch._inductor.scheduler import BaseSchedulerNode as _BSN`.
On pytorch main the class was renamed to `SchedulerNodeBase` and
`BaseSchedulerNode` was removed after a deprecation cycle.
Import fails at torch-spyre package load. →
PYTHON_IMPORT_API_BREAK. Minimum patch: `try: from
torch._inductor.scheduler import SchedulerNodeBase as _BSN /
except ImportError: from torch._inductor.scheduler import
BaseSchedulerNode as _BSN`.

### INDUCTOR_API_BREAK

**Definition.** Both trees built, torch-spyre imported, and a
compile attempt reaches Inductor. It fails inside torch-spyre's
inductor integration because an Inductor internal (an FX pass hook,
a scheduler protocol, a codegen entry, a `V.graph` attribute) has
changed shape. torch-spyre is calling into upstream Inductor with
an old-shaped call.

**Typical evidence.**
- `TypeError: X() got an unexpected keyword argument 'Y'` where
  the call site is in torch-spyre and the callee is in
  `torch._inductor.*`.
- `AttributeError: 'GraphLowering' object has no attribute
  'some_attr'` originating from `torch_spyre/_inductor/*.py`.
- Failure at the register-custom-passes moment, at the scheduler
  wrap moment, or during `codegen_kernel` — after the frontend
  passes have started, so `pipeline:CustomPreGradPasses` may
  appear in the trace but the failing frame is torch-spyre's
  inductor glue.
- The frame that raises is in `torch._inductor` but the
  offending argument was constructed in torch-spyre.

**Response.** Torch-spyre-side, minimum-patch, hypothesis-first.
The fix pattern is a version-gated adapter around the Inductor
call, not a rewrite of the Spyre pass pipeline. Verify the
minimum patch does not perturb `_inductor/pipeline/*` behavior on
declared-supported torch.

**Example.** `torch_spyre/_inductor/__init__.py:88` registers
custom pre-grad passes with
`register_custom_pre_grad_pass(pass_fn, name="CustomPreGrad")`.
Upstream removed the positional-only `pass_fn` slot on pytorch
main; the callable is now passed via a builder object. On the
new torch this raises `TypeError: register_custom_pre_grad_pass()
missing 1 required positional argument: 'builder'`. →
INDUCTOR_API_BREAK. Minimum patch guards the call site on the
Inductor version.

### SEMANTIC_COMPILER_BREAK

**Definition.** The compile runs end-to-end, no exception is
raised — but the compiled artifact is wrong at the semantics
level. A Spyre pass produced malformed IR because an assumption it
made about Inductor's FX graph shape (attribute presence, node
op-name string, meta-tensor stride convention) no longer holds.
The break is not a crash; it is a wrong graph.

**Typical evidence.**
- Compile succeeds. `sdsc_bundle_gen` emits a bundle. But
  `_C.compiled_graph.run(inputs)` returns tensors of the wrong
  shape/dtype, or the runtime rejects the bundle with
  "unexpected operand" / "layout mismatch" / "spec references
  undefined tensor".
- A Spyre pass silently no-ops on a graph structure it does not
  recognize (e.g. an op name it filters by string comparison was
  renamed upstream), and the downstream pass sees a graph that
  should have been rewritten.
- `--compare-cpu` shows a numeric mismatch that does not
  reproduce on the declared-supported control.

**Response.** Torch-spyre-side, but the diagnosis is harder than
an API break. Follow the hypothesis-first template with
particular care: the hypothesis must name the specific pass, the
specific assumption, and the specific upstream change that
invalidated it. Cite `torch-spyre@<sha>:<pass-file>:<line>` for the
assumption and the pytorch commit that changed the surrounding
Inductor behavior. Verify the minimum patch on both the
declared-supported control and the new torch.

**Example.** `torch_spyre/_inductor/passes/propagate_layouts.py:214`
filters candidate nodes with `if node.target ==
"aten.copy_.default":`. On pytorch main the copy operator was
namespaced to `"aten::copy_.default"` in FX target strings; the
filter now matches zero nodes; the layout propagation pass no-ops;
downstream tile planning inserts the wrong reads. Compile
succeeds, output tensor has wrong strides on the fast-path shape.
→ SEMANTIC_COMPILER_BREAK. Minimum patch replaces the exact-string
match with a resolved-op-overload comparison.

### GRAPH_STRUCTURE_BREAK

**Definition.** A specific torch-spyre pass fails because the FX
graph it received has a structure that pass was not written to
handle. Upstream Inductor's decomposition or pattern-matching
changed and now emits, say, a `torch.ops.aten.split_copy.Tensor`
where torch-spyre's pass expected `aten.split.Tensor`. Related to
`INDUCTOR_API_BREAK` but distinct — the API surface is unchanged,
the *content* passed through it changed.

**Typical evidence.**
- `KeyError`, `IndexError`, or `AssertionError` inside a
  torch-spyre pass — the traceback lands in
  `torch_spyre/_inductor/passes/<pass>.py` — with the failure
  showing the pass encountered an op or an FX-node shape it did
  not expect.
- Pass runs, but a downstream pass asserts an invariant it should
  have maintained. Trace shows two pass frames; the earlier one
  is the actual cause.
- Reproduces cleanly with a single small sentinel (WA_baseline
  or the smallest scaling point) — the graph shape difference is
  not workload-specific.

**Response.** Torch-spyre-side, minimum-patch. The fix is
usually broadening the pass's op-set to include the new
decomposed op, or normalizing the new op back to the old shape at
pass entry. Verify on the declared-supported control that the
broadened pass still handles the old graph identically.

**Example.** `torch_spyre/_inductor/wsr/coarse_tile.py:842`
walks `aten.split.Tensor` nodes in `_plan_read_copies`. On
pytorch main a decomposition change now emits
`aten.split_with_sizes.Tensor` for the same source-level `split`
call on shapes ≥2048. The pass raises `AssertionError: expected
aten.split.Tensor, got aten.split_with_sizes.Tensor`. →
GRAPH_STRUCTURE_BREAK. Minimum patch handles both op targets in
the same walker branch.

### CORRECTNESS_REGRESSION

**Definition.** No exception, no bundle-emission error, but
`--compare-cpu` returns a numeric mismatch on the new torch that
did not reproduce on the declared-supported control. Either a
Spyre pass or a codegen path is producing wrong output. Related
to `SEMANTIC_COMPILER_BREAK` but distinguished by symptom: this
one is caught by numerical comparison, not by bundle validation
or runtime rejection.

**Typical evidence.**
- `--compare-cpu` reports `max_abs_err = 3.2e-1` on the new
  torch and `max_abs_err = 1.1e-6` on the declared-supported
  control at the same sentinel.
- Reruns give the same magnitude of mismatch (not noise).
- The mismatch localizes to a specific tensor / operator; other
  outputs of the same graph match CPU within tolerance.

**Response.** Torch-spyre-side, but treat with the highest care —
a silent wrong result is worse than any crash. Do NOT commit any
patch until:

1. The bad tensor is localized to a specific op / a specific
   pass invocation.
2. The pytorch commit that changed the corresponding upstream
   behavior is identified.
3. A minimum patch is verified on both the declared-supported
   control (still numerically matches CPU) and the new torch
   (now numerically matches CPU).

If any of these three is missing, the classification stays
`CORRECTNESS_REGRESSION` in `03-results.md` and no patch is
committed. Escalate.

**Example.** A matmul-then-add fused pattern that hits a Spyre
`fma`-style codegen path yields correct results on
`torch~=2.13.0` and `max_abs_err = 0.28` (float32) on pytorch
main. The upstream commit that changed
`aten.addmm.default`'s decomposition on the shape class
`(B, N, N)` also changed which arg the beta scales. torch-spyre's
codegen assumed beta scales arg2. → CORRECTNESS_REGRESSION.
Localize, cite, patch, verify both sides.

### TEST_HARNESS_DRIFT

**Definition.** The test/measurement harness itself is broken on
the new torch — the workload script, the correctness comparator,
the timing recorder, or the sentinel driver imports or calls a
torch API in a way that fails on the new torch, independently of
torch-spyre. torch-spyre's compile path may work fine; the run
still shows a red result because the harness cannot report it.

**Typical evidence.**
- The failing frame is under `scripts/`, `analyses/`,
  `.claude/skills/*/scripts/`, or a workload harness — not under
  `torch_spyre/`.
- Errors reference torch APIs the harness uses for measurement or
  reference computation (`torch.cuda.synchronize`,
  `torch.utils._pytree`, `torch._dynamo.reset`, private profiler
  APIs) rather than for compilation.
- Swapping the harness for a known-minimum reproducer against the
  same torch-spyre + torch pair produces a clean run.

**Response.** Do NOT edit torch-spyre. Fix the harness under
`compiler-timing/` (or the ephemeral experiment directory) or
under `analyses/`. If the harness lives inside torch-spyre's own
tests, that's still a torch-spyre patch — but it should be
labeled `TEST_HARNESS_DRIFT`, not any of the compiler-side
categories, and reviewed on that footing.

**Example.** The `timing_shim.py` measurement harness calls
`torch._dynamo.reset()` before each cold-cache sample. On pytorch
main this function was renamed to `torch._dynamo.reset_state`
with `reset` becoming a shim that emits a deprecation warning —
but the shim raises `AttributeError` when Dynamo's compile cache
is in a particular state that only appears on the new torch. →
TEST_HARNESS_DRIFT. Fix is in `timing_shim.py`, not in torch-spyre.

### PERFORMANCE_REGRESSION

**Definition.** Compile succeeds, output is numerically correct
against CPU, but compile time or run time is measurably worse on
the new torch. This is a movement, not a break — and forward-compat
is not primarily a performance study. Record it, quantify it,
defer it.

**Typical evidence.**
- `compile_fx_wrapper` inclusive time on the new torch is outside
  the spread of the declared-supported control's samples on the
  same sentinel.
- One or more `pipeline:*` events shift measurably; structural
  counters (`fx_nodes_at_entry`, `n_specs`,
  `input_operations`) are unchanged (see
  `frontend-compiler-impact/references/interpretation-guide.md`
  §"Structural change vs performance change").

**Response.** Do NOT edit torch-spyre in the forward-compat run.
Record the delta in `03-results.md` with the same measurement
discipline the frontend-compiler-impact skill requires
(inclusive_ns, sample spread, structural-counter check). File a
follow-up under `analyses/` for a dedicated performance study.
Forward-compat's job is to get the run green — a performance
delta that is not accompanied by any other category above is
green-with-a-note, not red.

**Example.** On the new torch, `compile_fx_wrapper` on
`WB_scaling_pair@n=4` is 71.2 s (min 70.9, max 71.8) vs 64.4 s
(min 64.1, max 64.9) on the declared-supported control. Δ = +6.8 s
(+10.6%), outside spread on both sides. Structural counters
unchanged. No numeric mismatch, no crash. →
PERFORMANCE_REGRESSION. Record; open follow-up.

### NOT_TORCH_SPYRE

**Definition.** A failure occurred somewhere in the run, but the
failing component is neither torch-spyre nor PyTorch — a third
dependency (numpy, sympy, protobuf, an AIU runtime library, a
tokenizer, a random test-time HTTP fetch) failed. The failure is
attributable to that third component's version, not to the pair
under test.

**Typical evidence.**
- Failing frame is under a third-party package in
  `.venv/lib/pythonX.Y/site-packages/<pkg>/…` where `<pkg>` is
  not `torch` or `torch_spyre`.
- `pip check` on the pod reports resolver-level conflicts unrelated
  to the pair under test.
- The same failure reproduces with torch-spyre replaced by a
  trivial script that only imports the third dependency.

**Response.** Do NOT edit torch-spyre. Do NOT edit PyTorch.
Either pin the third dependency to a known-good version and
document the pin in `01-substrate.md`, or escalate to the third
dependency's maintainers. If pinning it green-lights the
forward-compat run, that pin is a substrate note, not a fix.

**Example.** During a compile the AIU runtime library
`libaiu_runtime.so` reports an ABI mismatch: it was built against
protobuf 4.x, but the pod's site-packages has protobuf 5.x
because pytorch main's requirements bumped it. The failing frame
is a `google.protobuf` importer under site-packages, not under
`torch_spyre/` or `torch/`. → NOT_TORCH_SPYRE. Pin protobuf to
4.x in the venv (record the pin) or request the AIU runtime team
rebuild against protobuf 5.x.

### UNKNOWN

**Definition.** The failure has been observed and captured, but
the evidence available so far does not uniquely identify which
of the above categories it falls into. Use this as a **holding
state**, never as a resting state.

**Typical evidence.**
- A trace with a torch-spyre frame AND a torch frame AND a
  substrate library frame — any of the three could be the cause.
- An intermittent failure not yet reproduced enough times to
  determine substrate vs source-tree.
- A failure whose stack trace was lost (crash in a child process
  without stderr capture).

**Response.** Do NOT edit anything. Continue the promotion
checklist below until the classification is definite.

**Example.** `python -c "import torch_spyre; import torch" ; python
run_sentinel.py` exits with SIGSEGV, no Python traceback. Could be
a C-extension ABI mismatch (TORCH_SPYRE_BUILD_API_BREAK), a bad
substrate library (SUBSTRATE_FAILURE), or a corrupt install
(NOT_TORCH_SPYRE). → UNKNOWN until at least one is ruled out.

### PIPELINE_DEFECT

The failure is caused by the skill's own pipeline mixing state
between two configurations (typically the SUPPORTED_CONTROL and
FORWARD_BEFORE_FIX venvs). torch-spyre and torch are not to blame.

**Typical evidence.**
- Two builds against different torch versions were run in the same
  shell / directory / source tree.
- `stat -c "%y %n"` on the built artifact (`_C.so`, wheel, install
  metadata) shows a timestamp later than one of the two build logs
  but pointing at the wrong venv's editable install.
- Symbol probe: `nm -uD` on the artifact shows undefined refs from
  the *other* venv's torch (i.e. the artifact was built against a
  different torch than the venv now trying to load it).

**Response.** Do NOT edit torch-spyre. Fix the pipeline. Give each
venv its own source tree (fresh clone or `git clone --reference`
with `--dissociate`), rerun both configurations, then re-classify
whatever failure remains.

**Fast pre-flight probe** (add to Stage 0 as `SUPPORTED_CONTROL_PROBE`):

```bash
# The set difference must be empty. Any element that appears is a
# real ABI mismatch. If the .so was contaminated by another venv's
# build, this catches it before Stage 0 spends time.
comm -23 \
  <(nm -uD "$WORKDIR/torch-spyre/torch_spyre/_C.so" | awk '{print $NF}' | sort -u) \
  <(nm -D  "$VENV/lib*/python3.12/site-packages/torch/lib/libtorch_cpu.so" \
        | awk '$2=="T"{print $NF}' | sort -u)
```

**Example (this validation run, F1).** Two builds against
`.venv-supported` (torch 2.13.0) and `.venv-latest` (torch 2.15.0.dev
nightly) shared a single `torch-spyre/` clone. The second (nightly)
build overwrote `torch-spyre/torch_spyre/_C.so`. When SUPPORTED_CONTROL
Stage 0 later ran, its editable install pointed at the on-disk `_C.so`
— nightly-built, referencing `c10d::Backend::incref_pyobject`, which
`.venv-supported`'s libtorch (2.13.0) does not define.

### REVERSE_ENTRYPOINT_HAZARD

torch-spyre registers `torch_spyre._autoload` as a torch backend
entry point in `pyproject.toml`. On modern torch, `import torch`
triggers `_import_device_backends()` which invokes every registered
entry point. If a caller imports `torch_spyre` **without importing
`torch` first**, then torch_spyre's own `__init__.py` starts
executing, imports torch, and torch's `_import_device_backends()`
callback fires — but torch_spyre's `__init__.py` has not yet reached
the definition of `_autoload`. The callback fails on a partially-
initialized module, and any retry produces cascading errors like
duplicate `TORCH_LIBRARY` registrations.

**Typical evidence.**
- `AttributeError: partially initialized module 'torch_spyre' has no
  attribute '_autoload' (most likely due to a circular import)`.
- Downstream: `RuntimeError: Only a single TORCH_LIBRARY can be used
  to register the namespace <ns>` in the *same* python process.
- Test: `python -c "import torch_spyre"` fails, but `python -c
  "import torch; import torch_spyre"` succeeds.

**Response.** Fix in torch-spyre-side, hypothesis first. Either
restructure `torch_spyre/__init__.py` so `_autoload` is defined at
the top of the module before any statement that might trigger a
callback, or make the entry-point callable resilient to being
called before initialization completes (e.g. cache a resolution
promise; on re-entry, no-op or await).

**Import-matrix diagnostic recipe.** Run this as Stage 0 probe on
both venvs:

```
A) python -c "import torch"
B) python -c "import torch; import torch._inductor"
C) python -c "import torch_spyre"                 # no `torch` first, autoload on
D) TORCH_DEVICE_BACKEND_AUTOLOAD=0 python -c "import torch_spyre"
E) python -c "import torch; import torch_spyre"
F) python -c "import torch_spyre; import torch_spyre._inductor.lowering"
G) TORCH_DEVICE_BACKEND_AUTOLOAD=0 python -c "import torch_spyre; import torch_spyre._inductor.lowering"
H) python -c "import torch; import torch._inductor; import torch_spyre; import torch_spyre._inductor.lowering"
```

If A, B, D, E, H pass and C, F fail with "partially initialized
module" or a downstream `TORCH_LIBRARY` error, classify as
`REVERSE_ENTRYPOINT_HAZARD`. If C or F fails with a different
signature, this is not the right category.

**Example (this validation run, F3).** Case C and F fail with the
circular-import signature; A, B, D, E, H all pass. That
disambiguates the underlying `TORCH_LIBRARY(triton)` double
registration observed in Stage 1 as a downstream symptom of this
re-entrancy, not an independent Triton compatibility issue.

## How to promote UNKNOWN to a real category

Work the list top to bottom. Stop at the first step that
uniquely identifies a category — but complete enough of the
remaining steps to rule out the neighboring categories with
confidence.

1. **Recreate the pod.** If the failure does not reproduce on a
   freshly-provisioned pod using the recorded image digest, it
   was almost certainly `SUBSTRATE_FAILURE`. Log and stop.
2. **Rebuild PyTorch from scratch on the fresh pod.** If the
   build fails: `PYTORCH_BUILD_FAILURE`. If the build succeeds
   but the failure changes character: substrate contamination
   was involved — treat as `SUBSTRATE_FAILURE` and re-baseline.
3. **Skip torch-spyre. Run a torch-only smoke.** `python -c
   "import torch; torch.compile(lambda x: x*x)(torch.randn(3))"`
   on the new torch. Failure here is upstream — `NOT_TORCH_SPYRE`
   from the forward-compat run's perspective.
4. **Rebuild torch-spyre from source against the new torch.**
   Failure in the C++/C-extension build: `TORCH_SPYRE_BUILD_API_BREAK`.
5. **Import torch_spyre in isolation.** Failure at import:
   `PYTHON_IMPORT_API_BREAK`.
6. **Run the declared-supported control on the same pod.** If the
   same failure reproduces against `torch~=2.13.0`, this is NOT
   a forward-compat break — it is a pre-existing bug in
   torch-spyre or its harness that the run happened to expose.
   Reclassify accordingly (usually `TEST_HARNESS_DRIFT` or a
   torch-spyre issue unrelated to forward-compat) and route to
   the appropriate track.
7. **Run one small sentinel end-to-end.** If it crashes during
   `pipeline:*` or `sdsc_bundle_gen` with a torch-spyre frame:
   `INDUCTOR_API_BREAK` or `GRAPH_STRUCTURE_BREAK` (distinguish
   by whether the failure is at the call boundary to Inductor
   vs inside a torch-spyre pass reading the FX graph).
8. **Run `--compare-cpu` on that sentinel.** If compile
   succeeds but numeric comparison fails only on the new torch:
   `SEMANTIC_COMPILER_BREAK` (if a bundle validation or runtime
   rejection precedes the compare) or `CORRECTNESS_REGRESSION`
   (if the compare itself is the first indicator).
9. **Measure compile time on the sentinel with the discipline of
   the frontend-compiler-impact skill.** If the run is green but
   slower outside sample spread: `PERFORMANCE_REGRESSION`.
10. **Re-examine the failing frame's package path.** If the frame
    is under `site-packages/<pkg>` where `<pkg>` is neither
    `torch` nor `torch_spyre`, and steps 1–2 already ruled out
    substrate: `NOT_TORCH_SPYRE`.

If, after all ten steps, the failure still cannot be uniquely
categorized, keep the label `UNKNOWN`, record the ten step
outcomes in `03-results.md`, and STOP. Handing an `UNKNOWN` back
with the steps traversed is a legitimate deliverable — an
unclassified failure with a bogus torch-spyre patch on top is not.

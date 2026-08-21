# Validation ladder — torch-spyre forward-compat

Ordered gate sequence for evaluating whether a torch-spyre tree can
be built and driven against a candidate upstream PyTorch. Each stage
is a **gate**: the next stage runs only after the current one meets
its success criteria. Skipping a stage (or "running Stage 3 first
because it looks more informative") invalidates every downstream
result — a broken import can mask a broken lowering, and a broken
lowering can look like a scaling regression at Stage 6.

The ladder produces a single verdict per fresh pod:
`COMPATIBLE` / `INCOMPATIBLE` / `INSUFFICIENT_EVIDENCE`, with the
stage at which the ladder terminated and the smallest reproducer for
any failure. It is designed to fail as early and as cheaply as
possible — Stage 0 costs seconds, Stage 6 costs pod-hours.

Assume the fresh pod is:

- Pod name: `tdeshane-forward-compat-2026-08-21`
- Namespace: `a5-deepview`
- Base image (immutable digest recorded at pod-creation time):
  `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`
- Torch-spyre checkout: `a31289852145a59099edccc3e506cf5336e8e2e0`
  (short: `a3128985`)
- PyTorch checkout under evaluation:
  `73961011bf64f1c04b3291bf90ac1dbbe197c2ca` (short: `73961011`)

The torch pin torch-spyre declares in `pyproject.toml` at HEAD is
`torch~=2.13.0`. **Scripts must re-read the pin at runtime** from
`torch-spyre@<sha>:pyproject.toml` — never hard-code `2.13.0` in a
script — because the pin moves independently of this document.

## Stage 0 — ENVIRONMENT

### Purpose

Confirm that the base image on the fresh pod has a functioning
Python, the intended torch build, and torch-spyre can be imported
enough to enumerate the Spyre device. This is a **smoke check of the
runtime, not of the compiler.** If Stage 0 fails, no later stage can
be interpreted — a `torch_spyre` import error at Stage 3 is
indistinguishable from an ABI break at Stage 0.

### Prerequisites

None. Stage 0 is the entry point.

### Exact commands to run

```bash
# On the fresh pod, in the torch-spyre venv.
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      set -e
      cd $HOME/torch-spyre-work/torch-spyre
      source .venv/bin/activate
      python -c "import sys; print(sys.version)"
      python -c "import torch; print(torch.__version__, torch.__file__)"
      python -c "import torch_spyre; print(torch_spyre.__file__)"
    '
```

Then the device enumeration and a trivial eager op:

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/torch-spyre-work/torch-spyre/.venv/bin/activate
      python - <<PY
import torch, torch_spyre
n = torch.spyre.device_count()
print("spyre_device_count =", n)
assert n >= 1, "no spyre device visible"
x = torch.arange(8, device="spyre") + 1
y = x * 2
print("eager_op_ok =", (y.cpu() == torch.arange(2, 18, 2)).all().item())
PY
    '
```

### Success criteria

- `import torch` prints a version compatible with the torch-spyre
  pin at HEAD (read `torch~=` line from `pyproject.toml` at run
  time; the compatibility rule is PEP 440 `~=` — same major, minor
  ≥ pinned minor, `<` next major).
- `import torch_spyre` succeeds with no traceback.
- `torch.spyre.device_count()` is ≥ 1.
- The trivial eager `arange + 1; *2` on device produces the CPU
  reference tensor exactly.

### Fail-fast rules

- Any `ImportError`, `OSError` (typically the flex-ABI
  `undefined symbol` case in `_C.so`), or non-zero exit from the
  three-line invocation → **STOP** and record
  `INCOMPATIBLE` at Stage 0 with the raw traceback. Do not run
  Stage 1. Do not attempt to rebuild yet — first inspect whether
  the failure is a version mismatch (fixable by aligning
  torch/torch-spyre) or a genuine ABI break (the study's actual
  question).
- Device count == 0 → **STOP** and record `INSUFFICIENT_EVIDENCE`
  at Stage 0. Later stages will produce misleading failures without
  a device.

### What NOT to do at this stage

- Do NOT run `torch.compile` yet — that is Stage 2.
- Do NOT rebuild `_C.so` inside Stage 0. If the pre-built
  extension does not load against the candidate torch, that fact
  IS the Stage 0 result. Rebuilding masks the very question we
  are asking.
- Do NOT set `TORCH_LOGS=+dynamo`, `TORCH_SPYRE_DEBUG=1`, or any
  verbose env vars — an environment smoke should reflect the
  default runtime.
- Do NOT run a model or a workload.

## Stage 1 — BUILD / IMPORT

### Purpose

Confirm that torch-spyre's C extension can be built against the
candidate torch, that all primary compiler-side Python modules
import cleanly, and that the torch-spyre `torch.compile` entry-point
autoload registers without error. This is the last stage before we
ask the compiler to do anything.

### Prerequisites

- Stage 0 passed. In particular: `import torch_spyre` currently
  succeeds with the *shipped* `_C.so`. If Stage 0 failed on the
  shipped `_C.so`, that finding is the answer — do not attempt
  Stage 1.

### Exact commands to run

Rebuild the C extension in-tree against the candidate torch:

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      set -e
      cd $HOME/torch-spyre-work/torch-spyre
      source .venv/bin/activate
      # Re-read the pin at runtime — never hard-code the torch version.
      python - <<PY
import tomllib, pathlib
pin = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
deps = pin.get("project", {}).get("dependencies", [])
torch_pin = next((d for d in deps if d.split()[0].startswith("torch")), None)
print("declared_torch_pin =", torch_pin)
PY
      python setup.py build_ext --inplace 2>&1 | tail -60
    '
```

Then module-import walk and entry-point autoload check:

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/torch-spyre-work/torch-spyre/.venv/bin/activate
      python - <<PY
import importlib, sys

primary = [
    "torch_spyre",
    "torch_spyre._C",
    "torch_spyre._inductor",
    "torch_spyre._inductor.lowering",
    "torch_spyre._inductor.decompositions",
    "torch_spyre._inductor.propagate_layouts",
    "torch_spyre._inductor.propagate_hints",
    "torch_spyre._inductor.optimize_restickify",
    "torch_spyre._inductor.insert_restickify",
    "torch_spyre._inductor.fusion",
    "torch_spyre._inductor.scheduler",
    "torch_spyre._inductor.work_division",
    "torch_spyre._inductor.wsr.coarse_tile",
    "torch_spyre._inductor.wsr.coarse_tile_hints",
    "torch_spyre._inductor.wsr.propagate_named_dims",
    "torch_spyre._inductor.scratchpad.allocator",
    "torch_spyre._inductor.codegen.bundle",
    "torch_spyre._inductor.spyre_kernel",
    "torch_spyre._inductor.dedup_constants",
    "torch_spyre._inductor.enforce_indirect_access_layout",
    "torch_spyre._inductor.split_multi_ops",
    "torch_spyre._inductor.deadcode_elimination",
    "torch_spyre.execution.async_compile",
    "torch_spyre.runtime",
]
for m in primary:
    try:
        importlib.import_module(m)
        print("ok", m)
    except Exception as e:
        print("FAIL", m, type(e).__name__, e)
        sys.exit(1)

# Entry-point autoload: importing torch.compile plumbing must
# not raise even if no compile has happened yet.
import torch
import torch._dynamo  # noqa: F401
import torch._inductor  # noqa: F401
print("entry_point_autoload_ok = True")
PY
    '
```

### Success criteria

- `python setup.py build_ext --inplace` exits 0.
- The last 60 lines of build output contain no `error:` or
  `undefined reference to` markers.
- Every module in the `primary` list imports successfully — the
  script prints `ok <module>` for each and exits with 0.
- `entry_point_autoload_ok = True` is printed.

### Fail-fast rules

- Any build error (compiler error, linker error, missing torch
  headers) → **STOP** and record `INCOMPATIBLE` at Stage 1 with the
  build log. The failure surface is important — capture the exact
  compile command and the first non-warning diagnostic. Include
  which torch header the compiler could not find (or which symbol
  the linker could not resolve).
- Any `ImportError` on a module in the `primary` list → **STOP**.
  A single import failure invalidates all downstream stages: a
  broken `propagate_layouts` import will make Stage 3 look like a
  layout-propagation bug when it is actually a compat issue.
- Entry-point autoload raises → **STOP**. Record which torch API
  the autoload path exercises and the traceback.

### What NOT to do at this stage

- Do NOT edit torch-spyre source to work around a build error at
  this stage. If the build fails, the *finding* is that the tree
  does not build against the candidate torch. That is what we are
  measuring. Patch-and-continue destroys the signal.
- Do NOT run `torch.compile` yet. Successful imports do not imply
  successful compilation — a module can import and still have a
  runtime attribute error at `GraphLowering.run`.
- Do NOT run the test suite. That is Stage 6.
- Do NOT delete or move the pre-existing `_C.so` before recording
  its symbol table (`nm -D _C.so | head`) — if we need to
  understand *which* ABI symbol moved, we need the artifact.

## Stage 2 — MINIMAL COMPILE

### Purpose

Exercise the smallest possible path through the compiler on the
Spyre device: `torch.compile` a trivial function, run it, and verify
numerical parity against a CPU eager reference. This distinguishes
"the compiler can be entered" from "the compiler can produce a
correct kernel end-to-end". It is a bare-metal gate for Stage 3.

### Prerequisites

- Stage 0 passed (device visible, eager op correct).
- Stage 1 passed (fresh `_C.so`, all primary modules import).

### Exact commands to run

Three tiny compiles, each in a fresh Python process to avoid warm
cache. Each uses a unique `TORCHINDUCTOR_CACHE_DIR`.

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/torch-spyre-work/torch-spyre/.venv/bin/activate
      set -e
      for kind in add pointwise reduction; do
        cache=/tmp/torchind-fc-stage2-$kind-$$
        rm -rf "$cache"
        TORCHINDUCTOR_CACHE_DIR="$cache" python - <<PY
import torch, torch_spyre

kind = "'"$kind"'"

if kind == "add":
    def f(a, b): return a + b
    a = torch.randn(64, device="spyre"); b = torch.randn(64, device="spyre")
    args = (a, b)
elif kind == "pointwise":
    def f(a):    return torch.relu(a * 2.0 + 1.0)
    a = torch.randn(64, device="spyre")
    args = (a,)
else:  # reduction
    def f(a):    return a.sum(dim=-1)
    a = torch.randn(4, 64, device="spyre")
    args = (a,)

fc = torch.compile(f, backend="spyre")
out_dev = fc(*args).cpu()
out_cpu = f(*[x.cpu() for x in args])
ok = torch.allclose(out_dev, out_cpu, atol=1e-4, rtol=1e-4)
print(f"stage2_{kind}_ok = {ok}")
assert ok, (out_dev, out_cpu)
PY
      done
    '
```

### Success criteria

- Each of the three invocations prints `stage2_<kind>_ok = True`.
- No traceback, no fallback-to-eager warning that would indicate
  the Spyre backend refused the graph. Explicitly grep the output
  for `fallback` / `graph break` and record if seen — a silent
  graph break at Stage 2 means Stage 3 is measuring the wrong
  thing.
- Cache dir was fresh (`rm -rf` before use) — this is enforced by
  the driver but should be re-verified by reading
  `TORCHINDUCTOR_CACHE_DIR` back from the process log.

### Fail-fast rules

- Any traceback from `torch.compile` — **STOP**. Record the exact
  frame where the compiler raised (usually in `GraphLowering.run`
  or a pipeline pass). If the frame is inside torch (not
  torch-spyre), the failure is a torch API break; if inside
  torch-spyre, it is a compat issue.
- Numerical mismatch — **STOP**. Record `INCOMPATIBLE` at Stage 2
  with `out_dev` and `out_cpu` snippets. Do not paper over with a
  larger tolerance.
- Silent fallback to eager — **STOP**. A working eager pass is not
  a working compile pass and cannot be treated as one.

### What NOT to do at this stage

- Do NOT run any workload larger than the three trivial functions.
  Stage 2 is a gate, not a study — its device budget is seconds.
- Do NOT enable `TORCH_LOGS=+dynamo` or `TORCH_COMPILE_DEBUG=1`
  during the timed compile. If a diagnostic is needed to
  investigate a Stage 2 failure, run it separately and label the
  run "diagnostic".
- Do NOT profile. If Stage 2 succeeds, we care that it worked, not
  how fast it was.
- Do NOT proceed to Stage 3 if any of the three compiles crashed
  or fell back — Stage 3 will misattribute.

## Stage 3 — COMPILER-SURFACE SMOKES

### Purpose

Exercise each of the primary compiler substages on a small,
targeted input designed to reach that substage's code. This
distinguishes "the compiler works on toy add" from "the compiler
works on a graph that actually touches the passes torch-spyre
implements". Stage 3 is where forward-compat pain typically
surfaces — a torch API rename that Stage 2's trivial add does not
touch can break layout propagation.

### Prerequisites

- Stage 2 passed on all three trivial functions.

### Exact commands to run

Each smoke targets one substage. Run them serially, each in a fresh
process, each with its own cache dir. The script below drives them
from a list.

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/torch-spyre-work/torch-spyre/.venv/bin/activate
      set -e
      for smoke in lowering decomp graphlowering_run \
                   layout_propagation restickify \
                   wsr_coarse_tile work_division scratchpad \
                   bundle_sdsc wrapper_codegen; do
        cache=/tmp/torchind-fc-stage3-$smoke-$$
        rm -rf "$cache"
        TORCHINDUCTOR_CACHE_DIR="$cache" python \
          $HOME/torch-spyre-work/torch-spyre/tests/frontend_smoke/${smoke}_smoke.py \
          || { echo "STAGE3_FAIL $smoke"; exit 1; }
        echo "STAGE3_OK $smoke"
      done
    '
```

Each `<smoke>_smoke.py` is a **surgical** input: it constructs the
smallest graph that reaches the target substage and asserts the
substage ran (via a substage-level env-guarded counter or timing
hook), then compares against CPU. Concretely:

- `lowering_smoke.py`: an op whose lowering is Spyre-specific
  (e.g. a matmul with a specific layout hint), asserts
  `GraphLowering.run` ran and CPU compare.
- `decomp_smoke.py`: an op present in torch-spyre's
  `decompositions.py` table (e.g. a fused-attention-style op),
  asserts a decomp fired.
- `graphlowering_run_smoke.py`: a two-op graph, records
  `graphlowering_run` timing bucket, asserts > 0.
- `layout_propagation_smoke.py`: two matmuls sharing a tensor —
  drives `propagate_spyre_tensor_layouts` non-trivially.
- `restickify_smoke.py`: a graph with a candidate-generating op
  chain (e.g. a transpose feeding a matmul feeding a residual)
  that reaches `optimize_restickify_locations` with beam > 1.
- `wsr_coarse_tile_smoke.py`: n_chunks = 2 mini-workload that
  exercises `_maybe_coarse_tile_hints` without triggering the
  known O(n²)-adjacent scaling.
- `work_division_smoke.py`: a batched op that reaches
  `_distribute_work`.
- `scratchpad_smoke.py`: allocation-heavy tiny graph reaching
  `_maybe_scratchpad_planning`.
- `bundle_sdsc_smoke.py`: any compile that produces a bundle;
  asserts `sdsc_bundle_gen.meta.n_specs > 0`.
- `wrapper_codegen_smoke.py`: asserts the wrapper file was written
  under `TORCHINDUCTOR_CACHE_DIR`.

### Success criteria

- Every smoke prints its `STAGE3_OK <smoke>` line.
- Each smoke's substage-level assertion (counter > 0 or output
  present) passes — a "no crash" outcome is not sufficient because
  a smoke that skipped its target substage would pass a bare
  compile+run.
- CPU parity holds for every smoke that produces numerical output.

### Fail-fast rules

- **STOP at the first failing smoke.** Record which smoke, the
  traceback, and the substage the smoke was targeting. This is the
  most informative failure mode in the ladder because it names the
  affected substage directly.
- If a smoke passes but its substage-level counter shows the
  substage did not run, treat as `INSUFFICIENT_EVIDENCE` at
  Stage 3 for that substage — the smoke needs a stronger input.
  Do not silently continue past this.
- If more than one smoke fails, still stop at the first one;
  fixing the first often removes the second. Do not build a
  cumulative failure list at Stage 3.

### What NOT to do at this stage

- **Do NOT run the full test suite.** Stage 3 is targeted smokes.
  The test suite is Stage 6. Running `pytest torch_spyre/tests`
  here defeats the point of a graduated ladder — a passing suite
  hides the smallest reproducer, a failing suite drowns the signal.
- Do NOT enable `extra_timers` or the timing shim during Stage 3.
  Substage counters used for assertions are fine (they are
  cheap); full timing instrumentation adds ~5% overhead and its
  output distracts from the smoke's binary pass/fail.
- Do NOT run Stage 3 smokes in a shared Python process. Each must
  be fresh, each with its own cache dir.
- Do NOT scale up a smoke that revealed a failure. Stage 4 will
  minimize it, not enlarge it.

## Stage 4 — FOCUSED FAILURE-DRIVEN TESTING

### Purpose

For each break observed in Stages 0–3 (or later), find the smallest
reproducer that still exhibits the failure. The output of Stage 4
is a self-contained Python file, ≤ 40 lines, that reproduces the
failure on the fresh pod. This artifact is what upstream (torch or
torch-spyre) needs to act on the finding.

### Prerequisites

- At least one failure observed at Stage 0, 1, 2, or 3. If no
  failure has occurred, Stage 4 is a no-op and the ladder proceeds
  to Stage 5.

### Exact commands to run

Minimization is manual but bounded. For a failure observed at
`<smoke>`, start from that smoke's source and apply reductions in
this order:

1. Reduce tensor sizes to smallest that still fails (halve, then
   try 1).
2. Remove ops one at a time from the tail forward. After each
   removal, re-run and confirm the failure still reproduces.
3. Replace `torch.compile(f, backend="spyre")` with the direct
   `torch_spyre._inductor` entry point if that reproduces — this
   isolates whether dynamo or inductor triggers it.
4. If the failure is a traceback inside torch (not torch-spyre),
   attempt to reproduce on CPU by removing `.to("spyre")` — a
   torch-only reproducer routes the report to upstream torch.

Driver:

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/torch-spyre-work/torch-spyre/.venv/bin/activate
      set -e
      cache=/tmp/torchind-fc-stage4-min-$$
      rm -rf "$cache"
      TORCHINDUCTOR_CACHE_DIR="$cache" python \
        /tmp/repro_<smoke>.py 2>&1 | tee /tmp/repro_<smoke>.log
    '
```

The reproducer file lives at `/tmp/repro_<smoke>.py` on the pod and
should be copied out to the artifacts dir at the end of the ladder:

```bash
kubectl -n a5-deepview cp \
    tdeshane-forward-compat-2026-08-21:/tmp/repro_<smoke>.py \
    ./artifacts/repro_<smoke>.py
kubectl -n a5-deepview cp \
    tdeshane-forward-compat-2026-08-21:/tmp/repro_<smoke>.log \
    ./artifacts/repro_<smoke>.log
```

### Success criteria

- A single `.py` file ≤ 40 lines that reproduces the failure on a
  fresh pod, given only `pip install -e .` of torch-spyre at
  `a3128985` and the candidate torch at `73961011`.
- The reproducer prints the failure (traceback or numerical
  mismatch) deterministically on ≥ 3 successive runs (fresh
  process, fresh cache each time).
- The reproducer's traceback frame matches the frame from the
  original failure — verify with `diff -u` of the traceback tails.
  If frames differ, you have minimized to a *different* bug.

### Fail-fast rules

- If a reduction step makes the failure disappear, **revert that
  step** — you have crossed the bug's threshold, not minimized
  past it.
- If minimization stalls (5+ reduction steps with no change and
  the reproducer is still > 40 lines), record the current best
  reproducer and stop. Diminishing returns from further
  minimization are not worth the pod time.
- If the failure becomes non-deterministic during minimization
  (fails 2/3 runs), **STOP** and record that fact. A flaky
  reproducer is a different signal from a compat break and needs
  its own investigation; do not conflate.

### What NOT to do at this stage

- Do NOT enlarge the reproducer to "look more like a real
  workload". The reproducer's job is to be minimal, not
  representative.
- Do NOT attempt a fix. Stage 4 produces evidence; fixes belong to
  the followup PR against torch-spyre (or the upstream torch
  issue).
- Do NOT run more smokes from Stage 3 speculatively. Stay on the
  one failure.
- Do NOT skip the copy-out to artifacts. A reproducer that lives
  only on the pod is lost when the pod is deleted.

## Stage 5 — REGRESSION VERIFICATION

### Purpose

Once a Stage-4 reproducer exists and (if applicable) a fix has been
proposed, verify that:

1. The reproducer still fails at the pre-fix state.
2. It passes after the fix.
3. Neighbors of the affected substage still work.
4. A small cross-substage smoke, chosen from the compiler-stage
   map's near-linear "other passes" bucket, still works.

This guards against a fix that silences the reproducer while
breaking something adjacent.

### Prerequisites

- Stage 4 produced a reproducer.
- A proposed fix exists (either an upstream torch patch, a
  torch-spyre patch, or a documented version pin).

### Exact commands to run

Establish the pre-fix baseline (must still fail on a re-run):

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/torch-spyre-work/torch-spyre/.venv/bin/activate
      cache=/tmp/torchind-fc-stage5-pre-$$
      rm -rf "$cache"
      TORCHINDUCTOR_CACHE_DIR="$cache" \
        python /tmp/repro_<smoke>.py; echo "pre_fix_exit=$?"
    '
```

Apply the fix in an isolated checkout (never patch the primary
torch-spyre tree with an unmerged fix — use the
`setup_isolated_checkout.sh` pattern):

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      set -e
      cd $HOME/forward-compat-work
      git clone $HOME/torch-spyre-work/torch-spyre torch-spyre-fixed
      cd torch-spyre-fixed
      git checkout a31289852145a59099edccc3e506cf5336e8e2e0
      # Apply proposed patch:
      git apply /tmp/proposed-fix.patch
      python -m venv .venv
      source .venv/bin/activate
      pip install -e .
    '
```

Run the reproducer against the fixed tree and the neighbor smokes:

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/forward-compat-work/torch-spyre-fixed/.venv/bin/activate
      set -e
      cache=/tmp/torchind-fc-stage5-post-$$
      rm -rf "$cache"
      TORCHINDUCTOR_CACHE_DIR="$cache" \
        python /tmp/repro_<smoke>.py

      # Rerun the same-substage smoke plus its two nearest neighbors.
      # E.g. if the break was at layout_propagation, also run
      # decomp_smoke.py and restickify_smoke.py.
      for smoke in <affected> <neighbor1> <neighbor2>; do
        cache=/tmp/torchind-fc-stage5-$smoke-$$
        rm -rf "$cache"
        TORCHINDUCTOR_CACHE_DIR="$cache" \
          python $HOME/forward-compat-work/torch-spyre-fixed/tests/frontend_smoke/${smoke}_smoke.py
      done

      # Cross-substage smoke: run one small end-to-end that
      # exercises decomposition → lowering → layout_propagation →
      # scratchpad → bundle, none of which is the affected substage
      # if that is possible. This is defined in
      # tests/frontend_smoke/cross_substage_smoke.py.
      cache=/tmp/torchind-fc-stage5-cross-$$
      rm -rf "$cache"
      TORCHINDUCTOR_CACHE_DIR="$cache" \
        python $HOME/forward-compat-work/torch-spyre-fixed/tests/frontend_smoke/cross_substage_smoke.py
    '
```

### Success criteria

- `pre_fix_exit` is non-zero (the reproducer still reproduces
  pre-fix — the environment has not drifted).
- The reproducer passes post-fix.
- The affected-substage smoke and the two nearest neighbors all
  pass post-fix.
- The cross-substage smoke passes.

### Fail-fast rules

- `pre_fix_exit == 0` (reproducer no longer reproduces pre-fix) →
  **STOP** and mark `INSUFFICIENT_EVIDENCE` at Stage 5. The
  environment has drifted; the fix cannot be credited to the
  reproducer. Rebuild the reproducer against the current pod
  state before continuing.
- Reproducer fails post-fix → **STOP**. The fix does not close the
  issue. Record and return to Stage 4.
- Any neighbor smoke fails post-fix → **STOP**. The fix regressed
  an adjacent substage. Record which neighbor, and revisit the
  fix design.
- Cross-substage smoke fails post-fix → **STOP**. The fix moved
  something not local to the substage. Investigate before
  proceeding to Stage 6.

### What NOT to do at this stage

- Do NOT apply the fix in-place on the primary torch-spyre tree.
  Use an isolated checkout — the primary tree is the reference
  state and must remain untouched for the duration of the ladder.
- Do NOT rebuild `_C.so` by symlink from the primary tree if the
  fix touches `torch_spyre/csrc/**`. Rebuild from source in the
  isolated tree.
- Do NOT skip the pre-fix rerun. Skipping it means a post-fix
  pass could be an environment change, not the fix.
- Do NOT run the broader Inductor slices yet; that is Stage 6.

## Stage 6 — BROADER CONFIDENCE

### Purpose

Now that the failure is understood, minimized, and fixed (or
documented as an accepted incompatibility), run selected slices of
the Inductor test suite and the project's sentinel workloads to
gain confidence that the fix or the pin is not silently regressing
elsewhere. Stage 6 is the most expensive stage in the ladder — do
not run it unless Stages 0–5 have all resolved.

### Prerequisites

- Stage 5 passed (fix verified, neighbors clean, cross-substage
  clean). If the resolution is a documented incompatibility
  (`INCOMPATIBLE`, no fix), Stage 6 is not required — the ladder
  terminates at Stage 5's evidence.

### Exact commands to run

Run selected Inductor suite slices. The slices are the ones the
compiler-stage-map identifies as touching the affected substage and
its immediate consumers.

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/forward-compat-work/torch-spyre-fixed/.venv/bin/activate
      set -e
      cd $HOME/forward-compat-work/torch-spyre-fixed
      # Slice selection depends on the affected substage.
      # For a layout-propagation break, run at minimum:
      #   tests/inductor/test_layout_propagation.py
      #   tests/inductor/test_restickify.py
      #   tests/inductor/test_lowering.py
      # For a scratchpad break, run:
      #   tests/inductor/test_scratchpad.py
      #   tests/inductor/test_work_division.py
      pytest -x -q tests/inductor/test_<slice>.py 2>&1 | tail -100
    '
```

Then the existing sentinel workloads (workload A and workload B at
their smallest configured points — do not run the largest points
here, they are for the primary studies, not for a compat check):

```bash
kubectl -n a5-deepview exec tdeshane-forward-compat-2026-08-21 -- \
    bash -lc '
      source $HOME/forward-compat-work/torch-spyre-fixed/.venv/bin/activate
      set -e
      # Refer to sentinel-workloads.md in the frontend-compiler-impact
      # skill for the exact workload harness commands. Run at the
      # smallest configured point of each workload only.
      #   Workload A: smallest point (b=4)
      #   Workload B: smallest point (n=2)
      $HOME/forward-compat-work/torch-spyre-fixed/scripts/run_workload_a.sh --b 4 --n 1
      $HOME/forward-compat-work/torch-spyre-fixed/scripts/run_workload_b.sh --n 2 --samples 1
    '
```

### Success criteria

- Every selected Inductor slice passes (`pytest` exit 0).
- Both sentinel workloads compile end-to-end at their smallest
  point without traceback and produce output that agrees with the
  primary study's cached reference (bit-exact is not required;
  numerical agreement per that workload's declared tolerance is).
- No new warnings in the compile logs that reference torch API
  deprecation, autograd changes, or dynamo graph-break shifts —
  these often signal near-future compat problems.

### Fail-fast rules

- Any slice fails → **STOP** and record which test, which
  substage. The fix regressed something not caught in Stage 5
  neighbors; investigate before publishing.
- Either sentinel workload fails at its smallest point → **STOP**.
  A workload that succeeded pre-compat-work but fails post is a
  regression. Do not push the fix.
- A cascade of failures (> 3 tests failing in the same slice) →
  stop at the first one, minimize (Stage 4 loop again), do not
  chase the cascade.

### What NOT to do at this stage

- Do NOT run the largest configured points of the sentinel
  workloads. The compat check needs *presence* of a working
  compile at one size, not a scaling study.
- Do NOT run the entire torch-spyre test suite unless the failure
  history at Stages 3–5 justifies it. Selected slices per the
  compiler-stage-map are the intent.
- Do NOT bench-mark timing here. Stage 6 is a correctness
  confidence gate, not a performance measurement. Timing studies
  are the province of the frontend-compiler-impact skill.
- Do NOT report a Stage 6 pass as "torch-spyre is fully compatible
  with torch @ 73961011". Report only "sampled slices and smallest
  sentinel points pass; larger configurations not tested".

## How to abort the ladder

An explicit checklist for when to stop and escalate versus when to
push through. Aborting is a valid outcome — the ladder's job is to
produce a truthful verdict, not a green tick.

### Stop immediately and escalate

- **Any Stage 0 failure.** The runtime cannot be characterized;
  every downstream signal is untrustworthy.
- **A C-extension build error at Stage 1** with an `undefined
  symbol` referencing a torch symbol. This is the canonical
  forward-compat break and is the most informative one to report.
- **A traceback whose frame is inside `torch/**` (not
  `torch_spyre/**`)** at any stage from 2 onwards. The bug is
  upstream; the report belongs on the torch tracker with the
  Stage 4 reproducer.
- **A silent fallback to eager at Stage 2 or 3.** Silent
  fallbacks corrupt every later interpretation.
- **A non-deterministic reproducer at Stage 4.** Flakiness is a
  distinct investigation; do not fold it into the compat report.
- **Pre-fix rerun passes at Stage 5.** The environment has
  drifted; nothing after this point is credited correctly.

### Continue with a documented caveat

- **A Stage 3 smoke that passes but whose substage-level counter
  shows the substage did not run.** Record as
  `INSUFFICIENT_EVIDENCE` for that substage; continue with the
  other smokes. The correct fix is a stronger smoke, but that is
  a followup, not a blocker.
- **A Stage 6 pytest slice that fails on a test flagged as
  pre-existing xfail** for a reason unrelated to the compat
  question. Note the xfail's issue link and continue.
- **A Stage 6 sentinel workload emits a new deprecation warning
  but still succeeds.** Log the warning verbatim in the artifacts;
  it is a near-future risk, not a current failure.

### Never do this on abort

- Do NOT retry a failing stage by widening its tolerance or
  loosening its assertion.
- Do NOT skip forward. "Stage 3 is failing so let me try Stage 6
  instead" produces an unattributable pass.
- Do NOT delete the pod on abort. The failing artifacts are the
  point. Copy them out first (`kubectl cp` from `/tmp/repro_*.py`
  and `/tmp/*.log`).
- Do NOT edit CLAUDE.md, the skill directory, or the
  pyproject.toml pin in response to a failure — the failure is
  the finding.

### Final verdict rubric

The ladder writes one of three verdicts to
`artifacts/verdict.json` on exit:

- `COMPATIBLE` — Stages 0–6 all passed (or Stages 0–5 passed and
  Stage 6 was scoped to the affected substage's slices and
  smallest sentinel points).
- `INCOMPATIBLE` — a stage failed with a Stage 4 reproducer in
  hand and either no fix or a fix that Stage 5 rejects. The
  reproducer file and traceback are the artifact.
- `INSUFFICIENT_EVIDENCE` — a stage failed in a way the ladder
  cannot resolve (drift, flakiness, missing device). Record what
  is missing and what the next run would need.

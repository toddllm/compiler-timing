# Pre-DXP frontend harness — epic #4117

Runs the normal cold-compile path through backend-input generation and
stops immediately before `subprocess.run(["dxp_standalone", ...])` in
`torch_spyre/execution/async_compile.py`. Everything upstream of that
call — Dynamo, AOTAutograd, Inductor lowering, all six `Custom*Passes`
pipelines, the `Scheduler`, `SpyrePythonWrapperCodegen`,
`generate_bundle`, `build_kernel_provenance_descriptor` — runs
unmodified.

## Files

- `pre_dxp_stop.py` — main entry point. Loads `torch_spyre`, builds a
  workload (flash-attention closure or a small MLP stack), patches
  `torch_spyre.execution.async_compile.subprocess.run` with a stub
  that raises `_PreDxpBoundary`, then invokes `torch.compile(fn)` and
  catches the sentinel. Writes hierarchical timing to `--out`.
- `check_bundle_fidelity.py` — pairs a normal-compile run against a
  pre-DXP-stop run at one baseline point (default Lq=512, Lk=1024)
  and diffs the `inductor-spyre/<digest>_<kernel>_*/` bundle
  contents. Passes when no files exist only in the stop run and every
  common file is byte-identical.

## Interception mechanism

`pre_dxp_stop._install_pre_dxp_stop()` replaces
`torch_spyre.execution.async_compile.subprocess.run` with a wrapper
that:

1. inspects the command; if it is not `["dxp_standalone", ...]` it
   delegates to the original `run` (safety valve, though this module
   currently only calls `subprocess.run` for DXP).
2. emits a `pre_dxp_boundary_marker` event into the timing recorder so
   the boundary has a queryable ordinal in the JSON.
3. raises `_PreDxpBoundary(args, kwargs)` — the outer harness catches
   it, walking `__cause__`/`__context__` since Dynamo may wrap the
   exception in `InductorError`.

The sentinel carries the captured `(args, kwargs)` so we can prove the
compile actually reached the DXP call site (as opposed to bailing
earlier for some other reason).

Everything after `subprocess.run` in a normal compile —
`SpyreSDSCKernelRunner`, kernel-load, the first-call return — does not
run. The harness is analysis-only; do not attempt to use its results
for correctness testing.

## Environment

| Variable | Required | Purpose |
|---|---|---|
| `TORCHINDUCTOR_CACHE_DIR` | Yes | Fresh dir per cold-compile sample. `check_bundle_fidelity.py` sets this per run. |
| `TORCH_SPYRE_TIMING` | Yes | `=1` — required for the timing recorder to attach. |
| `SPYRE_TIMING_OUT` | Yes | Path for the JSON timing dump (harness also writes to `--out`). |
| `SENCORES` | Optional | Number of Spyre cores. Recorded in the timing meta. |

## Usage

Single pre-DXP-stop run:

```bash
TORCHINDUCTOR_CACHE_DIR=/tmp/tsc-cache-$RANDOM \
TORCH_SPYRE_TIMING=1 \
SPYRE_TIMING_OUT=$PWD/out.json \
python3 harness/pre_dxp_stop.py \
    --workload flash --Lq 512 --Lk 1024 \
    --out $PWD/out.json
```

Baseline fidelity check (runs the workload twice, once with DXP, once
without, then diffs bundles):

```bash
python3 harness/check_bundle_fidelity.py \
    --out-dir $PWD/../data/fidelity_check
```

Exit codes for `check_bundle_fidelity.py`:

- `0` — bundle contents identical up to DXP output artifacts
- `2` — argparse / environment
- `3` — one of the compile runs produced no bundle directory
- `4` — files only appear in the pre-DXP stop run, or a common file
  diverged in size / SHA-256

## Cold-compile protocol

Every sample uses a fresh `TORCHINDUCTOR_CACHE_DIR`. `torch.manual_seed`
is pinned so tensor content is stable across runs. The workload
factory places all tensors on `spyre` before `torch.compile` is
called, so `first_call_wall` measures only compilation and does not
double-count device transfers.

Take three cold samples, report the median, per the study protocol in
`analyses/2026-08-pr3806-frontend-timing/`.

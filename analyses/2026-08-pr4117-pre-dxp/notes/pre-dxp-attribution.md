# Pre-DXP time attribution — how to read + how to produce

**Status: awaiting pod data.** This file will be overwritten with a
table by `harness/analyze_sweep.py` once `data/sweep/` is populated.
The framing below stays as a docstring in the analyzer's output
paragraph so future readers see it.

## What the table shows

`pre_dxp_total` = `first_call_wall − dxp_standalone`.

Every row is one workload-shape (e.g. `flash-512x1024`). Every column
is a bucket that Phase 3 instrumentation brackets. All values are
median-of-N cold samples, in milliseconds.

## Bucket definitions

| bucket | what it measures | source of the bracket |
|---|---|---|
| `dynamo_aot_prelude` | Dynamo + AOTAutograd time upstream of Torch-Spyre's `compile_fx_wrapper` | derived: `first_call_wall − compile_fx_wrapper − dxp_standalone − async_compile_wait` |
| `graphlowering_run` | Upstream Inductor `GraphLowering.run` (FX → IR lowering) | `extra_timers.install_extra_timers` |
| `custompresched` | Torch-Spyre's 22-pass `CustomPreSchedulingPasses` pipeline | `pipeline:CustomPreSchedulingPasses` in the instrumentation patch |
| `scheduler_and_node` | Scheduler ctor + `CustomPreFusionPasses` + upstream fusion + `CustomPostFusionPasses`, derived | `graphlowering_compile_to_fn − sdsc_total − spyre_kernel_codegen − custompresched` |
| `spyre_kernel_codegen` | `SpyreKernel.codegen_kernel` calls (per emitted kernel) | `extra_timers.install_extra_timers` |
| `sdsc_bundle_gen` | `generate_bundle` inside `SpyreAsyncCompile.sdsc` | direct `_tr.stage` around the call |
| `kernel_provenance` | `build_kernel_provenance_descriptor` | direct `_tr.stage` |
| `async_compile_wait` | `SpyreAsyncCompile.wait` (excludes sdsc, which is called before wait) | direct `_tr.stage` |
| `unattributed_wrapper` | anything inside `compile_fx_wrapper` no other bucket accounts for | derived |

`dxp_standalone` is included as a column for reference but is **not
part of `pre_dxp_total`**. This investigation stops at the DXP
subprocess boundary by definition.

## How to read it

1. Look at `pre_dxp_total` at the largest flash shape to know the
   headroom this investigation can address.
2. Look at the **percent-of-pre-DXP** section for the same shape to
   see the share each bucket owns. Anything below 5% is small even
   perfectly eliminated.
3. Cross-reference with `tables/scaling.md` — a bucket with a large
   share and a super-linear slope is the strongest candidate.
4. For `custompresched`, drill into `tables/pass-detail.md` to see
   which passes drive the pipeline's share.

## How to run it

On an instrumented pod:

```bash
# One-time setup: apply the instrumentation patch to a torch-spyre checkout.
export TORCH_SPYRE_REPO=$HOME/pr4117/torch-spyre
bash patches/apply_instrumentation.sh

# Runtime env for every sample.
export TORCH_SPYRE_TIMING=1

# Sweep (writes to data/sweep/):
bash harness/sweep_driver.sh

# Analyze the sweep into notes + tables:
python3 harness/analyze_sweep.py \
    --sweep-dir data/sweep \
    --out-notes notes \
    --out-tables notes/tables
```

Analyzer overwrites this file with the real attribution table.

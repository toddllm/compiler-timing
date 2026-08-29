# Pre-DXP frontend investigation — summary

**Epic:** torch-spyre #4117 — investigate remaining pre-DXP compile
time outside `CustomPreSchedulingPasses`.

**Scope:** cold `torch.compile()` path through generation of backend
input, stopping immediately before `subprocess.run(["dxp_standalone",
...])` in `torch_spyre/execution/async_compile.py:155`. DXP itself is
out of scope.

## Question

> Once known pass-level costs are accounted for, where does the rest
> of pre-DXP compile time go, how does each bucket scale with graph
> size, and which remaining bucket is the next material optimization
> target?

## What we built

- **Stage map** (`notes/pre-dxp-stage-map.md`) — every source-level
  stage between `torch.compile()` and `dxp_standalone`, with
  file:line citations against upstream `3855d11`.
- **Frontend-only harness** (`harness/pre_dxp_stop.py`) — cold
  compile driver that patches `subprocess.run` inside
  `SpyreAsyncCompile.sdsc` with a sentinel raise, stopping the compile
  after `generate_bundle` and `build_kernel_provenance_descriptor`
  but before `dxp_standalone`. Flash-attention and MLP workloads.
- **Bundle fidelity check** (`harness/check_bundle_fidelity.py`) — at
  one baseline point, runs the workload twice (normal + stop) and
  proves the bundle files are byte-identical up to DXP output.
- **Hierarchical instrumentation** (`patches/instrumentation.patch`,
  `patches/timing_recorder.py`, `patches/extra_timers.py`) — brackets
  `compile_fx_wrapper`, `graphlowering_run`,
  `graphlowering_compile_to_fn`, `pipeline:CustomPre*Passes` (all
  six), every pass inside `CustomPreSchedulingPasses`,
  `spyre_kernel_codegen`, `sdsc_total`, `sdsc_bundle_gen`,
  `kernel_provenance`, `dxp_standalone`, `async_compile_wait`. Writes
  a hierarchical JSON per sample.
- **Sweep driver** (`harness/sweep_driver.sh`) — nine flash-attn
  points and five MLP points, three cold samples each, serial (Spyre
  is exclusive per process).
- **Analyzer** (`harness/analyze_sweep.py`) — reads the sweep,
  produces `notes/pre-dxp-attribution.md` (bucket shares at every
  shape) and `notes/tables/{scaling.md,pass-detail.md}` (log-log
  slopes vs `fx_nodes_at_entry` and top-K passes per shape).

## What runs where

Everything above is authored on the laptop under
`/Users/tdeshane/toddllm/compiler-timing/analyses/2026-08-pr4117-pre-dxp/`.
Nothing has to be upstreamed into torch-spyre for this analysis; the
instrumentation patch and vendored recorder/extra_timers install into
an editable torch-spyre checkout on a pod for the duration of the
sweep, then get reverted.

Fidelity check + sweep + analyzer are the three things that need pod
execution. All three are ready to run — see the instructions at the
bottom of `notes/pre-dxp-attribution.md`.

## Findings

*(To be filled in from real data — the analyzer produces the tables
this section should cite.)*

Read the ranked list at the bottom of `notes/next-opportunities.md`
for the "which bucket next?" call, and `notes/pre-dxp-attribution.md`
for the underlying share/scaling numbers.

## Comparability to PR #3806

- Same flash-attention workload closure (parameters
  `B=1, H=8, D=128, b_block=1, h_block=4, q_block=256, kv_block=512`).
- Same cold-compile protocol: fresh `TORCHINDUCTOR_CACHE_DIR` per
  sample, three cold samples, median.
- Same `timing_recorder` — schema version 1, `perf_counter_ns` clock.
- Same nine flash-attention (Lq, Lk) points as the prior sweep, plus
  five MLP points added for a non-flash structural comparison.

A pre-#4113 baseline for `dedup_and_promote_constants` is not
re-created here; the analyzer's `tables/pass-detail.md` will confirm
whether it dropped out of the top-K as the fix intended.

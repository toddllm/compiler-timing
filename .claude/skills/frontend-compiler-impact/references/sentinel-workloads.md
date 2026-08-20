# Sentinel workload registry

The skill selects from this registry based on the static-triage
tags. **Do not run every workload for every PR.** Each entry
names the mechanisms it exercises so the selector can match.

All commands assume the pod-side layout established by the primary
study: harness in `$HOME/pr3806/workload_harness.py` (workload A)
and `$HOME/pr3806/workload_harness_kvchunk.py` (workload B),
timing recorder in
`$HOME/pr3806/torch-spyre/torch_spyre/_inductor/timing_recorder.py`,
`compile_fx_wrapper` instrumentation in the pod-side `_inductor/`
tree.

Each timed sample uses:

```
export TORCH_SPYRE_TIMING=1
export TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor_<point>_r<sample>
rm -rf $TORCHINDUCTOR_CACHE_DIR
python <harness> <args> --out <OUT>
```

---

## `WA_baseline` — workload A, `Lq=512, Lk=1024, H=8`

- **Mechanisms exercised**: dedup (`ops×dups`), scratchpad
  (moderate live-range), generic FX-node growth, layout propagation,
  restickify at moderate size, coarse-tile hints only if
  `spyre_hint` is used (default: not exercised).
- **Command**:
  ```
  python $HOME/pr3806/workload_harness.py --Lq 512 --Lk 1024 --out $OUT
  ```
- **Expected wall time**: ~90–100 s per cold sample.
- **Device required**: yes.
- **Correctness oracle**: `--compare-cpu` (runs
  `torch.testing.assert_close(atol=0.1, rtol=0.1)` outside timed
  region).
- **Key metrics**: `compile_fx_wrapper`, `pipeline:CustomPreSchedulingPasses`,
  each top-6 pass. Structural: `fx_nodes_at_entry`, `n_specs`.
- **Known limitations**: does not exercise WSR coarse tiling; if
  the PR touches WSR-only code paths this sentinel is silent.

## `WA_scaling_pair` — workload A, base `Lq=512, Lk=1024` and `Lq=512, Lk=2048`

- **Purpose**: measure growth ratio for a change that may affect
  scaling. Cheaper than the 4096/8192 points.
- **Commands**:
  ```
  python $HOME/pr3806/workload_harness.py --Lq 512 --Lk 1024 --out $OUT
  python $HOME/pr3806/workload_harness.py --Lq 512 --Lk 2048 --out $OUT
  ```
- **Expected wall time**: ~90 s + ~220 s = ~310 s per (base,head)
  pair × sample.
- **Growth ratio**: `t(Lk=2048) / t(Lk=1024)` — expect ~2.2× for
  compile_fx, ~2.5× for dedup, ~1.8× for layout_prop from the
  primary study.

## `WA_large` — workload A, `Lq=512, Lk=4096` or `Lq=512, Lk=8192`

- **Purpose**: superlinear scratchpad territory; also stresses
  dedup and restickify at large graph sizes.
- **Commands**:
  ```
  python $HOME/pr3806/workload_harness.py --Lq 512 --Lk 4096 --out $OUT   # ~570 s
  python $HOME/pr3806/workload_harness.py --Lq 512 --Lk 8192 --out $OUT   # ~2380 s
  ```
- **Use only for Level 3** where scratchpad or large-graph
  mechanisms are the specific target. 8192 point burns 40 min per
  sample.

## `WB_n4` — workload B, `n_chunks=4`

- **Mechanisms exercised**: `_maybe_coarse_tile_hints`, restickify
  beam (post-fix constant-fill layout), dedup under richer
  inner_fn, WSR H tiling.
- **Command**:
  ```
  python $HOME/pr3806/workload_harness_kvchunk.py \
    --B 1 --H 8 --D 128 --Lq 256 --Lk 4096 --kv-block 1024 \
    --h-tiles 4 --lq-tiles 0 --out $OUT
  ```
- **Expected wall time**: ~55–60 s per cold sample.
- **Layout state**: post-fix required (`toggle_layout_fix.sh post`);
  pre-fix crashes at n=8.
- **Key metrics**: `_maybe_coarse_tile_hints` (~4.1 s baseline),
  `optimize_restickify_locations` (~1.0 s), `dedup_and_promote_constants`
  (~0.65 s).

## `WB_scaling_pair` — workload B, `n_chunks=4` and `n_chunks=8`

- **Purpose**: growth-ratio comparison. The pair that revealed the
  coarse-tile-hints 3.52× → 2.80× shift under the reverse-adjacency
  prototype.
- **Commands**: as `WB_n4`, plus `--kv-block 512` for `n_chunks=8`.
- **Wall time**: ~60 s + ~125 s per sample pair.
- **Growth ratio**: `t(n=8) / t(n=4)` — baseline post-fix is 3.52×
  for `_maybe_coarse_tile_hints`, 2.19× for restickify, 3.74× for
  dedup, 1.93× for scratchpad.

## `WB_n8` — workload B, `n_chunks=8` alone

- **Purpose**: single-point check when the change is expected
  visible at n=8 but not n=4 (e.g. a mechanism that only bites
  above a threshold).
- **Wall time**: ~125 s per sample.

## `WB_n16` — workload B, `n_chunks=16` alone

- **Purpose**: stress point where `_maybe_coarse_tile_hints` = 53 s.
- **Wall time**: ~330 s per sample. Level 3 only.

## `PR_local` — the PR's own regression test / minimal reproducer

- **Purpose**: when neither WA nor WB exercises the changed path.
  Extract the smallest reproducer from the PR's added test or the
  minimal example in its description.
- **Wall time**: PR-specific.
- **Correctness**: comparing PR test output at head is often the
  correctness oracle already.

## Frontend-setup sentinel

For changes to `_inductor/__init__.py`, `patches.py`, decomposition
setup, `decompositions.py`, or `get_spyre_decomp_table`:

Use `WA_baseline` first. This is the cheapest sentinel that
exercises the full setup path. If the change is expected to affect
only decomposition registration (visible in `GraphLowering.run` or
in the 6–11 s upstream/setup component), the extra_timers hook must
be enabled — see
`analyses/2026-08-frontend-scaling-cross-workload/patches/extra_timers_v2.py`
and `patches/extra_timers_hook.py`.

## Selecting sentinels — cheatsheet

| Change touches | Primary sentinel | Optional |
|---|---|---|
| dedup / propagate_layouts (linear) | WA_baseline | WB_n4 for cross-workload confirmation |
| coarse_tile / coarse_tile_hints / plan_tiling_propagation | WB_scaling_pair | — |
| optimize_restickify (beam) | WB_n4 or WB_n8 | pre-fix repro if candidate-set change |
| scratchpad / allocator | WA_baseline (linear regime) or WA_large (superlinear) | not WB (already linear) |
| spyre_kernel / lowering / decompositions | WA_baseline with extra_timers | — |
| C-extension (csrc/) | WA_baseline + rebuild both revisions | — |
| async_compile / sdsc / dxp path | WA_baseline; classify as backend if only backend changed | — |
| tests-only / docs / CI | Level 0 (no run) | — |

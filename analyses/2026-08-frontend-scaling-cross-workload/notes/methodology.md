# Methodology — cross-workload measurements

## Environment
- torch-spyre HEAD `a9316b3` (pr3806 base, main snapshot).
- torch 2.13.0+cpu, Python 3.12, single Spyre PF device.
- `SENCORES=32`. All measurements at default compiler config unless
  explicitly toggled.

## Toggling pre-fix / post-fix state

The PR #3812 code change reduces to one line:

- Pre-fix: `torch_spyre/_inductor/propagate_layouts.py:1910` reads
  `op.layouts = _all_constant_layouts(op)`.
- Post-fix: same line reads `op.layouts = [generic_layout(op)]`.

`patches/toggle_layout_fix.sh {pre|post|status}` performs a sed-based
in-place swap. Idempotent, both directions.

## Instrumentation additions

Three patches enable finer-grained recording:

- `patches/coarse_tile_substage_timing.py` — adds `_tr.stage` wraps
  around 10 substages inside `_coarse_tile_common`
  (`wsr/coarse_tile.py`), enabling 100% attribution of the umbrella
  `pass:_maybe_coarse_tile_hints` event. `apply` and `revert` idempotent.
- `patches/restickify_beam_counters.py` — adds beam-frontier counters
  per-op in `beam_global_min_cost` (`optimize_restickify.py`). Emits a
  single `restickify_beam_trace` event whose meta carries max_*
  summary counters plus per-op trace_head/trace_tail arrays.
- The primary study's `patches/instrumentation.patch` +
  `patches/timing_recorder.py` provide the pipeline / pass /
  `compile_fx_wrapper` timing already used.

Instrumentation overhead measured at n_chunks=4: instrumented compile
takes ~5% longer than baseline (63 s vs 60 s). Acceptable for
decomposition runs; toggled off for primary timing runs.

## Workload harness

`patches/workload_harness_kvchunk.py` reproduces PR #3812's
`_run_kv_chunked_flash` closure verbatim, including all four
load-bearing details from the PR's test docstring:

1. K loop inside a single H/Lq scope (avoids `validate_coarse_tile_groups`
   "hint_id in both group X and Y" errors).
2. K/V chunks sliced by the caller and passed as named tensors.
3. Carry inits use the `torch.full((B,H,Lq,64), val).amax(-1)` sparse
   idiom (a plain 3-D `full` raises "no mechanism to resolve stick
   incompatibility").
4. Final divide inside the innermost scope.

`compare-cpu` flag runs `torch.testing.assert_close(atol=0.01, rtol=0.1)`
against a CPU reference, outside the timed region.

## Cold-compile hygiene

Same rules as the PR #3806 study:

- Fresh Python process per sample.
- Fresh `TORCHINDUCTOR_CACHE_DIR` per sample. Each driver `rm -rf`s
  the exact path before use.
- No `TORCH_COMPILE_DEBUG` / `TORCH_LOGS` / verbose logs during
  timing runs.
- Diagnostic (cProfile, log-level tests) runs are separate from
  timing runs.
- Spyre runs strictly serially — device is exclusive per process.

## Cache-path scheme per dataset

- `data/workload-B-pre-fix/`  and  `data/workload-B-post-fix/`:
  `/tmp/torchinductor_kvchunk_kv{kv_block}_r{i}`
- `data/workload-B-post-instr-v3/`:
  `/tmp/torchinductor_kvchunk_kv{kv_block}_r{i}_postinstrv3`
- `data/workload-B-beam-trace-{pre,post}fix/`:
  `/tmp/torchinductor_{pre,post}fix_kv{kv_block}_$$`
- `data/workload-B-lq-sweep/`:
  `/tmp/torchinductor_lqsweep_lq{Lq}_r{i}`
- `data/workload-B-lq-tiled-sweep/`:
  `/tmp/torchinductor_lqtiled_lq{Lq}_t{lq_tiles}_r{i}`
- `data/workload-B-lk-sweep/`:
  `/tmp/torchinductor_lksweep_lk{Lk}`

The exact string is preserved in each JSON's `meta.TORCHINDUCTOR_CACHE_DIR`
and any backend `output_dir` fields.

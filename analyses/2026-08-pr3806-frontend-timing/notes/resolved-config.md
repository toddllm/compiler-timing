# Resolved compiler configuration

`data/env-probe.json` records the values of the env vars that
`torch_spyre._inductor.config` reads at import. Most of those knobs
have non-trivial defaults, so recording env-var absence is not enough
to describe what the compiler actually did; the resolved settings
after config initialization are what matter.

`data/resolved-config.json` is the output of
`torch_spyre._inductor.config.get_config_copy()` taken on the same
system the sweep executed on. Every JSON under `data/` was produced
with these settings.

## Non-default and workload-relevant knobs

| knob | env var read | env var value | resolved value | effect if changed |
|---|---|---|---|---|
| `sencores` | `SENCORES` | unset | **32** | `_distribute_work` and `_maybe_scratchpad_planning` depend on core count. |
| `lx_planning` | `LX_PLANNING` | unset | **True** | With `LX_PLANNING=0`, `_maybe_scratchpad_planning` becomes a no-op. That pass is 1.0 s at baseline and 74.0 s at 128 inner bodies. |
| `global_stick_optimizer` | `GLOBAL_STICK_OPTIMIZER` | unset | **True** | Affects the stickify path in `propagate_spyre_tensor_layouts`. |
| `hbm_pool_planning` | `HBM_POOL_PLANNING` | unset | **True** | Enables `hbm_pool_planning` inside `CustomPostFusionPasses`. |
| `ignore_wsr_hints` | — | — | False | Working-set-reduction hint passes are active. |
| `ignore_span_overflow_hints` | — | — | **True** | `_maybe_coarse_tile_span_overflow` returns early; the ~0 time reported for that pass reflects the early return, not the absence of work. |
| `cost_model` | — | — | `""` | `cost_model_pass` and `dump_cost_model` are inert. |
| `log_passes` | — | — | `""` | Per-pass DEBUG dumps disabled (heavyweight diagnostics were intentionally off during timing runs). |
| `bundle_symbolic_args` | `BUNDLE_SYMBOLIC_ARGS` | 1 | True | SDSC path (the one exercised here); the alternative KTIR path requires this to be 0. |
| `ktir_emitter` | `TORCH_SPYRE_KTIR` | unset | False | Compilation goes through the SDSC path, not KTIR. |

## Notes

- The measured 74.0 s at 128 inner bodies for `_maybe_scratchpad_planning`
  exists only because `lx_planning=True`. It would evaporate under
  `LX_PLANNING=0`.
- `_maybe_coarse_tile_span_overflow` shows near-zero time because
  `ignore_span_overflow_hints=True` returns before the pass does any
  work. A future run with that flag flipped would introduce
  measurable time for that pass.
- `cost_model_pass` and `dump_cost_model` run outside the timed pass
  loop and are inert; they would add wall time without changing the
  compiled program.

## Comparing future measurements

To compare a fix to a specific pass — for example, a rewrite of
`dedup_and_promote_constants` — future runs should either keep the
settings in `data/resolved-config.json` identical or explicitly note
any change.

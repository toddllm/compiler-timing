# Pre-DXP time attribution — methodology + how to produce

**Status: awaiting pod data.** This file will be overwritten with a
median-of-N table by `harness/analyze_sweep.py` once `data/sweep/` is
populated. The methodology below stays as a docstring in the
analyzer's output header so readers of the produced table always see
the framing.

## Primary pre-DXP total

Derived directly from timestamps:

    pre_dxp_total_ns = pre_dxp_boundary_marker.t_start_ns
                       - first_call_wall.t_start_ns

This is exactly "from first invocation start to the moment
immediately before the DXP subprocess would have run". The
`first_call_wall` event's `inclusive_ns` also includes a sentinel
unwind, which is reported separately as `sentinel_unwind` and
excluded from the primary total.

## Top-level bucket definitions

Every bucket in the "attribution" section of the produced table is
directly bracketed or derived from timestamps between direct events —
none from `parent.inclusive − sum(children)` unless every subtracted
child is also directly bracketed.

| bucket | source |
|---|---|
| `pre_compile_fx` | `compile_fx_wrapper.t_start − first_call_wall.t_start`. Time before Torch-Spyre's compile_fx wrapper fires — Dynamo tracing, AOTAutograd prelude, torch bookkeeping. |
| `compile_fx_wrapper` | direct inclusive |
| `between_compile_and_wait` | `async_compile_wait.t_start − compile_fx_wrapper.t_end`. Setup between compile completion and first-invocation start. |
| `wait_pre_dxp` | `pre_dxp_boundary_marker.t_start − async_compile_wait.t_start`. Everything inside async_compile_wait upstream of the boundary (sdsc, generate_bundle, kernel_provenance, prefix of the dxp subprocess call). |

Their sum equals `pre_dxp_total` when reconciliation residual is 0.
`tables/reconciliation.md` reports the residual for every sample.

## Full bucket detail

The full attribution table also breaks each top-level bucket into
directly-measured sub-buckets so a reader can drill from
"compile_fx_wrapper is 87% of pre-DXP time" all the way down to
"insert_restickify is 12% of compile_fx_wrapper" without any
subtractive arithmetic — every number is either a direct event
inclusive time or a timestamp difference between direct events.

## Non-obvious accounting rules

- **SDSC is NOT nested in `compile_fx_wrapper` or
  `graphlowering_compile_to_fn`.** SDSC (and DXP) fires during the
  first invocation of the compiled wrapper — i.e. INSIDE
  `async_compile_wait`, which is a SIBLING of `compile_fx_wrapper`
  under `first_call_wall`. The analyzer does not subtract SDSC from
  either of those parents.
- **`CustomPreSchedulingPasses.__call__`** runs `cost_model_pass`,
  `dump_cost_model`, and `finalize_work_division_for_scheduler`
  AFTER the 23-pass loop but BEFORE the pipeline event closes. The
  pipeline event brackets all of them; nested sub-events isolate the
  four regions.
- **`recover_spyre_hints`** runs inside `_spyre_update_scheduler`
  but OUTSIDE `pipeline:CustomPreSchedulingPasses`. Its own timer
  captures it.
- **`_pre_fusion_custom_pass` and `_post_fusion_custom_pass`** fire
  from inside `Scheduler.__init__`, not `CustomPreSchedulingPasses`.
  They appear as their own pipeline events.

## How to produce the real table

On an instrumented pod at the frozen SHA:

```bash
export TORCH_SPYRE_TIMING=1
bash harness/sweep_driver.sh
python3 harness/analyze_sweep.py \
    --sweep-dir data/sweep \
    --out-notes notes \
    --out-tables notes/tables \
    --strict
```

`--strict` makes the analyzer exit non-zero if any run failed
validation, so a sweep with a subtle bug does not silently produce a
table that trusts partial data.

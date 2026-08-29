# Solver A/B — post-pilot diagnostic (frozen torch-spyre 3358f39)

Purpose: determine whether the ~O(n^1.4) `_maybe_scratchpad_planning`
cost seen in the five-point pilot is a scratchpad-pipeline regression
or the current-main default of `LAYOUT_SOLVER=cpsat`. Will's earlier
`faff191` measurements ran under `LAYOUT_SOLVER=greedy` (the
`faff191`-era default). All other LX/co-opt/relayout/sencores knobs
were already matching Will's on frozen 3358f39.

## Resolved runtime config (both arms)

Recorded directly from `torch_spyre._inductor.config` at run time:

| key | value |
|---|---|
| layout_solver | **variable** (`cpsat` vs `greedy`) |
| co_optimizing_lx_planning | False |
| lx_planning | True |
| lx_planner_relayout | True |
| allow_all_ops_in_lx_planning | False |
| sencores | 32 |
| dxp_lx_frac_avail | 0.2 |
| hbm_pool_planning | True |
| native_layout_packer | True |
| ignore_wsr_hints | False |
| ignore_span_overflow_hints | True |
| validate_op_specs | True |

Env explicitly forced for BOTH arms:
`USE_SPYRE_CCL=0`, `CO_OPTIMIZING_LX_PLANNING=0`, `LX_PLANNING=1`,
`SPYRE_LX_PLANNER_RELAYOUT=1`, `SENCORES=32`, `LAYOUT_SOLVER=<arm>`.

## Results

| shape | solver | solver_class | scratchpad_pass_ms | solve_ms | prepare_buffers_ms | build_solver_ms | n_buffers | n_specs | pre_dxp_ms |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| flash 512×1024 | cpsat | CpSatLayoutSolver | 3515.6 | 435.7 | 460.0 | 2615.7 | 264 | 257 | 23862 |
| flash 512×1024 | greedy | GreedyLayoutSolver | **792.5** | 8.5 | 772.2 | 0.02 | 280 | 273 | 20481 |
| flash 512×8192 | cpsat | CpSatLayoutSolver | 77742.1 | 70543.8 | 4927.2 | 2242.0 | 2056 | 2049 | 201956 |
| flash 512×8192 | greedy | GreedyLayoutSolver | **8345.9** | 503.2 | 7379.7 | 0.04 | 2184 | 2177 | 135082 |

## Interpretation

* **CP-SAT is 4.4× slower at 512×1024 and 9.3× slower at 512×8192**
  on scratchpad planning.
* Inside the solver: `solve_ms` went 436 → 70544 = **162×** as
  `n_buffers` grew 264 → 2056 (7.8×). Empirical slope ≈ 4.9 log-log —
  the CP-SAT cost is combinatorial in the number of buffers, not
  linear.
* Greedy: `scratchpad_pass_ms` 792 → 8346 = 10.5× as presched_ops
  grew 260 → 2052 (7.9×). Slope ≈ 1.13. **Near-linear**, consistent
  with Will's `faff191` measurements.
* `n_buffers` and `n_specs` differ between arms because the two
  planners produce different plans that lead to different downstream
  buffer counts. This is expected planner behavior; it does not
  invalidate the comparison of solver cost.
* `presched_input_ops` are IDENTICAL between arms at each shape
  (260 and 2052), so the input to the scratchpad pass is the same;
  divergence is entirely inside the solver + downstream.

## Verdict

**Solver selection fully explains the "scratchpad regression"
compared with Will's `faff191` numbers.** No code-drift investigation
(§4) needed. The observed superlinear scratchpad growth in the pilot
IS the CP-SAT default; greedy on the same source is nearly linear
and sub-second at 512×1024 in the range Will described.

## Study terminology update

* "current-default scratchpad planning" = **CP-SAT** (`LAYOUT_SOLVER=cpsat`)
* "historical / Will comparison arm" = **greedy** (`LAYOUT_SOLVER=greedy`)

Do not merge their scaling data into one curve.

## Post-Will investigation ranking (revised)

Given this data, the top post-restickify question is no longer
"optimize `_maybe_scratchpad_planning`". It is:

> Why does the current default CP-SAT scratchpad planner scale so
> super-linearly on large flash graphs, and is that compile-time
> cost justified by the plan-quality benefit versus greedy?

Concretely: at flash 512×8192 CP-SAT spends 70 s solving vs
greedy's 0.5 s. If the CP-SAT plan is materially better than
greedy's (residency, spill count), the trade-off may be
appropriate; if not, the current default may not carry its weight
on the pre-DXP time axis.

This is a much larger investigation than Will's greedy-solver
cleanup and belongs in a separate epic. Not to be started as part of
#4117.

## Recommended configuration for full #4117 sweep

**Primary baseline** — current frozen-main defaults, including CP-SAT:
`LAYOUT_SOLVER=cpsat`.
Everything else at their defaults (which match Will's).
This is what today's users see.

**Compatibility arm (small)** — enough greedy points to connect our
measurements to PR #3806 / Will's data:
`LAYOUT_SOLVER=greedy` at a subset of shapes, not the full sweep.
Suggest 3 flash shapes (512×1024, 512×4096, 1024×8192) × 3 samples,
and 3 MLP shapes (L=2, L=16, L=32) × 3 samples.

Do not double the entire 9-flash × 6-MLP × 3-sample matrix.

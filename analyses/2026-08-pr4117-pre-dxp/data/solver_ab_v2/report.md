# Solver A/B v2 — plan-outcome comparison

Frozen torch-spyre `3358f39` with `USE_SPYRE_CCL=0`. All resolved
config identical between arms except `LAYOUT_SOLVER`:

* `LAYOUT_SOLVER=cpsat` (current frozen-main default)
* `LAYOUT_SOLVER=greedy` (Will's `faff191` default)

Both arms had `SPYRE_DUMP_COST=1` so the analytical cost model
scored each resulting plan.

## Terminology (§1)

Fixed from the prior A/B. These are now distinct measured columns
and none is used as a proxy for another:

| term | meaning |
|---|---|
| `presched_input_ops` | ops entering `_maybe_scratchpad_planning` (before the allocator sees anything) |
| `planner_buffers` | buffers the allocator's `_prepare_buffers` handed to the solver |
| `eligible_buffers` | subset that the solver would place — `planner_buffers − barred` |
| `barred_buffers` | subset pinned non-resident before the solve (residency_reason, capacity fail, etc.) |
| `placed_in_lx` | buffers with `address is not None` after the solve returned |
| `spilled_from_lx` | buffers with `address is None` after the solve returned |
| `bytes_placed_in_lx` | sum of `buffer.size` where placed. Note: with in-place chains or paired buffers, sizes can share slots, so the sum can exceed the physical `lx_capacity_bytes`. It is a plan property, not a residency footprint. |

## Compact result table

| shape | solver | scratchpad_ms | solve_ms | prep_ms | build_ms | planner_buffers | eligible | barred | placed | spilled | LX_bytes | LX_cap | cost_us | solver_status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| flash 512×1024 | cpsat  | 794.4 | 327.6 | 462.8 | 0.04 | 264 | 113 | 151 | 113 | 151 | 1044480 | 1625344 | 1499.8 | OPTIMAL |
| flash 512×1024 | greedy | 789.0 |   8.4 | 768.8 | 0.03 | 280 | 145 | 135 | 145 | 135 | 1830912 | 1625344 | 1259.8 | — |
| flash 512×8192 | cpsat  | 55629.9 | 50728.4 | 4876.9 | 0.12 | 2056 |  897 | 1159 |  897 | 1159 | 8155136 | 1625344 | 11732.5 | OPTIMAL |
| flash 512×8192 | greedy |  8347.1 |   505.9 | 7620.6 | 0.04 | 2184 | 1153 | 1031 | 1153 | 1031 | 14446592 | 1625344 |  9812.5 | — |

Notes:

* Every `spilled_from_lx` value here equals `barred_buffers` — on
  both shapes, both solvers **spilled only pre-solve-barred buffers**.
  `solver_chose_spill_count = 0` in every arm.
* `bytes_placed_in_lx` exceeds `lx_cap_bytes` in three of four rows.
  With in-place chains and paired-buffer overlays, buffer sizes can
  share physical addresses; `bytes_placed_in_lx` is the plan-property
  sum, not a residency footprint.
* Same-shape `n_specs` differs between arms: cpsat 257 vs greedy 273
  at 512×1024, cpsat 2049 vs greedy 2177 at 512×8192. Downstream
  emits ~5-6% more specs under greedy.

## OR-Tools stats for CP-SAT arms

| shape | status | walltime_s | branches | conflicts | workers | time_limit_s | obj_value |
|---|---|---:|---:|---:|---:|---:|---:|
| flash 512×1024 | OPTIMAL | 0.32 | 100 | 0 | 192 | 600.0 | 29312 |
| flash 512×8192 | OPTIMAL | 50.41 |   4 | 0 | 192 | 600.0 | 575872 |

**Observations that matter:**

* Both CP-SAT runs terminate `OPTIMAL` well inside the 600 s time
  limit; the solver is NOT running out of time budget.
* `num_conflicts=0` in both — CP-SAT never backtracked, so its cost
  is not from combinatorial search failure.
* `num_branches` = 100 at the smaller shape but only 4 at the larger
  shape — the larger model has fewer branches yet 158× more wall
  time. That points at CP-SAT's cost being in **model construction +
  propagation**, not in branch-and-bound search.
* `walltime_s` (50.41) matches our stage timer `solve_ms` (50728),
  so the "solve time" we report is exactly OR-Tools' own wall.

## Cost-model context (§4)

`SPYRE_DUMP_COST=1` was on for both arms. `cost_model_pass.LAST_REPORT.total_us`:

| shape | cpsat µs | greedy µs | greedy − cpsat |
|---|---:|---:|---:|
| flash 512×1024 | 1499.8 | **1259.8** | **-16.0%** |
| flash 512×8192 | 11732.5 | **9812.5** | **-16.4%** |

On both shapes the analytical cost model **predicts greedy's plan
runs ~16% faster than CP-SAT's plan**. This is a plan-quality signal
from the existing model, computed at zero incremental cost.

## Semantic compiler-outcome comparison (§3)

* `presched_input_ops` is IDENTICAL between arms at each shape (260
  and 2052), so the input to `_maybe_scratchpad_planning` is
  the same.
* `planner_buffers` differs slightly (264 vs 280; 2056 vs 2184).
  Different plans generate slightly different downstream buffer
  counts.
* `eligible_buffers` differs meaningfully — greedy sees more buffers
  as eligible (145 vs 113; 1153 vs 897). This is because CP-SAT and
  greedy compute the barred/residency partition differently for the
  same input graph — the two solvers do not agree on which buffers
  even *could* be placed. Not "solver quality"; different eligibility
  logic on the same input.
* `n_kernels` = 1 in every arm — same kernel count reaches SDSC.
* `n_specs` differs by ~5-6% (257 vs 273; 2049 vs 2177). Cost-model
  runs on both.

Placed/spilled name signatures are captured in each JSON's
`scratchpad_plan_allocation.meta.placed_signature` and
`spilled_signature`. They diverge; details in the raw files.

## Verdict (§5)

**Case B — little/no measurable plan benefit** applies here, in fact
stronger than the review's Case B contemplated:

> At flash 512×1024 the current-default CP-SAT solver takes 327 ms
> to solve where greedy takes 8 ms, for a plan that the analytical
> cost model predicts is 16% SLOWER at runtime than greedy's plan.
>
> At flash 512×8192 the same comparison: 50 728 ms vs 506 ms
> (100× slower to plan), predicting a plan that is 16% slower to run
> than greedy's.

CP-SAT terminates `OPTIMAL` in both cases. So this is not
CP-SAT-hitting-a-time-limit-with-a-worse-plan — it is CP-SAT
optimizing a residency objective that is not the same thing the
cost model measures, and doing so with a much larger model-build
cost than greedy needs.

> **Flag as a high-priority frontend-performance finding for #4117.**
>
> The current-main default solver pays a large CP-SAT compile-time
> premium and by the existing analytical cost model produces a
> plan that is roughly 16% worse on this flash workload family.

## Scope framing (§6)

Per your correction, the CP-SAT compile-time investigation is IN
scope for #4117:

* **In scope for #4117**:
  * why current-default CP-SAT costs so much during compilation;
  * deterministic work scaling (model-build/propagation cost as a
    function of graph size — this A/B strongly implicates
    model-build, not search);
  * avoiding unnecessary search (thresholds, fast paths for small
    graphs);
  * a fallback rule that switches to greedy when CP-SAT's expected
    compile-time cost exceeds a threshold OR when its cost-model
    plan is not detectably better than greedy's.
* **Out of scope for #4117**:
  * redesigning the CP-SAT residency objective;
  * trying to improve CP-SAT solution quality for its own sake.

The plan-quality comparison in this experiment exists only to
interpret whether the compile-time premium corresponds to a
different compiler decision. Here, it corresponds to a slightly
worse decision by the cost model.

## Two-point empirical exponents

Per your terminology correction. These are two-point empirical
exponents between the two measured points; they are NOT statements
about CP-SAT algorithmic complexity:

* CP-SAT `solve_ms` growth: 327.6 → 50728.4 = 155× when
  `planner_buffers` grew 264 → 2056 = 7.8×. Two-point exponent ≈ 4.86.
* Greedy `scratchpad_pass_ms` growth: 789.0 → 8347.1 = 10.6× when
  `planner_buffers` grew 280 → 2184 = 7.8×. Two-point exponent ≈ 1.14.

Do not infer from two points what shape CP-SAT would have at other
sizes. Full-sweep data across more shapes would let us fit a real
exponent.

## Recommended full-sweep configuration (§7)

**Primary baseline (frozen-main defaults):**
* `LAYOUT_SOLVER=cpsat`
* All other resolved-config values at the pilot's captured defaults.
* Full flash sweep + layer-scaled MLP sweep + 3 cold samples per point.

**Historical compatibility (flash-only, 3 points, 3 samples each):**
* `LAYOUT_SOLVER=greedy`
* Shapes: 512×1024, 512×4096, 1024×8192.
* Enough to connect to PR #3806 / Will's data.

**No greedy MLP compatibility arm.** No historical MLP dataset from
PR #3806 or Will needs bridging.

Total: 15 flash-cpsat + 18 mlp-cpsat = 33 primary runs, plus 9
flash-greedy compatibility runs = **42 cold compiles**. Half the
runtime of a full 2× sweep.

**Do not merge cpsat and greedy scaling data into one curve.**

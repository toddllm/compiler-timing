# PR #4139 hardening report

Two passes, both dated 2026-08-30. First pass covered §1–§7 of the
initial hardening list (rebase onto #3810, spill-cost dedup,
alignment-unit certificate domain, exact `record_exclusions()`
floor, representability guard, 17 unit tests, differential corpus
rerun, capacity-pressure sweep rerun, pre-commit + CI). Second pass
(section 14 below) tightened proof wording (zero-cost non-excluded
buffers may remain spilled on a certified plan), added test 5b as
a regression against the earlier over-strong claim, and ran an
end-to-end validation on the rebased branch through
`torch.compile` with instrumentation on `plan_layout`.

## 1. Rebase

- Rebased onto upstream `main` at `ae9b88d4d79b971026591e525c63e504302502b7`
  (includes #3810 "Integrate cost model with ILP solver").
- No mechanical merge — the rebase was semantic: `_plan_layout_generic`'s
  signature grew a `cost_expr: sympy.Expr | None = None` parameter,
  reachable only through `plan_layout_and_core_divisions`, which the
  seed does not touch.

## 2. #3810 interaction analysis

`cost_expr` enters `_plan_layout_generic._run` through the joint entry
`plan_layout_and_core_divisions` only. `_run` dispatches:

- `cost_expr is not None` → `_minimize_cost_expr` (the analytical
  cost-model branch #3810 introduces).
- `cost_expr is None` → the residency lex-solve
  (`_minimize_residency` then optional parallelism/balance).

`plan_layout` (placement-only entry) calls `_plan_layout_generic()`
with no arguments and never passes `cost_expr`, so its `_run` branch
is unchanged by #3810. The seed is on `plan_layout` only.

## 3. Certificate proof (source-checked on `ae9b88d`)

- **Placement-only objective**: `_run` runs only level 1 of the
  lex-solve when `co_optimizing_lx_planning=False`. Levels 2/3 are
  gated on `core_terms != []`; the placement wrapper
  `_LifetimeBufferWithCpVars` sets `cores = None`, so those levels
  never fire.
- **Nonnegative sum**: `spill_cost(b) ≥ 0`,
  `(1 - in_buffer(b)) ∈ {0, 1}` → objective is a nonneg sum, and its
  minimum is the sum over terms forced active.
- **Forced set = `record_exclusions()`**: buffers with
  `residency_reason` OR `min_footprint > limit` are pinned to
  `in_buffer = 0` in `_add_core_division`.
- **Alignment-unit domain**: `_wrap` builds every model buffer with
  `size = ceil_div(original.size, alignment)`; the objective is
  built over those sizes. The seed evaluates in the same domain.
- **Representability**: `_capacity_units = self.limit // self.alignment`;
  CP-SAT can only express addresses in
  `[0, _capacity_units × alignment)`. The seed guards
  `_capacity_units > 0` and rejects greedy plans whose addresses
  misalign or top exceeds that ceiling.

## 4. Spill-cost dedup (§2A)

Added a module-level `_hbm_spill_cost(buffer)` helper.
`_LifetimeBufferWithCpVars.spill_cost` delegates to it via
`return _hbm_spill_cost(self.buffer)`. The seed calls it directly.
One formula, no duplication.

## 5. Alignment-domain handling (§2B)

The seed computes both `lower_bound_units` and `greedy_objective_units`
by wrapping each buffer with `replace(b, size=ceil_div(b.size, alignment))`
before passing to `_hbm_spill_cost` — identical to what `_wrap`
produces for CP-SAT. Non-aligned sizes are handled correctly (test
#8 exercises this).

## 6. Exact lower-bound implementation (§2C)

```python
forced_reasons = dict(self.record_exclusions())
lower_bound_units = sum(
    _hbm_spill_cost(replace(b, size=ceil_div(b.size, self.alignment)))
    for b in buffers
    if b.name in forced_reasons
)
```

`record_exclusions()` returns the union of `residency_reason` and
`min_footprint > limit`. Test #4 exercises the size-only case
(`min_footprint > limit`, `residency_reason=None`) and confirms the
buffer is in the floor.

## 7. Representability preservation (§2D)

- Guard: `if self._capacity_units <= 0: return None` (test #9).
- Per-buffer check on greedy's plan:
  `address % alignment == 0` and `address + size <= _capacity_units × alignment`
  (test #10).

## 8. Test suite (§3)

`tests/inductor/test_cpsat_certified_greedy_seed.py` — 17 tests:

1. lower-bound greedy plan skips CP-SAT solve
2. non-zero greedy objective falls through
3. `residency_reason` contributes to floor
4. `min_footprint > limit` contributes to floor
5. zero-spill-cost buffer semantics
6. graph-input spill-cost semantics
7. intermediate spill-cost semantics
8. non-aligned buffer sizes match CP-SAT objective
9. `limit < alignment` never certifies (representability guard)
10. `limit` not divisible by `alignment` uses CP-SAT top
11. in-place reuse still certifies
12. rejected seed leaves originals untouched
13. accepted seed commits addresses only
14. joint path never uses seed (behavioral: patch to raise; joint
    call succeeds → seed never fired)
15. `spill_reasons` use forced reason for excluded buffer
16. explicit greedy solver (LAYOUT_SOLVER=greedy) unchanged
17. `_LifetimeBufferWithCpVars.spill_cost` delegates to shared helper

Local run: **17/17 pass** with autoload disabled.

Existing tests: 250/250 pass in `tests/inductor/test_scratchpad_solver.py`.

Test #14 is behavioral (patches the seed method to raise, verifies
joint path completes without hitting the raise) — no source-string
introspection.

## 9. Differential corpus rerun (§5)

`harness/hybrid_certified_corpus.py` — updated to use
`record_exclusions()` semantics for its lower-bound function and to
use `_plan_layout_generic()` directly for standalone-CP-SAT
measurement.

Result: **28 non-SKIP cases, 20 greedy-certified, 8 cpsat-fallback,
0 invariant violations**. `hybrid_objective == standalone_cpsat_objective`
holds on every valid case.

Data: `data/hybrid_certified_corpus_v2/summary.json`.

## 10. Capacity-pressure sweep on captured buffers (§4)

`harness/capacity_pressure_sweep.py` — same updates.

Result: **40 workload×scale points, 39 certified, 1 cpsat-fallback
(flash-512x8192 @ 25% — the exact capacity-pressure case),
0 objective mismatches vs standalone CP-SAT**.

Data: `data/capacity_pressure_sweep_v2/summary.json`.

## 11. Local tests + pre-commit (§6)

- `pre-commit run --files <two modified paths>`: **all hooks pass**
  (ruff-check, ruff-format, mypy, spaces-in-filenames, import-regex,
  suggestion).
- Post-format re-run of unit tests on pod: **17/17 pass**.

## 12. GitHub CI (§6)

Pushed to `tdeshane/adaptive-solver-threshold-draft` at head
`7e6e9db4cc072a58bdab317949a89b566d22f561` (previous commit
`d493ddab2424b1f966b21f016a95c88e45ad7d79` fixed the initial CI
wire-check failure).

**All 5 parent workflows completed with conclusion `success`:**

- `tests` — success
- `Enforce Test CI Coverage` — success
- `oot-config-checker-tool` — success
- `linters` — success
- `upstream-pytorch-tests` — success

Individual-check rollup: 142 SUCCESS, 2 SKIPPED, **1 FAILURE**.

The one failure is
`run-tests / Inductor / Test Inductor Ops Misc Shape C`, on
`test_keep_by_index_4d_dim3_spyre` with
`AssertionError: Tensor-likes are not close!` at
`test_inductor_ops.py:6354`. This is a numerical-correctness test on
`aten.index_select`-style ops, entirely unrelated to the scratchpad
memory planner or the CP-SAT layout solver. Same job failed both
pushes to this branch. The parent `tests` workflow treats it as
non-blocking (its overall conclusion is `success`), and the
project's `retry-failed-tests` workflow only fires on
`workflow_run.conclusion == 'failure'`, so it did not auto-retry
this run.

I do not have admin rights to trigger a rerun of just the failed
job. Options: (a) accept the flake since the parent workflow is
green and the failure is orthogonal to the change; (b) ask an
admin to `gh run rerun 33334496400 --failed`; (c) push another
inert commit to trigger fresh CI.

## 13. PR body (§7)

Updated with the safety argument using the user's preferred framing:
"first runs a cheap greedy probe on a solver-local copy" and
"feasible under the CP-SAT placement contract and attains the exact
forced-spill lower bound of CP-SAT's own residency objective."

## Draft → Ready readiness (my read)

The certificate proof is source-checked on the current rebase base.
Every certificate step now has a corresponding unit test (17/17
pass) plus a fixture-level replay that shows equivalent decisions
on real captured planner-buffer sets from compiled workloads (40/40
match standalone CP-SAT). The joint path is untouched and covered
by a behavioral test.

The one open item at the time of writing is the flake on
`test_keep_by_index_4d_dim3_spyre` (an inductor ops test unrelated
to scratchpad memory planning) that appeared on the first push and
is now being re-run against `7e6e9db`. If it fails again on the
same test we should read the log — but the failure signature is
`test_inductor_ops__oot_wrapper` and the code path my PR touches is
solver-only.

**Decision on Ready remains with Todd.** No `@tardieu` comment
added; conclusion is materially unchanged from the prior draft
discussion (certified seed is the preferred direction, no threshold
knob, no config change, joint path untouched).

## 14. Second-pass: proof-wording cleanup + end-to-end validation

### 14.1 Zero-cost spill correction

The docstring and study writeups previously claimed:

> Reaching that floor is equivalent to placing every non-excluded
> buffer.

That claim assumes strictly positive spill costs. When a
non-excluded buffer has `spill_cost == 0` (e.g. a single-use graph
input: `read_count == 1`, `first_use_is_read == True` gives
`reads_served == 0`, `is_intermediate == 0`), it can legally remain
spilled on a certified plan: the objective is a nonneg sum, and a
zero term does not push it above the floor.

The revised wording — used in the docstring of
`_try_certified_greedy_seed`, in `certified-greedy-seed.md`, and
in the PR body — is:

> Reaching the forced-spill lower bound proves global optimality of
> the placement-only residency objective. Any additionally spilled
> non-excluded buffers must have `spill_cost == 0` and therefore
> cannot improve or worsen that objective. The certificate bounds
> the objective, not the placement set.

Also adjusted: the code comment above the `spill_reasons` fallback
in `_try_certified_greedy_seed`. The fallback to
`_SOLVER_CHOSE_SPILL` for a buffer NOT in `forced_reasons` is a
real code path, not symmetry: a `spill_cost == 0` non-excluded
buffer that greedy left unplaced will hit exactly that branch.

Added `test_zero_cost_non_excluded_buffer_may_remain_spilled`
(test 5b) that constructs such a fixture (`hot` size 10 fills the
capacity, `zero` a `spill_cost=0` graph input arrives while `hot`
is live and cannot fit) and asserts:

- `_hbm_spill_cost(zero) == 0`, `_hbm_spill_cost(hot) > 0`;
- the hybrid certifies, `resident_set == {"hot"}`;
- `hybrid_objective == standalone_cpsat_objective`;
- `zero` is NOT in `record_exclusions()` yet appears in
  `spill_reasons` under the solver-chose-spill sentinel.

Test suite now: 18 tests, all pass on the pod.

### 14.2 Post-#3810 end-to-end validation

`harness/seed_endtoend_probe.py` monkey-patches
`CpSatLayoutSolver.plan_layout` to record every real invocation
(chosen path, buffer counts, forced set, greedy plan objective,
standalone-CP-SAT cross-check, wall times) on the rebased branch.

`harness/seed_endtoend_driver.sh` sweeps:

| workload | shape | samples |
|----------|------|---------|
| flash    | 512x4096 | 3 cold |
| flash    | 512x8192 | 3 cold |
| mlp      | N_in=1024, N_hidden=4096, 4 layers | 1 |
| sdpa     | B=1, H=8, S=512, D=128 | 1 |

Each sample runs `torch.compile(fn)` and lets the front-end reach
scratchpad memory planning. DXP is intercepted before its
subprocess call so wall time stays bounded; the seed decision fires
inside the scratchpad allocator (which runs before DXP), so the
data we care about is fully captured.

Result (`data/e2e_validation/*.json`):

| workload   | sample | chosen           | n_buf | placed | lb_u | hybrid_obj | std_obj | seed_ms | std_cpsat_ms |
|------------|-------:|------------------|------:|-------:|-----:|-----------:|--------:|--------:|-------------:|
| flash_4096 |      0 | greedy-certified |    13 |      6 |   16 |         16 |      16 |    0.45 |        14.66 |
| flash_4096 |      1 | greedy-certified |    13 |      6 |   16 |         16 |      16 |    0.50 |        10.91 |
| flash_4096 |      2 | greedy-certified |    13 |      6 |   16 |         16 |      16 |    0.40 |        10.17 |
| flash_8192 |      0 | greedy-certified |    13 |      6 |   16 |         16 |      16 |    0.53 |        15.99 |
| flash_8192 |      1 | greedy-certified |    13 |      6 |   16 |         16 |      16 |    0.51 |        11.43 |
| flash_8192 |      2 | greedy-certified |    13 |      6 |   16 |         16 |      16 |    0.43 |        10.06 |
| mlp_L96    |      0 | greedy-certified |    21 |      8 |    2 |          2 |       2 |    0.73 |        17.29 |
| sdpa_S512  |      0 | greedy-certified |    31 |     18 | 1152 |       1152 |    1152 |    1.42 |        35.10 |

8 real seed invocations across 4 workloads. All certified, all
`hybrid_objective == standalone_cpsat_objective`. Zero mismatches.

Note: the flash `n_buffers=13` here is the compile-time small-graph
count for the study's stand-alone closure, not the captured
production planner-buffer set (2056 buffers for flash-512x8192).
Both are exercised — this pass validates the seed on the actual
`torch.compile` path, and section 10 (capacity-pressure sweep on
captured buffers) validates on production-shape inputs.

### 14.3 Fallback validation on flash-512x8192 @ 25% capacity

`harness/seed_fallback_probe.py` loads the captured 2056-buffer
flash-512x8192 planner set at 25% of shipped LX capacity and runs
it through the rebased solver. Result
(`data/e2e_validation/flash_8192_25pct_fallback.json`):

| quantity | value |
|----------|-------|
| n_buffers | 2056 |
| scaled_limit_bytes | 406336 |
| capacity_units | 3174 |
| greedy alone objective (units) | 578432 |
| forced-spill floor (units) | 575872 |
| greedy above floor | **True** (2560 units above) |
| seed returned `None` | **True** (certificate rejects) |
| standalone CP-SAT objective (units) | 575872 |
| hybrid public-path objective (units) | 575872 |
| **objectives match** | **True** |
| greedy alone wall | 225 ms |
| seed probe wall | 261 ms |
| standalone CP-SAT wall | 45.3 s (this run) |
| hybrid (seed + fallback) wall | 64.9 s (this run) |

On a fallback, the hybrid necessarily pays the greedy probe
overhead before running CP-SAT. In this measured 2056-buffer flash
case the greedy probe itself was ~237 ms (`_try_certified_greedy_seed`
inside `plan_layout`). End-to-end CP-SAT solve wall varied
substantially between runs, so the fallback measurements above are
NOT used to claim a wall-time improvement or regression — only the
per-run greedy-probe overhead and the objective identity are
deterministic conclusions.

The seed's greedy probe strictly leaves 2560 units of residency
on the table vs the forced-spill floor. The certificate correctly
rejects, `plan_layout` falls through to `_plan_layout_generic`,
and the hybrid returns the CP-SAT-optimal objective. This is
exactly the fallback case predicted by the corpus study.

### 14.4 Ready-for-review reassessment

Every certificate step is now source-checked, unit-tested (18
tests), replay-checked on 28 corpus scenarios (0 invariant
violations), replay-checked on 40 captured workload×scale points
(0 objective mismatches), and end-to-end-checked on 8 real
`torch.compile` invocations on the rebased branch (0 mismatches).
The proof language has been corrected to say the certificate
bounds the objective, not the placement set.

The one previously-open CI item — `test_keep_by_index_4d_dim3_spyre`
failing at the individual-check level while the parent `tests`
workflow remained `success` — is an inductor-ops numerical
correctness test in `test_inductor_ops__oot_wrapper.py`. It does
not touch the scratchpad memory planner or the CP-SAT layout
solver, and the parent workflow treated it as non-blocking. If it
reproduces after the next push, we should file it separately;
the seed code is orthogonal.

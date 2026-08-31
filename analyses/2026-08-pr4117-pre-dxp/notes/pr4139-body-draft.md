# inductor: certified greedy seed for placement-only CP-SAT

> Placement-only CP-SAT first runs greedy on a solver-local copy. If
> that placement is representable under CP-SAT's placement domain and
> attains the exact forced-spill lower bound of CP-SAT's own residency
> objective, then no feasible CP-SAT solution can have a lower
> objective value, so the greedy placement is accepted. Otherwise
> normal CP-SAT runs unchanged. The certificate bounds the objective,
> not the placement set: a non-excluded buffer whose `spill_cost == 0`
> may legally remain spilled on a certified plan.

Ready for technical review by the scratchpad / CP-SAT owners.
Reviewers should evaluate the certificate implementation, API
assumptions, and whether any additional DXP/on-device validation is
wanted before merge — objective equivalence is formally certified
on accepted plans and preserved by the standalone CP-SAT fallback
on rejected ones, but the final rebased end-to-end pass intercepted
DXP before its subprocess (see caveat below).

Refs #4117, #3978, #3932, #2062.

**Architecture note (Aug. 31):** maintainers indicated joint CP-SAT
co-optimization of scratchpad allocation and work division is
expected to become the default imminently. This PR intentionally
does not apply to that joint path; the certificate is a
forced-spill lower bound on the placement-only residency objective
only, not on the joint objective (which adds parallelism, balance,
and #3810's optional `cost_expr` axes). Merge value therefore
depends on whether placement-only CP-SAT remains a meaningful
supported configuration; that maintainer decision is pending in
the discussion below.

The final implementation was rebased on August 31 onto then-current
upstream `main` (which includes #3810 "Integrate cost model with
ILP solver"). #3810 adds a `cost_expr` parameter reachable only
through `plan_layout_and_core_divisions`; the placement-only entry
`plan_layout` never passes `cost_expr`, so its `_run` branch is
unchanged. The seed is on `plan_layout` only —
`plan_layout_and_core_divisions` is untouched.

## Certificate

Under `co_optimizing_lx_planning=False` (the current default at the
time of writing; the joint-CP-SAT default switch flagged in the
architecture note above is still pending),
`plan_layout` runs only level 1 of the lexicographic solve inside
`_plan_layout_generic._run`: minimize
`sum(spill_cost(b) * (1 - in_buffer(b)))` over CP-SAT's
alignment-unit-scaled buffer copies. Levels 2 (parallelism) and 3
(balance) are gated on `core_terms` being non-empty, which requires a
non-`None` `.cores` on a wrapped buffer;
`_LifetimeBufferWithCpVars.__post_init__` sets `cores = None`, so
those levels never fire on the placement-only path. The `cost_expr`
branch is also unreachable here.

Every `spill_cost(b) ≥ 0` and `(1 - in_buffer) ∈ {0, 1}`, so the
objective is a nonnegative sum. Its absolute lower bound is the sum
over the buffers CP-SAT pins non-resident before it optimizes anything:
`MemoryPlanSolver.record_exclusions()`, which is the union of

- buffers whose allocator-declared `residency_reason` is not `None`,
- buffers whose `min_footprint > limit` (size-only forced exclusion),

matches the exact set `_add_core_division` pins to `in_buffer = 0`.
Reaching the forced-spill lower bound proves global optimality of the
placement-only residency objective. Any additionally spilled
non-excluded buffers must have `spill_cost == 0` and therefore cannot
improve or worsen that objective (test #5b covers this case). The
certificate bounds the objective, not the placement set.

The certificate compares CP-SAT-domain quantities. CP-SAT works over
alignment-unit-scaled sizes (`ceil_div(size, alignment)` in `_wrap`)
and can only express addresses in `[0, _capacity_units × alignment)`
where `_capacity_units = self.limit // self.alignment`. The seed
therefore:

1. **Guards representability.** If `_capacity_units ≤ 0` the model
   has no addressable slot; the seed cannot be evaluated in that
   domain and returns `None` immediately (fallback to CP-SAT).
2. **Runs greedy on a solver-local deep copy** at `self.limit`, so the
   caller's buffers are never mutated by the probe.
3. **Rejects any unrepresentable greedy plan.** Each placed buffer
   must have `address % alignment == 0` and
   `address + size ≤ _capacity_units × alignment`, so
   `self.limit` not being a multiple of alignment does not fool the
   certificate into accepting a plan CP-SAT could not encode.
4. **Evaluates greedy's objective in the same alignment-unit domain**
   the CP-SAT objective is built in, via a single module-level helper
   `_hbm_spill_cost(buffer)` that `_LifetimeBufferWithCpVars.spill_cost`
   also delegates to (one source of truth — no hand-duplicated
   formula).
5. **Accepts iff** `greedy_objective_units == lower_bound_units`;
   otherwise falls through to `_plan_layout_generic` on the untouched
   originals.

On acceptance, greedy's addresses are committed onto the caller's
buffers by name, and `spill_reasons` is populated with each excluded
buffer's reason from `record_exclusions()` — matching what the
`_plan_layout_generic` tail would have produced.

## Evidence

**Differential corpus** — 28 non-SKIP scenarios captured from
`BaseLayoutSolverTests`, with the harness's lower-bound function using
the exact `record_exclusions()` semantics:

| hybrid choice        | count |
|----------------------|------:|
| greedy-certified     |    20 |
| cpsat-fallback       |     8 |
| SKIP (no solve call) |     7 |
| **INVARIANT_VIOLATION** | **0** |

Invariants that hold on every valid case:

- `hybrid_objective == standalone_cpsat_objective` (via
  `_plan_layout_generic` directly to bypass the seed)
- `hybrid_chosen == "greedy-certified" ⇒ hybrid_objective == lb ==
  greedy_objective`

**Capacity-pressure sweep on captured planner-buffer sets** (flash
512x{1024,2048,4096,8192}, MLP L∈{96,192,384}, sdpa
S∈{512,1024,2048}, each at 100/75/50/25% of the shipped LX
capacity — 40 workload-scale points):

| hybrid choice   | count |
|-----------------|------:|
| greedy-certified |    39 |
| cpsat-fallback   |     1 |

Invariant `hybrid_objective == standalone_cpsat_objective` holds on
every 40 points (0 mismatches).

The single fallback is flash-512x8192 at 25% capacity — the exact
capacity-pressure case where CP-SAT genuinely picks a better placement
(greedy_obj = 74,039,296; cpsat_obj = 73,711,616). The seed correctly
rejects and the hybrid returns CP-SAT's optimum.

Compared with the previous sweep summary in `certified-greedy-seed.md`
(which was written against a harness lower-bound function that only
counted `residency_reason`-forced buffers), 9 sdpa/edge-case points
that used to appear as fallback now correctly certify: they attain
the true `record_exclusions`-based floor.

Selected wall times:

| workload         | scale | g_obj    | c_obj    | chosen           | g_ms  | c_ms      | h_ms   |
|------------------|------:|---------:|---------:|------------------|------:|----------:|-------:|
| flash-512x1024   |  1.00 |  3.75M   |  3.75M   | greedy-certified |   4.9 |     333.1 |    9.1 |
| flash-512x2048   |  1.00 |  9.03M   |  9.03M   | greedy-certified |  19.6 |    1627.0 |   23.3 |
| flash-512x4096   |  1.00 | 24.30M   | 24.30M   | greedy-certified |  57.0 |    8938.5 |   73.6 |
| flash-512x8192   |  1.00 | 73.71M   | 73.71M   | greedy-certified | 229.1 |   50456.4 |  265.7 |
| **flash-512x8192**  | **0.25** | **74.04M** | **73.71M** | **cpsat-fallback** | **236.9** | **65316.5** | **45476.2** |
| mlp-L96          |  1.00 |   128    |   128    | greedy-certified |   9.5 |     196.4 |   19.9 |
| mlp-L192         |  1.00 |   128    |   128    | greedy-certified |  38.0 |     621.6 |   53.1 |
| mlp-L384         |  1.00 |   128    |   128    | greedy-certified | 151.7 |    1488.4 |  182.7 |
| sdpa-S512        |  1.00 |  459K    |  459K    | greedy-certified |   0.2 |      23.6 |    0.8 |
| sdpa-S1024       |  1.00 |  1.44M   |  1.44M   | greedy-certified |   0.2 |      23.5 |    0.8 |
| sdpa-S2048       |  1.00 | 22.02M   | 22.02M   | greedy-certified |   0.2 |      17.1 |    1.0 |

**Wall-time framing on the fallback row.** On a fallback, the hybrid
necessarily pays the greedy probe overhead before running CP-SAT.
In the measured 2056-buffer flash-512x8192 case the greedy probe
itself was about 237 ms. End-to-end CP-SAT solve wall varied
substantially between runs (a separate rebased-branch run on the
same captured buffers reported 45.3 s standalone vs 64.9 s hybrid;
this table reports 65.3 s vs 45.5 s from a different run), so the
fallback measurements are NOT used to claim a wall-time improvement
or regression. The deterministic conclusions are objective identity
and the per-run greedy-probe overhead.

**Unit tests** — `tests/inductor/test_cpsat_certified_greedy_seed.py`,
18 tests:

1. lower-bound greedy plan skips CP-SAT solve
2. non-zero greedy objective falls through to CP-SAT
3. `residency_reason` contributes to lower bound
4. `min_footprint > limit` contributes to lower bound (size-only
   forced exclusion)
5. zero-spill-cost buffer semantics
5b. zero-cost non-excluded buffer may remain spilled on a certified
    plan (proves the certificate bounds the objective, not the
    placement set — a `spill_cost == 0` term neither raises nor
    lowers the residency sum)
6. graph-input spill-cost semantics
7. intermediate spill-cost semantics
8. non-aligned buffer sizes match CP-SAT objective in unit domain
9. `limit < alignment` never certifies (`_capacity_units == 0`
   representability guard)
10. `limit` not divisible by `alignment` uses CP-SAT top for
    representability
11. in-place reuse still certifies
12. rejected seed leaves originals untouched before CP-SAT
13. accepted seed commits addresses only (no other field mutated)
14. `spill_reasons` use forced reason for excluded buffer
15. joint `plan_layout_and_core_divisions` never uses the seed
    (behavioral: patch `_try_certified_greedy_seed` to raise;
    joint path succeeds without hitting the raise)
16. explicit greedy solver arm (`LAYOUT_SOLVER=greedy`) unchanged
17. `_LifetimeBufferWithCpVars.spill_cost` delegates to shared
    `_hbm_spill_cost` helper

Also verified: the 250 existing scratchpad-solver tests all pass with
the seed enabled.

## What's in this PR

`torch_spyre/_inductor/scratchpad/ilp_solver_ortools.py`:
- Module-level `_hbm_spill_cost(buffer)` helper: the one source of
  truth for the placement-only spill-cost formula.
- `_LifetimeBufferWithCpVars.spill_cost` delegates to
  `_hbm_spill_cost` (no duplicated formula).
- `CpSatLayoutSolver._try_certified_greedy_seed()` implements the
  certificate: representability guard, solver-local greedy probe,
  address/top-of-buffer representability check per placed buffer,
  unit-domain objective evaluation, exact
  `record_exclusions()`-based lower bound, address commit on
  acceptance, `None` return on rejection.
- `CpSatLayoutSolver.plan_layout()` calls
  `_try_certified_greedy_seed()` first and falls through to
  `_plan_layout_generic()` on `None`.
- `plan_layout_and_core_divisions()` is untouched (the `cost_expr`
  branch added by #3810 is not on the placement-only path).

`tests/inductor/test_cpsat_certified_greedy_seed.py`: 18 tests
described above (the labelled `5b` addition brings the visually 1–17
list to 18 actual test cases).

## What is NOT in this PR

- No config knob. No `adaptive_solver_threshold_ops`, no workload
  classifier. The certificate is derived from CP-SAT's own objective.
- No default change to `layout_solver`.
- No change to the joint (`co_optimizing_lx_planning=True`) path.
- No change to `demote_incoherent_lx_buffers` (#3378) or the
  correctness path from #2062.
- No mutation of caller buffers when the seed rejects; on
  acceptance, only `address` (and `spill_reasons`) are written.

## Post-#3810 end-to-end validation on the rebased branch

`harness/seed_endtoend_probe.py` instruments the shipped
`plan_layout` on the rebased branch and records every real
invocation as `torch.compile` drives the front end. The DXP
subprocess is intercepted before its call so wall time stays
bounded; the seed decision fires inside the scratchpad allocator,
which runs before DXP.

| workload   | sample | chosen           | n_buf | placed | lb_u | hybrid_obj | std_obj | seed_ms | std_cpsat_ms |
|------------|-------:|------------------|------:|-------:|-----:|-----------:|--------:|--------:|-------------:|
| flash-512x4096 | 0/1/2 | greedy-certified | 13 | 6 | 16 | 16 | 16 | 0.4–0.5 | 10–15 |
| flash-512x8192 | 0/1/2 | greedy-certified | 13 | 6 | 16 | 16 | 16 | 0.4–0.5 | 10–16 |
| mlp (N_in=1024, N_hidden=4096, 4L) | 0 | greedy-certified | 21 | 8 | 2 | 2 | 2 | 0.73 | 17.3 |
| sdpa (S=512, D=128, H=8, B=1) | 0 | greedy-certified | 31 | 18 | 1152 | 1152 | 1152 | 1.42 | 35.1 |

8 real seed invocations, all certified, 0 objective mismatches vs
standalone CP-SAT.

Fallback validation on the captured 2056-buffer flash-512x8192
planner set at 25% of shipped LX capacity, driven through the
rebased solver:

- greedy alone: 578432 units (2560 units above the floor)
- forced-spill floor: 575872 units
- seed returned `None` (certificate rejects — greedy > floor)
- standalone CP-SAT: 575872 units
- hybrid public path: 575872 units
- **objectives match**

Data: `data/e2e_validation/*.json`.

## Caveats

- **The certificate proves objective optimality, not placement
  identity.** On an accepted plan the returned buffer list is
  objective-equivalent to what CP-SAT would produce; the placement
  set may differ, and a non-excluded buffer whose `spill_cost == 0`
  can legally remain spilled (test 5b guards this). `spill_reasons`
  falls back to `_SOLVER_CHOSE_SPILL` in that branch.
- **Zero-cost non-excluded buffers may remain spilled.** Single-use
  graph inputs (`read_count == 1`, `first_use_is_read == True`) have
  `reads_served == 0` and `is_intermediate == 0`, so `spill_cost ==
  0`; the residency objective is invariant to their placement, so
  the certificate is valid even when they are unplaced.
- **Greedy probe adds overhead on CP-SAT fallback cases.** ~0.2 ms
  on tiny graphs, ~237 ms on the 2056-buffer flash-512x8192
  capacity-pressure case. On fallback the hybrid necessarily pays
  this on top of the CP-SAT solve; the CP-SAT solve wall itself
  varies substantially between runs, so the measurements here are
  not used to claim a fallback wall-time improvement or regression.
- **The current-main post-#3810 front-end validation intercepted
  DXP before its subprocess.** The e2e harness records the seed
  decision, buffer counts, objectives, and the standalone-CP-SAT
  cross-check on the rebased branch, but the DXP compile itself was
  short-circuited to keep wall time bounded (the seed fires inside
  the scratchpad allocator, which runs before DXP). Earlier study
  data on the parent #4117 branch contains actual DXP / on-device
  bitwise-equality evidence; this final rebased validation did not
  repeat device execution.
- **Joint `plan_layout_and_core_divisions(cost_expr=...)` is
  untouched.** #3810's `cost_expr` branch is reachable only through
  that joint entry and never through `plan_layout`; the seed is on
  `plan_layout` only. Test 15 exercises this behaviorally by
  patching the seed to raise and confirming the joint path
  completes without hitting the raise.
- Bundle-generation nondeterminism from the #4117 study stands as a
  separate follow-up; the regression gates for this PR are the
  structural placement-objective identity, not `bundle.mlir` bytes.

## Study links

- Certified greedy seed writeup:
  `toddllm/compiler-timing/analyses/2026-08-pr4117-pre-dxp/notes/certified-greedy-seed.md`
- Differential corpus (with hybrid arm):
  `.../data/hybrid_certified_corpus_v2/summary.json`
- Capacity pressure sweep:
  `.../data/capacity_pressure_sweep_v2/summary.json`
- End-to-end validation on the rebased branch:
  `.../data/e2e_validation/*.json`
- Hardening report:
  `.../notes/pr4139-hardening-report.md`
- Captured planner-buffer sets:
  `.../data/captured_buffers/*.pkl`

Signed-off-by: Todd Deshane <todd.deshane@ibm.com>

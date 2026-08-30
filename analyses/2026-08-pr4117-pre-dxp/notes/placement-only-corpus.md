# Placement-only CP-SAT vs greedy differential corpus (#4139)

Second-round follow-up to the #4139 draft. The predictor-discovery
study established that greedy solve is cheaper than placement-only
CP-SAT solve on every measured shape (flash, MLP, sdpa). The
question that remained: does placement-only CP-SAT ever produce
a materially better placement decision than greedy on the corpus
we already consider important?

Runner: `harness/differential_corpus.py`.
Data: `data/differential_corpus/summary.json`,
`data/differential_corpus/fixtures/`.

## Method

For every test method declared on
`BaseLayoutSolverTests` in
`tests/inductor/test_scratchpad_solver.py`, capture the
`LifetimeBoundBuffer` set the test constructs, then hand a fresh
copy of that set to both `GreedyLayoutSolver` and
`CpSatLayoutSolver` (placement-only, `co_optimizing_lx_planning=False`,
`lx_planner_relayout=False`). Compute the CP-SAT spill objective
`sum(spill_cost(b))` over the buffers each plan did not place —
`spill_cost` is a pure function of the buffer, so evaluating on
either arm's plan is just a sum over its spilled set.

Classification:

- **A** — same resident set, same objective, same addresses.
- **B** — same resident set, same objective, different addresses.
- **C** — greedy strictly worse objective than CP-SAT.
- **D** — greedy strictly better objective than CP-SAT.
- **E** — one solver failed (invalid layout or exception).

## Result

35 test methods total; 28 successfully captured the buffer set.
The other 7 don't call `self.solve()` or `self.verify_layout()`
(e.g. `test_rejects_wrong_end_time` — assertion-only cases
that don't exercise a solver).

| class | count | meaning                                         |
|-------|------:|-------------------------------------------------|
| A     |    17 | identical placement between arms                |
| B     |     8 | same resident set + same objective; different addresses |
| C     |     1 | greedy worse than CP-SAT                        |
| D     |     1 | greedy better than CP-SAT                       |
| E     |     1 | both failed identically (invalid input rejected)|

**On this corpus, placement-only CP-SAT produces a strictly better
objective than greedy on 1 of 26 differential cases** (excluding
SKIP/E).

## The single C case (CP-SAT wins)

`test_largest_buffer_evicted_when_full`
(`data/differential_corpus/fixtures/test_largest_buffer_evicted_when_full.json`):

- Capacity 50, alignment 1.
- Three buffers, all live at ticks [0, 3]:
  a (size 10), b (size 20), c (size 30). All computed
  intermediates (`first_use_is_read=False`).
- Greedy places a@0, b@10, spills c → objective = spill_cost(c) = 60.
- CP-SAT places b@0, c@20, spills a → objective = spill_cost(a) = 20.
- Delta: greedy 3× the CP-SAT objective.

This is a **synthetic constrained-capacity example**. It exercises
exactly the kind of tie-breaking greedy is bad at: capacity is only
6.7× the total buffer size, so exactly one buffer must be spilled,
and greedy's "place buffers in order until you hit a wall, then
spill the last one that didn't fit" heuristic picks the largest
buffer (worst objective).

## The single D case (CP-SAT loses)

`test_simple_layout_below_alignment`
(`data/differential_corpus/fixtures/test_simple_layout_below_alignment.json`):

- Capacity 10, alignment 128.
- Three buffers each size 3 or 4, all live at ticks [0, 1].
- Greedy places buffer0@0, spills the others → objective = 14.
- CP-SAT places nothing → objective = 20.

This is a **synthetic capacity < alignment edge case**. CP-SAT
works in alignment-sized units:
`_capacity_units = 10 // 128 = 0`, so its model has zero
addressable slots. Greedy doesn't do that integer division and
places one buffer at address 0 because nothing else is live
there. Capacity < alignment does not happen in production LX
planning (LX capacity is 2 MiB; alignment is 128 bytes).

## Cross-check with measured workload data

On the eight measured workloads in `data/structural_sweep/`
(flash 512x1024/2048/4096/8192, mlp L=96/128/192/384) under
`SPYRE_LX_PLANNER_RELAYOUT=0`:

- `max_live_bytes / LX_capacity`: 15.6% – 71.8%. Never close to
  capacity-limited.
- Resident set at `(name, size)`: IDENTICAL between arms on
  every shape (symmetric difference = 0).
- Spilled bytes: identical.
- CP-SAT spill objective: identical (same buffers spilled →
  same sum of spill_costs).

**On the compiled workloads measured here measured in this study,
placement-only CP-SAT and greedy produce byte-for-byte the same
resident-vs-spilled split and therefore the same spill objective.**
The 1 C corpus case does not correspond to a shape any of these
workloads hits.

## Cross-check with #2062

The 11 LX-planning value-corruption failures documented in #2062
(post-fusion producer/consumer core-mapping disagreement) are
already mitigated for the placement-only path by
`demote_incoherent_lx_buffers` (#3378). The joint co-optimization
path (`layout_solver=cpsat` + `co_optimizing_lx_planning=True`)
fixes them structurally. Placement-only CP-SAT (`cpsat` + co-opt
`False`) does NOT fix them any more than greedy does. So the
correctness motivation from #2062/#3932 lands on the joint path,
not on placement-only CP-SAT.

## Reframed policy question

Given:

- Placement-only CP-SAT and greedy produce identical resident sets
  on every measured workload.
- Placement-only CP-SAT costs 6-250× more solver wall time than
  greedy on the same input.
- The one demonstrated placement-quality win is a synthetic
  capacity-constrained fixture that does not appear in the
  measured workloads.
- The correctness motivation for shipping CP-SAT (from
  #2062/#3932) lands on the joint co-optimizer, not on the
  placement-only path.
- The recent flip to `cpsat` default (#3978, `f66a996`) was
  explicitly a staging step: "Co-optimization will be deferred to
  a later PR once the cost model is refined."

The question changes from "when should we swap CP-SAT for greedy
on large graphs" to "does the current placement-only CP-SAT
default provide any measurable benefit on production workloads
that offsets its 6-250× solve wall time cost."

Answer from this corpus: **not on any workload we can measure**.
The one placement-quality advantage found is a synthetic
capacity-constrained test fixture.

The change this suggests for #4139 is **not** a threshold
selector. It is: **avoid placement-only CP-SAT and reserve
CP-SAT for the joint co-optimization path where its correctness
properties actually apply**. #3978 already deferred co-optimization
"once the cost model is refined"; if the shipping default is meant
to be the joint path eventually, the interim placement-only default
is a temporarily expensive configuration and reverting the
placement-only default to `greedy` (or keeping the joint
`cpsat`+co-opt path when that lands) is the cleaner interim state.

**Important compatibility caveat:** changing the global default
back to `greedy` in `config.py` also re-enables greedy's normal
paired-buffer LX-relayout behavior (greedy declares
`supports_paired_buffers=True`; CP-SAT inherits the base default
`False`). That is different from the solver-only fallback the
adaptive-solver draft (#4139) measured. Specifically, under a
plain `layout_solver="greedy"` config with the pod default
`SPYRE_LX_PLANNER_RELAYOUT=1`, `_prepare_buffers` calls
`collect_lx_relayout_plans` and expands the buffer universe;
this produces a different `n_specs` from CP-SAT (the previous
solver_ab_v2 study documented this at every flash shape).

So a "revert the default" patch has to also decide what
`lx_planner_relayout` does under the greedy-default. Options:

1. Revert `layout_solver` default to `greedy` and keep
   `lx_planner_relayout=True` — matches the pre-#3978 shipped
   behavior exactly.
2. Revert `layout_solver` default to `greedy` and set
   `lx_planner_relayout=False` as the default — matches what
   #4139's adaptive-solver arm B measured; identical downstream
   `n_specs` to placement-only CP-SAT. Behavioral change vs
   pre-#3978.
3. Keep `layout_solver=cpsat` as-shipped and route only the
   placement-only path through a fallback (what #4139 currently
   proposes with `adaptive_solver_threshold_ops`).

None of these are proposed as a change to make right now. The
core team should decide. This note documents the trade-offs.

## Next-step recommendation for #4139 (unchanged: DRAFT)

Keep #4139 draft. Update the body to say: after building a
placement-only differential corpus over the 28 shared solver
tests, placement-only CP-SAT produces a better objective than
greedy in 1 case (a synthetic capacity-constrained fixture), and
in 0 of the 8 measured workloads. This reframes the PR's
motivation from "avoid CP-SAT on large graphs" to "the interim
placement-only CP-SAT default provides no measured
plan-quality benefit and costs 6-250× more solve wall time; the
correctness motivation lives on the joint co-optimizer path
that's deferred by #3978."

Do not merge, do not request review, do not change global
defaults.

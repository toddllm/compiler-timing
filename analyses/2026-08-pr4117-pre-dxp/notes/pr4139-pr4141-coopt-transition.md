# #4139 / #4141 — strategic transition after joint CP-SAT co-optimizer becomes default

**Written 2026-08-31 for the Will handoff.** Captures the maintainer
feedback and architectural fork the #4139/#4141 stack is now waiting
on.

## Maintainer feedback

Dave Grove (`dgrove-oss`, author of the #3932 epic
"Default enable CP-SAT co-optimizer for lx_planning and core
division") commented on #4139 on 2026-08-31:

> I'm skeptical this is worth pursuing. We're moving to enabling
> CP-SAT based co-optimization of scratchpad allocation and work
> division within the next couple of days.

Paraphrased: joint CP-SAT co-optimization is imminent as the shipped
default; the placement-only CP-SAT path #4139 accelerates may become
the non-default path, or may go away.

Todd replied on 2026-08-31 acknowledging the scope-mismatch and
asking Dave whether placement-only will remain a meaningful supported
path after the switch or whether #4139 should be treated as
performance-study evidence for #3932 and closed. That decision is
maintainer-owned; both PRs are held Ready-for-Review and untouched
pending Dave's direction.

## Architectural implication

**#4139** only accelerates the placement-only path:

- entry: `CpSatLayoutSolver.plan_layout` (called when
  `co_optimizing_lx_planning=False`).
- certificate: greedy placement is accepted only when it attains the
  forced-spill lower bound of the residency objective, which is the
  scalar objective placement-only CP-SAT minimises. No parallelism
  or work-division optimum enters the certificate.

**#4139 does NOT accelerate**:

- `plan_layout_and_core_divisions` — the joint entry, which
  co-optimises core division alongside placement.
- The joint objective is not the same scalar residency objective the
  certificate proves greedy meets; it includes parallelism, balance,
  and (from #3810) an optional `cost_expr`. The forced-spill lower
  bound is not the joint objective's lower bound, and a greedy
  placement carries no core-division decision.

The certificate methodology cannot be trivially extended to joint
CP-SAT without redefining what "greedy is provably optimal" means for
the joint objective — a substantial new design task, not a mechanical
extension.

## #4141 coupling

**#4141**'s headline startup benefit compounds #4139: certified
placement-only compiles avoid loading OR-Tools entirely.

If joint CP-SAT becomes the shipped default:

- OR-Tools is actually needed on the default compile path.
- `_load_ortools()` fires on the first joint compile, paying the
  ~1.4 s SWIG bootstrap that #4141 was designed to skip.
- **#4141's measured -1 to -2 s startup win no longer applies** to
  the shipped default; it survives only for callers that stay on
  placement-only (via `co_optimizing_lx_planning=False`) or that
  select a non-CP-SAT `layout_solver`.

Independent value that still holds regardless of the switch:

- Lazy loading remains cleaner hygiene than an eager module-top
  import: `import torch_spyre` stays cheap, `find_spec` availability
  probe replaces a bare `raise ImportError` on missing-ortools
  installs (s390x/ppc64le behavior preserved exactly).
- The deterministic thread-safety and idempotence tests (`
  _do_ortools_import` seam, publication-under-lock invariant) are
  independent of which CP-SAT entry callers use.

Whether that residual hygiene value is worth merging without the
compounding startup win is a maintainer judgment, not a
performance-study answer.

## Status

- **#4139**: technically complete / Ready-for-Review /
  MERGEABLE / all focused tests green. **Strategic merge value
  awaiting maintainer decision because joint co-optimization is
  imminent.**
- **#4141**: technically complete / Ready-for-Review / MERGEABLE /
  all 5 required top-level workflows green. **Strategic value
  coupled to #4139 and to whether placement-only CP-SAT remains a
  meaningfully supported path after the switch.**

Neither PR is dead or obsolete. Both are held for maintainer
direction. Do not close either without Dave or another responsible
maintainer answering the architectural question.

Classification:

- `RESEARCH_EVIDENCE = durable`
- `PRODUCTION_IMPLEMENTATION_VALUE = pending architecture decision`
- `TODD_FINAL_CODE_STACK = #4139 + #4141`
- `MERGE_DECISION = PENDING_MAINTAINER_COOPT_DIRECTION`
- `NO_NEW_TODD_PR = YES`

## Durable research value (not wasted)

The #4139 work produced evidence and methodology that remains useful
for the #3932 compile-time/scalability track regardless of merge
outcome:

- **Placement-only CP-SAT scales badly** at production graph sizes
  (harness data in `data/hybrid_certified_corpus_v2/`,
  `data/capacity_pressure_sweep_v2/`, historical study in
  `notes/certified-greedy-seed.md`).
- **Greedy often reaches the same residency objective** on captured
  planner-buffer sets from compiled workloads (39 of 40 measured
  capacity-pressure points; 20 of 28 corpus scenarios).
- **The certificate methodology proved when skipping placement-only
  CP-SAT is safe** (forced-spill lower bound via
  `MemoryPlanSolver.record_exclusions`; representability check
  against `_capacity_units`).
- **The capacity-pressure case proved greedy is not universally
  optimal** (flash-512x8192 at 25% capacity — CP-SAT strictly wins,
  and the certificate correctly rejects).

None of that survey work depends on the joint switch. The framing
just changes from "here's a merge candidate for placement-only" to
"here's evidence about placement-only CP-SAT scaling that feeds into
the #3932 architectural decision."

## Handoff consequence — do NOT extend the certificate into the joint solver

**Explicit instruction to Will**: do not spend time trying to lift
#4139's certificate into `plan_layout_and_core_divisions`. The joint
objective has additional axes (parallelism, balance, optional
`cost_expr`) that the placement-only forced-spill lower bound doesn't
cover. Extending the certificate would require designing a new
lower-bound proof for the joint objective — a real research task,
not a rewrite.

Instead, once the joint configuration lands as the shipped default,
the first performance task on the new default path is:

### First joint-CP-SAT performance experiment

**Profile the actual joint CP-SAT path at production graph scale.**
Do not assume the joint path has the same scaling behavior as
placement-only CP-SAT.

Reuse the #4117 harness methodology:

1. **Frontend boundary**: intercept the DXP subprocess as
   `harness/frontend_reconnaissance.py` does; bound wall-time while
   still exercising the full frontend.
2. **Break out the joint model's cost separately**:
   - model-building time (constructing `_LifetimeBufferWithCpVars` /
     `_CoreDivisionBufferWithCpVars` wrappers, adding
     `AddNoOverlap2D` and slicing-match constraints).
   - CP-SAT solve time (level 1 residency, level 2 parallelism,
     level 3 balance, plus #3810's optional `cost_expr` branch).
   - `_wrap`'s alignment scaling.
3. **Deterministic counters**:
   - `n_buffers`, `n_core_division_buffers`, mean
     `len(core_divisions)` per buffer.
   - decision-variable count and constraint count if the
     `cp_model.CpModel` object exposes them.
   - `record_exclusions` size.
4. **Scale sweep** against graph size using the same production-
   shaped workloads (flash, MLP, sdpa) with captured planner-buffer
   sets under `data/captured_buffers/*.pkl`; add joint-path captures
   if they don't exist yet.
5. **Distinguish fixed startup from solve scaling.** Fixed startup
   (torch/torch_spyre import, first Spyre tensor init) is
   independent of the switch; the interesting question is how the
   joint solver's model-build + solve wall grows with graph size.
6. **Compare against the placement-only baseline only as
   historical context** — the previous 138 s / 35.7 s / ~9 ms per
   spec numbers are from a pre-#4139 world with a different solver
   configuration. Do not assume any of them apply to the joint
   default.

If the joint path exhibits the same super-linear scaling that
placement-only did, the #3932 team will want to know quickly and
will need the evidence. The scaffolding for that measurement is
already in `analyses/2026-08-pr4117-pre-dxp/harness/` — reuse it,
don't rewrite it.

## Reference

- #4139 PR: <https://github.com/torch-spyre/torch-spyre/pull/4139>
- #4141 PR: <https://github.com/torch-spyre/torch-spyre/pull/4141>
- #3932 Epic: `Default enable CP-SAT co-optimizer for lx_planning
  and core division`
- Dave's #4139 comment: 2026-08-31T15:19:21Z
- Todd's reply: 2026-08-31 (issue-comment posted this pass)

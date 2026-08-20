---
name: frontend-compiler-impact
description: Evaluate the Torch-Spyre frontend compiler impact of a code change (GitHub PR, commit range, or local branch). Use when the user asks things like "what frontend compiler impact does PR #XXXX have?", "does this branch regress compile time?", "which frontend passes could this diff affect?", "what should I benchmark for this change?", "scan current PRs for frontend impact?", or "did this optimization actually improve the intended scaling law?". The skill enforces a discipline of static triage first, then targeted device measurement only when warranted, driven by the empirical knowledge captured in `analyses/2026-08-pr3806-frontend-timing/` and `analyses/2026-08-frontend-scaling-cross-workload/`.
version: 0.2.0
---

# Frontend Compiler Impact Skill

**Purpose.** Given a code change to `torch-spyre` (a GitHub PR, a
commit range, or a local branch), decide whether it can affect
Torch-Spyre's frontend compilation, predict where, choose the
minimum-information experiment that could confirm or refute the
prediction, run it if warranted, and classify the result. This
skill encodes what the two committed compiler-timing studies in this
repository already established, so a fresh Claude Code session can
apply that knowledge without re-reading everything.

The primary success criterion is **discipline**, not throughput.
Correctly labeling a PR as "no run necessary" is as valuable as
finding a regression.

## The decision process (top-level)

Run this as a state machine. Do not skip stages.

```
1. resolve target       → concrete base/head SHAs and diff
2. static triage        → change → compiler stage(s) → impact hypothesis
3. select experiment    → Level 0 / 1 / 2 / 3 / 4 (see below)
4. commit prediction    → write 01-static-assessment.md, 02-experiment-plan.md
5. measure (if any)     → base/head paired, cold, isolated
6. classify             → 7 defined verdicts
7. attribute            → why did numbers move? include structural deltas
8. retrospective        → 04-retrospective.md; update skill only after
```

Every case produces:

- `01-static-assessment.md` — written BEFORE any run.
- `02-experiment-plan.md` — written BEFORE any run.
- `03-results.md` — written AFTER running (or "no run" verdict).
- `04-retrospective.md` — written LAST.
- `impact.json` — machine-readable report, schema in `references/impact-report.schema.json`.

## Inputs the skill accepts

- **GitHub PR**: number or URL. Resolve to CURRENT base branch, base
  SHA, head branch, head SHA — never assume `main` is the base for
  stacked PRs.
- **Commit range**: `<base>..<head>`.
- **Local branch / diff**: current branch vs merge-base; staged or
  unstaged only when explicitly requested.
- **Open-PR scan**: fetch current open torch-spyre PRs, triage them
  without running anything, produce a ranked list. See
  `references/scan-mode.md`.

`scripts/resolve_target.sh <pr#|range>` produces a normalized target
record; use it before doing anything else.

## Level ladder — how much device time to spend

Encoded in `references/measurement-policy.md`; summary:

| Level | Use when | Cost | Output |
|---|---|---|---|
| **0** | docs-only / CI-only / test-only / runtime-only / clearly unrelated frontend code | zero device time | static assessment + no-run verdict |
| **1** | localized change with clear affected pass; can be probed with one sentinel at one point | 1 sentinel × 3 samples base + 3 samples head (paired) | targeted comparison |
| **2** | shared infra; mechanism known to vary by workload; cross-workload check needed | 2 sentinels × 3+3 samples each | cross-workload confirmation |
| **3** | change claims/fears altered complexity | 2 sentinels × 3 samples each at two graph sizes so 4→8 or n→2n growth ratio is measured | scaling-law comparison |
| **4** | Level ≤3 showed real movement and cause needs attribution | substage instrumentation, cProfile diagnostic, per-pass counters — from a diagnostic run, not a timed run | attribution report |

**Do not** deep-profile every PR by default. Escalate on evidence,
not on suspicion.

## Static triage rules (from empirical knowledge)

Full list in `references/compiler-stage-map.md`. Reusable rules:

- **`torch_spyre/_inductor/dedup_constants.py`** — dedup follows
  `t ∝ operations × duplicates` (measured, both workloads). Shape
  generalizes; constant is workload-dependent (~4.6× larger on
  richer inner_fns). Level ≥1 if the change alters
  `_redirect_consumers`, `_drop_constant`, or the loop over duplicate
  groups.
- **`torch_spyre/_inductor/wsr/coarse_tile.py` and
  `wsr/coarse_tile_hints.py`** — `_maybe_coarse_tile_hints` is the
  dominant pass in WSR/KV-chunked workloads. 96.6% of it at n=8 is
  in `_patch_retiled_load_indexes` (74.5%) and `_plan_tiling_propagation`
  (22.1%). Both grow near-quadratic. Level ≥1 if a change touches
  either. Level 3 if the change claims to alter their complexity.
- **`torch_spyre/_inductor/optimize_restickify.py`** — pre-#3812 had
  exponential beam blowup from constant-fill layout candidates
  (issue #3687). PR #3812's `_all_constant_layouts` →
  `[generic_layout(op)]` collapsed the diamond source. Post-fix
  restickify still scales 2.2–2.4× per doubling in workload B; that
  mechanism is NOT source-attributed. Level ≥1 for changes to beam
  logic, candidate generation, or STL enumeration.
- **`torch_spyre/_inductor/scratchpad/`** — same code shows different
  scaling: linear on workload B, superlinear (n^~1.45) on workload A.
  Root cause is **UNRESOLVED**. The `_extern_kernel_in_live_range`
  hypothesis was prototyped and refuted by measurement. **Do not
  reason about scratchpad performance from source structure alone.**
  Level ≥1 only if the change touches the actual timed path;
  test/validation changes → Level 0.
- **`torch_spyre/_inductor/propagate_layouts.py` and
  `propagate_hints.py`** — measured near-linear on both workloads.
  Level 1 (targeted) unless the change alters candidate generation
  (then think restickify).
- **`torch_spyre/_inductor/{fusion,scheduler,work_division}.py`** —
  minor share of measured frontend time. Level 1 targeted.
- **`torch_spyre/_inductor/spyre_kernel.py`** — kernel codegen was
  <1% of `compile_fx` at every measured point. Level 0 unless the
  change plausibly changes generated kernel count or spec count.
- **`torch_spyre/csrc/` / `perm_layout_native.cpp`** — C-extension
  changes cannot be A/B'd by Python patching alone; require rebuild
  per revision. Level ≥1 with a rebuild plan; note explicitly in
  `02-experiment-plan.md`.
- **`torch_spyre/execution/async_compile.py:sdsc`** — external
  backend `dxp_standalone` wrapper. Backend growth is dominant at
  scale but separate ownership. If a change moves the backend
  handoff or output, report it, but classify as **backend impact
  only** unless the frontend surface also changed.
- **`tests/`** — test-only. Level 0 unless a shared test helper is
  imported by non-test code.
- **`docs/`, `CI/`, `.github/`, `README.md`** — Level 0 always.

## The "hot path may not execute" rule

Touching a file listed as a hotspot **does not** automatically mean
frontend-perf risk. The static triage must ask three questions:

1. Does the changed code execute on the timed compile path in a
   sentinel workload? (If a guard or option gates it, note the gate.)
2. Is the change on the hot inner loop of the pass, or on setup/
   validation/error paths?
3. Does the change alter the collections/constants that made the
   pattern quadratic in the first place, or is it a local edit that
   preserves the algorithm?

Only when all three answers point at real execution on the hot
inner loop does the static triage escalate above Level 1 targeted.

Explicit example: PR #3849's follow-up scratchpad-packer validation
changes touched `scratchpad/` but per description alter only
validation/guard behavior with unchanged valid layouts. Classify as
Level 1 targeted at most, not scaling.

## Sentinel workload registry

Full registry in `references/sentinel-workloads.md`.

- **`WA_baseline`** — Workload A (OpSpec/static tiled FA), `Lq=512,
  Lk=1024, H=8` baseline. Fast (~90 s per sample). Exercises dedup,
  scratchpad, layout propagation, restickify at moderate size, generic
  graph growth.
- **`WA_scaling_pair`** — same workload at `Lq=512, Lk=1024` (base)
  and `Lq=512, Lk=2048` (2× graph). Growth-ratio comparison.
- **`WA_large`** — `Lq=512, Lk=4096` or `Lq=512, Lk=8192`. Superlinear
  scratchpad territory. Use only for Level 3 when scratchpad or
  larger-graph mechanisms are in play.
- **`WB_n4`** — Workload B (KV-chunked FA from PR #3812 recipe),
  `n_chunks=4`. Fast (~60 s). Exercises `_maybe_coarse_tile_hints`,
  restickify beam, dedup under richer inner_fn.
- **`WB_scaling_pair`** — `n_chunks=4` and `n_chunks=8`. Growth-ratio
  comparison. This is the pair that revealed coarse-tile-hints
  3.52× → 2.80× shift under the reverse-adjacency prototype.
- **`WB_n8`** — `n_chunks=8` alone. Use when the change is expected
  to be visible at n=8 but not n=4.
- **`PR_local`** — the PR's own regression test or a minimal
  reproducer derived from it. Use when neither workload family
  exercises the changed path.

Selection is driven by the static-triage tags. The registry file
lists each workload's exact command, expected runtime class, whether
device is required, correctness oracle, and known limitations.

## Measurement discipline

Enforced by `references/measurement-policy.md`. Non-negotiable:

- Spyre device is exclusive per process → runs are strictly serial.
- Fresh Python process per timed sample.
- Fresh unique `TORCHINDUCTOR_CACHE_DIR` per sample; `rm -rf` before
  use.
- No `TORCH_COMPILE_DEBUG` / `TORCH_LOGS` / verbose logs during
  timed samples.
- CPU correctness reference runs OUTSIDE the timed region.
- **Paired/interleaved base/head samples** (base1 head1 base2 head2
  base3 head3), not all-base-then-all-head, to reduce time-of-day
  drift.
- 3 cold samples per point is the default; n=1 acceptable for
  expensive points if clearly labeled.
- Report median AND spread; do not manufacture significance from n=3.
- For C-extension changes, rebuild per revision.

## What to measure

Full metric list in `references/interpretation-guide.md`. The core set:

- `first_call_wall`, `compile_fx_wrapper`
- `GraphLowering.run`, `GraphLowering.codegen`
- All six Spyre custom pass pipeline totals
- Individual pre-scheduling passes touched by the change (and the
  known top-6: `_maybe_coarse_tile_hints`, `dedup_and_promote_constants`,
  `optimize_restickify_locations`, `_maybe_scratchpad_planning`,
  `propagate_spyre_tensor_layouts`, `_distribute_work`)
- `SpyreKernel.codegen_kernel`, `sdsc_total`, `sdsc_bundle_gen`,
  `dxp_standalone`, `async_compile_wait`
- Structural counters: `fx_nodes_at_entry`, `n_specs`, per-pass
  `input_operations` and `ops_delta`

**When a change can alter generated graph structure**, ALWAYS compare
structural counters at head vs base. A pass that ran faster because
the graph shrank is a different result from the same graph compiling
more efficiently. Say which happened.

## Result classification — exactly seven verdicts

1. **FRONTEND IMPROVEMENT** — Spyre pass pipelines faster at head;
   effect exceeds observed spread on at least one measured point.
2. **FRONTEND REGRESSION** — Spyre pass pipelines slower at head;
   same spread test.
3. **NO MEASURABLE FRONTEND IMPACT** — deltas within observed spread
   on all measured points.
4. **STRUCTURAL CHANGE, PERFORMANCE NEUTRAL IN TESTED REGIME** —
   FX-nodes / n_specs / other structural counters changed but pass
   time did not, or changed proportionally with graph size.
5. **BACKEND IMPACT ONLY** — `dxp_standalone` moved; Spyre frontend
   passes did not.
6. **ACTIVATION-SPECIFIC IMPACT** — change affects a code path that
   is gated (feature flag, argument, layout), and default-path
   compile is unaffected.
7. **INSUFFICIENT EVIDENCE** — measured but variance/sample size /
   experiment mismatch prevents classification.

Report absolute deltas and relative deltas. Compare effect size to
run spread — do not use a rigid 5% threshold. A 20 ms shift in a 50 s
pass is noise; a 10 s shift matters even if `compile_fx` is
backend-dominated.

## Prediction before measurement

Written to `01-static-assessment.md` and `02-experiment-plan.md`
BEFORE any run. Include:

- Affected stages / passes with confidence.
- Expected direction (improvement / regression / neutral / unknown).
- Magnitude class: none / small / moderate / potentially large /
  unknown.
- Selected sentinels + rationale.
- Metrics expected to move.
- Metrics expected NOT to move.
- Failure modes for the prediction — how would we know if the
  static hypothesis were wrong?

The retrospective `04-retrospective.md` compares prediction to
measurement and updates the skill only after documenting the
original prediction/result.

## Scientific discipline (carry forward from prior studies)

**Static source complexity is a hypothesis; measurement determines
priority.** The scratchpad `_extern_kernel_in_live_range` prefix-sum
was a plausible source-level fix. Prototype: 1–2% within noise. The
hypothesis was wrong. The skill preserves this discipline by:

- Ranking predictions with confidence and flagging static-only
  hypotheses as such.
- Marking every opportunity/estimate as `MEASURED` or `ESTIMATED`.
- Encouraging Level 0 verdicts when justified.
- Recording refuted hypotheses in the study's retrospectives so the
  next PR does not repeat the mistake.

## Invocation

From this repo, given a PR number or range:

```
# Resolve target
.claude/skills/frontend-compiler-impact/scripts/resolve_target.sh 3890 > /tmp/target.json

# Or: current-branch diff
.claude/skills/frontend-compiler-impact/scripts/resolve_target.sh HEAD..

# Static triage — reads the diff, emits per-file classification
.claude/skills/frontend-compiler-impact/scripts/static_triage.py /tmp/target.json

# BEFORE any device time — alignment gate check:
# Verify per-touched-file blob equality with the PR's actual base.
.claude/skills/frontend-compiler-impact/scripts/check_alignment.sh \
    torch-spyre/torch-spyre 3890 /home/tdeshane/pr3806/torch-spyre
# exit 0 → Tier 2 satisfied (in-place patch swap is scientifically valid)
# exit 1 → Tier 2 fails, must escalate to Tier 3 isolated checkout
# exit 3 → pod tree missing a PR-touched file, Tier 3 required

# Scan mode (many PRs, no runs)
.claude/skills/frontend-compiler-impact/scripts/scan_open_prs.sh torch-spyre/torch-spyre
```

Then write the four case documents (`01`..`04`) using the templates
in `references/case-templates/`.

The device-side measurement scripts assume an available Spyre pod
and the same cold-compile hygiene as the primary study
(`analyses/2026-08-pr3806-frontend-timing/patches/sweep-driver.sh`
is the reference implementation).

## Isolated-checkout workflow (v0.2)

When the pod tree does not align with a PR's base (older `main`
snapshot, PR touches C-extension, PR needs newer system libs), the
skill supports an isolated-checkout path:

```
# 1. Pod-tree alignment check
git apply --check <pr>.diff              # in the pod tree
# CLEAN  → in-place patch swap OK
# FAIL   → isolated checkout required

# 2. Create the isolated checkout at the PR's exact SHA
.claude/skills/frontend-compiler-impact/scripts/setup_isolated_checkout.sh \
    <sha> <dest-dir>
# clones torch-spyre, fetches refs/pull/*/head if needed,
# symlinks _C.so from the pod's baseline (if ABIs match),
# smoke-tests the import.

# 3. Run a sample with the timing shim
.claude/skills/frontend-compiler-impact/scripts/run_isolated_sample.sh \
    <tree-dir> <harness.py> <out.json> [harness args…]
# The shim installs compile_fx_wrapper, pipeline:*, sdsc_*
# instrumentation at import time — no tree modification needed.
```

If `_C.so` ABIs have diverged (e.g. the PR's base has newer C-extension
symbols than the pod's shared `_C.so`), the isolated checkout will
error on the smoke import. Options in order of preference:

- Use the PR's OWN base commit as the isolated base (rather than a
  shared `_C.so`) — build `_C.so` fresh in the isolated tree.
- If the fresh build itself fails (system libs too old — profiler
  headers, AIupti CBIDs, spyrecode-host-functions), the correct
  verdict is `INSUFFICIENT_EVIDENCE` on that measurement attempt.
  Do not compromise the science to run something that isn't
  the PR's base.

## Files under this skill

```
.claude/skills/frontend-compiler-impact/
    SKILL.md                              — this file
    references/
        compiler-stage-map.md             — stage-by-stage triage rules
        sentinel-workloads.md             — registry with commands
        measurement-policy.md             — cold-compile hygiene, pairing,
                                            pod-tree alignment gate (v0.2)
        interpretation-guide.md           — metric list + classification
        scan-mode.md                      — open-PR triage
        impact-report.schema.json         — machine-readable output
        case-templates/                   — 01/02/03/04 templates
    scripts/
        resolve_target.sh                 — normalize PR / range / branch
        static_triage.py                  — diff → per-file stage tags
        scan_open_prs.sh                  — list + rank open PRs
        emit_impact_report.py             — construct impact.json
        setup_isolated_checkout.sh        — v0.2: clone at SHA, symlink _C.so
        timing_shim.py                    — v0.2: runtime monkey-patch
                                            instrumentation for isolated tree
        timing_recorder.py                — v0.2: bundled recorder impl
        shim_runner.py                    — v0.2: shim-first harness runner
        run_isolated_sample.sh            — v0.2: orchestrator
        check_alignment.sh                — v0.2 fix: per-touched-file blob
                                            equality check (Tier 2 gate)
```

## Where this skill knowledge came from

- `analyses/2026-08-pr3806-frontend-timing/` — workload A detailed
  measurements, dedup `ops × dups` model, per-pass scaling table,
  `compile_fx_wrapper` four-bucket decomposition.
- `analyses/2026-08-frontend-scaling-cross-workload/` — workload B
  measurements, 100% coarse-tile-hints substage attribution,
  restickify beam-frontier evolution pre/post PR #3812, dedup
  out-of-sample generalization, scratchpad measured null, extra-timers
  closure of `compile_fx_wrapper`, measured coarse-tile
  reverse-adjacency prototype.
- `analyses/2026-08-frontend-impact-skill-validation/` — validation
  study for this skill. Static-triage cases: PR #3871 (test-only,
  correct no-run), PR #3873 (activation-specific gated), PR #3849
  (static-only, C-extension blocked), PR #3890 (isolated-checkout
  blocked by system-lib drift). Machinery-validation control:
  `local-revadj-prototype` (coarse-tile reverse-adjacency — full
  measurement flow on a known-positive change, verdict
  FRONTEND_IMPROVEMENT). Novel-change attempt: `pr-3868` (SDSC
  json caching — initial marginal-patch measurement was retracted
  after the alignment gate was tightened; Tier 3 isolated-checkout
  retry blocked by pod system-lib age; final verdict
  INSUFFICIENT_EVIDENCE. The retraction motivated the current Tier 2
  policy: per-touched-file blob equality with the PR's actual base).

Read those studies' `SUMMARY.md` and `notes/findings.md` when a
compiler-timing refresher is needed. The skill's `references/`
files distill the reusable rules; those studies are the source
data.

## What this skill is NOT

- Not a benchmark runner. It selects the smallest experiment that
  can decide the question and stops.
- Not a source auditor. It uses source structure to form
  hypotheses, not to declare conclusions.
- Not a substitute for correctness testing. Correctness impact
  is reported separately from performance impact.
- Not authoritative about the backend `dxp_standalone`. Backend
  ownership is separate; the skill notes backend movement but
  does not diagnose it.

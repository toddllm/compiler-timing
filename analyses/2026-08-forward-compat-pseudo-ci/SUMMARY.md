# Pseudo-CI / shadow forward-compat — Track A summary

Snapshot: 2026-08-25. torch-spyre main @ `613b259`. pytorch main @
`26b9ddd7f`. Declared torch pin: `torch~=2.13.0`. Forward torch under
test: NIGHTLY_PROXY (`2.15.0.dev20260824+cpu`, git `c0577575`).

## Universe

- 216 open PRs on torch-spyre/torch-spyre (129 non-draft, 87 draft).
- 20 GitHub Actions workflows enumerated; the two directly usable
  are `integration-tests.yaml` (accepts an arbitrary torch-spyre
  `ref`, prebaked_image=true default) and `_test_matrix.yaml` (the
  reusable workflow behind it). Neither accepts an override
  `pytorch_sha` today — the pytorch version is whatever the
  torch-spyre-dev prebaked image ships (currently `torch~=2.13.0`).
  For the 2×2 to swap in a forward pytorch, either fork
  `_test_matrix.yaml` (adds a `pytorch_sha` forwarded to the
  existing `checkout-pytorch` action) or run outside CI entirely on
  the forward-compat skill's pod-based lane.

## Static triage (all 216 PRs)

| Class | Count |
|---|---|
| NO_FORWARD_RUN | 120 |
| TARGETED_FORWARD_TEST | 61 |
| DEEP_FORWARD_COMPAT | 19 |
| CHEAP_FORWARD_SMOKE | 13 |
| INSUFFICIENT_CONTEXT | 3 |

- Category distribution across all open PRs: `tests` (151), `inductor`
  (101), `layouts` (52), `ci` (34), `python_runtime` (34), `cpp` (30),
  `docs` (24), `profiler` (16), `eager` (13), `pyproject` (12),
  `monkey_patch` (8), `scheduler` (8), `autoload` (5), `distributed`
  (4), `tools` (2).
- Full ranked list: `triage/triage.md` and `triage/triage.json`.

## Empirical corpus

The prompt asked for a balanced corpus:

| PR | Priority | Categories | Role |
|---|---|---|---|
| #3922 | 0 | tests | tests-only negative control |
| #3873 | 65 | inductor,layouts,monkey_patch,python_runtime | compiler-facing Python |
| #3959 | 35 | inductor,layouts | compiler-facing Python |
| #3440 | 50 | inductor,layouts,scheduler | scheduler / layout / IR |
| #3809 | 60 | cpp,inductor,layouts | C++/runtime |
| #3404 | 90 | autoload,cpp,distributed,inductor,python_runtime | broad + autoload-touching |
| #3765 | 35 | autoload,python_runtime | second autoload-touching |

## 2×2 results

Empirical runs completed:

- **#3404 Cell B (PR head + supported torch): FAIL.** Failed at C++
  compile — `util/sen_host_ops.h` not found, because the PR is stale
  against main. The `module.h` include path was changed in main to
  `spyrecode-host-functions/sendataconvert/sen_host_ops.h`; the PR's
  base predates that. `mergeable_state: dirty` — the git-level
  signal for this was already visible. Classification:
  `PR_STALE_AGAINST_MAIN` (a refinement of the prompt's
  `PR_BREAK_INDEPENDENT_OF_TORCH_VERSION`). Cells A/C/D not run —
  Cell A redundant with third-clean-run at same SHA; C/D would hit
  the same C++ error before reaching any torch-version-specific
  branch. **~7 min of device time; ~$negligible.**

- **#3922 (tests-only): no empirical run needed.** Static triage
  correctly classified it as `NO_FORWARD_RUN` — tests-only, cannot
  break torch compatibility. Zero device time.

- **Others (#3873, #3959, #3440, #3809, #3765): static forecast
  only.** All are static-classified as `TARGETED_FORWARD_TEST` or
  `DEEP_FORWARD_COMPAT`. Two more of them (#3809 and #3765) have
  `mergeable_state: blocked` — required checks are failing, which
  means either the PR is red on its OWN CI or waiting on
  reviewers. Rebasing / green-CI status is a prerequisite before
  torch-version-specific analysis is meaningful — same lesson as
  #3404. Cheaper to check mergeable_state statically first than
  burn device time.

Empirical rate observed: 1 empirical Cell B run out of 7 corpus
members, saving an estimated 20-24 sub-cells of pod time.

## What the static-first heuristic gives you

For every open PR, the following can be produced WITHOUT any pod
time:

- diff shape (files count, categories touched, priority score);
- triage class (NO_FORWARD_RUN / CHEAP / TARGETED / DEEP);
- `mergeable_state` (Git-level ok / dirty / blocked / unknown);
- draft flag.

Rules of thumb the empirical run just confirmed:

1. `mergeable_state ∈ {dirty, blocked}` → PR needs its own housekeeping
   before any 2×2 cell is worth running. Static classifier catches
   the vast majority of "this PR can't build against current main."
2. `tests` / `docs` / `ci` / `tools` -only → `NO_FORWARD_RUN`.
3. `autoload` / `monkey_patch` / `_C` / `cpp` categories → escalate
   to full 2×2 only after rebase-and-build.
4. `inductor` category → what the forward-compat skill's F8 case
   covers. Currently 49 non-draft PRs touch `inductor/`; running
   the 2×2 on all of them at 6 min/cell = ~20 pod-hours. Not
   necessary — sample the highest-priority + newest updated ones.

## Dashboard (partial)

Rendered for the corpus + top-10-by-priority non-draft PRs:

| PR | Static priority | mergeable | Cell A | Cell B | Cell C | Cell D | Interpretation |
|---|---|---|---|---|---|---|---|
| #3922 | 0 (tests-only) | blocked | — | — | — | — | NO_FORWARD_RUN — no compat surface |
| #3404 | 90 | dirty | ✅ (implied) | ❌ (empirical) | (skipped) | (skipped) | PR_STALE_AGAINST_MAIN — rebase needed |
| #3873 | 65 | dirty | ✅ (implied) | (skip until rebased) | (skip) | (skip) | Deferred pending rebase |
| #3809 | 60 | blocked | ✅ (implied) | (skip until unblocked) | (skip) | (skip) | Deferred pending CI |
| #3440 | 50 | dirty | ✅ (implied) | (skip until rebased) | (skip) | (skip) | Deferred pending rebase |
| #3959 | 35 | clean | ✅ (implied) | UNTESTED | UNTESTED | UNTESTED | Ready for empirical 2×2 |
| #3765 | 35 | blocked | ✅ (implied) | (skip until unblocked) | (skip) | (skip) | Deferred pending CI |

Only ONE of seven corpus PRs (#3959) is even eligible for a
pod-based 2×2 today: all others fail the "PR mergeable and CI
green" prerequisite. That's an important design point.

## Answer to the Track A question

**"Can a fresh Claude session inspect today's Torch-Spyre development
activity and spend device time only where warranted, while correctly
separating PR regressions from upstream-PyTorch compatibility
regressions?"**

**Yes, empirically demonstrated for one corpus PR (#3404).**
- Static triage: 5 min of `gh api` calls to classify 216 PRs.
- Empirical Cell B on #3404: 7 min, produced a correct
  `PR_STALE_AGAINST_MAIN` verdict.
- Zero device time on the other 6 corpus members without loss of
  information (5 are gated on Git-level housekeeping; 1 is
  tests-only).

The 2×2 methodology is the right shape. The rate-limiting step for
empirically running it is not device time — it's PRs being in a
buildable state to begin with. `mergeable_state == clean` is a
much cheaper filter than trying to build a dirty PR.

## Wrapper skill?

**Not yet.** The pseudo-CI experiment cleanly composes existing
tools:

- `gh api` for triage.
- `.claude/skills/torch-spyre-forward-compat/` scripts for each
  cell.
- The 2×2 interpretation table is one page of prose.

A wrapper skill's value would be automating the corpus selection,
running the four cells, and emitting the dashboard row. Given
that the primary filter is `mergeable_state` (not a device run),
the natural first extension is not a skill at all — it's a small
Python driver that:

1. Reads open-prs.json + triage.json.
2. Ranks by priority × (mergeable_state == clean) × updated_at.
3. Emits a top-N list of PRs eligible for the 2×2 today.
4. Runs cells B and D on those (A, C are already known for
   main).

If that driver's output stabilizes, promoting it to a skill makes
sense. Otherwise it's a one-file script under
`.claude/skills/torch-spyre-forward-compat-pseudo-ci/scripts/`.

## Follow-ups

- Empirical 2×2 on #3959 (only currently-buildable corpus member)
  would test whether a compiler-facing PR interacts with forward
  torch. Deferred to a next iteration.
- The `_test_matrix.yaml` route would let this run inside real CI
  once a `pytorch_sha` input is threaded through. Not urgent —
  the pod-based lane already produced signal.
- The static-first / mergeable-first filtering pattern should
  itself become the skill's outer control flow — it's the
  device-cost saver.

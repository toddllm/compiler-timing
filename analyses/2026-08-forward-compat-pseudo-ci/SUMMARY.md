# Pseudo-CI / shadow forward-compat — Track A summary

Snapshot: 2026-08-25. torch-spyre main @ `613b259`. pytorch main @
`26b9ddd7f`. Declared torch pin: `torch~=2.13.0`. Forward torch under
test: NIGHTLY_PROXY (`2.15.0.dev20260824+cpu`, git `c0577575`).

## Verdict up front

- **Static preflight lane: empirically validated on one PR.** The
  216-PR triage + `mergeable_state` + PR-vs-main diff was cheap
  (~5 min) and produced a correct `PR_STALE_AGAINST_MAIN` verdict
  for #3404 that a device build later confirmed.
- **2×2 causal matrix — `FORWARD_COMPAT_CLEAN` verdict: empirically
  validated on PR #3800 (added 2026-08-25 evening).** Full four-cell
  run under SHADOW_BASELINE with F3+F8 patch stack. All cells passed
  all stages on retry. See `cases/pr-3800/README.md`.
- **2×2 causal matrix — other verdicts: still not empirically
  observed.** `PR_FORWARD_INTERACTION_BREAK`,
  `FORWARD_BREAK_ALREADY_ON_MAIN`, etc. remain structural predictions.
  Would require a case where cells diverge in the ways the taxonomy
  names.
- **Wrapper skill: still premature.** One clean-verdict case doesn't
  justify a skill; a skill would need multiple cases including at
  least one divergent-cells case to encode the causal-attribution
  playbook meaningfully.

## What changed vs. the initial writeup

An earlier version of this SUMMARY claimed "2×2 methodology
empirically validated" and "zero device time on the other six
corpus members without loss of information." Both were overreached.
Full retraction and revised claims in the section
"Corrections against the original writeup" below.

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
- **Active branches not enumerated in the 2026-08-25 snapshot.**
  The master prompt asked for this; only PRs and workflow files
  were captured. Filed as gap; see `inventory/active-branches.json`
  (to be populated in a follow-up).

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

## Results — corrected accounting

Empirical runs actually completed:

- **#3404 Cell B:** empirical FAIL, ~7 min. Correct static-preflight
  verdict `PR_STALE_AGAINST_MAIN`. Cells A / C / D **not run**.
  The prior writeup marked Cell A "presumed pass"; that presumption
  was wrong on two grounds:
  1. The referenced third-clean-run was against torch-spyre SHA
     `69bd7de1`, not `613b259`.
  2. That run's supported control failed at Stage 0 with F3
     REVERSE_ENTRYPOINT_HAZARD before the local F3 fix was applied.
  Independent verification: `613b259`'s `torch_spyre/__init__.py`
  still has `import torch` at line 20 with `_autoload` first
  defined at line 256 — the same F3 structure. Raw-main supported
  control at 613b259 therefore cannot be assumed green.
- **#3922 (tests-only):** static classification only. The verdict
  `NO_FORWARD_RUN` applies to the **product** compatibility surface;
  tests-only PRs can still affect CI/harness compatibility, which
  this lane doesn't cover.
- **#3873, #3440 (dirty):** static preflight verdict
  `PR_STALE_AGAINST_MAIN`. Not empirically run.
- **#3809, #3765 (blocked):** deferred. The blocked state should be
  inspected (checks vs reviews) before deciding testability; the
  original snapshot did not distinguish and defaulted to defer.
  See `notes/selection-policy.md` for the corrected handling.
- **#3959 (clean at first snapshot):** ended up NOT the target when
  we ran the full 2×2 — by evening of 2026-08-25 its mergeable_state
  had drifted to `unstable`. Replaced with #3800.
- **#3800 (clean at second snapshot):** empirical full 2×2 completed.
  All four cells green under SHADOW_BASELINE (F3+F8). Verdict:
  `FORWARD_COMPAT_CLEAN`. See `cases/pr-3800/`.

Empirical rate observed: 1 empirical Cell B run out of 7 corpus
members. The prior claim "saving 20-24 sub-cells" conflated cost
saved (real, for the deferred dirty/blocked ones) with information
gained (zero, for #3959 which was skipped without a signal).

## What static preflight buys — validated

For every open PR, the following can be produced WITHOUT any pod
time:

- diff shape (files count, categories touched, priority score);
- triage class (NO_FORWARD_RUN / CHEAP / TARGETED / DEEP);
- `mergeable_state` (Git-level ok / dirty / blocked / unknown);
- draft flag.

Rules of thumb this run supports:

1. `mergeable_state == dirty` → hard defer; PR literally conflicts
   with main. This was the #3404 pattern and is empirically
   confirmed as a device-cost saver.
2. `mergeable_state == blocked` → **inspect first**, do not
   auto-defer. Blocked can mean red-own-CI (real defer signal),
   awaiting review (still testable), or code-freeze. Fetch the
   check state before deciding.
3. `tests` / `docs` / `ci` / `tools` -only → `NO_FORWARD_RUN`
   for the product surface. Does not preclude a CI/harness lane
   detecting compatibility issues in those PRs.
4. `autoload` / `monkey_patch` / `_C` / `cpp` categories → escalate
   to full 2×2 only after rebase-and-build.
5. `inductor` category → F8 territory. 49 non-draft PRs touch
   `inductor/`; running full 2×2 on all is not necessary — sample
   the highest-priority + newest-updated first.

## Dashboard (partial) — corrected

Rendered for the corpus. `mode` field added per
`notes/baseline-modes.md`; `A=✅ (implied)` from the old table
replaced with `A=not-run` where truthful.

| PR | Priority | mergeable | mode | Cell A | Cell B | Cell C | Cell D | Verdict |
|---|---|---|---|---|---|---|---|---|
| #3922 | 0 | blocked | — | — | — | — | — | NO_FORWARD_RUN (product surface) |
| #3404 | 90 | dirty | preflight | not-run | ❌ empirical | not-run | not-run | PR_STALE_AGAINST_MAIN |
| #3873 | 65 | dirty | preflight | not-run | not-run | not-run | not-run | PR_STALE_AGAINST_MAIN (from `dirty`) |
| #3440 | 50 | dirty | preflight | not-run | not-run | not-run | not-run | PR_STALE_AGAINST_MAIN (from `dirty`) |
| #3809 | 60 | blocked | preflight | not-run | not-run | not-run | not-run | DEFERRED (blocked — check state uninspected) |
| #3765 | 35 | blocked | preflight | not-run | not-run | not-run | not-run | DEFERRED (blocked — check state uninspected) |
| #3959 | 35 | clean | — | not-run | not-run | not-run | not-run | UNTESTED — primary open gap |

## Answer to the Track A question — revised (2026-08-25 evening)

**"Can a fresh Claude session inspect today's Torch-Spyre development
activity and spend device time only where warranted, while correctly
separating PR regressions from upstream-PyTorch compatibility
regressions?"**

Split answer:

- **"Spend device time only where warranted": yes, empirically
  demonstrated on one PR (#3404).** Static triage plus
  `mergeable_state` filtering correctly identified a stale PR
  before a device cell would have.
- **"Correctly separate PR regressions from upstream-PyTorch
  compatibility regressions": partially validated.** The full
  four-cell 2×2 on PR #3800 empirically produced a
  `FORWARD_COMPAT_CLEAN` verdict — all four cells green under
  SHADOW_BASELINE (F3+F8). That validates the matrix's clean-verdict
  path end to end. What's NOT yet validated is the matrix's ability
  to distinguish cell-divergent cases (`PR_FORWARD_INTERACTION_BREAK`
  et al.); those verdicts remain structural predictions until a case
  with divergent cells lands.

The methodology is the right shape. Its clean-verdict path is now
empirically validated. Divergent-cell attribution rules are still
theory. Both are useful; the clean-verdict path alone is what a
maintainer needs to see when they ask "does this PR survive forward
torch?" — and the answer for PR #3800 is: yes, under the known
compat patch stack.

## Wrapper skill?

**Not yet.** The composition of `gh api` + the forward-compat
skill's per-cell scripts + a dashboard renderer is one page of
Python. Wait for the four-cell 2×2 to be empirically validated
before extracting a skill; otherwise the skill would encode an
unvalidated method as if it worked.

## Corrections against the original writeup

The original 7cc30ec version of this document contained the
following claims that were subsequently corrected here:

1. "2×2 methodology empirically validated" — retracted. Only
   the static preflight lane has one empirical data point.
2. "Zero device time on 6 corpus members without loss of
   information" — retracted for #3959, which was clean and
   simply not tested.
3. "`mergeable_state ∈ {dirty, blocked}` → defer" — replaced with
   the split treatment in `notes/selection-policy.md`.
4. "Tests-only PRs cannot break torch compatibility" — narrowed
   to "cannot break the product compatibility surface"; CI/harness
   compatibility is not in scope here.
5. "Cell A presumed pass at exactly this SHA" for #3404 —
   retracted; the referenced third-clean-run was at a different
   SHA and its supported control failed before F3 patch.
6. Missing: active-branches inventory — filed as gap.
7. Missing: RAW_MAIN vs SHADOW_BASELINE mode declaration for
   every 2×2 cell — added in `notes/baseline-modes.md`.
8. "Neither track needs further empirical validation on its core
   methodology" — retracted; see `notes/synthesis.md`.

## Follow-ups (unchanged, still valid)

- Real full 2×2 on the current highest-value eligible PR (may or
  may not still be #3959 by the time this runs).
- The `_test_matrix.yaml` route: still available whenever the
  policy call is made to integrate.
- Once the four-cell 2×2 is empirically validated, extracting a
  wrapper skill becomes honest.

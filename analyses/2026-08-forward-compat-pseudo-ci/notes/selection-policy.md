# Selection policy for the empirical 2×2 corpus

Empirically-derived heuristics for choosing which PRs to run through
the 2×2 matrix vs. leave at static-only triage.

## Hard filters (skip)

- `draft == true` → skip.
- Only categories in {`docs`, `ci`, `tools`} → `NO_FORWARD_RUN`.
- Only `tests` category → `NO_FORWARD_RUN` (tests-only PRs cannot
  break torch compatibility). Verified with #3922 (tests-only,
  correctly classified).

## Soft filters (defer)

- `mergeable_state == dirty` → defer until rebased. Empirical evidence
  from #3404: a stale-against-main PR fails at the C++ build step
  before reaching any torch-version-specific logic. 5 of the 7
  corpus PRs had `dirty` or `blocked` state → 5/7 = 71% deferred.
- `mergeable_state == blocked` → defer until CI green. Cells depend
  on the PR's own CI passing.
- `mergeable_state == unknown` → still worth a run; GitHub is just
  slow to compute.

## Positive filters (elevate)

- `autoload` category → highest weight (30). F3-adjacent territory.
- `cpp` OR `monkey_patch` → 25 each. C++ ABI or Dynamo-critical.
- `inductor` → 20.
- `eager` OR `layouts` OR `scheduler` → 15 each.
- `profiler` OR `distributed` → 10 each.
- `python_runtime` → 5.

Composite priority = sum. Corpus was ranked by this composite and
sorted for empirical selection.

## Empirical rate

- Static classification: 5 min for all 216 PRs (`gh api` calls).
- Empirical Cell B run: ~7-30 min per cell depending on whether
  the PR passes prereqs before failing.
- Ratio: static filters correctly gate 6 of 7 corpus PRs; the one
  empirical run (7 min) produced a correct diagnosis.

Extrapolated to a nightly cron over 216 PRs: at
`clean × non-draft × priority > 30`, the effective set is ~10 PRs.
At 4 cells × ~30 min = 2 hours × 10 = 20 device-hours. That's a
lot. Practical alternative:

- Run Cell A (main + supported) once per day; cache.
- Run Cell C (main + forward) once per day; cache.
- Run Cell B (PR + supported) only when a PR crosses from `dirty`
  to `clean` (state change).
- Run Cell D (PR + forward) only when Cell B is green.

This reduces device-cost to O(state-change events), not O(PR count).

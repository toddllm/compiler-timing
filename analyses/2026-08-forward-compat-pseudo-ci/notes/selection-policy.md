# Selection policy for the empirical 2×2 corpus

Empirically-derived heuristics for choosing which PRs to run through
the 2×2 matrix vs. leave at static-only triage.

**Read this alongside `baseline-modes.md`** — the mode
(RAW_MAIN vs SHADOW_BASELINE) affects which cells are worth
running at all.

## Hard filters (skip)

- `draft == true` → skip.
- Only categories in {`docs`, `ci`, `tools`} → `NO_FORWARD_RUN`.
- Only `tests` category → `NO_FORWARD_RUN` for the **product**
  compatibility surface. This is not a claim that tests-only PRs
  cannot affect any compatibility — they can affect CI/harness
  compatibility (test infrastructure imports, fixtures that pin
  behavior, xfail markers). The pseudo-CI lane's product-side
  matrix doesn't detect those; a separate CI/harness lane would.
  #3922 was correctly product-classified as `NO_FORWARD_RUN`.

## Soft filters — but treat them distinctly

`dirty` and `blocked` mean different things and should not be
collapsed into a single "defer" bucket.

### `mergeable_state == dirty`

**Hard defer.** The PR has literal merge conflicts against main.
The PR-head checkout doesn't compose with current main's file
tree; any device build will hit conflict-induced errors before
reaching a compat surface. #3404 is exactly this pattern.

Action: emit `PR_STALE_AGAINST_MAIN` from static preflight; do
not run a device cell.

### `mergeable_state == blocked`

**Inspect, then decide.** `blocked` means "not automatically
mergeable, but the branches don't literally conflict." Causes
include:

- Required reviews not met.
- Required status checks not passing (the PR's own CI is red).
- Branch protection rule waiting on something (approval,
  codeowner review).
- Repo-level restrictions (e.g. code freeze).

Only the second case ("PR's own CI is red") is a signal that the
PR is likely un-buildable. Required-review and code-freeze
gating say nothing about whether the PR compiles against current
main. Before deferring on `blocked`, fetch the actual check runs
and review state:

    gh api repos/{o}/{r}/pulls/{n} --jq '.mergeable_state, .rebaseable'
    gh pr checks {n} --json state,name,conclusion

If checks are green and only reviews are missing, run the 2×2
anyway — the PR is testable, it just isn't mergeable yet. If
checks are red, defer with reason "PR's own CI is red" and
record the failing checks in the case's `matrix.json`.

### `mergeable_state == unknown`

Still worth a run; GitHub is just slow to compute. Retry the
`gh api` call once before scheduling a device run.

## Positive filters (elevate)

- `autoload` category → highest weight (30). F3-adjacent territory.
- `cpp` OR `monkey_patch` → 25 each. C++ ABI or Dynamo-critical.
- `inductor` → 20.
- `eager` OR `layouts` OR `scheduler` → 15 each.
- `profiler` OR `distributed` → 10 each.
- `python_runtime` → 5.

Composite priority = sum. Corpus was ranked by this composite and
sorted for empirical selection.

## Empirical rate — with the corrected accounting

- Static classification: 5 min for all 216 PRs (`gh api` calls).
- Empirical Cell B run: ~7-30 min per cell depending on whether
  the PR passes prereqs before failing.
- Actual: 1 empirical Cell B run on #3404, produced a correct
  `PR_STALE_AGAINST_MAIN` verdict. That verdict was reachable
  from `mergeable_state: dirty` alone at ~0 device cost. The Cell
  B run confirmed the static signal but did not add causal
  attribution.

Do NOT claim the other six corpus PRs were "correctly filtered
without loss of information." #3959 in particular was
`mergeable_state == clean` at snapshot time, and no device cell
was run on it. Its state is genuinely UNTESTED, not "correctly
skipped." That's the one where information was left on the table.

## Extrapolation caveats

Extrapolating to a nightly cron over 216 PRs suggested "at
`clean × non-draft × priority > 30`, ~10 PRs qualify." That number
came from the 2026-08-25 snapshot. PR states drift; the real cron
would need to re-run the filter each night. Do not commit to the
"~10 PRs / night" figure without a fresh snapshot.

Practical device-budget-conscious cadence:

- Run Cell A / Cell C (main-side cells) once per SHA_main and
  cache; they change only when main advances or the shadow patch
  stack changes.
- Run Cell B (PR + supported) when a PR crosses from `dirty` to
  `clean`, or when its head SHA advances after that transition.
- Run Cell D (PR + forward) only when Cell B is green.

This reduces device-cost to O(state-change events), not O(PR
count) — but the "state change" trigger itself needs
implementing; today it's a hypothesis.

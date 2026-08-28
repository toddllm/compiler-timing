# PR #4113 — moved from Draft → Ready for review

## Timeline

- **2026-08-28 13:05 UTC**: PR #4113 opened as **Draft**.
- **2026-08-28 13:05–13:22 UTC**: CI ran. `tests` workflow includes
  a pod-level retry step for any suite that fails initially.
- **~2026-08-28 09:XX (laptop local)**: All required workflows
  reported success at the workflow level. Marked **Ready for
  review** via `gh pr ready 4113`.

## Pre-flip sanity checks (all passed)

| check                                       | result                                                           |
|---------------------------------------------|------------------------------------------------------------------|
| PR still open, still draft, unchanged head  | OPEN, draft=true, head=`ce34227e…` (unchanged since open)       |
| base/head SHAs unchanged                    | base=`813a2980…`, head=`ce34227e…`                              |
| mergeable state                             | `MERGEABLE`                                                      |
| new commits since open                      | none                                                             |
| unexpected file changes                     | none — still exactly 3 files                                     |
| required workflows green (workflow-level)   | `tests`, `upstream-pytorch-tests`, `linters`, `DCO`,             |
|                                             | `Enforce Test CI Coverage`, `oot-config-checker-tool` = success |
| `Inductor / Test Dedup Constants More`      | SUCCESS                                                          |
| review comments / automated feedback        | none                                                             |
| DCO / sign-off                              | SUCCESS (Signed-off-by: Todd Deshane <todd.deshane@ibm.com>)     |
| AI co-author trailers                       | none                                                             |
| forbidden content in diff                   | no diagnostics, no batch-removal, no private-repo refs           |

## One flaky failure — retry covered it

`run-tests / Inductor / Test Scratchpad Solver` (initial attempt)
came back FAILURE. The failure was device-init hardware:

```
RuntimeError: RAS::MCI::DdrInitRetryLimitExceeded —
"DDR maximum initialization retry Limit exceeded"
"Replace card"
```

- Error is raised in `torch_spyre/__init__.py:77` (Spyre C++ device
  init at import time), before any Python code from this PR runs.
- Every test in `test_scratchpad_solver.py` hit the same error
  ID; the runner-assigned Spyre card DDR controller failed to
  initialise.
- Test surface has nothing to do with `dedup_and_promote_constants`.

The `tests` workflow's `Collect suites for pod-level retry` +
`(pod-level retry)` mechanism re-ran the suite on a different pod
at 13:21 UTC and it succeeded:

```
run-tests / Inductor / Test Scratchpad Solver               FAILURE  (13:07)
run-tests / Collect suites for pod-level retry              SUCCESS
run-tests / Inductor / Test Scratchpad Solver (pod-level retry) SUCCESS  (13:21)
```

The `tests` workflow's aggregate conclusion is `success`, which is
what branch protection evaluates. The `statusCheckRollup` in the
PR view still shows the initial-attempt failure — that is how
this repo's retry infrastructure is designed and is not a merge
blocker.

## Post-flip state

| field           | value                                                    |
|-----------------|----------------------------------------------------------|
| URL             | https://github.com/torch-spyre/torch-spyre/pull/4113     |
| Number          | 4113                                                     |
| State           | OPEN                                                     |
| Draft           | **false**                                                |
| Base SHA        | `813a2980dbd9d2e84f5006b9cde2f305e679fc71`               |
| Head SHA        | `ce34227eb162d5a622cb3946c1dcbdce97b6766a`               |
| Mergeable       | `MERGEABLE`                                              |
| MergeState      | `BLOCKED` (review required by branch protection)         |
| reviewDecision  | `REVIEW_REQUIRED`                                        |
| latestReviews   | 0                                                        |
| comments        | 0                                                        |
| assignees       | (none)                                                   |
| labels          | (none)                                                   |

## Reviewer assignment (automation-driven)

On flip from draft → ready, repository automation (CODEOWNERS)
automatically requested 14 reviewers. **No manual reviewer
requests were made.**

Requested reviewers:

    avery-blanchard, moriohara, ashokponkumar, JRosenkranz,
    dgrove-oss, tardieu, ani300, pradghos, anubhavjana,
    n-marion, thoangtrvn, cyang49, marnold-ibm, jjhursey

## No new labels, no comments, no reviews yet

Nothing to act on from the review side yet. Next expected
signals: reviewers looking at the diff, possibly adding labels,
possibly requesting changes or approving.

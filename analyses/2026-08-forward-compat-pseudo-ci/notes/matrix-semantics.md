# 2×2 matrix — semantics

Adapted from the prompt's classifier taxonomy, with one refinement
learned empirically.

**Prerequisite:** every 2×2 run must declare its baseline mode
(RAW_MAIN vs SHADOW_BASELINE). See `baseline-modes.md`. Reading
this file without that context will produce wrong verdicts.

**Empirical validation status (2026-08-25):** the 2×2 causal
attribution rules below are the design specification. They have
NOT been end-to-end validated by a full four-cell run yet. The
#3404 case ran one cell (B) and produced a static-preflight
verdict (`PR_STALE_AGAINST_MAIN`) that is mode-independent.
Full-matrix validation is the work in task #15.

## The four cells

```
                          SUPPORTED torch          FORWARD torch

    torch-spyre main            A                       C

    PR head                     B                       D
```

## Verdict table

| A | B | C | D | Interpretation |
|---|---|---|---|---|
| ✅ | ✅ | ✅ | ✅ | `FORWARD_COMPAT_CLEAN` — nothing interesting |
| ✅ | ❌ | * | * | `PR_REGRESSION_ON_SUPPORTED` — PR itself is broken; refine below |
| ✅ | ✅ | ❌ | ❌ (same failure as C) | `FORWARD_BREAK_ALREADY_ON_MAIN` + `PR_HAS_NO_EFFECT_ON_FORWARD` |
| ✅ | ✅ | ✅ | ❌ | `PR_FORWARD_INTERACTION_BREAK` — PR specifically breaks on forward torch |
| ✅ | ✅ | ❌ (fail A) | ❌ (fail B, same as C) | `FORWARD_BREAK_NO_ADDITIONAL_PR_EFFECT` |
| ✅ | ❌ | ✅ | ❌ (same failure as B) | `PR_BREAK_INDEPENDENT_OF_TORCH_VERSION` |
| ✅ | ✅ | ❌ (fail A) | ❌ (materially different from C) | `PR_CHANGES_FORWARD_BREAK_SURFACE` |
| ❌ | * | * | * | `NO_SIGNAL_UNTIL_SUPPORTED_CONTROL_FIXED` |
| any | any | ⚠️ | ⚠️ | `SUBSTRATE_FAILURE` if DMA/pod issues |
| any | any | ⚠️ | ⚠️ | `PIPELINE_FAILURE` if the scripts themselves broke |

## Refinement observed empirically

`PR_REGRESSION_ON_SUPPORTED` collapses two distinct causes:

- **`PR_STALE_AGAINST_MAIN`** — the PR is behind current main and
  its base predates a repo-wide change (header path renames,
  method removals in shared includes). Fix: rebase. NOT the PR's
  fault semantically.
- **`PR_INTRINSIC_REGRESSION`** — the PR itself introduces a bug
  even after rebase. Fix: PR author needs to fix the code.

`mergeable_state` is a proxy for `PR_STALE_AGAINST_MAIN` — if it's
`dirty`, prefer rebasing before running the 2×2. This was #3404's
situation: `dirty` predicted `PR_STALE_AGAINST_MAIN`, and Cell B
empirically confirmed it.

## Corollary — check Git-level state before spending device time

The empirical Cell B on #3404 took 7 min. `mergeable_state: dirty`
was visible from `gh api` in seconds. The latter is a strictly
cheaper filter for `PR_STALE_AGAINST_MAIN` specifically. It is
not a substitute for the 2×2 in the general case — a PR with
`mergeable_state: clean` can still be a
`PR_FORWARD_INTERACTION_BREAK`, which is precisely the case the
2×2 exists to distinguish.

## Why the 2×2 shape is still useful even when it collapses

Even for `PR_STALE_AGAINST_MAIN`, having the 2×2 as the diagnostic
frame is what lets Cell B's failure be attributed correctly. Without
cells A and C for context, Cell B alone could look like an F4
substrate hazard, an F8-style forward-compat break, or a torch-spyre
bug. The taxonomy rules those out by asserting what would be seen
in A and C if it were them. That's a structural argument for the
2×2 shape; it is not yet an empirical validation of the full
attribution table.

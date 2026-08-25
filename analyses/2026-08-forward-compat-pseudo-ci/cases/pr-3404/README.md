# PR #3404 — empirical Cell B; A/C/D not run

- **PR:** [`torch-spyre/torch-spyre#3404`](https://github.com/torch-spyre/torch-spyre/pull/3404)
  "fix(distributed): fix import torch_spyre crash from spyre::broadcast_async schema ordering"
- **Author:** anubhavjana
- **Base SHA:** `9de3a7be39f4aafd24cb3d003409f5fd902223da`
- **Head SHA:** `a50ba6a6854d348ec8c6162e129be88cfe24471d`
- **State (2026-08-25 snapshot):** open, `mergeable_state: dirty` (has conflicts against main)
- **Diff:** 3 files, +17 / −9. Small, well-scoped.

## Scope of this case

This case exercises the **static preflight** part of the pseudo-CI
lane and one empirical build cell (Cell B). It does NOT exercise
the 2×2 interaction attribution — cells A, C, and D were not run.
The dashboard-level classification here is `PR_STALE_AGAINST_MAIN`,
which the static preflight can produce cheaply. The prompt's
2×2 causal semantics (distinguishing PR breakage from PyTorch
breakage from their interaction) is NOT empirically validated by
this case.

See `../../notes/baseline-modes.md` for the baseline-mode design
question that any future full 2×2 run has to resolve first.

## Static triage

Priority score: **90** — the highest in the whole 216-PR set.
Classification: `DEEP_FORWARD_COMPAT`.

File categories touched:

- `autoload` (torch_spyre/__init__.py) — F3-adjacent
- `cpp` (torch_spyre/csrc/distributed/spyre_distributed.cpp)
- `distributed`
- `inductor` (torch_spyre/_inductor/distributed/spyre_library.py)
- `python_runtime`

The `autoload` + `cpp` + `distributed` combination is exactly the
shape of PR that the forward-compat skill's F3 case worries about:
reordering the import path of torch_spyre by pulling a submodule
earlier in `_autoload_impl`.

## Actual diff — content

`torch_spyre/__init__.py` +5, adds:

```python
    # Must run before torch_spyre._C loads anywhere below (ops.eager,
    # decompositions both import it). _C's impl registration needs this
    # module's schema to already exist, or import torch crashes.
    from torch_spyre._inductor.distributed import spyre_library  # noqa: F401
```

This is a legitimate targeted fix — pull the schema-registration
import to before `_C` gets loaded via `ops.eager`.

## Cells executed

|                       | SUPPORTED torch 2.13 | FORWARD torch 2.15 nightly |
|-----------------------|---------------------|----------------------------|
| **torch-spyre main @ 613b259** | Cell A — **NOT RUN**. See below. | Cell C — **NOT RUN**. See below. |
| **PR head @ a50ba6a** | Cell B — **empirical FAIL** (this run) | Cell D — **NOT RUN**. Blocked by Cell B failure. |

### Cell B — empirical FAIL

`setup_supported_env.sh --torch-spyre-sha a50ba6a...` on pod
`tdeshane-pseudo-ci-2026-08-25`. RC=8. Failed in the C++ build:

    /home/tdeshane/pr-b/torch-spyre/torch_spyre/csrc/module.h:21:10:
        fatal error: util/sen_host_ops.h: No such file or directory
         21 | #include <util/sen_host_ops.h>
            |          ^~~~~~~~~~~~~~~~~~~~~

Full log: `data/cellB-build.log`.

Root cause: **the PR is stale against main.** At the PR's base SHA
`9de3a7b`, `torch_spyre/csrc/module.h:21` had:

    #include <util/sen_host_ops.h>

At current main SHA `613b259`, the same line reads:

    #include <spyrecode-host-functions/sendataconvert/sen_host_ops.h>

The deeptools image now installed on the fresh pod ships the header
at `/opt/ibm/spyre/deeptools/include/spyrecode-host-functions/
sendataconvert/sen_host_ops.h`. Main is aligned to the new path;
the PR is not. This is precisely why `mergeable_state: dirty` shows
red on GitHub — the header path in module.h is one of the merge
conflicts against main.

### Why A / C / D were not run — and why the earlier writeup was wrong

The prior version of this document said Cell A was "PRESUMED PASS
from third-clean-run's 2026-08-25 evidence at exactly this SHA."
Both halves of that claim were incorrect:

1. **The third-clean-run's torch-spyre SHA was `69bd7de1`, not
   `613b259`.** See
   `../../../2026-08-forward-compat-skill-validation/cases/third-clean-run-2026-08-25/01-versions.json`.
2. **The third-clean-run's supported-control failed at Stage 0**
   with F3 REVERSE_ENTRYPOINT_HAZARD before the local F3 fix was
   applied. That case is a green result for the SKILL.md workflow
   (which included the F3 fix), not a green result for raw
   `69bd7de1`. Reading it as a green supported control for raw
   main confuses baseline modes — see
   `../../notes/baseline-modes.md`.

Additionally, `613b259`'s `torch_spyre/__init__.py` still has
`import torch` at line 20 with `_autoload` defined at line 256 and
`_autoload_impl` at line 284 — the same structural pattern F3
described. A raw-main supported control at 613b259 therefore
cannot be presumed green.

C and D were also NOT run empirically. The prior writeup's claim
that they would "hit the same build error as Cell B before reaching
a torch-version-specific check" is a plausible hypothesis but not
tested here.

## Interpretation via the 2×2 classifier

The prompt's classifier maps A-green / B-red to
`PR_REGRESSION_ON_SUPPORTED`. This case does not exercise cell A
empirically, so the strongest supported claim is a **static
preflight verdict**:

- **`PR_STALE_AGAINST_MAIN`** — the PR head fails at the C++
  compile step because its base predates a repo-wide header rename.
  A rebase would fix the header path. `mergeable_state: dirty`
  already telegraphs this at the GitHub layer, before any device
  time is spent.

This verdict is producible without a 2×2 run — one build cell plus
a `git diff` between the PR base and current main is enough. That's
useful evidence for the **static preflight lane**. It is not
evidence for the 2×2 classifier's ability to distinguish PR
regression from PyTorch-forward regression from their interaction;
that remains unvalidated.

## Action for the PR (shadow / non-invasive)

**Do NOT patch or comment.** Per the prompt's rules, the shadow
compatibility lane does not post to PR authors.

If we were to report this internally, the useful maintainer message
would be:

> "PR #3404 build-broken on supported torch because base-branch has
> drifted (`module.h` include path changed). Rebase on current main
> resolves. Forward-PyTorch interaction cannot be assessed until
> then."

## Device cost

- Cell B: ~7 minutes of pod time before failing at the C++ compile
  step.
- Cells A / C / D: not run.
- Static preflight (mergeable_state check + PR-vs-main file
  diff): ~5 seconds of `gh api` and `git diff`. Would have flagged
  this before Cell B ran; Cell B mostly served to confirm the
  static signal.

Serial device work respected.

## Fresh-Claude actionable summary

Static triage flagged this PR as top-priority (autoload + cpp +
distributed + inductor). Empirical Cell B took ~7 min and confirmed
the PR is stale against main; no torch-version-specific interaction
is testable in its current shape.

Correct dashboard row:

    #3404  preflight=STALE  B=❌(stale)  A/C/D=not-run   →  PR_STALE_AGAINST_MAIN
    Author message (not posted): "rebase on main; module.h include path drifted."

The old row (`A=✅  B=❌  C=(skip)  D=(skip)`) was misleading — it
implied cell A had been evaluated when it had not.

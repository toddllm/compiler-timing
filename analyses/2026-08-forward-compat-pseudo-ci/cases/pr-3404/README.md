# PR #3404 — 2×2 empirical result

- **PR:** [`torch-spyre/torch-spyre#3404`](https://github.com/torch-spyre/torch-spyre/pull/3404)  
  "fix(distributed): fix import torch_spyre crash from spyre::broadcast_async schema ordering"
- **Author:** anubhavjana
- **Base SHA:** `9de3a7be39f4aafd24cb3d003409f5fd902223da`
- **Head SHA:** `a50ba6a6854d348ec8c6162e129be88cfe24471d`
- **State:** open, `mergeable_state: dirty` (has conflicts against main)
- **Diff:** 3 files, +17 / −9. Small, well-scoped.

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

## 2×2 matrix

|                       | SUPPORTED torch 2.13 | FORWARD torch 2.15 nightly |
|-----------------------|---------------------|----------------------------|
| **torch-spyre main @ 613b259** | Cell A — PRESUMED PASS from third-clean-run's 2026-08-25 evidence at exactly this SHA. | Cell C — PRESUMED PASS with F3+F8 patches; PRESUMED FAIL without them (F8 will fire on inductor compile). |
| **PR head @ a50ba6a** | Cell B — **FAIL** (empirical, this run) | Cell D — presumed to fail with the same C++ error as Cell B before it can reach a torch-version-specific check. |

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

## Interpretation via the 2×2 classifier

Textbook interpretation with A green, B red, same C/D pattern:
`PR_BREAK_INDEPENDENT_OF_TORCH_VERSION` — the PR is broken on
supported torch, and the failure is a stale-against-main build
break, not anything to do with the PR's actual intent or with
forward PyTorch.

Refinement of the taxonomy: **PR_STALE_AGAINST_MAIN**. The 2×2
prompt lists `PR_REGRESSION_ON_SUPPORTED` as the A-green-B-red
interpretation, which is technically accurate here, but the CAUSE
is that the PR hasn't been rebased. That's meaningfully different
from "the PR itself introduces a regression" — a rebase would fix
it.

## Action for the PR (shadow / non-invasive)

**Do NOT patch or comment.** Per the prompt's rules, the shadow
compatibility lane does not post to PR authors.

If we were to report this internally, the useful maintainer message
would be:

> "PR #3404 build-broken on supported torch because base-branch has
> drifted (`module.h` include path changed). Rebase on current main
> resolves. No PyTorch-version-specific interaction is testable
> until then."

## Device cost

- Cell B: ~7 minutes of pod time before failing at the C++ compile
  step. Cheap because it dies before the setup script even tries a
  smoke stage.
- Cells A / C / D not run empirically because:
  - Cell A is redundant with third-clean-run at the same SHA.
  - Cell C is redundant with third-clean-run's forward setup.
  - Cell D would hit the same build error as Cell B — no torch-version
    contribution possible until Cell B is green.

Serial device work respected.

## Fresh-Claude actionable summary

Static triage flagged this PR as top-priority (autoload + cpp +
distributed + inductor). Empirical Cell B took ~7 min and confirmed
the PR is stale against main; no torch-version-specific interaction
is testable in its current shape.

A dashboard row for this PR would read:

    #3404  A=✅  B=❌  C=(skip)  D=(skip)   →  PR_STALE_AGAINST_MAIN
    Author message (not posted): "rebase on main; module.h include path drifted."

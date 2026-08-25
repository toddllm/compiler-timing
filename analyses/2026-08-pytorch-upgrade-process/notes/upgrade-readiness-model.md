# Upgrade-readiness model

Dimensions a maintainer wants to check BEFORE opening the official
version-bump PR. Derived from the 2.11/2.12/2.13 evidence + the
forward-compat cases.

Not a boolean — preserve dimensions.

## Dimensions

### D1. PyTorch artifact readiness

- [ ] `release/X.Y` branch exists on pytorch/pytorch
- [ ] `v$NEW.0` tag exists (or an RC does)
- [ ] CPU wheels on `https://download.pytorch.org/whl/cpu` for
      cp312 (torch-spyre's minimum Python)
- [ ] Source-build path works from the `release/X.Y` branch
- [ ] Relevant upstream fixes that the team cares about have
      cherry-picked to the target patch release (e.g. 2.12.1's
      cherry-pick of pytorch/pytorch#185909)

### D2. Torch-spyre core compatibility

- [ ] Forward-compat SUPPORTED_CONTROL green on main
- [ ] Forward-compat FORWARD_BEFORE_FIX at target torch — known
      failures identified and enumerated in the compat ledger
- [ ] Every open ledger entry for the target torch either landed on
      main or has an accepted patch in the shadow lane
- [ ] `import torch_spyre` produces the primary-module import
      matrix cleanly at target torch
- [ ] Minimal `torch.compile(..., backend="inductor")` smoke passes
- [ ] Hand-picked cheap `tests/inductor/` subset passes
- [ ] The `_monkey_patch.py` monkey-patches don't fire an
      `AttributeError` at torch import (would show up if a private
      dynamo/guard API drifted)

### D3. Downstream readiness

- [ ] vLLM compatible at target torch OR spyre-inference no longer
      depends on precompiled vLLM CPU wheels
- [ ] spyre-inference main builds against target torch
- [ ] hf-adapters compatible
- [ ] kineto-spyre wheel published for target torch
- [ ] All C++ extensions rebuilt cleanly (nm scan for
      `_ZN3c10*`/`_ZN5torch*` symbols)

### D4. CI readiness

- [ ] `_test_matrix.yaml` can be dispatched with target torch
      (either via prebaked image or via `checkout-pytorch` +
      pytorch_sha input if the fork lands)
- [ ] `upstream_tests.yaml` config includes target torch
      (`test_profiler_config.yaml` and equivalents updated —
      this was 2.13's ashokponkumar/seshapad ask)
- [ ] Multi-arch runners available (x86 minimum; s390x/ppc64le if
      required)
- [ ] Test-suite `test_suite_config.labels` covers the compat
      surfaces the target torch touches

### D5. Migration readiness (mechanical)

- [ ] pyproject.toml edits identified (6 lines + filterwarnings)
- [ ] Lockfile regeneration will succeed (wheels on index)
- [ ] docs/torch-spyre-docs edits identified
- [ ] project-overview skill reference identified

The `upgrade-pytorch-version` skill covers this dimension well.

### D6. Performance readiness

- [ ] Compile-time regression check via `frontend-compiler-impact`
      on main + target torch — no material regression
- [ ] Model-level smoke unchanged (one small Granite block or
      equivalent)

This dimension was NOT explicitly gated in any of 2.11/2.12/2.13.
It's forward-facing.

## Overall verdict states

- `NOT_READY` — any D1 red, or D2 has open ledger entries without
  proposed fixes.
- `READY_WITH_KNOWN_PATCHES` — D1/D2/D3 green; D4/D5/D6 pending;
  every substantive fix has an authored patch in the shadow lane
  waiting to be bundled into the bump PR.
- `READY_FOR_UPGRADE_PR` — all six dimensions green; the maintainer
  can open the version-bump PR with confidence that CI will not
  surface surprises. The PR itself may still bundle
  `REPO_HYGIENE_BUNDLING` unrelated bumps.
- `UPGRADE_PR_VALIDATED` — the version-bump PR has been merged and
  post-merge follow-ups (if any) are tracked.

Dimensions must be preserved on the internal record even when the
overall state is set — a `READY_WITH_KNOWN_PATCHES` state might
have D3=vLLM-red that is expected but worth surfacing.

## What the forward-compat + upgrade skills each contribute

| Dimension | forward-compat | upgrade-pytorch-version |
|---|---|---|
| D1 (PT artifact) | – | prerequisite check, refuses without |
| D2 (core compat) | ★ | "Potential Breakage" watch list |
| D3 (downstream) | partial (via case cross-references) | ABI-rebuild recipe |
| D4 (CI) | – | comment-string edits only |
| D5 (mechanical) | – | ★ |
| D6 (perf) | – | – (out of scope) |

`frontend-compiler-impact` (separate skill, not analyzed here) is
the natural D6 owner.

## The composed picture

```
                       (D1: PT artifact watcher — cron)
                                  │
        (D2: forward-compat pseudo-CI — Track A)  ─────┐
                                                       │
        (D3: downstream lag monitor — separate)  ──────┤
                                                       │
        (D4: CI knob checker — trivial)          ──────┤
                                                       │
        (D5: upgrade-pytorch-version — skill)    ──────┼───► READY_FOR_UPGRADE_PR
                                                       │
        (D6: frontend-compiler-impact)           ──────┘

        pre-existing skill                       ★★★
        Track A's shadow lane                    ★★
        readiness composition (this doc)         ★
        not yet built                            –
```

Two of six dimensions have existing skills. One (D2) has
scaffolding via Track A. Three (D3, D4, D6) don't have a dedicated
mechanism — each is a small check, not another whole skill.

A readiness skill would be a THIN orchestration layer that queries
each dimension and emits a report. Body of work is small if the
dimensions themselves are already covered.

## Is a readiness skill justified NOW?

Weak yes. Enough of the pieces exist that a readiness dashboard is
mostly an assembly job. But the current bottleneck is not
orchestration — it's D2 (the forward-compat empirical shadow lane)
being fully continuous, and D3 (downstream lag) having any
mechanism at all. Address those first; the readiness layer is
easy to compose once they exist.

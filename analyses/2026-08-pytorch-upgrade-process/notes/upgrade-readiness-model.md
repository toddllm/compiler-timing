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

- [ ] Compile-time regression check on main + target torch — no
      material regression
- [ ] Model-level smoke unchanged (one small Granite block or
      equivalent)

This dimension was NOT explicitly gated in any of 2.11/2.12/2.13.
It's forward-facing.

**Caveat on tooling:** the `frontend-compiler-impact` skill was
validated for comparing **torch-spyre code deltas** (main vs. a
PR head at a fixed torch version). Comparing the same torch-spyre
SHA across two different torch versions (torch 2.13 vs torch 2.14
holding torch-spyre fixed) is a **different experimental axis**
that skill has not been validated for yet. The instrumentation
(compile-phase timings, mem/perf counters) likely transfers, but
the interpretation guides in that skill assume torch-spyre-side
change is the independent variable. Cross-torch use of the same
mechanics would need its own validation pass before its output
should be trusted.

## Overall verdict states

The prior version had `READY_WITH_KNOWN_PATCHES` require "D1/D2/D3
green" but then said the same state "might have D3=vLLM-red." That
was a self-contradiction. Fixed states:

- **`NOT_READY`** — one or more gating dimensions has unresolved
  unknowns or open ledger entries without an authored remediation.
  Gating set: D1 (PT artifact), and D2's must-fix items (the ones
  the team has marked as blocking rather than "known and worked
  around"). D3/D4/D5/D6 are not gating for entering this state;
  a red D3 with a documented workaround is not a NOT_READY signal.

- **`READY_WITH_KNOWN_GAPS`** — every dimension has been evaluated
  and every gap is either fixed, has an accepted patch in the
  shadow lane, or has been explicitly dispositioned as an accepted
  workaround. Some dimensions may still be red — that's fine, as
  long as the redness is known and dispositioned. This is the
  state most historical upgrade PRs opened from: the team knew
  vLLM would lag or a specific test would xfail, and chose to
  proceed anyway.

- **`READY_FOR_UPGRADE_PR`** — the required-for-PR-open subset of
  dimensions are green or explicitly waived. That subset is D1
  (must have a target-torch artifact), D2's mechanical import +
  compile smoke, and D5 (mechanical migration recipe). D3/D4/D6
  can be tracked as PR blockers but are not required for the
  PR to open.

- **`UPGRADE_PR_VALIDATED`** — the version-bump PR has been opened
  and passed its required validation (CI matrix green on the
  bump PR itself, downstream checks that were red pre-open are
  now dispositioned, post-merge follow-ups tracked).

Dimensions must be preserved on the internal record even when the
overall state is set — a `READY_WITH_KNOWN_GAPS` state that has
D3=vLLM-red must record the D3=red status and the disposition
("accepted workaround: spyre-inference no longer depends on vLLM
CPU wheels, per spyre-inference#357"), not lose that detail.

The states are ordered: `NOT_READY` → `READY_WITH_KNOWN_GAPS` →
`READY_FOR_UPGRADE_PR` → `UPGRADE_PR_VALIDATED`. Moving forward
requires resolving/dispositioning gaps; moving backward requires
new unknowns emerging (e.g. an ABI break discovered mid-PR).

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
the natural D6 candidate but has only been validated for the
torch-spyre-code-delta axis; cross-torch-version use is a
different application that would need its own validation. See
D6 caveat above.

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

One of six dimensions has an existing validated skill (D5:
upgrade-pytorch-version). D2 has scaffolding via Track A (with
the caveat that Track A's 2×2 causal attribution is not yet
empirically validated). D6 has a candidate skill
(frontend-compiler-impact) that is validated for a different
axis and would need cross-torch validation before it can be
counted as a D6 owner. D1/D3/D4 don't have dedicated mechanisms
yet — small checks, not new skills.

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

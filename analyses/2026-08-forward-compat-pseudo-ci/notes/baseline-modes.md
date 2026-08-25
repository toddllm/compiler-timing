# Baseline modes for the 2×2 — RAW_MAIN vs SHADOW_BASELINE

The 2×2 matrix uses "torch-spyre main" as the top row's reference
point. What "main" means for a compatibility experiment is not
obvious, because torch-spyre main today ships without some fixes
that the shadow forward-compat lane has already identified and
verified (F3 REVERSE_ENTRYPOINT_HAZARD, F8 FallbackKernel single-
tensor). If those fixes are quietly applied to the "main" row, the
matrix reports patched-main results while labeling them as raw
main. That's a category error.

This note fixes the mode question before any full 2×2 is run.

## Two valid modes

### RAW_MAIN

Every cell uses whatever torch-spyre main ships today, unpatched.

- Cell A = main @ SHA_main + supported torch
- Cell B = PR head + supported torch
- Cell C = main @ SHA_main + forward torch
- Cell D = PR head + forward torch

**Stop rule:** if Cell A is red, the 2×2 produces no causal signal
about the PR. Report `NO_SIGNAL_UNTIL_SUPPORTED_CONTROL_FIXED` and
stop. Do not try to compare B, C, D against a broken baseline.

Use RAW_MAIN when the question is "what does actual upstream main
look like today, unmediated by our own patches?"

### SHADOW_BASELINE

Every cell uses main plus a recorded, verified patch stack `S`
containing our open compatibility fixes.

- Cell A = main @ SHA_main + `S` + supported torch
- Cell B = PR head + `S` + supported torch
- Cell C = main @ SHA_main + `S` + forward torch
- Cell D = PR head + `S` + forward torch

Every dashboard row records both the SHA and the patch-stack hash.

Use SHADOW_BASELINE when the question is "given the patches we
already know work, does this PR interact with forward torch in a
new way?" It's what you'd actually want for prioritizing which
PRs to test forward, because RAW_MAIN spends most of its device
time re-confirming the same known main-side failure.

## Rule

**Every dashboard row must declare which mode it was run under.**
Never mix them silently. If a case reports Cell A green, the
report must say whether that's raw main green or shadow-baseline
green.

The tabular form:

    #3959  mode=SHADOW_BASELINE  patch-stack=F3+F8  A=✅  B=✅  C=✅  D=❌  →  PR_FORWARD_INTERACTION_BREAK
    #3959  mode=RAW_MAIN        patch-stack=(none)  A=❌  B=❌  C=—  D=—  →  NO_SIGNAL_UNTIL_SUPPORTED_CONTROL_FIXED

Same PR, different mode, different verdict. Both are legitimate
and mean different things.

## Patch-stack `S` definition

For the shadow-baseline mode, `S` is the set of patches from
`../../2026-08-forward-compat-skill-validation/cases/*/patches/`
whose `first_torch_spyre_sha_with_fix` is null in the
compatibility ledger (i.e. not yet landed on main).

As of 2026-08-25, that set is:

- F3 REVERSE_ENTRYPOINT_HAZARD — patches for
  `torch_spyre/__init__.py` moving `import torch` inside
  `_autoload_impl`.
- F8 FallbackKernel single-tensor direct-output layout — patch for
  the inductor fallback path when a fallback kernel emits a
  single tensor directly to `V.graph.buffers`.

Record the exact patch files and their sha256 in the case's
`matrix.json` under `patch_stack`. When a fix lands on main and
its ledger entry moves to a non-null SHA, drop it from `S`.

## What the #3404 case established

The #3404 case ran one empirical cell in what would be RAW_MAIN
mode — but only Cell B, and Cell B failed at C++ compile before
any torch use. Its verdict `PR_STALE_AGAINST_MAIN` is
mode-independent (a stale PR is stale under either mode).

The prior writeup implicitly used SHADOW_BASELINE for A/C
(by referring to the third-clean-run, which had F3 applied) but
used PR-head-unpatched for B/D. That's neither mode — it's a
mix that yields no clean causal claim.

## Practical selection

For pseudo-CI on open PRs, **default to SHADOW_BASELINE**. Reasons:

1. The main-side compat failures (F3, F8) are known and boring;
   burning a Cell A on them every run adds no information.
2. The interesting question for a PR is D-relative-to-C:
   given the known patch stack, does adding this PR create a new
   forward-torch failure?
3. RAW_MAIN answers a different question — "how bad is unmediated
   upstream main?" — that only matters when the compat ledger
   itself needs auditing, not per-PR.

Run RAW_MAIN periodically (weekly-ish?) as a ledger audit: confirms
each entry in `S` still fires on raw main, and catches the case
where a patch became unnecessary because upstream evolved.

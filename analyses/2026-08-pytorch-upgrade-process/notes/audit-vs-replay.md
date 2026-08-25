# Audit vs replay — a methodological distinction

The master prompt asked for a **blind empirical replay** of the
`upgrade-pytorch-version` skill. What the initial commit
(`7cc30ec`) produced under `skill-replay/` is a **static
historical coverage audit** — a different methodology with weaker
epistemic force. This note fixes the labeling and explains what
each is good for.

## Definitions

### Static historical coverage audit

Read the skill's SKILL.md and the merged upgrade PR side by side.
Enumerate:

- files the skill says to change vs. files the PR actually changed;
- categories the skill says to watch vs. categories the PR
  actually hit;
- gaps in either direction.

Author's knowledge state when writing: **full**. Both artifacts
are visible; hindsight applies.

Good for: understanding the skill's design shape, identifying
whether its prescription covers what actually landed, spotting
categories the skill treats as watch items vs. as specific
predictions.

Weak for: measuring what the skill would ACTUALLY produce when
run without foreknowledge, because the person writing the audit
is not the skill.

### Blind empirical replay

Give a fresh Claude session:

1. The historical pre-upgrade torch-spyre SHA.
2. The target PyTorch version.
3. The skill (SKILL.md).
4. **Nothing about the merged PR.**

Preserve that session's output. THEN reveal the merged PR and
compare. Enumerate:

- edits the skill actually prescribed (from its output);
- edits the PR actually needed;
- predictions the skill made (if any) about non-mechanical
  breaks;
- non-mechanical breaks the PR actually contained.

Author's knowledge state when the skill runs: **only what the
skill's prompt provides**. No hindsight.

Good for: measuring the skill's real-world signal-to-noise ratio;
identifying what the skill would produce for a NEW upgrade
where hindsight isn't available.

Weak for: nothing structural — but expensive to set up right,
because "fresh session" has to genuinely mean no context bleed
from prior conversations.

## Why the distinction matters for this analysis

The `coverage.json` v1 numbers (schema field
`silent_correctness_actual: N`) read as if the skill was given
a chance to predict and failed to. That framing overstates the
test — the skill was never given a chance. The v2 breakdown
(under `silent_correctness_v2_breakdown`) makes the accounting
finer but the underlying methodology is still audit, not replay.

The stronger claim that survives after the reclassification:

> The `upgrade-pytorch-version` skill's stated scope is mechanical
> migration. Its "Potential Breakage" section enumerates categories
> without specific predictions. Both statements are visible in
> `SKILL.md.snapshot` regardless of whether we audit or replay it.

The weaker claim that requires actual replay:

> If run blind on 2.11 pre-upgrade, the skill would produce
> mechanical edits {X} and would/would not name specific breaks {Y}.

That's task #14 in the correction-commit task list. Do it before
using coverage.json's numbers to justify any claim about the
skill's real-world coverage.

## What this means for the readiness model

The readiness model in `upgrade-readiness-model.md` says the
existing skill covers D5 well. That claim rests on the audit,
not on a replay. Given the skill is stated-scope for mechanical
migration and the audit shows 100% mechanical hit rate against
5 files, the claim is defensible even from audit-only evidence.

The stronger claim "the skill's Potential Breakage list matches
K of M actual breaks" should NOT be relied on until a replay
confirms it. In particular, do not use the audit-derived numbers
to argue "the skill would have missed break X" — you can only
say "the audit noted the skill did not name break X specifically;
whether it would still steer the user toward looking for it is a
blind-replay question."

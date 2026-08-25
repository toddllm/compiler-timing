# What this directory actually is — static historical coverage audit

**IMPORTANT:** This directory is titled `skill-replay/` but its
contents are a **static historical coverage audit**, not a blind
empirical replay. The distinction matters — see
`../notes/audit-vs-replay.md`.

## What's actually in here

- `SKILL.md.snapshot` — 580-line snapshot of the
  `upgrade-pytorch-version` skill at the reviewed version.
- `upgrade-skill-2.11-to-2.12.md`, `upgrade-skill-2.12-to-2.13.md`
  — retrospective audit documents that compare "what the skill
  prescribes" against "what actually happened in the merged
  upgrade PR." Written with knowledge of the final PR content.
- `coverage.json` — machine-readable aggregate of the audit.
  Schema v2 (2026-08-25) split the earlier lumped
  `silent_correctness_actual: N` count into the finer
  OBSERVED_SILENT_WRONG_OUTPUT / LATENT_CORRECTNESS_RISK /
  REFERENCE_TOLERANCE_DRIFT breakdown; the v1 field is preserved
  for provenance.

## Why this is not a blind replay

The master prompt's B6 asked for a blind replay:

> Give the upgrade skill ONLY:
> - starting repo;
> - target version.
>
> Ask:
>
>     "What would this skill have changed/predicted before seeing
>      the final merged PR?"
>
> Preserve that output.

That step was not performed in this session. The audits in this
directory read the skill AND the merged PR side-by-side and
describe the gap. Useful, but a different kind of evidence than
what B6 asked for.

## What to trust from this directory

- The mechanical-file coverage numbers (rows 1–3 in each
  coverage.json entry) — these are measurable from any angle and
  don't depend on whether you saw the PR first.
- The consequence taxonomy per version — same.
- The "the skill covers mechanical, not substantive breaks"
  conclusion — this holds regardless of audit vs. replay
  methodology, because the skill's own text says so.

## What NOT to trust from this directory as-is

- "The skill predicts N of M substantive breaks." This is a
  retrospective judgment, not a blind measurement. The number
  would be different if measured blind.
- "The skill's Potential Breakage watch list matches K categories."
  Retrospective — reading the watch list with knowledge of the
  actual outcome inflates match count.

## What would fix it

A true blind replay would need to spawn a fresh Claude session
with:

1. The historical pre-upgrade torch-spyre SHA (e.g. main just
   before PR #2218 opened for 2.11 → 2.12).
2. The target version string ("2.12").
3. The `upgrade-pytorch-version` skill (SKILL.md.snapshot here).
4. **Nothing about the actual PR.**

Then preserve that session's output, then compare it against the
merged PR. Task #14 in the correction-commit task list is that
work. Cheap, no hardware required.

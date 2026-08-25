# PyTorch upgrade process archaeology — Track B summary

## What was reconstructed

Three merged PyTorch upgrade PRs on `torch-spyre/torch-spyre`:

- **PT 2.11** — #1930, merged 2026-05-11 by `bohnstingl` (11 files, +647 / −81)
- **PT 2.12** — #2218, merged 2026-07-28 by `ani300` (39 files, +906 / −617)
- **PT 2.13** — #3374, merged 2026-07-29 by `ani300` (13 files, +788 / −556)

Full timelines at `historical/pt-{2.11,2.12,2.13}/timeline.md` +
`consequences.json` per version. Consequence taxonomy at
`notes/consequence-taxonomy.md`. Team-process reconstruction at
`notes/actual-team-process.md`.

## Big-picture findings

### The upgrade PR is a discovery-and-fix vehicle, not a bookkeeping one

Every upgrade PR contains substantive fixes that were discovered by
trying the new torch:

- 2.11: `add_lambda_guard` gained `user_stack`.
- 2.12: `size_hint` split, decomposition broadening, Dynamo `.to`
  graph-break, fp16 numeric xfails, downstream architectural
  unblock (spyre-inference#357).
- 2.13: `pyobj_slot_` C++ rename, LX loop-order pre-fusion pass,
  profiler polish.

The mechanical file edits are a fraction of the diff. The
substantive fixes carry the story.

### Observed-silent-wrong-output is the failure mode current tooling misses

The initial writeup lumped "silent correctness" into one bucket
with three cases. The finer taxonomy
(`notes/consequence-taxonomy.md`) splits them:

- **`OBSERVED_SILENT_WRONG_OUTPUT`** (2 cases): 2.12 Dynamo `.to`
  graph-break — wrong D2D dtype casts produced at runtime; 2.13
  LX loop-order — wrong reduction outputs. **These are the ones
  with sharp teeth.**
- **`LATENT_CORRECTNESS_RISK`** (1 case): 2.12 `size_hint` split
  — wrong replacement caught in review before wrong output
  materialized.
- **`REFERENCE_TOLERANCE_DRIFT`** (1 case): 2.12 fp16 1-ULP CPU
  reference numerics changed; Spyre kernel produced the same
  output.

Both `OBSERVED_SILENT_WRONG_OUTPUT` cases stemmed from an unchanged
API's INTERNAL behavior drifting — Dynamo inlining behavior for
2.12; scheduler loop-reorder for 2.13. An API-signature grep would
not catch either. Only rebuild-and-run-with-a-CPU-oracle catches
them.

### The existing upgrade skill is well-scoped for mechanical, not for discovery

**Methodology note:** the section below labels its evidence as
"replay results," but the underlying work is a **static historical
coverage audit**, not a blind empirical replay. See
`notes/audit-vs-replay.md` and `skill-replay/README.md` for the
distinction. Task #14 (a true blind replay) is a followup that
would strengthen the numbers below.

The `upgrade-pytorch-version` skill (authored in the 2.11 PR by
`bohnstingl`, now in torch-spyre main at
`.claude/skills/upgrade-pytorch-version/SKILL.md`, 580 lines):

- Prescribes 5 mechanical files correctly for both 2.11 → 2.12 and
  2.12 → 2.13. Full coverage of pyproject, lockfiles, docs,
  project-overview reference, filterwarnings URLs, workflow
  comments.
- Names correct file paths, correct sed patterns, correct
  order-of-operations.
- Includes a "Potential Breakage" section that enumerates
  categories (Inductor API, Dynamo/guard API, downstream C++,
  etc.) — but as watch items, not predictions.

Audit results (`skill-replay/coverage.json` — schema v2):

| Version | Mechanical prescribed & needed | Mechanical needed but not prescribed | Substantive breaks specifically predicted | Observed-silent-wrong-output actual | Latent-correctness-risk actual | Reference-tolerance-drift actual |
|---|---|---|---|---|---|---|
| 2.11 → 2.12 | 5 / 5 | 2 (hygiene bundles) | 0 predicted | 1 | 1 | 1 |
| 2.12 → 2.13 | 5 / 5 | 4 | 0 predicted | 1 | 0 | 0 |

The skill is honest about its scope. Its Potential-Breakage list
gestures at every substantive category but never names a specific
symbol.

### The team's actual process has three recurring patterns

1. **Substantive fixes bundle into the upgrade PR.** They are
   discovered by rebuild-and-run, not pre-authored.
2. **CI infrastructure lands in parallel.** Multi-arch runners
   (#1997), pytorch-commit tracking (#2274), upstream-tests
   enablement — all handled outside the upgrade PR but as
   prerequisites for it.
3. **Downstream lag is architected around, not waited on.**
   spyre-inference#357 removed the vLLM CPU-wheel coupling so the
   2.12 → 2.13 hop wasn't gated on upstream vLLM.

### The compatibility ledger

`compatibility-ledger.json` + `.md` — 14 entries so far:

- 12 from historical 2.11/2.12/2.13 upgrades.
- 2 open (F3 REVERSE_ENTRYPOINT_HAZARD active on current main;
  F8 FallbackKernel-single-tensor for PT 2.15 nightly).

Every historical fix landed in an official upgrade PR. Every open
entry has a proposed patch under `analyses/2026-08-forward-compat-
skill-validation/cases/`.

### Readiness model — six dimensions

Full breakdown at `notes/upgrade-readiness-model.md`. Six axes:

1. PyTorch artifact readiness (release branch, wheels, cherry-picks)
2. Torch-spyre core compatibility (forward-compat skill's territory)
3. Downstream readiness (vLLM, spyre-inference, hf-adapters, kineto)
4. CI readiness (workflow config, multi-arch runners)
5. Migration readiness (mechanical — upgrade-pytorch-version's territory)
6. Performance readiness (frontend-compiler-impact candidate — but
   validated only for torch-spyre-code-delta axis, not
   cross-torch-version axis; see D6 caveat in the readiness model)

Existing skills cover D5 (mechanical) validated on its own axis;
D2 (compatibility) via forward-compat, but Track A's causal 2×2
is unvalidated. D6 has `frontend-compiler-impact` as a candidate,
validated for torch-spyre-code-delta axis but not cross-torch-
version. D1 / D3 / D4 are small check-lists without dedicated
tooling yet.

## Answer to the Track B question

**"Can Claude tell the team, before an official PyTorch upgrade
starts, what is already known to break, what is already fixed,
what downstream pieces are ready, and what work remains?"**

**Partially yes, right now.**

- "What is already known to break": YES via the compatibility
  ledger.  All 14 historical/open entries are recorded with
  discovery notes and remediation status.
- "What is already fixed": YES — every ledger entry has a
  `first_torch_spyre_sha_with_fix` field.
- "What downstream pieces are ready": PARTIALLY — the pattern is
  understood (vLLM, kineto-spyre, spyre-inference, hf-adapters),
  the check itself is a small script (kineto wheel URL; nm scan
  on installed .so files) that isn't automated.
- "What work remains": PARTIALLY — the readiness model lists six
  dimensions, but composition is manual today.

The gap is not in analysis; it's in orchestration. A readiness
skill would compose existing signals; it does not need to
independently learn how any of them work.

## Should the existing upgrade skill change?

**No, not directly.** The static coverage audit shows it does
what it says it does — mechanical migration is 5/5 files for
both 2.11→2.12 and 2.12→2.13. Its "Potential Breakage" section
is honestly labeled as a watch list. A blind replay (task #14)
would strengthen this conclusion; the current evidence is audit,
not replay.

The productive next move is not to bolt discovery onto the
mechanical skill — it's to add a readiness composition layer
alongside it that:

- consults the compatibility ledger (this repo);
- runs the forward-compat pseudo-CI (Track A);
- checks downstream readiness (D3 small script);
- checks CI configuration (D4 small script);
- checks upstream artifact readiness (D1 small script);
- optionally invokes `frontend-compiler-impact` (D6);
- and only THEN invokes `upgrade-pytorch-version` when D1–D4
  are green.

That's the composition described in `notes/upgrade-readiness-model.md`.

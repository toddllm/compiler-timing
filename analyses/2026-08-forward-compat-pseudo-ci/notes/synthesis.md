# Cross-track synthesis — Track A × Track B

## The empirical picture from both tracks

**Track A (shadow forward-compat over open PRs):**
- 216 open PRs statically triaged (5 min).
- 1 empirical **Cell B only** run (7 min, correctly diagnosed
  as `PR_STALE_AGAINST_MAIN`). Cells A / C / D were not run.
- 13 active non-PR branches inventoried (task #5 catchup).
- **What's empirically validated:** static preflight filter
  correctly identifies stale-against-main PRs before device time
  is spent.
- **What's NOT yet empirically validated:** the 2×2 causal
  matrix's ability to distinguish PR breakage from PyTorch
  breakage from their interaction. That requires a full four-cell
  run on a clean-mergeable PR — task #15.
- The rate-limiting factor observed for *this* corpus was PR
  mergeability. Do not generalize to a claim about all PR sets;
  it's one data point.

**Track B (three historical upgrades + static coverage audit):**
- 2.11 / 2.12 / 2.13 fully reconstructed with timelines +
  consequences.
- Existing `upgrade-pytorch-version` skill covers mechanical
  migration well (5/5 files, 100%); did not name specific
  substantive breaks. See `../../2026-08-pytorch-upgrade-process/skill-replay/README.md` — the underlying evidence is a
  **static historical coverage audit**, not a blind empirical
  replay. Blind replay is task #14.
- `OBSERVED_SILENT_WRONG_OUTPUT` (2.12 Dynamo `.to`, 2.13 LX
  loop-order) is the failure mode with sharpest teeth. Split
  from `LATENT_CORRECTNESS_RISK` and `REFERENCE_TOLERANCE_DRIFT`
  in the tightened taxonomy — see
  `../../2026-08-pytorch-upgrade-process/notes/consequence-taxonomy.md`.
- Compatibility ledger populated with 12 historical + 2 open
  entries.

## Where the two tracks touch

The forward-compat cases from Track A produce entries in the same
ledger that Track B's readiness model reads:

```
     shadow forward-compat lane (Track A)
                │
                │  produces: a compatibility-ledger entry per open failure,
                │  each with a case-dir + proposed patch + status
                ▼
        compatibility-ledger.json
                │
                │  read by: readiness model (Track B) as part of D2
                ▼
     upgrade-readiness model (Track B)
                │
                │  emits: NOT_READY / READY_WITH_KNOWN_PATCHES / READY_FOR_UPGRADE_PR
                ▼
   maintainer opens the upgrade PR
                │
                │  bundles: the ledger's proposed patches that hadn't
                │  landed yet on main
                ▼
   upgrade-pytorch-version skill runs the mechanical migration
                │
                ▼
       frontend-compiler-impact confirms no perf regression
                │
                ▼
                MERGE
```

## Answers to the ten synthesis questions

### 1. What should run continuously/on-demand?

- **Continuously:** the static triage over open PRs (5 min against
  `gh api`; cheap; produces the dashboard's leftmost columns).
- **On-demand (weekly-ish):** the forward-compat 2×2 empirical
  matrix, filtered to non-draft + `mergeable_state=clean` +
  high-priority. Currently ~1 PR in our sample corpus qualifies at
  any given moment.
- **Continuously (cron):** the ledger's "does upstream release
  X still need patch Y?" checks — check `pytorch/pytorch` for the
  cherry-pick, update ledger status when it lands.

### 2. What should run only when an official bump is being planned?

- Downstream readiness sweep (vLLM main + spyre-inference main +
  hf-adapters main against target torch; kineto-spyre wheel
  availability).
- CI configuration audit (D4 — check that `upstream_tests*.yaml`
  covers target torch, multi-arch runners are up, `_test_matrix.yaml`
  can dispatch it).
- `frontend-compiler-impact` on main + target torch.

### 3. What information should pseudo-CI preserve for the future bump?

- Every case-dir (observation, diagnosis, plan, patch, verification).
- The compatibility ledger's per-entry `dual_compatible` flag —
  cases that pass on BOTH the current-supported and the target-forward
  torch can land BEFORE the bump PR, reducing the bump PR's size.
- Failed cells and their reasons — a running record of "this PR
  couldn't be tested against forward torch because it was stale
  against main; recheck after rebase."

### 4. What information from historical upgrade practice should affect pseudo-CI triage?

- Priority weighting should skew toward the surfaces that have
  bitten in past upgrades: Inductor semantic, Dynamo behavior,
  scheduler/loop-ordering, C++ ABI. Track A's priority function
  already does this.
- `SILENT_CORRECTNESS_CHANGE` is the failure mode most likely to
  slip past a Row-1 targeted test. Track A's PRs that touch
  layouts + scheduler should trigger the Row-5 device-oracle path
  (currently `05-verification.oracle.py` is per-case).
- Downstream lag is REAL but architected around. Track A does not
  need to worry about it; Track B's D3 handles it during the bump.

### 5. Where should `frontend-compiler-impact` enter?

- **Not in Track A** — pseudo-CI is a compat/import lane, not a
  perf lane. Adding perf measurement per PR would blow the device
  budget.
- **In Track B, at D6** — the readiness model's performance
  dimension. Run it once, on main + target torch, before the bump
  PR is opened.

### 6. What should stay human/maintainer decision-making?

- "Is this a good target release?" — the team decides based on
  which upstream features they want. Track B can list what
  target releases contain what features (via the ledger), but the
  "do we bump now" call is human.
- "Merge criteria are met?" — the "at this point it's ready to
  merge!" moment. Machine can assemble the checklist; human
  signs off.
- Bundling non-torch dep bumps into the upgrade PR — that's a
  team preference, not a tooling call.

### 7. Which parts are safe to automate?

- Static PR triage.
- Compatibility ledger updates (add entries as forward-compat
  cases resolve).
- `mergeable_state` / `draft` filtering.
- Downstream repo-existence + version checks.
- `nm` ABI scans of installed .so files.
- Kineto-spyre wheel URL 200-OK check.

### 8. Which parts require scarce Spyre hardware?

- All four cells of the 2×2 that involve an actual `torch.compile`
  or an actual test run — cells A/B/C/D beyond the "does it
  build?" step.
- Row 6 of `verify_patch.sh` (fresh-venv build + import). Cheap
  actual-hardware use (build only, no compile).
- Row 5 device-correctness oracle (real spyre device required).

### 9. Which parts can be Level-0/static?

- All of static triage.
- Compatibility ledger authoring.
- Downstream repo status.
- Wheel/tag availability.
- The mechanical portion of `upgrade-pytorch-version` (its `Step
  10: Verification` grep step is Level-0).

### 10. What would a future real-CI integration look like?

Minimal-invasive path:

1. `_test_matrix.yaml` gets an optional `pytorch_sha` input,
   forwarded to the existing `checkout-pytorch` action's `sha`
   input (already exists in the action; just not plumbed
   through).
2. New `.github/workflows/forward-compat-shadow.yaml`:
   `workflow_dispatch` only (never `pull_request`), calls
   `_test_matrix.yaml` with `pytorch_sha` = current nightly-cpu
   torch SHA. Doesn't post to PRs. Nightly cron.
3. Its output goes to ClickHouse via the existing
   `push-to-clickhouse.yaml` (perf ingest path) — same pattern
   the maintainers already trust.
4. The compatibility ledger becomes a queryable dashboard
   over that data.
5. Whether this becomes a required check is a policy call —
   the prompt explicitly says "Do NOT make GitHub status checks
   required," so leave it as advisory data.

## The next highest-value experiment

Two candidates, ranked:

### A. Run the empirical 2×2 on `#3959` (the only currently-buildable corpus member).

- Cost: 4 cells × ~30 min each on a fresh pod = ~2 hours.
- Value: proves the 2×2 taxonomy on a PR that ISN'T
  stale-against-main. Would validate `PR_FORWARD_INTERACTION_BREAK`
  detection if #3959 happens to interact with 2.15 nightly.

### B. Populate the readiness model against a hypothetical "PT 2.14"

- Cost: ~30 min of doc work + gh queries.
- Value: exercise every readiness dimension against a real target;
  identifies which dimensions have gaps that would block a real
  bump today. Answers the "if the team says 'let's do 2.14 next
  week,' where would they hit friction?" question.

I would pick B — cheaper, higher information density, doesn't
consume device time. A becomes worthwhile once B identifies which
compat surfaces to target.

## Wrapper skills — final call

**Track A ("pseudo-CI"):** create as a THIN orchestration script
first, not a skill. Body: enumerate PRs, filter by
`mergeable_state=clean` × priority × updated_at, run cells B and D
on top-N. Once the driver stabilizes, promote to
`.claude/skills/torch-spyre-forward-compat-pseudo-ci/`. Not urgent
— the existing `torch-spyre-forward-compat` skill's scripts already
do the per-cell work.

**Track B ("upgrade readiness"):** create when D1 / D3 / D4 have
small check scripts. The composition layer is one page of Python.
Naming: `.claude/skills/torch-spyre-pytorch-upgrade-readiness/`
(preserves the distinction from the existing
`upgrade-pytorch-version` mechanical skill).

Both are premature to create today — the analysis in this repo
IS the design work. Once the checks are automated and pointed
somewhere, THEN a skill wrapping them is honest.

## Final answers to Todd's two independent questions — REVISED

Earlier version of this file overreached. Corrected answers:

**A. "Can Claude act as a useful shadow compatibility CI system
over current Torch-Spyre development without wasting device time
or confusing PR failures with PyTorch failures?"**

**Split answer:**

- "Spend device time only where warranted" — YES, empirically
  demonstrated on one PR (#3404). Static preflight (triage +
  `mergeable_state`) correctly identified a stale PR before a
  device cell would have.
- "Correctly separate PR failures from PyTorch failures via the
  2×2 causal matrix" — NOT empirically validated yet. The #3404
  case ran one cell (Cell B). Cells A / C / D were never run,
  and the earlier writeup's claim that Cell A was "presumed pass"
  was wrong (see `../cases/pr-3404/README.md`). The 2×2
  interaction-attribution rules in `matrix-semantics.md` remain
  a design specification. Task #15 (full four-cell 2×2 on a
  clean-mergeable PR) is the missing empirical validation.

**B. "Can Claude tell the team, before an official PyTorch upgrade
starts, what is already known to break, what is already fixed,
what downstream pieces are ready, and what work remains?"**

**Partial yes.** The compatibility ledger + readiness model +
historical timelines are useful evidence today. Remaining gaps:

- What appears in the ledger has not been reconciled against a
  real upcoming target — the recommended next experiment
  (PyTorch 2.14 RC readiness, task #13) exercises this against
  a real target rather than a hypothetical.
- The `upgrade-pytorch-version` skill's coverage numbers rest on
  a **static historical coverage audit**, not a blind replay
  (see `../../2026-08-pytorch-upgrade-process/notes/audit-vs-replay.md`).
  Task #14 is the blind replay.
- The readiness state machine had a self-contradiction in its
  earlier version and has been rewritten
  (`../../2026-08-pytorch-upgrade-process/notes/upgrade-readiness-model.md`).
  It is now internally consistent but has not been exercised
  end-to-end against a real target version.
- D6 (perf) does not yet have a validated cross-torch-version
  owner. `frontend-compiler-impact` is a candidate but was
  validated for a different axis.

**Retraction:** the earlier line "Both tracks are ready for the
next round of engineering; neither needs further empirical
validation on its core methodology" was wrong. Track A's 2×2
causal matrix is unvalidated. Track B's audit-vs-replay
distinction was not respected in the initial numbers. Both need
follow-up empirical work before that summary claim is honest.

## What still needs empirical validation

1. **Full four-cell 2×2** on a clean-mergeable PR, with an
   explicit baseline-mode declaration (task #15).
2. **Real PT 2.14 RC readiness exercise** — 2.14 is no longer
   hypothetical (RC1 exists on the test CPU channel as of the
   PyTorch dev-discuss announcement; GA scheduled 2026-09-02)
   (task #13).
3. **Blind replay of `upgrade-pytorch-version`** — give a fresh
   Claude session only the historical starting SHA + target
   version; preserve output before revealing the merged PR
   (task #14).
4. **Cross-torch-version validation of `frontend-compiler-impact`**
   (or explicit replacement mechanism for D6).

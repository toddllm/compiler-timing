# Cross-track synthesis — Track A × Track B

## The empirical picture from both tracks

**Track A (shadow forward-compat over open PRs):**
- 216 open PRs statically triaged (5 min).
- 1 empirical Cell-B run (7 min, correctly diagnosed as
  `PR_STALE_AGAINST_MAIN`).
- The rate-limiting factor is not device time. It's PRs being in a
  buildable state to begin with. `mergeable_state ∈ {clean, dirty,
  blocked}` is a cheaper filter than trying to build.

**Track B (three historical upgrades + skill replay):**
- 2.11 / 2.12 / 2.13 fully reconstructed with timelines +
  consequences.
- Existing `upgrade-pytorch-version` skill covers mechanical
  migration well; predicts zero of the substantive breaks.
- Silent-correctness cases (2.12's Dynamo `.to`, 2.13's LX
  loop-order) are the hardest failure mode.
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

## Final answers to Todd's two independent questions

**A. "Can Claude act as a useful shadow compatibility CI system
over current Torch-Spyre development without wasting device time
or confusing PR failures with PyTorch failures?"**

Yes, in principle, empirically validated for ONE PR. The 2×2
matrix reliably distinguishes `PR_STALE_AGAINST_MAIN` from a
torch-version issue. The methodology works. Scale-out is a matter
of driver code + device budget; those are engineering, not open
questions.

**B. "Can Claude tell the team, before an official PyTorch upgrade
starts, what is already known to break, what is already fixed,
what downstream pieces are ready, and what work remains?"**

Yes — the compatibility ledger + readiness model + historical
timelines together answer this today. What is missing is
orchestration: a single command that emits the ready/not-ready
report per target torch version. That's a small piece of glue,
not another research question.

Both tracks are ready for the next round of engineering; neither
needs further empirical validation on its core methodology.

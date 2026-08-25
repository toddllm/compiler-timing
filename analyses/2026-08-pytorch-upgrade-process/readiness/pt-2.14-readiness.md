# PyTorch 2.14 upgrade readiness — real target, not hypothetical

**Snapshot:** 2026-08-25. torch-spyre main @ `8567fb2` (pin
`torch~=2.13.0`). pytorch main @ `26b9ddd7f`. Target: **PyTorch 2.14**
(`release/2.14` tip @ `9724418` = `v2.14.0-rc7`; GA scheduled
**2026-09-02** per the PyTorch dev-discuss announcement).

## Verdict up front

**State: `READY_WITH_KNOWN_GAPS`.** Every dimension has been evaluated
against real target artifacts. The gating subset for
`READY_FOR_UPGRADE_PR` (D1 + D2 mechanical import/compile smoke + D5)
is not yet green — one blocking gap identified in D3 (kineto-spyre) and
one in D2 (no forward-compat run has been done against 2.14 RC). None
of the gaps look novel; all fit patterns seen in 2.11/2.12/2.13
upgrades. Estimated total remaining work: <1 day of Claude + a
forward-compat pod run + kineto-spyre wheel build.

## Per-dimension evidence

### D1. PyTorch artifact readiness — **GREEN**

- [x] `release/2.14` branch exists on pytorch/pytorch
      (tip `9724418` at snapshot time).
- [x] `v2.14.0-rcN` tags exist — currently rc1 through rc7 published.
      GA tag `v2.14.0` not yet cut (scheduled 2026-09-02).
- [x] CPU wheels on `https://download.pytorch.org/whl/test/cpu/torch/`
      for `cp312`:
      - `torch-2.14.0+cpu-cp312-cp312-linux_x86_64.whl` ✓
      - `torch-2.14.0+cpu-cp312-cp312-manylinux_2_28_aarch64.whl` ✓
      - `torch-2.14.0+cpu-cp312-cp312-linux_s390x.whl` ✓
      - `torch-2.14.0+cpu-cp312-cp312-win_amd64.whl` ✓
- [x] Source-build path from `release/2.14` — same shape as 2.13 source
      build; no known blockers.
- [~] Relevant upstream cherry-picks — none identified as required at
      snapshot time. This dimension turns yellow only if a specific
      needed fix is not yet in `release/2.14`.

**Notes for the maintainer:** the wheels are on the **test** channel,
not the **stable** channel, because GA hasn't cut. If the upgrade PR
lands before 2026-09-02, `./tools/update-requirements.sh` will need to
point at the test index or use a pre-release marker. If after, the
stable channel should have `2.14.0` before the PR opens.

### D2. Torch-spyre core compatibility — **NOT_EVALUATED_AGAINST_2.14**

The compatibility ledger has 14 entries. None of them are against PT
2.14 specifically. Current shadow forward-compat cases use PT 2.15
nightly as their "forward" torch (`c0577575` at snapshot). No
supported-vs-2.14 evaluation exists yet.

- [ ] Forward-compat SUPPORTED_CONTROL green on current main —
      **known red** at snapshot: F3 REVERSE_ENTRYPOINT_HAZARD is still
      open on main. This is a torch-spyre-side hazard, not a
      2.14-specific issue, but it must be fixed (or the SHADOW_BASELINE
      mode with the F3 patch stack must be used) before D2 can be
      evaluated.
- [ ] Forward-compat FORWARD_BEFORE_FIX at target torch 2.14 —
      **NOT RUN**. This is the gap that gates D2.
- [ ] Open ledger entries against 2.14 — none yet (the ledger's forward
      entries are against 2.15 nightly).
- [ ] `import torch_spyre` clean at PT 2.14 — untested.
- [ ] Minimal `torch.compile(..., backend="inductor")` smoke — untested.
- [ ] Hand-picked cheap `tests/inductor/` subset — untested.

**Blocking action:** run the forward-compat skill's supported + forward
lanes against PT 2.14 RC7 on a fresh pod. That's a ~30-40 min run
(fresh pod, F3 patch on the supported side, RC7 wheel from the test
channel on the forward side). Recorded as follow-up work below.

**Expected outcome from historical pattern:** 2.13 → 2.14 is likely to
show 1-2 mechanical fix cases (a monkey_patch signature drift and/or
an inductor internal rename) plus 0-1 `OBSERVED_SILENT_WRONG_OUTPUT`
cases. That's the empirical rhythm of the last three upgrades.

### D3. Downstream readiness — **YELLOW / one specific gap**

Checked:

- [x] **spyre-inference** (torch-spyre/spyre-inference) — `pyproject.toml`
      says `"torch"` unpinned; version is "determined by torch-spyre and
      vllm." No hard block from spyre-inference. Green.
- [x] **hf-adapters** (torch-spyre/hf-adapters) — pinned `torch>=2.0`,
      permissive. Not a block. Green.
- [x] **vLLM** — the historical 2.12 lag was resolved by
      spyre-inference#357 removing the CPU-wheel coupling. That
      architectural change is durable — spyre-inference does not
      currently depend on precompiled vLLM CPU wheels for the compat
      lane. Green in that dimension.
- [ ] **kineto-spyre** (IBM/kineto-spyre) — **RED / known lag**. Latest
      release tag is `torch-2.11.0.aiu.kineto.1.1.2` (2026-05-15).
      **kineto-spyre has not published wheels for torch 2.12 or 2.13,
      let alone 2.14.** This means:
      - torch-spyre's `docs/profiling_tools.md` kineto URL for 2.14
        will 404 until a wheel is built.
      - Any downstream that requires kineto for profiling on 2.14
        will need a fresh build from source.
      - This is an EXISTING gap that predates 2.14 planning — the
        team has been running against a 2.11 kineto or building from
        source. Documenting it as a 2.14-specific block would be
        wrong; documenting it as a 2.14 blocker for anyone who
        cares about kineto profiling is right.
- [x] **C++ extensions** — the ABI-rebuild-across-minor-versions
      pattern is well-understood (watch #8 in the skill). No net-new
      concern for 2.14 beyond the historical baseline.

**Blocking action:** decide whether kineto-spyre wheel availability
gates 2.14. Historical answer: it hasn't gated 2.12 or 2.13 either
(both merged without a matching kineto wheel), so probably not a
block. Worth confirming with the profiling team.

### D4. CI readiness — **MOSTLY GREEN**

Checked against current `torch-spyre/main`:

- [x] `_test_matrix.yaml` — parametric on the torch-spyre `ref`; the
      pytorch version is whatever the prebaked torch-spyre-dev image
      ships. For 2.14 the image would need a rebuild against RC7.
      This is a standard part of the bump process (new
      torch-spyre-dev image per minor).
- [x] `_upstream_tests_beta_matrix.yaml` — the pytorch release branch
      is derived from `pyproject.toml`. Once `torch~=2.14.0` is set,
      the workflow follows automatically. No hardcoded 2.13.
- [x] `upstream_tests.yaml` — same; comment-only version references
      (skill's Step 4). The blind replay predicted these edits; the
      2.12 and 2.13 upgrade teams both chose not to apply them.
      Consistent with "logic is version-agnostic."
- [x] `upstream_tests_beta.yaml` — same as above.
- [x] Multi-arch runners — x86 primary, aarch64 available. s390x per
      wheel availability (test channel wheel exists). No new
      runner-plumbing work for 2.14 that we can see; the 2.11
      multi-arch push (#1997) is durable.
- [~] `tests/configs/upstream_tests/test_profiler_config.yaml` — this
      is the file the 2.13 upgrade added to enable upstream profiler
      tests for a new target. If PT 2.14 introduces further profiler
      changes (watch #4 territory), similar config touch may be
      needed. Not verifiable statically.

**Blocking action:** none for D4 itself, but the torch-spyre-dev
prebaked image needs a rebuild against RC7. That's mechanical.

### D5. Migration readiness (mechanical) — **GREEN**

The `upgrade-pytorch-version` skill covers this dimension well —
confirmed independently by two blind replays. Mechanical file coverage
(pyproject.toml, project-overview SKILL.md, installation.md, uv.lock +
requirements/*.txt) is 5/5 for both prior upgrades. No reason to
expect 2.14 differs.

- [x] pyproject.toml edits identified (6 lines + filterwarnings)
- [x] Lockfile regeneration path — `./tools/update-requirements.sh`.
      Requires the wheel to be reachable; test-channel index or
      pre-release marker until GA.
- [x] docs/torch-spyre-docs edits identified (dev_install.md,
      profiling_tools.md — same pattern as 2.13)
- [x] project-overview skill reference identified

The one 2.14-specific nuance: `torch~=2.14.0` under a strict-compat
resolver may or may not accept `2.14.0rc7`. If the upgrade PR opens
before GA, either:
- pin to `torch==2.14.0rc7` explicitly, then bump to `~=2.14.0` on
  GA day; OR
- open the upgrade PR after 2026-09-02 GA.

### D6. Performance readiness — **NOT_EVALUATED**

The readiness model's D6 is "no material regression at target torch"
measured against the same torch-spyre SHA. The candidate skill
(`frontend-compiler-impact`) was validated for torch-spyre code
deltas, not cross-torch axis (per the correction commit's D6 caveat).

- [ ] Compile-time regression check — NOT RUN. Would compare same
      torch-spyre SHA on PT 2.13 vs PT 2.14 RC7.
- [ ] Model-level smoke — NOT RUN.

**Blocking action:** either validate `frontend-compiler-impact` for
the cross-torch axis and then run it, or use a simpler compile-time
timing harness. Historical pattern: 2.11/2.12/2.13 upgrades did NOT
gate on this dimension. So D6 non-eval is not a state block for
`READY_FOR_UPGRADE_PR`; it's a "would be nice to know" question.

## Rolled-up state

Per the corrected readiness state machine
(see `../notes/upgrade-readiness-model.md`):

- D1 = GREEN (artifact readiness verified against real RC7)
- D2 = NOT_EVALUATED_AGAINST_2.14 (gating; needs forward-compat run)
- D3 = YELLOW (kineto-spyre lag; historical precedent is to accept)
- D4 = MOSTLY_GREEN (needs image rebuild, otherwise green)
- D5 = GREEN (mechanical coverage confirmed)
- D6 = NOT_EVALUATED (non-gating)

**State: `READY_WITH_KNOWN_GAPS`.** Every dimension has an answer;
some answers are "known lag, accepted historically" (D3 kineto) and
one is "empirically untested" (D2 vs 2.14 specifically). Not yet
`READY_FOR_UPGRADE_PR` because the gating subset (D1 + D2 mechanical
smoke + D5) is not fully green — D2 needs a forward-compat pod run
against RC7.

## Blocking work to reach READY_FOR_UPGRADE_PR

1. **Fix F3 REVERSE_ENTRYPOINT_HAZARD on main** or explicitly document
   the SHADOW_BASELINE mode being used. ~1 hour, patch already
   authored in `../../2026-08-forward-compat-skill-validation/cases/`.
2. **Run forward-compat 2×2 supported + forward against RC7.** ~30-40
   min fresh pod. This produces:
   - Cell A (main + supported torch 2.13) — should be green after F3
     fix.
   - Cell C (main + forward torch 2.14 RC7) — this is the new data.
3. **Rebuild torch-spyre-dev prebaked image** against RC7. Standard.

Non-blocking but worth doing:

4. **Build kineto-spyre wheel** for torch 2.14 (or accept the
   historical lag and note it).
5. **Compile-time regression check** on the same torch-spyre SHA
   across 2.13 vs 2.14 RC7. Needs D6 tooling clarification first.

## What this exercise proved about the readiness model

- **D1 was answerable with 5 minutes of `gh api` + `curl`.** No custom
  tooling needed — the answer is a small check script.
- **D3 required 4 separate `gh api` reads** but each was mechanical
  (repo → pyproject.toml → torch pin). Also scriptable.
- **D2 is the load-bearing dimension.** Everything else composes
  cheaply; D2 requires actual pod time.
- **D5 didn't need re-checking** — the skill's mechanical scope is
  stable.
- **D6 has a real gap.** No cross-torch-version perf tooling has been
  validated. Not a 2.14 block per historical precedent, but a real
  gap for the readiness model.

## Delta from the master prompt's "hypothetical PT 2.14" experiment

The prompt's original recommendation (synthesis Experiment B) was a
hypothetical 2.14 exercise. Todd's review correctly pointed out that
2.14 is no longer hypothetical. This exercise used real artifacts
(`release/2.14`, `v2.14.0-rc7`, actual test-channel wheels, actual
kineto-spyre release tags) and the answers landed as **specific**
gaps rather than **hypothetical** gaps. That's the value the master
prompt intended; using a real target makes the answers actionable.

## Next actions for the readiness model itself

The readiness model was in `../notes/upgrade-readiness-model.md`. This
exercise validates its structure but exposes three refinements worth
recording:

1. **D2's "supported control green on main" prerequisite is often
   red.** F3 has been open across the 2.11 / 2.12 / 2.13 / 2.15
   nightly range. The model needs to explicitly declare which
   baseline mode (RAW_MAIN vs SHADOW_BASELINE) D2 evaluates under
   — same lesson as Track A's baseline-modes.md.
2. **D3's kineto-spyre check is trivially scriptable** (`gh api
   repos/IBM/kineto-spyre/releases --jq '.[0].tag_name'` +
   parse). Should become a small check script under the readiness
   layer.
3. **D6 needs an owner or an explicit "deferred" status.** Naming
   `frontend-compiler-impact` as the D6 owner was over-scoped in
   the initial model (per correction commit). This exercise
   confirms D6 remains without a validated owner.

Recording these back into `../notes/upgrade-readiness-model.md` is
a follow-up docs edit; not blocking on completing the 2.14
exercise.

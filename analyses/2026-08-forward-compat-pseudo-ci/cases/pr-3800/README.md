# PR #3800 — full four-cell 2×2 empirical (FORWARD_COMPAT_CLEAN)

## Verdict up front

**Classification: `FORWARD_COMPAT_CLEAN` under SHADOW_BASELINE (F3+F8).**

All four cells of the 2×2 pass at all stages (0/1/2/3) on retry. PR
#3800 does not introduce any new forward-torch break relative to
main. Cell D (PR + forward torch) is the cleanest result of any cell.

## Snapshot

- **PR:** [`torch-spyre/torch-spyre#3800`](https://github.com/torch-spyre/torch-spyre/pull/3800)
- **Title:** "Fix(inductor): keep the stick coordinate offset-free on a padded base"
- **Head SHA:** `aba2c7b4bb266025d3cf26aef8e78b6911e32aba`
- **Base SHA:** `eeeb115c838e96cf0b4f815151c753ab6e7d23f0`
- **State (2026-08-25 evening):** open, non-draft, `mergeable_state: clean`
- **Diff:** 3 files, +167/-29
  - `torch_spyre/_inductor/views.py` (compiler-facing — the actual fix)
  - `tests/inductor/test_inductor_ops.py`
  - `tests/tensor/test_coordinates.py`
- **torch-spyre main at snapshot:** `8567fb2bc32c729d0dba7bd14d9df14b4a5adb77`

## Baseline mode + patch stack

**Mode: `SHADOW_BASELINE`** per `../../notes/baseline-modes.md`.

**Patch stack `S` = {F3, F8}:**
- **F3 REVERSE_ENTRYPOINT_HAZARD** — applied to all four cells.
  Compat-ledger entry `torch-spyre-F3-reverse-entrypoint`. Confirmed
  live at torch-spyre `8567fb2` (independently verified: line 20 is
  still top-level `import torch`; `_autoload` first defined at line
  256).
- **F8 FallbackKernel-single-tensor** — applied only to forward
  cells (C, D). Compat-ledger entry
  `torch-2.15-FallbackKernel-single-tensor`. Was in the ledger as an
  open entry; **this run empirically confirms the entry is live and
  reproducible** — Cell C's first attempt with F3-only stack failed
  at Stage 0 with the exact error the ledger predicts.

## The 2×2 matrix — final results

|                                    | SUPPORTED torch 2.13.0                  | FORWARD torch 2.15.0.dev20260825 (NIGHTLY_PROXY)                    |
|------------------------------------|-----------------------------------------|---------------------------------------------------------------------|
| **main @ 8567fb2 + `S`**           | **Cell A: PASS** — 6/6 all stages       | **Cell C: PASS (after adding F8)** — 6/6 all stages                 |
| **PR head @ aba2c7b + `S`**        | **Cell B: PASS** — 6/6 all stages       | **Cell D: PASS** — 6/6 all stages (first attempt)                   |

**All cells green.** Verdict: **`FORWARD_COMPAT_CLEAN`.**

## Detailed timeline

Pod: `tdeshane-2x2-pr3800-20260825` on `p1-worker-85`, image
`sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`.

| Time | Event | Notes |
|---|---|---|
| 17:07 UTC | Pod created | Fresh, PVC swept |
| 17:24-17:36 | **Cell A setup** | 12 min. Detached with nohup to survive oc-exec drop; first attempt was killed by an oc-exec timeout at 10 min. |
| 17:40-17:48 | **Cell A smoke (attempt 1)** | Stages 0/1/2 pass; Stage 3 = 4/6 pass with 2 timeouts (`test_building_blocks`, `test_inductor_scalar`) |
| 17:48-18:00 | **Cell B setup** | 12 min |
| 18:00-18:08 | **Cell B smoke (attempt 1)** | Stages 0/1/2 pass; Stage 3 = 5/6 pass with 1 timeout on `test_building_blocks` |
| 18:08-18:22 | **Cell C setup** | NIGHTLY_PROXY installed `2.15.0.dev20260825+cpu` (sha `55199d11`) |
| 18:22-18:23 | **Cell C smoke (attempt 1)** | **Stage 0 FAIL** with `InductorError: FallbackKernel(...) does not have FixedTiledLayout` at `propagate_layouts.py:132` — F8 fired as ledger predicted |
| 18:23-18:24 | F8 patch applied | Copied F8-forward-patch.diff to Cell C's tree; hunk offset -19 but applied cleanly |
| 18:24-18:33 | **Cell C smoke (attempt 2)** | Stages 0/1/2 pass under F3+F8; Stage 3 = 5/6 pass with 1 timeout on `test_building_blocks` |
| 18:33-18:45 | **Cell D setup** | 12 min |
| 18:45-18:52 | **Cell D smoke** | **6/6 all stages pass first attempt.** `test_building_blocks` landed at 111s (under 120s limit) |
| 18:52-19:01 | **Cell A retry smoke** | 6/6 pass. `test_building_blocks` at 107s |
| 19:01-19:09 | **Cell B retry smoke** | 6/6 pass. `test_building_blocks` at 112s |
| 19:09-19:17 | **Cell C retry smoke (attempt 3)** | 6/6 pass. `test_building_blocks` at 108s |
| 19:17 | Pod deleted | |

## Stage 3 subtest timing — showing the timeout was noise

Same 6 test files across all 4 cells + retries. The `test_building_blocks.py` file was the fickle one:

| Cell | Attempt | `test_building_blocks.py` result |
|---|---|---|
| A | 1 | >120s timeout |
| A | retry | 107s pass |
| B | 1 | >120s timeout |
| B | retry | 112s pass |
| C | 2 (F3+F8) | >120s timeout |
| C | retry (3rd) | 108s pass |
| D | 1 | 111s pass |

All four "timeout" runs and all four "pass" runs sit within ~10 seconds
of the 120s boundary. This is pod-timing variance around a fixed
threshold, not a real signal. Todd flagged this correctly: retry
runs eliminated all four timeouts.

## Empirical findings

### F8 ledger entry confirmed live

The compat ledger's `torch-2.15-FallbackKernel-single-tensor` entry
was marked OPEN with a proposed patch. Cell C's first attempt
(F3-only stack, forward torch) reproduced the exact failure the ledger
described:

    torch._inductor.exc.InductorError: RuntimeError:
    FallbackKernel(
      python_kernel_name='torch.ops.spyre.to_dtype_cpu.default',
      layout=FixedLayout('spyre:0', torch.float32, size=[8], stride=[1]),
      ...
    ) does not have FixedTiledLayout

Location: `torch_spyre/_inductor/propagate_layouts.py:132`.
Trigger: env-smoke Stage 0's first `torch.compile` call.

Applying `F8-forward-patch.diff` (hunk offset -19 lines from original —
minor drift since the patch was authored) resolved it and Cell C's
retry passed cleanly through Stage 3.

### PR #3800 does not perturb forward-torch behavior

The 2×2's causal-attribution rules (see `../../notes/matrix-semantics.md`):

- A green, B green, C green, D green → `FORWARD_COMPAT_CLEAN`.
- The PR (Cell B vs Cell A: PR head + supported vs main + supported)
  is compat-clean on supported torch.
- Forward torch (Cell C vs Cell A: main + forward vs main + supported)
  needs the F8 patch to be compat-clean.
- **PR + forward torch (Cell D)** does not add any failure that Cell
  C doesn't already have. The PR's `views.py` change (padded-base
  stick coordinate offset) doesn't intersect the F8 fallback-kernel
  path or anything else exposed by the smoke stages.

### Ledger update needed

The `torch-2.15-FallbackKernel-single-tensor` ledger entry can move
from `status: OPEN` → `status: OPEN — reproduced 2026-08-25 in
pr-3800/`. The patch was already authored; it's still not landed on
main. Same as before, but with one more empirical reproduction data
point.

## Interpretation via the master prompt's 2×2 classifier

Per the prompt's specification and `../../notes/matrix-semantics.md`:

| Cells | Interpretation |
|---|---|
| A/B/C/D all ✅ | `FORWARD_COMPAT_CLEAN` — nothing interesting |

**This run empirically validates the causal-attribution methodology on
one full four-cell case.** Track A's 2×2 was previously validated only
for the static-preflight lane (via #3404). This case extends the
validation to the full empirical matrix.

## What this changes about Track A's overall verdict

The correction commit (`dcb79de`) said the 2×2 causal matrix was
"NOT empirically validated yet." That claim can now be upgraded:

- **`FORWARD_COMPAT_CLEAN` verdict**: empirically produced from a real
  four-cell run. Validated.
- **`PR_STALE_AGAINST_MAIN` verdict** (from the earlier #3404 case):
  empirically produced. Validated.
- **`FORWARD_BREAK_ALREADY_ON_MAIN`, `PR_FORWARD_INTERACTION_BREAK`,
  and the other four verdicts**: still not empirically observed. They
  are structural predictions of the matrix, not empirical
  confirmations.

So the 2×2's ability to produce a CLEAN verdict is now empirically
demonstrated. Its ability to distinguish PR-vs-torch-vs-interaction
failures is still a structural claim — you can't validate it without
at least one case where cells diverge in the ways the taxonomy names.
PR #3800 not being interesting from a forward-compat angle IS the
verdict; there's nothing more to squeeze out of this particular case.

## Device economics — reality check

The pre-staged case README predicted the four-cell 2×2 would take
40-60 min. The actual wall-clock:

- Four setups × ~12 min = 48 min
- Five smoke runs (four cells + one F8 diagnosis retry) × ~8 min = 40 min
- Three retry smokes × ~7 min = 21 min
- **Total pod time: ~112 min. Total wall clock: ~3 hours** including
  monitor waits, network hiccup, and F8 diagnosis.

The gap between "40-60 min" (pre-staged estimate) and "112 min actual"
was:
1. Underestimated setup time (~10 min in pre-stage, actual ~12-13 min per cell).
2. F8 diagnosis + retry added an extra smoke run (+8 min).
3. Retry runs added 3 × 7 min = 21 min. These were Todd's ask, not in
   the original estimate.
4. Network / VPN interruption during the run added maybe 10 min of
   idle wait.

Actionable lessons for future pseudo-CI runs:

1. **Cell setup budget: 15 min each.** Not 10.
2. **F8-style retry-with-larger-patch-stack is common.** Include a
   default 15-min buffer for "the first forward cell fails on an
   already-known ledger entry, apply the patch, retry."
3. **Retries for timing-flaky Stage 3 tests are cheap** (~7 min each)
   and eliminate false-fail noise. Worth doing by default when Stage 3
   fails with any file crossing the 120s timeout.

## Follow-ups

- Update compat-ledger `torch-2.15-FallbackKernel-single-tensor`:
  add reproduction data point from `pr-3800/data/cellC-smoke.attempt1-F8-fail/`.
- Fix the F8 patch's line offset — the hunk had `-19` and `-31` line
  drift when applied to current main. Not blocking, but the patch's
  reference version is stale. This is a documentation / patch-hygiene
  item, not a compat break.
- Consider raising the Stage 3 per-file timeout from 120s to 180s
  or making it environment-aware. `test_building_blocks.py` clearly
  operates near the boundary; a bit of pod variance flips it between
  pass and timeout with no code change.

## Artifacts

Under `data/`:
- `00-environment.json` — pod environment
- `01-versions.json` — resolved SHAs at run start
- `cellA-setup.log` — Cell A setup output (first attempt log; setup
  itself completed on the detached retry)
- `cellA-smoke/` — final green Cell A smoke (retry)
- `cellB-smoke/` — final green Cell B smoke (retry)
- `cellC-smoke/` — final green Cell C smoke (retry, F3+F8)
- `cellC-smoke.attempt1-F8-fail/` — first Cell C run showing F8 firing
- `cellC-smoke.attempt2-timeout/` — second Cell C run with F3+F8 but
  the test_building_blocks timeout
- `cellD-smoke/` — Cell D smoke (clean on first attempt)

The pre-F3 backup files (`torch_spyre/__init__.py.pre-F3` and
`torch_spyre/_inductor/propagate_layouts.py.pre-F8`) exist in the pod's
Cell workdirs but were not pulled locally — they can be recovered
from the F3 and F8 patch sources.

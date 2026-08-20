# Retrospective — PR #3868

## What happened

Three attempts, one validated verdict.

1. **Marginal-patch attempt** on the old pod tree (pod `bundle.py` as
   base, pod `bundle.py` + PR diff as head). Produced a plausible
   BACKEND_IMPACT_ONLY result. Retracted after the alignment gate was
   tightened: pod `bundle.py` (md5 `314e022307...`) is not the same
   as PR #3868's actual base `bundle.py` (md5 `c93d3ba5d7...`) —
   they differ by 14 lines around the pool-allocation refactor.
2. **Tier 3 attempt on old pod** — isolated checkouts at exact PR
   SHAs. `_C.so` from pod's pr3806 build failed to import
   (`NativePermutationLayoutSolver` missing). Fresh build in
   isolated tree failed on missing `fast_process_hcm.h` header.
   Verdict: `INSUFFICIENT_EVIDENCE`.
3. **Tier 3 attempt on new pod** (`tdeshane-compiler-timing-dev-v2`,
   built from fresh `:latest` pull with newer `ibm-deeptools-...
   2245.85f9432`). `_C.so` rebuilt successfully at both PR base
   `2e935f...` and PR head `a7786ac...`. Timing shim
   (`.claude/skills/frontend-compiler-impact/scripts/timing_shim.py`)
   instrumented both trees without tree modification. 3+3 paired cold
   samples at WB_n4 and WB_n8. Verdict: **BACKEND_IMPACT_ONLY**
   with a documented `sdsc_bundle_gen` regression, HIGH confidence.

## Prediction vs measurement (the whole point)

The static assessment predicted `FRONTEND_IMPROVEMENT` on
`sdsc_bundle_gen` via cache hits on repeated OpSpecs, MEDIUM
confidence. Preserved verbatim in `01-static-assessment.md` and
`prediction.json`.

The TRUE base/head measurement disagreed at both points:

- `n_specs` unchanged on both SDSC bundles at both points (5→5 and
  1→1). Python-level chunk repetition does not produce identical
  OpSpec dicts at the compiler level.
- `sdsc_bundle_gen` regressed +65% at n=4 and +46% at n=8 — head
  paid the added canonical-compile + `json.dumps(sort_keys=True)`
  overhead without cache-hit payoff.
- `dxp_standalone` improved −40% at n=4 and −45% at n=8 (−8.8 s and
  −20.8 s absolute) — the canonical bundle representation shift
  makes backend work faster even without spec dedup.
- Every Spyre `pipeline:*` is flat within noise.

Net wall-clock improves at both points (head is 94% of base at n=4
and 84% of base at n=8). The PR is a net win, but via a mechanism
that is NOT what static reading predicted.

## What the skill got right

- The full state machine executed at each attempt: static triage,
  prediction (before any run), alignment gate, sentinel selection,
  measurement, retrospective.
- Each attempt was labeled per its actual status. The marginal-patch
  was called `INSUFFICIENT_EVIDENCE` when the alignment gate was
  tightened, not retconned into a "kind of clean" measurement.
- The Tier 3 attempt on the old pod produced the correct
  `INSUFFICIENT_EVIDENCE` verdict when the system libs were too
  old, per the policy.
- The prediction was preserved verbatim across all three attempts.
  The final measurement disagrees with the prediction; that
  disagreement is now the study's canonical example of why
  prediction-before-measurement discipline matters.

## What the skill got wrong initially

- Tier 2 was too weak. "Diff applies cleanly" (`git apply --check`
  returns 0) is not the same as "the file the PR touches is
  actually the PR's base for that file". Tightened to per-touched-file
  blob equality in `references/measurement-policy.md`.
- The shim required two follow-up fixes when applied to a newer
  isolated tree:
  - `_has_spyre_device` is gone from `CustomPreSchedulingPasses` in
    the PR-base tree; the shim needs to skip that gate defensively.
  - The primary study's harness imports
    `from torch_spyre._inductor import timing_recorder` directly,
    which fails in an isolated tree that doesn't ship that module.
    The shim now aliases its own recorder into
    `torch_spyre._inductor.timing_recorder` at install time.
- The initial shim only instrumented `sdsc_total` (aggregate);
  distinguishing frontend `sdsc_bundle_gen` from backend
  `dxp_standalone` required patching `bundle.generate_bundle` and
  `subprocess.run` (for the `dxp_standalone` argv). Both now in
  the shim.

## Lessons carried forward

1. **Tier 2 = per-touched-file blob equality with the PR's actual
   base.** Codified in `references/measurement-policy.md`. The new
   `scripts/check_alignment.sh` runs the check.
2. **When the pod substrate is too old, refresh the pod image.**
   Standing up `tdeshane-compiler-timing-dev-v2` from a fresh
   `:latest` pull gave us `ibm-deeptools 2245.85f9432` (vs pod's
   `2238.654a8d5`), which had the missing
   `fast_process_hcm.h` and let `_C.so` rebuild at the PR base.
3. **`sdsc_bundle_gen` is a boundary metric** and can regress while
   `dxp_standalone` improves and every Spyre pass is flat. Codified
   in `references/interpretation-guide.md`.
4. **Cache-hit predictions require `n_specs` verification** —
   Python-level structural repetition does not imply OpSpec-level
   repetition. Static reading of the diff alone cannot reveal
   whether the cache the PR adds will actually populate.
5. **Backend improvements can come from frontend representation
   shifts**, not just from frontend time reduction. The canonical
   JSON that PR #3868 embeds makes `dxp_standalone` significantly
   faster (−40 to −45%) even when no spec dedup occurs on the
   frontend.

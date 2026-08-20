# Retrospective — PR #3868

## What the skill got right

The full state-machine ran: target resolved, static triage produced a
per-file classification, prediction was written before any run,
sentinels were selected, and the paired base/head measurement was
executed cleanly at two workload points with tight spreads.

The prediction, preserved verbatim, was `FRONTEND_IMPROVEMENT` on
`sdsc_bundle_gen` via cache hits — a genuinely different position
from what the measurement showed. This is what the skill's
prediction-before-measurement discipline exists to enable.

## What the skill got wrong — the reason for retraction

The measurement's "base" was the pod tree's `bundle.py`, not PR
#3868's actual base. The initial v0.2 alignment gate accepted "diff
applies cleanly" as sufficient for Tier 2. But `git apply --check`
only checks context-line match at the patch's hunks — it says
nothing about whether the file has drifted elsewhere.

For PR #3868, the drift was substantial. The pod's `bundle.py` is 14
lines shorter than PR base and predates the pool-allocation
body-emit refactor. The measurement therefore captured:

- The PR #3868 diff, PLUS
- The pool-allocation refactor being applied simultaneously (because
  the "head" state includes the refactor via the drifted lines).

We cannot separate the two contributions from this data. The
observed +65% `sdsc_bundle_gen` and −33% `dxp_standalone` may belong
to PR #3868, or to the pool refactor, or to some combination.

## What was tightened in the skill v0.2 policy

Alignment Tier 2 is now defined as **per-touched-file blob equality**,
not "diff applies cleanly":

- For each file the PR touches, fetch the base blob and compare
  byte-for-byte against the pod's copy.
- Any mismatch → escalate to Tier 3 (isolated checkout at exact
  base and head SHAs).

See `references/measurement-policy.md` "Tier 2 — Adequate:
per-touched-file blob equality".

## Attempted Tier 3 execution

An isolated checkout at the exact PR base (`2e935f...`) and head
(`a7786ac...`) SHAs was set up on the pod. Both trees checked out
cleanly with matching bundle.py md5s. But:

- Symlinking the pod's shared `_C.so` fails because the pod's C
  extension lacks `NativePermutationLayoutSolver`, added between
  pod's SHA and PR base. This symbol is imported top-level in
  scratchpad code and cannot be dodged.
- Rebuilding `_C.so` in the isolated tree fails at compile time
  because the pod's `/opt/ibm/spyre/deeptools/include/` predates
  `spyrecode-host-functions/fast_process_hcm.h`.

Per the tightened Tier 3 policy, this is `INSUFFICIENT_EVIDENCE`.
The measurement environment cannot support a valid A/B for this PR.

## What this case ultimately validated about the skill

The negative outcome — the retraction — is itself the validation:

- The initial marginal-patch measurement produced a plausible-looking
  result that could have been reported as a verdict.
- The alignment gate check caught the substrate drift.
- The Tier 3 attempt showed a legitimate failure mode (build blocked
  by system-lib age), which the policy explicitly names and routes
  to `INSUFFICIENT_EVIDENCE`.

If we had NOT tightened the policy, this case would have been
committed as a "clean A/B on a current PR" that isn't. Instead the
case reads: "here is the measurement we ran; here is why it is not
a validated PR-impact number; here is what would fix it."

## Lessons carried forward

1. Tier 2 alignment REQUIRES per-touched-file blob equality with the
   PR's actual base — not "diff applies cleanly".
2. When Tier 3 is blocked by system-lib age, `INSUFFICIENT_EVIDENCE`
   is the correct verdict. Do NOT fall back to a less-strict Tier.
3. The marginal-patch data is still worth preserving — it may
   inform hypotheses about the pool refactor's interaction with
   SDSC bundle emission — but it is not a validated PR verdict.
4. The skill's "predict → measure → learn" loop worked here even
   though the measurement was retracted: the prediction was
   preserved, the substrate mismatch was caught, and the policy
   was updated so the next PR does not repeat the error.

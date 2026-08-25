# The team's actual PyTorch upgrade process

Reconstructed from the 2.11, 2.12, 2.13 upgrade PRs, not from the
skill's documentation.

## Timing

- **2.11 upgrade** (#1930) — merged 2026-05-11. Weeks of wait time.
  Gated by multi-arch runner infra (#1997).
- **2.12 upgrade** (#2218) — merged 2026-07-28.
- **2.13 upgrade** (#3374) — merged 2026-07-29, ONE DAY after 2.12.

The 2.12 → 2.13 cadence is remarkable: they didn't wait for a
release cycle to prove out 2.12 before starting 2.13. Very likely
the 2.13 work was in progress in parallel and merged as soon as
2.12 landed.

## Author distribution

- 2.11: `bohnstingl` (external contributor)
- 2.12: `ani300` (IBM)
- 2.13: `ani300` (IBM)

The upgrade skill was AUTHORED by `bohnstingl` in the 2.11 PR.
`ani300` then used it for 2.12 and 2.13.

## Recurring pattern: the upgrade PR is not just the version bump

Every one of the three upgrades contains substantive fixes that
are NOT purely mechanical:

- **2.11:** `_monkey_patch.py` `user_stack` param fix.
- **2.12:** decomposition-broadening workaround, Dynamo `.to`
  graph-break fix, `size_hint` split, fp16 numeric xfails,
  vLLM-lag downstream architectural change (#357, separate repo).
- **2.13:** `pyobj_slot_` C++ rename, LX loop-order pre-fusion
  pass, profiler-test polish, upstream-test enablement request.

The upgrade PR is where these fixes LAND. They are not authored
against a green baseline first and then rebased into the upgrade
PR — they are discovered by trying the new torch, and fixed in the
same PR that bumps the version.

## Recurring pattern: unrelated dependency bumps get bundled

- 2.12: "I also used the excuse to do a dependency pass and update
  our other dependencies. If CI catches something we can decide if
  we want to avoid some of them."
- 2.13: "update deps to latest" commit.

This is expedient (one review, one merge, one lockfile regen) but
mixes concerns and makes historical reconstruction harder — some
of the diff isn't PyTorch-related at all.

## Recurring pattern: CI infrastructure lands in parallel

- 2.11: multi-arch test images landed via #1997 in parallel; 2.11
  merged after #1997 was in.
- 2.12: pytorch-commit tracking fix landed via #2274 first (2026-05-26).
- 2.13: upstream-tests-for-2.13 requested at merge time.

The upgrade PR is not fully self-contained; it has infrastructure
prerequisites the team recognizes and works around.

## Recurring pattern: downstream dependency lag

- 2.11 → 2.12: vLLM lag. Resolved by spyre-inference's own
  architectural change (#357) removing dependence on precompiled
  vLLM CPU wheels.
- 2.13: no new lag mentioned; presumed same architecture holds.

The bump is NOT gated on upstream vLLM catching up — the team
architected a way around that. That's a strategic decision worth
highlighting.

## Recurring pattern: silent correctness comes from unchanged APIs

Both 2.12 and 2.13 had at least one `SILENT_CORRECTNESS_CHANGE`.
Both stemmed from upstream doing INVISIBLE WORK in a public API
that torch-spyre relied on:

- 2.12: Dynamo's inlining behavior changed for the C++ `orig_to`
  call. No API signature changed. Old code compiled and produced
  wrong output.
- 2.13: `Scheduler._try_reorder_loops_for_candidates` computed then
  discarded a reorder. No API signature changed. Old code
  compiled and produced wrong output on LX-resident buffers.

The mechanical skill's watch list does not cover this class. The
forward-compat skill's Row-5 device-oracle IS the right shape to
catch them.

## Recurring pattern: upstream fixes go BOTH ways

- 2.12: `bohnstingl` landed his own upstream fix (pytorch/pytorch#185909)
  to make decomposition handling cleaner. Torch-spyre carries a
  workaround until 2.12.1.
- IBM-requested PrivateUse1 profiler features landed in 2.12.

The team is not passive downstream — they actively contribute
upstream to reduce future bump cost. This matters for the readiness
model: "did an upstream fix that we care about land in the target
release?" is a useful gate.

## Merge criteria in practice

Reconstructed from `"at this point it's ready to merge!"` moments:

1. `CI green` (green here means the maintained subset of upstream
   tests plus multi-arch runners).
2. Downstream dependency lag either resolved or bypassed
   architecturally.
3. Silent-correctness issues from earlier in the PR discussion
   have been addressed with either fixes or documented xfails.
4. Bundled dep-pass changes not causing new breakage.
5. Two-three-arch testing (x86 mandatory; s390x / ppc64le when
   available).

Not on the list: performance regression check. That's a separate
concern that `frontend-compiler-impact` would eventually cover; the
upgrade PRs did not gate on compile-time or run-time performance.

## Time-in-flight

- 2.11: weeks (infrastructure wait).
- 2.12: ~1-2 weeks (rough estimate from comment timestamps —
  from initial PR to merge).
- 2.13: ~1-2 days (very fast on the heels of 2.12).

Fast cadence when the infra is in place and the substantive fixes
compose cleanly. Slow when infra needs to catch up.

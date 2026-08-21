# F5 — Second forward-compat break blocks §7 replay execution on this substrate

**Discovered 2026-08-21 during §7 replay execution.**

## What happened

After cherry-picking `bf1ddc05e` to resolve F4 substrate-drift:

- Baseline (`dd95ef44 + bf1ddc05e` on torch 2.12.1+cpu): builds
  cleanly, `_C.so` loads, `torch.spyre.device_count() == 1`, eager
  works. rc=0. This is the correct "green baseline" for a §7 replay.
- Forward (`dd95ef44 + bf1ddc05e` on torch 2.13.0+cpu): **rebuild
  fails rc=1** with ccache misinvocation across all 15 .cpp
  translation units:

  ```
  FAILED: [code=1] .../csrc/module.o
  ccache: error: Could not find compiler "-MMD" in PATH
  ```

## Why

torch 2.13's `torch/utils/cpp_extension.py` invokes ninja with a
different argument order than torch 2.12 did, in a way that causes
ccache (given `CXX="ccache c++"`) to interpret `-MMD` as the
compiler-name argument. The exact torch commit that changed this is
not identified yet.

Same source tree, same substrate, same `CXX` — the only variable is
torch version. That makes this a legitimate `TORCH_SPYRE_BUILD_API_BREAK`
in the taxonomy: torch changed a build-integration contract in a way
that torch-spyre's build recipe assumed to be stable.

## Why the earlier a3128985 build against 2.13 nightly worked

The forward-compat run in `cases/current-main` used **the same
approach** and produced `_C.so` successfully against torch 2.15.0.dev
nightly. That build's `_C.so` had six undefined symbols after the
pipeline-defect swap (F1), but the build itself succeeded rc=0.

Comparison:

| Config | torch | Result |
|---|---|---|
| a3128985 + a3128985-tree | 2.13.0+cpu (venv-supported) | build rc=0 |
| a3128985 + a3128985-tree | 2.15.0.dev nightly (venv-latest) | build rc=0 |
| dd95ef44 + bf1ddc05e | 2.12.1+cpu | build rc=0 |
| dd95ef44 + bf1ddc05e | 2.13.0+cpu | **build rc=1, ccache -MMD error** |

The pattern: **only the dd95ef44+bf1ddc05e combination against exactly
2.13.0** breaks. That's a strange four-way isolation. Possible
mechanisms:

1. Between bf1ddc05e (2026-07-31) and a3128985 (2026-08-21), some
   commit updated build_ext / setup.py in a way that survives torch
   2.13's build-integration change. The historical replay is *supposed*
   to test dd95ef44's response to torch 2.13 — but the fix that lets
   the build succeed against 2.13 hasn't been cherry-picked in yet.
2. Or a5-deepview's ccache config drifted between the two builds
   somehow.

Option 1 is very likely. torch-spyre@754839cc8 ("Upgrade to pytorch
2.13 (#3374)") probably contains build-side changes to make the
build work against 2.13. That's actually part of the story — the
skill is supposed to identify what a torch bump requires torch-spyre
to change, and build-integration is a legitimate class of that
change.

## Implication for the §7 replay

The intent of §7 was to see whether the skill could independently
find the LX producer/consumer semantic break — a **runtime**
correctness issue, not a build-time issue. On this substrate, we
would need to also identify and cherry-pick whatever build-integration
change from 754839cc8 lets the build against 2.13 succeed, and only
then would we see the LX semantic break at runtime.

That is a two-step replay:

1. Substrate-align to bf1ddc05e (done).
2. Build-align to whatever hunk from 754839cc8 enables 2.13 builds
   (deferred).
3. Then verify the LX semantic break surfaces on aminmax tests.

Cherry-picking the *build-side* of 754839cc8 without the LX-fix
scheduler.py addition would give the skill the exact starting state
Todd's §7 asked for: a torch-spyre that builds against 2.13 but has
the semantic bug. That is a v0.2 escalation.

## Failure taxonomy

**`TORCH_SPYRE_BUILD_API_BREAK`** — torch's cpp_extension build-line
generation changed between 2.12 and 2.13 in a way that broke
torch-spyre's ccache invocation. Not the LX semantic break we're
chasing; a separate finding.

## What v0.1 got right despite the incomplete replay

The skill's discipline held again:

- No preemptive patch was applied to torch-spyre@dd95ef44 during the
  first (failing) build. The failure was classified as
  `SUBSTRATE_FAILURE` (F4) and root-caused before any code touch.
- After F4 was applied (cherry-pick bf1ddc05e), the *next* failure
  was classified as its own distinct finding (F5), not conflated
  with F4 or with the yet-unreached LX break.
- The three-state contract held: baseline (2.12) is green, forward
  (2.13) fails — that's the correct discriminator for a forward-compat
  investigation.

## Session state

Baseline `_C.so` is on disk at
`/home/tdeshane/replay-pt213/torch-spyre-parent/torch_spyre/_C.so`
(66 MB, built 2026-08-21T20:37:17Z). It's the last known-good state
for the historical replay setup. The next session should either:

1. Reuse this state as the replay's SUPPORTED_CONTROL and identify
   which build-side hunk of 754839cc8 unblocks the forward-2.13 build.
2. Move to a properly newer substrate where 754839cc8's full patch
   set is not needed (an older `torch-aiu-runtime-dev` image variant
   that shipped alongside torch 2.12 / early 2.13).

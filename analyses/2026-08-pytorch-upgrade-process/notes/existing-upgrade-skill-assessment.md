# Existing `upgrade-pytorch-version` skill — assessment

Source: `torch-spyre@613b259:.claude/skills/upgrade-pytorch-version/SKILL.md`
(local snapshot at `../skill-replay/SKILL.md.snapshot`, 580 lines).

## What the skill mechanizes well

- **Version-string editing across the tree.** Six lines in
  `pyproject.toml` (three active, three commented alternatives), URL
  strings in `pyproject.toml` filterwarnings comments,
  `upstream_tests.yaml` (comments only — logic is version-agnostic),
  `project-overview/SKILL.md`, `installation.md`, `checkout-pytorch-src.sh`,
  `build-torch-spyre.sh` (sed patterns — both forward and trap),
  `dev_install.md`, `profiling_tools.md`. All specific paths, all with
  a rule for what the substitution should be.
- **Lockfile-and-requirements protocol.** Instructs the operator to run
  `tools/update-requirements.sh` rather than freehand `uv` commands,
  because the script encodes the exact `--no-emit-package torch` flag
  set the project depends on.
- **C++ ABI story.** Warns explicitly that PyTorch doesn't maintain C++
  ABI stability across minor versions, lists the extensions that must
  be rebuilt (vllm `_C.abi3.so`, torch-spyre `_C.so`/`_hooks.so`,
  torchvision/torchaudio), gives the diagnostic (`nm -D
  --undefined-only ... | grep _ZN3c10`), and notes a specific vllm
  libgomp shim pitfall with a full worked recipe.
- **Legacy vs. modern split.** Explicitly documents the pre-`faad75c`
  codegen pipeline and the two bugs it hit in the PT 2.11 upgrade
  (`schemas[19:]` hardcode, `Scalar`-inside-`ScalarType` substring bug)
  as historical notes, so an operator on an old release branch can
  find them, but marks the current path as skipping this entirely.
- **Verification grep** for stale `$OLD` references — including a
  useful reminder to grep for INTERMEDIATE versions (e.g. `2.11 | 2.12`
  when going 2.10 → 2.13) because a prior skipped upgrade may have
  left a comment behind.

## What the skill assumes is already known

- **PyTorch source at target version is already checked out and built.**
  Prerequisite check runs `git describe --tags` in `$PYTORCH_DIR` and
  refuses if the tag doesn't match. This is a HARD external
  prerequisite the skill does not fulfil on its own — no clone, no
  fetch, no build.
- **`DTI_PROJECT_ROOT` env or well-known locations.** Falls back to
  `~/dt-inductor` or `~/torch-spyre`. Fine for the dev-pod layout,
  fragile for anywhere else.
- **kineto-spyre wheel availability.** Says "the wheel for the new
  version may not yet be published" and asks the operator to verify.

## What it explicitly punts

- **API breakage discovery.** The "Potential Breakage" section names
  seven categories (op signatures, new ops, removed/renamed ops,
  Inductor API, deprecation warnings, Dynamo/guard API,
  skipped-version accumulation, legacy codegen drift, downstream C++)
  but the strategy is "watch for" — grep + read release notes. No
  automated diff between torch versions, no test that would surface
  each category before the operator sees a red run.
- **Compiler-semantic changes.** Not addressed at all — the skill's
  mental model is that PyTorch releases change APIs (which are
  greppable) rather than semantic behavior of an unchanged API
  (which isn't). Cases like F8 (torch's `FallbackKernel.create` now
  taking a `create_direct_output` path with a different layout shape,
  no signature change) are outside this skill's field of view.
- **Runtime autoload / import-ordering hazards.** F3 was not a
  version bump — it was live on every torch-spyre main SHA we tested,
  irrespective of torch version. The skill's frame is "PyTorch
  changed, chase it," not "torch-spyre changed, an old torch behavior
  now fails."
- **Cross-repo dependency status.** vLLM, spyre-inference, hf-adapters
  compatibility is named as "must rebuild" but there is no readiness
  check for each — no "is vLLM main's HEAD already compatible with
  target torch."
- **Nightly / RC handling.** Assumes a real release branch/tag.
  NIGHTLY_PROXY-style tests against a pre-release torch aren't in the
  vocabulary.

## What it does about API changes

Item 5a in "Potential Breakage" is illustrative: it documents that
PyTorch 2.11 added a required `user_stack` parameter to
`add_lambda_guard`, called out where the monkey-patch is
(`torch_spyre/_monkey_patch.py`), and cites where to check the new
signature (`torch/_C/_dynamo/guards.pyi`). That's HISTORY — it
records what happened after the fact. There's no procedure for
detecting the next such change *before* seeing it break.

## What it does about C++ ABI

Best-covered area. It's the item with the longest treatment in the
"Potential Breakage" list and has its own step 9. Gives:

- diagnostic script (nm scan for unresolved `_ZN3c10*` symbols)
- rebuild table (vllm, torch-spyre, torchvision)
- specific vllm libgomp shim pitfall
- verification via CMake `if(EXISTS)` follow-symlinks trap
- recurrence note (redo symlinks after every PyTorch source rebuild)

Nothing about the ABI-check being automated — it's an operator
recipe.

## What it does about downstream projects

Named: vllm, torchvision, torchaudio, custom kernels. Actionable
step: "rebuild against new torch." No readiness gate — "does vllm
main compile against torch $NEW today?" — which the historical
record suggests HAS actually blocked upgrades.

## What it does about release branches / wheels

Steps 6-8 handle release branches (`release/$NEW` on PyTorch clone),
kineto-spyre wheels (URL update + "verify wheel exists"), and CPU
index wheel availability for the lockfile regenerator. Recognized
but not gated — the skill will do the pyproject bump even if the
wheel isn't published; it just tells the operator to skip lockfile
regen.

## What it does about CI

Step 4 says `upstream_tests.yaml`'s logic is version-agnostic
(dynamic pyproject read), so only the comments need touching.
Nothing about the `_test_matrix.yaml` or the integration/regression
runners. Nothing about the CI infra I need to inspect for Track A.

## What it cannot know until empirical testing

By the skill's own framing, "Potential Breakage" is a runtime
discovery process. No stage before rebuild-and-run flags:

- an API signature drift;
- a semantic change in an unchanged API;
- an inductor decomposition change;
- a scheduler / IR shape change that changes which ops fire;
- a symbolic-shapes change that alters guard emission;
- an autoload / device-registration change.

## Rough shape of what a replay would show

If we were to hand the skill a torch-spyre checkout at PT-2.11 and
say "upgrade to 2.12":

- **Definite hits:** the mechanical file edits are laid out well —
  the skill would produce the correct pyproject.toml diff (all 6
  lines), the correct comment-URL updates, the correct docs edits,
  the correct build script sed patterns.
- **Probable miss for 2.11 → 2.12:** any dynamo/inductor API drift
  between those versions (guard signatures, decomposition tables,
  scheduler internals) that torch-spyre had to chase. The skill
  names *categories* to watch, but doesn't produce a candidate list
  of touch points.
- **Probable miss:** anything that required an actual test run and
  a follow-up commit on the same PR (as the historical evidence
  shows).

The empirical replay in Task #70 is what tests these predictions.

## Working hypothesis, to test via replay

**upgrade-pytorch-version = mechanical migration executor.**
**torch-spyre-forward-compat = empirical compatibility discoverer.**

They compose: forward-compat identifies the API/semantic touch
points that the upgrade skill "watches for," and the upgrade skill
executes the mechanical migration once forward-compat has cleared
the substantive obstacles.

The replay in Task #70 is what confirms or falsifies this split.

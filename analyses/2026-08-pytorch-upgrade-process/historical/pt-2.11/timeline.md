# PT 2.11 upgrade — timeline

- **PR:** [`torch-spyre/torch-spyre#1930`](https://github.com/torch-spyre/torch-spyre/pull/1930)  
  "[FEATURE] Update to PT 2.11", author `bohnstingl`.
- **Tracking issue:** #1315 (author `bohnstingl`, closed by @ani300).
- **Merge commit:** `539a1a0c2d54b228c19c982ee80044e210bcde98`
- **Merged:** 2026-05-11.
- **Head branch:** `pt211_update`.
- **Diff shape:** 11 files, +647 / −81.
- **Commits (linearized):**
  - `bdd760dd` — "Updated files for PT 2.11" (single functional commit)
  - a series of `Merge branch 'main' …` merges from 9a639936 through 50efc5f6

## Files touched

```
.claude/skills/project-overview/SKILL.md
.claude/skills/upgrade-pytorch-version/SKILL.md   <-- this PR AUTHORED the upgrade skill
.github/workflows/upstream_tests.yaml
.github/workflows/upstream_tests_beta.yaml
docs/source/getting_started/installation.md
pyproject.toml
requirements/build.txt
requirements/dev.txt
requirements/run.txt
torch_spyre/_monkey_patch.py
uv.lock
```

## What triggered the upgrade

Standing team practice — "keep up with stable PyTorch releases at least
until we start locking down dependencies for a release" (issue #1315
body). No specific compatibility break drove it; it was a routine
release-tracking bump.

## Consequences that surfaced in the PR

### VERSION_BOOKKEEPING (mechanical)

- `pyproject.toml`: three active `torch~=2.11.0` deps + three commented
  alternatives + comment URLs in `filterwarnings`.
- `installation.md`: version-requirement table row.
- `.github/workflows/upstream_tests*.yaml`: version-string examples in
  comments (logic reads pyproject dynamically).
- `.claude/skills/project-overview/SKILL.md`: version reference.

### LOCKFILE_REGENERATION

- `uv.lock` + `requirements/*.txt` regenerated. Diff was large but
  mechanical.

### PYTHON_API_BREAK — `_monkey_patch.py:200`

The only non-mechanical Python-source change. `torch._C._dynamo.guards
.GuardManager.add_lambda_guard` gained a required third argument
`user_stack` in PT 2.11:

```diff
     ),
     [f"SpyreTensorLayout({guard.name}) == {expected_layout}"],
+    guard.user_stack,
 )
```

Discovered by the author running the test suite; called out explicitly
in a review comment when @ani300 asked "just curious, why is this
needed?" and @bohnstingl replied "PyTorch 2.11 changed the signature of
`torch._C._dynamo.guards.GuardManager.add_lambda_guard`. It now requires
a third argument `user_stack`. The old 2-arg form (lambda,
verbose_code_parts) from 2.10 is no longer accepted."

Category: `PYTHON_API_BREAK`. Specifically a Dynamo guard-API drift
that is not visible until an actual guarded compile runs.

### CI_INFRASTRUCTURE_CHANGE — codegen removal timing

Reviewer @dgrove-oss commented "We removed the entire codegen direction
from main in #1875. Bad merge?" — the PR had inadvertently included
edits to the removed `codegen/` tree because the author started work
before #1875 landed. Author responded "@dgrove-oss most likely. Let me
correct." and rebased.

The takeaway: mechanical upgrade skill needs to know that pre-`faad75c`
codegen is gone in modern main; the SKILL.md.snapshot documents this
in its Step 3 "Legacy" note.

### DOWNSTREAM_DEPENDENCY_LAG — profiling

At issue-close (from @ani300): "Our profiling infrastructure broke
because of the update, but it's also broken from parallel runtime
changes. The update to 2.12 this week will both resolve it and make it
simpler to maintain in the future, so we can close this as completed
for now!"

Key point: PT 2.11 had a KNOWN follow-up cost that was NOT resolved in
this PR — the profiler broke and was punted forward to be handled in
the 2.12 upgrade PR. This is a data point for "PT bump work spans
multiple PRs, not one."

### CI_INFRASTRUCTURE_CHANGE — multi-arch gating

Merge was gated by three-arch testing:
- ✅ testing on x86
- ⏸ testing on s390x
- ⏸ testing on ppc64le

@HarikrishnanBalagopal: "We don't have that yet, we just merged a new
test with newer multi-arch images (PR #1997). If Nicholas and the rest
of the team is ok with it we can go ahead and merge this PR."

The multi-arch test infrastructure landed IN PARALLEL to this PR (via
#1997). Merged with x86 alone once #1997 was in.

Two upstream-test failures at merge time were dismissed as unrelated:
"Those two are upstream tests, they are failing for different known
issue(s), you can ignore those for now" — @HarikrishnanBalagopal.

## Bundled work

- **Skill authoring.** `.claude/skills/upgrade-pytorch-version/SKILL.md`
  was AUTHORED in this same PR. The upgrade skill exists because this
  upgrade happened. The pattern of "upgrade to X and document how to do
  the next one" was set here.
- **Reviewer edits.** @yoheiueda caught two things:
  - the pyproject filterwarnings URL didn't need a version bump because
    PT 2.10 introduced the warning, not 2.11 (i.e. some URLs point at
    the version that FIRST emitted the warning, not the current pin);
  - a line-number in a URL comment shifted, so bumping only the version
    string but not the anchor produces a broken link.

## Post-merge

- Profiler infrastructure remained broken; picked up in 2.12.
- The upgrade skill authored here is what @ani300 will use for 2.12
  and 2.13.

## Criteria used to say "ready to merge"

- (implicit) x86 CI clean.
- Multi-arch testing acknowledged as follow-up.
- Two failing upstream tests dismissed as pre-existing.
- No integration/regression device-suite reference was made.
- No explicit "downstream projects rebuilt" gate — just "we can merge
  and deal with profiler in 2.12."

## Time from PR open to merge

Not measured precisely, but the discussion threads mention "just merged
a new test with newer multi-arch images https://github.com/torch-spyre/
torch-spyre/pull/1997" indicating this PR spent time waiting on that
infrastructure PR. Order of days-to-weeks at minimum.

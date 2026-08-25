# Skill replay — 2.11 → 2.12

**Starting state:** torch-spyre @ `a84df55f` (2.12 PR base), pyproject
declares `torch~=2.11.0`.

**Target:** `2.12` (per `upgrade-pytorch-version` skill's argument
contract).

**Skill being replayed:** `.claude/skills/upgrade-pytorch-version/`
snapshot at `SKILL.md.snapshot` (580 lines), i.e. the file authored
in the 2.11 upgrade PR itself.

The skill's OWN framing is that it produces the mechanical file
edits plus a "Potential Breakage" watch list — not that it runs
tests. So the replay compares:

1. What files did the skill say to edit? → check against the actual
   #2218 file list.
2. What did the skill's "Potential Breakage" list flag?
3. What actually broke in #2218 that the skill did NOT flag?

## What the skill would produce (files edited, per SKILL.md Steps 1-9)

- `pyproject.toml`
  - three active `torch~=2.11.0` → `torch~=2.12.0`
  - three commented `#    "torch>=2.11.0"` → `#    "torch>=2.12.0"`
  - filterwarnings URL update (with @yoheiueda's caveat about tags vs.
    line-shifts — but the skill DOES mention updating "the URL
    version" and "Note: if an intermediate version was skipped, the
    comment URL may reference a version older than $OLD")
- `.github/workflows/upstream_tests.yaml` — comment strings only
- `.github/workflows/upstream_tests_beta.yaml` — comment strings only
- `.claude/skills/project-overview/SKILL.md` — version reference
- `docs/source/getting_started/installation.md` — version table row
- `torch-spyre-docs/scripts/checkout-pytorch-src.sh` (external repo,
  outside PR)
- `torch-spyre-docs/scripts/build-torch-spyre.sh` (external repo)
- `torch-spyre-docs/docs/dev_install.md`
- `torch-spyre-docs/docs/profiling_tools.md`
- lockfile regen via `tools/update-requirements.sh`
- verification grep for stale `$OLD` and any intermediate versions

## What actually happened in PR #2218

Files touched (39 total):

**Match with skill's plan (in-repo only, 5 mechanical files):**

- ✅ `.claude/skills/project-overview/SKILL.md`
- ✅ `docs/source/getting_started/installation.md`
- ✅ `pyproject.toml`
- ✅ `requirements/{build,dev,run,lint}.txt` (four files; skill names
  "requirements/*.txt")
- ✅ `uv.lock`

The skill did NOT prescribe:

- `.pre-commit-config.yaml` (upgraded pre-commit versions bundled in)
- `.github/scripts/ingest_xml.py` (CI ingest script; unrelated)

The skill DID prescribe `.github/workflows/upstream_tests*.yaml`
edits, but the actual PR did NOT touch them. Why? Either the
comments already had 2.11 examples that weren't outdated relative to
2.12 (grep-only claim), or the author skipped that mechanical step.
An audit of the 2.11 PR's diff on those files shows THAT one DID
touch them, so the pattern differs between 2.11 and 2.12 authors.

## API/semantic breaks — what actually broke in #2218

None of these were in the SKILL.md file list. All appeared in the
"Potential Breakage" watch list only as CATEGORIES, not as specific
call sites:

| Break | SKILL "watch for" match | Detail |
|---|---|---|
| `size_hint` split | Item 4: "Inductor API changes" (generic) | Skill did not name `V.graph.sizevars.size_hint`; discovered by rebuild-and-run + review. |
| Decomps broadened (mm/bmm K==1, arange/tril/…) | Item 4 + item 2 "New ATen ops we don't yet register" | Skill named the category. Did not predict which ops. Discovered via compile-time assertion. |
| Dynamo `.to` inlining graph-break | Item 5a: "Dynamo / guard API changes" (partial) | Skill named the category but only in terms of "signature changes." A behavior change with no signature change was outside the watch item's frame. Discovered via wrong dtype cast. |
| fp16 CPU-ref numerics drift (3 xfails) | Not in watch list at all | `TEST_EXPECTATION_CHANGE` from an upstream numeric change was outside the skill's frame. |
| PrivateUse1 profiler API (positive) | Not in watch list; IBM-requested feature | Adding a new upstream feature that resolves an outstanding 2.11 breakage. |
| vLLM downstream lag | Item 8: "Downstream C++ extensions must be rebuilt" (partial) | Skill covered ABI-rebuild, not "vLLM hasn't moved to the new torch yet." Discovered via reviewer comment. |
| `psutil` pin loosening | Not in watch list | Bundled dependency-pass housekeeping. |

## Coverage score for 2.11 → 2.12

**Mechanical files:**

- Prescribed by skill and actually needed: 5 / 5.
- Prescribed by skill but not needed on this PR: 2
  (workflow-comment edits — skill was overzealous on this pair for
  2.12's diff, though correct in general).
- Needed on this PR but not prescribed: 2 (pre-commit config; CI
  ingest script — both bundled/hygiene, not intrinsic to the bump).

**Potential-Breakage watch categories:**

- Correctly named categories: 4 (Inductor API, new/renamed ATen
  ops, Dynamo/guard API, downstream C++).
- Categories missed as such: 1 (CPU-reference numeric drift causing
  test expectations to shift; not stated in the "Potential
  Breakage" list at all).
- Categories named but too narrow: 2 (Dynamo watch item asked for
  signature changes only; downstream rebuild watch item covered
  ABI rebuilds only, not "downstream hasn't moved yet").

**Substantive predictions (specific line/file/API):** 0. The skill's
job is to produce mechanical edits and a watch list. It does not
predict which specific PyTorch symbols will change.

## What a replay would tell someone starting the 2.11 → 2.12 work

- ✅ pyproject.toml diff will be right the first time.
- ✅ lockfile regen path will be right.
- ✅ downstream project-overview reference will be updated.
- ✅ docs table will be updated.
- ⚠️ Do NOT expect the skill to tell you `size_hint` was split. Or
  that decompositions moved. You will discover that by building and
  running.
- ⚠️ Do NOT expect the skill to tell you Dynamo will graph-break
  when inlining your `.to` wrapper. You will find that from a
  wrong dtype cast.
- ⚠️ Downstream vLLM may not be ready — the skill doesn't check.

The skill is honest about this: its "Potential Breakage" section
is explicitly a "watch for" list, not a discovery procedure.

## Conclusion

**The skill's job is well-defined and mostly well-executed:**
mechanical migration file edits, in the right order, with the
right sed patterns, with recovery-from-skipped-versions hygiene.

**The skill is not a discovery tool** for API drift or semantic
change. Every one of the substantive PT 2.12 breaks (`size_hint`,
decompositions, Dynamo `.to`) was discovered by rebuild-and-run
followed by review, NOT by inspecting the skill's output.

That is exactly the split between mechanical migration and
empirical compatibility that Track A / Track B's dividing line
suggests. The upgrade-pytorch-version skill handles the mechanical
half; something else — the `torch-spyre-forward-compat` skill — is
what would produce the specific-symbol predictions the mechanical
skill doesn't.

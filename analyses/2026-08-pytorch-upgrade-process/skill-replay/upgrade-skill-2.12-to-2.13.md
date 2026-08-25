# Skill replay — 2.12 → 2.13

**Starting state:** torch-spyre @ `dd95ef44` (2.13 PR base), pyproject
declares `torch~=2.12.0`.

**Target:** `2.13`.

## What the skill would produce (same shape as 2.11 → 2.12)

- `pyproject.toml`: six lines
- `.github/workflows/upstream_tests*.yaml`: comment strings
- `docs/source/getting_started/installation.md`: version row
- `.claude/skills/project-overview/SKILL.md`: version ref
- external `torch-spyre-docs` scripts + docs
- lockfile regen

## What actually happened in PR #3374

Files touched (13 total):

**Match with skill's plan:**

- ✅ `pyproject.toml`
- ✅ `docs/source/getting_started/installation.md`
- ✅ `.claude/skills/project-overview/SKILL.md`
- ✅ `requirements/{build,dev,run,lint}.txt`
- ✅ `uv.lock`

**Not prescribed by the skill (substantive fixes):**

- ❌ `torch_spyre/csrc/spyre_tensor_impl.cpp` — the `load_pyobj_
  interpreter` → `getGlobalPyInterpreter` one-line C++ rewrite.
- ❌ `torch_spyre/_inductor/passes.py` and `scheduler.py` — the LX
  producer loop-order alignment pass (semantic correctness fix).
- ❌ `tests/inductor/test_inductor_ops.py` +
  `tests/configs/upstream_tests/test_profiler_config.yaml` —
  test-expectation follow-through.

Note: `.github/workflows/upstream_tests*.yaml` was NOT touched again
(same pattern as 2.12).

## API/semantic breaks — coverage

| Break | SKILL "watch for" match | Detail |
|---|---|---|
| `load_pyobj_interpreter` removed | Item 8: "Downstream C++ extensions must be rebuilt" — but this is a torch-spyre-own C++ break, not a downstream rebuild issue. The skill's C++ story is ABI-rebuild diagnostics (`nm` unresolved symbols). It gets you halfway there — you'd hit the undefined-symbol trace at build time, know it's a C++-side break, and be pointed at `_ZN3c10*` mangled names. Then you'd have to look up the new name yourself. | The forward-compat skill's F6 case DID predict this specifically. |
| LX loop-order accidental correctness | Item 4: "Inductor API changes" is the closest but this isn't an API change — it's a semantic change in an unchanged API. Not on the watch list in that framing. | Silent wrong results. Author found via failing tests: "required for PT 2.13, otherwise CI is not green." |
| Profiler / inplace-op test config | Not enumerated. Item 4 (Inductor API) covers changes, item 1 (Op signature changes) partial. | Would surface via test failure. |
| Upstream-tests-for-2.13 enablement | Not covered by the mechanical skill; it's a workflow/config change orthogonal to the source. | Requested via team discussion at merge time. |

## Coverage score for 2.12 → 2.13

**Mechanical files:**

- Prescribed and actually needed: 5 / 5 (pyproject, docs, lockfiles,
  project-overview).
- Prescribed but not needed: 2 (upstream_tests*.yaml — again).
- Needed but not prescribed: 4 (the C++ ABI break; the two Inductor
  scheduler-side files; the two test-expectation files).

**Potential-Breakage watch categories:**

- Correctly named: 2 (Inductor API — generic; downstream C++ /
  ABI — partial).
- Missed: 2 (SILENT_CORRECTNESS_CHANGE from internal-behavior drift
  in an unchanged API is not on the list at all; specific `c10::impl`
  symbol removals require an ABI-rebuild pass to find, which the
  skill outlines but does not automate).

**Substantive predictions:** 0.

## The interesting differential: forward-compat skill DID predict F6

The historical-replay `cases/historical-replay-pt213/` folder shows
the `torch-spyre-forward-compat` skill, given only the pre-upgrade
torch-spyre tree + torch 2.13.0, derived the byte-identical
`pyobj_slot_.load_pyobj_interpreter()` → `(*c10::impl::
getGlobalPyInterpreter())` fix ahead of time. That's a full "the
compatibility skill would have saved this step" case — it is what
the mechanical upgrade skill's Potential-Breakage list gestured at
without producing.

Similar prediction is likely POSSIBLE for the LX loop-order case
too: given a differential test that computes reductions on an LX-
resident buffer with two consumers, the forward-compat pipeline's
Row-5 device-correctness oracle would have caught the wrong result
(that oracle is EXACTLY the thing the forward-compat verify_patch
requires when a fix touches a tensor-producing path). But we didn't
run it against the 2.12 → 2.13 delta empirically; that's a future
experiment.

## Conclusion

For 2.12 → 2.13, the mechanical skill got the 5 mechanical files
right and the 4 substantive ones NOT prescribed. That's a smaller
mechanical footprint than 2.12 (which was also 5 files) but a
proportionally BIGGER share of substantive fixes (4 substantive vs.
5 mechanical; 2.12 was ~4 substantive vs. 5 mechanical too, so the
ratio holds).

The consistent picture across both replays: the upgrade skill's
mechanical accuracy is high; its predictive value for substantive
breaks is zero (by design). The next torch bump WILL still surface
one or more substantive breaks that appear only at rebuild-and-run
time. A readiness model that wants to predict those needs a
different mechanism — the forward-compat skill's continuous shadow
lane, run in the weeks BEFORE the official bump, is that
mechanism.

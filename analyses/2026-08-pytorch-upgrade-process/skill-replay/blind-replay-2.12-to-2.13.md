# Blind replay: 2.12 → 2.13 — fresh Claude session output

## Methodology

A fresh general-purpose subagent was given:

- torch-spyre checkout at `3c1c67de61c4cd3c0ae136e43d3a75dabad10e95` (the
  parent of the 2.13 upgrade PR's first commit).
- Access to the `.claude/skills/upgrade-pytorch-version/SKILL.md` **as it
  existed at that SHA**.
- Target version string: "2.13".
- **Hard rules:** no reading of PR #3374 or its diff; no reading of any
  file under `/Users/tdeshane/toddllm/compiler-timing`; no time-machine
  peeks.

## Subagent output — verbatim

    ## Blind replay: torch-spyre @ 3c1c67de → PyTorch 2.13

    ### Skill sections invoked
    1-12. Same sequence as 2.11→2.12 replay.

    ### Files the skill prescribes to edit
    In-tree:
      - pyproject.toml (Step 1: six lines in three sections)
      - pyproject.toml filterwarnings (Step 2)
      - .github/workflows/upstream_tests.yaml (Step 4)
      - .github/workflows/upstream_tests_beta.yaml (Step 5)
      - .claude/skills/project-overview/SKILL.md (Step 5)
      - docs/source/getting_started/installation.md (Step 5)
      - uv.lock + requirements/*.txt (Step 8, via update-requirements.sh)

    Out-of-tree (torch-spyre-docs):
      - scripts/checkout-pytorch-src.sh (Step 6)
      - scripts/build-torch-spyre.sh (Step 6)
      - docs/dev_install.md (Step 7)
      - docs/profiling_tools.md (Step 7)

    ### Potential Breakage predictions
    Same watch-list categories as the 2.11→2.12 replay:
      1. Op signature changes
      2. New ATen ops we don't yet register
      3. Removed/renamed ops
      4. Inductor API changes
      5. Deprecation warnings
      5a. Dynamo/guard API changes
      6. Skipped-version accumulation (n/a)
      7. Legacy codegen drift (n/a)
      8. Downstream C++ extensions must be rebuilt

    ### Verification steps the skill prescribes
    Same as 2.11→2.12: grep for stale "2.12" refs, rebuild, pytest
    inductor_ops.

    ### Actions the skill does NOT cover
    Same list as 2.11→2.12: no concrete API-drift patches, no ATen
    enumeration, no kineto wheel verify, PyTorch build out of scope,
    no PR/CI templates, no version guards.

    ### Confidence
    Not mergeable as-is. High confidence on mechanical text edits.
    Low confidence on "will it build and pass tests" — that's the
    watch-list territory the skill flags but doesn't resolve.

## Grading — blind replay vs. actual PR #3374

### Mechanical file coverage

The actual PR #3374 modified **13 files**.

**In-tree files the blind replay named that the actual PR also modified:**

| File | Predicted | Actual |
|---|---|---|
| `pyproject.toml` | ✅ | ✅ |
| `.claude/skills/project-overview/SKILL.md` | ✅ | ✅ |
| `docs/source/getting_started/installation.md` | ✅ | ✅ |
| `uv.lock` + `requirements/*.txt` (4 files) | ✅ | ✅ |

**In-tree files the blind replay named that the actual PR did NOT modify:**

| File | Predicted | Actual |
|---|---|---|
| `.github/workflows/upstream_tests.yaml` | ✅ | ✗ |
| `.github/workflows/upstream_tests_beta.yaml` | ✅ | ✗ |

Same over-prediction pattern as 2.12: comment-only edits the team
chose not to apply. Consistent across both replays and both audits.

**Files the actual PR modified that the blind replay did NOT specifically
predict:**

- `torch_spyre/_inductor/passes.py` — Inductor internals (watch #4 match)
- `torch_spyre/_inductor/scheduler.py` — the LX loop-order pre-fusion
  pass (`OBSERVED_SILENT_WRONG_OUTPUT`; matches watch #4 as a category
  but the specific mechanism — a compute-then-discard reordering
  upstream — is not in the skill's watch list)
- `torch_spyre/csrc/spyre_tensor_impl.cpp` — CXX_ABI_BREAK
  (`c10::impl::PyObjectSlot::load_pyobj_interpreter` rename). Matches
  watch #8 ("Downstream C++ extensions must be rebuilt") as the
  category, but the specific rename is not named. Note: our
  forward-compat skill's F6 case predicted this rename byte-identically
  before the upgrade; the mechanical upgrade skill did not.
- `tests/configs/upstream_tests/test_profiler_config.yaml` — profiler
  config for the new target (matches CI_INFRASTRUCTURE_CHANGE from
  the consequence taxonomy; not in the skill's file list)
- `tests/inductor/test_inductor_ops.py` — test edits

### Substantive break coverage

| Category | Blind replay | Actual case |
|---|---|---|
| CXX_ABI_BREAK | Watch #8 (rebuild C++ extensions) | `pyobj_slot_` rename — specific fix outside skill's naming |
| INDUCTOR_SEMANTIC_BREAK (LX loop-order) | Watch #4 category match; specific mechanism not named | scheduler.py rewrite to defend against upstream's compute-then-discard |
| CI / test config | Not named | test_profiler_config.yaml new target |

The LX loop-order case is the `OBSERVED_SILENT_WRONG_OUTPUT` for this
upgrade. As with 2.12's Dynamo `.to`, the skill's watch category is
correct but the specific mechanism is not enumerated.

### Coverage summary

| Measure | Value |
|---|---|
| Mechanical files predicted and needed | 4 |
| Mechanical files predicted but not needed | 2 (upstream_tests, upstream_tests_beta) |
| Mechanical files needed but not predicted | 3 in-tree (test_profiler_config, plus edits driven by substantive fixes) |
| Substantive breaks specifically predicted | 0 |
| Substantive-break CATEGORY match rate | 2/2 major categories (CXX_ABI_BREAK, INDUCTOR_SEMANTIC_BREAK) |
| Forward-compat skill's cross-check | F6 case (in our repo) predicted the CXX_ABI_BREAK by-symbol; the mechanical upgrade skill did not |

## Conclusions

1. **Both blind replays reproduce the retrospective audit numbers
   exactly.** The audit's 5/5 mechanical + 2 over-prediction pattern
   holds under blind methodology.

2. **The forward-compat skill catches something the mechanical upgrade
   skill doesn't.** The F6 case (`pyobj_slot_` rename) is a specific
   symbol prediction; the upgrade skill's watch #8 is a category
   assertion. Both are useful; they're different jobs, as the
   audit-vs-replay note argues.

3. **Watch #4 needs a sub-item on "internal-behavior drift with
   unchanged signatures".** Both 2.12's Dynamo `.to` and 2.13's LX
   loop-order fall under watch #4 as a category but the mechanism
   they represent — internal semantic behavior changing without
   API signature changes — isn't specifically flagged. This is the
   `OBSERVED_SILENT_WRONG_OUTPUT` category from the tightened
   taxonomy.

## Delta from the earlier retrospective audit

Same mechanical numbers. The blind replay confirms the audit was not
inflated by hindsight. The only refinement worth pushing back to the
skill (if we were to propose changes — which the correction commit
explicitly deferred) is a named sub-item for
`OBSERVED_SILENT_WRONG_OUTPUT` under watch #4. That's a specific,
actionable improvement grounded in two concrete historical cases.

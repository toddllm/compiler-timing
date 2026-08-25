# Static triage — 216 open PRs

Snapshot: torch-spyre main @ `613b259` (2026-08-25).

## Distribution

| Class | Count |
|---|---|
| NO_FORWARD_RUN | 120 |
| TARGETED_FORWARD_TEST | 61 |
| DEEP_FORWARD_COMPAT | 19 |
| CHEAP_FORWARD_SMOKE | 13 |
| INSUFFICIENT_CONTEXT | 3 |

Draft PRs: 87
Non-draft PRs: 129

## Top-30 non-draft PRs by priority

Priority score = weighted sum of touched compatibility-sensitive categories.
Weights: autoload=30, cpp=25, monkey_patch=25, inductor=20, eager=15, layouts=15, scheduler=15, profiler=10, distributed=10, python_runtime=5.

| # | Pri | Class | files | Categories | Title |
|---|---|---|---|---|---|
| #3404 | 90 | DEEP_FORWARD_COMPAT | 3 | autoload,cpp,distributed,inductor,python_runtime | fix(distributed): fix import torch_spyre crash from spyre::broadcast_async schem |
| #3668 | 70 | DEEP_FORWARD_COMPAT | 15 | ci,cpp,distributed,docs,inductor,layouts,tests | Compile time decomposition - WorkScheduleInfo creation + applyTensor  |
| #3873 | 65 | DEEP_FORWARD_COMPAT | 5 | inductor,layouts,monkey_patch,python_runtime,tests | feat(inductor): allow specifying STL on `torch.full` |
| #3601 | 65 | DEEP_FORWARD_COMPAT | 5 | inductor,layouts,monkey_patch,python_runtime,tests | Add ElementArrangement in eager mode type conversion |
| #3051 | 65 | DEEP_FORWARD_COMPAT | 7 | inductor,layouts,monkey_patch,python_runtime,tests | Fix AOT Autograd backward compilation |
| #3892 | 60 | DEEP_FORWARD_COMPAT | 13 | cpp,inductor,layouts,tests | Enable persistent expert loops from coarse-tile hints |
| #3809 | 60 | DEEP_FORWARD_COMPAT | 3 | cpp,inductor,layouts,tests | Reject a size-0 device dim instead of crashing with SIGFPE |
| #3182 | 60 | DEEP_FORWARD_COMPAT | 38 | cpp,docs,inductor,layouts,tests | feat(scratchpad): joint core division + LX-placement annealer |
| #3172 | 55 | DEEP_FORWARD_COMPAT | 9 | eager,inductor,layouts,python_runtime,tests | Enable Eager Mode for FP8 scaled_mm and Quantize Ops; Fix FP8 batchmatmul Separa |
| #3831 | 50 | DEEP_FORWARD_COMPAT | 5 | inductor,monkey_patch,python_runtime,tests | Spyre subgraph wrapper codegen + invoke_subgraph decomp threading |
| #3449 | 50 | DEEP_FORWARD_COMPAT | 25 | docs,inductor,profiler,pyproject,python_runtime,scheduler,tests | feat(provenance): persist and resolve kernel provenance artifacts |
| #3440 | 50 | DEEP_FORWARD_COMPAT | 9 | inductor,layouts,scheduler,tests | LX Relayouts: Add grouped LX gathers |
| #2816 | 45 | DEEP_FORWARD_COMPAT | 3 | cpp,eager,python_runtime,tests | fix: Fix `copy_` into spyre view tensors writing to wrong device offset (always  |
| #3801 | 40 | TARGETED_FORWARD_TEST | 5 | cpp,layouts,tests | Updated DCI for sliced tensors |
| #3389 | 40 | DEEP_FORWARD_COMPAT | 4 | eager,inductor,python_runtime,tests | Enable torch.cumsum via parallel prefix scan |
| #2582 | 40 | DEEP_FORWARD_COMPAT | 11 | eager,inductor,python_runtime,tests | torch.any with absmax and torch.all |
| #4000 | 35 | DEEP_FORWARD_COMPAT | 6 | docs,inductor,layouts,tests | Feature/bmm combined output reduction tiling |
| #3988 | 35 | TARGETED_FORWARD_TEST | 5 | inductor,layouts,tests | Fix layout optimizer abstraction violations for mutation ops |
| #3959 | 35 | TARGETED_FORWARD_TEST | 4 | inductor,layouts,tests | fix(pass_utils): resolve broadcast-batch/generated-dim ambiguity in matmul layou |
| #3953 | 35 | TARGETED_FORWARD_TEST | 10 | inductor,layouts,tests | fix(inductor): preserve ownership through decode SDPA |
| #3938 | 35 | TARGETED_FORWARD_TEST | 11 | inductor,layouts,tests | Add keep_by_index support |
| #3860 | 35 | TARGETED_FORWARD_TEST | 1 | cpp,profiler | Profiler/fix stream id memcpy |
| #3765 | 35 | TARGETED_FORWARD_TEST | 2 | autoload,python_runtime,tests | :bug: Remove lazy initialzation for spyre profiler which also starts runtime |
| #3590 | 35 | TARGETED_FORWARD_TEST | 1 | cpp,profiler | Add cycles_ts array metadata to kernel and memcpy trace events |
| #3587 | 35 | TARGETED_FORWARD_TEST | 10 | cpp,distributed,tests | feat(kvc): add get_composite_address accessor (M1-T1) |
| #3511 | 35 | DEEP_FORWARD_COMPAT | 11 | docs,inductor,layouts,tests | test(wsr): migrate the literal spyre_hint call sites to tile_size_per_dim |
| #3505 | 35 | TARGETED_FORWARD_TEST | 5 | inductor,layouts,tests | Refactor: Consolidate bool layout-dtype resolution into dtype_ops |
| #3356 | 35 | TARGETED_FORWARD_TEST | 8 | inductor,layouts,tests | Fix/device size tiling |
| #3070 | 35 | TARGETED_FORWARD_TEST | 9 | inductor,layouts,tests | Adding support for topk operator for all value of k and also run inputs with les |
| #2939 | 35 | DEEP_FORWARD_COMPAT | 20 | inductor,layouts,tests | inductor: add LX planner extension to enable all-to-all and all-gather on-chip |

## Negative controls (docs / tests / CI-only)

- #4001: feat: Add CRCR RH callback  (ci)
- #3958: [DO NOT MERGE] DUMMY PR TEST (ci)
- #3952: Make run_test.sh aware of SPYRE_DEVICES (tests)
- #3922: Remove tensorsoncpu tags from Gemma 4 YAML configs (tests)
- #3918: ci: retry gh api log-fetch in push-hw-diagnostics (fix HTTP 502 flake) (ci)
- #3895: fix(tests): resolve model_ops device args against the test device (tests)
- #3871: fix(tests): repair two Gemma op-test helpers that fail at the CPU reference (tests)
- #3858: fix(tests): bound torch.setitem.1 idx tensor to indexed dim size in gemma-4-26B-A4B-it op-tests (tests)
- #3843: fix(ci): stop retries from erasing earlier attempts' JUnit reports (ci)
- #3805: Fix: test_memory_pressure_gc failures (tests)
- #3667: DO NOT MERGE: shadow-validation for /next :dev runner image switch (ci)
- #3628: Enable test_large_matmul on s390x/ppc64 via fp32 CPU refs (tests)
- #3384: ci: drop leftover uv/venv from push-to-clickhouse (cleanup on top of #3383) (ci)
- #3349: [DO NOT MERGE] TREAT AS DUMMY EMPTY PR (ci)
- #3312: "Optimize extract_decompositions by parsing specific decorators" (docs)

## Classification rules

- **NO_FORWARD_RUN**: docs-only, tests-only, CI-only, tools-only, or draft. No compatibility surface.
- **CHEAP_FORWARD_SMOKE**: pyproject-only, or generic non-compat runtime — quick smoke suffices.
- **TARGETED_FORWARD_TEST**: touches one compat-sensitive surface (profiler / python_runtime / narrow inductor).
- **DEEP_FORWARD_COMPAT**: multi-surface (>=4 categories or >=15 files), or touches cpp+inductor+layouts+scheduler.
- **INSUFFICIENT_CONTEXT**: no files parsed.

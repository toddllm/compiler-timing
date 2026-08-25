# Compatibility ledger

Schema: v1 · Generated: 2026-08-25

Durable record of what upstream PyTorch changes have hit which torch-spyre surface, whether a fix landed, and where the forward-compat case lives (when one exists).

| ID | PT | Surface | Classification | Fix in? | Status |
|---|---|---|---|---|---|
| `PT-2.11-add_lambda_guard-user_stack` | 2.11.0 | torch_spyre/_monkey_patch.py:200 (_spyre_TENSOR_MATCH) | PYTHON_API_BREAK | #1930 | landed |
| `PT-2.11-profiler-breakage` | 2.11.0 | profiler infrastructure | PROFILER_CHANGE + DOWNSTREAM_DEPENDENCY_LAG | #2218 | landed in 2.12 upgrade |
| `PT-2.11-multiarch-runners` | 2.11.0 | CI infrastructure | CI_INFRASTRUCTURE_CHANGE | #1930 | landed |
| `PT-2.12-size_hint-split` | 2.12.0 | torch_spyre/_inductor/codegen/superdsc.py:602 (_concretize_f | INDUCTOR_API_BREAK + SILENT_CORRECTNESS_CHANGE | #2218 | landed |
| `PT-2.12-decomp-broadening` | 2.12.0 | torch_spyre/_inductor/lowering.py + decompositions.py | INDUCTOR_SEMANTIC_BREAK + DECOMPOSITION_CHANGE | #2218 | landed; upstream fix pending 2.12.1 GA ( |
| `PT-2.12-dynamo-to-graph-break` | 2.12.0 | torch_spyre/_monkey_patch.py (spyre_to wrapper) | INDUCTOR_API_BREAK + SILENT_CORRECTNESS_CHANGE | #2218 | landed |
| `PT-2.12-fp16-numeric-drift` | 2.12.0 | three fp16 test cases | TEST_EXPECTATION_CHANGE + SILENT_CORRECTNESS_CHANGE (reference-side) | #2218 | landed |
| `PT-2.12-vllm-lag` | 2.12.0 | downstream vLLM / spyre-inference | DOWNSTREAM_DEPENDENCY_LAG | #2218 | resolved by downstream architectural cha |
| `PT-2.13-pyobj-slot` | 2.13.0 | torch_spyre/csrc/spyre_tensor_impl.cpp:253 | CXX_ABI_BREAK | #3374 | landed; forward-compat skill produced a  |
| `PT-2.13-scheduler-loop-reorder-discard` | 2.13.0 | torch_spyre/_inductor/scheduler.py + passes.py (CustomPreFus | INDUCTOR_SEMANTIC_BREAK + SILENT_CORRECTNESS_CHANGE | #3374 | landed |
| `PT-2.13-profiler-inplace` | 2.13.0 | tests/inductor/test_inductor_ops.py + tests/configs/upstream | PROFILER_CHANGE + TEST_EXPECTATION_CHANGE | #3374 | landed |
| `PT-2.13-upstream-tests-enable` | 2.13.0 | upstream tests configuration | CI_INFRASTRUCTURE_CHANGE | #3374 | requested at merge time; presumed landed |
| `torch-spyre-F3-reverse-entrypoint` | all (2.11, 2.12, 2.13, 2.15-nightly) | torch_spyre/__init__.py (line 20 area) | REVERSE_ENTRYPOINT_HAZARD | OPEN | OPEN — reproduced on three consecutive t |
| `torch-2.15-FallbackKernel-single-tensor` | 2.15.0.dev20260824+cpu (nightly) | torch_spyre/_inductor/propagate_layouts.py:132 (_get_prop_ar | INDUCTOR_API_BREAK | OPEN | OPEN — PT 2.15 not yet released; ready f |

## Entries in detail

### `PT-2.11-add_lambda_guard-user_stack`

- **PyTorch:** 2.11.0
- **Surface:** `torch_spyre/_monkey_patch.py:200 (_spyre_TENSOR_MATCH)`
- **Classification:** PYTHON_API_BREAK
- **Failure:** torch._C._dynamo.guards.GuardManager.add_lambda_guard() now requires 3-arg (lambda, verbose_code_parts, user_stack); torch-spyre passed 2 args.
- **Fix:** Append `guard.user_stack` as third arg to `add_lambda_guard`.
- **Included in upgrade PR:** #1930
- **Dual-compatible:** False
- **Status:** landed

### `PT-2.11-profiler-breakage`

- **PyTorch:** 2.11.0
- **Surface:** `profiler infrastructure`
- **Classification:** PROFILER_CHANGE + DOWNSTREAM_DEPENDENCY_LAG
- **Failure:** Profiler broke on 2.11 due to PT 2.11 changes + parallel runtime changes.
- **Fix:** Deferred to 2.12 upgrade (new PrivateUse1 profiler API).
- **Included in upgrade PR:** #2218
- **Status:** landed in 2.12 upgrade

### `PT-2.11-multiarch-runners`

- **PyTorch:** 2.11.0
- **Surface:** `CI infrastructure`
- **Classification:** CI_INFRASTRUCTURE_CHANGE
- **Failure:** s390x / ppc64le runners not available at 2.11 merge; x86 alone gated merge after #1997 landed.
- **Included in upgrade PR:** #1930
- **Related PR:** 1997
- **Status:** landed

### `PT-2.12-size_hint-split`

- **PyTorch:** 2.12.0
- **Surface:** `torch_spyre/_inductor/codegen/superdsc.py:602 (_concretize_for_sdsc)`
- **Classification:** INDUCTOR_API_BREAK + SILENT_CORRECTNESS_CHANGE
- **Failure:** size_hint removed, split into optimization_hint (may be non-concrete) and guarding_hint_or_throw (concrete or throws). Wrong choice = silent wrong SDSC compilation.
- **Fix:** Use guarding_hint_or_throw where concretization is required.
- **Included in upgrade PR:** #2218
- **Status:** landed

### `PT-2.12-decomp-broadening`

- **PyTorch:** 2.12.0
- **Surface:** `torch_spyre/_inductor/lowering.py + decompositions.py`
- **Classification:** INDUCTOR_SEMANTIC_BREAK + DECOMPOSITION_CHANGE
- **Failure:** PT 2.12 added in-tree decomps for arange/tril/triu/isin/index_copy.out and broadened mm/bmm to decompose the K==1 case; torch-spyre's fallbacks conflict with the auto-installed decomp.
- **Fix:** register_fallback_over_decomp() helper + spyre_decompositions_to_exclude entries.
- **Included in upgrade PR:** #2218
- **Upstream follow-up:** pytorch/pytorch#185909
- **Status:** landed; upstream fix pending 2.12.1 GA (2026-06-17)

### `PT-2.12-dynamo-to-graph-break`

- **PyTorch:** 2.12.0
- **Surface:** `torch_spyre/_monkey_patch.py (spyre_to wrapper)`
- **Classification:** INDUCTOR_API_BREAK + SILENT_CORRECTNESS_CHANGE
- **Failure:** Dynamo graph-breaks when inlining spyre_to's C++ orig_to call; D2D dtype casts silently go eager and return wrong results.
- **Fix:** torch._dynamo.allow_in_graph(torch.Tensor.to) — global process-level mark.
- **Included in upgrade PR:** #2218
- **Status:** landed

### `PT-2.12-fp16-numeric-drift`

- **PyTorch:** 2.12.0
- **Surface:** `three fp16 test cases`
- **Classification:** TEST_EXPECTATION_CHANGE + SILENT_CORRECTNESS_CHANGE (reference-side)
- **Failure:** PT 2.12 changed CPU-reference fp16 numerics for exp/sin round-trips; 1-ULP drifts fail existing assertions.
- **Fix:** xfail the three edge cases via commit 3a2d482.
- **Included in upgrade PR:** #2218
- **Status:** landed

### `PT-2.12-vllm-lag`

- **PyTorch:** 2.12.0
- **Surface:** `downstream vLLM / spyre-inference`
- **Classification:** DOWNSTREAM_DEPENDENCY_LAG
- **Failure:** Upstream vLLM had NOT moved to 2.12 at merge time.
- **Fix:** spyre-inference#357 removed dep on precompiled vLLM CPU wheels.
- **Included in upgrade PR:** #2218
- **Related PR:** torch-spyre/spyre-inference#357
- **Status:** resolved by downstream architectural change

### `PT-2.13-pyobj-slot`

- **PyTorch:** 2.13.0
- **Surface:** `torch_spyre/csrc/spyre_tensor_impl.cpp:253`
- **Classification:** CXX_ABI_BREAK
- **Failure:** c10::impl::PyObjectSlot::load_pyobj_interpreter() removed; replaced with c10::impl::getGlobalPyInterpreter().
- **Fix:** One-line change to (*c10::impl::getGlobalPyInterpreter())->detach(this).
- **Forward-compat case:** `cases/historical-replay-pt213/F6-pyobj-slot-api-rename-independently-derived.md`
- **Included in upgrade PR:** #3374
- **Dual-compatible:** True
- **Status:** landed; forward-compat skill produced a byte-identical fix in independent replay.

### `PT-2.13-scheduler-loop-reorder-discard`

- **PyTorch:** 2.13.0
- **Surface:** `torch_spyre/_inductor/scheduler.py + passes.py (CustomPreFusionPasses)`
- **Classification:** INDUCTOR_SEMANTIC_BREAK + SILENT_CORRECTNESS_CHANGE
- **Failure:** PT 2.13 Scheduler._try_reorder_loops_for_candidates computes then DISCARDS a loop reorder. LX-pinned clones no longer accidentally match consumers' iter order. Two reductions sharing one LX buffer read the wrong core's slice. Silent wrong results.
- **Fix:** New align_lx_producer_loop_order pass, run BEFORE build_loop_scheduler_nodes.
- **Included in upgrade PR:** #3374
- **Notes:** 'accidental correctness' had held since forever; only surfaced when the upstream internal rewrite stopped applying.
- **Status:** landed

### `PT-2.13-profiler-inplace`

- **PyTorch:** 2.13.0
- **Surface:** `tests/inductor/test_inductor_ops.py + tests/configs/upstream_tests/test_profiler_config.yaml`
- **Classification:** PROFILER_CHANGE + TEST_EXPECTATION_CHANGE
- **Failure:** Inplace-op tests + profiler config updates for 2.13.
- **Included in upgrade PR:** #3374
- **Status:** landed

### `PT-2.13-upstream-tests-enable`

- **PyTorch:** 2.13.0
- **Surface:** `upstream tests configuration`
- **Classification:** CI_INFRASTRUCTURE_CHANGE
- **Failure:** Adding 2.13 to the upstream test suite is not automatic; explicit infrastructure work requested at merge time.
- **Included in upgrade PR:** #3374
- **Status:** requested at merge time; presumed landed post-merge

### `torch-spyre-F3-reverse-entrypoint`

- **PyTorch:** all (2.11, 2.12, 2.13, 2.15-nightly)
- **Surface:** `torch_spyre/__init__.py (line 20 area)`
- **Classification:** REVERSE_ENTRYPOINT_HAZARD
- **Failure:** torch._import_device_backends() fires while torch_spyre is partially initialized. `_autoload` name not yet bound; AttributeError → wrapped RuntimeError.
- **Fix:** Hoist a defer-and-invoke `def _autoload()` before `import torch`; tail-invoke at end of file.
- **Forward-compat case:** `cases/live-current-main-F3/, cases/second-pod-repro-2026-08-24/, cases/third-clean-run-2026-08-25/`
- **Dual-compatible:** True
- **Status:** OPEN — reproduced on three consecutive torch-spyre main SHAs; upstream needs the fix landed.

### `torch-2.15-FallbackKernel-single-tensor`

- **PyTorch:** 2.15.0.dev20260824+cpu (nightly)
- **Surface:** `torch_spyre/_inductor/propagate_layouts.py:132 (_get_prop_args)`
- **Classification:** INDUCTOR_API_BREAK
- **Failure:** PT 2.15 FallbackKernel.create for single-tensor output takes create_direct_output path — FallbackKernel now carries a FixedLayout directly, no MultiOutputLayout + trailing MultiOutput wrapper. propagate_spyre_tensor_layouts assumed the wrapping.
- **Fix:** Extend FallbackKernel branch to handle Case 1': assign op.layouts = [generic_layout(op)] when op.get_layout() is FixedLayout.
- **Forward-compat case:** `cases/f8-fallback-single-tensor/`
- **Dual-compatible:** True
- **Status:** OPEN — PT 2.15 not yet released; ready for the upgrade PR when it starts.


Stacks on #4139 (certified greedy seed for placement-only CP-SAT) but touches an orthogonal concern: module loading, not the certificate.

Refs #4117.

## Motivation

PR #4139's certified greedy seed lets `CpSatLayoutSolver.plan_layout` return the CP-SAT-optimal placement without a CP-SAT solve when greedy already reaches the forced-spill lower bound of the residency objective. On the production-shaped compile probes used to demonstrate the startup win in this PR — 8/8 real `torch.compile` invocations on the rebased branch — the seed accepts on the certified path.

The broader #4139 evidence, which set expectations for how often the fast path fires but is *not* what this PR's win rests on:
- Differential corpus: 20 greedy-certified, 8 CP-SAT-fallback (of 28 non-SKIP cases).
- Capacity-pressure sweep on captured planner-buffer sets: 39 greedy-certified, 1 CP-SAT-fallback (flash-512x8192 at 25% of shipped LX capacity — the known case where CP-SAT strictly wins).

Yet every first compile in a fresh process was still paying ~1.4 s for the SWIG bootstrap of `ortools.sat.python.cp_model`, because that module was imported eagerly at `ilp_solver_ortools` import time — before the seed had a chance to prove CP-SAT unnecessary. The reconnaissance harness (commit `a0ec30a` in `toddllm/compiler-timing`, `notes/frontend-roadmap-handoff.md` Card 1) traced the exact import chain.

This PR makes the OR-Tools import happen only when a CP-SAT solve actually needs to run. Known-fallback cases (capacity-pressure workloads that hit the 1-of-40 sweep point, or the joint `plan_layout_and_core_divisions` path) still trigger the load on demand — that cost is unchanged for them.

## Design

- Replace module-top `from ortools.sat.python import cp_model, cp_model_helper` with `cp_model = None; cp_model_helper = None` in the runtime branch. Type annotations already use `TYPE_CHECKING` + `from __future__ import annotations`, so class definitions and method signatures don't need `cp_model` alive at import time.

- New `_ortools_available()`: cheap idempotent availability probe via `importlib.util.find_spec("ortools.sat.python.cp_model")`. First call is ~10 ms; the answer is cached in `_ORTOOLS_AVAILABLE`; subsequent calls are effectively free. Robust to `ModuleNotFoundError` / `ImportError` / `ValueError` — all treated as "not available" so a broken sys.path or frozen distribution surfaces as the greedy fallback rather than a bare exception.

- New `_load_ortools()`: idempotent, thread-safe full import that populates the module globals `cp_model` and `cp_model_helper` on first call.
  - Double-checked lock (`threading.Lock`) around the critical section: two threads racing into the first uncertified compile see the same module identities and neither corrupts the other.
  - Publishes both globals in one step after a successful import; no caller observes half-initialized state.
  - Raises `ImportError` if the import itself fails. The message matches the old eager path.

- `CpSatLayoutSolver.__init__` swaps the old `if cp_model is None: raise ImportError` for `_ortools_available()`. On x86_64 with ortools installed, the ~10 ms probe runs once per process; the cached answer serves every subsequent solver instance. On s390x/ppc64le, the probe returns False and `ImportError` fires exactly as today (caught by `_make_cpsat_solver` → greedy fallback).

- `CpSatLayoutSolver._plan_layout_generic` calls `_load_ortools()` on entry. This is the single choke point every CP-SAT code path flows through: the certificate-rejection fallback from `plan_layout` and the joint entry `plan_layout_and_core_divisions` (including the `cost_expr` branch added by #3810). A source audit of all 15 non-string runtime `cp_model` / `cp_model_helper` accesses in `ilp_solver_ortools.py` confirmed every one is inside methods reachable only through `_plan_layout_generic`.

## Observable-semantics reassessment

An earlier draft of this PR claimed "user-visible behavior unchanged." That claim is too strong. Two failure modes to distinguish:

**Package absent** (typical s390x/ppc64le, or any x86_64 install missing the wheel):
`_ortools_available()` returns False. `CpSatLayoutSolver.__init__` raises `ImportError` at construction. `_make_cpsat_solver` catches it and returns the greedy allocator with the same warning message. **Behavior identical to pre-#4141.**

**Package present-but-broken** (spec resolvable, but `import ortools.sat.python.cp_model` fails at runtime — a corrupted install, missing native dependency, etc.):
- Pre-#4141: the eager module-level `from ortools.sat.python import cp_model` inside `ilp_solver_ortools` fires as part of `_make_cpsat_solver`'s lazy import of the module; its `ImportError` is caught there and translated into the greedy fallback with a warning. The broken install is invisible to the user.
- Post-#4141 on a certified compile: `_ortools_available()` returns True; `__init__` succeeds; the seed accepts; no `_load_ortools()` call; **the broken install is silently invisible on the certified path**.
- Post-#4141 on a fallback compile: `_plan_layout_generic` calls `_load_ortools()`, which raises `ImportError`. That error propagates past `scratchpad_planning`'s `except SolveError` (it is not a `SolveError`) and past `_make_cpsat_solver`'s already-completed catch, so the compile fails with a genuine import error.

Verdict: this is a **narrowing** of the pre-#4141 fallback contract for the present-but-broken case. We accept the narrowing intentionally because (a) an ortools install that resolves via `find_spec` but raises at import time is a corrupted environment problem the user should see, not paper over silently; and (b) certified compiles — the vast majority — silently succeed with an objective-equivalent result. The `_load_ortools` docstring documents this narrowing explicitly.

## Measured impact

Rebased branch on `ae9b88d` + #4139 head `2afe619`, 5 fresh-process samples per arm, trivial `torch.relu(x)` compile:

| arm | first_call_wall median (min, max) |
|---|---:|
| BASELINE | 3.04 s (2.59, 5.00) |
| LAZY | 1.93 s (1.59, 2.22) |

**-1.11 s (-36%) off first useful compile latency.**

Across the four stand-alone workloads from the frontend reconnaissance (flash 512x4096, flash 512x8192, MLP L=8, sdpa S=512), `_maybe_scratchpad_planning` falls off the top-8 pass list entirely (was 500-1200 ms; now < 60 ms), and `graphlowering.compile_to_module` drops ~600 ms consistently on every workload.

Second-call cache hit is unchanged (54 ms LAZY vs 68 ms BASELINE, within noise).

## Tests

`tests/inductor/test_cpsat_lazy_ortools_load.py` — 15 tests wired into GHA CI:

1. Importing `ilp_solver_ortools` does not import `cp_model`.
2. Constructing `CpSatLayoutSolver` does not import `cp_model`.
3. Certified greedy `plan_layout` does not import `cp_model`.
4. Fallback `plan_layout` (classic 10/20/30 with capacity 50) lazily imports `cp_model` and returns the CP-SAT optimum (objective 20).
5. Joint `plan_layout_and_core_divisions` (default residency-lex-solve path) lazily imports `cp_model`.
6. Joint `plan_layout_and_core_divisions(cost_expr=…)` behavioral test: pass a small nonconstant sympy expression (`-sum(sym_is_lx for b in bufs)`); assert `cp_model` unloaded before the call, loaded after, and the plan respects the `cost_expr`'s residency preference.
7. Repeated CP-SAT solves load exactly once (module identity preserved across two solves; second-solve wall < 1 s where a re-import would add ~1.4 s).
8. `_ortools_available()` matches `find_spec`.
9. `_ortools_available()` is cached (patching `find_spec` to raise).
10. `_ortools_available()` returns False when `find_spec` returns None.
11. `_ortools_available()` returns False when `find_spec` raises `ModuleNotFoundError`.
12. `_ortools_available()` returns False when `find_spec` raises `ValueError` (frozen-dist edge).
13. `_load_ortools()` is idempotent (module identity preserved on repeat calls).
14. `_load_ortools()` publishes both globals in one step (no half-initialized state observable).
15. Concurrent first-load: two threads racing into `_load_ortools` under a barrier both succeed and see identical module identities.

Subprocess isolation for the `sys.modules`-membership assertions so pytest's own imports do not pollute the state under test.

All 15 lazy-load tests pass on the rebased branch. The existing 18 certified-greedy-seed tests, 250 scratchpad-solver tests, and 35 scratchpad-patterns tests remain green (11 unrelated expected failures).

## Not touched (reserved for follow-on owners)

- `optimize_restickify_locations` / restickify pipeline (Will's lane).
- SDSC per-spec / bundle-generation optimization.
- Shared cross-pass analysis context.
- Scheduler init/codegen or wrapper generation.
- Spyre device / runtime initialization.
- Broad `torch`/`torch_spyre` import restructuring.

The frontend roadmap for these lives at `toddllm/compiler-timing` `analyses/2026-08-pr4117-pre-dxp/notes/frontend-roadmap-handoff.md`.

Signed-off-by: Todd Deshane <todd.deshane@ibm.com>

# F8 — FallbackKernel single-tensor direct-output missing `.layouts`

## Classification

`INDUCTOR_API_BREAK`. Upstream torch changed the shape of the object
`FallbackKernel.create` produces for a single-tensor output between
torch 2.13 and torch 2.15 nightly. torch-spyre's
`propagate_spyre_tensor_layouts` pass assumed the old shape and now
raises when the new shape reaches downstream inductor ops.

## Substrate (2026-08-24 fresh pod)

- Pod: `tdeshane-fwdcompat-2026-08-24`, namespace `a5-deepview`.
- Base image digest:
  `sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`
  (torch-aiu-runtime-dev at 2026-08-21 push; unchanged since).
- torch-spyre HEAD: `e7bb29dc1a0730829e9ed891b3bcd30b69887ec5`.
  Same tree carried F3 patch (defer-and-invoke-at-end for _autoload).
- forward torch: `2.15.0.dev20260824+cpu`,
  git `c0577575187a039c482a985e9a594816dc711a4c`.
- supported torch: `2.13.0+cpu`.

## Observation (FORWARD_BEFORE_FIX)

Stage 0 of `run_compat_smoke.sh` under the forward venv fails:

    torch._inductor.exc.InductorError: RuntimeError:
        FallbackKernel(python_kernel_name='torch.ops.spyre.to_dtype_cpu.default',
                       name=buf0,
                       layout=FixedLayout('spyre:0', torch.float32, size=[8], stride=[1]),
                       ...)
        does not have FixedTiledLayout

Full traceback at `data/forward-before-f8-stage_0.log:32-95`. The
raise site is
`torch_spyre/_inductor/propagate_layouts.py:132` (inside
`_get_prop_args`, which is called during
`propagate_spyre_tensor_layouts` at line 1991).

Under the supported venv (torch 2.13.0+cpu, same source tree, no F8
patch), the same smoke passes: all four stages green
(`data/supported-pre-f8-summary.json`). The
"aten.arange.default is falling back to cpu" FallbackWarning fires
on 2.13 too, so the fallback path is exercised in both worlds — the
2.15 delta is where its layout is represented, not whether it exists.

## Diagnosis

Upstream inductor's `FallbackKernel.create` in torch >=2.15 takes a
`create_direct_output` code path for the `isinstance(example_output,
torch.Tensor)` case. That path builds a `FallbackKernel` whose own
`.layout` is a real `FixedLayout` — no MultiOutputLayout wrapper, no
trailing MultiOutput. Confirmed by reading `FallbackKernel.create` on
the pod (source captured via `inspect.getsource` under the forward
venv).

torch-spyre's `propagate_spyre_tensor_layouts` iterates operations
and dispatches on their type. Its FallbackKernel branch documented
three cases:

    #   Case 1 (single tensor)  -> MultiOutputLayout + 1 MultiOutput
    #   Case 2 (tuple of N)     -> MultiOutputLayout + N MultiOutputs
    #   Case 3 (void/in-place)  -> NoneLayout        + 0 MultiOutputs

and did `pass` — relying on the trailing MultiOutput to be the entity
that gets `.layouts` assigned (that MultiOutput's branch, a few lines
down, does `op.layouts = [generic_layout(op)]`).

Under torch 2.15's single-tensor path, no MultiOutput follows. The
FallbackKernel itself becomes a read that shows up in downstream
ops' `rw.reads`. When `_get_prop_args` inspects that buffer, it
finds:

- Not a `SpyreConstantFallback` (so the early-continue path doesn't
  trigger).
- No `.layouts` attribute (nothing assigned it — Case 1' is unhandled).
- `buf.get_layout()` returns a `FixedLayout` (not a `FixedTiledLayout`).

So the assertion `raise RuntimeError(f"{buf} does not have
FixedTiledLayout")` fires.

## Minimum patch

`patches/F8-forward-patch.diff`. Two hunks, 24 net lines added:

1. Import `MultiOutputLayout` and `NoneLayout` from
   `torch._inductor.ir` (they're already imported next to the
   `FallbackKernel` import).
2. Extend the FallbackKernel branch to detect the new single-tensor
   direct-output case and assign `op.layouts = [generic_layout(op)]`
   — the same treatment MultiOutput gets under 2.13.

```python
elif isinstance(op, FallbackKernel):
    # ...comment updated to name Case 1'...
    fk_layout = op.get_layout() if not isinstance(
        op.layout, (MultiOutputLayout, NoneLayout)
    ) else None
    if isinstance(fk_layout, FixedLayout):
        op.layouts = [generic_layout(op)]
        op.restick_cost_fn = AnyInNode.from_args()
```

**Why the type check is right, not a broad "if not MultiOutputLayout":**
`op.layout` is inspected directly (not via `op.get_layout()`) because
`get_layout()` on a `MultiOutputLayout`/`NoneLayout` raises rather
than returns the sentinel — matching the pre-existing comment
("MultiOutputLayout / NoneLayout both raise from get_layout()"). The
explicit isinstance check preserves that invariant.

**Why this is semantics-preserving under 2.13:**
On 2.13, single-tensor FallbackKernels always carry a `MultiOutputLayout`
(they take the trailing-MultiOutput path). The new isinstance check
therefore evaluates to False, `fk_layout` becomes None, the
`isinstance(fk_layout, FixedLayout)` guard is False, and the branch
takes no action — identical to the pre-patch `pass`.

## Verification

### FORWARD_BEFORE_FIX → FORWARD_AFTER_FIX

Same smoke, same tree, same venv (`/home/tdeshane/forward/.venv-latest`,
torch 2.15.0.dev20260824+cpu) — only the patch changed:

| Stage | Before F8 | After F8 |
|---|---|---|
| 0 env smoke | FAIL @ propagate_layouts.py:132 | PASS 43s |
| 1 imports  | (not reached) | PASS 12s |
| 2 add compile+match | (not reached) | PASS 18s |
| 3 hand-picked tests | (not reached) | PASS 370s (6/6) |

Full FORWARD_AFTER_FIX summary in `data/forward-after-f8-summary.json`:
`{"verdict": "PASS", "last_stage_run": 3, "failed_stage": -1, ...}`.
Stage-3 log excerpt at `data/forward-after-f8-stage_3.log` includes
per-test STAGE3_OK markers for all six test files.

### SUPPORTED retest (DUAL_COMPAT proof)

Ran with F8 applied to the supported tree
(`/home/tdeshane/supported/torch-spyre`, same SHA e7bb29d, F3 already
applied), against torch 2.13.0+cpu:

    {
      "verdict": "PASS",
      "last_stage_run": 3,
      "failed_stage": -1,
      "stage_through_requested": 3,
      "venv": "/home/tdeshane/supported/.venv-supported",
      "timestamp_utc": "2026-08-25T03:22:00Z"
    }

All four stages green (see
`data/supported-after-f8-summary.json`). Pre-F8 verdict for
reference: `data/supported-pre-f8-summary.json` — also PASS all four.
Same tree, same venv, only difference = F8 patch.

**F8 verdict: DUAL_COMPAT.** Same patch preserves 2.13 behavior and
fixes the 2.15 break. This is the strongest verdict the skill can
produce for a torch-spyre-side patch without running the full
seven-row verification matrix (which would require the row-4
"latest-only" venv this session doesn't build separately from the
forward venv).

## Skill-workflow validation footprint

This case is the first "real" forward-side finding the skill produced
from a genuinely fresh pod using SKILL.md's own scripts:

- `setup_supported_env.sh` — green.
- F3 patch (already applied on the source tree in earlier session) —
  still required for `import torch_spyre` under torch 2.13, still
  required under 2.15.
- `run_compat_smoke.sh` on supported — green (baseline).
- `setup_latest_pytorch_env.sh` — green after F7 fix in this session.
- `run_compat_smoke.sh` on forward, no F8 — RED at Stage 0 (this
  observation).
- Diagnose via reading `FallbackKernel.create` source on-pod — no
  guessing at deltas, only reading actual code.
- Patch drafted with the explicit isomorphism to the 2.13 code path.
- `run_compat_smoke.sh` on forward, with F8 — GREEN.
- `run_compat_smoke.sh` on supported, with F8 — GREEN (DUAL_COMPAT).

That whole loop, from RED to DUAL_COMPAT, is the workflow the skill
exists to make routine.

## Also fixed in this session (F9)

`run_compat_smoke.sh` Stage 3 test-tree locator did not honor
`$TORCH_SPYRE_TREE` — it walked up from the venv, which under the
fresh pod's layout found `/home/tdeshane/torch-spyre` (a stale
checkout from prior work) BEFORE it would find
`/home/tdeshane/forward-tree/torch-spyre` (the tree we built the
forward venv against). Under the F9 fix, the env var wins; the
walk-up remains as a fallback for the supported-side layout.

## Follow-ups

- Land F8 as a PR against torch-spyre. The patch is byte-authored
  in this session; the exact torch commit that introduced
  `create_direct_output` should be looked up to fill the `#<TBD>`
  reference in the comment before submitting.
- Task #46 (byte-exact second-pod repro) still open.
- The Stage-3 test list in `run_compat_smoke.sh` is hand-picked from
  fast tests; a more thorough sweep on the forward venv is a natural
  next step now that Stage 0-3 land green.

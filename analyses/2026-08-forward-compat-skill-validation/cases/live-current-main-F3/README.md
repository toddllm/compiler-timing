# F3 live-remediation case — current torch-spyre main

**Recorded 2026-08-21/22.** This is the primary current-main
remediation case Todd asked for in his post-F6 review: apply the F3
re-entrancy fix to current torch-spyre main, not to a3128985.

## Live SHAs at experiment start

- torch-spyre HEAD (`origin/main` at fetch time):
  `8aba5bcad158ce67434c8b15f6e43e9bb75556a2`
  (message: "Support int32<->fp32 conversion (#3876)")
- pytorch HEAD (`origin/main` at fetch time):
  `392fb70e54bd3325f743652e54eb8768275dd740`
- torch-spyre pyproject-declared torch pin: `torch~=2.13.0`
- torch actually installed for this case: `2.13.0+cpu` from
  `https://download.pytorch.org/whl/cpu` (the declared version)
- Pod: `tdeshane-compiler-timing-dev-v2`
- Image digest:
  `sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`
- Compiler: GCC 14.3.1 20251022; `CXX=c++` (F5 lesson — no
  `"ccache c++"`)

## Pre-fix state — F3 reproduces on current main

Import matrix run on torch-spyre@8aba5bc + torch 2.13.0+cpu, no
patches applied:

| # | Imports | Autoload | Result |
|---|---|---|---|
| A | `import torch` | ON | PASS |
| B | `import torch; import torch._inductor` | ON | PASS |
| **C** | `import torch_spyre` (no `torch` first) | **ON** | **FAIL** — `AttributeError: partially initialized module 'torch_spyre' has no attribute '_autoload' (most likely due to a circular import)` |
| D | `import torch_spyre` (no `torch` first) | OFF | PASS |
| E | `import torch; import torch_spyre` | ON | PASS |
| **F** | `import torch_spyre; import torch_spyre._inductor.lowering` | ON | **FAIL** — same signature |
| H | full canonical order (torch → inductor → torch_spyre → lowering) | ON | PASS |

Matches the same signature previously observed on torch-spyre@a3128985
in the primary case (`cases/current-main/failures/F3-.../02-import-matrix.md`).
**F3 remains live in current torch-spyre main.**

## The fix

Applied via `patches/F3-live-patch.diff`. One-file change to
`torch_spyre/__init__.py`. Two hunks:

1. Insert new `_autoload()` definition at top of module, before the
   top-level `import torch` on line 20. The early stub uses
   `globals().get("_autoload_impl")` to defer: if `_autoload_impl` is
   not yet bound (because our `__init__.py` is still executing), it
   sets `_autoload._requested = True` and returns. Otherwise it calls
   `_autoload_impl()`.
2. Delete the original `_autoload()` definition ~230 lines down.
3. Append a tail-of-file guard:
   ```python
   if getattr(_autoload, "_requested", False):
       _autoload()
   ```
   which runs after `_autoload_impl` is defined and only if torch
   actually asked for autoload during our import.

## Why this design

- torch's `_import_device_backends()` fires during our own
  `import torch` (line 20 of `__init__.py`). At that moment, the
  rest of `__init__.py` hasn't executed. `_autoload_impl` is not yet
  bound to module globals.
- Naive H1 (just move `def _autoload` to the top) fails at runtime
  with `NameError: name '_autoload_impl' is not defined` when torch
  tries to invoke autoload during that early call.
- The defer-and-invoke-at-end pattern is the minimum change that
  satisfies both callers:
  - torch's early call gets a no-op that succeeds without raising;
  - the tail of our own module invokes autoload after everything is
    bound.
- `_autoload._ran` / `_autoload._requested` flags make the pattern
  idempotent: multiple calls, in any order, produce the same effect.

## Post-fix verification

Full import matrix retested on torch-spyre@8aba5bc + F3 patch +
torch 2.13.0+cpu:

| # | Result |
|---|---|
| A | PASS |
| B | PASS |
| **C** | **PASS** (was FAIL pre-fix) |
| D | PASS |
| E | PASS |
| **F** | **PASS** (was FAIL pre-fix) |
| H | PASS |

Stage 0 device enum + Stage 2 real Spyre compile:

```
torch = 2.13.0+cpu
spyre.device_count = 1
pointwise delta = 0.015625      (fp16 noise)
reduction delta = 0.023438      (fp16 noise)
amin+amax pair min_delta = 0.001953
amin+amax pair max_delta = 0.001953
```

All within fp16 tolerance. Real `torch.compile(backend="inductor")`
against Spyre-device tensors, CPU oracle comparison, correct output.

## Failure taxonomy classification

**`REVERSE_ENTRYPOINT_HAZARD`** — the category proposed in F3's
`02-import-matrix.md` and codified in
`.claude/skills/torch-spyre-forward-compat/references/failure-taxonomy.md`.
This case validates the taxonomy: the diagnostic (5-case import matrix)
correctly identified F3, and the response (fix in torch-spyre's
`__init__.py`, defer-and-invoke pattern) resolved it.

## What this validates about the skill

1. **Live bug fix, not historical replay.** F3 was diagnosed and
   remediated on the current torch-spyre `main` (SHA 8aba5bc, one day
   old at the time of this run). This is the strongest possible
   demonstration of the skill's diagnose-fix-verify loop.
2. **The hypothesis-first record proved useful.** The remediation
   plan (`03-remediation-plan.md` in the historical case) predicted
   H1: define `_autoload` at the top of the module. That naive form
   failed at runtime (NameError). The correct fix required the defer
   pattern — which the plan's H2 anticipated ("fallback shim").
   Landing this refinement without the hypothesis-first discipline
   would have been much slower.
3. **Rule zero held.** F3's fix touches only `torch_spyre/__init__.py`
   in a minimum-diff form (one function moved, defer flag added,
   tail-call guard). No unrelated cleanup, no reformats.

## Files

- `patches/F3-live-patch.diff` — the actual diff applied.
- `data/pre-fix-import-matrix.log` — full traceback of the FAIL cases.
- `data/post-fix-import-matrix.log` — the 7/7 PASS log.
- `data/stage2-verification.log` — Stage 0 + Stage 2 verification
  with Spyre device.

## Next steps (v0.2 backlog additions)

- Upstream this fix to torch-spyre as a PR. This is a real
  torch-spyre-side bug fix that would benefit any user importing
  torch_spyre before torch.
- Consider whether `_autoload_impl` itself should also have a
  defer-guard so torch can call `_autoload()` more than once safely.
- Test on torch nightly (main HEAD SHA 392fb70e) to confirm the
  same fix works forward.

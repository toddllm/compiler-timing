# Fresh-pod endtoend run — 2026-08-24 restart

Restart of the fresh-pod verification after a two-day gap. First-
principles cluster login, provisioned a genuinely fresh pod, confirmed
every substrate assumption the skill scripts make.

## Pod

- Name: tdeshane-fwdcompat-2026-08-24
- Namespace: a5-deepview
- Node: p1-worker-47 (scheduler chose over preferred p1-worker-23; the
  --digest byte-exact pin ensured layer-cache hit even on a different
  node, so pull time was ~30 seconds)
- Image digest: sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6
  (identical to the digest recorded on 2026-08-21 and 2026-08-22 —
  torch-aiu-runtime-dev:latest has not been re-pushed in the interval)
- Provisioning: bash create_fresh_pod.sh --name POD --digest
  tdeshane-compiler-timing-dev-v2 --prefer-node p1-worker-23. Script
  ran clean end-to-end.

## Substrate check (first-principles)

- User: tdeshane, uid 1000810000, home /home/tdeshane (PVC mount OK).
- GCC 14.3.1, ccache-wrapped c++ on PATH at /usr/lib64/ccache/c++.
- Python 3.12.13.
- All five SPYRE_* env vars (SPYRE_COMMS_INSTALL_DIR,
  RUNTIME_INSTALL_DIR, DEEPTOOLS_INSTALL_DIR, SENLIB_INSTALL_DIR,
  SENTINYEXEC_INSTALL_DIR) present under `bash -l` — so setup scripts
  that source /etc/profile.d/ibm-aiu-setup.sh get them.
- PVC contamination confirmed live:
  /home/tdeshane/.local/lib/python3.12/site-packages/__editable__.torch_spyre-0.0.1.pth
  dated Jun 20. F4 hazard still applies; PYTHONNOUSERSITE=1 +
  TORCH_DEVICE_BACKEND_AUTOLOAD=0 guards in the fixed scripts handle it.

## SHAs resolved via resolve_versions.sh

- torch-spyre HEAD: e7bb29dc1a0730829e9ed891b3bcd30b69887ec5
  (moved ~30 commits since Aug 22's 8aba5bcad158...)
- pytorch HEAD: fffac8868260473ca9a496b802835ec5cbda2692
  (moved ~1000 commits since Aug 22's e8eff463c3e0...)
- Declared torch pin: torch~=2.13.0 (unchanged)

## Ready to continue

Pod is in a byte-known state matching every assumption the fixed
scripts make. Next moves per Todd's operational NO-GO gate:

1. Run setup_supported_env.sh — expect green build on
   torch-spyre@e7bb29d + torch 2.13.0+cpu given the 13 defect fixes
   from 2026-08-22 are all in.
2. Apply F3 patch. Interesting: does F3 still reproduce on
   e7bb29d? Three SHAs' worth of consecutive-live evidence would
   strengthen it further.
3. Full 4-stage smoke against supported venv.
4. setup_latest_pytorch_env.sh — hits the still-open SETUP_RC=2
   downstream defect. That's the primary v0.3 debug target.
5. Once forward builds, run smoke against it; verify F3 patch is
   still a DUAL_COMPAT_FIX now with two more commits of drift.
6. Second-pod byte-exact reproduction (Todd's §46).

## Results (through 2026-08-24 19:26Z, in order)

### SUPPORTED_CONTROL — PASS

- venv: `/home/tdeshane/supported/.venv-supported`
- torch: 2.13.0+cpu
- torch-spyre: e7bb29d + F3 patch (defer-and-invoke-at-end pattern)
- run_compat_smoke stages 0–3: all PASS. Verdict PASS.
- Same source tree used for the forward-side run below (F3 patch applied
  once, reused across venvs — this is what makes the two runs a fair
  A/B on nothing-but-torch-version).

### F7 — pipefail-safe gcc-toolset glob (fixed in this session)

`setup_latest_pytorch_env.sh` was exiting SETUP_RC=2 with no explanation
after nightly torch install. Root cause: under `set -euo pipefail`,
inside `install_torch_spyre_editable()`,

    tsxx="$(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ 2>/dev/null | tail -1)"

fails on pod images without gcc-toolset — `ls` exits 2, pipefail makes
the pipeline exit 2, `set -e` kills the function. `setup_supported_env.sh`
has the same textual line at top level but uses `set -uo pipefail`
(no `-e`), which is why the same defect never surfaced on the supported
path. Fix: wrap the ls in `{ …; || true; }` before the pipe. Verified
byte-exact reproducer on-pod:

    $ oc exec "$POD" -- bash -c '
        set -euo pipefail
        myfn() {
          local tsxx
          tsxx="$(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ 2>/dev/null | tail -1)"
          echo "got past"
        }
        myfn; echo OK
      '
    (exits 2, prints nothing)

Fixed variant:

    tsxx="$( { ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ 2>/dev/null || true; } | tail -1)"

Commit: `forward-compat skill: F7 fix — pipefail-safe gcc-toolset glob in setup_latest`.

### FORWARD substrate — PASS

- venv: `/home/tdeshane/forward/.venv-latest`
- torch: 2.15.0.dev20260824+cpu (git c0577575187a039c482a985e9a594816dc711a4c)
- torch-spyre: e7bb29d (same tree, same F3 patch) built successfully
  as editable against nightly torch. `_C.so` linked, `pip show torch_spyre`
  reports 0.0.1.
- `pytorch_selection.json` recorded (NIGHTLY_PROXY mode, fallback_reason
  null, actual_sha matches).

### FORWARD_BEFORE_FIX — Stage 0 FAIL — INDUCTOR_API_BREAK candidate

Same smoke script, same source tree, same F3 patch, different torch:

    File "torch_spyre/_inductor/propagate_layouts.py", line 132, in _get_prop_args
        raise RuntimeError(f"{buf} does not have FixedTiledLayout")
    torch._inductor.exc.InductorError: RuntimeError:
        FallbackKernel(python_kernel_name='torch.ops.spyre.to_dtype_cpu.default',
                       name=buf0,
                       layout=FixedLayout('spyre:0', torch.float32, size=[8], stride=[1]),
                       ...)
        does not have FixedTiledLayout

Precondition: `aten.arange.default` falls back to CPU (this happens on
2.13 too — same FallbackWarning appears in supported/stage_0.log, but
there the pass never rejects it). The forward run raises because
`_get_prop_args` iterates buffer reads and, when the buffer isn't a
`SpyreConstantFallback` and doesn't expose a `layouts` attribute,
demands a `FixedTiledLayout` — which a FallbackKernel's `FixedLayout`
is not.

Delta: between torch 2.13.0 and 2.15.0.dev20260824, upstream inductor
changed how `to_dtype_cpu` fallbacks are represented in the read set
seen by pre-scheduling passes (or the same buffer is being surfaced to
`_get_prop_args` where 2.13 hid it). Either way, torch-spyre's
propagate_layouts pass is the entity that raises — the fix belongs in
torch-spyre, not upstream.

**Not patched in this session.** Root-causing the exact behavior
change in torch (does FallbackKernel newly appear in these `rw.reads`?
does the FixedLayout it carries differ?) is prerequisite to writing a
minimum patch — this is exactly the kind of "characterize before you
patch" moment the skill exists to model. Recorded here as the first
genuine live forward-side finding produced by the skill from a fresh
pod.

### Skill validation status after this run

- Ladder-0: green on supported (fresh substrate → build → import).
- Ladder-1: green on supported (import matrix, F3 exercised).
- Ladder-2: green on supported (trivial add compiles + matches CPU).
- Ladder-3: green on supported (all 6 hand-picked inductor tests pass).
- Ladder-0 on forward: FAIL — first real INDUCTOR_API_BREAK candidate.
  Skill workflow reached the intended verdict state.
- setup_latest fix (F7): now working end-to-end on this image family;
  eliminates the last known "silent SETUP_RC" failure mode.

Outstanding for the skill:
- Task #46: second-pod byte-exact reproduction from SKILL.md alone.
- Task #50: patch investigation + verify_patch for the FallbackKernel
  layout issue above.


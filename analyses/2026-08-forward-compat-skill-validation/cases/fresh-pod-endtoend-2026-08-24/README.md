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

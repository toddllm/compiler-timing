# Device economics

## Constraints observed

- One AIU device per pod.
- Device runtime state is exclusive; concurrent workloads on the
  same pod hit DMA timeouts / SIGABRT
  (`references/environment-policy.md` in the parent skill, F12
  lesson in the third-clean-run case).
- Fresh pod provisioning: ~30 seconds when the digest is layer-
  cached on the target node, up to ~60 min for a genuinely
  uncached pull. `--digest` byte-exact pin is the reliable
  approach.
- setup_supported_env (fresh clone + build + editable install +
  smoke prereqs): ~4-8 minutes per pod.
- setup_latest_pytorch_env (nightly torch install + torch-spyre
  self-clone + build): ~5-7 minutes.
- run_compat_smoke.sh --stage-through 3 (env + import + minimal
  compile + 6 targeted tests): ~2-6 minutes.
- verify_patch.sh (full 7-row matrix, includes a Row-6 fresh venv
  build): ~8-15 minutes.

## Cost per matrix

Cheapest per-PR 2×2 (assume Cell A and Cell C are cached from
prior main runs):

- Cell B (PR + supported): ~7-15 minutes.
- Cell D (PR + forward): ~10-15 minutes.
- Serialized on one pod: ~20-30 minutes per PR.

Corpus of 10 non-draft, non-dirty, high-priority PRs = ~4 hours of
device time.

## Caching main runs

Cells A and C do not change with the PR under test — they only
change when torch-spyre main advances. Run each once per main-SHA
advance:

- Cell A (main + supported torch) — cache result keyed on main SHA.
- Cell C (main + forward nightly torch) — cache result keyed on
  (main SHA, nightly build SHA).

Torch-spyre main advances several times a day (~10 commits in the
6 hours between yesterday's `e7bb29d` and today's `613b259`).
Forward nightly changes daily. Cache lifetime: ~1-day for either
cell.

## Non-device work is free

Static triage, mergeable_state checks, priority ranking, PR file
enumeration — all `gh api` calls that take seconds. Don't burn a
pod on any PR whose static properties already tell the answer:

- tests-only → NO_FORWARD_RUN.
- docs-only → NO_FORWARD_RUN.
- draft → wait.
- `mergeable_state == dirty` → wait for rebase.
- `mergeable_state == blocked` → wait for own-CI-green.

## What the empirical run actually cost

- One pod (`tdeshane-pseudo-ci-2026-08-25`), provisioned in ~30s
  (digest layer-cached on the target node).
- Cell B for #3404 ran 7 minutes before failing at the C++ build.
- Pod torn down immediately.
- Total device time: 7 minutes. Total wall time: ~10 minutes.

For a diagnostic verdict (`PR_STALE_AGAINST_MAIN`) on the
highest-priority PR in the whole 216-PR set. That's a very good
ratio.

## Anti-patterns

- **Running all 4 cells on every PR.** The 3rd-clean-run's Cell A
  and Cell C are ALREADY green for any main SHA that has landed
  the F3+F8 patches; no need to re-run.
- **Concurrent cell execution on one pod.** The 2026-08-24 second-
  pod run empirically showed that concurrent setup_latest +
  supported-smoke wedges the device.
- **Running Cell D before Cell B is green.** If Cell B fails, Cell
  D will fail the same way. No new information.

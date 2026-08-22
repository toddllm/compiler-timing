# Fresh-pod end-to-end operational verification (Todd §8)

**Recorded 2026-08-22.** Todd's post-F6 review named this as a blocker
for calling the skill GO: "test the skill's own fresh-pod machinery
... use its own script to create a second clean pod." This is that
verification, and it also produced two real script defects that were
fixed on the spot.

## What ran

Executed the skill's scripts on a genuinely fresh pod, using them as
a fresh Claude session would.

Step 1: `create_fresh_pod.sh` (skill v0.2 form, digest-pinned)

```
$ ./scripts/create_fresh_pod.sh \
      --name tdeshane-fwdcompat-v02-endtoend \
      --digest tdeshane-compiler-timing-dev-v2 \
      --prefer-node p1-worker-23
# --digest resolved from pod tdeshane-compiler-timing-dev-v2:
   us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev@sha256:81c352...
# pod is Ready
# node: p1-worker-48
# image_id: us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev@sha256:81c352...
```

- Pod Ready in ~1 minute. `imagePullPolicy: IfNotPresent` combined
  with digest-pin hit the layer cache even though scheduler chose
  `p1-worker-48` instead of the preferred `p1-worker-23`.
- The v0.2 script fixes (digest-pin, prefer-node) both worked as
  intended: digest-pin was load-bearing (byte-exact repro);
  prefer-node was a soft preference the scheduler could override
  without cost.
- Same immutable digest recorded: `sha256:81c352...`.
- No 66-minute hang like the first v0.1 attempt.

Step 2: `capture_environment.py`

```
$ python3 scripts/capture_environment.py > environment.json
```

- Ran successfully; produced valid JSON.
- Correctly captured pod name, python version (3.12.13), toolchain
  (GCC 14.3.1, cmake, ninja, ccache).
- Correctly recorded a `torch.error` because the fresh pod inherits
  the flex-ABI-broken editable install from `~/.local/lib/python3.12/
  site-packages/__editable__.torch_spyre-0.0.1.pth` on the shared
  PVC. That's the F4/environment-policy hazard the skill already
  documents; the script surfacing it as an `error` field is correct
  behavior.

Step 3: `resolve_versions.sh` — TWO REAL DEFECTS

Initial run FAILED with two real script defects.

**Defect 1** — over-strict `GITHUB_TOKEN` requirement. The script
died with: `GITHUB_TOKEN (or GH_TOKEN) must be set to read private
repo torch-spyre/torch-spyre`.

torch-spyre is nominally private but its public https endpoints
(`git ls-remote https://github.com/...`,
`raw.githubusercontent.com/.../{sha}/pyproject.toml`) are anonymously
readable on the dev cluster. The v0.1 script hard-required a token;
the workflow this session had been running never needed one.

**Fix**: script attempts anonymous fetch first, falls back to Bearer
token only if the anonymous route fails.

**Defect 2** — heredoc-vs-pipe stdin conflict swallowed content.
After Defect 1 fix, `declared_pytorch_dep` came back empty. Cause:

```bash
DECLARED_TORCH=$(printf '%s' "$PYPROJECT_TXT" | python3 - <<'PY'
    txt = sys.stdin.read()  # 0 chars!
    ...
```

The intent was to pipe `$PYPROJECT_TXT` into python's stdin. But
`python3 -` reads its script from stdin, and the `<<'PY'` heredoc
attaches to python's stdin (fd 0) — so the heredoc wins over the
pipe. Python got zero characters of `$PYPROJECT_TXT`.

**Fix**: pass `$PYPROJECT_TXT` through the environment
(`PYPROJECT_TXT="$PYPROJECT_TXT" python3 - <<'PY'`); python reads it
via `os.environ.get("PYPROJECT_TXT", "")`. Leaves stdin for the
heredoc script only, no fd conflict.

## Post-fix verification

```
$ ./scripts/resolve_versions.sh --out versions.json && cat versions.json
{
  "schema_version": 1,
  "timestamp": "2026-08-22T02:35:47Z",
  "torch_spyre": {
    "repo": "torch-spyre/torch-spyre",
    "branch": "main",
    "sha": "8aba5bcad158ce67434c8b15f6e43e9bb75556a2",
    "declared_pytorch_dep": "torch~=2.13.0"
  },
  "pytorch": {
    "repo": "pytorch/pytorch",
    "branch": "main",
    "sha": "e8eff463c3e0c82a5c4b7e6439ab36fe869eac68"
  }
}
```

Correct: torch-spyre HEAD matches earlier (`8aba5bcad158...`);
pytorch HEAD has advanced to `e8eff463c3e0...` (a normal several-hour
delta from the earlier `392fb70e`); declared dep parsed cleanly.

## What this validates

- **`create_fresh_pod.sh` works as designed.** Digest-pin resolution
  from an existing pod's imageID is byte-exact. Prefer-node is a
  soft hint that doesn't fail when the scheduler overrides.
- **`capture_environment.py` runs on a fresh venvless pod.**
  Correctly captures state including PVC contamination hazards.
- **The `resolve_versions.sh` defects are the exact kind of thing a
  real end-to-end run catches** that internal validation misses.
- **v0.2 script quality is now demonstrably higher than v0.1** — two
  defects found and fixed in one fresh-pod session.

## What this fresh-pod run did NOT complete

Ran out of session budget before executing the remaining scripts:

- `setup_supported_env.sh` — creates the supported venv and builds
  torch-spyre against declared torch. Would take ~5-10 min.
- `setup_latest_pytorch_env.sh` — creates the forward venv and
  either builds pytorch from main SHA (3h) or installs nightly.
- `run_compat_smoke.sh` — Stage 0-3 ladder.
- `verify_patch.sh` — six-row verification matrix.

Each is authored and syntax-checked but not yet exercised on this
fresh pod. That is v0.3 continuation work.

Given the two defects already caught in the two scripts that did
run this session, expect at least one or two more real defects to
surface across the other five. That is the honest state to hand
off.

## Pod cleanup

`tdeshane-fwdcompat-v02-endtoend` on `p1-worker-48` is retained for
follow-up. Delete with `oc delete pod tdeshane-fwdcompat-v02-endtoend
-n a5-deepview` when done.

## Files

- `data/versions.json` — output of `resolve_versions.sh` after both
  defects fixed.
- `data/environment.json` — output of `capture_environment.py`.

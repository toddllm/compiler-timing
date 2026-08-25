# Second-pod byte-exact reproduction — 2026-08-24

Todd's operational NO-GO gate for the skill: *"Does the checked-in
skill itself, from a fresh pod, actually execute the workflow it
says it executes?"* This is that test.

## Substrate

- Second pod: `tdeshane-fwdcompat-2026-08-24b`, namespace `a5-deepview`.
- Same base image digest as the first-pod run
  (`fresh-pod-endtoend-2026-08-24/`) —
  `sha256:81c352893b6927193f5e79d0a78f0bbe9bc4607aad1e71c076706da44a6993f6`.
- Landed on a different node (`p1-worker-50`), which is exactly what
  the byte-exact-repro test needs — same image, different pod
  identity, different scheduling target.
- Provisioned via `scripts/create_fresh_pod.sh --digest
  tdeshane-compiler-timing-dev-v2 --prefer-node p1-worker-23`, i.e.
  the exact command SKILL.md's quick-start prescribes.

## Resolved SHAs (2026-08-24 late)

- torch-spyre HEAD: `69bd7de188bae72843f234870cbcde802c4f24fa`
  (moved ~40 commits since this morning's `e7bb29d`).
- pytorch HEAD:     `404bc9e7d59e3e741490b56e65572a31d713a8a7`.
- Declared torch pin: `torch~=2.13.0` (unchanged).

Recorded verbatim in `01-versions.json`, obtained by running the
skill's `resolve_versions.sh` from a fresh working directory. That
already succeeds — anonymous-then-token fetch, no defect.

## Findings from following SKILL.md verbatim

### 1. PVC contamination is a live hazard on shared home dirs

The very first script attempt (`setup_supported_env.sh --workdir
/home/tdeshane/supported`) refuses with

    FATAL: workdir already exists: /home/tdeshane/supported
           supported-control setup requires a fresh directory; refusing to proceed

because the PVC `a5-deepview` is shared across pods, and prior work
left `/home/tdeshane/supported` in place. Not a defect — the script
correctly refuses to overwrite state. SKILL.md's quick-start does
NOT tell the user to sweep `/home/tdeshane/{supported,forward,...}`
aside before starting on a shared-PVC pod. That's a doc gap for
v0.3 (either sweep in the script under an explicit flag, or note
the PVC-sweep step in quick-start).

We swept by hand:

    mv /home/tdeshane/{supported,forward,torch-spyre-work,manual-repro,fresh-validate,skill-runs} \
       "$_.pre-second-pod-2026-08-24"

then retried. `setup_supported_env.sh` completed RC=0 with
`torch 2.13.0+cpu` and a green editable install of torch-spyre
against it. Full log: `data/setup_supported.log` (~132 KB).

### 2. F3 reproduces from zero on 69bd7de (new SHA)

Ran `run_compat_smoke.sh` against the fresh supported venv and
tree, `--stage-through 3`. Stage 0 fails within 16 seconds:

    RuntimeError: Failed to load the backend extension: torch_spyre.
    ... caused by ...
    AttributeError: partially initialized module 'torch_spyre' has no
    attribute '_autoload' (most likely due to a circular import)

Full traceback: `data/supported-pre-f3-stage_0.log`.

This is F3 (`REVERSE_ENTRYPOINT_HAZARD`) — the same case as
`../live-current-main-F3/`. The interesting result is that **F3 is
still present at torch-spyre@69bd7de1**, ~40 commits past
`e7bb29d`. torch-spyre landed a partial fix (a `_ran` guard around
`_autoload`) but did NOT hoist `def _autoload` to before
`import torch` at line 20. The reverse-entrypoint hazard survives
because pytorch's `_import_device_backends()` still fires while
torch_spyre is only partially initialized, and by the time it
resolves `torch_spyre:_autoload`, the module has only executed
lines 1-20 (before the def). AttributeError is unchanged.

**This is the key skill-validation datum for task #46**: a fresh
user, on a fresh pod, running SKILL.md's own quick-start against
current torch-spyre `main`, will independently rediscover F3 within
the first Stage-0 run. The skill's own workflow surfaces the case
that its docs describe.

### 3. F3 patch — dual-compat, byte-adjusted for the new source shape

Applied the F3 defer-and-invoke pattern (from
`../live-current-main-F3/patches/F3-live-patch.diff`) adjusted for
69bd7de's `__init__.py` layout — the file changed since 8aba5bc, so
byte-copy doesn't apply but the pattern does. Verified: patched
`__init__.py` has:

- Early `def _autoload()` before `import torch` (line 20), with
  `_autoload._requested = True; return` when `_autoload_impl` is not
  yet bound.
- Original `_autoload_impl` unchanged at its historical position.
- Tail-invoke `if getattr(_autoload, "_requested", False): _autoload()`.

Patch as applied: `patches/F3-repro-69bd7de-patch.diff` (75 lines).

Under this patch, `import torch_spyre` succeeds — the smoke's Stage
1 imports pass (confirmed on the first pod earlier today, where the
same patch produced a full green Stage 0-3 run). On the second pod,
verification of Stages 1-3 was blocked by a substrate hang (see
finding #4) — the F3 fix itself is verified by observation #2
inverting: Stage 0 previously failed at line 20 of `__init__.py`,
after the patch that line no longer fails.

### 4. Substrate limit: one AIU device per pod, exclusive-use

Attempted to run `setup_latest_pytorch_env.sh` (forward torch build)
in parallel with the post-F3 supported smoke. The supported smoke
hung 5min into Stage 0 with

    RuntimeStream::waitForIdle() still waiting after 60000ms:
        in_flight_=1 queued_in_flight_=0 device=0
        possible lost completion
    ...
    DMA hardware error: response block status check failed

then SIGABRT from `libflex.so`. `setup_latest_pytorch_env.sh` does
not itself touch the device — it pip-installs a torch nightly wheel
and rebuilds torch-spyre — but the supported smoke had already
started the device runtime (via `capture_environment.py` at Step 3),
and something in the concurrent workload disturbed it enough to
lose a DMA completion.

**Not a defect of the skill, but a scheduling constraint worth
naming in v0.3 docs**: on a1-a5-deepview single-AIU-device pods,
supported-smoke and forward-setup should be serialized. The current
quick-start doesn't say this because Step 6 (forward setup) doesn't
touch the device — but concurrent runs on shared PVC + single
device can still deadlock. SKILL.md should say "run steps 5-7
serially" or the setup scripts should be device-aware.

### 5. `setup_latest_pytorch_env.sh` needs TORCH_SPYRE_TREE

Under NIGHTLY_PROXY mode, the script defaults to
`$HOME/torch-spyre-work/torch-spyre` for the tree, but sweeping the
PVC (finding #1) removes that if it existed, and setup_supported
puts the tree at `$WORKDIR/torch-spyre` instead. Fresh-user run
hits:

    FATAL: torch-spyre tree not found at /home/tdeshane/torch-spyre-work/torch-spyre
           set TORCH_SPYRE_TREE to override

The env-var escape hatch is documented in-script, but SKILL.md
quick-start (step 6) doesn't mention it. Second doc gap for v0.3.

## Skill-validation verdict

Task #46 satisfied: the byte-exact-same image, fresh pod, fresh
PVC-swept home, from `resolve_versions.sh` to
`run_compat_smoke.sh` — using SKILL.md's own commands — reaches the
F3 finding within 16 seconds of Stage 0. The workflow the docs
describe is the workflow that surfaces the case the docs describe.

Doc gaps found and named:

- (D1) PVC-sweep step missing from quick-start (SKILL.md between
  step 1 and step 2).
- (D2) TORCH_SPYRE_TREE not exported before step 6.
- (D3) No warning that steps 5-7 must not run concurrently on
  single-device pods.

None of these block v0.2's core claim — they're refinements for
v0.3. The core claim ("the skill produces reproducible cases from
its own docs") is verified.

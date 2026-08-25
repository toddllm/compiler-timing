# torch-spyre CI infrastructure — what already exists

Snapshot: torch-spyre main @ `613b259aacbee507c34ccba1e3e25280a6bc55cb`
(2026-08-25). Files fetched into `inventory/wf-*.yaml`.

## Workflows

| File | Trigger | Purpose |
|---|---|---|
| `integration-tests.yaml` | `workflow_dispatch` from an upstream dep repo | Runs `_test_matrix.yaml` with a caller-provided torch-spyre `ref` and `test_type` tier |
| `torch_spyre_tests.yaml` | `pull_request` and pushes (I did not read this one in depth yet) | Standard PR CI |
| `upstream_tests.yaml` | `workflow_dispatch` | Runs unmodified upstream pytorch suites against the pinned torch |
| `upstream_tests_beta.yaml` | `workflow_dispatch` | Beta variant of the above |
| `runtests_nightly.yaml` | `schedule: 0 2 * * *` + `workflow_dispatch` | Full nightly, calls `_test_matrix.yaml` with `checkout_pytorch: true` |
| `_test_matrix.yaml` | `workflow_call` | Reusable matrix runner (1221 lines) |
| `_upstream_tests_beta_matrix.yaml` | `workflow_call` | Upstream-tests matrix runner |
| `build_test_pytorch_source.yaml` | (unread) | pytorch source-build path |
| `model_ops_tests*.yaml` | (unread) | Model-level ops tests |
| `push-*.yaml` | (unread) | ClickHouse ingest jobs |

## What can already execute an arbitrary torch-spyre ref

`integration-tests.yaml` accepts:

| Input | Default | Notes |
|---|---|---|
| `ref` | `''` (uses `github.sha`) | Any branch / tag / SHA |
| `repository` | `''` (base repo) | Fork clone URL |
| `test_type` | `integration` | `smoke` / `unit` / `integration` / `regression` / `trunk` — these are literal test_suite_config.labels |
| `prebaked_image` | `true` | Uses pre-baked torch-spyre-dev image; nothing built at runtime |
| `runner_label` | `''` (uses `image_spyre_backend`) | Per-PR ephemeral image label |

The reusable `_test_matrix.yaml` is called with `checkout_pytorch: false`
— so **the pytorch version is whatever the pre-baked image contains**.
The image is `torch-spyre-dev`, built with the pyproject-declared torch
(currently `torch~=2.13.0`).

Under `prebaked_image=true` (the default here), there is no `pip
install` or C++ rebuild at runtime — the container already has the
editable install and the venv.

## What can execute an arbitrary PYTORCH ref

`.github/actions/checkout-pytorch/action.yml` composite action does
re-point the pre-cloned pytorch tree at a specific `sha` input, but

- `_test_matrix.yaml` never forwards a `pytorch_sha` input to the
  action (grep shows the action is called four times without any
  `with: sha:` block);
- so all four call sites use the action's default: pyproject-derived
  release branch;
- `runtests_nightly.yaml` sets `checkout_pytorch: true` and does
  compile against a source torch, but at the pyproject-pinned
  release branch, not a forward main or nightly.

**Conclusion for Track A:** the existing infra can dispatch a
torch-spyre ref end-to-end at the pyproject-pinned torch. It cannot,
without modification, run the same torch-spyre ref against a
DIFFERENT (forward) torch. To do the 2×2 the prompt asks for, one of:

1. Fork `_test_matrix.yaml` to accept a `pytorch_sha` input and forward
   it to the four `checkout-pytorch` calls. Small diff, big blast
   radius (the reusable workflow is called by four different
   parent workflows and has 1221 lines).
2. Run a shadow lane that does NOT depend on `_test_matrix.yaml`:
   reuse our validated `.claude/skills/torch-spyre-forward-compat/`
   scripts on a fresh pod — that's exactly what they were built for.
   No `.github/workflows/` changes required.

Track A picks path 2 for the initial validation: keep GitHub Actions
out of it entirely, use the forward-compat skill's pod-based lane as
the compatibility engine. The result is a per-PR compatibility
verdict that could be POSTED into a `_test_matrix.yaml` shim later —
but we don't need CI plumbing to establish the technique.

## Test-tier vocabulary

`test_type` is one of `smoke` / `unit` / `integration` / `regression`
/ `trunk` / `suite_<group>` / any label. These map DIRECTLY to
`test_suite_config.labels` in the repo's test suite config — there is
no alias-resolution layer. Comment in `integration-tests.yaml:2-8`
is explicit about this.

`integration` covers: streams, job launch plans, codegen,
LX/scratchpad planning, tensor layout, allocator/GC, D2D copies.
`regression` = every config. `trunk` = full trunk suite. `smoke` =
fastest subset.

## Labels observed in `.github/workflows/integration-tests.yaml`

- `triggering_repo` / `triggering_sha` / `pr_url_hash` — for upstream
  dep-repo callers to record provenance.
- `image_spyre_backend` = standing image; `image_spyre_backend_pr_*` =
  per-PR ephemeral runner-set label used when a PR builds its own
  container image.
- `clickhouse_env` = `dev` | `prod` — perf ingest routing.

## What that gives Track A

For each PR in the empirical corpus (Task #64), we CAN do this today
without any GitHub Actions changes:

- **Static triage** (Task #63): analyze diff / labels / files via
  `gh api`. Pure metadata. No infrastructure needed.
- **Cell A (main + supported):** the forward-compat skill's
  `setup_supported_env.sh` at torch-spyre main @ 613b259 + torch~=2.13.0.
  Already validated across three pod runs.
- **Cell B (PR head + supported):** re-run setup_supported with the
  PR's head_sha. Same script.
- **Cell C (main + forward nightly):** `setup_latest_pytorch_env.sh`
  at torch-spyre main + nightly cpu torch. Already validated (the
  third-clean-run went green).
- **Cell D (PR head + forward nightly):** same script with the PR's
  head_sha instead.

The 2×2 orchestration is a driver script that runs those four
sub-runs and interprets the four verdicts. That's the shadow-CI
core — no `.github/workflows/` write required.

## Not addressed in this task

- Whether `torch_spyre_tests.yaml` (the PR-native workflow) has knobs
  we haven't looked at.
- What `build_test_pytorch_source.yaml` does exactly; if it's a
  standing "compile pytorch from source at a specific ref" workflow,
  it might be closer to what Track A eventually needs than a
  greenfield extension of `_test_matrix.yaml`.
- Whether any repo secrets are needed for the ClickHouse perf ingest;
  Track A doesn't need them for the compatibility verdict.

# CI integration options (future, not urgent)

Reminder from the prompt: **do NOT wire this into production CI
yet, do NOT make GitHub status checks required, do NOT push
compatibility patches upstream as part of this task.** This
document is future-facing.

## Option 1: reuse `_test_matrix.yaml` with a `pytorch_sha` input

Concrete diff to torch-spyre (illustrative, not proposed as a PR):

- `_test_matrix.yaml`: add optional `pytorch_sha` input; forward to
  each of the four `uses: ./.github/actions/checkout-pytorch`
  callsites as `with: sha: ${{ inputs.pytorch_sha }}`. The
  action already accepts `sha`; it's just not plumbed through.
- New `.github/workflows/forward-compat-shadow.yaml`:
  workflow_dispatch only (no `pull_request` trigger), calls
  `_test_matrix.yaml` with `pytorch_sha` = current nightly-cpu
  torch git SHA. Doesn't post to PRs.

**Pros:** reuses existing prebaked-image path, existing test
matrix, existing ClickHouse ingest. Minimal new code.

**Cons:** the prebaked image is `torch-spyre-dev` with
`torch~=2.13.0` already installed. Overriding torch inside the
container means either rebuilding torch-spyre from source inside
CI (cost) or having the container ship a virtualenv-swap
script. Not trivial.

## Option 2: greenfield workflow using the forward-compat skill's pod-based lane

Concrete shape:

- New `.github/workflows/forward-compat-cell-b.yaml`:
  workflow_dispatch only. Inputs: `ref` (PR head SHA), `torch_mode`
  (SUPPORTED | FORWARD_NIGHTLY).
- Runner uses the standing `image_spyre_backend` runner set, NOT
  the prebaked image.
- Invokes the forward-compat skill's `setup_supported_env.sh`
  and/or `setup_latest_pytorch_env.sh` scripts checked into the
  torch-spyre-forward-compat plugin directory.
- Emits result to job summary + optional ClickHouse.

**Pros:** clean separation — the pseudo-CI lane is its OWN
workflow with its OWN scripts. Doesn't perturb the existing
`_test_matrix.yaml` path.

**Cons:** duplicates some of the standing runner setup.

## Option 3: keep off-CI entirely

Do the forward-compat runs from a maintainer's laptop / dev-pod on
demand. Post nothing back. Emit a dashboard to a private
compiler-timing repo (this repo).

**Pros:** no CI blast radius. No security review needed. No
required-check concerns.

**Cons:** manual to trigger; results not auto-shared.

Currently doing option 3 — everything in Track A is off-CI.

## Recommendation

Not urgent to move off option 3. Once the compatibility ledger
stabilizes and the maintainer team asks for continuous status,
option 2 is the cleanest path: greenfield workflow, own scripts,
`workflow_dispatch` only, never `pull_request`, never `required`.

Option 1 is a bigger commitment because it touches the shared
`_test_matrix.yaml` — that's a lot of consumers of a critical
workflow, and the `pytorch_sha` addition would be a real API
change to be reviewed carefully.

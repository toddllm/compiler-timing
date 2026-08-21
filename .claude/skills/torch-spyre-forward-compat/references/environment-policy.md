# Environment policy

Non-negotiable rules for the pod environment used in a
torch-spyre forward-compat run. Violation of any rule invalidates
the run — the whole point of a forward-compat study is that the
environment is a known, captured artifact, not a drifted mystery.

## Fresh pod per run

- Every forward-compat case starts from a **freshly-created pod**.
  No reuse of a prior venv, a prior `_C.so`, a prior torch install,
  or a prior compiler cache directory.
- The pod is named for the case (e.g. `tdeshane-forward-compat-2026-08-21`)
  and is created for that case alone. Namespace is `a5-deepview`.
- The base image is
  `us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest`.
  This is a moving tag by design — the immutable digest is
  recorded at pod-creation time (see "Recording the image
  digest" below).
- The pod spec sets `imagePullPolicy: Always` (or the platform
  equivalent) so that the fresh pod actually pulls the current
  `:latest`, not a cached stale copy on the node.

The one narrow exception is the fresh-pod reproduction
acceptance test (§18 of the SKILL prompt): the same pod may be
reused **only** to re-run the reproduction protocol from a
scrubbed state (see "Fresh-pod reproduction reuse" below).
Anything else — a second case, a follow-up validation, a "quick
retry" — requires a new pod.

## Recording the image digest

The `:latest` tag drifts. Every run must pin the exact image
that produced its results:

```
kubectl -n a5-deepview get pod <pod-name> \
    -o jsonpath='{.status.containerStatuses[*].imageID}'
```

The resulting `docker-pullable://…@sha256:<digest>` string
lands in `environment.json` under `image.digest`. Two runs that
claim the same base image but carry different digests are two
different environments and must be reported as such.

## Compiler-cache hygiene

- `TORCHINDUCTOR_CACHE_DIR` is created fresh for the run,
  under a path unique to the run (e.g.
  `/tmp/forward-compat-<date>/inductor-cache/`). Never reuse a
  previous run's cache dir even implicitly via
  `$HOME/.cache/torch/inductor`.
- The ccache directory (`CCACHE_DIR` if ccache is in play for the
  `_C.so` build) is likewise fresh, unless the case is
  **deliberately** measuring warm-cache behavior — in which case
  `environment.json` records `ccache.reused: true` and the source
  of the reused cache.
- Any other compiler / linker cache the base image installs
  (Spyre compiler on-disk cache, deeptools cache, LLVM module
  cache) is cleared at the start of the run. Absence of caching
  is the default; presence is a labeled exception.

## The environment.json capture

Every run emits a single `environment.json`. It is produced by
`scripts/capture_environment.py` and lands under
`analyses/<date>-<slug>/environment/environment.json` **before
any test runs**. A missing or late `environment.json` is a
protocol failure — the results are unusable because they cannot
be tied to a substrate.

### Required schema

```json
{
  "run_id": "<date>-<slug>",
  "captured_at": "<ISO-8601 UTC>",
  "image": {
    "name": "us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest",
    "digest": "sha256:<64-hex>",
    "pull_policy": "Always"
  },
  "pod": {
    "name": "<pod-name>",
    "namespace": "a5-deepview",
    "node": "<node-name>",
    "created_at": "<ISO-8601 UTC>"
  },
  "python": {
    "version": "<X.Y.Z>",
    "executable": "<abs path>",
    "venv": "<abs path or null>"
  },
  "torch_stack": {
    "torch": {"version": "<X.Y.Z>", "location": "<abs path>"},
    "torch_spyre": {
      "version": "<X.Y.Z>",
      "location": "<abs path>",
      "editable": true,
      "commit": "<sha or null>"
    },
    "deeptools": {"version": "<X.Y.Z or null>"}
  },
  "spyre_runtime": {
    "spyre_compiler": {"version": "<...>", "package": "<name>"},
    "spyre_runtime_libs": [
      {"name": "<lib>", "version": "<...>"}
    ]
  },
  "toolchain": {
    "gcc": "<version string>",
    "clang": "<version string or null>",
    "cmake": "<version>",
    "ninja": "<version>"
  },
  "device": {
    "torch_spyre_device_count": <int>,
    "equivalent_probe": "<name>: <int>",
    "probe_output": "<raw>"
  },
  "env_vars": {
    "TORCH_SPYRE_DEBUG": "<value or null>",
    "LX_PLANNING": "<value or null>",
    "SENCORES": "<value or null>",
    "TORCH_LOGS": "<value or null>",
    "TORCHINDUCTOR_CACHE_DIR": "<abs path>",
    "CCACHE_DIR": "<abs path or null>",
    "<other>": "<value>"
  },
  "declared_torch_spec": "<verbatim from pyproject.toml — e.g. torch~=2.13.0>"
}
```

### Field notes

- `image.digest` comes from `kubectl … imageID` as shown above.
  Never fabricate; leave `null` and mark the run invalid if the
  digest cannot be resolved.
- `torch_stack.torch_spyre.commit` is `git rev-parse HEAD` inside
  the editable install location.
- `declared_torch_spec` is the current spec string read from
  `torch-spyre@<HEAD>:pyproject.toml` at capture time — the
  capture script must **re-read pyproject.toml at runtime**, not
  hard-code a value. The current value at the time of this
  writing is `torch~=2.13.0` (torch-spyre main HEAD
  `a3128985`, torch-spyre repo is private — citation form
  `torch-spyre@a3128985:pyproject.toml:<line>`), but the spec is
  expected to change and the capture must reflect whatever it is
  at run time.
- `device.torch_spyre_device_count` is the result of
  `torch.spyre.device_count()`. `device.equivalent_probe` records
  the platform-specific probe (e.g. lspci for the AIU, or the
  runtime library's own device enumerator) and its result. Both
  numbers must be present; a divergence between them is itself
  the answer for some forward-compat cases.
- `env_vars` records the resolved values at capture time. If a
  var is unset, use JSON `null` (not the empty string) so that
  "unset" is distinguishable from "set to empty" in diff tools.

## Fresh-pod reproduction reuse

The fresh-pod reproduction acceptance test (§18 of the SKILL
prompt) is the one place where the same pod may be reused. The
protocol:

1. The primary run has already produced its `environment.json`
   and results.
2. Wipe the venv, the editable install, and any compiler caches
   that the primary run touched. Leave the base image and any
   runtime libs from the image untouched.
3. Re-capture `environment.json` — the second capture goes to
   `environment/environment.post-wipe.json` and must show the
   torch stack absent (or reverted to the image's built-in
   state), caches cleared, and the same `image.digest` as the
   primary capture.
4. Reinstall the torch stack from the same pinned
   specifications the primary run used.
5. Re-capture `environment.json` a third time
   (`environment.reproduction.json`) and diff it against the
   primary capture. The two must agree on `image.digest`,
   `torch_stack.*.version`, `spyre_runtime.*`, `toolchain.*`.
   Divergence on any of those invalidates the reproduction — the
   pod has drifted despite the wipe, and a genuinely fresh pod
   is required.
6. Re-run the case.

Any reuse outside this protocol is prohibited. In particular:

- Do **not** reuse a pod across two different forward-compat
  cases, even if they share an image.
- Do **not** reuse a pod for a follow-up "just the failing test"
  rerun — that path is where drift enters silently.
- Do **not** reuse a pod because the fresh one is slow to
  schedule. Time cost is not an acceptable reason to invalidate
  a run.

## When a run cannot satisfy this policy

If any of the following happens, stop and record the run as
`INVALID_ENVIRONMENT` rather than producing results:

- The pod could not be freshly created (only an existing pod
  was available and it does not satisfy the reproduction-reuse
  protocol).
- `image.digest` cannot be resolved.
- `environment.json` was not written before the first test run.
- The declared torch spec in `pyproject.toml` could not be read
  at runtime (script fell back to a hard-coded value).
- `torch.spyre.device_count()` and the equivalent probe cannot
  both be recorded.

`INVALID_ENVIRONMENT` is a first-class verdict. Producing it
correctly is more useful than producing suggestive numbers on
an un-attested substrate.

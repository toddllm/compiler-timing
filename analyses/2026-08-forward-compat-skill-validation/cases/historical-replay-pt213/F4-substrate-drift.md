# F4 — Substrate drift makes historical replay's baseline unbuildable without a companion patch

**Discovered 2026-08-21 during §7 replay setup.** Not part of Todd's
original v0.1 finding list — surfaced by attempting the replay
mechanic itself.

## Observation

Cloned torch-spyre@`dd95ef44e` (parent of the 2.13-upgrade fix
`754839cc8`) and tried to build against `torch~=2.12.0` on the
current `torch-aiu-runtime-dev:latest` image
(digest `sha256:81c352893b...`). **Build failed rc=1** with:

```
fatal error: util/sendefs.h: No such file or directory
fatal error: util/sen_host_ops.h: No such file or directory
fatal error: util/spyrecode.h: No such file or directory
fatal error: util/sen_data_convert.h: No such file or directory
```

The same failure reproduces against torch 2.13 in a separate venv
(also rc=1). So the failure is **not torch-version-dependent**; it's
substrate-dependent.

## Root cause

Between `dd95ef44e` (2026-07-29-ish) and `a31289852` (2026-08-21),
torch-spyre committed a header-path migration at
`bf1ddc05e81020d372e1d6632beaab064cbcdbeb` — "Change deeptools headers
path (#3408)" (Alberto Mannari, 2026-07-31). Nine files were touched:

- `.github/actions/build-torch-spyre-wheel/action.yml`
- `torch_spyre/csrc/job_plan.cpp`
- `torch_spyre/csrc/job_plan.h`
- `torch_spyre/csrc/module.cpp`
- `torch_spyre/csrc/module.h`
- `torch_spyre/csrc/prepare_kernel.cpp`
- `torch_spyre/csrc/spyre_tensor_impl.h`
- `torch_spyre/csrc/spyre_views.cpp`
- `torch_spyre/csrc/types_mapping.h`

The migration rewrote every `#include "util/<x>.h"` to the new nested
paths, e.g.:

- `util/sendefs.h` → `util/sendefs/sendefs.h`
- `util/sen_host_ops.h` → `spyrecode-host-functions/sendataconvert/sen_host_ops.h`
- `util/spyrecode.h` → `spyrecode-host-functions/spyrecode.h`
- `util/sen_data_convert.h` → `spyrecode-host-functions/sendataconvert/sen_data_convert.h`

The current pod image ships the *new* header layout under
`/opt/ibm/spyre/deeptools/include/`. Pre-`bf1ddc05e` source code no
longer compiles on this substrate because its old-style includes
don't resolve.

## Why this matters for the historical replay

Todd's §7 asked: "run torch-spyre@dd95ef44 against torch 2.13 and see
whether the skill independently rediscovers the LX
producer/consumer semantic break." The intent was that only the
torch version differs between baseline and forward configurations, so
any observed break is attributable to torch.

But on the *current pod substrate*, torch-spyre@dd95ef44 **cannot
build at all**. A "run torch-spyre@dd95ef44 against torch 2.13"
experiment on this pod is contaminated by a substrate mismatch: the
build fails not because torch changed, but because deeptools headers
changed. Any patch that "fixes" the build without acknowledging this
substrate drift would be a substrate-patch, not the actual LX-fix
Todd's replay is validating.

Three ways to make the replay executable on this substrate:

1. **Cherry-pick `bf1ddc05e`** onto `dd95ef44`. The replay's baseline
   becomes `dd95ef44 + bf1ddc05e = <new SHA>`, which builds cleanly.
   The LX semantic break we're chasing is orthogonal to headers, so
   the cherry-pick doesn't corrupt the experiment. This is what this
   session did.
2. **Older pod image.** Provision a pod with an image that ships the
   old header layout — probably `torch-aiu-runtime-dev:dev-2025_12_10-*-pt2.9.1`
   from the docs pod template, but that image also ships torch 2.9.1,
   not 2.12/2.13. Multiple substrate variables move together.
3. **Skip torch-spyre-parent entirely.** Start the replay from
   `754839cc8^` and roll back only the LX-fix hunks. But that
   defeats the purpose — the replay is supposed to prove the skill
   can find the fix by discovering the failure without being told
   what to look for.

Option 1 is the cleanest for validation because it isolates one
variable at a time. Option 2 is what a real customer would face if
they froze their substrate. Option 3 is a cheat.

## Failure taxonomy category

**`SUBSTRATE_FAILURE`** — the pod image and the source under test are
from different eras and their headers no longer line up. The
appropriate response is not to patch torch-spyre; it's to align the
substrate (option 2) or apply a substrate-compatibility patch series
(option 1).

## Rule for v0.2

The skill needs a **substrate-alignment probe** as part of Stage 0,
in `references/environment-policy.md`. Before running any ladder,
check whether the code under test can even build against the current
substrate at *its own declared torch version*. If it can't, halt and
either escalate to a different image or apply a
substrate-compatibility patch series (recorded in the case).

Concretely: add a `substrate-fitness-check` step that does a bare
`pip install -e . --no-deps --no-build-isolation` at the declared
torch pin and requires rc=0 before the ladder proceeds. If it
fails, the failure is `SUBSTRATE_FAILURE` and the ladder's
subsequent forward-compat findings are void.

## Session action

1. Cherry-pick `bf1ddc05e` onto both replay trees (baseline and
   forward). Both now at `dd95ef44 + bf1ddc05e = 3b49fbe`/`858b046`.
2. Rebuild in progress.
3. Once baseline builds cleanly against torch 2.12, run the actual
   §7 replay: torch 2.13 build + aminmax test — the LX
   producer/consumer break should surface.

## Value to the skill

This finding demonstrates one of the skill's most important
properties: **it distinguishes substrate failures from source-code
failures**. Todd's original v0.1 SUPPORTED_CONTROL failure was
misclassified as a pyproject-pin issue when it was really a pipeline
defect. Now the historical replay's initial build failure could have
been misclassified as a pre-existing torch-spyre bug in dd95ef44,
when it's really substrate drift. The taxonomy is doing real work
here.

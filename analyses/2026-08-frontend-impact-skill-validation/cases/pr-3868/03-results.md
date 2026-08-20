# Results — PR #3868

**Written AFTER measurement. Reflects both the initial marginal-patch
attempt AND the tightened alignment gate that the initial measurement
itself motivated.**

## Verdict

**INSUFFICIENT_EVIDENCE** for the question "impact of PR #3868 vs its
actual base".

The marginal-patch measurement (12 paired cold samples at WB_n4 and
WB_n8, initially reported below as an A/B) is retracted as a validated
PR-impact measurement. Per the tightened alignment gate in
`references/measurement-policy.md`, "diff applies cleanly" (Tier 2) is
not sufficient when a PR-touched file has drifted at the pod base.
`bundle.py` at the pod (md5 `314e022307...`) differs from `bundle.py`
at PR #3868's actual base `2e935f...` (md5 `c93d3ba5d7...`). The pod
version is 14 lines shorter and predates the pool-allocation
body-emit refactor.

## Why the marginal-patch data is retained but not authoritative

The measurement DID happen. It shows a consistent pattern at two
workload points:

- Every Spyre pass pipeline: flat within ±1.5%.
- `sdsc_bundle_gen`: +55–65% (regressed at head).
- `dxp_standalone`: −33% at both points (backend faster at head).
- `n_specs` on both bundles: unchanged (5→5 and 1→1).

But the "base" here is *pod pre-refactor bundle.py*, not PR base
bundle.py. The observed effect is `[PR #3868 diff] applied to
[older-pre-refactor pod bundle.py]` vs `[older-pre-refactor pod
bundle.py]`. It is NOT `[PR #3868 head] vs [PR #3868 base]`.

The two are meaningfully different: PR base ALREADY carries the
pool-allocation refactor (a `pool_size` param, `MAX_POOL_SIZE_BYTES`
import, `device_mem_allocate` in the emitted body instead of a
`%pool_base_addr` parameter). Any `dxp_standalone` movement in the
marginal-patch data could be attributed to the pool refactor being
introduced late (at head, from pod's perspective) rather than to
PR #3868 itself.

We cannot separate the two contributions from this data. So this
measurement stays as an exploratory data point, labeled clearly, and
does not classify PR #3868 under the seven-verdict scheme.

## Attempted isolated checkout

Per the tightened Tier 3 policy, an isolated checkout at PR #3868's
exact base SHA `2e935febe58bcf275accfaa4c960d972d7e6ce49` and head SHA
`a7786ac8a6934645821b3698a9eb33ae2d3b590b` was set up on the pod. Both
trees checked out cleanly. `bundle.py` md5s at the two isolated
checkouts (`c93d3ba5d7...` at base and `e13273ee01...` at head) match
the blobs fetched from GitHub directly, confirming the trees.

Symlinking the pod's shared `_C.so` (built at pod SHA `a9316b3`) into
the isolated checkout failed at import time:

```
ImportError: cannot import name 'NativePermutationLayoutSolver' from
    'torch_spyre._C' (/home/tdeshane/pr3868-iso/torch-spyre-base/
     torch_spyre/_C.so)
```

`NativePermutationLayoutSolver` is a new C++ symbol added between the
pod's SHA and PR #3868's base. It is imported top-level in
`_inductor/scratchpad/permutation_layout.py`, which is transitively
imported by `_inductor/scratchpad/allocator.py`, which the compile
pipeline loads. We cannot dodge this import.

Rebuilding `_C.so` from source in the isolated tree failed with:

```
fatal error: spyrecode-host-functions/fast_process_hcm.h:
    No such file or directory
```

The pod's `/opt/ibm/spyre/deeptools/include/spyrecode-host-functions/`
directory only contains
`processSpyreCodeArtifacts.h, senconst, sendataconvert, spyrecode.h` —
`fast_process_hcm.h` is not present. The pod's deeptools install is
older than what PR base needs.

Per the Tier 3 policy: "Only fall back to `INSUFFICIENT_EVIDENCE`
when even the fresh build fails (system libs too old for the PR's
base)." Fresh build fails. Verdict: `INSUFFICIENT_EVIDENCE`.

## Where the marginal-patch measurement data lives

Preserved for reference and for anyone with a newer substrate:

- `data/kv1024-nchunks4-{base,head}-run{1,2,3}.json` — WB_n4 paired.
- `data/kv512-nchunks8-{base,head}-run{1,2,3}.json` — WB_n8 paired.

These files are what got measured. Their interpretation is limited
per the retraction above.

## Bundle-level marginal-patch breakdown (supplementary)

Two SDSC bundles per compile. All samples show the same pattern:

| Bundle | n_specs | base bundle_gen (s) | head bundle_gen (s) | Δ | base dxp (s) | head dxp (s) | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| `sdsc_fused_amax_full_zeros_like_0` | 5 → 5 | 0.028 | 0.048 | +0.020 | 1.14 | 0.78 | −0.36 |
| `sdsc_fused_add_amax_..._unsqueeze_1` | 1 → 1 | 0.457 | 0.743 | +0.286 | 22.07 | 14.55 | −7.52 |

`n_specs` unchanged on both bundles at both workload points, so the
PR's cache was never populated — every op-spec was distinct at this
workload.

## Prediction vs measurement (rebalanced)

Original prediction: `FRONTEND_IMPROVEMENT` on `sdsc_bundle_gen` via
cache hits. That prediction is preserved verbatim in
`01-static-assessment.md` and `prediction.json`. It was written
before the measurement.

The measurement is `INSUFFICIENT_EVIDENCE` at the PR-base level.
The exploratory marginal-patch data disagrees with the prediction on
direction, but per the retraction above we cannot say the disagreement
is a property of PR #3868 rather than of the pod-drift substrate.

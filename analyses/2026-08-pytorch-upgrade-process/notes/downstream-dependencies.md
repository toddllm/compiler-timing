# Downstream dependencies — evidence + patterns

## Historical evidence

- **2.11 upgrade (#1930):** profiler infrastructure broke; deferred
  to 2.12.
- **2.12 upgrade (#2218):** vLLM had not moved to 2.12 (draft PR
  vllm-project/vllm#42848). Resolved by spyre-inference#357
  removing dependence on precompiled vLLM CPU wheels.
- **2.13 upgrade (#3374):** no downstream lag mentioned; the 2.12
  architectural change kept the path clear.

## The downstream projects that matter

From SKILL.md snapshot + PR discussion:

| Project | Repo | Coupled to torch | Rebuild style |
|---|---|---|---|
| vLLM | vllm-project/vllm | Yes (`_C.abi3.so`) | `uv pip install -e . --torch-backend=auto` |
| spyre-inference | torch-spyre/spyre-inference | Indirect via vLLM | (Python-only after #357) |
| hf-adapters | torch-spyre/hf-adapters | (unknown; probably Python-only) | |
| kineto-spyre | IBM/kineto-spyre | Yes (extension) | Wheel published per torch version |
| torchvision, torchaudio | pytorch/vision, pytorch/audio | Yes | Reinstall from source or matching wheel |

## Pattern: coupling can be architected away

The 2.12 → 2.13 unblock is the cleanest datum. spyre-inference#357
"swap to vllm-empty" — the summary is:

> "We have merged a PR in spyre-inference that removes our
> dependency on precompiled CPU wheels of upstream vLLM. This
> gives us more flexibility in terms of which torch version we
> can use, and in particular means we can bump the torch version
> before upstream vLLM does. Nothing blocking this anymore from
> our side."  
> — @tdoublep, 2026-07 comment on PR #2218

The strategic decision: DO NOT let downstream release cadences
gate the torch-spyre bump. Where a downstream isn't ready, either
(a) architect around the coupling, or (b) merge and let the
downstream catch up. This is why the 2.12 → 2.13 hop was so fast.

## Pattern: kineto-spyre wheels are the persistent friction

SKILL.md flags this explicitly: "Warning: The kineto-spyre wheel
for the new version may not yet be published." No matching
architectural workaround — the wheel is a hard external artifact
that has to be released for each new torch minor.

A readiness dimension for kineto-spyre wheels: is the wheel for
target torch published at `github.com/IBM/kineto-spyre/releases`?
Simple binary check.

## Pattern: ABI rebuild is the reliable ambient hazard

Every downstream C++ extension linked against libtorch/libc10 must
be rebuilt. SKILL.md's `nm -D --undefined-only ... | grep _ZN3c10`
diagnostic is the right tool. But it's an operator recipe, not
automated.

An automated version:

```bash
for so in $(find $VENV/lib/python*/site-packages -name "*.so"); do
    if nm -D --undefined-only "$so" 2>/dev/null | grep -q -E "_ZN3c10|_ZN5torch"; then
        echo "STALE: $so"
    fi
done | tee stale-extensions.txt
```

Trivial to bake into a readiness check.

## Pattern: what downstream feature gates matter

From @ani300's 2.12 comment: "there are a lot of breaking changes
for 2.12 that affect us: decompositions, profiling, symbolic shapes
hints — these are all changes we (as IBM) have requested from
pytorch."

The team knows in advance which upstream torch features they want
enabled. That means a readiness check has a QUESTION component:
"is upstream feature X in target release?" Answered via:

- pytorch release notes;
- specific PR-in-torch numbers the team is tracking;
- the compatibility ledger's `upstream_followup_pr` field.

For future bumps, the ledger should track "we care about upstream
PR NNNN — is it in target release?" as a first-class item.

## Composition into the readiness model's D3

D3 as stated in the readiness model:

- [ ] vLLM compatible OR spyre-inference has decoupled
- [ ] spyre-inference main builds against target torch
- [ ] hf-adapters compatible
- [ ] kineto-spyre wheel published
- [ ] All C++ extensions rebuilt cleanly (nm scan)

The first four are queries against external repos / release pages.
The last is an operator recipe that's automatable. All would be
one skill's worth of glue code.

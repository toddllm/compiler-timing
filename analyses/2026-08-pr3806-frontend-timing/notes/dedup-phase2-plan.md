# `dedup_and_promote_constants` — Phase 2 Plan & Evidence Framework

Companion to `notes/dedup-source-analysis.md`. This is the pre-measurement
plan and the framework for the six-section decision report the phase must
produce. Section A (exact-source corrections) is filled in now.
Sections B–F are stubs pointing to the exact tables the analyzer emits;
they get populated after the sweep runs.

**No production optimization is implemented in this phase.** Every deliverable
here is either (a) diagnostic instrumentation gated off by default, or
(b) additive unit tests that lock in current behavior.

## Contents

- [0. Source basis](#0-source-basis)
- [A. Exact-source corrections](#a-exact-source-corrections)
- [Pre-dedup pass mutation table](#pre-dedup-pass-mutation-table)
- [Batch-removal safety, redone at `a9316b3`](#batch-removal-safety-redone-at-a9316b3)
- [Diagnostic instrumentation plan](#diagnostic-instrumentation-plan)
- [Unit-test plan](#unit-test-plan)
- [A vs E decision framework](#a-vs-e-decision-framework)
- [B. Measured cost decomposition (stub — post-run)](#b-measured-cost-decomposition-stub--post-run)
- [C. Consumer-index evidence (stub — post-run)](#c-consumer-index-evidence-stub--post-run)
- [D. A-vs-E engineering decision (stub — post-run)](#d-a-vs-e-engineering-decision-stub--post-run)
- [E. Predicted new complexity (stub — post-run)](#e-predicted-new-complexity-stub--post-run)
- [F. Exact next implementation experiment (stub — post-run)](#f-exact-next-implementation-experiment-stub--post-run)

## 0. Source basis

Every claim in this document is against these SHAs. Do not read
against any other version.

| component        | version                                                            | on this laptop                                   |
| ---------------- | ------------------------------------------------------------------ | ------------------------------------------------ |
| torch-spyre      | `a9316b381fb66013945b0a5fa6159ae7c782e1d9` ("PR #3806 head")       | `~/multi-spyre-testing/repos/torch-spyre`         |
| upstream PyTorch | `cf30153c4c131c8164ee7798e5022d810682e2cb` (torch 2.13.0+cpu)      | `~/dt-inductor.1/pytorch` (fetched, not checked out) |
| Python           | 3.12.13 (RHEL 9.6 pod)                                             | —                                                |

Cross-check: study's `data/env-probe.json` records
`torch=2.13.0+cpu`, `torch.version.git_version=cf30153c...`,
`torch_spyre_repo.git_rev_parse_HEAD=a9316b381...`. Study README §Environment
matches.

## A. Exact-source corrections

Delta between the previous report (source read at `0e8f7f257`, June)
and the actual measured version at `a9316b3`. Only files that
materially affect the dedup optimization are listed.

**Conclusions that hold unchanged:**

- `dedup_and_promote_constants` algorithm shape: group by
  `(value, dtype, device)` → per-duplicate `_redirect_consumers` +
  `_drop_constant` → front-load. Same steps, same order.
- `_redirect_consumers` walks all of `graph.operations` and calls
  `op.get_read_writes()` on each op. Same code.
- `_drop_constant` calls `operations.remove(dup)`; still `O(N)` per
  duplicate on a Python list.
- Cleanups on `V.graph.{removed_buffers, name_to_buffer, name_to_op,
  name_to_users}` unchanged.
- `NameSwapHandler` (in `insert_restickify.py`) unchanged; still the
  mechanism `_patch_inner_fn` uses.
- Upstream torch 2.13 `GraphLowering.name_to_users` behavior unchanged
  from the pattern I described: populated at lowering by
  `register_users_of(result)`, called from `graph.py:2141` (moved from
  1822 in the earlier tree but same call site semantically). Value
  entries are `TensorBox` instances; keys are the read-name set from
  `TensorBox.get_read_names()`. `ComputedBuffer.get_read_writes` is
  still uncached at 2.13 (torch/_inductor/ir.py:5281). `Buffer.make_loader`
  still emits `ops.load(self.name, ...)` (ir.py:5065).

**Conclusions that changed (or need to change) at `a9316b3`:**

1. **`_drop_constant` calls `merge_provenance([canonical, dup], canonical,
   pass_name="dedup_and_promote_constants", reason="duplicate constant")`
   before `operations.remove(dup)`**. This did not exist at
   `0e8f7f257`. `merge_provenance` (source at
   `torch_spyre/_inductor/provenance.py:303-323`, and its helpers
   `_union_origins`, `_append_transform`):

   - Unions `dup.origins` (and `canonical.origins`) into `canonical.origins`
     in place (`_union_origins`).
   - Clears `canonical.origin_node` to None.
   - Appends a `ProvenanceTransform(kind="fusion", pass_name=...,
     reason=...)` to `canonical`'s `_spyre_prov_history`.

   It mutates only `canonical` and reads only `[canonical, dup]`. It
   does not touch `graph.operations`, `name_to_users`,
   `name_to_buffer`, `name_to_op`, or `removed_buffers`. **Therefore
   merge_provenance is cleanly separable from any operations-list
   surgery: call it once per duplicate on the canonical, before
   scheduling the duplicate for batch removal.**

2. **`CustomPreSchedulingPasses` ordering** at `a9316b3` is the full
   20-pass pipeline the study measured. Pre-dedup mutating passes
   (from `passes.py:447-486`), in order:
   `deadcode_elimination, propagate_named_dims, validate_named_dims,
   assign_dim_hints, _maybe_reorder_unhinted_interlopers,
   _maybe_coarse_tile_hints, split_multi_ops,
   propagate_spyre_tensor_layouts, validate_ops,
   optimize_restickify_locations, finalize_layouts, insert_restickify,
   enforce_indirect_access_layout, insert_post_mutation_restickify,
   insert_bmm_padding, dedup_and_promote_constants`.

   Two new passes vs `0e8f7f257`: `enforce_indirect_access_layout` and
   `insert_post_mutation_restickify`. Both need mutation-table entries
   (below).

3. **The previous report's batch-removal sketch (§7)** did not include
   the `merge_provenance` call. Any real implementation must preserve
   it. The corrected sketch is in the batch-removal section below.

4. **The "output-name skip" latent-bug observation** (previous report §8):
   still present at `a9316b3`, byte-identical code path. The pass still
   skips `_redirect_consumers` for output-name duplicates but proceeds
   to `_drop_constant` (which is where `operations.remove` and
   `merge_provenance` live). Reachability and severity are still
   unanswered; do not couple this to the performance work.

## Pre-dedup pass mutation table

Rows are passes that run between the earliest pass that can affect a
constant's consumer set and `dedup_and_promote_constants`, in
pipeline order (`passes.py:447-486` at `a9316b3`).

Columns:

- **ops list**: mutates `graph.operations`?
- **inner_fn / reads rewrite**: patches a consumer's `inner_fn` with a
  `NameSwapHandler` or otherwise rewrites what the consumer reads?
- **updates `name_to_users`**: writes to `graph.name_to_users`?
- **can over-report `name_to_users[D]` (FP)**: after this pass, can a
  buffer name D correctly still be in `name_to_users[D]` even though
  the referenced TensorBox no longer really reads D?
- **can under-report `name_to_users[D]` (FN)**: can this pass introduce
  a new real reader of D without a corresponding entry in `name_to_users[D]`?

**Methodological note (correction).** The original version of this
table analyzed only pass MUTATIONS *after* index construction — i.e.
"does this pass update `name_to_users` correctly given that the
index was already populated at lowering time?" That was insufficient.
The later Section C measurement showed that `name_to_users` was
already incomplete at *creation time*: when a single `run_node` call
lowers an FX node whose decomposition produces internal IR consumers
(e.g. `constant_pad_nd` → allocate + `SpyreConstantFallback` +
fill Pointwise + copy Pointwise), `register_users_of` runs once on
the top-level returned `TensorBox` and does not visit the internal
`ComputedBuffer`s that were created along the way. Any pass whose
lowering path goes through such a decomposition can leave
`name_to_users[<internal reader's target>]` under-populated. The FN
column below has been rewritten to reflect this.

| pass                                | ops list                  | inner_fn / reads rewrite | updates `name_to_users` | FP possible | FN possible |
| ----------------------------------- | ------------------------- | ------------------------ | ----------------------- | ----------- | ----------- |
| `deadcode_elimination`              | removes dead ops          | no                       | no                      | yes¹        | no          |
| `propagate_named_dims`              | metadata only             | no                       | no                      | no          | no          |
| `validate_named_dims`               | no writes                 | no                       | no                      | no          | no          |
| `assign_dim_hints`                  | metadata only             | no                       | no                      | no          | no          |
| `_maybe_reorder_unhinted_interlopers` | reorder only            | no                       | no                      | no          | no          |
| `_maybe_coarse_tile_hints`          | metadata only             | no                       | no                      | no          | no          |
| `split_multi_ops`                   | removes+inserts (`run_node`) | patches inner_fn²      | yes (via `run_node`)    | yes²        | yes³        |
| `propagate_spyre_tensor_layouts`    | metadata only             | no                       | no                      | no          | no          |
| `validate_ops`                      | no writes                 | no                       | no                      | no          | no          |
| `optimize_restickify_locations`     | metadata only             | no                       | no                      | no          | no          |
| `finalize_layouts`                  | writes `restickify_plan`  | no                       | no                      | no          | no          |
| `insert_restickify`                 | inserts (`run_node`) + `remove/insert` reorder | patches consumer inner_fn (name-swap old→new restickify buffer) | yes (via `run_node`) | yes⁴ | yes³ |
| `enforce_indirect_access_layout`    | via `insert_restickify_on_node_inputs` | patches consumer inner_fn | yes (indirect) | yes⁴ | yes³ |
| `insert_post_mutation_restickify`   | inserts (`run_node`) + reorder | rewrites mutation-op layout; does not swap constant reads | yes (via `run_node`) | no⁵ | yes³ |
| `insert_bmm_padding`                | inserts (`run_node`) + reorder; `_rebuild_matmul` via `replace_computed_buffer_body` | patches matmul inner_fn (y-loader → padded buffer) | yes (via `run_node`)   | no⁶ | **yes — measured** ⁶ |

Footnotes:

1. **`deadcode_elimination` — FP:** a dead consumer op is removed from
   `graph.operations` but its stale entry in
   `name_to_users[<any buffer it read>]` is not cleaned. Downstream code
   that trusts `name_to_users` will see a `TensorBox` that maps back
   (via `TensorBox → StorageBox → ComputedBuffer`) to an op that no
   longer exists in `operations`. Impact on dedup: over-reports
   candidates. Mitigation: filter candidates through
   `get_read_writes` (their reads may still be D even though they were
   dropped) OR check `op is in operations`. The dropped op will not be
   in `V.graph.name_to_op` after DCE either (DCE adds writes to
   `removed_buffers` but does not touch `name_to_op` — see
   `torch_spyre/_inductor/deadcode_elimination.py:88-97`).

2. **`split_multi_ops` — FP:** the pass replaces multi-output ops with
   split single-output ops using `run_node`, `operations.remove/insert`,
   and inner_fn patches (`torch_spyre/_inductor/split_multi_ops.py` at
   `a9316b3`). The `run_node`-inserted top-level TensorBox gets
   `register_users_of`'d; the *old* multi-output op's TensorBox may
   still be listed in `name_to_users[<what it used to read>]` after
   removal, a subset of the DCE-FP case.

3. **FN — the actual mechanism.** `register_users_of(result)` at
   upstream `torch/_inductor/graph.py:2141` (`register_users_of`
   defined at graph.py:1128–1136 in torch 2.13) walks only the
   top-level `TensorBox` returned by `run_node` — specifically it
   calls `value.get_read_names()` on each returned `TensorBox` and
   appends *that TensorBox* to `name_to_users[read_name]` for every
   name in that read-name set. It does NOT recursively enter
   `TensorBox.data.data` and register the internal ComputedBuffers
   the lowering produced. Consequence: any lowering path whose FX
   decomposition produces internal `ComputedBuffer`s that read a
   buffer name never registers those internal readers under that
   buffer name in `name_to_users`. This is not specific to
   `constant_pad_nd`; it applies to any lowering that decomposes into
   multiple IR-level ops that share a name-based read edge, wherever
   the top-level returned TensorBox is not itself the reader. Every
   pass in the table that lowers via `run_node` inherits this FN
   possibility for its internal readers.

4. **`insert_restickify` / `enforce_indirect_access_layout` — FP:**
   After these passes, a consumer's inner_fn is patched via
   `NameSwapHandler({old_name: new_restickify_name})`. The consumer's
   TensorBox is still in `name_to_users[old_name]` from lowering time,
   but its live `get_read_writes` no longer contains `old_name`. If
   `old_name` happens to be a constant we later dedup, this is an FP.
   In practice constants themselves are not the "old_name" that gets
   restickified — restickify targets user tensors between layouts —
   so this FP path is unlikely to matter for constant readers.

5. **`insert_post_mutation_restickify` — no FP for constants:** this
   pass targets slice-mutation ops (`hasattr(op, '_restickify_plan')`)
   which are `ComputedBuffer` mutation writes, not fill Pointwise
   buffers over constants. It inserts restickify buffers before/after
   mutation ops. Constants' `name_to_users` entries are not touched.

6. **`insert_bmm_padding` — measured FN.** Corrected from the earlier
   claim that its fill-Pointwise consumers were "registered fresh in
   `name_to_users`". They are not. The pass calls `lower_pad_sequence`
   (`torch_spyre/_inductor/pass_utils.py:1202–1290`) which invokes
   `graph_lowering.run_node(pad_fx)` on a single
   `torch.ops.aten.constant_pad_nd.default` FX node. That single
   `run_node` produces four IR operations inside the decomposition
   (documented in the `lower_pad_sequence` docstring at
   pass_utils.py:1215–1219):
    1. output-buffer allocation `ComputedBuffer`
    2. the `SpyreConstantFallback` fill constant
    3. a fill Pointwise `ComputedBuffer` that reads the constant
    4. a copy Pointwise `ComputedBuffer`
   By footnote 3, `register_users_of` sees only the top-level
   returned TensorBox for the whole `constant_pad_nd`, so
   `name_to_users[<constant_name>]` does NOT receive an entry for
   the fill Pointwise (item 3), which is the live reader of the
   constant. Section C measures this: 624 / 624 gold consumers were
   missing from `name_to_users[D]` across the sweep.

**Overall summary (corrected).** For duplicates produced by
`insert_bmm_padding` in this workload, `name_to_users[D]` at dedup
time contains neither the true consumer nor a general FP over the
true-consumer set — it typically holds the constant's own TensorBox
self-reference, or nothing that unwraps to a live operation.
`name_to_users` is therefore not a sound consumer source for this
pass under the current Torch 2.13 / torch-spyre lowering behavior.
This is a scoped, measured claim; it does not generalize to arbitrary
uses of `name_to_users` elsewhere in upstream Inductor.

## Batch-removal safety, redone at `a9316b3`

Same argument as `dedup-source-analysis.md §7`, updated for
`merge_provenance`:

```python
# Batched-removal sketch. Preserves ALL current per-duplicate work
# except the operations.remove(dup) call, which is deferred to Step 3.

dead_ids: set[int] = set()

for key, group in groups.items():
    if len(group) <= 1:
        continue
    canonical = group[0]
    for dup in group[1:]:
        _redirect_consumers(operations, dup, canonical)

        # Preserved verbatim from _drop_constant:
        D = dup.get_name()
        C = canonical.get_name()
        op_name = dup.get_operation_name()

        merge_provenance(
            [canonical, dup],
            canonical,
            pass_name="dedup_and_promote_constants",
            reason="duplicate constant",
        )
        # NOTE: no operations.remove(dup) here.
        V.graph.removed_buffers.add(D)
        V.graph.name_to_buffer.pop(D, None)
        V.graph.name_to_op.pop(op_name, None)
        extra_users = V.graph.name_to_users.pop(D, [])
        if extra_users:
            V.graph.name_to_users.setdefault(C, []).extend(extra_users)

        dead_ids.add(id(dup))

# --- Step 3: front-load surviving constants, filtering out dead dups. ---
survivors = [op for op in operations if id(op) not in dead_ids]
constants = [op for op in survivors if isinstance(op, SpyreConstantFallback)]
if not constants:
    operations[:] = survivors
    return
non_constants = [op for op in survivors if not isinstance(op, SpyreConstantFallback)]
operations[:] = constants + non_constants
```

Safety obligations against the exit invariants (see previous report §2):

1. **Constants front-loaded, original relative order preserved.** The
   rebuild filters `operations` (already topologically ordered), then
   partitions preserving order — identical to today.

2. **`SpyreConstantFallback` corresponding to a name in
   `removed_buffers` is absent from `operations` at exit.** Achieved
   by `id(dup) not in dead_ids`. Note: the check must be `id`, not
   `is not`, because `dead_ids` is a set. Identity check matches what
   `_redirect_consumers` already does inline (`op is dup or op is
   canonical`), which does not compare via `__eq__` either — safe.

3. **`operations.remove(dup)` was O(N).** Its removal is what buys us
   the wall-clock. The final `operations[:] = ...` is one O(N)
   pass regardless of `D`.

4. **Do earlier duplicates need to be absent from `operations` when
   later duplicates are processed?** Restated argument at `a9316b3`:
   `_redirect_consumers` scans every op and calls `get_read_writes`.
   For a still-present-in-list previous duplicate `dup1`:

   - `dup1 is dup2 or dup1 is canonical` is False → falls through the
     inline skip.
   - `dup1.get_read_writes()` returns an empty read set (constants
     have no inputs, inherited from `InputsKernel.get_read_writes` at
     upstream `torch/_inductor/ir.py:5716` — same call at 2.13).
   - `any(dep.name == D2 for dep in {})` is False → skipped.

   No corrupt patch. Adds one extra iteration per still-present
   previous dup; the outer `_redirect_consumers` per-duplicate cost
   grows by `O(number-of-previous-dups)`, which sums across the pass
   to `O(D²)` — trivially dwarfed by the `O(N)` per-iteration and
   ignored in the analysis. Acceptable.

5. **Later `_redirect_consumers` calls do not re-scan a `dead_ids`
   member as a candidate consumer** — same reason as (4): dead dups
   have empty read sets and fail the `any(dep.name == Dnext ...)`
   check.

6. **`merge_provenance` order.** Currently called once per duplicate.
   In the batched variant, still called once per duplicate before the
   `dead_ids.add`. Same semantics.

7. **`name_to_users[C]` fold order.** Currently folds one duplicate at
   a time in canonical-order-of-iteration. In the batched variant,
   same iteration order — identical result.

8. **`removed_buffers`, `name_to_buffer.pop`, `name_to_op.pop`.** All
   preserved verbatim.

Batch removal at `a9316b3` is safe under the pass's stated invariants
and under the two new observations at this SHA (merge_provenance and
the extra pre-dedup passes).

## Diagnostic instrumentation plan

Three artifacts land in `patches/`, all inert unless
`TORCH_SPYRE_DEDUP_DIAG=1`.

- **`patches/dedup_diagnostics.py`** — recorder module. Aggregates
  per-invocation sub-timers and per-duplicate `name_to_users` snapshots
  into a `DedupRecord`. atexit dump to `$SPYRE_DEDUP_DIAG_OUT`. Has
  a TensorBox-unwrap helper (`unwrap_tensorbox_to_op_name`) for the
  index comparison; failures are counted, never fatal.

- **`patches/dedup_diagnostics.patch`** — diff against
  `torch_spyre/_inductor/dedup_constants.py` at `a9316b3`. Adds
  aggregate `perf_counter_ns` counters around each hot region:

  - `grouping_ns` (Step 1)
  - `redirect_ns` (Step 2 outer for `_redirect_consumers`)
  - `get_read_writes_ns` (inside redirect)
  - `reads_probe_ns` (`any(dep.name == D ...)`)
  - `patch_inner_fn_ns`
  - `drop_ns` (Step 2 outer for `_drop_constant`)
  - `merge_provenance_ns`
  - `operations_remove_ns`
  - `bookkeeping_ns` (`removed_buffers`/`name_to_buffer`/
    `name_to_op`/`name_to_users` folds)
  - `front_load_ns` (Step 3)
  - `dedup_total_ns`

  And counts:

  - `n_ops_at_entry, n_constants, n_groups, n_groups_multi,
    n_duplicates`
  - `n_ops_scanned, n_get_read_writes_calls,
    n_get_read_writes_by_type, n_consumer_hits,
    n_operations_remove_calls`

  Per-duplicate blocks include the gold/name_to_users comparison:
  `gold_consumer_ops`, `nu_raw_entry_count`, `nu_unique_op_count`,
  `nu_true_positives`, `nu_false_positives`, `nu_false_negatives`,
  `nu_false_positive_ops`, `nu_false_negative_ops`,
  `nu_unwrap_failures`, `nu_consumer_types`. Cap of
  `SPYRE_DEDUP_DIAG_MAX_PER_DUPLICATE=10000` per invocation to bound
  JSON size.

- **`patches/run_dedup_diag.sh`** — sweep script. Todd's three points
  (H=8, Lq=512, Lk ∈ {1024, 4096, 8192}), three cold samples each,
  fresh `TORCHINDUCTOR_CACHE_DIR` per sample. Uses the existing
  `workload_harness.py`. Writes one JSON per sample under
  `$DATA_DIR/dedup-<Lq>x<Lk>-run<N>.json`.

- **`patches/analyze_dedup_diag.py`** — reads all JSONs and emits the
  Markdown tables required by Sections B and C of this report.
  Includes a headline verdict: is `n_false_negatives == 0` across the
  sweep?

### Perturbation control

The added timers are aggregate counters, not per-call events. Each
adds two `perf_counter_ns()` reads (~40 ns on modern CPUs) around
code paths that already spend microseconds or more. For the largest
measured point (`n_ops_scanned ≈ 1.1M`, `n_get_read_writes_calls ≈ 1.1M`)
the added overhead is at most ~90 ms — well under 1% of the ~225 s
dedup wall-clock. The `per_duplicate` recording adds one Python-level
dict per duplicate (~256 at the largest point) — cheap.

The gold-vs-name_to_users comparison is inside the diagnostic path
only. It does NOT run the linear scan a second time — it observes
the existing scan by having `_redirect_consumers` append hits to a
list under a keyword-arg. Zero extra passes over `operations`.

### One-time perturbation check

To verify the diagnostics do not distort the measurement, plan an
extra "diagnostics-off" run of the baseline point (Lq=512, Lk=1024)
on the same pod with `TORCH_SPYRE_DEDUP_DIAG=0` and
`TORCH_SPYRE_TIMING=1`. Compare `pass:...:dedup_and_promote_constants`
timing between the diag-off and diag-on runs. If they agree within
2%, treat the diagnostic runs as trustworthy proxies for the
wall-clock split.

## Unit-test plan

Add `tests/inductor/test_dedup_constants_more.py` (already staged in
`patches/`). Four tests, all against the current unmodified pass:

- `test_zero_consumer_duplicate` — asserts bookkeeping cleanup on
  dropped constants, and skips itself if the workload does not
  actually produce a zero-consumer duplicate.
- `test_many_consumer_duplicate` — three bmms sharing a padding
  constant; canonical must be read by more than one live buffer.
- `test_name_to_users_canonical_fold` — the canonical's
  `name_to_users` entry contains at least the pre-dedup users of the
  duplicates. Load-bearing for scratchpad planning.
- `test_provenance_merged` — canonical's `_spyre_prov_history`
  contains a `ProvenanceTransform` with
  `pass_name == "dedup_and_promote_constants"`.

All four should pass unchanged against `a9316b3`. If any fails, the
current behavior is different from what this document assumes —
investigate before proceeding.

Register the new file in
`tests/configs/torch_spyre_tests/inductor/` (existing
`test_dedup_constants_config.yaml` shows the format —
`unlisted_test_mode: mandatory_success`).

### Output-name latent bug

Separate observation. `_redirect_consumers` at `a9316b3` skips the
redirect when `D in V.graph.get_output_names()`, but the caller
still runs `_drop_constant` unconditionally. Consequence: an
output-name duplicate is removed from `operations`, gets its
`removed_buffers` / `name_to_buffer` / `name_to_op` /
`name_to_users` entries cleaned, and its provenance is merged into
canonical — but its consumers still emit `ops.load(D_name)` at
codegen time, which will fail.

Not part of this performance work. Reachability question: can a
`SpyreConstantFallback` (which has no inputs and represents a
compile-time constant fill value) ever be a graph output? A fresh
`torch.full(..., 0.0)` in the graph could conceivably be if the
compiled function returns it directly, but that's a pathological
program. Recommendation: file this as a separate defect (short
reproducer, or a note that we searched and could not construct one),
independent of the perf refactor.

## A vs E decision framework

Restate the two designs so the post-run decision is grounded in
identical criteria.

**Option A — use `V.graph.name_to_users[D]` as candidate index**

```python
def _redirect_consumers_via_index(operations, dup, canonical):
    D = dup.get_name(); C = canonical.get_name()
    if D in V.graph.get_output_names():
        return
    seen = set()
    for tb in V.graph.name_to_users.get(D, []):
        op = _unwrap(tb)                  # TensorBox → ComputedBuffer
        if op is None or id(op) in seen:
            continue
        seen.add(id(op))
        rw = op.get_read_writes()
        if not any(dep.name == D for dep in rw.reads):
            continue                       # FP filter
        if isinstance(op, ComputedBuffer):
            _patch_inner_fn(op, {D: C})
        else:
            raise AssertionError(...)
```

Complexity: `O(|name_to_users[D]|)` per duplicate + one
`get_read_writes` per candidate. On the current workload
`|name_to_users[D]|` is expected to be ~1 (one fill Pointwise per
padding constant); measurement will confirm.

Costs:

- Depends on upstream `name_to_users` staying populated across every
  pre-dedup pass — mitigated by the FN=0 argument in the mutation
  table.
- Requires TensorBox-unwrap; can fail on ReinterpretView / MultiOutput /
  DonatedBuffer intermediaries. Failures counted, not fatal.
- Depends on the FP filter to shed stale entries.

**Option E — build fresh local reverse index once at pass entry**

```python
def _build_reverse_consumer_index(operations):
    idx = defaultdict(list)               # buffer_name -> list[Operation]
    for op in operations:
        rw = op.get_read_writes()
        for dep in rw.reads:
            idx[dep.name].append(op)
    return idx

def dedup_and_promote_constants(graph):
    operations = graph.operations
    consumers_by_name = _build_reverse_consumer_index(operations)
    # groups = ...
    for key, group in groups.items():
        if len(group) <= 1: continue
        canonical = group[0]
        for dup in group[1:]:
            D = dup.get_name()
            for op in consumers_by_name.get(D, []):
                if op is dup or op is canonical: continue
                if isinstance(op, ComputedBuffer):
                    _patch_inner_fn(op, {D: canonical.get_name()})
                else:
                    raise AssertionError(...)
            _drop_constant_bookkeeping(op, dup, canonical)
            dead_ids.add(id(dup))
    # ... front-load rebuild
```

Complexity: `O(N)` scan once (with `get_read_writes` on every op,
same call as the current inner loop but only ONCE), then
`O(|consumers_by_name[D]|)` per duplicate. No per-candidate
`get_read_writes` filter needed — the index was built from live
reads.

Costs:

- One `O(N)` sweep at pass entry, always. On the current workload
  this is one `_redirect_consumers`-style scan; ~201.8 µs · N ≈ 220 ms
  at the largest measured point (Lq=1024, Lk=8192, N=4356). That's
  <0.1% of the current 225 s wall-clock at that point.
- No dependency on cross-pass `name_to_users` correctness. Robust to
  future compiler-pass additions.
- Simple correctness proof: the index is a materialization of the
  same `get_read_writes` calls the current algorithm makes; per-dup
  behavior is a subset. Batch removal semantics unchanged.
- The reverse index becomes stale as we patch inner_fns. Question to
  resolve during measurement: does the algorithm ever look up
  `consumers_by_name[X]` for an X we've already patched? A quick
  first-principles check: we build the index once for the buffer
  reads AT PASS ENTRY, then patch inner_fn to swap D → C for
  consumers of D. After patching, that consumer's live
  `get_read_writes` no longer contains D, but we never re-query
  `consumers_by_name[D]` — we've already processed D. When we later
  process another dup D2 (different value), we query
  `consumers_by_name[D2]`, and D2 is a different constant; a
  consumer's inner_fn was NOT swapped for D2. So the index entry for
  D2 is still valid at the time we consume it, unless the same
  consumer reads BOTH D and D2 — which is unlikely for padding
  constants (one fill per padded buffer) but not disallowed by the
  IR. The correctness of E depends on: **can a single
  ComputedBuffer read two different SpyreConstantFallback names**?
  For the padding-constant case at hand, no (each fill Pointwise
  reads exactly its own fill value). For a hypothetical general
  case, an implementation of E should still be correct because
  patching the same consumer twice with two different name-maps
  simply stacks two `NameSwapHandler`s in its `inner_fn` closure —
  each translates its own key. The stacked handlers are the
  same mechanism used elsewhere in torch-spyre (see
  `_rebuild_matmul` at `padding.py:151`, which stacks over any
  existing name-swap). So E is correct even under the general case.

**Decision axes to evaluate post-run:**

| axis                                              | A (name_to_users)                   | E (fresh local index) |
| ------------------------------------------------- | ----------------------------------- | --------------------- |
| Asymptotic complexity                             | `O(D · U)` + FP filter              | `O(N + Σ_D U_D)`      |
| Cost overhead at entry                            | 0                                   | one `O(N)` sweep      |
| Depends on upstream `name_to_users` freshness     | yes                                 | no                    |
| Depends on cross-pass `register_users_of` correctness | yes                             | no                    |
| TensorBox-unwrap complexity in the hot path       | yes (mitigated)                     | no                    |
| Correctness argument size                         | needs FN=0 empirical evidence + FP filter | one-page             |
| Robustness to future compiler-pass changes        | fragile                             | robust                |
| Maintainability                                   | knows upstream Inductor internals   | reads only local API |
| Testability                                       | need to add FN-detection assertion  | straightforward       |
| Wall-clock estimate at largest point (Lk=8192)    | ~<10 ms (n_users ≈ 1)               | ~220 ms (1 sweep)      |

The post-run decision is D — but the tilt in this framework matches
Todd's read: **E wins unless A's constant factor is at least an
order of magnitude better and FN=0 is confirmed empirically**.

## B. Measured cost decomposition

Sweep: three H=8 points, three cold samples each, executed on the
`tdeshane-compiler-timing-dev-v2` pod (RHEL 9.6, Python 3.12.13,
torch 2.13.0+cpu, torch-spyre at `a9316b381`). Raw records in
`data-diag/dedup-512x{1024,4096,8192}-run{1,2,3}.json`. Analyzer
output (medians) reproduced verbatim from `analyze_dedup_diag.py`:

**Wall-clock split (median ms per point):**

| point (Lq×Lk) | samples | total | grouping | redirect(scan) | get_read_writes | list_remove | merge_provenance | bookkeeping | front_load | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 512×1024      | 3 |   976.9 | 0.10 |  1.52 |   967.65 |  0.27 | 0.27 | 0.07 | 0.08 | 0.21 |
| 512×4096      | 3 | 15697.1 | 0.26 | 21.82 | 15568.04 |  3.21 | 1.54 | 0.32 | 0.34 | 0.82 |
| 512×8192      | 3 | 62189.4 | 0.49 | 84.62 | 61687.57 | 12.80 | 3.91 | 0.70 | 0.94 | 1.73 |

**Percent of dedup total:**

| point | grouping | redirect(scan) | get_read_writes | list_remove | merge_provenance | bookkeeping | front_load | other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 512×1024 | 0.0% | 0.2% | **99.1%** | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 512×4096 | 0.0% | 0.1% | **99.2%** | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| 512×8192 | 0.0% | 0.1% | **99.2%** | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

The wall-clock split lands in essentially the same shape at every
point: `get_read_writes` from inside `_redirect_consumers` is 99.1–
99.2% of dedup time; everything else is measurement noise. In
particular:

- **`operations.remove(dup)`** takes 0.27 / 3.21 / 12.80 ms at the
  three points — 0.02–0.03% of dedup total. The previously-suspected
  "second `O(N × D)` term" is real in the source but negligible in
  wall-clock. Batch removal as a standalone change saves at most
  ~13 ms out of ~62 s at the largest point.
- **`merge_provenance`** is 0.27 / 1.54 / 3.91 ms — even smaller.
  It must still be preserved in any refactor (correctness), but is
  not a performance signal.
- **Grouping + `reads_probe` + `patch_inner_fn` + `bookkeeping` +
  `front_load`** together are <1% at every point.

The measured coefficient `total_ms · 1000 / (N × D)`:

| point | N | D | N × D | median µs/(N·D) | ns per `get_read_writes` |
|---|---:|---:|---:|---:|---:|
| 512×1024 |  276 |  16 |    4,416 | **221.2** | ~226,900 |
| 512×4096 | 1092 |  64 |   69,888 | **224.6** | ~229,800 |
| 512×8192 | 2180 | 128 |  279,040 | **222.9** | ~227,900 |

The `study` fit was `t ≈ 201.8 µs × (N × D)`; the diag-on rerun sits
at ~222 µs. An earlier draft of this document attributed the ~10%
difference to overhead from the diagnostic timers. That was
plausible but not demonstrated. **Follow-up perturbation check**
(6 interleaved cold samples at Lq=512, Lk=1024,
data at `data-perturb/`) contradicts the timer-overhead hypothesis:

| variant  | dedup wall-clock (ms) per sample | median  |
|----------|----------------------------------|---------|
| DIAG-OFF | 979.0 / 955.4 / 973.2            | 973.2   |
| DIAG-ON  | 990.3 / 985.2 / 970.4            | 985.2   |

Same-environment DIAG-ON is only +1.23% slower than DIAG-OFF at the
median. Individual samples overlap across the two variants (the
lowest DIAG-ON of 970.4 ms is lower than two of the three DIAG-OFF
samples). The ~10% delta between the original study's 201.8 µs
coefficient and the diag sweep's ~222 µs coefficient is therefore
**not** attributable to the diagnostic timers. It is more likely
ordinary run-to-run / pod-state / interpreter variation across the
weeks between the two datasets. The per-call cost of
`ComputedBuffer.get_read_writes()` is remarkably stable at ~228 µs
regardless of graph size — as expected for a per-op
`extract_read_writes(inner_fn, size)` walk of a Pointwise body — and
this stability suggests that either coefficient is a defensible
estimate of the pre-refactor pass cost; do not read the ~10% gap as
evidence of any specific instrumentation cost.

## C. Consumer-index evidence

Gold set was captured by observing the current linear scan from
inside `_redirect_consumers`; the `V.graph.name_to_users[D]`
snapshot was taken BEFORE `_drop_constant` folded it into
`name_to_users[C]`. Both operate on the SAME dedup invocation, so
the comparison is head-to-head at each duplicate.

| point | dups | median gold consumers/dup | median NU raw/dup | median NU unique/dup | Σ TP | Σ FP | Σ FN | Σ unwrap fail | consumer types (count) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 512×1024 |  48 | 1 | 1 | 1 |   0 |  45 |  48 | 3 | TensorBox=48 |
| 512×4096 | 192 | 1 | 1 | 1 |   0 | 189 | 192 | 3 | TensorBox=192 |
| 512×8192 | 384 | 1 | 1 | 1 |   0 | 381 | 384 | 3 | TensorBox=384 |
| **total** | **624** | | | | **0** | **615** | **624** | **9** | TensorBox=624 |

**Verdict — `name_to_users` is not a sound consumer source for this
pass/workload under the current Torch 2.13 / torch-spyre lowering
behavior.**

Scoped claim. This is not a universal statement about `name_to_users`
elsewhere in Inductor; it is a statement about the specific pattern
`constant_pad_nd` → decomposed fill Pointwise → `SpyreConstantFallback`
reader produced by `insert_bmm_padding` on this workload, plus the
`register_users_of` behavior described in the mutation-table
footnote 3.

- `Σ TP = 0` — the current scan's actual consumers **never** appear
  in `V.graph.name_to_users[D]` for this workload. Not "rarely" —
  never.
- `Σ FN = 624` — every gold consumer (1 per dup, 624 total) is
  MISSING from `name_to_users`.
- `Σ FP = 615` — for 615 / 624 duplicates, `name_to_users[D]`
  contains exactly one entry pointing at an operation that does NOT
  read D. The remaining 9 are unwrap failures (TensorBox → ComputedBuffer
  fails).

**Why (source-level explanation).**

`insert_bmm_padding` at `torch_spyre/_inductor/padding.py:284` calls
`lower_pad_sequence`, which invokes `graph_lowering.run_node(pad_fx)`
on a `constant_pad_nd` FX node. `constant_pad_nd`'s decomposition
inside a single `run_node` produces four IR ops (from
`pass_utils.py:1215–1219`):

1. `ComputedBuffer` — output buffer allocation
2. `SpyreConstantFallback` — the fill constant `D`
3. `ComputedBuffer` — the fill Pointwise (whose `inner_fn` emits
   `ops.load(D)`)
4. `ComputedBuffer` — the copy Pointwise

`register_users_of(result)` at upstream `graph.py:2141` runs
**once**, on the TensorBox returned by `run_node` — which is the
final output TensorBox for the whole `constant_pad_nd`, not each
internal ComputedBuffer. `TensorBox.get_read_names()` returns the
read names of that top-level buffer; the fill Pointwise buffer (the
actual reader of D) never gets a `register_users_of` call and so
never enters `name_to_users[D]`.

What IS in `name_to_users[D]`: 615 of 624 entries are TensorBoxes
that unwrap to the ORIGINAL constant Buffer itself (its own name is
in its `get_read_names()` — see upstream `ir.py:5278`,
`Buffer.get_read_names → OrderedSet([self.get_name()])`). That is,
the constant TensorBox lists itself as a "user of itself" at
lowering time. The 9 unwrap failures are TensorBoxes whose
`.data.data` is not a ComputedBuffer — likely intermediate
`ReinterpretView` / `MultiOutput` nodes from the `constant_pad_nd`
decomposition; those also do not point at the fill Pointwise.

To make Option A work, we would need `run_node` (or
`register_users_of`) to walk into `constant_pad_nd`'s IR
decomposition and register every internal ComputedBuffer that reads
the constant. That is an upstream Inductor change, not a torch-spyre
change, and it would need to be justified against the whole
population of readers, not just this pass. Out of scope.

## D. A-vs-E engineering decision

**Recommendation: Option E (fresh local reverse index built once at
pass entry), plus batch removal.**

Filled-in decision table (updated with measured numbers):

| axis                                              | A (name_to_users)                  | E (fresh local index)              |
| ------------------------------------------------- | ----------------------------------- | ---------------------------------- |
| Asymptotic complexity                             | `O(D · U)` + FP filter              | `O(N · f) + O(Σ_D U_D)`            |
| Cost overhead at entry                            | 0                                   | one `O(N)` sweep, ~228 µs · N      |
| False-negative rate on the measured workload      | **624 / 624 (100%)**                | 0 by construction                  |
| Depends on upstream `name_to_users` freshness     | yes — and freshness is provably not maintained by `run_node` for decomposed FX nodes | no |
| Depends on cross-pass `register_users_of` correctness | yes                             | no                                 |
| TensorBox-unwrap complexity in the hot path       | yes (mitigated); 9 unwrap failures / 624 in the measurement | no |
| Correctness argument size                         | requires an upstream Inductor change to `register_users_of` OR a workload-specific search of `name_to_users` fallback list | one paragraph — the index is a materialization of the same `get_read_writes` calls the current algorithm makes |
| Robustness to future compiler-pass changes        | fragile — any new pass that adds a decomposed lowering with an internal constant reader inherits the same FN                | robust                             |
| Wall-clock estimate at largest point (Lk=8192)    | infeasible without the upstream fix | one `O(N)` sweep ≈ 2180 × 228 µs ≈ **497 ms**, plus O(D) for the redirects ≈ ~30 ms; total ≈ ~530 ms |

Option A is not viable on this workload without an upstream
`register_users_of` change. Even if we shipped the FP-filter-only
variant (fall back to the linear scan when `name_to_users[D]`
misses), the fallback path would fire 100% of the time on this
workload — it would BE the linear scan.

Option E delivers the intended `O(N × D) → O(N)` collapse with no
upstream dependencies. Batch removal composes trivially with E (the
dead-ids set is populated in the same loop) and preserves
`merge_provenance` semantics unchanged.

## E. Predicted new complexity

With Option E + batch removal at `a9316b3`:

```text
build local reverse index:  O(N · f_grw)          f_grw ≈ 228 µs per op
                                                   (measured, ComputedBuffer path)
redirect consumers:         O(Σ_D U_D)             Σ U_D == D on this workload
                                                   (1 gold consumer per dup)
bookkeeping (per dup):      O(1)                   merge_provenance, dict pops,
                                                   name_to_users fold
batch removal (Step 3):     O(N)                   one filter+partition rebuild

overall wall-clock ≈ N · f_grw  +  D · (c_patch + c_bookkeeping)  +  N · c_filter
```

Predicted wall-clock per point:

| point | N | D | N · f_grw | D · (patch + bookkeeping) | total predicted | current measured | ratio |
|---|---:|---:|---:|---:|---:|---:|---:|
| 512×1024 |  276 |  16 |   ~63 ms | 16 · ~40 µs ≈ 0.6 ms |   ~64 ms |    977 ms | **~15×** |
| 512×4096 | 1092 |  64 |  ~249 ms | 64 · ~40 µs ≈ 2.6 ms |  ~252 ms | 15,697 ms | **~62×** |
| 512×8192 | 2180 | 128 |  ~497 ms | 128 · ~40 µs ≈ 5.1 ms | ~503 ms | 62,189 ms | **~123×** |

The `40 µs` per-dup cost is a conservative sum of `merge_provenance`
(median ~30 µs at Lk=8192: 3908 µs / 128), `patch_inner_fn` (median
~5 µs), and dict operations. Filter+partition at the end is one
`O(N)` list pass, small compared to the `f_grw · N` scan.

Predicted absolute speedup grows with `D` because we eliminate a
D-fold repetition of the same `O(N · f_grw)` work. At the largest
point, the prediction is a **123× speedup** (62 s → 0.5 s). Do NOT
promise 123× — measure it after landing E. The prediction only
serves as a sanity check that the algorithmic change is worth
doing.

Note that the prediction assumes `f_grw` stays at ~228 µs when we
call it in a single sweep at pass entry rather than nested in a
per-duplicate scan. This is expected — the inner_fn walk is
deterministic — but should be verified in the first measurement of
the E implementation.

## F. Exact next implementation experiment

**Goal.** Replace the O(N × D) consumer scan in
`_redirect_consumers` with a single O(N) build of a local
`consumers_by_name` dict at the top of
`dedup_and_promote_constants`, and defer per-duplicate
`operations.remove(dup)` calls to a single Step 3 filter+partition
rebuild.

**Scope.** One file: `torch_spyre/_inductor/dedup_constants.py`.
Estimated diff: +30 / −10 lines.

**Preserves (correctness obligations):**

- Grouping key `(value, dtype, device)` and canonical selection
  (`group[0]`) unchanged.
- `merge_provenance([canonical, dup], canonical, pass_name=...)`
  called once per duplicate before the duplicate is scheduled for
  removal, identical to today's `_drop_constant`.
- `V.graph.removed_buffers.add(D)`,
  `V.graph.name_to_buffer.pop(D, None)`,
  `V.graph.name_to_op.pop(op_name, None)`, and the
  `name_to_users[D] → name_to_users[C]` fold — all preserved,
  same order.
- Output-name skip (`if D in V.graph.get_output_names(): return`)
  preserved. The latent bug in the current handling of that skip
  path (removes dup but skips redirect) is NOT touched by this
  refactor; it remains a separate defect.
- Non-`ComputedBuffer` consumer raises `AssertionError` — preserve.
- Final `operations[:] = constants + non_constants` order —
  preserve, filtered via `id(dup) not in dead_ids`.

**Test plan.**

1. `tests/inductor/test_dedup_constants.py` — the five existing
   tests must pass.
2. `tests/inductor/test_dedup_constants_more.py` (this phase adds
   these):
    - `test_zero_consumer_duplicate` — skipped-if-not-reproducible
      today; if the E implementation produces a zero-consumer dup,
      it should still cleanly remove and fold.
    - `test_many_consumer_duplicate` — canonical read by more than
      one live ComputedBuffer.
    - `test_name_to_users_canonical_fold` — canonical's
      `name_to_users` entry contains at least the pre-dedup users.
    - `test_provenance_merged` — canonical carries a
      `ProvenanceTransform` with
      `pass_name == "dedup_and_promote_constants"`.
3. `tests/inductor/test_padding.py::test_padding_constants_deduped`
   — end-to-end correctness (torch.testing.assert_close of Spyre
   vs CPU).
4. `pre-commit run --all-files` — style/lint.

**Measurement plan.** Same three points, same pod:

- Run `run_dedup_diag.sh` first on the E branch to capture the
  same DedupRecord shape post-change. Expected: `n_ops_scanned`
  drops from `N × D` to ~`N`; `n_get_read_writes_calls` drops
  similarly.
- Also run the study's plain `run_sweep.sh` (no dedup diag) to
  compare against the phase-1 dataset directly.
- Verdict: dedup wall-clock at Lk=8192 should drop from ~55 s
  (study) / ~62 s (diag-on) to well under 1 s.

**Success criterion:**

- All tests pass.
- `dedup_and_promote_constants` wall-clock at (H=8, Lq=512,
  Lk=8192) < 2 s (target: <1 s; hard ceiling: <5 s).
- The measured/predicted-model consistency check: post-change
  wall-clock ≈ `N · f_grw + O(D)`; if it is materially higher,
  investigate before merging.

**Explicitly out of scope for this experiment:**

- Option A (`name_to_users`) — proven dead in section D.
- Any upstream Inductor change (e.g. teaching `register_users_of`
  to walk decomposed lowerings).
- Optimization of `optimize_restickify_locations` or
  `_maybe_scratchpad_planning` — separate investigations
  (findings.md §9 tracks them).
- Fixing the output-name skip bug — noted separately in section A.
- Caching `get_read_writes()` more aggressively — subsumed by E
  (which calls it N times, not N × D times).

Land as **one commit** (algorithm change + batch removal folded
together). Rationale in the commit message: they are already
coupled in the design — the local index and the dead-ids set are
populated in the same loop; separating them would either require
maintaining two loops or leaving `operations.remove(dup)` as an
O(N × D) tail on an otherwise O(N) pass. Commit message must cite
this phase-2 report by path and SHA.

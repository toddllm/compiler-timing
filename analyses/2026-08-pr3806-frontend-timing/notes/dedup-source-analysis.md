# `dedup_and_promote_constants` — Source-Level Analysis

Scope note. This is a source-level companion to `notes/findings.md`. It
concerns *only* `dedup_and_promote_constants` and the code it touches.
It does not investigate `dxp_standalone`, SDSC backend behavior, or any
other pre-scheduling pass. It is a report; it makes no code changes.

Source tree read: local torch-spyre checkout at
`/Users/tdeshane/multi-spyre-testing/repos/torch-spyre` on branch
`tdeshane/async-broadcast-work-candidate-20260622` at `0e8f7f257`
("spyre_ccl: real async broadcast Work handle"). Local PyTorch reference
under `/Users/tdeshane/dt-inductor.1/pytorch/torch/_inductor/`. See §13
for the pipeline-order discrepancy with the timing-boundary map.

---

## 1. Executive Summary

The pass in `torch_spyre/_inductor/dedup_constants.py` does three
things:

1. Group `SpyreConstantFallback` ops by `(value, dtype, device)`.
2. For every duplicate `dup` in a group, walk every op in
   `graph.operations`, call `op.get_read_writes()`, and if the op reads
   `dup`, patch its `inner_fn` with a `NameSwapHandler` so it reads
   the canonical name instead. Then `operations.remove(dup)` and clean
   up graph bookkeeping.
3. Move surviving constants to the head of `operations`.

Two constant-factor sources of repeated work dominate the pass:

- **Consumer discovery** (`_redirect_consumers`, lines 51-78 of
  `dedup_constants.py`) is `O(N)` in `|operations|` per duplicate; per
  op it calls `op.get_read_writes()` which is uncached on
  `ComputedBuffer` and re-runs `extract_read_writes` (a MockHandler
  walk of `inner_fn`) every time. This gives `O(N · D)` for the pass
  before adding the read-writes cost per op.
- **Duplicate removal** (`_drop_constant`, lines 81-99) calls
  `operations.remove(dup)`, a linear scan of a Python list, once per
  duplicate. That adds another `O(N · D)`.

The measured fit `t ≈ 201.8 µs × N × D` and the H-out-of-sample
prediction error under 2.2% are consistent with both terms being
present. The 201.8 µs coefficient is dominated by the per-op
`get_read_writes` call (walking a Pointwise `inner_fn`), not by the
list-remove overhead.

`GraphLowering.name_to_users` already indexes buffer name →
`TensorBox` consumers and is populated at lowering time for every
`ops.load(name)` in a Pointwise inner_fn. `SpyreConstantFallback`
readers do go through that path (see §6). It is a plausible substitute
for the full-`operations` scan in `_redirect_consumers`, with two
caveats worth verifying empirically before committing: (a) it can
over-report consumers after upstream `NameSwapHandler` rewrites (e.g.
`insert_restickify`), so a `get_read_writes`-based read check is still
needed on the *filtered* candidate set; and (b) its consumer type is
`TensorBox`, and dedup currently patches the `ComputedBuffer` behind
the `TensorBox.data.data` — the mapping is straightforward but a
correctness constraint to preserve.

Recommended next step: a narrowly-scoped, source-level proof that
`name_to_users[D]` (after `TensorBox → StorageBox → ComputedBuffer`
unwrapping) is a *superset* of what `_redirect_consumers` currently
finds; then replace the scan with an index lookup + a per-candidate
`get_read_writes` filter. Batch-remove duplicates as part of the same
change since one already dominates the other in the current
measurements and separating them costs an extra sweep. Concrete
milestone in §12.

---

## 2. Current Algorithm, Step by Step

Full source: `torch_spyre/_inductor/dedup_constants.py` (145 lines).

**Entry** (`dedup_and_promote_constants`, line 102). Takes a
`GraphLowering`. Reads `graph.operations` (a `list[Operation]` in
topological order — see `torch_spyre/_inductor/passes.py:303-305`).

**Step 1: group by identity key** (lines 116-122).

```python
groups: dict[tuple, list[SpyreConstantFallback]] = {}
for op in operations:
    if not isinstance(op, SpyreConstantFallback):
        continue
    key = _constant_key(op)
    groups.setdefault(key, []).append(op)
```

`_constant_key` (line 27) is
`(op.constant_args[0], layout.dtype, normalised_device)`.
`constant_args[0]` is the Python-level scalar value passed to
`SpyreConstantFallback.__init__` at lowering time (see
`torch_spyre/_inductor/lowering.py:838-842` and `ir.py:110-138`).
Device is normalized so `spyre` and `spyre:0` collide correctly.
`layout.size == []` for every constant (they are 0-dim); size is not in
the key.

**Step 2: dedup** (lines 125-131). For each group with more than one
member, `canonical = group[0]` (first-in-topological-order). For every
other `dup`:

```python
_redirect_consumers(operations, dup, canonical)
_drop_constant(operations, dup, canonical)
```

`_redirect_consumers` (lines 51-78):

```python
D = dup.get_name()
C = canonical.get_name()
if D in V.graph.get_output_names():
    return
for op in operations:
    if op is dup or op is canonical:
        continue
    rw = op.get_read_writes()
    if not any(dep.name == D for dep in rw.reads):
        continue
    if isinstance(op, ComputedBuffer):
        _patch_inner_fn(op, {D: C})
    else:
        raise AssertionError(...)
```

`_patch_inner_fn` (lines 39-48) wraps the consumer's `inner_fn` in a
closure whose body sets `V.ops` to a `NameSwapHandler({D: C})` (see
`torch_spyre/_inductor/insert_restickify.py:66-77`) for the duration
of the inner call, and invalidates the `ComputedBuffer.get_default_sizes_body`
cache on that consumer. The `NameSwapHandler.load` (line 76-77)
substitutes the constant name at the `ops.load(name, index)` boundary.

`_drop_constant` (lines 81-99):

```python
operations.remove(dup)               # O(|operations|)
V.graph.removed_buffers.add(D)
V.graph.name_to_buffer.pop(D, None)
V.graph.name_to_op.pop(op_name, None)
extra_users = V.graph.name_to_users.pop(D, [])
if extra_users:
    V.graph.name_to_users.setdefault(C, []).extend(extra_users)
```

Note the last two lines: `name_to_users[D]` is folded into
`name_to_users[C]`. Later passes (scratchpad planning specifically —
see the comment on line 94) rely on `name_to_users[C]` seeing the
full set. This behavior is a load-bearing invariant for any
replacement (see §6).

**Step 3: front-load surviving constants** (lines 134-140).

```python
constants     = [op for op in operations if isinstance(op, SpyreConstantFallback)]
non_constants = [op for op in operations if not isinstance(op, SpyreConstantFallback)]
operations[:] = constants + non_constants
```

`operations[:] = ...` is one bulk rewrite — the pass already replaces
the list in place at the end. That fact matters for §7.

**Exit invariants** the pass promises to downstream passes:

- Every surviving `SpyreConstantFallback` in a duplicate group is
  unique by `(value, dtype, device)`; other groups may still exist
  with the same key on different `(value, dtype, device)` tuples.
- Every consumer that used to `ops.load(dup_name)` now
  `ops.load(canonical_name)` at codegen time (via the
  `NameSwapHandler`-wrapped `inner_fn`).
- `V.graph.name_to_buffer`, `V.graph.name_to_op`,
  `V.graph.name_to_users` no longer contain a key for any dropped
  duplicate; `V.graph.removed_buffers` contains every dropped
  duplicate name.
- Every surviving `SpyreConstantFallback` in `graph.operations`
  precedes every non-constant. Relative order among constants and
  among non-constants is preserved.

---

## 3. Important Data Structures and Invariants

- `graph.operations : list[Operation]` — the authoritative
  topologically-ordered op list at pre-scheduling time. Downstream
  passes iterate it (`torch_spyre/_inductor/passes.py:343-360`) and
  the scheduler consumes it after the pass pipeline exits.
- `graph.name_to_buffer : dict[str, ir.Buffer]` — buffer name →
  Buffer, populated by `register_buffer` at lowering time.
- `graph.name_to_op : dict[str, ir.Operation]` — operation name →
  Operation, populated by `register_operation`.
- `graph.name_to_users : defaultdict[str, list[ir.IRNode]]` —
  buffer name → list of consumer `TensorBox` IRNodes. Populated by
  `GraphLowering.register_users_of` at each `run_node` call
  (`torch/_inductor/graph.py:973-984`, invoked at `graph.py:1822`).
  Values are pushed by `TensorBox.get_read_names()` (which delegates
  to the inner data's read-name set, ultimately populated by walking
  a Pointwise `inner_fn` via `OpCounterCSE`, `ir.py:1000-1046`).
- `graph.removed_buffers : OrderedSet[str]` — buffers dropped from
  codegen consideration.
- `SpyreConstantFallback` — subclass of `ir.ExternKernel` /
  `InputsKernel` / `OperationBuffer`. `should_allocate() → False`,
  `get_mutation_names() → []`, no unbacked symbol defs. `inputs = []`,
  so its `get_read_writes()` (inherited from `InputsKernel`,
  `ir.py:5297`) returns an empty read set and a single StarDep write
  on itself — cheap, `O(1)`.
- `ComputedBuffer.get_read_writes()` — `ir.py:4558-4577`. When
  `self.data` is a `Pointwise` / `Reduction` / `Scan` / `Sort`, it
  calls `extract_read_writes(get_store_function, sizes)`. That runs
  the store function (which wraps `inner_fn`) under a MockHandler and
  records every `ops.load(name, ...)`. **This call is not cached.**
- `ComputedBuffer.get_default_sizes_body()` — `ir.py:4676`, `@cache_on_self`.
  Cached. `dedup_constants._patch_inner_fn` invalidates this cache on
  each patched consumer (line 48).
- `NameSwapHandler` — `torch_spyre/_inductor/insert_restickify.py:66`.
  A `WrapperHandler` that rewrites `ops.load(name, index)` to
  `ops.load(name_map.get(name, name), index)`. Composable with other
  `NameSwapHandler`s (each patched `inner_fn` is a new closure that
  installs its own map on entry).

Invariants relied on by the pass:

- `operations` is in topological order at entry (established by
  `passes.py:303-305`, and by every earlier pass preserving order).
- Every `SpyreConstantFallback` was registered with `register_buffer`
  and `register_operation` at lowering time, so `name_to_buffer`
  and `name_to_op` contain them.
- No two `SpyreConstantFallback` instances share a buffer name
  (unique via `register_buffer`).
- `SpyreConstantFallback` instances are compared by identity within
  the pass (`op is dup or op is canonical`), not by `__eq__`.

---

## 4. Source-Derived Complexity Model

Let

- `N = |graph.operations|` at pass entry
- `C = |{op ∈ operations : isinstance(op, SpyreConstantFallback)}|`
- `D = C − G` where `G` is the number of dedup groups
  (empirically `D ≈ 256` at Lq=1024, Lk=8192; `C` is slightly
  larger — the report equates them for the fit).
- `Kᵢ` = number of `ops.load` calls in op `i`'s `inner_fn`
  (roughly the number of reads; usually 1-3 for Pointwise buffers).
- `Uᴰ` = the actual consumer count of dup name `D`, which is 1 for
  the typical restickify-fed consumer here.

**Step 1 (grouping):**

```
for op in operations: ...       O(N)
groups.setdefault(...)          O(1) hash on the key tuple; hashing
                                the Python scalar in constant_args[0]
                                is O(1) for a float.
                                            → O(N)
```

**Step 2 (dedup):** the outer loop runs `D` times. For each duplicate:

```
_redirect_consumers:
    output-name check           O(|outputs|)  ≪ N
    for op in operations:       O(N)
        get_read_writes         per op — cost depends on op type.
                                For SpyreConstantFallback / ExternKernel
                                (InputsKernel): O(1).
                                For ComputedBuffer with Pointwise data:
                                O(Kᵢ · f(inner_fn)) where f is the cost
                                of running inner_fn once under MockHandler.
                                Not cached.
        `any(dep.name == D ...)` O(|rw.reads|) ≤ O(Kᵢ)
        _patch_inner_fn         only on real hits, so ≤ Uᴰ times per dup.
                                O(1) closure allocation + O(1) cache clear.
_drop_constant:
    operations.remove(dup)      O(N)
    dict/set/defaultdict ops    O(1) each; the extend on
                                name_to_users[C] adds ≤ |name_to_users[D]|
                                which is ≤ Uᴰ.
```

Summing over the `D` duplicates:

```
Step 2 total ≈ D · ( N + Σᵢ get_read_writes(opᵢ) + N )
            = D · ( 2N + Σᵢ get_read_writes(opᵢ) )
            + D · O(Uᴰ)   [patch + name_to_users merge]
```

Two `D · N` terms — one from the operation scan in
`_redirect_consumers`, one from `operations.remove` in `_drop_constant`.
They are the same asymptotic order. The 201.8 µs coefficient absorbs
both plus the per-op `get_read_writes` cost.

**Step 3 (front-load):** two list comprehensions + one `operations[:] = ...`,
total `O(N)`.

**Overall pass:** `O(D · N)` plus a `D · (Σᵢ get_read_writes(opᵢ))` term
that behaves like a scaled `D · N` on this workload. Matches the fit
in §5 of `findings.md`.

**Cost sources not previously called out.** All present, none of them
individually dominant here but each worth naming for the record:

- `_patch_inner_fn` allocates a new closure per patched consumer and
  invalidates the sizes cache; `get_default_sizes_body` will
  re-execute on next access. This lands on downstream passes, not on
  the dedup pass timing itself.
- The `not any(dep.name == D for dep in rw.reads)` walk is `O(|reads|)`
  per op — small for Pointwise buffers, but multiplied by `N · D`.
- Grouping key uses a tuple hash including a Python `torch.device`
  and `torch.dtype`; both are cheap but non-zero, and this is
  `N` calls not `N · D` so it does not scale badly.
- `name_to_users` merge in `_drop_constant` iterates
  `name_to_users[D]` values (`≤ Uᴰ`). Not a scaling concern.
- No hidden repeated work in `_constant_key` (single dict/tuple
  lookups).

---

## 5. Why the Measured Scaling Happens

Two `O(N)` operations per duplicate, times `D` duplicates, gives
`O(N · D)`. The fit `t ≈ 201.8 µs · N · D` fits a single linear
coefficient across nine H=8 points spanning `N · D` from ~1k to ~1M —
a ~1000× range. It also predicts the H=16 and H=32 points at
`Lq=512, Lk=1024` within −1.0% and −2.2% respectively. Two facts make
this convincing:

- The H-axis is *independent* of the Lq/Lk axis. The out-of-sample
  H points sit near `N · D = 17,536` and `69,888`, values already
  covered on the Lq/Lk axis. That the same coefficient fits both
  axes without refitting confirms the model does not accidentally
  encode Lk-specific structure.
- The near-linear scaling of duplicates with operations for this
  workload (`D/N ≈ 1/17`) makes the product look quadratic in graph
  size, but the underlying cost model in the source is a product of
  two independent quantities. A workload with the same `N` but very
  few dup groups would sit far below this line.

The 201.8 µs coefficient absorbs three per-op costs — the
`for op in operations` scan overhead, the `get_read_writes()` call
(the dominant contributor), and the `operations.remove(dup)` inner scan.
Splitting the coefficient into those pieces would require the
instrumentation in §11.

---

## 6. Consumer Lookup / `name_to_users` Analysis

**What does `name_to_users` map, and how is it populated?**

`GraphLowering.name_to_users : defaultdict[str, list[ir.IRNode]]`
is initialized at `torch/_inductor/graph.py:410` and mutated in
exactly one place upstream: `register_users_of` at
`graph.py:973-984`. For each `TensorBox` in the return value of a
`run_node`, and for each name in that `TensorBox.get_read_names()`,
it appends the `TensorBox` to `name_to_users[read_name]`.

`TensorBox.get_read_names()` unwraps to `data.data.get_read_names()`.
For a Pointwise-backed `ComputedBuffer`, that returns the set of
buffer names its `inner_fn` calls `ops.load(name, ...)` on
(collected by `OpCounterCSE`, `ir.py:1000-1046`).

**Does a `SpyreConstantFallback` reader show up in `name_to_users`?**

Yes. `lower_full` at `torch_spyre/_inductor/lowering.py:838-853`
creates a `SpyreConstantFallback`, calls `scalar.make_loader()` (which
resolves to `Buffer.make_loader` at `ir.py:4383-4392`, returning a
closure that emits `ops.load(self.name, indexer(index))`), and wraps
it inside a Pointwise's `inner_fn`. That Pointwise gets realized as
a `ComputedBuffer` whose read-name set contains the constant's name.
The outer `TensorBox` is registered by `register_users_of` on the
next line of graph.py:1822, so
`name_to_users[constant_name].append(that_tensorbox)`.

The `pad_sequence` path (`torch_spyre/_inductor/coarse_tile.py:970-985`
and the constants created by `insert_bmm_padding`) follows the same
pattern.

**Is `name_to_users` authoritative at the point where
`dedup_and_promote_constants` runs?**

Not quite. Between lowering and dedup, several passes have run
(pipeline in this checkout: `deadcode_elimination`, `split_multi_ops`,
`propagate_spyre_tensor_layouts`, `validate_ops`,
`optimize_restickify_locations`, `finalize_layouts`,
`insert_restickify`, `insert_bmm_padding`). Some of them mutate the
graph:

- `deadcode_elimination` (`torch_spyre/_inductor/deadcode_elimination.py:97`)
  calls `operations.remove(op)` on dead ops. It does NOT update
  `name_to_users`, but a dead op reads live buffers, not the other
  way around — a stale `name_to_users` entry would only be a *dead
  consumer* still listed as a user of a live constant. That over-reports
  consumers but is harmless if the replacement also filters via
  `get_read_writes`.
- `insert_restickify` (`torch_spyre/_inductor/insert_restickify.py`)
  inserts new restickify buffers between constant readers and their
  consumers, patches the consumer's `inner_fn` with a `NameSwapHandler`
  (line 174-178), and calls `graph_lowering.run_node(restick_fx_node)`
  (line 129). The `run_node` call triggers `register_users_of` for the
  new restickify TensorBox, so `name_to_users[constant_name]` gets a
  new entry — the restickify buffer as a user of the constant.
  However, the *old* consumer TensorBox is still in
  `name_to_users[constant_name]`, even though after the name-swap
  its `inner_fn` no longer emits `ops.load(constant_name)`.
- `split_multi_ops` — does it mutate `name_to_users`? Yes indirectly:
  it calls `gl.operations.remove(buf)` (line 428) and inserts new
  ops via `operations.index/insert` (line 679), but appears to
  update `env` from `name_to_users` rather than write to it.
- `optimize_restickify_locations` — reads only, no known mutations.
- `finalize_layouts`, `validate_ops`, `insert_bmm_padding` — I did
  not check every line, but grep found no writes to `name_to_users`
  from any torch-spyre pass other than `dedup_constants` itself and
  `scratchpad/graph_editor.py` (which runs later, after dedup).

**Consequence for using `name_to_users` in dedup:**

- `name_to_users[D]` is a *superset* of the current consumers of
  the constant `D` (may over-report after `insert_restickify` and
  after `deadcode_elimination` — both list a `TensorBox` that used
  to read `D` but no longer does).
- The current `_redirect_consumers` gets the exact set because it
  re-derives reads from each op's live `inner_fn` via
  `get_read_writes`. Any replacement using `name_to_users` MUST
  either
  (a) still call `get_read_writes` on each candidate to filter
      out stale entries, or
  (b) prove that stale entries are safely no-op-patched (patching an
      `inner_fn` that no longer reads `D` is a no-op: the
      `NameSwapHandler` translates only when `ops.load(D, ...)` is
      seen, which no longer happens).

**Option (b) is nearly correct but not free.** The `_patch_inner_fn`
call has two side effects that are not no-ops on a stale consumer:

1. It replaces `consumer.data.inner_fn` with a new closure — that is
   still semantically equivalent (the new closure just installs an
   inert `NameSwapHandler` before delegating), but each such patch
   adds a wrapper layer that runs on every subsequent codegen call.
   For a hot consumer that gets patched many times across multiple
   dedup groups, this is a real (but small) cost.
2. It calls `ComputedBuffer.get_default_sizes_body.clear_cache(consumer)`.
   Invalidating a cache on a consumer that would not have benefited
   from the patch is wasted work.

The safer strategy is (a): use `name_to_users[D]` as the *candidate
set* and filter with `get_read_writes`. Candidate-set size in this
workload is `Uᴰ ≈ 1` (each constant has one real consumer, typically
a restickify buffer), so the filter is cheap. Total cost per
duplicate drops from `O(N)` to `O(|name_to_users[D]|)` plus a single
`get_read_writes` call per candidate — a ~two-orders-of-magnitude
reduction at the largest measured workload.

**Type-mapping caveat.** `name_to_users[D]` values are `TensorBox`
instances. `_patch_inner_fn` currently expects a `ComputedBuffer`
`Operation`. The mapping is `TensorBox → StorageBox → ComputedBuffer`
via `.data.data` (same pattern used in
`torch_spyre/_inductor/insert_restickify.py:100-104`). Whether the
mapping always terminates at a `ComputedBuffer` for our case is
worth checking during implementation — some consumers may be
`MultiOutput` or `ReinterpretView` intermediaries, and the current
`_redirect_consumers` raises `AssertionError` on non-`ComputedBuffer`
readers (line 75), so that constraint is already in force.

**Other candidate indexes.** No index in `torch/_inductor/graph.py`
maps *from a name to Operations that consume it* more directly than
`name_to_users`. `V.graph.buffers`, `V.graph.name_to_buffer`, and
`V.graph.name_to_op` are producer-side; only `name_to_users` is
consumer-side. Building a Buffer→consumers dict inside the pass by
scanning `operations` once (O(N) with one `get_read_writes` per op)
and then dedup'ing against it would give the same asymptotic
improvement as `name_to_users`, at the cost of one extra `O(N)`
sweep at pass entry — worth considering if `name_to_users`'
staleness turns out to require rework.

---

## 7. Duplicate Removal Analysis

**What does the pass promise about the operations list at exit?**
Two things (see §2 exit invariants):
- Surviving order: constants first, in original relative order among
  constants; non-constants after, in original relative order among
  non-constants.
- No `SpyreConstantFallback` in the list corresponds to a name in
  `graph.removed_buffers`.

Step 3 already writes `operations[:] = constants + non_constants` in
bulk. Batch removal is *already how the pass finishes*. The
`operations.remove(dup)` calls in Step 2 are redundant with Step 3 in
the sense that Step 3's list comprehensions would exclude a dropped
`dup` if it were still present — because a `dup` is a
`SpyreConstantFallback` and Step 3 rebuilds the list from a filter,
the dropped instances would be excluded automatically if they were
tagged somehow.

**Object-identity vs value-equality.** `SpyreConstantFallback` is an
`ir_dataclass(frozen=False)` (see `ir.py:4293`, `4519`, `4293`,
combined with `utils.py:3352`). Default `dataclass(frozen=False,
eq=True)` generates a field-based `__eq__` and sets `__hash__ = None`.
Two facts:
- Every instance has a unique `self.name` field assigned by
  `register_buffer`, so field-based `__eq__` still distinguishes any
  two distinct instances. `operations.remove(dup)` finding a
  same-identity match is guaranteed.
- Instances are unhashable, so we cannot use `set()` for a batch
  removal set. Use `id(op)` as the key (matching the pass's own
  `op is dup or op is canonical` identity checks in
  `_redirect_consumers`).

**Batch-removal safety.** Replace

```python
for dup in group[1:]:
    _redirect_consumers(operations, dup, canonical)
    _drop_constant(operations, dup, canonical)
```

with, in outline:

```python
dead_ids = set()                                # id(op) values to remove
for key, group in groups.items():
    if len(group) <= 1: continue
    canonical = group[0]
    for dup in group[1:]:
        _redirect_consumers(operations, dup, canonical)
        # bookkeeping only, no operations.remove:
        D, C = dup.get_name(), canonical.get_name()
        V.graph.removed_buffers.add(D)
        V.graph.name_to_buffer.pop(D, None)
        V.graph.name_to_op.pop(dup.get_operation_name(), None)
        extra = V.graph.name_to_users.pop(D, [])
        if extra:
            V.graph.name_to_users.setdefault(C, []).extend(extra)
        dead_ids.add(id(dup))

# Step 3 rebuild — filter dead in one pass:
survivors     = [op for op in operations if id(op) not in dead_ids]
constants     = [op for op in survivors if isinstance(op, SpyreConstantFallback)]
non_constants = [op for op in survivors if not isinstance(op, SpyreConstantFallback)]
operations[:] = constants + non_constants
```

Safety checks:

1. Ordering. The pass's exit invariant is constants-first, original
   relative order preserved among each partition. The batch rebuild
   filters through `survivors` in original order, then partitions —
   same result as the current code.

2. References held elsewhere. `V.graph.name_to_buffer.pop(D)` and
   `V.graph.name_to_op.pop(op_name)` still happen. Any other index
   that references the dup instance directly? A grep of the
   torch-spyre `_inductor/` tree for `graph.buffers` and
   `graph.operations` shows only `graph.operations` mutations in the
   passes; downstream passes iterate `graph.operations` and lookup
   via `name_to_buffer` / `name_to_op` — both cleaned by the pass
   already. The batch-removal change preserves the exact same clean-up.

3. Mutation side effects during the loop. Currently `_drop_constant`
   removes `dup` from `operations` *before* the next duplicate is
   processed. Does the next `_redirect_consumers` call rely on
   `dup` already being absent from `operations`? In the current
   code, the `_redirect_consumers` scan skips `op is dup or op is
   canonical` inline (line 68), so a dropped-but-still-in-list dup
   would be filtered on the identity check either way — except:
   the identity check names only the *current* `dup` and canonical.
   If a *previous* dup (`dup₁`) is still in `operations` when we
   process `dup₂`, the loop scans `dup₁` too. `dup₁.get_read_writes()`
   returns an empty read set (SpyreConstantFallback has no inputs),
   so `any(dep.name == D₂ ...)` is False, and `dup₁` is not patched.
   No incorrect action, just one extra iteration per still-present
   dup. Batch removal is therefore functionally identical here.

4. Canonical selection. The canonical is `group[0]`, chosen at group
   construction time (Step 1), before any removals. Batch or
   per-duplicate removal does not affect which op is canonical.

5. Later dedup groups. Group construction is complete before Step 2
   starts. Step 2 does not iterate `groups` in a way that depends on
   `operations` contents.

6. `name_to_users` update ordering. Currently `_drop_constant`
   folds `name_to_users[D]` into `name_to_users[C]` per duplicate.
   In the batch variant it still does — same order, same result.
   Downstream reads of `name_to_users[C]` only happen after the pass
   returns.

Batch-removal is safe under the current implementation's own
invariants and correctness constraints.

**Expected speedup for the removal side alone.** Each
`operations.remove(dup)` is `O(N)`. `D` of them gives `O(N · D)` —
literally the *same* asymptotic order as the operation-scan side of
`_redirect_consumers`. Removing this term should roughly halve the
201.8 µs coefficient (before any consumer-lookup improvement).
Measurement via the instrumentation in §11 will resolve the actual split.

---

## 8. Correctness and Mutation Risks

Constraints an optimized implementation must preserve. These are the
behaviors of the current pass that must survive any change:

- **Skip output constants.** `_redirect_consumers` line 62 skips
  duplicates whose name is in `V.graph.get_output_names()` and logs
  a debug message. Any replacement must reproduce this. The current
  code skips *only the redirect*, not `_drop_constant`; a duplicate
  that is an output name would therefore currently be *removed but
  not redirected* — that appears to be a bug (consumers still read
  the removed name). Worth flagging separately. For now, an
  optimization should not change this behavior — matching bugs
  matter for a refactor.
- **Groups with zero duplicates** (a single-instance group) do
  nothing. Preserve.
- **Multiple duplicate groups.** Independent — the fold on one
  group's `name_to_users[C]` cannot break another group's canonical.
- **Different dtype/device constants are separate groups.** Enforced
  by `_constant_key`. Preserve; tested by
  `tests/inductor/test_dedup_constants.py::test_different_dtype_constants_not_merged`.
- **Constants referenced only indirectly** (through a chain of
  Pointwise buffers that in turn are read by another buffer). The
  current pass walks `operations` and calls `get_read_writes` on
  each op; a chain of intermediate `ComputedBuffer`s would have
  their *own* `get_read_writes` reflect their own reads, not the
  eventual leaf reader's reads. Any redirect chain is handled
  because each link is patched individually if it reads `D`.
- **Unusual read/write structures.** Non-`ComputedBuffer` consumers
  raise `AssertionError` — a hard constraint we should not silently
  loosen.
- **Operation ordering.** Constants front-loaded; among constants,
  original relative order preserved (matters for topological
  consistency with FX-node origins used by `assign_dim_hints` etc.).
  Tested by `test_constants_at_front` and
  `test_surviving_constant_at_index_zero`.
- **Metadata / provenance.** The pass registers no observer of its
  own (see `passes.py:200-218` — `CustomPreSchedulingPasses`
  attaches a `SpyreGraphTransformObserver` around each pass; the
  observer runs on the whole pass). `_patch_inner_fn` does not
  touch `op.origins`. Preserve.
- **`name_to_users[canonical]` must contain the union of pre-dedup
  users.** Load-bearing for `scratchpad/graph_editor.py:186-197`
  which iterates `name_to_users[buf_name]` and mutates it during
  scratchpad planning. Any replacement must still fold
  `name_to_users[D]` into `name_to_users[C]`.
- **`removed_buffers` must contain every dropped duplicate name.**
  Downstream codegen (`spyre_kernel.py:648,741`) reads it. Preserve.

Mutations performed by `replace_input` — the current code does not
call `replace_input` at all; it exclusively uses `NameSwapHandler`.
Not a concern for the current pass but worth noting: an alternative
approach that uses `replace_input` would need a much broader safety
argument.

---

## 9. Existing Test Coverage and Missing Tests

Tests found:

- `tests/inductor/test_dedup_constants.py` — five structural tests.
- `tests/inductor/test_padding.py::test_padding_constants_deduped`
  — end-to-end test that two matmuls sharing a padding sequence
  dedup to one surviving constant, then correctness-check the
  compiled result against CPU.

**What is covered:**

- `test_constants_at_front` — every constant precedes every
  non-constant after the pass.
- `test_dedup_across_same_dtype_pad_sequences` — two matmuls sharing
  a pad → exactly one surviving constant.
- `test_different_dtype_constants_not_merged` — fp16 and fp32
  constants with the same numeric value are kept separate.
- `test_no_orphans_in_name_to_buffer` — every surviving constant is
  in the operations list, no other constants present.
- `test_surviving_constant_at_index_zero` — first operation is a
  `SpyreConstantFallback` when any exist.
- `test_padding_constants_deduped` — end-to-end correctness.

**What is not covered:**

- **Zero-consumer duplicates.** A constant with no readers at all —
  can this happen (e.g. after `deadcode_elimination` removed the
  reader but not the constant)? The dedup pass would still try to
  `_redirect_consumers` (finds none) and then `_drop_constant`. Not
  tested. Important for the `name_to_users` optimization because
  `name_to_users[D]` may be empty for such a constant.
- **Many-consumer duplicates.** All the existing tests have single
  reader per dup (one matmul reads one padding constant). We have no
  test where the same constant is read by many ops. This is exactly
  the case `name_to_users` should accelerate; a targeted test
  helps prove correctness of a replacement.
- **Output-name duplicates.** The `if D in V.graph.get_output_names()`
  branch is not exercised. The current bug (skip redirect but still
  drop) would go unnoticed. Not directly on the critical path for
  the optimization, but worth flagging.
- **Chained constant reads.** A constant read by an intermediate
  Pointwise that is itself read by another Pointwise. The pass walks
  each layer via `get_read_writes` and patches at each layer — but
  no test verifies this.
- **Non-`ComputedBuffer` consumer** raises the `AssertionError` on
  line 75. Untested. Would surface if a later pass introduces a
  non-`ComputedBuffer` reader (e.g. an `ExternKernel` fallback).
- **`name_to_users[C]` fold correctness.** No test asserts that
  after dedup, `V.graph.name_to_users[canonical_name]` contains the
  union of pre-dedup users. Load-bearing for scratchpad planning.
- **Performance regression guard.** No test asserts pass time is
  linear in a specific quantity. The timing study is external; a
  micro-benchmark test that walks a synthetic 500-op / 64-dup graph
  and asserts wall-clock under a threshold would catch a regression.

Recommendation: before or alongside any implementation, add tests
for zero-consumer, many-consumer, and `name_to_users[C]`-fold cases.
These are cheap unit tests that hook `CustomPreSchedulingPasses` the
same way `test_dedup_constants.py` already does.

---

## 10. Candidate Optimizations, Ranked

Each option's complexity is stated as `before → after` on the
dominant term(s) for this workload.

### A. Use `name_to_users` for consumer discovery

Before: `O(N)` scan per duplicate, `O(N · D)` total, with the
expensive per-op `get_read_writes` inside.
After: `O(|name_to_users[D]|)` per duplicate, plus one
`get_read_writes` per candidate to filter stale entries. On the
measured workload `|name_to_users[D]| ≈ Uᴰ ≈ 1`, so effectively
`O(D)` for this term.

- Expected performance impact. Very large. Halves-to-eliminates the
  consumer-discovery half of the 201.8 µs · N · D cost. At the
  largest measured point (Lq=1024, Lk=8192, `N · D ≈ 1.1M`), that
  is ~225 s → single-digit seconds if the removal side is also
  fixed (see B).
- Implementation difficulty. Moderate. Requires the
  TensorBox → ComputedBuffer unwrap, the read-filter, and reproducing
  the output-name skip.
- Correctness risk. Non-trivial. The staleness argument in §6 needs
  to be verified against every earlier pass in the pipeline. The
  filter via `get_read_writes` reduces the risk to a performance
  question — the wrong candidate list would just slow the pass down,
  not corrupt it — but only if the filter is not accidentally
  removed for a "clean-up".
- Metadata / index maintenance. Same folds into `name_to_users[C]`
  as today. The pass consumes the index, so it must still remove
  dead entries at the end (already does).
- Independent test. Yes — the many-consumer test suggested in §9
  isolates it.

### B. Batch-remove duplicates

Before: `D` calls to `operations.remove(dup)`, `O(N · D)` total.
After: One `operations[:] = ...` at end of Step 3, `O(N)`.

- Expected performance impact. Significant. Removes one of the two
  `O(N · D)` terms from the 201.8 µs coefficient. Standalone: modest
  wall-clock win, ~half. Combined with A: essential to complete the
  cleanup.
- Implementation difficulty. Low. See the sketch in §7.
- Correctness risk. Low. The pass already batch-rewrites `operations`
  at Step 3. This change moves individual `.remove` calls into that
  final rewrite.
- Metadata / index maintenance. Unchanged.
- Independent test. Yes — a "dedup an N-op graph in linear time"
  micro-benchmark.

### C. Skip consumer discovery when the duplicate has no users

Before: full `_redirect_consumers` walk even for zero-user dups.
After: `if not V.graph.name_to_users.get(D): return` at
`_redirect_consumers` entry.

- Expected performance impact. Small on the studied workload
  (every dup has one consumer — the restickify buffer). Larger on
  workloads where deadcode has eliminated readers but not the
  constant itself.
- Implementation difficulty. Trivial.
- Correctness risk. Very low; the guard is a fast-path around a
  branch that would have been a no-op anyway.
- Independent test. Zero-consumer case is worth testing regardless.
- **Note.** This is a strict subset of A. If A is done, C comes free.

### D. Cache `get_read_writes()`

Before: uncached; every call re-runs `extract_read_writes`.
After: memoize on a per-buffer basis for the duration of the pass.

- Expected performance impact. On the current algorithm, moderate:
  each op's read set is called `D + 1` times (once per duplicate
  and once by the pre-loop grouping — actually the grouping does
  not call `get_read_writes`, so `D` times). A per-op cache local
  to the pass would reduce that to one call per op. But A already
  eliminates the outer scan, so D obsoletes itself if A lands.
- Implementation difficulty. Low: wrap `_redirect_consumers` in a
  `dict[id(op), ReadWrites]` cache.
- Correctness risk. Moderate: `_patch_inner_fn` on op X *changes* X's
  read names (it swaps a read of D for a read of C in the closure).
  Any cache would need to be invalidated on X after patching.
  Because A avoids the inner scan entirely, D is not worth doing
  standalone.

### E. Build a local Buffer→consumers dict at pass entry

Before: `O(N)` scan per duplicate.
After: `O(N)` scan once, then `O(1)` lookup per duplicate.

- Expected performance impact. Very close to A, without depending
  on `name_to_users` freshness.
- Implementation difficulty. Low. One pre-pass through `operations`
  calling `get_read_writes` once each, building
  `defaultdict[str, list[Operation]]`.
- Correctness risk. Low. No cross-pass staleness concerns — the
  dict is built from live state.
- Trade-off vs A. Adds one `O(N)` sweep at entry. On this workload
  that is ~one 201.8 µs unit times `N` = one *N*-cost run rather
  than *N·D*, so the added cost is <1% of the current pass time at
  large `N`. Preferable to A if `name_to_users` staleness turns out
  to be a maintenance headache.

**Ranking for this workload:**

1. **A + B together.** They address the two `O(N · D)` terms in the
   observed model. Correctness argument is the pass's own current
   invariants. Estimated wall-clock: from 225 s to a few seconds at
   the largest measured workload — call it 30-100× improvement,
   pending measurement.
2. **E + B** as a fallback if A's staleness analysis reveals a
   correctness edge case. Similar asymptotic gain; slightly worse
   constant factor.
3. **C** as free housekeeping regardless (or subsumed by A).
4. **D** is not worth pursuing standalone.

---

## 11. Additional Instrumentation Worth Adding

Before touching the algorithm, add counters that separate the two
`O(N · D)` terms. Concretely, extend
`patches/timing_recorder.py` (or add a small `dedup_metrics`
context inside the pass under an env-gated log) to record per invocation:

- `n_operations_at_entry` — already have via
  `pass:CustomPreSchedulingPasses:dedup_and_promote_constants.input_operations`.
- `n_constant_ops` — `C`.
- `n_dedup_groups` — `G`.
- `n_duplicates` — `D = C − G`.
- `n_operations_scanned` — cumulative op iterations inside
  `_redirect_consumers`; should be ~`D · N`.
- `n_get_read_writes_calls` — split into
  `n_get_read_writes_computed_buffer` vs `n_get_read_writes_other`.
- `n_consumer_hits` — `Σ Uᴰ`, i.e. how many patches actually happen.
- `n_operations_remove_calls` — should equal `D`.
- `wall_time_redirect_consumers`, `wall_time_drop_constant`,
  `wall_time_front_load` — three sub-timings.

Two runs are enough to answer the outstanding question: is the
201.8 µs coefficient split ~50/50 between consumer scan and
`operations.remove`, or is it dominated by one? Run the baseline
(Lq=512, Lk=1024, H=8) and the largest well-sampled point
(Lq=512, Lk=8192, H=8). The split determines whether A or B is the
bigger win and whether A alone gets us to acceptable performance.

`n_consumer_hits` tells us `Uᴰ`. If it stays ≈ 1 across the sweep,
the `name_to_users[D]` candidate set is guaranteed tiny and A's
speedup is nearly maximal. If `Uᴰ` grows with graph size, A is still
good but less dramatic.

Correctness instrumentation worth adding as unit tests before the
change (§9): zero-consumer dup, many-consumer dup, `name_to_users[C]`
fold.

---

## 12. Recommended Next Experiment

**Do this next, and nothing beyond it:**

1. Add the instrumentation in §11 in a *no-behavior-change* patch.
   Run the H=8 baseline and Lk=8192 points. Log the timing split.
2. Add the three unit tests in §9 (zero-consumer, many-consumer,
   `name_to_users[C]` fold). All should pass against the current
   implementation. This locks in the behavior we are about to
   preserve.
3. In a separate patch, prove `name_to_users[D]` correctness by
   asserting inside a copy of `_redirect_consumers` that every op
   currently identified as a consumer via the linear scan is *also*
   in `name_to_users[D]` after
   `TensorBox → StorageBox → ComputedBuffer` unwrapping. Run the
   full test suite plus the H=8 sweep. This is a purely-additive
   assertion pass that either passes silently (proving the
   superset relationship) or raises loudly (revealing a case we
   need to handle).

Only if step 3 passes silently across the sweep, proceed to the
implementation experiment: replace `_redirect_consumers`' outer scan
with the `name_to_users`-indexed candidate loop (Option A), plus the
batch-removal change (Option B). Measure the same points. Expected
result: the near-quadratic slope collapses.

Do not implement A and B in the same PR without step-3 evidence.
The commit that ships the algorithm change should have a paragraph
in its message explaining why `name_to_users[D]` is sound at the
pass's entry point.

**Explicitly NOT recommended:**

- Optimizing `optimize_restickify_locations` or
  `_maybe_scratchpad_planning` in this same experiment. Both have
  their own findings (`findings.md` §9) and each deserves an
  independent source-level report before touching.
- Caching `get_read_writes` (Option D) before A. Subsumed by A.
- Any change to `_patch_inner_fn` semantics or `NameSwapHandler`.
  Out of scope.

---

## 13. Exact Files and Functions Likely Involved in the Change

Primary:

- `torch_spyre/_inductor/dedup_constants.py`
  - `_redirect_consumers` (lines 51-78) — replaced with a
    `name_to_users[D]`-indexed loop plus a read-filter and the same
    output-name skip.
  - `_drop_constant` (lines 81-99) — the `operations.remove(dup)`
    call removed; the remaining bookkeeping preserved. Duplicate
    identity accumulated into a `dead_ids: set[int]` in the caller.
  - `dedup_and_promote_constants` (lines 102-144) — Step 2 no longer
    mutates `operations` per iteration; Step 3's list comprehensions
    also filter `dead_ids`.

Secondary (touched only for tests / assertions):

- `tests/inductor/test_dedup_constants.py` — add three tests
  (zero-consumer, many-consumer, `name_to_users[C]` fold). No changes
  to existing tests.
- `patches/timing_recorder.py` (in `compiler-timing` repo) — add the
  dedup sub-counters described in §11. Note this file lives outside
  torch-spyre.

Read but not modified:

- `torch_spyre/_inductor/insert_restickify.py` — `NameSwapHandler`
  definition (line 66) and the existing `name_to_users` unwrap pattern
  (lines 96-104) that the new code will mirror.
- `torch_spyre/_inductor/ir.py` — `SpyreConstantFallback` definition
  (line 110), for the identity-check argument.
- `torch/_inductor/graph.py` (upstream) — `name_to_users`
  initialization (line 410), `register_users_of` (line 973). No
  changes.
- `torch/_inductor/ir.py` (upstream) — `ComputedBuffer.get_read_writes`
  (line 4558), `InputsKernel.get_read_writes` (line 5297) for the
  cost-model argument. No changes.

**Pipeline-order note.** This local checkout has the
`CustomPreSchedulingPasses` list at `torch_spyre/_inductor/passes.py:315-341`
running 15 passes, ending with `_maybe_scratchpad_planning`. The
timing-boundary map (`notes/timing-boundary-map.md`) lists 20 passes
in the version under measurement — this checkout is at
commit `0e8f7f257` (2026-06-22), older than the study run
(2026-08). The additional passes in the study version are
`propagate_named_dims`, `validate_named_dims`, `assign_dim_hints`,
`_maybe_reorder_unhinted_interlopers`, `_maybe_coarse_tile_hints`,
`enforce_indirect_access_layout`, `insert_post_mutation_restickify`,
`_maybe_coarse_tile_span_overflow`. Crucially,
`dedup_and_promote_constants` runs *after* `insert_restickify` and
`insert_bmm_padding` in both versions, so the analysis of consumer
identity (restickify buffers as constant readers) holds. Before
committing an implementation, verify against the study-version tree
that no pass between `insert_restickify` and dedup mutates
`name_to_users` in a way that changes the staleness argument in §6.

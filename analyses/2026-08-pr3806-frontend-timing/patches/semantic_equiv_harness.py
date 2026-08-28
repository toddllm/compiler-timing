"""Semantic-equivalence harness for dedup_and_promote_constants.

Runs a workload twice through the same pipeline, differing ONLY in
which dedup implementation is active (pristine vs E-only vs E+batch).
Captures normalized post-dedup graph state each run and compares.

Comparison targets (normalized to abstract away process-specific
name suffixes):

  * `graph.operations` — ordered list of (type_name, canonical_key
    | position) for each op.
  * surviving-constant identity keys `(value, dtype, device)`
    counted by group and by position.
  * `removed_buffers` — count and per-run set of buffer-name prefixes.
  * `name_to_buffer` — surviving keys, canonicalized.
  * `name_to_op` — surviving keys, canonicalized.
  * `name_to_users` — {canonical: [list_of_read_names_of_users]}.
  * `_spyre_prov_history` on the canonical constants: transform
    kinds, pass_names, reasons (count).
  * per-consumer live reads after dedup: for every ComputedBuffer
    surviving in operations, the set of names it currently reads.

Two-run mode:
  python semantic_equiv_harness.py --Lq 512 --Lk 1024 --out state.json

That writes state.json for whichever dedup implementation is active
in the tree at run time. Do two runs with different swaps active
(pristine vs E vs E+batch) and compare with `diff_semantic_state.py`.

Names in Inductor are process-nondeterministic across recompiles;
we canonicalize by (a) mapping each buffer name to an index equal
to its position in `graph.operations` after dedup, and (b) mapping
each constant name to a group key + within-group index.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import torch

# The harness's job is to lower the workload, capture normalized
# post-dedup state, and write it out. We reuse the workload builder
# from workload_harness.py to keep the graph identical.


def _capture_state(graph) -> dict:
    """Return a normalized snapshot of graph state after dedup.

    See module docstring for what's included.
    """
    from torch_spyre._inductor.ir import SpyreConstantFallback
    from torch_spyre._inductor.dedup_constants import _constant_key
    from torch._inductor.ir import ComputedBuffer

    ops = list(graph.operations)

    # Canonicalize names: map raw buffer name -> stable index.
    # For SpyreConstantFallback, additionally emit (key, within-group idx).
    name_index = {}
    for i, op in enumerate(ops):
        try:
            name_index[op.get_name()] = f"op#{i}"
        except Exception:
            pass

    def canonical(name):
        return name_index.get(name, f"?{name}?")

    # ordered ops as (type_name, canonical_index)
    ops_summary = [
        {
            "type": type(op).__name__,
            "canonical": canonical(op.get_name()) if hasattr(op, "get_name") else None,
            "op_name": op.get_operation_name() if hasattr(op, "get_operation_name") else None,
        }
        for op in ops
    ]

    # surviving constants: their identity keys and positions
    constants = [
        (i, op) for i, op in enumerate(ops) if isinstance(op, SpyreConstantFallback)
    ]
    const_summary = [
        {
            "pos": i,
            "key": [str(part) for part in _constant_key(op)],
            "provenance_history_len": len(getattr(op, "_spyre_prov_history", ()) or ()),
            "provenance_pass_names": [
                getattr(t, "pass_name", None)
                for t in (getattr(op, "_spyre_prov_history", ()) or ())
            ],
        }
        for i, op in constants
    ]

    # removed_buffers
    rb = sorted(str(x) for x in graph.removed_buffers)

    # name_to_buffer keys, canonicalized
    n2b = sorted(canonical(k) if k in name_index else k for k in graph.name_to_buffer)

    # name_to_op keys, canonicalized (op names too, but for our workload
    # buffer names == op names on Operation subclasses of Buffer)
    n2o = sorted(k for k in graph.name_to_op)

    # name_to_users: for each key, list of read-name sets of each entry
    n2u = {}
    for k, users in graph.name_to_users.items():
        entries = []
        for u in users:
            try:
                # TensorBox / IRNode: try get_read_names -> set of buffer names
                if hasattr(u, "get_read_names"):
                    reads = sorted(str(n) for n in u.get_read_names())
                else:
                    reads = None
                # also whatever underlying buffer name it has, if any
                inner_name = None
                node = u
                for _ in range(4):
                    inner_name = getattr(node, "name", None) or getattr(
                        node, "operation_name", None
                    )
                    if inner_name:
                        break
                    node = getattr(node, "data", None)
                    if node is None:
                        break
                entries.append({
                    "type": type(u).__name__,
                    "read_names": reads,
                    "inner_name_canonical": canonical(inner_name) if inner_name else None,
                })
            except Exception as e:
                entries.append({"type": type(u).__name__, "error": str(e)})
        n2u[canonical(k)] = entries

    # per-consumer live reads for every surviving ComputedBuffer
    live_reads = {}
    for i, op in enumerate(ops):
        if isinstance(op, ComputedBuffer):
            try:
                reads = sorted(str(dep.name) for dep in op.get_read_writes().reads)
                live_reads[f"op#{i}"] = {
                    "type": type(op).__name__,
                    "reads": [canonical(n) for n in reads],
                }
            except Exception:
                pass

    return {
        "n_operations": len(ops),
        "n_surviving_constants": len(constants),
        "operations": ops_summary,
        "constants": const_summary,
        "removed_buffers_count": len(rb),
        "removed_buffers": rb,
        "name_to_buffer_keys_canonical": n2b,
        "name_to_op_keys": n2o,
        "name_to_users": n2u,
        "live_reads": live_reads,
    }


def _post_dedup_capture_hook():
    """Return a subclass of CustomPreSchedulingPasses that captures
    state IMMEDIATELY after dedup and short-circuits the rest of the
    pipeline. Downstream passes may not tolerate the graph state we
    inspect (dedup writes to name_to_users for scratchpad planning to
    then read), so we cannot run them here.
    """
    from torch_spyre._inductor.passes import CustomPreSchedulingPasses

    class _CapturePasses(CustomPreSchedulingPasses):
        captured_state = None

        def __call__(self, graph):
            from torch_spyre._inductor.passes import _operations_have_spyre_device
            if not _operations_have_spyre_device(graph.operations):
                return
            pass_list = list(self.passes)
            dedup_idx = next(
                i for i, p in enumerate(pass_list)
                if getattr(p, "__name__", "") == "dedup_and_promote_constants"
            )
            # Run everything up to and INCLUDING dedup.
            for pass_fn in pass_list[:dedup_idx + 1]:
                pass_fn(graph)
            _CapturePasses.captured_state = _capture_state(graph)
            # Stop — do not run downstream passes.

    return _CapturePasses


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--Lq", type=int, required=True)
    ap.add_argument("--Lk", type=int, required=True)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    # Reuse the workload builder from workload_harness.py — it lives
    # in the same directory on the pod.
    workload_path = os.path.join(os.path.dirname(__file__), "workload_harness.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("workload_harness", workload_path)
    workload_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workload_mod)

    from torch_spyre._inductor import passes
    from unittest.mock import patch as _patch

    _CapturePasses = _post_dedup_capture_hook()

    # Same knobs the timing harness uses for the study.
    B, H, D = 1, 8, 128
    b_block_size, h_block_size = 1, 4
    q_block_size, kv_block_size = 256, 512

    flash = workload_mod.build_flash_closure(
        B, H, D, args.Lq, args.Lk,
        b_block_size, h_block_size, q_block_size, kv_block_size,
    )

    device = "spyre"
    torch.manual_seed(0xAFFE)
    queries = torch.randn(B, H, args.Lq, D, device=device, dtype=torch.float16)
    keys = torch.randn(B, H, args.Lk, D, device=device, dtype=torch.float16)
    values = torch.randn(B, H, args.Lk, D, device=device, dtype=torch.float16)
    causal = torch.tril(torch.ones(args.Lq, args.Lk, dtype=torch.bool))
    mask_cpu = torch.zeros(1, 1, args.Lq, args.Lk, dtype=torch.float16)
    mask_cpu.masked_fill_(~causal, float("-inf"))
    mask = mask_cpu.to(device)

    with _patch.object(passes, "CustomPreSchedulingPasses", _CapturePasses):
        compiled = torch.compile(flash, fullgraph=True)
        try:
            compiled(queries, keys, values, mask)
        except Exception:
            # Expected — we short-circuited the pipeline post-dedup.
            # If dedup itself raised, that's a real bug worth surfacing.
            if _CapturePasses.captured_state is None:
                raise

    if _CapturePasses.captured_state is None:
        print("FATAL: never captured post-dedup state", file=sys.stderr)
        return 2

    with open(args.out, "w") as f:
        json.dump(_CapturePasses.captured_state, f, indent=2)
    print(f"wrote {args.out}: {len(json.dumps(_CapturePasses.captured_state))} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

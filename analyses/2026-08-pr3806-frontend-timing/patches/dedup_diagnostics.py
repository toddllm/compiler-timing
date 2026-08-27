"""
Dedup-diagnostic instrumentation for the PR #3806 front-end study.

Target source: torch-spyre at commit a9316b3 (PR #3806 head), torch
2.13.0+cpu. This module is gated on ``TORCH_SPYRE_DEDUP_DIAG=1`` and
is completely inert when off. It is a companion to
``timing_recorder.py``; it does not replace it.

What it collects, per invocation of
``torch_spyre._inductor.dedup_constants.dedup_and_promote_constants``:

Sub-timers (perf_counter_ns, aggregated per pass invocation, not per op):
    grouping_ns           Step 1 — group by identity key.
    redirect_ns           Step 2 outer — total time in _redirect_consumers.
    get_read_writes_ns    Time specifically inside op.get_read_writes()
                          called from _redirect_consumers.
    reads_probe_ns        Time in ``any(dep.name == D for dep in rw.reads)``.
    patch_inner_fn_ns     Time in _patch_inner_fn.
    drop_ns               Step 2 outer — total time in _drop_constant.
    merge_provenance_ns   Time in merge_provenance from _drop_constant.
    operations_remove_ns  Time specifically inside operations.remove(dup).
    bookkeeping_ns        removed_buffers/name_to_buffer/name_to_op/name_to_users
                          folds in _drop_constant.
    front_load_ns         Step 3 rebuild.
    dedup_total_ns        End-to-end time for the pass (should equal the
                          sum of the above within a few percent).

Counts:
    n_ops_at_entry              len(graph.operations) at pass entry.
    n_constants                 |{op: isinstance(op, SpyreConstantFallback)}|.
    n_groups                    Number of distinct (value, dtype, device) keys.
    n_groups_multi              Number of groups with |group| > 1.
    n_duplicates                Σ(|group|-1) over groups with |group|>1.
    n_ops_scanned               Σ over dups of |operations| iterated in
                                _redirect_consumers (∼ n_duplicates × N).
    n_get_read_writes_calls     Total get_read_writes calls from redirect.
    n_get_read_writes_by_type   dict[str -> int] — per-Operation-subtype
                                count. Uses type(op).__name__ so we can
                                see which classes dominate the calls.
    n_consumer_hits             Number of times a scanned op's reads
                                actually contained D (equals number of
                                _patch_inner_fn calls).
    n_operations_remove_calls   Should equal n_duplicates.

Gold/name_to_users comparison, collected while dedup runs
(one entry per processed duplicate, no cross-pass side effects):

    per_duplicate[i] = {
        "dup_name":                 <str>,
        "canonical_name":           <str>,
        "gold_consumer_ops":        [operation_name, ...],   # from linear scan
        "gold_consumer_count":      <int>,
        "nu_raw_entry_count":       <int>,   # len(V.graph.name_to_users[D])
        "nu_unique_op_count":       <int>,   # unique underlying operation
                                              # names after TensorBox unwrap
        "nu_true_positives":        <int>,   # in both gold and index
        "nu_false_positives":       <int>,   # in index only (stale)
        "nu_false_negatives":       <int>,   # in gold only (index missing)
        "nu_unwrap_failures":       <int>,   # index entries we could not
                                              # unwrap to a live operation
        "nu_consumer_types":        {type_name: count, ...},
    }

The comparison MUST NOT change behavior. Every hook only reads state;
the linear-scan result (the gold set) is captured by observing the
existing algorithm from inside, not by re-running anything.

Output: written to $SPYRE_DEDUP_DIAG_OUT (JSON) at the end of the
process, or appended to the same file the timing recorder writes if
$SPYRE_DEDUP_DIAG_MERGE_INTO_TIMING=1 (kept separate by default so a
diagnostic run is easy to diff against a plain timing run).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


_ENABLED = os.environ.get("TORCH_SPYRE_DEDUP_DIAG") == "1"


def is_enabled() -> bool:
    return _ENABLED


# ---------------------------------------------------------------------------
# Per-invocation record.

@dataclass
class DedupRecord:
    invocation_ordinal: int = 0
    graph_id: Optional[int] = None
    # sub-timers
    grouping_ns: int = 0
    redirect_ns: int = 0
    get_read_writes_ns: int = 0
    reads_probe_ns: int = 0
    patch_inner_fn_ns: int = 0
    drop_ns: int = 0
    merge_provenance_ns: int = 0
    operations_remove_ns: int = 0
    bookkeeping_ns: int = 0
    front_load_ns: int = 0
    dedup_total_ns: int = 0
    # counts
    n_ops_at_entry: int = 0
    n_constants: int = 0
    n_groups: int = 0
    n_groups_multi: int = 0
    n_duplicates: int = 0
    n_ops_scanned: int = 0
    n_get_read_writes_calls: int = 0
    n_get_read_writes_by_type: dict[str, int] = field(default_factory=dict)
    n_consumer_hits: int = 0
    n_operations_remove_calls: int = 0
    # per-duplicate consumer comparison
    per_duplicate: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_ordinal": self.invocation_ordinal,
            "graph_id": self.graph_id,
            "timings_ns": {
                "grouping": self.grouping_ns,
                "redirect": self.redirect_ns,
                "get_read_writes": self.get_read_writes_ns,
                "reads_probe": self.reads_probe_ns,
                "patch_inner_fn": self.patch_inner_fn_ns,
                "drop": self.drop_ns,
                "merge_provenance": self.merge_provenance_ns,
                "operations_remove": self.operations_remove_ns,
                "bookkeeping": self.bookkeeping_ns,
                "front_load": self.front_load_ns,
                "dedup_total": self.dedup_total_ns,
            },
            "counts": {
                "n_ops_at_entry": self.n_ops_at_entry,
                "n_constants": self.n_constants,
                "n_groups": self.n_groups,
                "n_groups_multi": self.n_groups_multi,
                "n_duplicates": self.n_duplicates,
                "n_ops_scanned": self.n_ops_scanned,
                "n_get_read_writes_calls": self.n_get_read_writes_calls,
                "n_get_read_writes_by_type": self.n_get_read_writes_by_type,
                "n_consumer_hits": self.n_consumer_hits,
                "n_operations_remove_calls": self.n_operations_remove_calls,
            },
            "per_duplicate": self.per_duplicate,
        }


# ---------------------------------------------------------------------------
# Recorder — one process-wide instance.

class DedupDiagRecorder:
    def __init__(self) -> None:
        self._records: list[DedupRecord] = []
        self._lock = threading.Lock()
        self._next_ordinal = 0

    def new_record(self, graph_id: Optional[int] = None) -> DedupRecord:
        with self._lock:
            rec = DedupRecord(invocation_ordinal=self._next_ordinal, graph_id=graph_id)
            self._next_ordinal += 1
            self._records.append(rec)
        return rec

    def dump_json(self, path: str) -> None:
        payload = {
            "meta": {
                "recorder_version": 1,
                "clock": "time.perf_counter_ns",
                "python_pid": os.getpid(),
                "torch_spyre_commit_target": "a9316b381 (PR #3806 head)",
            },
            "records": [r.to_dict() for r in self._records],
        }
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)


RECORDER = DedupDiagRecorder()


# ---------------------------------------------------------------------------
# Optional atexit dump so a run always writes results.

def _install_atexit_dump() -> None:
    out = os.environ.get("SPYRE_DEDUP_DIAG_OUT")
    if not out:
        return
    import atexit

    def _dump() -> None:
        try:
            RECORDER.dump_json(out)
        except Exception:
            # Diagnostic instrumentation must never break the compile.
            pass

    atexit.register(_dump)


if _ENABLED:
    _install_atexit_dump()


# ---------------------------------------------------------------------------
# TensorBox → underlying Operation-name unwrap helper.
#
# name_to_users maps buffer names to TensorBox instances (see
# torch/_inductor/graph.py:1128 and register_users_of usage). To compare
# against the current pass' consumer set (a list of Operations discovered by
# scanning graph.operations), we need to unwrap each TensorBox to the name of
# the operation that Owns the underlying ComputedBuffer.
#
# The unwrap is: TensorBox.data -> StorageBox / MutableBox -> ComputedBuffer.
# On ir_dataclass classes, ``.data`` is present on both TensorBox and
# StorageBox; the loop below terminates at the first non-MutableBox.
#
# Unwrap can fail if:
#   - the TensorBox is now a ReinterpretView / MultiOutput / DonatedBuffer,
#     which have no operation_name of their own.
#   - the underlying object is a Buffer without an operation_name (e.g. an
#     InputBuffer that appeared as an intermediate).
#
# Failures are counted; they are NOT fatal.

def unwrap_tensorbox_to_op_name(tb: Any) -> Optional[str]:
    """Return the operation_name of the Operation behind a TensorBox, or None.

    Never raises. Callers count None-returns as ``nu_unwrap_failures``.
    """
    try:
        node = tb
        # Walk down the MutableBox chain.
        for _ in range(4):  # cap the walk defensively
            data = getattr(node, "data", None)
            if data is None:
                break
            node = data
        # ``node`` should now be an Operation-owning Buffer (typically
        # ComputedBuffer). ``get_operation_name`` raises AssertionError
        # for objects with operation_name == None, so use getattr.
        op_name = getattr(node, "operation_name", None)
        if op_name:
            return op_name
        # Some nodes expose the name via get_operation_name only, others via
        # buffer name. Fall back to buffer name (Operation subclasses that
        # inherit from Buffer set self.name to the buffer name, which is the
        # same as the operation name for OperationBuffer per its
        # get_operation_name definition).
        get_op_name = getattr(node, "get_operation_name", None)
        if callable(get_op_name):
            try:
                return get_op_name()
            except AssertionError:
                return None
        return None
    except Exception:
        return None

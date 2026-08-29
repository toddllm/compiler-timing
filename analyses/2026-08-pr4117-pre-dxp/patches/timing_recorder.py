"""
Compiler-timing recorder for the PR #3806 front-end study.

Design goals:

- Monotonic high-resolution clock: ``time.perf_counter_ns()``.
- ``try/finally`` around every stage so a failing pass still records.
- Inclusive AND self (exclusive) time, so nested timers can be summed
  without double-counting.
- Ordered event list, so a run reproduces the wall-clock timeline.
- Structured JSON dump per run at ``$SPYRE_TIMING_OUT``.
- Off by default; on when ``TORCH_SPYRE_TIMING=1``.

Not gated on ``TORCH_COMPILE_DEBUG=1`` on purpose: that flag turns on
heavyweight artifact dumps we do *not* want during timing runs.

The recorder is intentionally dependency-free (stdlib only) and lives in
its own file so the diff against torch-spyre stays small.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, ContextManager, Iterator, Optional

# ---------------------------------------------------------------------------
# Gate

_ENABLED = os.environ.get("TORCH_SPYRE_TIMING") == "1"


def is_enabled() -> bool:
    return _ENABLED


# ---------------------------------------------------------------------------
# Event model

@dataclass
class _Event:
    name: str
    ordinal: int
    parent_ordinal: Optional[int]
    t_start_ns: int
    t_end_ns: int = 0
    inclusive_ns: int = 0
    # self_ns = inclusive_ns minus the inclusive time of direct children.
    self_ns: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    # Filled in when the timed region raises.
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "ordinal": self.ordinal,
            "parent_ordinal": self.parent_ordinal,
            "t_start_ns": self.t_start_ns,
            "t_end_ns": self.t_end_ns,
            "inclusive_ns": self.inclusive_ns,
            "self_ns": self.self_ns,
        }
        if self.meta:
            d["meta"] = self.meta
        if self.error is not None:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# Recorder — one process-wide instance

class TimingRecorder:
    def __init__(self) -> None:
        self._events: list[_Event] = []
        # Stack of open events per thread so nesting is thread-safe.
        self._stack_local = threading.local()
        self._lock = threading.Lock()
        self._next_ordinal = 0
        self.run_meta: dict[str, Any] = {}

    # ---- stack helpers ---------------------------------------------------

    def _stack(self) -> list[_Event]:
        stk = getattr(self._stack_local, "stack", None)
        if stk is None:
            stk = []
            self._stack_local.stack = stk
        return stk

    def _new_ordinal(self) -> int:
        with self._lock:
            n = self._next_ordinal
            self._next_ordinal = n + 1
            return n

    # ---- public API ------------------------------------------------------

    def stage(self, name: str, **meta: Any) -> ContextManager[_Event]:
        return _Region(self, name, meta)

    def set_run_meta(self, **kv: Any) -> None:
        self.run_meta.update(kv)

    def dump_json(self, path: str) -> None:
        """Write the run to disk. Safe to call multiple times."""
        payload = {
            "meta": {
                **self.run_meta,
                "recorder_version": 1,
                "clock": "time.perf_counter_ns",
                "python_pid": os.getpid(),
            },
            "events": [e.to_dict() for e in self._events],
        }
        # Write atomically via .tmp -> rename so a crash mid-write can't
        # leave a half-written JSON that fools the roll-up.
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)

    # ---- internals used by _Region --------------------------------------

    def _start(self, name: str, meta: dict[str, Any]) -> _Event:
        stk = self._stack()
        parent = stk[-1].ordinal if stk else None
        ev = _Event(
            name=name,
            ordinal=self._new_ordinal(),
            parent_ordinal=parent,
            t_start_ns=time.perf_counter_ns(),
            meta=meta,
        )
        stk.append(ev)
        self._events.append(ev)
        return ev

    def _finish(self, ev: _Event, error: Optional[str]) -> None:
        ev.t_end_ns = time.perf_counter_ns()
        ev.inclusive_ns = ev.t_end_ns - ev.t_start_ns
        if error is not None:
            ev.error = error
        stk = self._stack()
        # Pop the current event even if it doesn't match, to avoid corrupting
        # the stack for later timers when something raised.
        if stk and stk[-1] is ev:
            stk.pop()
        elif stk:
            # Best-effort: pop until we find ourselves, in case an inner
            # region wasn't torn down (should not happen with the context
            # manager below, but be defensive).
            while stk and stk[-1] is not ev:
                stk.pop()
            if stk:
                stk.pop()

    def finalize(self) -> None:
        """Compute self_ns for every event.

        Called once before dump_json. self_ns for an event is its
        inclusive_ns minus the sum of inclusive_ns of its direct children.
        Events are already ordered by start; parent-of relation is via
        ``parent_ordinal`` so this is a single pass.
        """
        # inclusive-of-children per parent
        child_inclusive: dict[int, int] = {}
        for e in self._events:
            if e.parent_ordinal is None:
                continue
            child_inclusive[e.parent_ordinal] = (
                child_inclusive.get(e.parent_ordinal, 0) + e.inclusive_ns
            )
        for e in self._events:
            e.self_ns = e.inclusive_ns - child_inclusive.get(e.ordinal, 0)


class _Region:
    __slots__ = ("_rec", "_name", "_meta", "_ev")

    def __init__(self, rec: TimingRecorder, name: str, meta: dict[str, Any]) -> None:
        self._rec = rec
        self._name = name
        self._meta = meta
        self._ev: Optional[_Event] = None

    def __enter__(self) -> _Event:
        self._ev = self._rec._start(self._name, self._meta)
        return self._ev

    def __exit__(self, exc_type, exc, tb) -> bool:
        err = None if exc is None else f"{exc_type.__name__}: {exc}"
        assert self._ev is not None
        self._rec._finish(self._ev, err)
        # Do not suppress exceptions — preserve caller behavior.
        return False


# ---------------------------------------------------------------------------
# No-op recorder for the disabled case, so patched call sites can stay
# unconditional. Same interface, zero cost.

class _NullRecorder:
    run_meta: dict[str, Any] = {}

    def stage(self, name: str, **meta: Any) -> "_NullRegion":
        return _NullRegion()

    def set_run_meta(self, **kv: Any) -> None:  # noqa: D401 - protocol match
        return None

    def dump_json(self, path: str) -> None:  # noqa: D401
        return None

    def finalize(self) -> None:  # noqa: D401
        return None


class _NullRegion:
    def __enter__(self) -> Any:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


# ---------------------------------------------------------------------------
# Module-level singleton — Inductor is single-process per compile, and the
# recorder is thread-safe, so one instance is fine.

if _ENABLED:
    RECORDER: Any = TimingRecorder()
else:
    RECORDER = _NullRecorder()


def stage(name: str, **meta: Any) -> ContextManager[Any]:
    return RECORDER.stage(name, **meta)


def set_run_meta(**kv: Any) -> None:
    RECORDER.set_run_meta(**kv)


def dump_and_finalize(path: str) -> None:
    RECORDER.finalize()
    RECORDER.dump_json(path)


__all__ = [
    "is_enabled",
    "stage",
    "set_run_meta",
    "dump_and_finalize",
    "RECORDER",
]

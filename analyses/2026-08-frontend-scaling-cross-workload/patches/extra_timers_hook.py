"""Install/uninstall the extra_timers.install_extra_timers() call from
`torch_spyre/_inductor/__init__.py`.

Adds:
  - `from . import extra_timers as _extra_timers` import
  - `_extra_timers.install_extra_timers()` call inside the compile_fx
    wrapper, right after `uses_spyre = _uses_spyre(gm, example_inputs)`.

Idempotent: checks marker before applying/removing.
"""
from __future__ import annotations

import os
import sys

TARGET_FILE = os.environ.get(
    "INDUCTOR_INIT_PATH",
    os.path.expanduser("~/pr3806/torch-spyre/torch_spyre/_inductor/__init__.py"),
)

IMPORT_ANCHOR = "from . import timing_recorder as _tr"
IMPORT_INJECT = "from . import extra_timers as _extra_timers  # inserted by extra_timers_hook patch\n"

CALL_MARKER = "        def _wrapper(gm, example_inputs, *args, **kwargs):\n            uses_spyre = _uses_spyre(gm, example_inputs)\n"
CALL_MARKER_NEW = (
    "        def _wrapper(gm, example_inputs, *args, **kwargs):\n"
    "            uses_spyre = _uses_spyre(gm, example_inputs)\n"
    "            if uses_spyre:\n"
    "                _extra_timers.install_extra_timers()\n"
)


def apply() -> None:
    text = open(TARGET_FILE).read()
    if "_extra_timers.install_extra_timers()" in text:
        print(f"already patched: {TARGET_FILE}")
        return

    if IMPORT_INJECT not in text:
        idx = text.find(IMPORT_ANCHOR)
        if idx < 0:
            print(f"FATAL: import anchor missing", file=sys.stderr)
            sys.exit(2)
        # Insert AFTER the anchor line (so it sits with sibling imports).
        line_end = text.find("\n", idx)
        text = text[:line_end + 1] + IMPORT_INJECT + text[line_end + 1:]

    c = text.count(CALL_MARKER)
    if c != 1:
        print(f"FATAL: call anchor count = {c}", file=sys.stderr)
        sys.exit(2)
    text = text.replace(CALL_MARKER, CALL_MARKER_NEW, 1)

    open(TARGET_FILE, "w").write(text)
    print(f"patched: {TARGET_FILE}")


def revert() -> None:
    text = open(TARGET_FILE).read()
    if IMPORT_INJECT in text:
        text = text.replace(IMPORT_INJECT, "")
    if CALL_MARKER_NEW in text:
        text = text.replace(CALL_MARKER_NEW, CALL_MARKER)
    open(TARGET_FILE, "w").write(text)
    print(f"reverted: {TARGET_FILE}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("apply", "revert"):
        print("usage: python extra_timers_hook.py {apply|revert}", file=sys.stderr)
        sys.exit(2)
    (apply if sys.argv[1] == "apply" else revert)()

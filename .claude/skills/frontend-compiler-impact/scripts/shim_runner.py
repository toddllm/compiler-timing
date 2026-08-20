"""Explicit runner for a harness under the timing shim.

Usage:
    python shim_runner.py <harness.py> <harness_args...>

The shim (timing_shim.py in the same directory) is imported first, then
sys.argv is set to the harness argv and the harness is executed.
"""
from __future__ import annotations

import os
import runpy
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Install shim.
import timing_shim  # noqa: F401

if len(sys.argv) < 2:
    print("usage: shim_runner.py <harness.py> [args...]", file=sys.stderr)
    sys.exit(2)

harness = sys.argv[1]
sys.argv = [harness] + sys.argv[2:]

# Run as __main__ so the harness's if __name__ == "__main__": block fires.
runpy.run_path(harness, run_name="__main__")

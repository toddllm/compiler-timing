#!/usr/bin/env bash
# Forward-compat validation ladder — Stages 0..3, cheap end.
#
# Runs on the fresh pod itself (not from the laptop). Given a venv
# and an output directory, it drives Stages 0..3 of the ladder
# described in `references/validation-ladder.md` and writes, per
# stage, a raw `.log` and a small `.result` JSON. The ladder is
# strictly ordered: a failed stage stops the run — a broken import
# would make a Stage 2 compile look like a compiler bug, and a
# broken Stage 2 would make Stage 3 look like a pass-level bug.
#
# Usage:
#   run_compat_smoke.sh --venv PATH --out-dir DIR --stage-through {0,1,2,3}
#
# Layout of the output directory after a run:
#   <out-dir>/
#     stage_0.log        raw stdout+stderr from the stage
#     stage_0.result     {"stage":0,"status":"pass","duration_s":N,"notes":"..."}
#     stage_1.log        (only if stage 0 passed)
#     stage_1.result
#     stage_2.log        (only if stage 1 passed)
#     stage_2.result
#     stage_3.log        (only if stage 2 passed)
#     stage_3.result
#     summary.json       overall verdict, last stage, timestamp
#
# Exit codes:
#   0  — every requested stage passed
#   1  — a stage failed; the failed stage number is printed to
#        stderr and encoded in summary.json
#   2  — usage error (bad flags, missing venv, etc.)
#
# Design constraints (from references/validation-ladder.md):
#   - Stage 1 rebuild is SKIPPED here: the fresh pod's venv already
#     has torch-spyre installed (nightly proxy). We still verify the
#     C extension imports cleanly against the currently-loaded torch.
#     The full rebuild lives in the ladder's Stage 1 doc; this smoke
#     is the cheap variant meant to gate later stages during a run.
#   - Stage 3's test list is HAND-PICKED from tests/inductor/. It
#     excludes coarse-tile suites (test_coarse_tile_e2e,
#     test_coarse_tiling) because those are Stage 6 concerns and
#     take pod-minutes each; the list here is cheap fixture-level
#     tests that exercise the frontend of the compiler without
#     dispatching real coarse-tile work.
#   - Any Stage-3 test that runs past 120s is aborted. That's a
#     load-bearing signal — the point of this stage is to detect
#     cheap forward-compat breaks, not to profile long tests.
#   - The torch pin is NOT hard-coded: Stage 1's log records it by
#     re-reading pyproject.toml at runtime.

set -uo pipefail

# Source Spyre runtime env (LD_LIBRARY_PATH, PYTHONPATH, PATH, and env
# vars like SPYRE_COMMS_INSTALL_DIR) so torch_spyre's _C.so can find
# libspyre_comms.so.1 and other runtime libs. Login shells source this
# automatically; the skill's scripts are typically launched from
# `oc exec -- bash -c` (non-login) so we source it explicitly.
if [ -f /etc/profile.d/ibm-aiu-setup.sh ]; then
    set +u
    # shellcheck disable=SC1091
    source /etc/profile.d/ibm-aiu-setup.sh
    set -u
fi

# --------------------------------------------------------------------
# Arg parsing
# --------------------------------------------------------------------

VENV=""
OUT_DIR=""
STAGE_THROUGH=""

usage() {
    cat >&2 <<EOF
usage: run_compat_smoke.sh --venv PATH --out-dir DIR --stage-through {0,1,2,3}

  --venv           Path to the venv to activate before each stage.
                   Typically \$HOME/torch-spyre-work/torch-spyre/.venv on
                   the a5-deepview fresh pod.
  --out-dir        Directory to write stage_N.log / stage_N.result /
                   summary.json into. Created if missing.
  --stage-through  Highest stage to run (inclusive). Lower stages are
                   always run — the ladder is not skippable.

Exit codes: 0 all requested stages passed; 1 a stage failed; 2 usage error.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --venv)          VENV="${2:-}";          shift 2 ;;
        --out-dir)       OUT_DIR="${2:-}";       shift 2 ;;
        --stage-through) STAGE_THROUGH="${2:-}"; shift 2 ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$VENV" ] || [ -z "$OUT_DIR" ] || [ -z "$STAGE_THROUGH" ]; then
    usage
    exit 2
fi

case "$STAGE_THROUGH" in
    0|1|2|3) : ;;
    *) echo "--stage-through must be one of 0,1,2,3 (got: $STAGE_THROUGH)" >&2; exit 2 ;;
esac

if [ ! -f "$VENV/bin/activate" ]; then
    echo "FATAL: venv activate script not found at $VENV/bin/activate" >&2
    exit 2
fi

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

# JSON-escape a string for embedding in a result file. Handles the
# characters that actually show up in Python tracebacks — backslash,
# double quote, newline, carriage return, tab. We keep this in pure
# bash rather than shelling out to python so the helper still works
# even if the very stage under test broke the venv's python.
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

write_result() {
    # write_result <stage_num> <pass|fail> <duration_s> <notes>
    local stage="$1" status="$2" dur="$3" notes="$4"
    local esc
    esc="$(json_escape "$notes")"
    cat >"$OUT_DIR/stage_${stage}.result" <<EOF
{"stage": ${stage}, "status": "${status}", "duration_s": ${dur}, "notes": "${esc}"}
EOF
}

now_s() { date +%s; }

# activate_venv is inlined into each stage's subshell so a stage that
# corrupts the environment cannot bleed into the next stage.
ACTIVATE_LINE="source \"$VENV/bin/activate\""

# --------------------------------------------------------------------
# Stage 0 — ENVIRONMENT
# --------------------------------------------------------------------
# Cheap smoke of the runtime: python/torch/torch_spyre import, spyre
# device enumeration, one eager op. If this fails there is no point
# running any later stage — a broken import at Stage 3 would look
# indistinguishable from an ABI break here.

run_stage_0() {
    local log="$OUT_DIR/stage_0.log"
    local t0 t1 dur rc notes
    t0=$(now_s)

    (
        # shellcheck disable=SC1090
        source "$VENV/bin/activate"
        set -e
        python -c "import sys; print('python_version =', sys.version.split()[0])"
        python -c "import torch; print('torch_version =', torch.__version__); print('torch_file =', torch.__file__)"
        python -c "import torch_spyre; print('torch_spyre_file =', torch_spyre.__file__)"
        python - <<'PY'
import torch, torch_spyre
n = torch.spyre.device_count()
print("spyre_device_count =", n)
assert n >= 1, "no spyre device visible"
x = torch.arange(8, device="spyre") + 1
y = x * 2
ok = (y.cpu() == torch.arange(2, 18, 2)).all().item()
print("eager_op_ok =", ok)
assert ok, "eager op mismatch on spyre device"
PY
    ) >"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_result 0 pass "$dur" "env smoke ok"
        return 0
    fi

    # Distinguish the two common failure surfaces so the notes field
    # points a human at the right reference section.
    if grep -q "no spyre device visible\|spyre_device_count = 0" "$log"; then
        notes="device count == 0; INSUFFICIENT_EVIDENCE per validation-ladder.md#stage-0"
    elif grep -q "ImportError\|ModuleNotFoundError\|undefined symbol" "$log"; then
        notes="import/ABI failure; see stage_0.log tail for symbol"
    else
        notes="stage 0 failed rc=$rc; see stage_0.log"
    fi
    write_result 0 fail "$dur" "$notes"
    return 1
}

# --------------------------------------------------------------------
# Stage 1 — IMPORT (build skipped: nightly-proxy venv)
# --------------------------------------------------------------------
# We do NOT rebuild _C.so here — the venv is provisioned via the
# nightly proxy per references/environment-policy.md. What we DO
# verify is that the shipped _C.so loads against the currently
# resolved torch, and that the primary compiler-side Python modules
# import without exercising the compiler yet. Also records the
# declared torch pin from pyproject.toml (re-read at runtime).

run_stage_1() {
    local log="$OUT_DIR/stage_1.log"
    local t0 t1 dur rc notes
    t0=$(now_s)

    (
        # shellcheck disable=SC1090
        source "$VENV/bin/activate"
        set -e

        # Re-read the torch pin at runtime. NEVER hard-code the pin
        # in this script — the policy is that scripts read the pin,
        # not that it's baked into skills.
        python - <<'PY'
import tomllib, pathlib, os
# The venv is created inside the torch-spyre checkout; find the
# nearest pyproject.toml walking up from the interpreter's cwd.
here = pathlib.Path(os.getcwd())
for cand in [here, *here.parents]:
    py = cand / "pyproject.toml"
    if py.exists():
        pin = tomllib.loads(py.read_text())
        deps = pin.get("project", {}).get("dependencies", [])
        tp = next((d for d in deps if d.split()[0].startswith("torch")), None)
        print(f"declared_torch_pin_source = {py}")
        print(f"declared_torch_pin = {tp}")
        break
else:
    print("declared_torch_pin = <pyproject.toml not found from cwd>")
PY

        # C-extension import against currently-loaded torch. Any
        # undefined-symbol failure here IS the finding; we do not
        # attempt to rebuild in Stage 1 of a smoke run.
        python - <<'PY'
import importlib, torch
# Hard-required modules (must exist across all torch-spyre revs
# post-2026-06). Optional modules are probed but don't fail Stage 1.
required = [
    "torch_spyre",
    "torch_spyre._C",
    "torch_spyre._inductor",
    "torch_spyre._inductor.lowering",
]
optional = [
    "torch_spyre._inductor.decomp",       # may not exist in older revs
    "torch_spyre._inductor.scheduler",
    "torch_spyre._inductor.dedup_constants",
]
for m in required:
    importlib.import_module(m)
    print(f"import_ok = {m}")
for m in optional:
    try:
        importlib.import_module(m)
        print(f"import_ok = {m}")
    except ModuleNotFoundError:
        print(f"import_optional_missing = {m}")
print(f"resolved_torch = {torch.__version__}")
PY

        # Verify Spyre device is visible after autoload. torch-spyre
        # does NOT register a custom dynamo backend called 'spyre'; it
        # patches Inductor lowerings for tensors on the 'spyre' device.
        # The real check is that torch.spyre.device_count() > 0 AND
        # the 'inductor' backend is available (it's the default).
        python - <<'PY'
import torch
assert hasattr(torch, "spyre"), "torch.spyre module not registered (autoload failed?)"
n = torch.spyre.device_count()
print(f"spyre_device_count = {n}")
assert n >= 1, f"expected >=1 Spyre device, got {n}"
from torch._dynamo import list_backends
backends = list_backends()
assert "inductor" in backends, f"inductor backend missing: {backends}"
print(f"inductor_backend_present = True")
PY
    ) >"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_result 1 pass "$dur" "primary imports ok; spyre backend registered"
        return 0
    fi

    if grep -q "undefined symbol\|ImportError.*_C" "$log"; then
        notes="C-extension ABI mismatch against current torch; see stage_1.log"
    elif grep -q "ModuleNotFoundError\|ImportError" "$log"; then
        notes="module import failure in primary compiler modules"
    elif grep -q "spyre backend not registered" "$log"; then
        notes="entry-point autoload did not register 'spyre' backend"
    else
        notes="stage 1 failed rc=$rc; see stage_1.log"
    fi
    write_result 1 fail "$dur" "$notes"
    return 1
}

# --------------------------------------------------------------------
# Stage 2 — MINIMAL COMPILE
# --------------------------------------------------------------------
# One trivial function through torch.compile on Spyre, compared to a
# CPU eager reference. Fresh cache dir. If this fails, Stage 3's
# richer inputs cannot be interpreted.

run_stage_2() {
    local log="$OUT_DIR/stage_2.log"
    local t0 t1 dur rc notes
    t0=$(now_s)

    local cache="/tmp/torchind-fc-stage2-$$"
    rm -rf "$cache"

    (
        # shellcheck disable=SC1090
        source "$VENV/bin/activate"
        set -e
        export TORCHINDUCTOR_CACHE_DIR="$cache"
        python - <<'PY'
import torch, torch_spyre  # noqa: F401

def f(a, b):
    return a + b

# torch-spyre does NOT register a custom dynamo backend named 'spyre'.
# It patches Inductor lowerings for tensors that live on the 'spyre'
# device. Spyre lowering happens automatically when Inductor sees
# operands on the spyre device. So: backend='inductor' with .to('spyre').
fc = torch.compile(f, backend="inductor")

# Default Spyre dtype is fp16. fp32 works too but noise from
# torch.arange casting differs; fp16 exercises the canonical path.
a_cpu = torch.arange(16, dtype=torch.float16)
b_cpu = torch.arange(16, dtype=torch.float16) * 2.0
a_sp = a_cpu.to("spyre")
b_sp = b_cpu.to("spyre")

out_sp = fc(a_sp, b_sp).cpu()
out_cpu = f(a_cpu, b_cpu)

# fp16 noise on a trivial add is small but nonzero. rtol/atol below
# reflect the observed floor from cases/live-current-main-F3 stage2
# runs (max_delta ~0.02 for pointwise). Exact-zero would be wrong.
torch.testing.assert_close(out_sp, out_cpu, rtol=1e-3, atol=1e-3)
print("stage2_compile_ok = True")
print("shape =", tuple(out_sp.shape))
print("dtype =", out_sp.dtype)
max_delta = (out_sp - out_cpu).abs().max().item()
print(f"max_delta = {max_delta}")
PY
    ) >"$log" 2>&1
    rc=$?

    rm -rf "$cache"
    t1=$(now_s); dur=$((t1 - t0))

    if [ "$rc" -eq 0 ]; then
        write_result 2 pass "$dur" "trivial add compiled and matched CPU"
        return 0
    fi

    if grep -q "assert_close\|Tensor-likes are not close" "$log"; then
        notes="numerical mismatch between spyre-compiled and CPU eager"
    elif grep -q "BackendCompilerFailed\|torch._dynamo.exc" "$log"; then
        notes="dynamo/inductor compile failed on trivial add; see stage_2.log"
    else
        notes="stage 2 failed rc=$rc; see stage_2.log"
    fi
    write_result 2 fail "$dur" "$notes"
    return 1
}

# --------------------------------------------------------------------
# Stage 3 — HAND-PICKED CHEAP INDUCTOR TESTS
# --------------------------------------------------------------------
# The point of this stage is to catch forward-compat breaks in the
# frontend passes (decomp/lowering/logging/dedup/etc) without paying
# for the coarse-tile suite. The list below was chosen by:
#   - excluding test_coarse_tile_e2e.py and test_coarse_tiling.py
#     (Stage 6 concerns)
#   - preferring files with many small fixture-level tests
#   - preferring files that don't already have a Stage 3 smoke in
#     tests/frontend_smoke/ (the ladder covers those elsewhere)
#
# Each test is timed. A single test exceeding 120s is aborted with
# SIGTERM (then SIGKILL after a grace period) — that is a Stage 6
# concern, not a forward-compat smoke concern, and we don't want the
# whole ladder to stall on a slow test.
#
# NOTE: the tests are launched via pytest so a missing test is
# reported cleanly (rc == 5) rather than as an import error.

STAGE3_TESTS=(
    "tests/inductor/test_building_blocks.py"
    "tests/inductor/test_dedup_constants.py"
    "tests/inductor/test_logging.py"
    "tests/inductor/test_overwrite.py"
    "tests/inductor/test_inductor_scalar.py"
    "tests/inductor/test_copy_back_elision.py"
)

STAGE3_PER_TEST_TIMEOUT_S=120

run_stage_3() {
    local log="$OUT_DIR/stage_3.log"
    local t0 t1 dur rc notes
    t0=$(now_s)
    : >"$log"

    # Locate the torch-spyre checkout so the test paths resolve.
    #
    # Preference order:
    #   1. TORCH_SPYRE_TREE env var — the authoritative override the
    #      setup scripts already use. If set, honor it.
    #   2. Walk up from the venv looking for tests/inductor or a
    #      torch-spyre/tests/inductor sibling — matches the layout
    #      setup_supported_env.sh produces
    #      ($WORKDIR/.venv-supported, $WORKDIR/torch-spyre/).
    #
    # Rationale (F9, 2026-08-24): on the fresh pod, /home/tdeshane
    # contains BOTH forward-tree/torch-spyre (the tree we built the
    # forward venv against) AND torch-spyre (a stale checkout from
    # prior sessions). Under NIGHTLY_PROXY the forward venv lives at
    # /home/tdeshane/forward/.venv-latest, so the walk-up hits
    # /home/tdeshane/torch-spyre first and Stage 3 runs the wrong
    # tests against the right venv. Honoring $TORCH_SPYRE_TREE lets
    # the caller — or the pytorch_selection.json chain — pin it.
    local tree=""
    if [ -n "${TORCH_SPYRE_TREE:-}" ] && [ -d "${TORCH_SPYRE_TREE}/tests/inductor" ]; then
        tree="$TORCH_SPYRE_TREE"
        echo "# torch_spyre_tree = $tree (from TORCH_SPYRE_TREE env)" >>"$log"
    else
        local cand="$VENV"
        for _ in 1 2 3 4 5; do
            cand="$(dirname "$cand")"
            if [ -d "$cand/tests/inductor" ]; then
                tree="$cand"; break
            fi
            if [ -d "$cand/torch-spyre/tests/inductor" ]; then
                tree="$cand/torch-spyre"; break
            fi
        done
    fi
    if [ -z "$tree" ]; then
        write_result 3 fail 0 "could not locate torch-spyre checkout from venv path $VENV (set TORCH_SPYRE_TREE to override)"
        return 1
    fi
    # log the resolved tree unless we already did (env-override branch above)
    if [ -z "${TORCH_SPYRE_TREE:-}" ]; then
        echo "# torch_spyre_tree = $tree (walked up from venv)" >>"$log"
    fi

    local any_fail=0
    local any_timeout=0
    local ran=0
    local passed=0

    for rel in "${STAGE3_TESTS[@]}"; do
        local abs="$tree/$rel"
        if [ ! -f "$abs" ]; then
            echo "# SKIP $rel  (not present in this checkout)" >>"$log"
            continue
        fi
        ran=$((ran + 1))

        local cache="/tmp/torchind-fc-stage3-$(basename "$rel" .py)-$$"
        rm -rf "$cache"

        local test_t0 test_t1 test_dur test_rc
        test_t0=$(now_s)

        # `timeout --kill-after` sends SIGTERM at the deadline, then
        # SIGKILL 10s later if the test is still running. Exit code
        # 124 means the kill was needed.
        (
            # shellcheck disable=SC1090
            source "$VENV/bin/activate"
            cd "$tree"
            export TORCHINDUCTOR_CACHE_DIR="$cache"
            timeout --kill-after=10s "${STAGE3_PER_TEST_TIMEOUT_S}s" \
                python -m pytest -x -q --no-header "$rel"
        ) >>"$log" 2>&1
        test_rc=$?
        test_t1=$(now_s); test_dur=$((test_t1 - test_t0))
        rm -rf "$cache"

        if [ "$test_rc" -eq 0 ]; then
            passed=$((passed + 1))
            echo "# STAGE3_OK  $rel  (${test_dur}s)" >>"$log"
        elif [ "$test_rc" -eq 124 ] || [ "$test_rc" -eq 137 ]; then
            any_timeout=1
            any_fail=1
            echo "# STAGE3_TIMEOUT  $rel  (>${STAGE3_PER_TEST_TIMEOUT_S}s, escalate to Stage 6)" >>"$log"
        else
            any_fail=1
            echo "# STAGE3_FAIL  $rel  rc=$test_rc  (${test_dur}s)" >>"$log"
        fi
    done

    t1=$(now_s); dur=$((t1 - t0))

    if [ "$ran" -eq 0 ]; then
        write_result 3 fail "$dur" "none of the hand-picked stage-3 tests were present in the tree"
        return 1
    fi

    if [ "$any_fail" -eq 0 ]; then
        write_result 3 pass "$dur" "all $passed hand-picked cheap tests passed"
        return 0
    fi

    if [ "$any_timeout" -eq 1 ]; then
        notes="at least one test exceeded ${STAGE3_PER_TEST_TIMEOUT_S}s (Stage 6 concern); $passed/$ran passed"
    else
        notes="$passed/$ran cheap tests passed; see stage_3.log for failing tests"
    fi
    write_result 3 fail "$dur" "$notes"
    return 1
}

# --------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------

write_summary() {
    # write_summary <verdict> <last_stage> <failed_stage_or_-1>
    local verdict="$1" last="$2" failed="$3"
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cat >"$OUT_DIR/summary.json" <<EOF
{
  "verdict": "${verdict}",
  "last_stage_run": ${last},
  "failed_stage": ${failed},
  "stage_through_requested": ${STAGE_THROUGH},
  "venv": "$(json_escape "$VENV")",
  "timestamp_utc": "${ts}"
}
EOF
}

FAILED_STAGE=-1
LAST_STAGE=-1

for stage in 0 1 2 3; do
    if [ "$stage" -gt "$STAGE_THROUGH" ]; then
        break
    fi
    case "$stage" in
        0) run_stage_0 ;;
        1) run_stage_1 ;;
        2) run_stage_2 ;;
        3) run_stage_3 ;;
    esac
    rc=$?
    LAST_STAGE=$stage
    if [ "$rc" -ne 0 ]; then
        FAILED_STAGE=$stage
        break
    fi
done

if [ "$FAILED_STAGE" -ge 0 ]; then
    write_summary "FAIL" "$LAST_STAGE" "$FAILED_STAGE"
    echo "stage $FAILED_STAGE failed; see $OUT_DIR/stage_${FAILED_STAGE}.log" >&2
    exit 1
fi

write_summary "PASS" "$LAST_STAGE" "-1"
exit 0

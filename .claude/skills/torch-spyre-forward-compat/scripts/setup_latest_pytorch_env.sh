#!/usr/bin/env bash
# Provision a fresh venv on the pod containing:
#   - a torch installed at (or against) the forward pytorch commit under
#     evaluation, and
#   - torch-spyre installed editable against that torch.
#
# The torch-spyre install step mirrors the canonical dev-flow build:
#   references/canonical-dev-flow.md
#   /Users/tdeshane/torch-spyre-docs/scripts/build-torch-spyre.sh
# specifically the `CXX="ccache <gcc-toolset c++>"; pip install -e .
# --no-deps --no-build-isolation -vvv --verbose` incantation, with the
# same prerequisite pip installs the IBM torch-spyre-docs dev_install.md
# lists (nanobind, ninja, pybind11, build, cmake, regex, wheel, plus
# requirements/dev.txt minus torch). --no-deps is what keeps the
# forward-compat torch (either the source-built one from
# EXACT_UPSTREAM_MAIN or the nightly from NIGHTLY_PROXY) from being
# evicted mid-install when pip resolves torch-spyre's declared pin.
#
# This script runs on the fresh forward-compat pod (typically
# tdeshane-forward-compat-2026-08-21 in namespace a5-deepview). It is
# invoked once per FORWARD state (FORWARD_BEFORE_FIX or FORWARD_AFTER_FIX);
# SUPPORTED_CONTROL uses the pod's declared-pin path, not this script.
#
# Two modes — the FORWARD state's substrate is one of:
#
#   EXACT_UPSTREAM_MAIN  (default; the empirically-honest path)
#     Build torch from source at the exact pytorch SHA the case names.
#     A wall-clock build budget (default 3 hours) bounds the attempt.
#     If the source build exceeds the budget or fails, the script falls
#     back to NIGHTLY_PROXY and records why.
#
#   NIGHTLY_PROXY  (fallback)
#     Install a torch nightly wheel and read its embedded
#     torch.version.git_version as the actual SHA. This substitutes a
#     nearby SHA for the requested one; the case document must flag the
#     substitution and cite the reason.
#
# What the script does NOT do:
#   - Does not resolve pytorch or torch-spyre HEADs from GitHub. Callers
#     pass explicit SHAs. (resolve_pytorch_head.sh / resolve_torch_spyre_head.sh
#     produce those SHAs upstream of this script.)
#   - Does not modify torch-spyre's pin. If pip refuses the install
#     because torch-spyre declares torch~=2.13.0 and the forward wheel
#     is 2.14+, the correct response is PIN_CONFLICT recorded at Stage 2
#     of the ladder, not editing pyproject.toml.
#   - Does not run the ladder. That is ladder_runner.py's job. This
#     script only produces the substrate.
#
# Outputs (all under --workdir):
#   .venv-latest/                 fresh venv, activated for downstream steps
#   pytorch/                      pytorch source clone at PYTORCH_SHA
#                                 (EXACT_UPSTREAM_MAIN only)
#   ccache/                       fresh ccache dir (EXACT_UPSTREAM_MAIN only)
#   pytorch_build.log             torch source build stdout+stderr
#                                 (EXACT_UPSTREAM_MAIN only)
#   pytorch_nightly.log           nightly install log + resolved version
#                                 (NIGHTLY_PROXY only)
#   torch_spyre_install.log       editable install of torch-spyre
#   pytorch_selection.json        machine-readable substrate record
#
# Exit codes:
#   0   substrate ready; pytorch_selection.json written
#   2   argument error
#   3   preflight failure (missing torch-spyre tree, no python3, etc.)
#   4   NIGHTLY_PROXY fallback also failed (both paths exhausted)
#
# On a build timeout in EXACT_UPSTREAM_MAIN, the script re-invokes ITSELF
# with --mode NIGHTLY_PROXY --pytorch-sha "" and records the fallback
# rationale in pytorch_selection.json. The caller sees exit 0 iff one of
# the two paths produced a usable venv.

set -euo pipefail

# Source /etc/profile.d/ibm-aiu-setup.sh if present. See
# setup_supported_env.sh for the full rationale — Spyre runtime env vars
# only get set by login shells, and `oc exec -- bash -c` skips them.
if [ -f /etc/profile.d/ibm-aiu-setup.sh ]; then
    # shellcheck disable=SC1091
    source /etc/profile.d/ibm-aiu-setup.sh
fi

# --- Argument parsing -------------------------------------------------------

TORCH_SPYRE_SHA=""
PYTORCH_SHA=""
WORKDIR=""
MODE="EXACT_UPSTREAM_MAIN"
BUILD_BUDGET_HOURS="3"

usage() {
    cat >&2 <<'USAGE'
usage: setup_latest_pytorch_env.sh \
           --torch-spyre-sha SHA \
           --pytorch-sha SHA \
           --workdir DIR \
           [--mode EXACT_UPSTREAM_MAIN|NIGHTLY_PROXY] \
           [--build-budget-hours N]

EXACT_UPSTREAM_MAIN (default) builds torch from source at --pytorch-sha,
bounded by --build-budget-hours (default 3). On timeout or non-zero exit,
falls back automatically to NIGHTLY_PROXY.

NIGHTLY_PROXY installs a torch nightly wheel and reports the resolved
embedded git SHA. --pytorch-sha may be empty in this mode; if provided
it is recorded as requested_sha for later comparison against actual_sha.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --torch-spyre-sha) TORCH_SPYRE_SHA="${2:-}"; shift 2 ;;
        --pytorch-sha)     PYTORCH_SHA="${2:-}"; shift 2 ;;
        --workdir)         WORKDIR="${2:-}"; shift 2 ;;
        --mode)            MODE="${2:-}"; shift 2 ;;
        --build-budget-hours) BUILD_BUDGET_HOURS="${2:-}"; shift 2 ;;
        -h|--help)         usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$TORCH_SPYRE_SHA" ] || [ -z "$WORKDIR" ]; then
    echo "FATAL: --torch-spyre-sha and --workdir are required" >&2
    usage
    exit 2
fi

case "$MODE" in
    EXACT_UPSTREAM_MAIN)
        if [ -z "$PYTORCH_SHA" ]; then
            echo "FATAL: --pytorch-sha required for EXACT_UPSTREAM_MAIN" >&2
            exit 2
        fi
        ;;
    NIGHTLY_PROXY) ;;
    *) echo "FATAL: unknown --mode: $MODE" >&2; exit 2 ;;
esac

# Numeric budget check.
if ! [[ "$BUILD_BUDGET_HOURS" =~ ^[0-9]+$ ]]; then
    echo "FATAL: --build-budget-hours must be a positive integer" >&2
    exit 2
fi

# --- Preflight --------------------------------------------------------------

TORCH_SPYRE_TREE="${TORCH_SPYRE_TREE:-$HOME/torch-spyre-work/torch-spyre}"
if [ ! -d "$TORCH_SPYRE_TREE" ]; then
    echo "FATAL: torch-spyre tree not found at $TORCH_SPYRE_TREE" >&2
    echo "       set TORCH_SPYRE_TREE to override" >&2
    exit 3
fi
if [ ! -f "$TORCH_SPYRE_TREE/pyproject.toml" ]; then
    echo "FATAL: $TORCH_SPYRE_TREE/pyproject.toml missing" >&2
    exit 3
fi

# Confirm the torch-spyre tree is at the recorded SHA, so the substrate
# we produce is provably tied to the case SHA. The forward-compat
# discipline forbids running against a drifted checkout.
ACTUAL_TS_SHA="$(git -C "$TORCH_SPYRE_TREE" rev-parse HEAD 2>/dev/null || echo unknown)"
if [ "$ACTUAL_TS_SHA" != "$TORCH_SPYRE_SHA" ]; then
    # Accept short-SHA prefix match too.
    case "$ACTUAL_TS_SHA" in
        "$TORCH_SPYRE_SHA"*) ;;
        *)
            echo "FATAL: torch-spyre tree HEAD ($ACTUAL_TS_SHA) does not match" >&2
            echo "       requested --torch-spyre-sha ($TORCH_SPYRE_SHA)." >&2
            echo "       Re-check out the tree at the case SHA before running." >&2
            exit 3
            ;;
    esac
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "FATAL: python3 not on PATH" >&2
    exit 3
fi

mkdir -p "$WORKDIR"
WORKDIR="$(cd "$WORKDIR" && pwd)"

# --- Helper: emit pytorch_selection.json ------------------------------------
# Arguments are passed through env for JSON safety.

emit_selection_json() {
    local out="$WORKDIR/pytorch_selection.json"
    local sel_mode="${1}"
    local sel_requested="${2}"
    local sel_actual="${3}"
    local sel_version="${4}"
    local sel_build_seconds="${5}"   # integer or the string "null"
    local sel_fallback_reason="${6}" # string or the string "null"

    python3 - "$out" "$sel_mode" "$sel_requested" "$sel_actual" \
                     "$sel_version" "$sel_build_seconds" "$sel_fallback_reason" \
        <<'PYEOF'
import json, sys
out, mode, requested, actual, version, build_seconds, fallback = sys.argv[1:8]
def _maybe_null(s):
    return None if s == "null" or s == "" else s
def _maybe_int(s):
    return None if s == "null" or s == "" else int(s)
doc = {
    "mode": mode,
    "requested_sha": _maybe_null(requested),
    "actual_sha": _maybe_null(actual),
    "version": _maybe_null(version),
    "build_seconds": _maybe_int(build_seconds),
    "fallback_reason": _maybe_null(fallback),
}
with open(out, "w") as f:
    json.dump(doc, f, indent=2, sort_keys=True)
    f.write("\n")
PYEOF
}

# --- Fresh venv -------------------------------------------------------------

VENV="$WORKDIR/.venv-latest"
if [ -e "$VENV" ]; then
    # Forward-compat discipline: never inherit a prior venv. Remove any
    # stale directory left over from a previous invocation on this workdir.
    rm -rf "$VENV"
fi
# --system-site-packages so the venv can see any pod-image-provided
# native libraries (e.g. gcc-toolset runtimes surfaced through site
# packages) while still isolating the pip-managed torch stack. The
# canonical dev flow assumes a dev image that layers system-provided
# tooling under the venv.
python3 -m venv --system-site-packages "$VENV"
# shellcheck disable=SC1090
source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip wheel setuptools

# --- Mode: NIGHTLY_PROXY ----------------------------------------------------

run_nightly_proxy() {
    local requested_for_record="${1:-}"      # may be empty
    local fallback_reason="${2:-null}"

    echo "[setup_latest_pytorch_env] MODE=NIGHTLY_PROXY"
    echo "[setup_latest_pytorch_env] fallback_reason=$fallback_reason"

    local nightly_log="$WORKDIR/pytorch_nightly.log"
    : > "$nightly_log"

    # Use the CPU nightly index. Spyre does not publish its own torch
    # index; a device-specific wheel would be preferable if one existed,
    # so this substitution is noted in the log.
    echo "# torch nightly install ($(date -u +%FT%TZ))" >> "$nightly_log"
    echo "# NOTE: using CPU nightly index — no Spyre-specific torch nightly" >> "$nightly_log"
    echo "#       index is known. The kernel/device path is exercised via" >> "$nightly_log"
    echo "#       torch-spyre's own _C.so build, not via the torch wheel." >> "$nightly_log"

    if ! pip install --pre --quiet torch \
             --index-url https://download.pytorch.org/whl/nightly/cpu \
             >> "$nightly_log" 2>&1; then
        echo "FATAL: torch nightly install failed; see $nightly_log" >&2
        emit_selection_json "NIGHTLY_PROXY" "$requested_for_record" "" "" "null" \
            "nightly_install_failed"
        exit 4
    fi

    # Read the wheel's embedded torch.version.git_version.
    local version git_sha
    version="$(python -c 'import torch; print(torch.__version__)')"
    git_sha="$(python -c 'import torch; print(torch.version.git_version or "")')"
    echo "torch.__version__ = $version" >> "$nightly_log"
    echo "torch.version.git_version = $git_sha" >> "$nightly_log"

    if [ -z "$git_sha" ]; then
        echo "WARNING: nightly wheel did not embed a git_version" >> "$nightly_log"
    fi

    install_torch_spyre_editable

    emit_selection_json "NIGHTLY_PROXY" "$requested_for_record" \
        "$git_sha" "$version" "null" "$fallback_reason"
    return 0
}

# --- torch-spyre editable install (both modes) ------------------------------

install_torch_spyre_editable() {
    local log="$WORKDIR/torch_spyre_install.log"
    local build_log="$WORKDIR/build_latest.log"
    echo "# torch-spyre editable install ($(date -u +%FT%TZ))" > "$log"
    echo "# tree = $TORCH_SPYRE_TREE @ $ACTUAL_TS_SHA" >> "$log"
    echo "# canonical flow: references/canonical-dev-flow.md" >> "$log"
    echo "#                 /Users/tdeshane/torch-spyre-docs/scripts/build-torch-spyre.sh" >> "$log"

    # --- Prerequisite pip installs -----------------------------------------
    # Matches the IBM torch-spyre-docs dev_install.md order: a small set
    # of test/build helpers, then the "Install python packages needed to
    # build things" block, then torch-spyre's own requirements/dev.txt
    # with the torch line stripped so we do not clobber the forward
    # torch already in the venv.
    #
    # `expecttest wheel psutil pytest` are ambient dev prereqs the docs
    # list separately; nanobind is pinned to 2.9.2 by dev_install.md;
    # cmake is pinned to ~=3.26 by the same doc. We do NOT use
    # --no-deps here — these are leaf helpers whose own dep closure is
    # fine to resolve normally.
    echo "# prereq installs (expecttest wheel psutil pytest)" >> "$log"
    if ! pip install --quiet expecttest wheel psutil pytest >> "$log" 2>&1; then
        echo "FATAL: SUBSTRATE_FAILURE — prereq install (expecttest wheel psutil pytest) failed" >&2
        echo "SUBSTRATE_FAILURE: prereq install (expecttest wheel psutil pytest)" >> "$log"
        exit 3
    fi

    echo "# prereq installs (nanobind==2.9.2 ninja pybind11 build cmake~=3.26 regex)" >> "$log"
    if ! pip install --quiet nanobind==2.9.2 ninja pybind11 build "cmake~=3.26" regex \
            >> "$log" 2>&1; then
        echo "FATAL: SUBSTRATE_FAILURE — prereq install (build toolchain) failed" >&2
        echo "SUBSTRATE_FAILURE: prereq install (nanobind/ninja/pybind11/build/cmake/regex)" >> "$log"
        exit 3
    fi

    # torch-spyre's requirements/dev.txt minus any torch line — the
    # forward torch is already installed and must not be evicted.
    local dev_reqs="$TORCH_SPYRE_TREE/requirements/dev.txt"
    if [ -f "$dev_reqs" ]; then
        echo "# prereq installs ($dev_reqs, torch line stripped)" >> "$log"
        # PEP 503 name normalization: `torch` may appear as `torch`,
        # `Torch`, or `torch >= …` — strip any line whose first token
        # (after stripping comment/whitespace) normalizes to `torch`.
        # Anything else (torch-audio, torchvision, torch_xla, etc.) is
        # kept because normalize("torch-audio") != "torch".
        local filtered
        filtered="$(python - "$dev_reqs" <<'PYEOF'
import re, sys
def normalize(name):
    return re.sub(r"[-_.]+", "-", name).strip().lower()
name_re = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")
with open(sys.argv[1]) as f:
    for line in f:
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            sys.stdout.write(line)
            continue
        m = name_re.match(stripped)
        if m and normalize(m.group(1)) == "torch":
            # skip torch line
            continue
        sys.stdout.write(line)
PYEOF
)"
        if ! printf '%s' "$filtered" | pip install --quiet -r /dev/stdin \
                >> "$log" 2>&1; then
            echo "FATAL: SUBSTRATE_FAILURE — requirements/dev.txt install (minus torch) failed" >&2
            echo "SUBSTRATE_FAILURE: requirements/dev.txt (minus torch)" >> "$log"
            exit 3
        fi
    else
        echo "# note: $dev_reqs not present at this SHA — skipping dev-reqs step" >> "$log"
    fi

    # --- CXX / ccache launcher --------------------------------------------
    # Mirrors build-torch-spyre.sh verbatim: pick the newest gcc-toolset
    # c++ under /opt/rh and wrap it in ccache. Anything else (system
    # /usr/bin/c++, no gcc-toolset at all) is a substrate defect on the
    # pod image, not something to paper over.
    local tsxx
    tsxx="$(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ 2>/dev/null | tail -1)"
    if [ -z "$tsxx" ]; then
        echo "FATAL: SUBSTRATE_FAILURE — no /opt/rh/gcc-toolset-*/root/usr/bin/c++ on this pod" >&2
        echo "SUBSTRATE_FAILURE: gcc-toolset c++ not found under /opt/rh" >> "$log"
        exit 3
    fi
    export CXX="ccache $tsxx"
    if [ -z "$CXX" ] || [ "$CXX" = "ccache " ]; then
        echo "FATAL: SUBSTRATE_FAILURE — CXX resolved empty ($CXX)" >&2
        echo "SUBSTRATE_FAILURE: CXX empty after gcc-toolset probe" >> "$log"
        exit 3
    fi
    echo "# CXX=$CXX" >> "$log"

    # --- The editable install itself --------------------------------------
    # --no-deps prevents pip from touching the forward torch already in
    # the venv (torch-spyre's declared pin would otherwise trigger a
    # downgrade / eviction). --no-build-isolation keeps setup.py running
    # in this venv so it links against THIS torch, not an ephemeral one
    # pip would materialize behind a PEP 517 wall. -vvv --verbose keeps
    # the full compiler transcript in build_latest.log for later
    # attribution.
    #
    # This CAN still fail — e.g. a header incompatibility between the
    # forward torch and torch-spyre's C++ side. That is a real Stage-2
    # datum, not a script error: we tee it to build_latest.log,
    # summarize in torch_spyre_install.log, and return 0 so the ladder
    # runner is the authority on the Stage-2 verdict.
    echo "# invoking: pip install -e . --no-deps --no-build-isolation -vvv --verbose" >> "$log"
    : > "$build_log"
    set +e
    ( cd "$TORCH_SPYRE_TREE" && pip install -e . --no-deps --no-build-isolation -vvv --verbose ) \
        2>&1 | tee "$build_log" >> "$log"
    local rc=${PIPESTATUS[0]}
    set -e
    if [ "$rc" -eq 0 ]; then
        echo "editable install OK (build log: $build_log)" >> "$log"
    else
        echo "editable install FAILED (rc=$rc) — see $build_log for the full transcript" >> "$log"
        # Preserve for downstream ladder attribution; do not exit here.
    fi

    unset CXX

    # Import smoke — record but do not gate. The ladder's Stage 3 is
    # the authority on import success.
    python - >> "$log" 2>&1 <<'PYEOF' || true
try:
    import torch
    print("import torch OK; version=", torch.__version__)
except Exception as exc:
    print("import torch FAILED:", type(exc).__name__, exc)
try:
    import torch_spyre  # noqa: F401
    print("import torch_spyre OK")
except Exception as exc:
    print("import torch_spyre FAILED:", type(exc).__name__, exc)
PYEOF
}

# --- Mode: EXACT_UPSTREAM_MAIN ---------------------------------------------

run_exact_upstream_main() {
    echo "[setup_latest_pytorch_env] MODE=EXACT_UPSTREAM_MAIN"
    echo "[setup_latest_pytorch_env] pytorch SHA=$PYTORCH_SHA"
    echo "[setup_latest_pytorch_env] build budget=${BUILD_BUDGET_HOURS}h"

    local pytorch_dir="$WORKDIR/pytorch"
    if [ ! -d "$pytorch_dir/.git" ]; then
        rm -rf "$pytorch_dir"
        git clone --quiet https://github.com/pytorch/pytorch.git "$pytorch_dir"
    fi
    # Fetch the requested SHA in case it postdates the local origin.
    if ! git -C "$pytorch_dir" rev-parse --verify "$PYTORCH_SHA^{commit}" \
             >/dev/null 2>&1; then
        git -C "$pytorch_dir" fetch --quiet origin
    fi
    if ! git -C "$pytorch_dir" rev-parse --verify "$PYTORCH_SHA^{commit}" \
             >/dev/null 2>&1; then
        echo "FATAL: pytorch SHA $PYTORCH_SHA not reachable from origin" >&2
        emit_selection_json "EXACT_UPSTREAM_MAIN" "$PYTORCH_SHA" "" "" "null" \
            "sha_not_reachable"
        exit 3
    fi
    git -C "$pytorch_dir" -c advice.detachedHead=false checkout \
        --quiet "$PYTORCH_SHA"
    git -C "$pytorch_dir" submodule sync --quiet
    git -C "$pytorch_dir" submodule update --init --recursive --quiet

    # Confirm we landed on the exact SHA we asked for.
    local resolved
    resolved="$(git -C "$pytorch_dir" rev-parse HEAD)"
    if [ "$resolved" != "$PYTORCH_SHA" ]; then
        echo "FATAL: pytorch checkout resolved to $resolved, expected $PYTORCH_SHA" >&2
        emit_selection_json "EXACT_UPSTREAM_MAIN" "$PYTORCH_SHA" "$resolved" "" "null" \
            "checkout_sha_mismatch"
        exit 3
    fi

    # Install torch's declared build requirements. pytorch keeps these
    # in requirements-build.txt (canonical) with requirements.txt as a
    # runtime superset; fall back to requirements.txt if the build file
    # is missing (older SHAs).
    local build_log="$WORKDIR/pytorch_build.log"
    : > "$build_log"
    echo "# pytorch build ($(date -u +%FT%TZ)) SHA=$PYTORCH_SHA" >> "$build_log"

    if [ -f "$pytorch_dir/requirements-build.txt" ]; then
        pip install --quiet -r "$pytorch_dir/requirements-build.txt" \
            >> "$build_log" 2>&1 || true
    fi
    if [ -f "$pytorch_dir/requirements.txt" ]; then
        pip install --quiet -r "$pytorch_dir/requirements.txt" \
            >> "$build_log" 2>&1 || true
    fi

    # Fresh ccache dir under the workdir — per environment-policy.md the
    # forward-compat case never reuses a compiler cache implicitly.
    local ccache_dir="$WORKDIR/ccache"
    rm -rf "$ccache_dir"
    mkdir -p "$ccache_dir"
    export CCACHE_DIR="$ccache_dir"
    export CMAKE_C_COMPILER_LAUNCHER="${CMAKE_C_COMPILER_LAUNCHER:-ccache}"
    export CMAKE_CXX_COMPILER_LAUNCHER="${CMAKE_CXX_COMPILER_LAUNCHER:-ccache}"

    # Run the build under a hard wall-clock deadline. `timeout` returns
    # 124 on timeout; any other non-zero is a real build failure.
    local budget_seconds=$(( BUILD_BUDGET_HOURS * 3600 ))
    local build_start build_end build_seconds rc
    build_start=$(date +%s)

    echo "# invoking: timeout ${budget_seconds}s python setup.py develop" >> "$build_log"
    set +e
    ( cd "$pytorch_dir" && timeout "${budget_seconds}s" \
          python setup.py develop ) >> "$build_log" 2>&1
    rc=$?
    set -e

    build_end=$(date +%s)
    build_seconds=$(( build_end - build_start ))
    echo "# build rc=$rc build_seconds=$build_seconds" >> "$build_log"

    if [ "$rc" -ne 0 ]; then
        local reason
        if [ "$rc" -eq 124 ]; then
            reason="build_timeout_after_${BUILD_BUDGET_HOURS}h"
        else
            reason="build_failed_rc_${rc}"
        fi
        echo "[setup_latest_pytorch_env] source build did not succeed" >&2
        echo "[setup_latest_pytorch_env] falling back to NIGHTLY_PROXY: $reason" >&2

        # Record the failed build attempt so the fallback JSON emitted
        # by the nightly path can be corroborated against this log; the
        # nightly re-invocation overwrites pytorch_selection.json with
        # its own record and sets fallback_reason to $reason.
        emit_selection_json "EXACT_UPSTREAM_MAIN" "$PYTORCH_SHA" "" "" \
            "$build_seconds" "$reason"

        # Deactivate and discard the venv before re-invoking self —
        # the fallback needs its own fresh venv.
        deactivate 2>/dev/null || true

        # Thread the fallback context through env so the child's
        # pytorch_selection.json records requested_sha and
        # fallback_reason correctly (its --pytorch-sha argv is empty
        # because NIGHTLY_PROXY does not consume a requested SHA).
        export _FWDCOMPAT_FALLBACK_REQUESTED_SHA="$PYTORCH_SHA"
        export _FWDCOMPAT_FALLBACK_REASON="$reason"

        # exec replaces this process with the nightly-mode invocation;
        # if exec itself fails, fall through to exit 4.
        exec "$0" \
            --torch-spyre-sha "$TORCH_SPYRE_SHA" \
            --pytorch-sha "" \
            --workdir "$WORKDIR" \
            --mode NIGHTLY_PROXY \
            --build-budget-hours "$BUILD_BUDGET_HOURS"
        echo "FATAL: exec of self in NIGHTLY_PROXY mode failed" >&2
        exit 4
    fi

    # Success path: install torch-spyre against the just-built torch.
    install_torch_spyre_editable

    local version
    version="$(python -c 'import torch; print(torch.__version__)')"

    emit_selection_json "EXACT_UPSTREAM_MAIN" "$PYTORCH_SHA" "$resolved" \
        "$version" "$build_seconds" "null"
    return 0
}

# --- Dispatch ---------------------------------------------------------------

case "$MODE" in
    EXACT_UPSTREAM_MAIN)
        run_exact_upstream_main
        ;;
    NIGHTLY_PROXY)
        # Two callers land here:
        #   (a) Direct invocation — user chose NIGHTLY_PROXY explicitly;
        #       requested_sha comes from --pytorch-sha (may be empty),
        #       fallback_reason is null.
        #   (b) exec'd from run_exact_upstream_main after a source-build
        #       failure — _FWDCOMPAT_FALLBACK_* env vars carry the
        #       original requested SHA and the failure reason.
        _req="${_FWDCOMPAT_FALLBACK_REQUESTED_SHA:-$PYTORCH_SHA}"
        _reason="${_FWDCOMPAT_FALLBACK_REASON:-null}"
        run_nightly_proxy "$_req" "$_reason"
        ;;
esac

echo "[setup_latest_pytorch_env] substrate ready under $WORKDIR"
echo "[setup_latest_pytorch_env] pytorch_selection.json:"
cat "$WORKDIR/pytorch_selection.json"

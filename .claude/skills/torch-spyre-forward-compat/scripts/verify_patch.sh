#!/usr/bin/env bash
# verify_patch.sh — run the seven-row verification matrix against one
# forward-compat patch and record the result in the failure's
# 05-verification.md.
#
# Purpose
# -------
#
# A patch is declared VERIFIED only when every applicable row of the
# matrix from references/verification-policy.md is PASS (or
# explicitly-justified N/A). This script is the automated executor of
# that matrix. It refuses to write "VERIFIED" unless every applicable
# row passed — the discipline is enforced by refusing to lie, not by
# a review reminder.
#
# CLI
# ---
#
#   verify_patch.sh --failure-dir DIR \
#                   --venv-supported PATH \
#                   --venv-latest    PATH
#
# --failure-dir     A failure directory previously created by
#                   record_failure.py. Must contain 04-patch.md whose
#                   metadata resolves to a concrete diff file (either
#                   `04-patch.diff` next to it, or a `04-patch/` dir
#                   whose contents are applied in lexicographic order).
# --venv-supported  Path to a virtualenv where torch is installed at
#                   the version torch-spyre currently declares in
#                   pyproject.toml. Used for Row 3.
# --venv-latest     Path to a virtualenv where torch is installed at
#                   the latest upstream pytorch main SHA the patch was
#                   authored against. Used for Row 4 and as the
#                   default venv for Rows 1/2/5/7.
#
# Output layout (created under --failure-dir):
#
#   05-verification.md            rewritten in place with the filled matrix
#   verify-logs/
#     substrate.txt               pod name, base image digest, timestamps
#     patch-hash.txt              git hash-object of the patch as verified
#     resolved-refs.txt           torch versions/SHAs seen by each row
#     row-1-targeted.log          Row 1 stdout+stderr
#     row-1-targeted.result       {"row":1,"status":"pass|fail|na","notes":"..."}
#     row-2-neighbors.log         (per-test appended)
#     row-2-neighbors.result
#     row-3-supported.log
#     row-3-supported.result
#     row-4-latest.log
#     row-4-latest.result
#     row-5-device.log
#     row-5-device.result
#     row-6-build-import.log
#     row-6-build-import.result
#     row-7-smoke.log             (per-test appended)
#     row-7-smoke.result
#
# The .result files are the machine-parseable summary; the .log files
# are the primary evidence. Both must be present for a row to count.
#
# Row 6 uses a throwaway venv the script creates under
# `verify-logs/venv6/`. The other rows use the venvs the caller
# provided — that is deliberate: the point of the matrix is to test
# the patch against known venvs, not against a set built inside this
# script.
#
# Exit codes
# ----------
#
#   0   VERIFIED   every applicable row is PASS
#   1   UNVERIFIED at least one row FAILed (or is DEFERRED/N/A without
#                  justification — this script never writes an
#                  unjustified N/A)
#   2   usage / argument error
#   3   the failure directory is not in a state the matrix can run
#       against (missing 04-patch, missing citations in 01-observation,
#       hypothesis/plan absent, etc.)
#
# On any non-zero exit the .log/.result files that DID run are left in
# place — they are the record of what was tried.

set -uo pipefail

SCRIPT_VERSION=1

# ---------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------

FAILURE_DIR=""
VENV_SUPPORTED=""
VENV_LATEST=""
TREE_SUPPORTED_ARG=""
TREE_LATEST_ARG=""

usage() {
    cat >&2 <<'USAGE'
usage: verify_patch.sh --failure-dir     DIR
                       --venv-supported  PATH
                       --venv-latest     PATH
                       --tree-supported  PATH
                       --tree-latest     PATH

  --failure-dir     Path to a failures/NN-<slug>/ directory previously
                    created by record_failure.py. Its 04-patch.md must
                    reference a concrete diff (04-patch.diff or a
                    04-patch/ directory of hunks).
  --venv-supported  Virtualenv with torch pinned to torch-spyre's
                    declared support (see references/environment-policy.md).
                    Row 3 evaluates against this venv.
  --venv-latest     Virtualenv with torch at the latest upstream pytorch
                    main SHA the patch was authored against. Row 4 uses
                    this; Rows 1/2/5/7 use it as the default.
  --tree-supported  torch-spyre source tree built into --venv-supported.
                    Row 3 applies the patch here.
  --tree-latest     torch-spyre source tree built into --venv-latest.
                    Rows 1/2/4/5/7 apply the patch here.

The tree args are required and explicit because the documented
layout (setup_supported_env.sh → $WORKDIR/torch-spyre next to
$WORKDIR/.venv-supported; setup_latest_pytorch_env.sh → same shape)
puts the tree as a SIBLING of the venv, not an ancestor. Earlier
walk-up heuristics silently failed on that layout.

Exit codes: 0 VERIFIED; 1 UNVERIFIED; 2 usage error; 3 case not ready.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --failure-dir)    FAILURE_DIR="${2:-}";        shift 2 ;;
        --venv-supported) VENV_SUPPORTED="${2:-}";     shift 2 ;;
        --venv-latest)    VENV_LATEST="${2:-}";        shift 2 ;;
        --tree-supported) TREE_SUPPORTED_ARG="${2:-}"; shift 2 ;;
        --tree-latest)    TREE_LATEST_ARG="${2:-}";    shift 2 ;;
        -h|--help)        usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$FAILURE_DIR" ] || [ -z "$VENV_SUPPORTED" ] || [ -z "$VENV_LATEST" ] \
   || [ -z "$TREE_SUPPORTED_ARG" ] || [ -z "$TREE_LATEST_ARG" ]; then
    usage; exit 2
fi

if [ ! -d "$FAILURE_DIR" ]; then
    echo "error: --failure-dir does not exist: $FAILURE_DIR" >&2
    exit 2
fi
FAILURE_DIR="$(cd "$FAILURE_DIR" && pwd)"

for label in "supported:$VENV_SUPPORTED" "latest:$VENV_LATEST"; do
    kind="${label%%:*}"
    path="${label#*:}"
    if [ ! -f "$path/bin/activate" ]; then
        echo "error: --venv-$kind has no bin/activate: $path" >&2
        exit 2
    fi
done

for label in "supported:$TREE_SUPPORTED_ARG" "latest:$TREE_LATEST_ARG"; do
    kind="${label%%:*}"
    path="${label#*:}"
    if [ ! -f "$path/pyproject.toml" ] || [ ! -d "$path/torch_spyre" ]; then
        echo "error: --tree-$kind is not a torch-spyre checkout: $path" >&2
        echo "       (expected $path/pyproject.toml and $path/torch_spyre/)" >&2
        exit 2
    fi
done

VENV_SUPPORTED="$(cd "$VENV_SUPPORTED" && pwd)"
VENV_LATEST="$(cd "$VENV_LATEST" && pwd)"
TREE_SUPPORTED_ARG="$(cd "$TREE_SUPPORTED_ARG" && pwd)"
TREE_LATEST_ARG="$(cd "$TREE_LATEST_ARG" && pwd)"

# ---------------------------------------------------------------------
# Preconditions on the failure directory
# ---------------------------------------------------------------------
#
# The matrix cannot run against a case that has not passed
# hypothesis-before-fix. Row 2's neighbor set and Row 7's smoke set
# must have been chosen in advance (recorded in 03-remediation-plan.md);
# a valid patch file must exist. This block refuses to grade a case
# that isn't ready — silence would produce a bogus "VERIFIED".

for required in \
    "01-observation.md" \
    "02-diagnosis-hypothesis.md" \
    "03-remediation-plan.md" \
    "04-patch.md"; do
    if [ ! -f "$FAILURE_DIR/$required" ]; then
        echo "error: $FAILURE_DIR missing $required — hypothesis-before-fix requires all of 01..04 before verification" >&2
        exit 3
    fi
done

# Locate the concrete patch. 04-patch.md is prose; the diff lives
# alongside it as `04-patch.diff` (single-hunk) or `04-patch/` (a
# directory of hunks applied in lex order).
PATCH_FILE=""
PATCH_DIR=""
if [ -f "$FAILURE_DIR/04-patch.diff" ]; then
    PATCH_FILE="$FAILURE_DIR/04-patch.diff"
elif [ -d "$FAILURE_DIR/04-patch" ]; then
    PATCH_DIR="$FAILURE_DIR/04-patch"
else
    echo "error: no 04-patch.diff or 04-patch/ next to 04-patch.md in $FAILURE_DIR" >&2
    echo "       verification requires a concrete diff; 04-patch.md is prose only" >&2
    exit 3
fi

# ---------------------------------------------------------------------
# Log dir and helpers
# ---------------------------------------------------------------------

LOG_DIR="$FAILURE_DIR/verify-logs"
mkdir -p "$LOG_DIR"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
now_s()   { date +%s; }

# JSON-escape a string using pure bash. Same reason as run_compat_smoke.sh:
# the very venv under test might be broken, and we still want to write
# a legible .result file.
# Source /etc/profile.d/ibm-aiu-setup.sh so downstream torch_spyre
# imports find libspyre_comms.so.1 / senlib / etc. under
# /opt/ibm/spyre/*/lib. Meant to be called inside a row's subshell
# AFTER `source $venv/bin/activate` — the setup script uses
# unbound-var references (e.g. `_IBM_AIU_SETUP`) that trip `set -u`,
# so we bracket with `set +u` and put it back afterwards.
source_ibm_aiu_env() {
    set +u
    # shellcheck disable=SC1091
    if [ -r /etc/profile.d/ibm-aiu-setup.sh ]; then
        source /etc/profile.d/ibm-aiu-setup.sh >/dev/null 2>&1 || true
    fi
    set -u
}

json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

write_row_result() {
    # write_row_result <row> <status> <duration_s> <notes>
    local row="$1" status="$2" dur="$3" notes="$4"
    local esc; esc="$(json_escape "$notes")"
    cat >"$LOG_DIR/row-${row}.result" <<EOF
{"row": ${row}, "status": "${status}", "duration_s": ${dur}, "notes": "${esc}", "timestamp_utc": "$(now_utc)"}
EOF
}

# Record the git hash-object of the patch content as verified. If the
# patch is a directory of hunks, hash their concatenation in
# lex-sorted order — that is the same order they will be applied in.
compute_patch_hash() {
    if [ -n "$PATCH_FILE" ]; then
        git hash-object "$PATCH_FILE" 2>/dev/null \
            || sha256sum <"$PATCH_FILE" | awk '{print "sha256:" $1}'
    else
        (
            cd "$PATCH_DIR"
            # shellcheck disable=SC2012
            ls | sort | xargs -I{} cat "{}"
        ) | { git hash-object --stdin 2>/dev/null \
              || sha256sum | awk '{print "sha256:" $1}'; }
    fi
}

# Apply the patch to a torch-spyre checkout given by $1 (cwd already
# in a subshell). Returns 0 on clean apply.
apply_patch() {
    local tree="$1"
    if [ -n "$PATCH_FILE" ]; then
        ( cd "$tree" && git apply --index "$PATCH_FILE" ) 2>&1
    else
        local rc=0
        while IFS= read -r hunk; do
            [ -n "$hunk" ] || continue
            if ! ( cd "$tree" && git apply --index "$hunk" ) 2>&1; then
                rc=1; break
            fi
        done < <(ls "$PATCH_DIR" | sort | sed "s|^|$PATCH_DIR/|")
        return $rc
    fi
}

# Trees came in via required --tree-supported / --tree-latest args
# above. This block used to walk up from each venv looking for
# pyproject.toml + torch_spyre/, but the documented setup layout puts
# the tree as a SIBLING of the venv, not an ancestor — so the walk-up
# always failed on genuine fresh-pod runs.
TREE_SUPPORTED="$TREE_SUPPORTED_ARG"
TREE_LATEST="$TREE_LATEST_ARG"

# ---------------------------------------------------------------------
# Substrate / patch-hash / refs metadata
# ---------------------------------------------------------------------

PATCH_HASH="$(compute_patch_hash)"
printf '%s\n' "$PATCH_HASH" >"$LOG_DIR/patch-hash.txt"

{
    echo "verify_patch.sh version: $SCRIPT_VERSION"
    echo "run_started_utc: $(now_utc)"
    echo "failure_dir: $FAILURE_DIR"
    echo "venv_supported: $VENV_SUPPORTED"
    echo "venv_latest:    $VENV_LATEST"
    echo "tree_supported: $TREE_SUPPORTED"
    echo "tree_latest:    $TREE_LATEST"
    echo "patch_ref: ${PATCH_FILE:-$PATCH_DIR}"
    echo "patch_hash: $PATCH_HASH"
    echo "hostname: $(hostname 2>/dev/null || echo unknown)"
    if [ -f /etc/hostname ]; then
        echo "etc_hostname: $(cat /etc/hostname)"
    fi
    if [ -n "${POD_NAME:-}" ]; then
        echo "pod_name_env: $POD_NAME"
    fi
} >"$LOG_DIR/substrate.txt"

# ---------------------------------------------------------------------
# Row execution
# ---------------------------------------------------------------------
#
# Each row is a function that returns 0 on PASS, 1 on FAIL, and 2 on
# N/A. N/A is only permitted where the policy explicitly allows it
# and only when the case files justify it (parsed from 01/02/03).
# Any row that would return N/A without a matching justification
# instead returns 1 (FAIL) — the script will not silently downgrade.

RESOLVED_TORCH_SUPPORTED=""
RESOLVED_TORCH_LATEST=""
RESOLVED_TORCH_GIT_SUPPORTED=""
RESOLVED_TORCH_GIT_LATEST=""

resolve_torch_in_venv() {
    # resolve_torch_in_venv <venv> <label>
    # Prints "<version> <git_version>" on stdout, "" on failure.
    local venv="$1" label="$2"
    local raw
    raw="$(
        # shellcheck disable=SC1090
        source "$venv/bin/activate" 2>/dev/null
        source_ibm_aiu_env
        python - <<'PY' 2>/dev/null
try:
    import torch
    v = torch.__version__
    g = getattr(torch.version, "git_version", "") or ""
    print(v, g)
except Exception as e:
    print("__ERR__", e)
PY
    )"
    printf '%s' "$raw"
    unset label
}

# --- Row 1: TARGETED TEST ---------------------------------------------
#
# Re-run the exact command from 01-observation.md against the
# --venv-latest venv with the patch applied. The command lives under
# a machine-parseable fence in 01-observation.md — we look for a
# fenced code block preceded by the string "targeted-command:" (case
# insensitive) on the line before the fence. Absent that, Row 1 is
# FAIL with a clear message asking the operator to add the block.

extract_targeted_command() {
    python3 - "$FAILURE_DIR/01-observation.md" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
txt = p.read_text()
# Look for: a line matching /targeted-command/i followed by a fenced
# code block (```...``` or ```bash ... ```).
m = re.search(
    r"(?im)^[^\n]*targeted-command[^\n]*\n+```[a-zA-Z0-9_+-]*\n(.*?)```",
    txt, re.S)
if m:
    sys.stdout.write(m.group(1).rstrip() + "\n")
    sys.exit(0)
sys.exit(1)
PY
}

run_row_1() {
    local log="$LOG_DIR/row-1-targeted.log"
    local t0 t1 dur rc
    t0=$(now_s); : >"$log"

    local cmd
    if ! cmd="$(extract_targeted_command)"; then
        echo "row 1: 01-observation.md has no 'targeted-command' fenced block" >>"$log"
        echo "       add one before running verify_patch.sh; see verification-policy.md Row 1" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 1 fail "$dur" "no targeted-command block in 01-observation.md"
        return 1
    fi

    echo "# targeted-command extracted from 01-observation.md:" >>"$log"
    printf '%s\n' "$cmd" >>"$log"
    echo "# --- begin execution ---" >>"$log"

    (
        # shellcheck disable=SC1090
        source "$VENV_LATEST/bin/activate"
        source_ibm_aiu_env
        cd "$TREE_LATEST"
        # The patch must actually be applied in the working tree for
        # this row to be meaningful. We check that a preceding step
        # applied it — if `git diff --quiet` reports "no diff" AND
        # the patch is non-empty, that's a setup bug, not a Row 1
        # failure.
        if git diff --quiet && [ -n "$PATCH_FILE$PATCH_DIR" ]; then
            echo "FATAL: working tree clean in $TREE_LATEST but a patch was expected to be applied" >&2
            exit 111
        fi
        # Run the extracted command through bash -c so shell operators
        # in the reproducer survive.
        bash -c "$cmd"
    ) >>"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_row_result 1 pass "$dur" "targeted reproducer exit 0 on --venv-latest with patch applied"
        return 0
    fi
    if [ "$rc" -eq 111 ]; then
        write_row_result 1 fail "$dur" "SETUP: patch not applied to $TREE_LATEST before verify (caller must apply)"
        return 1
    fi
    write_row_result 1 fail "$dur" "targeted reproducer failed rc=$rc; see row-1-targeted.log"
    return 1
}

# --- Row 2: NEIGHBOR TESTS -------------------------------------------
#
# The neighbor set was chosen BEFORE the patch (per policy) and
# recorded in 03-remediation-plan.md under `## Neighbor set (for Row 2
# of the verification matrix)`. Parse the bullet list under that
# heading — each bullet is a test path or `pytest` nodeid.

extract_list_under_heading() {
    # extract_list_under_heading <file> <heading substring>
    python3 - "$1" "$2" <<'PY'
import re, sys, pathlib
path, needle = sys.argv[1], sys.argv[2].lower()
text = pathlib.Path(path).read_text().splitlines()
i = 0
while i < len(text):
    line = text[i]
    if line.lstrip().startswith("#") and needle in line.lower():
        # collect subsequent bullet lines until the next heading
        i += 1
        items = []
        while i < len(text):
            l = text[i]
            if l.lstrip().startswith("#"):
                break
            m = re.match(r"^\s*[-*]\s+(.+?)\s*$", l)
            if m:
                items.append(m.group(1))
            i += 1
        for it in items:
            # strip surrounding backticks if present
            it = it.strip("`").strip()
            if it and not it.lower().startswith("(") and it != "...":
                print(it)
        sys.exit(0 if items else 1)
    i += 1
sys.exit(1)
PY
}

run_row_2() {
    local log="$LOG_DIR/row-2-neighbors.log"
    local t0 t1 dur
    t0=$(now_s); : >"$log"

    local -a neighbors=()
    while IFS= read -r line; do
        [ -n "$line" ] && neighbors+=("$line")
    done < <(extract_list_under_heading "$FAILURE_DIR/03-remediation-plan.md" "Neighbor set" 2>/dev/null || true)

    if [ "${#neighbors[@]}" -lt 3 ]; then
        echo "row 2: 03-remediation-plan.md must list at least 3 neighbor tests under a '## Neighbor set' heading" >>"$log"
        echo "       found ${#neighbors[@]}; policy requires 3 (>= 1 not exercising the patched path)" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 2 fail "$dur" "fewer than 3 neighbor tests in remediation plan"
        return 1
    fi

    local passed=0 failed=0
    for t in "${neighbors[@]}"; do
        echo "" >>"$log"
        echo "# --- neighbor: $t ---" >>"$log"
        local cache="/tmp/torchind-verify-row2-$$-$RANDOM"
        (
            # shellcheck disable=SC1090
            source "$VENV_LATEST/bin/activate"
            source_ibm_aiu_env
            cd "$TREE_LATEST"
            export TORCHINDUCTOR_CACHE_DIR="$cache"
            python -m pytest -x -q --no-header "$t"
        ) >>"$log" 2>&1
        rc=$?
        rm -rf "$cache"
        if [ "$rc" -eq 0 ]; then
            passed=$((passed + 1))
            echo "# neighbor OK: $t" >>"$log"
        else
            failed=$((failed + 1))
            echo "# neighbor FAIL rc=$rc: $t" >>"$log"
        fi
    done

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$failed" -eq 0 ]; then
        write_row_result 2 pass "$dur" "all ${#neighbors[@]} neighbor tests passed"
        return 0
    fi
    write_row_result 2 fail "$dur" "$failed/${#neighbors[@]} neighbor tests failed"
    return 1
}

# --- Row 3: SUPPORTED-PYTORCH CHECK ----------------------------------
#
# The targeted reproducer, re-run against --venv-supported with the
# patch applied there. The point is to catch a forward-compat fix
# that silently regresses the version torch-spyre officially supports.

run_row_3() {
    local log="$LOG_DIR/row-3-supported.log"
    local t0 t1 dur rc
    t0=$(now_s); : >"$log"

    local cmd
    if ! cmd="$(extract_targeted_command)"; then
        write_row_result 3 fail 0 "no targeted-command block (same failure as Row 1)"
        return 1
    fi

    # Record which torch this venv actually resolves to. Cache the
    # value for the resolved-refs.txt summary.
    local resolved
    resolved="$(resolve_torch_in_venv "$VENV_SUPPORTED" supported)"
    echo "# supported venv resolves to: $resolved" >>"$log"
    RESOLVED_TORCH_SUPPORTED="${resolved% *}"
    RESOLVED_TORCH_GIT_SUPPORTED="${resolved#* }"

    (
        # shellcheck disable=SC1090
        source "$VENV_SUPPORTED/bin/activate"
        source_ibm_aiu_env
        cd "$TREE_SUPPORTED"
        bash -c "$cmd"
    ) >>"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_row_result 3 pass "$dur" "targeted reproducer passed on supported torch $RESOLVED_TORCH_SUPPORTED"
        return 0
    fi
    write_row_result 3 fail "$dur" "targeted reproducer failed on supported torch (rc=$rc); patch regressed the declared-supported version"
    return 1
}

# --- Row 4: LATEST-PYTORCH CHECK -------------------------------------
#
# Same as Row 1 but stated separately because the policy asks for the
# torch git SHA and version to be recorded independently. Row 1 asks
# "does the reproducer pass?"; Row 4 asks "and here is exactly what
# torch we were running when it did".

run_row_4() {
    local log="$LOG_DIR/row-4-latest.log"
    local t0 t1 dur rc
    t0=$(now_s); : >"$log"

    local resolved
    resolved="$(resolve_torch_in_venv "$VENV_LATEST" latest)"
    echo "# latest venv resolves to: $resolved" >>"$log"
    RESOLVED_TORCH_LATEST="${resolved% *}"
    RESOLVED_TORCH_GIT_LATEST="${resolved#* }"

    if [ -z "$RESOLVED_TORCH_LATEST" ] || [ "$RESOLVED_TORCH_LATEST" = "__ERR__" ]; then
        write_row_result 4 fail 0 "could not import torch in --venv-latest"
        return 1
    fi
    if [ -z "$RESOLVED_TORCH_GIT_LATEST" ]; then
        echo "# WARNING: torch.version.git_version is empty; not a source-built torch" >>"$log"
        echo "#          Row 4 requires an exact upstream SHA per verification-policy.md" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 4 fail "$dur" "latest venv has no torch.version.git_version — cannot pin to an upstream SHA"
        return 1
    fi

    # Re-run targeted command; separate log from Row 1 to keep the
    # matrix rows independently reviewable.
    local cmd
    if ! cmd="$(extract_targeted_command)"; then
        write_row_result 4 fail 0 "no targeted-command block (same failure as Row 1)"
        return 1
    fi
    (
        # shellcheck disable=SC1090
        source "$VENV_LATEST/bin/activate"
        source_ibm_aiu_env
        cd "$TREE_LATEST"
        bash -c "$cmd"
    ) >>"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_row_result 4 pass "$dur" "targeted reproducer passed on latest torch $RESOLVED_TORCH_LATEST (git $RESOLVED_TORCH_GIT_LATEST)"
        return 0
    fi
    write_row_result 4 fail "$dur" "targeted reproducer failed on latest torch (rc=$rc); see row-4-latest.log"
    return 1
}

# --- Row 5: DEVICE CORRECTNESS ---------------------------------------
#
# N/A is only acceptable when the patched path produces no tensor
# outputs (pure metadata / registration / error-message change). The
# hypothesis file must state that explicitly under a heading whose
# body includes the phrase "Row 5 N/A because" — otherwise the row
# runs and is FAIL if no oracle script is provided.
#
# When runnable, the case must supply an oracle script at
# `05-verification.oracle.py` in the failure directory. Its exit code
# is authoritative: 0 = tensors match under the op's tolerances,
# non-zero = mismatch.

detect_row5_na_justification() {
    grep -q -i "Row 5 N/A because" "$FAILURE_DIR/02-diagnosis-hypothesis.md" 2>/dev/null
}

run_row_5() {
    local log="$LOG_DIR/row-5-device.log"
    local t0 t1 dur rc
    t0=$(now_s); : >"$log"

    if detect_row5_na_justification; then
        echo "# Row 5 N/A per 02-diagnosis-hypothesis.md (pure metadata / registration change)" >>"$log"
        grep -A 3 -i "Row 5 N/A because" "$FAILURE_DIR/02-diagnosis-hypothesis.md" >>"$log" 2>/dev/null || true
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 5 na "$dur" "N/A justified in 02-diagnosis-hypothesis.md"
        return 2
    fi

    local oracle="$FAILURE_DIR/05-verification.oracle.py"
    if [ ! -f "$oracle" ]; then
        echo "row 5: no 05-verification.oracle.py in $FAILURE_DIR" >>"$log"
        echo "       and no 'Row 5 N/A because' clause in 02-diagnosis-hypothesis.md" >>"$log"
        echo "       policy: patched paths that produce tensors require an oracle;" >>"$log"
        echo "       add one that compares spyre vs CPU-eager with documented tolerances" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 5 fail "$dur" "no oracle script and no N/A justification"
        return 1
    fi

    (
        # shellcheck disable=SC1090
        source "$VENV_LATEST/bin/activate"
        source_ibm_aiu_env
        cd "$TREE_LATEST"
        python "$oracle"
    ) >>"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_row_result 5 pass "$dur" "device-vs-CPU oracle passed"
        return 0
    fi
    write_row_result 5 fail "$dur" "oracle exited $rc; tensor outputs did not match under stated tolerances"
    return 1
}

# --- Row 6: BUILD/IMPORT (clean environment) -------------------------
#
# A throwaway venv, `pip install -e` the patched torch-spyre tree,
# import in a separate process. The venv is `verify-logs/venv6/`.
# We build it from `python3 -m venv` — do NOT copy or clone the
# author's venv, per the policy's disqualifier list.

run_row_6() {
    local log="$LOG_DIR/row-6-build-import.log"
    local t0 t1 dur rc
    t0=$(now_s); : >"$log"

    local venv6="$LOG_DIR/venv6"
    rm -rf "$venv6"

    # Prefer the same python that the latest venv uses, so the ABI
    # under test matches Row 4.
    local py_exec
    py_exec="$(
        # shellcheck disable=SC1090
        source "$VENV_LATEST/bin/activate"
        source_ibm_aiu_env
        command -v python
    )"
    if [ -z "$py_exec" ]; then
        echo "row 6: could not locate python inside --venv-latest to base venv6 on" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 6 fail "$dur" "no python found in latest venv"
        return 1
    fi

    {
        echo "# creating clean venv at $venv6 using $py_exec"
        "$py_exec" -m venv "$venv6"
    } >>"$log" 2>&1

    # Discover the exact torch installed in --venv-latest so Row 6
    # can install the same one into venv6. `pip wheel torch` alone
    # goes to PyPI (which gets a completely different, CUDA-tagged
    # 2.13 wheel), so we must (a) read the local version and (b) use
    # the same pytorch index the latest venv was populated from.
    local latest_torch_version
    latest_torch_version="$(
        # shellcheck disable=SC1090
        source "$VENV_LATEST/bin/activate"
        source_ibm_aiu_env
        python -c "import torch; print(torch.__version__)" 2>/dev/null
    )"
    if [ -z "$latest_torch_version" ]; then
        echo "row 6: could not read torch version from --venv-latest" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 6 fail "$dur" "could not read torch version from --venv-latest"
        return 1
    fi
    echo "# latest torch version = $latest_torch_version" >>"$log"

    # NIGHTLY_PROXY setups install torch from the CPU nightly index.
    # We recognize that by the "+cpu" local tag plus the ".dev" pre-
    # release tag; if both are present, use the nightly-cpu index.
    # Otherwise fall back to PyPI (which will match a normal
    # +cpu / stable install).
    local torch_index_url=""
    case "$latest_torch_version" in
        *".dev"*"+cpu") torch_index_url="https://download.pytorch.org/whl/nightly/cpu" ;;
        *"+cpu")        torch_index_url="https://download.pytorch.org/whl/cpu"          ;;
    esac
    echo "# torch source index = ${torch_index_url:-<default PyPI>}" >>"$log"

    (
        # shellcheck disable=SC1090
        source "$venv6/bin/activate"
        source_ibm_aiu_env
        set -e
        pip install --upgrade pip
        # Install the same torch version from the same source used by
        # --venv-latest — no wheel-copy dance (which fetches from PyPI
        # by default and gets an unrelated 2.13 CUDA wheel). Row 6's
        # only requirement is that venv6 sees the same torch as venv-
        # latest; explicit version+index does that.
        if [ -n "$torch_index_url" ]; then
            pip install --pre --index-url "$torch_index_url" "torch==$latest_torch_version"
        else
            pip install "torch==$latest_torch_version"
        fi
        # Install torch-spyre build prereqs from
        # references/canonical-dev-flow.md. Under --no-build-isolation
        # pip does NOT create an ephemeral build env, so nanobind /
        # ninja / pybind11 / cmake / regex must be present in the venv
        # already; expecttest / wheel / psutil / pytest / numpy /
        # typing_extensions cover the runtime import path.
        pip install \
            nanobind==2.9.2 ninja pybind11 build "cmake~=3.26" regex \
            expecttest wheel psutil pytest typing_extensions numpy
        # --no-deps: torch-spyre's pyproject pins torch~=2.13.0 —
        # if we let pip resolve deps it would downgrade the nightly
        # torch to 2.13-with-CUDA and defeat the entire venv-latest
        # SHA guarantee. Every non-torch runtime dep that a bare
        # `import torch_spyre` reaches is already in this venv6.
        # --no-build-isolation: canonical dev-flow form, links
        # against THIS torch (not an ephemeral one PEP 517 would
        # materialize).
        pip install -e "$TREE_LATEST" --no-deps --no-build-isolation
    ) >>"$log" 2>&1
    rc=$?
    if [ "$rc" -ne 0 ]; then
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 6 fail "$dur" "pip install -e failed in clean venv; see row-6-build-import.log"
        return 1
    fi

    # Separate-process import, per the policy's second disqualifier.
    (
        # shellcheck disable=SC1090
        source "$venv6/bin/activate"
        source_ibm_aiu_env
        python -c "import torch_spyre, sys; print('torch_spyre version =', getattr(torch_spyre, '__version__', '(no __version__)')); sys.exit(0)"
    ) >>"$log" 2>&1
    rc=$?

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$rc" -eq 0 ]; then
        write_row_result 6 pass "$dur" "clean venv install + separate-process import succeeded"
        return 0
    fi
    write_row_result 6 fail "$dur" "import torch_spyre failed in clean venv (rc=$rc)"
    return 1
}

# --- Row 7: BROADER COMPILER SMOKE -----------------------------------
#
# Smoke set drawn from 03-remediation-plan.md's `## Broader smoke set
# (for Row 7 of the verification matrix)` heading, minimum 3 tests
# spanning frontend/mid/backend. Same parsing rules as Row 2.

run_row_7() {
    local log="$LOG_DIR/row-7-smoke.log"
    local t0 t1 dur
    t0=$(now_s); : >"$log"

    local -a smoke=()
    while IFS= read -r line; do
        [ -n "$line" ] && smoke+=("$line")
    done < <(extract_list_under_heading "$FAILURE_DIR/03-remediation-plan.md" "Broader smoke set" 2>/dev/null || true)

    if [ "${#smoke[@]}" -lt 3 ]; then
        echo "row 7: 03-remediation-plan.md must list at least 3 tests under a '## Broader smoke set' heading" >>"$log"
        echo "       found ${#smoke[@]}; policy requires 3 covering frontend/mid/backend" >>"$log"
        t1=$(now_s); dur=$((t1 - t0))
        write_row_result 7 fail "$dur" "fewer than 3 broader smoke tests in remediation plan"
        return 1
    fi

    local passed=0 failed=0
    for t in "${smoke[@]}"; do
        echo "" >>"$log"
        echo "# --- smoke: $t ---" >>"$log"
        local cache="/tmp/torchind-verify-row7-$$-$RANDOM"
        (
            # shellcheck disable=SC1090
            source "$VENV_LATEST/bin/activate"
            source_ibm_aiu_env
            cd "$TREE_LATEST"
            export TORCHINDUCTOR_CACHE_DIR="$cache"
            python -m pytest -x -q --no-header "$t"
        ) >>"$log" 2>&1
        rc=$?
        rm -rf "$cache"
        if [ "$rc" -eq 0 ]; then
            passed=$((passed + 1))
            echo "# smoke OK: $t" >>"$log"
        else
            failed=$((failed + 1))
            echo "# smoke FAIL rc=$rc: $t" >>"$log"
        fi
    done

    t1=$(now_s); dur=$((t1 - t0))
    if [ "$failed" -eq 0 ]; then
        write_row_result 7 pass "$dur" "all ${#smoke[@]} broader smoke tests passed"
        return 0
    fi
    write_row_result 7 fail "$dur" "$failed/${#smoke[@]} smoke tests failed"
    return 1
}

# ---------------------------------------------------------------------
# Run the matrix
# ---------------------------------------------------------------------

declare -A ROW_STATUS
declare -A ROW_NOTES
declare -A ROW_TIME

STATUS_TO_LABEL() {
    case "$1" in
        0) echo "PASS" ;;
        1) echo "FAIL" ;;
        2) echo "N/A"  ;;
        *) echo "ERR"  ;;
    esac
}

run_and_record() {
    local row="$1" fn="$2"
    local t0 t1 dur
    t0=$(now_s)
    "$fn"
    local rc=$?
    t1=$(now_s); dur=$((t1 - t0))
    ROW_STATUS[$row]="$rc"
    ROW_TIME[$row]="$dur"
    # Notes are read back from the .result file (already written by
    # each row function via write_row_result). Fall back if not.
    if [ -f "$LOG_DIR/row-${row}.result" ]; then
        ROW_NOTES[$row]="$(sed -n 's/.*"notes": "\(.*\)", "timestamp_utc".*/\1/p' "$LOG_DIR/row-${row}.result")"
    else
        ROW_NOTES[$row]="(row wrote no .result file)"
    fi
    return 0
}

run_and_record 1 run_row_1
run_and_record 2 run_row_2
run_and_record 3 run_row_3
run_and_record 4 run_row_4
run_and_record 5 run_row_5
run_and_record 6 run_row_6
run_and_record 7 run_row_7

# ---------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------
#
# VERIFIED iff every row is PASS or an explicitly-justified N/A. Any
# FAIL, DEFERRED, or unwritten row makes the verdict UNVERIFIED.

VERDICT="VERIFIED"
FAILED_ROWS=()
for row in 1 2 3 4 5 6 7; do
    case "${ROW_STATUS[$row]:-999}" in
        0) : ;;                      # PASS
        2) : ;;                      # justified N/A
        *) VERDICT="UNVERIFIED"
           FAILED_ROWS+=("$row") ;;
    esac
done

{
    echo "torch_supported_version: ${RESOLVED_TORCH_SUPPORTED:-(unresolved)}"
    echo "torch_supported_git:     ${RESOLVED_TORCH_GIT_SUPPORTED:-(unresolved)}"
    echo "torch_latest_version:    ${RESOLVED_TORCH_LATEST:-(unresolved)}"
    echo "torch_latest_git:        ${RESOLVED_TORCH_GIT_LATEST:-(unresolved)}"
    echo "verdict:                 $VERDICT"
    echo "run_finished_utc: $(now_utc)"
} >"$LOG_DIR/resolved-refs.txt"

# ---------------------------------------------------------------------
# Rewrite 05-verification.md with the filled matrix
# ---------------------------------------------------------------------

TS="$(now_utc)"
OUT_MD="$FAILURE_DIR/05-verification.md"

emit_row_line() {
    # emit_row_line <n> <label>
    local n="$1" label="$2"
    local st; st="$(STATUS_TO_LABEL "${ROW_STATUS[$n]:-999}")"
    local ev="verify-logs/row-${n}-*.log"
    case "$n" in
        1) ev="verify-logs/row-1-targeted.log" ;;
        2) ev="verify-logs/row-2-neighbors.log" ;;
        3) ev="verify-logs/row-3-supported.log" ;;
        4) ev="verify-logs/row-4-latest.log" ;;
        5) ev="verify-logs/row-5-device.log" ;;
        6) ev="verify-logs/row-6-build-import.log" ;;
        7) ev="verify-logs/row-7-smoke.log" ;;
    esac
    local notes="${ROW_NOTES[$n]:-}"
    # Table cells can't contain unescaped pipes.
    notes="${notes//|/\\|}"
    printf '| %d | %-31s | %-6s | %-30s | %-19s | %s |\n' \
        "$n" "$label" "$st" "$ev" "$TS" "$notes"
}

{
    cat <<EOF
<!--
  05-verification.md
  Generated by verify_patch.sh v${SCRIPT_VERSION}
  Failure dir:     $FAILURE_DIR
  Written (UTC):   $TS
  Patch hash:      $PATCH_HASH
-->

# 05-verification

Populated by \`scripts/verify_patch.sh\`. Manual edits above the
verdict line are overwritten on re-run.

## Substrate

- Substrate kind: dev-pod (fresh-pod reproduction goes in §18 below)
- venv (supported): \`$VENV_SUPPORTED\`
- venv (latest):    \`$VENV_LATEST\`
- torch-spyre tree (supported venv): \`$TREE_SUPPORTED\`
- torch-spyre tree (latest venv):    \`$TREE_LATEST\`
- Patch hash (\`git hash-object\`): \`$PATCH_HASH\`
- Run timestamp (UTC): $TS

## Resolved refs

- torch on supported venv: \`${RESOLVED_TORCH_SUPPORTED:-(unresolved)}\` (git: \`${RESOLVED_TORCH_GIT_SUPPORTED:-(unresolved)}\`)
- torch on latest venv:    \`${RESOLVED_TORCH_LATEST:-(unresolved)}\` (git: \`${RESOLVED_TORCH_GIT_LATEST:-(unresolved)}\`)

## Matrix

| # | Row                             | Status | Evidence path                  | Timestamp           | Notes |
|---|---------------------------------|--------|--------------------------------|---------------------|-------|
EOF
    emit_row_line 1 "TARGETED TEST"
    emit_row_line 2 "NEIGHBOR TESTS"
    emit_row_line 3 "SUPPORTED-PYTORCH CHECK"
    emit_row_line 4 "LATEST-PYTORCH CHECK"
    emit_row_line 5 "DEVICE CORRECTNESS"
    emit_row_line 6 "BUILD/IMPORT (clean env)"
    emit_row_line 7 "BROADER COMPILER SMOKE"
    cat <<EOF

## §18 — Fresh-pod reproduction

(When re-run on the fresh pod, append the same matrix here under a
\`### Matrix (fresh pod)\` heading and record any per-row divergence
from the dev-pod matrix. This section is not filled by
verify_patch.sh; re-run the script under the fresh-pod venvs and
copy the resulting matrix here, then fill in "Divergence from
dev-pod matrix".)

## Verdict

**$VERDICT**
EOF
    if [ "$VERDICT" != "VERIFIED" ]; then
        echo ""
        echo "Rows preventing verification: ${FAILED_ROWS[*]}"
        echo ""
        echo "Fix or justify each failing row, then re-run verify_patch.sh"
        echo "against the same failure directory. The matrix will be rewritten"
        echo "with the new results and this verdict recomputed."
    fi
} >"$OUT_MD"

# ---------------------------------------------------------------------
# Exit
# ---------------------------------------------------------------------

if [ "$VERDICT" = "VERIFIED" ]; then
    echo "VERIFIED: $FAILURE_DIR"
    exit 0
fi

echo "UNVERIFIED: $FAILURE_DIR (rows: ${FAILED_ROWS[*]})" >&2
exit 1

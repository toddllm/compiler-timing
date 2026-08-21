#!/usr/bin/env bash
# setup_supported_env.sh — build the SUPPORTED_CONTROL environment on a
# fresh pod, from scratch.
#
# The three-state protocol (references/three-state-protocol.md) requires
# SUPPORTED_CONTROL to be established first — a green ladder run on a
# venv that installs torch at whatever version torch-spyre's
# pyproject.toml currently declares. Only if SUPPORTED_CONTROL reaches
# Stage 6 green is FORWARD_BEFORE_FIX scientifically legible.
#
# This script does one job:
#
#   Given a torch-spyre SHA and a working directory, create a fresh
#   .venv-supported at WORKDIR/.venv-supported (--system-site-packages,
#   because SENDNN / DEEPTOOLS live in the image's system site-packages
#   per basic_install.md), install torch at the version torch-spyre pins
#   in pyproject.toml (parsed at runtime — never hard-coded), install
#   torch-spyre as an editable install at the given SHA using the
#   canonical no-deps / no-build-isolation form from
#   /Users/tdeshane/torch-spyre-docs/scripts/build-torch-spyre.sh, and
#   prove that `import torch, torch_spyre` succeeds.
#
# Non-goals:
#   This script implements the basic_install.md flow. It does NOT
#   implement dev_install.md (full DTI_PROJECT_ROOT rebuild of the AIU
#   software stack: LLVM/DeepTools/senbfcc/torch-sendnn, then PyTorch,
#   then torch-spyre) — that's v0.2 work. This script assumes the pod's
#   image already ships a prebuilt AIU stack in system site-packages,
#   which is the contract of a torch-aiu-runtime-dev image.
#
# What this script deliberately does NOT do:
#   - It does NOT capture environment.json. That is
#     scripts/00_capture_env.sh's job.
#   - It does NOT run the validation ladder. That is
#     scripts/01_run_supported_control.sh's job.
#   - It does NOT install a forward torch. That is
#     scripts/setup_forward_env.sh's job (companion script).
#   - It does NOT touch caches (TORCHINDUCTOR_CACHE_DIR, CCACHE_DIR).
#     Cache hygiene is the ladder runner's responsibility.
#
# CLI:
#   setup_supported_env.sh --torch-spyre-sha SHA --workdir DIR [--python PY]
#
# Defaults:
#   --python python3.12
#
# Exit codes:
#   0   — venv created, torch + torch_spyre imports pass sanity check
#   2   — usage / argument error
#   3   — WORKDIR already exists (fresh means fresh; refuse to proceed)
#   4   — venv creation or pip upgrade failed
#   5   — torch-spyre clone / checkout failed
#   6   — pyproject.toml torch pin could not be parsed
#   7   — torch install failed (WHEEL_UNAVAILABLE or BUILD_FAILURE)
#   8   — torch-spyre build/install failed (typically PIN_CONFLICT or a
#         C++ compile error; also raised when the required
#         /opt/rh/gcc-toolset-*/root/usr/bin/c++ compiler is not
#         present, which indicates the image is not a
#         torch-aiu-runtime-dev variant). Do NOT proceed past a build
#         failure; that is a real datum.
#   9   — sanity import failed (torch or torch_spyre could not import,
#         or reported a version that disagrees with what pip claims to
#         have installed)
#
# All steps are logged verbatim to WORKDIR/setup_supported.log; the log
# is the primary artifact this script produces. On any non-zero exit,
# the log's tail is the failure signature — do not truncate it. The
# torch-spyre build itself additionally tees to
# WORKDIR/build_supported.log so the build's -vvv output is preserved
# even if the outer log is rotated.
#
# Non-negotiables:
#   - No hard-coded torch version. The pin is re-read from
#     pyproject.toml at runtime, per SKILL.md line 258 ("Every script
#     re-reads torch-spyre/pyproject.toml at runtime to recover the
#     currently-declared torch pin. Do not hard-code the pin.").
#   - No silent recovery from a build failure. If Stage 1 or Stage 2
#     fails here, exit non-zero and leave the log in place. That
#     failure IS the case's supported-control result, and the operator
#     needs to see it as-is.
#   - No reuse of an existing WORKDIR. A pre-existing directory could
#     carry stale bytecode, a partial editable install, or a
#     half-built .venv — every one of which is a silent-drift risk.
#   - No silent fallback to system c++ for the torch-spyre build. The
#     canonical build script requires the gcc-toolset compiler; if it
#     is absent the image is wrong and the operator needs to know now,
#     not after a subtle ABI mismatch surfaces at import time.

set -uo pipefail

# ---------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------

usage() {
    cat >&2 <<'USAGE'
usage: setup_supported_env.sh --torch-spyre-sha SHA --workdir DIR [--python PY]

Required:
  --torch-spyre-sha SHA   torch-spyre commit to check out (full SHA
                          recommended; short SHA accepted if
                          unambiguous)
  --workdir DIR           absolute path to a directory that DOES NOT
                          YET EXIST; the venv and torch-spyre checkout
                          will be created underneath it

Optional:
  --python PY             python interpreter to seed the venv with
                          (default: python3.12)

Exit codes: see script header.
USAGE
    exit 2
}

TORCH_SPYRE_SHA=""
WORKDIR=""
PY="python3.12"

while [ $# -gt 0 ]; do
    case "$1" in
        --torch-spyre-sha)
            TORCH_SPYRE_SHA="${2:-}"
            shift 2 || usage
            ;;
        --workdir)
            WORKDIR="${2:-}"
            shift 2 || usage
            ;;
        --python)
            PY="${2:-}"
            shift 2 || usage
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage
            ;;
    esac
done

if [ -z "$TORCH_SPYRE_SHA" ] || [ -z "$WORKDIR" ]; then
    usage
fi

# ---------------------------------------------------------------------
# Step 1 — refuse if WORKDIR exists
# ---------------------------------------------------------------------

if [ -e "$WORKDIR" ]; then
    echo "FATAL: workdir already exists: $WORKDIR" >&2
    echo "       supported-control setup requires a fresh directory; refusing to proceed" >&2
    exit 3
fi

# ---------------------------------------------------------------------
# Step 2 — create WORKDIR and open the log
# ---------------------------------------------------------------------

if ! mkdir -p "$WORKDIR"; then
    echo "FATAL: could not create workdir: $WORKDIR" >&2
    exit 3
fi

LOG="$WORKDIR/setup_supported.log"

# Everything from here on is teed to the log.  Log first, exit second.
# `exec` redirects fd 1 and 2 for the remainder of the script so both
# stdout and stderr land in the log while still surfacing on the
# controlling terminal.
exec > >(tee -a "$LOG") 2>&1

log_step() {
    printf '\n===== [%s] %s =====\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
    # $1 = exit code, remaining args = message.
    local code="$1"; shift
    printf '\n[FAIL exit=%d] %s\n' "$code" "$*" >&2
    exit "$code"
}

log_step "setup_supported_env.sh starting"
echo "torch_spyre_sha : $TORCH_SPYRE_SHA"
echo "workdir         : $WORKDIR"
echo "python          : $PY"
echo "log             : $LOG"
echo "pwd             : $(pwd)"
echo "uname           : $(uname -a)"
echo "id              : $(id -un)@$(hostname 2>/dev/null || echo unknown-host)"

cd "$WORKDIR" || fail 3 "could not cd into $WORKDIR"

# ---------------------------------------------------------------------
# Step 3 — create the venv (with --system-site-packages)
# ---------------------------------------------------------------------
#
# Per /Users/tdeshane/torch-spyre-docs/docs/basic_install.md, the venv
# is created with --system-site-packages because SENDNN / DEEPTOOLS ship
# as system-level packages in the torch-aiu-runtime-dev image and are
# not pip-installable from the venv. Dropping --system-site-packages
# hides them from `import` and Stage 1 fails downstream with an opaque
# ModuleNotFoundError.

log_step "creating venv with $PY (--system-site-packages)"

if ! command -v "$PY" >/dev/null 2>&1; then
    fail 4 "python interpreter not found on PATH: $PY"
fi

"$PY" --version || fail 4 "python interpreter reported an error: $PY --version"

if ! "$PY" -m venv --system-site-packages .venv-supported; then
    fail 4 "python -m venv --system-site-packages .venv-supported failed"
fi

# From here on, activate the venv for every command in this shell.
# shellcheck disable=SC1091
source .venv-supported/bin/activate || fail 4 "could not source .venv-supported/bin/activate"

echo "which python : $(command -v python)"
echo "which pip    : $(command -v pip)"
python --version
pip --version

# ---------------------------------------------------------------------
# Step 4 — upgrade pip (fresh pip; anything else drifts)
# ---------------------------------------------------------------------

log_step "upgrading pip"

if ! python -m pip install --upgrade pip; then
    fail 4 "pip self-upgrade failed"
fi
pip --version

# ---------------------------------------------------------------------
# Step 4b — install basic_install.md prerequisites
# ---------------------------------------------------------------------
#
# Per /Users/tdeshane/torch-spyre-docs/docs/basic_install.md, the
# prerequisites are expecttest / wheel / psutil / pytest before the
# clone. dev_install.md adds the build toolchain (nanobind==2.9.2,
# ninja, pybind11, build, cmake~=3.26, regex) — we install these too
# because a real from-source torch-spyre editable install needs them
# even under basic_install.md's flow (the image ships them via
# system-site-packages, but re-pinning them into the venv guarantees
# the versions the docs prescribe).

log_step "installing basic_install.md prerequisites (expecttest wheel psutil pytest)"

if ! pip install expecttest wheel psutil pytest; then
    fail 4 "pip install expecttest wheel psutil pytest failed"
fi

log_step "installing dev_install.md build toolchain (nanobind==2.9.2 ninja pybind11 build cmake~=3.26 regex)"

if ! pip install nanobind==2.9.2 ninja pybind11 build "cmake~=3.26" regex; then
    fail 4 "pip install nanobind/ninja/pybind11/build/cmake/regex failed"
fi

# ---------------------------------------------------------------------
# Step 5 — clone torch-spyre and check out the recorded SHA
# ---------------------------------------------------------------------

log_step "cloning torch-spyre and checking out $TORCH_SPYRE_SHA"

if ! git clone https://github.com/torch-spyre/torch-spyre.git torch-spyre; then
    fail 5 "git clone https://github.com/torch-spyre/torch-spyre.git failed"
fi

cd torch-spyre || fail 5 "could not cd into torch-spyre"

# If the SHA is not reachable from the default fetch, do a broader
# fetch (covers PR-head SHAs that only live under refs/pull/*/head).
if ! git rev-parse --verify "${TORCH_SPYRE_SHA}^{commit}" >/dev/null 2>&1; then
    echo "SHA not reachable from default fetch; fetching all remotes"
    git fetch --quiet origin || true
fi
if ! git rev-parse --verify "${TORCH_SPYRE_SHA}^{commit}" >/dev/null 2>&1; then
    echo "SHA still not reachable; fetching all PR heads"
    git fetch --quiet origin '+refs/pull/*/head:refs/remotes/origin/pr/*' || true
fi

if ! git -c advice.detachedHead=false checkout "$TORCH_SPYRE_SHA"; then
    fail 5 "git checkout $TORCH_SPYRE_SHA failed"
fi

RESOLVED_SHA=$(git rev-parse HEAD)
echo "resolved torch-spyre HEAD: $RESOLVED_SHA"

# ---------------------------------------------------------------------
# Step 5b — install requirements/dev.txt minus torch
# ---------------------------------------------------------------------
#
# Per /Users/tdeshane/torch-spyre-docs/docs/dev_install.md:
#   pip install -r <(grep -v -E '^(torch)' \
#                    $DTI_PROJECT_ROOT/torch-spyre/requirements/dev.txt)
#
# We filter out any dependency line whose left-hand name is exactly
# "torch" (torch-followed-by-space/bracket/comparator/end-of-line);
# this keeps torch-cousins like torchvision if the file lists them,
# while still removing the raw `torch` pin so we can install torch
# from pyproject.toml at the exact declared spec below.

DEV_REQ="requirements/dev.txt"
if [ -f "$DEV_REQ" ]; then
    log_step "installing torch-spyre requirements/dev.txt (minus torch)"

    FILTERED_REQ="$WORKDIR/dev-no-torch.txt"
    if ! grep -v -E '^torch([[:space:]<>=!]|$)' "$DEV_REQ" > "$FILTERED_REQ"; then
        # grep -v with no matches is fine; -v returning 1 only on read
        # error. If the source file is unreadable, fail loudly.
        if [ ! -s "$FILTERED_REQ" ]; then
            fail 4 "could not filter torch out of $DEV_REQ into $FILTERED_REQ"
        fi
    fi
    echo "filtered requirements written to: $FILTERED_REQ"

    if ! pip install -r "$FILTERED_REQ"; then
        fail 4 "pip install -r $FILTERED_REQ failed"
    fi
else
    echo "note: $DEV_REQ not present at this SHA; skipping the dev.txt install"
fi

# ---------------------------------------------------------------------
# Step 6 — parse the torch pin from pyproject.toml at runtime
# ---------------------------------------------------------------------

log_step "parsing torch pin from pyproject.toml"

if [ ! -f pyproject.toml ]; then
    fail 6 "pyproject.toml not found at torch-spyre@$RESOLVED_SHA"
fi

# The parse deliberately uses tomllib (stdlib in 3.11+) and walks the
# whole [project] dependency list. It matches on package name
# (case-insensitive, normalized per PEP 503) so it survives any of:
#   torch~=2.13.0
#   torch >= 2.13, < 2.14
#   torch==2.13.*
#   TORCH ~= 2.13
# On the first match it prints the ORIGINAL, verbatim dependency
# string on stdout. Anything else prints nothing and exits non-zero
# so the caller cannot silently proceed with a wrong pin.
TORCH_SPEC=$(python - <<'PYEOF'
import re
import sys

try:
    import tomllib
except ImportError:
    # tomllib is 3.11+. Fall back to tomli if the operator is on 3.10;
    # otherwise this whole ladder does not apply.
    try:
        import tomli as tomllib  # type: ignore
    except ImportError as e:
        print(f"cannot parse pyproject.toml: no tomllib/tomli: {e}",
              file=sys.stderr)
        sys.exit(1)

def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

with open("pyproject.toml", "rb") as f:
    data = tomllib.load(f)

candidates: list[str] = []
project = data.get("project", {})
for dep in project.get("dependencies", []) or []:
    candidates.append(dep)
opt = project.get("optional-dependencies", {}) or {}
for group in opt.values():
    for dep in group or []:
        candidates.append(dep)

# Also inspect [tool.poetry.dependencies] and [build-system.requires]
# defensively — torch-spyre is currently PEP-621 style, but this is
# cheap insurance if the layout shifts.
poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
for name, spec in poetry.items():
    if isinstance(spec, str):
        candidates.append(f"{name} {spec}")
    elif isinstance(spec, dict) and "version" in spec:
        candidates.append(f"{name} {spec['version']}")

for dep in data.get("build-system", {}).get("requires", []) or []:
    candidates.append(dep)

# Find the first dependency whose package name normalizes to "torch".
name_re = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")
for raw in candidates:
    m = name_re.match(raw)
    if not m:
        continue
    if normalize(m.group(1)) == "torch":
        print(raw.strip())
        sys.exit(0)

print("no torch dependency found in pyproject.toml", file=sys.stderr)
sys.exit(2)
PYEOF
)
PARSE_RC=$?

if [ $PARSE_RC -ne 0 ] || [ -z "$TORCH_SPEC" ]; then
    fail 6 "could not parse torch pin from pyproject.toml (parse exit=$PARSE_RC)"
fi

echo "declared torch spec (verbatim): $TORCH_SPEC"

# ---------------------------------------------------------------------
# Step 7 — install torch at the declared spec
# ---------------------------------------------------------------------
#
# We pass the exact spec string to pip, including any operator
# (~=, ==, >=, etc.). This is the point of the whole exercise: the
# supported control installs torch at whatever the checked-out
# torch-spyre says it wants, not at whatever we remember it wanting.

log_step "installing torch at declared spec: $TORCH_SPEC"

if ! pip install "$TORCH_SPEC"; then
    fail 7 "pip install '$TORCH_SPEC' failed — Stage-1 SUPPORTED_CONTROL cannot proceed"
fi

INSTALLED_TORCH_VERSION=$(python -c 'import torch; print(torch.__version__)' 2>/dev/null || true)
if [ -z "$INSTALLED_TORCH_VERSION" ]; then
    fail 7 "torch installed but import failed — cannot report version"
fi
echo "torch installed version: $INSTALLED_TORCH_VERSION"

# ---------------------------------------------------------------------
# Step 8 — install torch-spyre editable, canonical build form
# ---------------------------------------------------------------------
#
# The invocation below is the canonical torch-spyre build, taken
# verbatim from:
#   /Users/tdeshane/torch-spyre-docs/scripts/build-torch-spyre.sh
# and documented in:
#   /Users/tdeshane/torch-spyre-docs/docs/basic_install.md
#   references/canonical-dev-flow.md (this skill)
#
# --no-deps is required because we already installed torch at the exact
# pyproject-declared spec above; without --no-deps pip's resolver
# considers evicting our torch to satisfy a transitive constraint,
# which either (a) uninstalls the torch we just installed and reinstalls
# a different build (defeating the whole "install at the declared pin"
# purpose of Stage 1), or (b) links torch-spyre's C++ extension against
# one libtorch and imports it against another — a false-pass that
# silently corrupts every later stage.
#
# --no-build-isolation is required because the torch-spyre build reads
# torch's own headers/ABI from the venv at compile time; pip's default
# isolated build environment would compile against a different torch
# than the one Stage 1 imports.
#
# Both flags are the documented default form of this install, not a
# workaround. Do not remove them.

log_step "installing torch-spyre editable from $(pwd) (canonical no-deps / no-build-isolation)"

# The canonical build requires the gcc-toolset c++ compiler shipped in
# torch-aiu-runtime-dev images. If it is absent the image is wrong; we
# refuse to fall back to system c++ because a mismatched compiler would
# link against a different libstdc++ than the one torch was built with,
# producing a torch-spyre .so that imports but breaks in subtle ways at
# runtime.
GCC_TOOLSET_CXX=$(ls /opt/rh/gcc-toolset-*/root/usr/bin/c++ 2>/dev/null | tail -1)
if [ -z "$GCC_TOOLSET_CXX" ]; then
    fail 8 "SUBSTRATE_FAILURE: /opt/rh/gcc-toolset-*/root/usr/bin/c++ not found; image is not a torch-aiu-runtime-dev variant"
fi
export CXX="ccache $GCC_TOOLSET_CXX"
echo "CXX = $CXX"

if ! ( cd "$WORKDIR/torch-spyre" && pip install -e . --no-deps --no-build-isolation -vvv --verbose 2>&1 | tee "$WORKDIR/build_supported.log" ); then
    fail 8 "pip install -e . --no-deps --no-build-isolation failed — Stage-2 SUPPORTED_CONTROL cannot proceed; leave this failure in place (see $WORKDIR/build_supported.log)"
fi

unset CXX

# ---------------------------------------------------------------------
# Step 9 — sanity import
# ---------------------------------------------------------------------

log_step "sanity import"

SANITY_OUT=$(python - <<'PYEOF'
import sys
try:
    import torch
except Exception as e:  # pragma: no cover — reported below
    print(f"SANITY_FAIL torch import: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(10)

try:
    import torch_spyre
except Exception as e:
    print(f"SANITY_FAIL torch_spyre import: {type(e).__name__}: {e}",
          file=sys.stderr)
    sys.exit(11)

torch_v  = getattr(torch, "__version__", "unknown")
spyre_v  = getattr(torch_spyre, "__version__", "unknown")
torch_p  = getattr(torch, "__file__", "unknown")
spyre_p  = getattr(torch_spyre, "__file__", "unknown")

print(f"torch.__version__       = {torch_v}")
print(f"torch.__file__          = {torch_p}")
print(f"torch_spyre.__version__ = {spyre_v}")
print(f"torch_spyre.__file__    = {spyre_p}")
PYEOF
) || SANITY_RC=$?

echo "$SANITY_OUT"

SANITY_RC=${SANITY_RC:-0}
if [ "$SANITY_RC" -ne 0 ]; then
    fail 9 "sanity import failed with exit=$SANITY_RC (see log above)"
fi

# ---------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------

log_step "setup_supported_env.sh complete"
echo "venv               : $WORKDIR/.venv-supported"
echo "torch-spyre tree   : $WORKDIR/torch-spyre"
echo "torch-spyre SHA    : $RESOLVED_SHA"
echo "declared torch spec: $TORCH_SPEC"
echo "torch installed    : $INSTALLED_TORCH_VERSION"
echo "log                : $LOG"
echo "build log          : $WORKDIR/build_supported.log"
exit 0

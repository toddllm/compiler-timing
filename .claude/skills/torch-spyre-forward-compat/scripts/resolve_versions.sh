#!/bin/bash
# Record current upstream SHAs for torch-spyre and pytorch at experiment
# start, plus the pytorch dependency string torch-spyre declares at that
# SHA. Writes a single JSON file the rest of the skill can read.
#
# torch-spyre is PRIVATE, so fetching its pyproject.toml requires an auth
# token. Provide one of:
#   - GITHUB_TOKEN env var (a token with `repo` scope on torch-spyre), or
#   - GH_TOKEN env var (same semantics).
# No cached fallback: if any lookup fails, exit non-zero.
#
# Usage:
#   resolve_versions.sh --out FILE

set -euo pipefail

TORCH_SPYRE_REPO="torch-spyre/torch-spyre"
PYTORCH_REPO="pytorch/pytorch"

usage() {
    cat >&2 <<EOF
usage: resolve_versions.sh --out FILE

Records current main SHAs for $TORCH_SPYRE_REPO and $PYTORCH_REPO plus the
pytorch dependency torch-spyre declares in pyproject.toml at that SHA.

Requires GITHUB_TOKEN (or GH_TOKEN) with read access to $TORCH_SPYRE_REPO.
EOF
    exit 2
}

die() { echo "resolve_versions.sh: $*" >&2; exit 1; }

OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT="${2:-}"; shift 2 ;;
        -h|--help) usage ;;
        *) usage ;;
    esac
done
[[ -n "$OUT" ]] || usage

for cmd in git curl awk sed python3; do
    command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
done

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
[[ -n "$TOKEN" ]] || die "GITHUB_TOKEN (or GH_TOKEN) must be set to read private repo $TORCH_SPYRE_REPO"

# Resolve HEAD SHA of a repo via git ls-remote. torch-spyre is private, so
# embed the token; pytorch is public but we send the header uniformly.
resolve_head_sha() {
    local repo="$1"
    local out
    out=$(git -c credential.helper= \
              -c http.extraheader="Authorization: Bearer $TOKEN" \
              ls-remote "https://github.com/$repo" HEAD 2>/dev/null) \
        || die "git ls-remote failed for $repo"
    local sha
    sha=$(printf '%s\n' "$out" | awk 'NF{print $1; exit}')
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "unexpected ls-remote output for $repo: $out"
    printf '%s' "$sha"
}

TORCH_SPYRE_SHA=$(resolve_head_sha "$TORCH_SPYRE_REPO")
PYTORCH_SHA=$(resolve_head_sha "$PYTORCH_REPO")

# Fetch pyproject.toml at the resolved torch-spyre SHA from the GitHub API.
# The `contents` endpoint returns raw file bytes with the raw media type.
PYPROJECT_URL="https://api.github.com/repos/$TORCH_SPYRE_REPO/contents/pyproject.toml?ref=$TORCH_SPYRE_SHA"
PYPROJECT_TXT=$(curl -fsSL \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github.raw" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$PYPROJECT_URL") \
    || die "failed to fetch pyproject.toml at $TORCH_SPYRE_REPO@$TORCH_SPYRE_SHA"

[[ -n "$PYPROJECT_TXT" ]] || die "empty pyproject.toml from $TORCH_SPYRE_REPO@$TORCH_SPYRE_SHA"

# Extract the torch requirement string. torch-spyre declares its pytorch
# dep in [project].dependencies as a PEP 508 line like "torch~=2.13.0".
# We prefer python3's tomllib (Python >= 3.11); fall back to a permissive
# awk/sed scan if tomllib is missing. Both routes look at the same file.
DECLARED_TORCH=$(printf '%s' "$PYPROJECT_TXT" | python3 - <<'PY' 2>/dev/null || true
import re, sys
txt = sys.stdin.read()
try:
    import tomllib
    data = tomllib.loads(txt)
except Exception:
    data = None

def emit(dep):
    print(dep)
    sys.exit(0)

if data is not None:
    proj = data.get("project", {})
    for dep in proj.get("dependencies", []) or []:
        name = re.split(r"[\s<>=!~;\[]", dep, 1)[0].strip().lower()
        if name == "torch":
            emit(dep.strip())
    for group, deps in (proj.get("optional-dependencies") or {}).items():
        for dep in deps or []:
            name = re.split(r"[\s<>=!~;\[]", dep, 1)[0].strip().lower()
            if name == "torch":
                emit(dep.strip())

# Fallback: scan lines for a torch requirement in a dependencies array.
for raw in txt.splitlines():
    line = raw.strip().strip(",").strip()
    if not line or line.startswith("#"):
        continue
    if (line.startswith('"') and line.endswith('"')) or \
       (line.startswith("'") and line.endswith("'")):
        line = line[1:-1]
    m = re.match(r"^torch(\s|[<>=!~;\[]|$)", line)
    if m:
        emit(line.strip())
sys.exit(1)
PY
)

DECLARED_TORCH=$(printf '%s' "$DECLARED_TORCH" | sed -e 's/[[:space:]]*$//')
[[ -n "$DECLARED_TORCH" ]] || die "could not find a torch dependency in pyproject.toml at $TORCH_SPYRE_REPO@$TORCH_SPYRE_SHA"

TIMESTAMP=$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')

# Emit the JSON via python3 to guarantee valid escaping.
OUT="$OUT" \
TIMESTAMP="$TIMESTAMP" \
TORCH_SPYRE_REPO="$TORCH_SPYRE_REPO" \
TORCH_SPYRE_SHA="$TORCH_SPYRE_SHA" \
DECLARED_TORCH="$DECLARED_TORCH" \
PYTORCH_REPO="$PYTORCH_REPO" \
PYTORCH_SHA="$PYTORCH_SHA" \
python3 - <<'PY'
import json, os, sys
doc = {
    "schema_version": 1,
    "timestamp": os.environ["TIMESTAMP"],
    "torch_spyre": {
        "repo": os.environ["TORCH_SPYRE_REPO"],
        "branch": "main",
        "sha": os.environ["TORCH_SPYRE_SHA"],
        "declared_pytorch_dep": os.environ["DECLARED_TORCH"],
    },
    "pytorch": {
        "repo": os.environ["PYTORCH_REPO"],
        "branch": "main",
        "sha": os.environ["PYTORCH_SHA"],
    },
}
out = os.environ["OUT"]
tmp = out + ".tmp"
with open(tmp, "w") as f:
    json.dump(doc, f, indent=2, sort_keys=False)
    f.write("\n")
os.replace(tmp, out)
print(out)
PY

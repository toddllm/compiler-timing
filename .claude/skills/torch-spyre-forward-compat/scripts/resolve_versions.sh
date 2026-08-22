#!/bin/bash
# Record current upstream SHAs for torch-spyre and pytorch at experiment
# start, plus the pytorch dependency string torch-spyre declares at that
# SHA. Writes a single JSON file the rest of the skill can read.
#
# torch-spyre's public https endpoints (git ls-remote, raw.githubusercontent.com)
# happen to be readable anonymously on the dev cluster this skill runs on
# (verified 2026-08-22). The script attempts anonymous fetch first. If that
# fails (network policy or repo permissions change), it falls back to a
# Bearer token from:
#   - GITHUB_TOKEN env var (a token with `repo` scope on torch-spyre), or
#   - GH_TOKEN env var (same semantics).
# If both anonymous and token routes fail, exit non-zero.
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

Attempts anonymous fetch first. Falls back to GITHUB_TOKEN / GH_TOKEN if
anonymous fetch fails (network policy or repo permission change).
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

# Resolve HEAD SHA of a repo via git ls-remote. Try anonymous first
# (torch-spyre's ls-remote/raw endpoints happen to be readable anonymously,
# verified 2026-08-22 on the dev cluster); fall back to a Bearer token only
# if the anonymous fetch fails. This makes the script usable from fresh
# pods that don't have GITHUB_TOKEN wired up.
resolve_head_sha() {
    local repo="$1"
    local out
    if out=$(git -c credential.helper= ls-remote "https://github.com/$repo" HEAD 2>/dev/null); then
        :
    elif [[ -n "$TOKEN" ]]; then
        out=$(git -c credential.helper= \
                  -c http.extraheader="Authorization: Bearer $TOKEN" \
                  ls-remote "https://github.com/$repo" HEAD 2>/dev/null) \
            || die "git ls-remote failed for $repo (anonymous and with token)"
    else
        die "git ls-remote failed for $repo anonymously; set GITHUB_TOKEN and retry"
    fi
    local sha
    sha=$(printf '%s\n' "$out" | awk 'NF{print $1; exit}')
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "unexpected ls-remote output for $repo: $out"
    printf '%s' "$sha"
}

TORCH_SPYRE_SHA=$(resolve_head_sha "$TORCH_SPYRE_REPO")
PYTORCH_SHA=$(resolve_head_sha "$PYTORCH_REPO")

# Fetch pyproject.toml at the resolved torch-spyre SHA. Try raw.githubusercontent.com
# anonymously first (works on this dev cluster); fall back to the authenticated
# GitHub contents API if the raw endpoint returns anything other than 200.
RAW_URL="https://raw.githubusercontent.com/$TORCH_SPYRE_REPO/$TORCH_SPYRE_SHA/pyproject.toml"
if PYPROJECT_TXT=$(curl -fsSL "$RAW_URL" 2>/dev/null); then
    :
elif [[ -n "$TOKEN" ]]; then
    PYPROJECT_URL="https://api.github.com/repos/$TORCH_SPYRE_REPO/contents/pyproject.toml?ref=$TORCH_SPYRE_SHA"
    PYPROJECT_TXT=$(curl -fsSL \
        -H "Authorization: Bearer $TOKEN" \
        -H "Accept: application/vnd.github.raw" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "$PYPROJECT_URL") \
        || die "failed to fetch pyproject.toml at $TORCH_SPYRE_REPO@$TORCH_SPYRE_SHA (anonymous and with token)"
else
    die "failed to fetch pyproject.toml at $TORCH_SPYRE_REPO@$TORCH_SPYRE_SHA anonymously; set GITHUB_TOKEN and retry"
fi

[[ -n "$PYPROJECT_TXT" ]] || die "empty pyproject.toml from $TORCH_SPYRE_REPO@$TORCH_SPYRE_SHA"

# Extract the torch requirement string. torch-spyre declares its pytorch
# dep in [project].dependencies as a PEP 508 line like "torch~=2.13.0".
# We prefer python3's tomllib (Python >= 3.11); fall back to a permissive
# awk/sed scan if tomllib is missing. Both routes look at the same file.
# Pass pyproject content via env var so python's stdin stays free for its
# script argument (the heredoc). Piping stdin AND a heredoc-to-`python3 -`
# both fight for fd0 and the heredoc wins, giving python 0 chars of input.
DECLARED_TORCH=$(PYPROJECT_TXT="$PYPROJECT_TXT" python3 - <<'PY'
import os, re, sys
txt = os.environ.get("PYPROJECT_TXT", "")
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
) || DECLARED_TORCH=""

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

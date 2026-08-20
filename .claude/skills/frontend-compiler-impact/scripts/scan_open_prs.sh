#!/usr/bin/env bash
# Fetch current open PRs from a repo and produce a ranked triage.
# No device time. No repo clone. Just reads via `gh`.
#
# Usage:
#   scan_open_prs.sh torch-spyre/torch-spyre
#   scan_open_prs.sh torch-spyre/torch-spyre --limit 20
#   scan_open_prs.sh torch-spyre/torch-spyre --json > /tmp/scan.json
set -euo pipefail

REPO=""
LIMIT=100
FORMAT="markdown"

while [ $# -gt 0 ]; do
    case "$1" in
        --limit) LIMIT="$2"; shift 2 ;;
        --json)  FORMAT="json"; shift ;;
        --help) sed -n '2,10p' "$0" >&2; exit 0 ;;
        *) REPO="$1"; shift ;;
    esac
done

if [ -z "$REPO" ]; then
    echo "usage: scan_open_prs.sh <owner/repo> [--limit N] [--json]" >&2
    exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"

prs=$(GH_HOST=github.com gh pr list --repo "$REPO" --state open --limit "$LIMIT" \
    --json number,title,author,url,isDraft,changedFiles,files 2>/dev/null)

classify_one() {
    local pr_json="$1"
    local files triage level hot_stages rank run_rec stages
    files=$(echo "$pr_json" | jq -c '{changed_files: [.files[].path]}')
    triage=$(echo "$files" | python3 "$HERE/static_triage.py" 2>/dev/null || echo '{}')
    level=$(echo "$triage" | jq -r '.level_decision.level // 0')
    stages=$(echo "$triage" | jq -c '[.static_impact[].stage] | unique | sort')
    hot_stages=$(echo "$triage" | jq -r '[.static_impact[] | select(.stage=="dedup" or .stage=="coarse_tile" or .stage=="restickify") | .stage] | unique | join(",")')
    if [ -n "$hot_stages" ]; then
        rank="HIGH"
        run_rec="TARGETED_RUN or SCALING_RUN"
    elif [ "$level" -ge 3 ]; then
        rank="HIGH"
        run_rec="SCALING_RUN"
    elif [ "$level" -ge 1 ]; then
        rank="MEDIUM"
        run_rec="TARGETED_RUN"
    else
        rank="NONE"
        run_rec="NO_RUN"
    fi
    echo "$pr_json" | jq -c \
        --arg rank "$rank" \
        --argjson stages "$stages" \
        --argjson level "$level" \
        --arg run_rec "$run_rec" \
        '. + {rank: $rank, stages: $stages, level: $level, run_recommendation: $run_rec}'
}

scan=$(echo "$prs" | jq -c '.[]' | while read -r pr; do
    classify_one "$pr"
done | jq -sc '{prs: .}')

if [ "$FORMAT" = "json" ]; then
    echo "$scan"
    exit 0
fi

echo "# Open-PR scan -- $REPO"
echo ""
echo "| Rank | # | Title | Level | Stages | Recommendation |"
echo "|:---|---:|:---|---:|:---|:---|"
echo "$scan" | jq -r '.prs
    | sort_by([
        (if .rank == "HIGH" then 0 elif .rank == "MEDIUM" then 1 elif .rank == "LOW" then 2 else 3 end),
        .number * -1
      ])
    | .[] |
    "| \(.rank) | \(.number) | \(.title[:60] | gsub("\\|"; "\\|")) | \(.level) | \(.stages | join(", ")) | \(.run_recommendation) |"'
echo ""
echo "_Scan produced with no device time. Apply the full static assessment (SKILL.md) before running any timed sample._"

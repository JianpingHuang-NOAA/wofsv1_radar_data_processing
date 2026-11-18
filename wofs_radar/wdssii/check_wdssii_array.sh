#!/bin/bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

source "$ROOT/radar_runtime.sh"

CDATE="${1:?Usage: $0 CDATE DOMAIN}"

DOMAIN="${2:?Missing DOMAIN}"

RUN_ROOT="$(cat \
    "$RADAR_CASE_ROOT/$CDATE/$DOMAIN/latest_run.txt")"

JOB_ID="$(cat "$RUN_ROOT/job_id.txt")"

echo "=================================================="
echo "CDATE    : $CDATE"
echo "DOMAIN   : $DOMAIN"
echo "JOB_ID   : $JOB_ID"
echo "RUN_ROOT : $RUN_ROOT"
echo "=================================================="

total=0
completed=0

printf "%-6s %-8s %-15s %12s\n" \
    TASK RADAR STATUS ELAPSED_SEC

while read -r radar; do

    total=$((total + 1))

    marker="$RUN_ROOT/status/$radar.done"

    if [[ -s "$marker" ]]; then

        elapsed="$(awk '{print $3}' "$marker")"

        printf "%-6d %-8s %-15s %12s\n" \
            "$total" "$radar" COMPLETED "$elapsed"

        completed=$((completed + 1))

    else

        printf "%-6d %-8s %-15s %12s\n" \
            "$total" "$radar" NOT_COMPLETE "-"

    fi

done < "$RUN_ROOT/radar_sites.txt"

echo "=================================================="
echo "Total stations : $total"
echo "Completed      : $completed"
echo "Remaining      : $((total-completed))"

if [[ -s "$RUN_ROOT/status/STAGE.done" ]]; then
    echo "Staging        : COMPLETED"
else
    echo "Staging        : NOT_COMPLETE"
fi

echo "=================================================="

if [[ -s "$RUN_ROOT/stage_job_id.txt" ]]; then

    STAGE_JOB_ID="$(cat "$RUN_ROOT/stage_job_id.txt")"

    JOB_ID="$JOB_ID,$STAGE_JOB_ID"

fi

sacct -j "$JOB_ID" \
    --format=JobID,JobName%25,State,Elapsed,AllocCPUS,MaxRSS,ExitCode

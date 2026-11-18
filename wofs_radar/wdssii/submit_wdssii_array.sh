#!/bin/bash

set -euo pipefail

RADAR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

source "$RADAR_ROOT/radar_runtime.sh"

die()
{
    echo "[ERROR] $*" >&2
    exit 1
}

#-----------------------------------------------------------------------
# Case configuration
#-----------------------------------------------------------------------

CDATE="${1:?Usage: $0 CDATE DOMAIN [ALL|N] [--dry-run]}"

DOMAIN="${2:?Missing DOMAIN}"

LIMIT="${3:-$MAX_CONCURRENT}"

LIMIT="${LIMIT^^}"

MODE="${4:-}"

[[ "$MODE" == "" || "$MODE" == "--dry-run" ]] || \
    die "Invalid fourth argument"

[[ "$CDATE" =~ ^[0-9]{10}$ ]] || \
    die "Invalid CDATE"

[[ "$DOMAIN" =~ ^[A-Za-z0-9_-]+$ ]] || \
    die "Invalid DOMAIN"

[[ "$LIMIT" == ALL || "$LIMIT" =~ ^[1-9][0-9]*$ ]] || \
    die "Invalid concurrency"

PDY="${CDATE:0:8}"

cyc="${CDATE:8:2}"

VALID_DATE="$(date -u -d \
    "${PDY:0:4}-${PDY:4:2}-${PDY:6:2} $cyc:00" \
    +%Y%m%d%H)" || die "Invalid date"

[[ "$VALID_DATE" == "$CDATE" ]] || \
    die "Invalid CDATE"

PDYp1="$(date -u -d "$PDY +1 day" +%Y%m%d)"

#-----------------------------------------------------------------------
# Locate DOMAIN_SETUP radar list
#-----------------------------------------------------------------------

COM_CASE="$COMROOT/wofs/$WOFS_VERSION/wofs.$PDY/$cyc/$DOMAIN"

RADAR_LIST="$COM_CASE/radars_${PDY}_${DOMAIN}.csh"

RADAR_LIST="${RADAR_LIST_OVERRIDE:-$RADAR_LIST}"

NEXRAD_DIR="$NEXRAD_ROOT/$PDY"

[[ -s "$RADAR_LIST" ]] || \
    die "Missing radar list: $RADAR_LIST"

[[ -x "$WOFS_PYTHON" ]] || \
    die "Missing Python: $WOFS_PYTHON"

[[ -d "$NEXRAD_DIR" ]] || \
    die "Missing input directory: $NEXRAD_DIR"

#-----------------------------------------------------------------------
# Create unique case directory
#-----------------------------------------------------------------------

CASE_ROOT="$RADAR_CASE_ROOT/$CDATE/$DOMAIN"

mkdir -p "$CASE_ROOT"

RUN_ROOT="$(mktemp -d "$CASE_ROOT/run.XXXXXXXX")"

mkdir -p "$RUN_ROOT"/{logs,work,status,WDSSII,CLOUD_OBS,scripts}

cp -p "$RADAR_LIST" "$RUN_ROOT/radar_list.csh"

cp -p "$RADAR_ROOT"/{radar_runtime.sh,run_wdssii_site.slurm,run_wdssii_stage.slurm,runwdssii.py} \
    "$RUN_ROOT/scripts/"

SITE_LIST="$RUN_ROOT/radar_sites.txt"

#-----------------------------------------------------------------------
# Extract and validate radar stations
#-----------------------------------------------------------------------

"$WOFS_PYTHON" - "$RUN_ROOT/radar_list.csh" \
    > "$SITE_LIST" <<'PYTHON'

import re
import sys
import math
from pathlib import Path

text = Path(sys.argv[1]).read_text()

text = "\n".join(
    line.split("#", 1)[0]
    for line in text.splitlines()
)

match = re.search(
    r"^\s*setenv\s+num_rad\s+(\d+)\s*$",
    text,
    re.MULTILINE,
)

if not match:
    sys.exit("[ERROR] Missing num_rad")

nradars = int(match.group(1))


def read_array(name):

    match = re.search(
        r"^\s*set\s+" + name + r"\s*=\s*\((.*?)\)",
        text,
        re.MULTILINE | re.DOTALL,
    )

    if not match:
        sys.exit(f"[ERROR] Missing {name}")

    return match.group(1).replace("\\", " ").split()


radars = read_array("rad_name")

if nradars < 1:
    sys.exit("[ERROR] Empty radar list")

if len(radars) != nradars:
    sys.exit("[ERROR] Radar count mismatch")

if len(set(radars)) != nradars:
    sys.exit("[ERROR] Duplicate radar stations")

for radar in radars:

    if not re.fullmatch(r"K[A-Z0-9]{3}", radar):
        sys.exit(f"[ERROR] Invalid radar: {radar}")

for field in ("rad_lon", "rad_lat", "rad_alt"):

    values = read_array(field)

    if len(values) != nradars:
        sys.exit(f"[ERROR] Invalid count for {field}")

    if not all(math.isfinite(float(x)) for x in values):
        sys.exit(f"[ERROR] Invalid values for {field}")

print("\n".join(radars))

print(
    f"[PASS] Validated {nradars} unique radar stations",
    file=sys.stderr,
)

PYTHON

NRADARS="$(wc -l < "$SITE_LIST")"

# ALL means every station is eligible to run concurrently.
if [[ "$LIMIT" == ALL ]] || (( LIMIT > NRADARS )); then
    LIMIT="$NRADARS"
fi

#-----------------------------------------------------------------------
# Validate input files
#-----------------------------------------------------------------------

echo "===== Radar input validation ====="

while read -r radar; do

    [[ -d "$NEXRAD_DIR/$radar" ]] || \
        die "Missing input directory: $radar"

    count="$(find "$NEXRAD_DIR/$radar" \
        -maxdepth 1 \
        -type f \
        -name '*V06' \
        -size +0c | wc -l)"

    (( count > 0 )) || \
        die "No input files for $radar"

    printf "%-8s %8d input files\n" "$radar" "$count"

done < "$SITE_LIST"

#-----------------------------------------------------------------------
# Save case configuration
#-----------------------------------------------------------------------

WDSSII_DIR="$RUN_ROOT/WDSSII"

CLOUD_ROOT="$RUN_ROOT/CLOUD_OBS"

CONFIG="$RUN_ROOT/case.env"

for var in \
    CDATE DOMAIN PDY cyc PDYp1 \
    RADAR_ROOT RADAR_LIST RUN_ROOT SITE_LIST \
    NEXRAD_DIR WDSSII_DIR CLOUD_ROOT \
    HOMEwofs WOFS_PYTHON WDSSII_HOME WDSSII_SSL_HOME \
    NRADARS LIMIT
do
    printf 'export %s=%q\n' "$var" "${!var}"
done > "$CONFIG"

#-----------------------------------------------------------------------
# Print configuration
#-----------------------------------------------------------------------

echo "=================================================="
echo "CDATE          : $CDATE"
echo "DOMAIN         : $DOMAIN"
echo "RADAR_LIST     : $RADAR_LIST"
echo "NRADARS        : $NRADARS"
echo "MAX_CONCURRENT : $LIMIT"
echo "ARRAY          : 1-$NRADARS%$LIMIT"
echo "RUN_ROOT       : $RUN_ROOT"
echo "=================================================="

nl -ba "$SITE_LIST"

if [[ "$MODE" == "--dry-run" ]]; then
    echo "[PASS] Dry run: no jobs submitted"
    exit 0
fi

#-----------------------------------------------------------------------
# Slurm options
#-----------------------------------------------------------------------

opts=(--account="$RADAR_ACCOUNT")

if [[ -n "$RADAR_PARTITION" ]]; then
    opts+=(--partition="$RADAR_PARTITION")
fi

if [[ -n "$RADAR_QOS" ]]; then
    opts+=(--qos="$RADAR_QOS")
fi

#-----------------------------------------------------------------------
# Submit radar array
#-----------------------------------------------------------------------

JOB_ID="$(sbatch \
    "${opts[@]}" \
    --parsable \
    --job-name="radar_${DOMAIN}_${cyc}" \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task="$RADAR_CPUS" \
    --mem="$RADAR_MEM" \
    --time="$RADAR_WALLTIME" \
    --array="1-${NRADARS}%${LIMIT}" \
    --output="$RUN_ROOT/logs/radar_%A_%a.out" \
    --error="$RUN_ROOT/logs/radar_%A_%a.err" \
    "$RUN_ROOT/scripts/run_wdssii_site.slurm" \
    "$CONFIG")"

JOB_ID="${JOB_ID%%;*}"

echo "$JOB_ID" > "$RUN_ROOT/job_id.txt"

echo "$RUN_ROOT" > "$CASE_ROOT/latest_run.txt"

#-----------------------------------------------------------------------
# Submit dependent staging job
#-----------------------------------------------------------------------

STAGE_JOB_ID="$(sbatch \
    "${opts[@]}" \
    --parsable \
    --job-name="radar_stage_${DOMAIN}_${cyc}" \
    --dependency="afterok:${JOB_ID}" \
    --kill-on-invalid-dep=yes \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=1 \
    --mem=4G \
    --time=02:00:00 \
    --output="$RUN_ROOT/logs/stage_%j.out" \
    --error="$RUN_ROOT/logs/stage_%j.err" \
    "$RUN_ROOT/scripts/run_wdssii_stage.slurm" \
    "$CONFIG")"

STAGE_JOB_ID="${STAGE_JOB_ID%%;*}"

echo "$STAGE_JOB_ID" > "$RUN_ROOT/stage_job_id.txt"

echo "=================================================="
echo "[SUCCESS] Slurm jobs submitted"
echo "Radar array : $JOB_ID"
echo "Staging job : $STAGE_JOB_ID"
echo "Stations    : $NRADARS"
echo "Concurrent  : $LIMIT"
echo "Run root    : $RUN_ROOT"
echo "=================================================="

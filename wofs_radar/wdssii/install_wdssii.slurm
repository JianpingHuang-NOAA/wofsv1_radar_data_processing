#!/bin/bash
#=======================================================================
# Install dynamic WoFS WDSS-II Slurm workflow
#=======================================================================

set -euo pipefail

ROOT="$(pwd -P)"

[[ -s "$ROOT/runwdssii.py" ]] || {
    echo "[ERROR] Run from the wdssii directory"
    exit 1
}

TMP="$(mktemp -d "$ROOT/.radar-install.XXXXXXXX")"

trap 'rm -rf "$TMP"' EXIT

#=======================================================================
# 1. Centralized runtime environment
#=======================================================================

cat > "$TMP/radar_runtime.sh" <<'RUNTIME'
#!/bin/bash

export TZ=UTC

export HOMEwofs="${HOMEwofs:-/scratch3/NCEPDEV/wofs/Jianping.Huang/wofs-workflow-wps}"

export WOFS_PYTHON="${WOFS_PYTHON:-$HOMEwofs/python_env/bin/python}"

export WDSSII_HOME="${WDSSII_HOME:-/scratch4/NCEPDEV/fv3-cam/Jianping.Huang/WoFS/sorc/WDSSII}"

export WDSSPATH="$WDSSII_HOME"

export WDSSII_SSL_HOME="${WDSSII_SSL_HOME:-$HOME/envs/wdssii-ssl11}"

export W2_CONFIG_LOCATION="$WDSSII_HOME/w2config"

export PATH="$WDSSII_HOME/bin:$PATH"

export LD_LIBRARY_PATH="$WDSSII_HOME/lib:$WDSSII_SSL_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

export COMROOT="${COMROOT:-/scratch3/NCEPDEV/stmp/Jianping.Huang/com}"

export WOFS_VERSION="${WOFS_VERSION:-v1.0}"

export OBS_ROOT="${OBS_ROOT:-/scratch4/NCEPDEV/stmp/Jianping.Huang/wofs/realtime/OBSGEN}"

export NEXRAD_ROOT="${NEXRAD_ROOT:-$OBS_ROOT/NEXRAD}"

export RADAR_CASE_ROOT="${RADAR_CASE_ROOT:-$OBS_ROOT/RADAR_CASES}"

export RADAR_ACCOUNT="${RADAR_ACCOUNT:-wofs}"

export RADAR_PARTITION="${RADAR_PARTITION:-}"

export RADAR_QOS="${RADAR_QOS:-}"

export RADAR_CPUS="${RADAR_CPUS:-1}"

export RADAR_MEM="${RADAR_MEM:-8G}"

export RADAR_WALLTIME="${RADAR_WALLTIME:-04:00:00}"

export MAX_CONCURRENT="${MAX_CONCURRENT:-ALL}"

RUNTIME

#=======================================================================
# 2. Dynamic Slurm submission controller
#=======================================================================

cat > "$TMP/submit_wdssii_array.sh" <<'SUBMIT'
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

SUBMIT

#=======================================================================
# 3. Single-station Slurm worker
#=======================================================================

cat > "$TMP/run_wdssii_site.slurm" <<'WORKER'
#!/bin/bash

set -euo pipefail

source "${1:?Missing case.env}"

source "$RUN_ROOT/scripts/radar_runtime.sh"

TASK_ID="${SLURM_ARRAY_TASK_ID:?Missing task ID}"

RADAR="$(sed -n "${TASK_ID}p" "$SITE_LIST")"

[[ "$RADAR" =~ ^K[A-Z0-9]{3}$ ]] || {
    echo "[ERROR] Invalid radar station"
    exit 1
}

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"

log()
{
    printf '[%s] [%s] %s\n' \
        "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" \
        "$RADAR" "$*"
}

die()
{
    log "[ERROR] $*" >&2
    exit 1
}

#-----------------------------------------------------------------------
# Independent working directory
#-----------------------------------------------------------------------

export DATA

DATA="$(mktemp -d "$RUN_ROOT/work/${RADAR}.XXXXXXXX")"

mkdir -p "$DATA"/{input,output,logs}

mkdir "$DATA/input/$RADAR"

#-----------------------------------------------------------------------
# Validate WDSS-II runtime
#-----------------------------------------------------------------------

[[ -x "$WOFS_PYTHON" ]] || \
    die "Missing Python"

[[ -x "$WDSSII_HOME/bin/ldm2netcdf" ]] || \
    die "Missing ldm2netcdf"

[[ -d "$W2_CONFIG_LOCATION" ]] || \
    die "Missing WDSS-II configuration"

LIBS="$(ldd "$WDSSII_HOME/bin/ldm2netcdf")"

if grep -q 'not found' <<< "$LIBS"; then
    echo "$LIBS"
    die "Missing shared libraries"
fi

#-----------------------------------------------------------------------
# Prepare one radar station
#-----------------------------------------------------------------------

find "$NEXRAD_DIR/$RADAR" \
    -maxdepth 1 \
    -type f \
    -name '*V06' \
    -size +0c \
    -exec ln -s -t "$DATA/input/$RADAR" -- {} +

[[ -n "$(find "$DATA/input/$RADAR" \
    -type l -print -quit)" ]] || \
    die "No input files"

cp -p "$RUN_ROOT/scripts/runwdssii.py" "$DATA/"

cd "$DATA"

#-----------------------------------------------------------------------
# Process radar station
#-----------------------------------------------------------------------

log "Starting WDSS-II"
log "CDATE=$CDATE"
log "DOMAIN=$DOMAIN"
log "RADAR=$RADAR"
log "NODE=$(hostname)"
log "TASK_ID=$TASK_ID"
log "DATA=$DATA"

SECONDS=0

"$WOFS_PYTHON" -u \
    "$DATA/runwdssii.py" \
    "$PDY" \
    "$DATA/input" \
    "$DATA/output" \
    "$DATA/output" \
    K || die "runwdssii.py failed"

#-----------------------------------------------------------------------
# Validate processed files
#-----------------------------------------------------------------------

for field in Velocity ReflectivityQC; do

    FIELD_DIR="$DATA/output/$RADAR/$field"

    [[ -d "$FIELD_DIR" ]] || \
        die "Missing field: $field"

    count="$(find "$FIELD_DIR" \
        -type f \
        -name '*.netcdf' \
        -size +0c | wc -l)"

    (( count > 0 )) || \
        die "No uncompressed NetCDF files for $field"

    log "$field: $count files"

done

#-----------------------------------------------------------------------
# Publish validated output
#-----------------------------------------------------------------------

FINAL_OUTPUT="$WDSSII_DIR/$RADAR"

[[ ! -e "$FINAL_OUTPUT" ]] || \
    die "Output already exists: $FINAL_OUTPUT"

mv "$DATA/output/$RADAR" "$FINAL_OUTPUT"

printf '%s %s %s\n' \
    "$RADAR" \
    "$(date -u +%FT%TZ)" \
    "$SECONDS" \
    > "$RUN_ROOT/status/$RADAR.done.tmp"

mv "$RUN_ROOT/status/$RADAR.done.tmp" \
    "$RUN_ROOT/status/$RADAR.done"

log "Elapsed seconds: $SECONDS"

log "[SUCCESS] WDSS-II processing completed"

WORKER

#=======================================================================
# 4. Dependent radar staging job
#=======================================================================

cat > "$TMP/run_wdssii_stage.slurm" <<'STAGE'
#!/bin/bash

set -euo pipefail

source "${1:?Missing case.env}"

export TZ=UTC

echo "===== Radar staging ====="
echo "CDATE=$CDATE"
echo "DOMAIN=$DOMAIN"

# Verify all radar stations completed.

while read -r radar; do

    [[ -s "$RUN_ROOT/status/$radar.done" ]] || {
        echo "[ERROR] Incomplete radar: $radar"
        exit 1
    }

done < "$SITE_LIST"

# Stage only stations belonging to this case.

while read -r radar; do

    for field in Velocity ReflectivityQC; do

        src="$WDSSII_DIR/$radar/$field"

        [[ -d "$src" ]] || exit 1

        for day in "$PDY" "$PDYp1"; do

            dst="$CLOUD_ROOT/$day/Radar/$radar/$field"

            mkdir -p "$dst"

            rsync -a \
                --include='*/' \
                --include="${day}*.netcdf" \
                --exclude='*' \
                --prune-empty-dirs \
                "$src/" "$dst/"

        done

    done

    echo "[PASS] Staged $radar"

done < "$SITE_LIST"

# Validate staged files.

for day in "$PDY" "$PDYp1"; do

    count="$(find "$CLOUD_ROOT/$day" \
        -type f \
        -name '*.netcdf' \
        -size +0c | wc -l)"

    (( count > 0 )) || {
        echo "[ERROR] No staged observations for $day"
        exit 1
    }

    echo "$day: $count staged files"

done

date -u +%FT%TZ > "$RUN_ROOT/status/STAGE.done"

echo "[SUCCESS] Radar staging completed"
echo "CLOUD_ROOT=$CLOUD_ROOT"

STAGE

#=======================================================================
# 5. Dynamic monitoring script
#=======================================================================

cat > "$TMP/check_wdssii_array.sh" <<'CHECK'
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

CHECK

#=======================================================================
# 6. Validate all generated scripts
#=======================================================================

echo "===== Bash syntax validation ====="

for file in "$TMP"/*; do

    bash -n "$file"

    echo "[PASS] ${file##*/}"

done

#=======================================================================
# 7. Back up and install
#=======================================================================

BACKUP="$(mktemp -d "$ROOT/backup_slurm.XXXXXXXX")"

for file in "$TMP"/*; do

    name="${file##*/}"

    if [[ -e "$ROOT/$name" ]]; then
        cp -p "$ROOT/$name" "$BACKUP/"
    fi

    install -m 755 "$file" "$ROOT/$name"

    echo "[PASS] Installed $name"

done

echo "=================================================="
echo "[SUCCESS] WDSS-II Slurm installation completed"
echo "Installation directory: $ROOT"
echo "Backup directory      : $BACKUP"
echo "=================================================="

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

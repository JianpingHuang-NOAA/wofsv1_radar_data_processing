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

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

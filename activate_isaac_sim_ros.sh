#!/usr/bin/env bash
set -e

CONDA_BASE="${CONDA_EXE%/bin/conda}"
if [ -z "${CONDA_BASE}" ] || [ ! -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]; then
    CONDA_BASE="$(conda info --base)"
fi

source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate isaac_sim_ros_py310
export PYTHONNOUSERSITE=1
source /opt/ros/humble/setup.bash

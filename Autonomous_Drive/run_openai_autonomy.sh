#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DB_PATH="${SCRIPT_DIR}/merged.db"
DB_DIR="${SCRIPT_DIR}/maps"

RGB_TOPIC="/rgb"
DEPTH_TOPIC="/depth"
CAMERA_INFO_TOPIC="/camera_info"
GOAL_FRAME="start_local"
POSE_SOURCE="imu_cmd_vel"
POSE_SOURCE_EXPLICIT=0
ODOM_TOPIC="/rtabmap/odom"
ODOM_TOPIC_EXPLICIT=0
ODOM_YAW_SIGN="-1"
CMD_LINEAR_SIGN="-1"
YAW_SOURCE="hybrid"
IMU_TOPIC="/imu"
CONTROL_MODE="direct_cmd_vel"
RTABMAP_FRAME_ID=""
USE_SIM_TIME="false"
RTABMAP_VIZ="true"
RVIZ="false"
RTABMAP_ARGS=""
RTABMAP_MODE="mapping"
LAUNCH_RTABMAP=0
FRESH_DB=0
RTABMAP_PID=""
AUTONOMY_ARGS=()
RTABMAP_NAMESPACE=""
RTABMAP_ODOM_TOPIC_NAME=""
RTABMAP_LOCALIZATION="false"

set +u
source "${REPO_ROOT}/activate_isaac_sim_ros.sh"
set -u

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "OPENAI_API_KEY is not set." >&2
    echo "Export OPENAI_API_KEY before running this script." >&2
    exit 1
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --launch-rtabmap)
            LAUNCH_RTABMAP=1
            shift
            ;;
        --rgb-topic)
            RGB_TOPIC="$2"
            shift 2
            ;;
        --depth-topic)
            DEPTH_TOPIC="$2"
            shift 2
            ;;
        --camera-info-topic)
            CAMERA_INFO_TOPIC="$2"
            shift 2
            ;;
        --pose-source)
            POSE_SOURCE="$2"
            POSE_SOURCE_EXPLICIT=1
            shift 2
            ;;
        --goal-frame)
            GOAL_FRAME="$2"
            shift 2
            ;;
        --odom-topic)
            ODOM_TOPIC="$2"
            ODOM_TOPIC_EXPLICIT=1
            shift 2
            ;;
        --odom-yaw-sign)
            ODOM_YAW_SIGN="$2"
            shift 2
            ;;
        --cmd-linear-sign)
            CMD_LINEAR_SIGN="$2"
            shift 2
            ;;
        --yaw-source)
            YAW_SOURCE="$2"
            shift 2
            ;;
        --imu-topic)
            IMU_TOPIC="$2"
            shift 2
            ;;
        --control-mode)
            CONTROL_MODE="$2"
            shift 2
            ;;
        --database-path)
            DB_PATH="$2"
            shift 2
            ;;
        --fresh-db)
            FRESH_DB=1
            shift
            ;;
        --rtabmap-frame-id)
            RTABMAP_FRAME_ID="$2"
            shift 2
            ;;
        --use-sim-time)
            USE_SIM_TIME="$2"
            shift 2
            ;;
        --rtabmap-viz)
            RTABMAP_VIZ="$2"
            shift 2
            ;;
        --rviz)
            RVIZ="$2"
            shift 2
            ;;
        --rtabmap-args)
            RTABMAP_ARGS="$2"
            shift 2
            ;;
        --rtabmap-mode)
            RTABMAP_MODE="$2"
            shift 2
            ;;
        *)
            AUTONOMY_ARGS+=("$1")
            shift
            ;;
    esac
done

print_cmd() {
    printf '  '
    printf '%q ' "$@"
    printf '\n'
}

detect_camera_frame_id() {
    local detected=""
    detected="$(timeout 5s ros2 topic echo "${CAMERA_INFO_TOPIC}" --once 2>/dev/null | awk '/frame_id:/ {print $2; exit}' || true)"
    if [[ -n "${detected}" ]]; then
        printf '%s\n' "${detected}"
        return 0
    fi
    return 1
}

cleanup() {
    if [[ -n "${RTABMAP_PID}" ]] && kill -0 "${RTABMAP_PID}" 2>/dev/null; then
        kill "${RTABMAP_PID}" 2>/dev/null || true
        wait "${RTABMAP_PID}" 2>/dev/null || true
    fi
}

if [[ "${FRESH_DB}" -eq 1 ]]; then
    mkdir -p "${DB_DIR}"
    DB_PATH="${DB_DIR}/rtabmap_$(date +%Y%m%d_%H%M%S).db"
fi

if [[ "${RTABMAP_MODE}" != "mapping" && "${RTABMAP_MODE}" != "localization" ]]; then
    echo "Unsupported --rtabmap-mode: ${RTABMAP_MODE}" >&2
    echo "Use --rtabmap-mode mapping or --rtabmap-mode localization" >&2
    exit 1
fi

if [[ "${RTABMAP_MODE}" == "localization" && "${FRESH_DB}" -eq 1 ]]; then
    echo "--fresh-db cannot be used with --rtabmap-mode localization" >&2
    exit 1
fi

if [[ "${RTABMAP_MODE}" == "localization" ]]; then
    RTABMAP_LOCALIZATION="true"
    if [[ ! -f "${DB_PATH}" ]]; then
        echo "RTAB-Map localization mode requires an existing database: ${DB_PATH}" >&2
        exit 1
    fi
fi

if [[ -z "${RTABMAP_FRAME_ID}" ]]; then
    RTABMAP_FRAME_ID="$(detect_camera_frame_id || true)"
fi

if [[ -z "${RTABMAP_FRAME_ID}" ]]; then
    RTABMAP_FRAME_ID="camera_color_optical_frame"
fi

if [[ "${ODOM_TOPIC}" == /* ]]; then
    ODOM_TOPIC_STRIPPED="${ODOM_TOPIC#/}"
else
    ODOM_TOPIC_STRIPPED="${ODOM_TOPIC}"
fi

if [[ "${ODOM_TOPIC_STRIPPED}" == */* ]]; then
    RTABMAP_NAMESPACE="${ODOM_TOPIC_STRIPPED%/*}"
    RTABMAP_ODOM_TOPIC_NAME="${ODOM_TOPIC_STRIPPED##*/}"
else
    RTABMAP_NAMESPACE=""
    RTABMAP_ODOM_TOPIC_NAME="${ODOM_TOPIC_STRIPPED}"
fi

if [[ -z "${RTABMAP_ODOM_TOPIC_NAME}" ]]; then
    RTABMAP_ODOM_TOPIC_NAME="odom"
fi

if [[ "${POSE_SOURCE_EXPLICIT}" -eq 0 ]]; then
    if [[ "${LAUNCH_RTABMAP}" -eq 1 || "${ODOM_TOPIC_EXPLICIT}" -eq 1 ]]; then
        POSE_SOURCE="odom"
    fi
fi

RTABMAP_CMD=(
    ros2 launch rtabmap_launch rtabmap.launch.py
    "namespace:=${RTABMAP_NAMESPACE}"
    "localization:=${RTABMAP_LOCALIZATION}"
    "rgb_topic:=${RGB_TOPIC}"
    "depth_topic:=${DEPTH_TOPIC}"
    "camera_info_topic:=${CAMERA_INFO_TOPIC}"
    "visual_odometry:=true"
    "imu_topic:=${IMU_TOPIC}"
    "frame_id:=${RTABMAP_FRAME_ID}"
    "odom_topic:=${RTABMAP_ODOM_TOPIC_NAME}"
    "database_path:=${DB_PATH}"
    "use_sim_time:=${USE_SIM_TIME}"
    "rtabmap_viz:=${RTABMAP_VIZ}"
    "rviz:=${RVIZ}"
)

if [[ -n "${RTABMAP_ARGS}" ]]; then
    RTABMAP_CMD+=("args:=${RTABMAP_ARGS}")
fi

AUTONOMY_CMD=(
    python "${SCRIPT_DIR}/openai_bev_autodrive.py"
    --rgb-topic "${RGB_TOPIC}"
    --depth-topic "${DEPTH_TOPIC}"
    --camera-info-topic "${CAMERA_INFO_TOPIC}"
    --goal-frame "${GOAL_FRAME}"
    --pose-source "${POSE_SOURCE}"
    --odom-topic "${ODOM_TOPIC}"
    --odom-yaw-sign "${ODOM_YAW_SIGN}"
    --cmd-linear-sign "${CMD_LINEAR_SIGN}"
    --yaw-source "${YAW_SOURCE}"
    --imu-topic "${IMU_TOPIC}"
    --control-mode "${CONTROL_MODE}"
    --database-path "${DB_PATH}"
    "${AUTONOMY_ARGS[@]}"
)

cat <<EOF
[run_openai_autonomy]
RTAB-Map mode: ${RTABMAP_MODE}
Pose source: ${POSE_SOURCE}
Yaw source: ${YAW_SOURCE}
Cmd linear sign: ${CMD_LINEAR_SIGN}
IMU topic: ${IMU_TOPIC}
Control mode: ${CONTROL_MODE}
Goal frame: ${GOAL_FRAME}
Database: ${DB_PATH}
RTAB-Map command:
EOF
print_cmd "${RTABMAP_CMD[@]}"
cat <<EOF
Autonomy command:
EOF
print_cmd "${AUTONOMY_CMD[@]}"

if [[ "${LAUNCH_RTABMAP}" -eq 1 ]]; then
    trap cleanup EXIT INT TERM
    echo "Launching RTAB-Map in background..."
    "${RTABMAP_CMD[@]}" &
    RTABMAP_PID="$!"
    sleep 3
fi

if [[ "${LAUNCH_RTABMAP}" -eq 1 ]]; then
    "${AUTONOMY_CMD[@]}"
else
    exec "${AUTONOMY_CMD[@]}"
fi

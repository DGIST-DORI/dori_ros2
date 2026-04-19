conda activate env_isaaclab

# (2) ROS 버전 명시
export ROS_DISTRO=humble

# (3) DDS 구현체 선택 (권장)
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

# (4) ROS2 Bridge 라이브러리 경로 추가 (★핵심★)
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:\
$CONDA_PREFIX/lib/python3.11/site-packages/isaacsim/exts/isaacsim.ros2.bridge/humble/lib

# (선택) FastDDS SHM 경고 제거
export FASTDDS_SHM_TRANSPORT=0

# (5) Isaac Sim 실행 (pip 설치 기준)
isaacsim
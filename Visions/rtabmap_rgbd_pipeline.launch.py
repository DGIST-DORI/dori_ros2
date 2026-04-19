#!/usr/bin/env python3
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    # Core topics
    rgb_topic = LaunchConfiguration("rgb_topic")
    depth_topic = LaunchConfiguration("depth_topic")
    camera_info_topic = LaunchConfiguration("camera_info_topic")
    frame_id = LaunchConfiguration("frame_id")

    # Outputs
    cloud_topic = LaunchConfiguration("cloud_topic")
    assembled_cloud_topic = LaunchConfiguration("assembled_cloud_topic")
    odom_topic = LaunchConfiguration("odom_topic")

    # RTAB-Map include
    rtabmap_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("rtabmap_launch"), "launch", "rtabmap.launch.py"]
            )
        ),
        launch_arguments={
            "rgb_topic": rgb_topic,
            "depth_topic": depth_topic,
            "camera_info_topic": camera_info_topic,
            "frame_id": frame_id,
            "rgbd_sync": LaunchConfiguration("rgbd_sync"),
            "approx_sync": LaunchConfiguration("approx_sync"),
            "depth_scale": LaunchConfiguration("depth_scale"),
            "use_sim_time": LaunchConfiguration("use_sim_time"),
            "rtabmap_viz": LaunchConfiguration("rtabmap_viz"),
            "rviz": LaunchConfiguration("rviz"),
            "namespace": LaunchConfiguration("rtabmap_ns"),
            "database_path": LaunchConfiguration("database_path"),
            "args": LaunchConfiguration("rtabmap_args"),
        }.items(),
    )

    # Depth -> per-frame cloud
    point_cloud = Node(
        package="rtabmap_util",
        executable="point_cloud_xyzrgb",
        output="screen",
        parameters=[
            {
                "decimation": LaunchConfiguration("pc_decimation"),
                "max_depth": LaunchConfiguration("pc_max_depth"),
                "voxel_size": LaunchConfiguration("pc_voxel_size"),
                "approx_sync": LaunchConfiguration("approx_sync"),
            }
        ],
        remappings=[
            ("rgb/image", rgb_topic),
            ("depth/image", depth_topic),
            ("rgb/camera_info", camera_info_topic),
            ("cloud", cloud_topic),
        ],
    )

    # Accumulate cloud in map frame
    cloud_assembler = Node(
        package="rtabmap_util",
        executable="point_cloud_assembler",
        output="screen",
        parameters=[
            {
                "fixed_frame_id": LaunchConfiguration("map_frame_id"),
                "max_clouds": LaunchConfiguration("pc_max_clouds"),
                "voxel_size": LaunchConfiguration("pc_assembler_voxel"),
                "wait_for_transform": LaunchConfiguration("wait_for_transform"),
            }
        ],
        remappings=[
            ("cloud", cloud_topic),
            ("odom", odom_topic),
            ("assembled_cloud", assembled_cloud_topic),
        ],
    )

    # Ground/obstacles segmentation on assembled cloud
    obstacles_detection = Node(
        condition=IfCondition(LaunchConfiguration("enable_obstacles_detection")),
        package="rtabmap_util",
        executable="obstacles_detection",
        output="screen",
        parameters=[
            {
                "frame_id": frame_id,
                "Grid/MaxGroundHeight": LaunchConfiguration("grid_max_ground_height"),
                "Grid/MaxObstacleHeight": LaunchConfiguration("grid_max_obstacle_height"),
                "Grid/RangeMax": LaunchConfiguration("grid_range_max"),
            }
        ],
        remappings=[
            ("cloud", assembled_cloud_topic),
            ("ground", LaunchConfiguration("ground_topic")),
            ("obstacles", LaunchConfiguration("obstacles_topic")),
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "rgb_topic", default_value="/camera/camera/color/image_raw"
            ),
            DeclareLaunchArgument(
                "depth_topic",
                default_value="/camera/camera/aligned_depth_to_color/image_raw",
            ),
            DeclareLaunchArgument(
                "camera_info_topic", default_value="/camera/camera/color/camera_info"
            ),
            DeclareLaunchArgument(
                "frame_id", default_value="camera_color_optical_frame"
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("rtabmap_ns", default_value="rtabmap"),
            DeclareLaunchArgument("database_path", default_value="~/.ros/rtabmap.db"),
            DeclareLaunchArgument("rtabmap_args", default_value=""),
            DeclareLaunchArgument("rgbd_sync", default_value="true"),
            DeclareLaunchArgument("approx_sync", default_value="true"),
            DeclareLaunchArgument(
                "depth_scale",
                default_value="0.001",
                description="0.001 for 16UC1, 1.0 for 32FC1",
            ),
            DeclareLaunchArgument("rtabmap_viz", default_value="true"),
            DeclareLaunchArgument("rviz", default_value="false"),
            DeclareLaunchArgument("odom_topic", default_value="/rtabmap/odom"),
            DeclareLaunchArgument("map_frame_id", default_value="map"),
            DeclareLaunchArgument("wait_for_transform", default_value="0.2"),
            DeclareLaunchArgument("cloud_topic", default_value="/camera/cloud"),
            DeclareLaunchArgument(
                "assembled_cloud_topic", default_value="/rtabmap/assembled_cloud"
            ),
            DeclareLaunchArgument("pc_decimation", default_value="2"),
            DeclareLaunchArgument("pc_max_depth", default_value="5.0"),
            DeclareLaunchArgument("pc_voxel_size", default_value="0.02"),
            DeclareLaunchArgument("pc_max_clouds", default_value="30"),
            DeclareLaunchArgument("pc_assembler_voxel", default_value="0.05"),
            DeclareLaunchArgument("enable_obstacles_detection", default_value="true"),
            DeclareLaunchArgument("ground_topic", default_value="/rtabmap/ground"),
            DeclareLaunchArgument("obstacles_topic", default_value="/rtabmap/obstacles"),
            DeclareLaunchArgument("grid_max_ground_height", default_value="0.10"),
            DeclareLaunchArgument("grid_max_obstacle_height", default_value="1.50"),
            DeclareLaunchArgument("grid_range_max", default_value="6.0"),
            rtabmap_launch,
            point_cloud,
            cloud_assembler,
            obstacles_detection,
        ]
    )

"""
Development assembly launch for DORI.

Composes the production robot launch and optionally adds developer tools
such as dashboard/rosbridge.

Usage:
  ros2 launch bringup robot_dev.launch.py
  ros2 launch bringup robot_dev.launch.py enable_dashboard:=false
"""

import os
import logging

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    bringup_dir = get_package_share_directory('bringup')

    args = [
        DeclareLaunchArgument(
            'enable_dashboard',
            default_value='true',
            description='Launch rosbridge + web dashboard (development only)',
        ),
        DeclareLaunchArgument(
            'dori_namespace',
            default_value='/dori',
            description='Base namespace for all DORI topics',
        ),
    ]

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'robot.launch.py')
        ),
        launch_arguments={
            'dori_namespace': LaunchConfiguration('dori_namespace'),
        }.items(),
    )

    launch_list = [
        *args,
        robot_launch,
    ]

    try:
        dashboard_pkg_dir = get_package_share_directory('dashboard_pkg')
        launch_list.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(dashboard_pkg_dir, 'launch', 'dashboard.launch.py')
                ),
                condition=IfCondition(LaunchConfiguration('enable_dashboard')),
            )
        )
    except Exception as exc:
        # Dashboard is an optional development tool; skip it if the package is unavailable.
        logging.getLogger(__name__).warning(
            "Failed to include optional dashboard launch: %s", exc
        )

    return LaunchDescription(launch_list)

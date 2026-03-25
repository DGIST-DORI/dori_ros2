"""
Interaction stack launch (state machine/coordinator only).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    args = [
        DeclareLaunchArgument(
            'idle_timeout_sec',
            default_value='10.0',
            description='Seconds to wait for STT input before returning to IDLE',
        ),
        DeclareLaunchArgument(
            'greeting_text',
            default_value='안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
            description='Greeting spoken when wake word is detected',
        ),
    ]

    hri_manager_node = Node(
        package='interaction_pkg',
        executable='hri_manager_node',
        name='hri_manager_node',
        output='screen',
        parameters=[{
            'idle_timeout_sec': LaunchConfiguration('idle_timeout_sec'),
            'greeting_text': LaunchConfiguration('greeting_text'),
        }],
    )

    return LaunchDescription([
        *args,
        hri_manager_node,
    ])

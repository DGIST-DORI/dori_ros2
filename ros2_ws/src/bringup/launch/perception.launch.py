"""
Perception stack launch (camera/vision only).

Nodes started:
  depth_camera_node           (perception_pkg) x 2  - front / rear cameras
  person_detection_node       (perception_pkg)
  landmark_detection_node     (perception_pkg)
  gesture_recognition_node    (perception_pkg)
  facial_expression_node      (perception_pkg)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    try:
        perception_pkg_dir = get_package_share_directory('perception_pkg')
        landmark_db_default = os.path.join(perception_pkg_dir, 'config', 'landmark_db.json')
    except Exception:
        landmark_db_default = 'landmark_db.json'

    args = [
        DeclareLaunchArgument('person_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_db', default_value=landmark_db_default),
        DeclareLaunchArgument('device', default_value='cuda'),
        DeclareLaunchArgument('visualize', default_value='false'),
        DeclareLaunchArgument('enable_landmark', default_value='true'),
        DeclareLaunchArgument('enable_gesture', default_value='true'),
        DeclareLaunchArgument('enable_expression', default_value='true'),
        DeclareLaunchArgument('camera_fps', default_value='15'),
        DeclareLaunchArgument('camera_width', default_value='640'),
        DeclareLaunchArgument('camera_height', default_value='480'),
    ]

    camera_params = {
        'width': LaunchConfiguration('camera_width'),
        'height': LaunchConfiguration('camera_height'),
        'fps': LaunchConfiguration('camera_fps'),
        'enable_depth': True,
        'align_depth_to_color': True,
    }

    depth_camera_front = Node(
        package='perception_pkg',
        executable='depth_camera_node',
        name='depth_camera_front',
        namespace='dori/camera/front',
        output='screen',
        parameters=[{**camera_params, 'serial_number': ''}],
        remappings=[
            ('color/image_raw', '/dori/camera/color/image_raw'),
            ('depth/image_raw', '/dori/camera/depth/image_raw'),
            ('color/camera_info', '/dori/camera/color/camera_info'),
            ('depth/camera_info', '/dori/camera/depth/camera_info'),
            ('depth_scale', '/dori/camera/depth_scale'),
        ],
    )

    depth_camera_rear = Node(
        package='perception_pkg',
        executable='depth_camera_node',
        name='depth_camera_rear',
        namespace='dori/camera/rear',
        output='screen',
        parameters=[{**camera_params, 'serial_number': ''}],
        remappings=[
            ('color/image_raw', '/dori/camera/rear/color/image_raw'),
            ('depth/image_raw', '/dori/camera/rear/depth/image_raw'),
            ('color/camera_info', '/dori/camera/rear/color/camera_info'),
            ('depth/camera_info', '/dori/camera/rear/depth/camera_info'),
            ('depth_scale', '/dori/camera/rear/depth_scale'),
        ],
    )

    person_detection_node = Node(
        package='perception_pkg',
        executable='person_detection_node',
        name='person_detection_node',
        output='screen',
        parameters=[{
            'model_path': LaunchConfiguration('person_model'),
            'confidence_threshold': 0.5,
            'device': LaunchConfiguration('device'),
            'visualize': LaunchConfiguration('visualize'),
            'use_depth': True,
            'interaction_distance_m': 2.0,
            'lost_timeout_sec': 5.0,
        }],
    )

    landmark_detection_node = Node(
        package='perception_pkg',
        executable='landmark_detection_node',
        name='landmark_detection_node',
        output='screen',
        parameters=[{
            'model_path': LaunchConfiguration('landmark_model'),
            'device': LaunchConfiguration('device'),
            'visualize': LaunchConfiguration('visualize'),
            'landmark_db_path': LaunchConfiguration('landmark_db'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_landmark')),
    )

    gesture_recognition_node = Node(
        package='perception_pkg',
        executable='gesture_recognition_node',
        name='gesture_recognition_node',
        output='screen',
        parameters=[{
            'visualize': LaunchConfiguration('visualize'),
            'active_only_on_trigger': True,
        }],
        condition=IfCondition(LaunchConfiguration('enable_gesture')),
    )

    facial_expression_node = Node(
        package='perception_pkg',
        executable='facial_expression_node',
        name='facial_expression_node',
        output='screen',
        parameters=[{
            'visualize': LaunchConfiguration('visualize'),
            'active_only_on_trigger': True,
        }],
        condition=IfCondition(LaunchConfiguration('enable_expression')),
    )

    return LaunchDescription([
        *args,
        depth_camera_front,
        depth_camera_rear,
        person_detection_node,
        landmark_detection_node,
        gesture_recognition_node,
        facial_expression_node,
    ])

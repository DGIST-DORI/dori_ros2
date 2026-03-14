"""
dashboard.launch.py  (updated)
Launches: rosbridge WebSocket + static HTTP server (port 3000) + knowledge API (port 3001)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('dashboard_pkg')
    web_dir = os.path.join(pkg_dir, 'web')

    if not os.path.isdir(web_dir):
        raise FileNotFoundError(
            'dashboard_pkg web assets not found. Expected directory: '
            f"'{web_dir}'. Build the frontend (web/dist) before installing and launching dashboard_pkg."
        )

    repo_root = os.path.abspath(os.path.join(pkg_dir, '..', '..', '..', '..'))

    # Path to knowledge API script (inside dashboard_pkg or project tools)
    knowledge_api_script = os.path.join(pkg_dir, 'scripts', 'knowledge_api.py')

    return LaunchDescription([

        # ── rosbridge WebSocket (port 9090) ───────────────────────────────
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{'port': 9090}],
        ),

        # ── Static frontend (port 3000) ───────────────────────────────────
        ExecuteProcess(
            cmd=['python3', '-m', 'http.server', '3000'],
            cwd=web_dir,
            output='screen',
        ),

        # ── Knowledge Manager REST API (port 3001) ────────────────────────
        ExecuteProcess(
            cmd=['python3', knowledge_api_script,
                 '--repo-root', repo_root,
                 '--port', '3001'],
            output='screen',
        ),
    ])

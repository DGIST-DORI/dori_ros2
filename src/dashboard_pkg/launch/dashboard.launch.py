"""
dashboard.launch.py
Launches: rosbridge WebSocket + unified dashboard server (frontend + API on port 3000)
          + Cloudflare Tunnel (port 3000 and 9090, optional)

Cloudflare Tunnel is enabled by default.
To disable: ros2 launch dashboard_pkg dashboard.launch.py tunnel:=false
"""

import os
import shutil

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _make_tunnel_actions(context, *args, **kwargs):
    """
    OpaqueFunction: runs at launch time so we can check if cloudflared is
    installed and read the 'tunnel' LaunchConfiguration value.
    """
    enable = LaunchConfiguration('tunnel').perform(context).lower()
    if enable not in ('true', '1', 'yes'):
        return []

    if shutil.which('cloudflared') is None:
        print(
            '\n[dashboard.launch] WARNING: tunnel:=true but cloudflared not found in PATH.\n'
            '  Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/\n'
            '  Skipping tunnel.\n'
        )
        return []

    # Tunnel script: wraps cloudflared and prints the public URL clearly.
    # Both tunnels write their URL to stderr; we tee it through a small
    # shell one-liner so it appears in the ROS launch console.
    dashboard_tunnel = ExecuteProcess(
        cmd=[
            'bash', '-c',
            # cloudflared prints the URL line like:
            #   INF +----------------------------+
            #   INF |  Your quick Tunnel has been created! Visit it at  |
            #   INF | https://xxxx.trycloudflare.com                    |
            # We grep for the https line and re-print it conspicuously.
            'cloudflared tunnel --url http://localhost:3000 2>&1 | '
            'tee /tmp/cloudflared_dashboard.log | '
            r'grep --line-buffered -oP "https://[a-z0-9\-]+\.trycloudflare\.com" | '
            'while read url; do '
            '  echo ""; '
            '  echo "╔══════════════════════════════════════════════════════╗"; '
            '  echo "║  DORI Dashboard (external)                          ║"; '
            '  echo "║  $url"; '
            '  echo "╚══════════════════════════════════════════════════════╝"; '
            '  echo ""; '
            'done',
        ],
        output='screen',
        name='cloudflared_dashboard',
    )

    ws_tunnel = ExecuteProcess(
        cmd=[
            'bash', '-c',
            'cloudflared tunnel --url http://localhost:9090 2>&1 | '
            'tee /tmp/cloudflared_ws.log | '
            r'grep --line-buffered -oP "https://[a-z0-9\-]+\.trycloudflare\.com" | '
            'while read url; do '
            '  echo ""; '
            '  echo "╔══════════════════════════════════════════════════════╗"; '
            '  echo "║  DORI ROS WebSocket (external)                      ║"; '
            '  echo "║  Replace ws:// → wss:// when pasting into dashboard ║"; '
            '  echo "║  $url"; '
            '  echo "╚══════════════════════════════════════════════════════╝"; '
            '  echo ""; '
            'done',
        ],
        output='screen',
        name='cloudflared_ws',
    )

    return [dashboard_tunnel, ws_tunnel]


def generate_launch_description():
    pkg_dir = get_package_share_directory('dashboard_pkg')
    web_dir = os.path.join(pkg_dir, 'web')

    if not os.path.isdir(web_dir):
        raise FileNotFoundError(
            'dashboard_pkg web assets not found. Expected directory: '
            f"'{web_dir}'. Build the frontend (web/dist) before installing and launching dashboard_pkg."
        )

    repo_root = os.path.abspath(os.path.join(pkg_dir, '..', '..', '..', '..'))
    knowledge_api_script = os.path.join(pkg_dir, 'scripts', 'knowledge_api.py')

    return LaunchDescription([

        # ── Launch argument ───────────────────────────────────────────────
        DeclareLaunchArgument(
            'tunnel',
            default_value='true',
            description='Enable Cloudflare Tunnel for external access (true/false)',
        ),

        # ── rosbridge WebSocket (port 9090) ───────────────────────────────
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{'port': 9090}],
        ),

        # ── Unified dashboard server (frontend + API on port 3000) ────────
        ExecuteProcess(
            cmd=['python3', knowledge_api_script,
                 '--repo-root', repo_root,
                 '--port', '3000',
                 '--web-dir', web_dir],
            output='both',
            name='knowledge_api_server',
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
        ),

        # ── Cloudflare Tunnel (optional, default: enabled) ────────────────
        OpaqueFunction(function=_make_tunnel_actions),
    ])

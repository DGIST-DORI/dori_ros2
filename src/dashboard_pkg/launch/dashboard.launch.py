from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import ExecuteProcess
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    pkg_dir = get_package_share_directory('dashboard_pkg')
    web_dir = os.path.join(pkg_dir, 'web')
    
    return LaunchDescription([
        # rosbridge WebSocket server node
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{
                'port': 9090,
            }]
        ),
        
        # React web serving by simple HTTP server
        ExecuteProcess(
            cmd=['python3', '-m', 'http.server', '3000'],
            cwd=web_dir,
            output='screen'
        )
    ])
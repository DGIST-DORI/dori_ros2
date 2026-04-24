from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, Command, FindExecutable
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_input_nodes = LaunchConfiguration("use_input_nodes")

    supervisor_params = PathJoinSubstitution([
        FindPackageShare("robot_supervisor"),
        "config",
        "supervisor_params.yaml",
    ])

    drive_params = PathJoinSubstitution([
        FindPackageShare("robot_drive"),
        "config",
        "drive_params.yaml",
    ])

    transform_params = PathJoinSubstitution([
        FindPackageShare("robot_transform"),
        "config",
        "transform_params.yaml",
    ])

    dxl_bridge_params = PathJoinSubstitution([
        FindPackageShare("robot_transform"),
        "config",
        "dxl_bridge_params.yaml",
    ])

    urdf_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "cubemars_mit.urdf.xacro",
    ])

    controllers_file = PathJoinSubstitution([
        FindPackageShare("robot_bringup"),
        "config",
        "bldc_controllers.yaml",
    ])

    robot_description = {
        "robot_description": Command([
            FindExecutable(name="xacro"),
            " ",
            urdf_file,
        ])
    }

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_input_nodes",
            default_value="false",
            description="Launch keyboard_input_node and virtual_vlm_input_node"
        ),

        Node(
            package="controller_manager",
            executable="ros2_control_node",
            parameters=[robot_description, controllers_file],
            output="screen",
        ),

        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[robot_description],
            output="screen",
        ),

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=["joint_state_broadcaster", "--controller-manager", "/controller_manager"],
            output="screen",
        ),

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=["bldc_velocity_controller", "--controller-manager", "/controller_manager"],
            output="screen",
        ),

        Node(
            package="controller_manager",
            executable="spawner",
            arguments=["bldc_position_controller", "--controller-manager", "/controller_manager", "--inactive"],
            output="screen",
        ),

        Node(
            package="robot_drive",
            executable="bldc_command_bridge_node",
            output="screen",
        ),

        Node(
            package="dynamixel_sdk_examples",
            executable="read_write_node",
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="dxl_bridge_node",
            parameters=[dxl_bridge_params],
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="dxl_state_publisher_node",
            parameters=[dxl_bridge_params],
            output="screen",
        ),

        Node(
            package="robot_supervisor",
            executable="mode_manager_node",
            parameters=[supervisor_params],
            output="screen",
        ),

        Node(
            package="robot_drive",
            executable="drive_controller_node",
            parameters=[drive_params],
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="transform_manager_node",
            parameters=[transform_params],
            output="screen",
        ),

        Node(
            package="robot_transform",
            executable="transform_controller_node",
            parameters=[transform_params],
            output="screen",
        ),

        Node(
            package="robot_error",
            executable="error_manager_node",
            output="screen",
        ),

        Node(
            package="robot_input",
            executable="keyboard_input_node",
            condition=IfCondition(use_input_nodes),
            output="screen",
        ),

        Node(
            package="robot_input",
            executable="virtual_vlm_input_node",
            condition=IfCondition(use_input_nodes),
            output="screen",
        ),
    ])

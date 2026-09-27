from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_config = str(Path(get_package_share_directory('rc_car_bringup')) / 'config' / 'rc_car.yaml')
    config = LaunchConfiguration('config_file')
    nodes = [
        Node(package='joy', executable='game_controller_node', name='joy_node',
             parameters=[config], output='screen'),
        Node(package='teleop_manager', executable='teleop_manager', name='teleop_manager',
             parameters=[config], output='screen'),
        Node(package='jetracer_driver', executable='jetracer_node', name='jetracer_node',
             parameters=[config, {'use_mock_hardware': ParameterValue(
                 LaunchConfiguration('use_mock_hardware'), value_type=bool)}], output='screen'),
    ]
    # Register before starting processes; a failed required node stops the stack.
    handlers = [RegisterEventHandler(OnProcessExit(
        target_action=node,
        on_exit=[EmitEvent(event=Shutdown(reason='A required RC car node exited.'))],
    )) for node in nodes]
    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('use_mock_hardware', default_value='true',
                              description='Use false only on the calibrated vehicle.'),
        *handlers,
        *nodes,
    ])

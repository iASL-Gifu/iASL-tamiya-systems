from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config = str(Path(get_package_share_directory('tinylidarnet_ros')) / 'config' / 'tinylidarnet.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('model_dir', description='metadata.jsonとweights.ptを含む絶対パス'),
        DeclareLaunchArgument('config_file', default_value=config),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        Node(
            package='tinylidarnet_ros', executable='tinylidarnet_node', name='tinylidarnet_node',
            parameters=[LaunchConfiguration('config_file'), {
                'model_dir': ParameterValue(LaunchConfiguration('model_dir'), value_type=str),
            }],
            remappings=[('scan', LaunchConfiguration('scan_topic'))],
            output='screen',
        ),
    ])

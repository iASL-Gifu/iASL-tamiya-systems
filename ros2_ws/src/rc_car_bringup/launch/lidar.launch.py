from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessStart
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def launch_lidar(context):
    connection = LaunchConfiguration('connection').perform(context)
    config_file = LaunchConfiguration('config_file').perform(context)
    if not config_file:
        config_file = str(Path(get_package_share_directory('rc_car_bringup'))
                          / 'config' / f'urg_{connection}.yaml')
    overrides = {}
    for name in ('ip_address', 'serial_port'):
        value = LaunchConfiguration(name).perform(context)
        if value:
            overrides[name] = value
    # The driver selects serial only when ip_address is empty.
    if connection == 'serial':
        overrides['ip_address'] = ''
    node = LifecycleNode(
        package='urg_node2', executable='urg_node2_node', name='urg_node2',
        namespace='', output='screen', parameters=[config_file, overrides],
        remappings=[('scan', LaunchConfiguration('scan_topic'))],
    )
    configure = RegisterEventHandler(OnProcessStart(
        target_action=node,
        on_start=[EmitEvent(event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        ))],
    ))
    activate = RegisterEventHandler(OnStateTransition(
        target_lifecycle_node=node, start_state='configuring', goal_state='inactive',
        entities=[EmitEvent(event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=Transition.TRANSITION_ACTIVATE,
        ))],
    ))
    return [configure, activate, node]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('connection', default_value='ether', choices=['ether', 'serial']),
        DeclareLaunchArgument('config_file', default_value='',
                              description='Custom YAML path; empty selects the connection preset.'),
        DeclareLaunchArgument('ip_address', default_value='',
                              description='Ethernet IP override; empty uses YAML.'),
        DeclareLaunchArgument('serial_port', default_value='',
                              description='Serial device override; empty uses YAML.'),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        OpaqueFunction(function=launch_lidar),
    ])

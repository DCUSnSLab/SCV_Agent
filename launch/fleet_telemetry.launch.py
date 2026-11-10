"""The monitoring agent.

ros2 launch fleet_telemetry fleet_telemetry.launch.py \
    [param_file:=<file>.param.yaml] [streams_file:=<file>.yaml] [container:=/<running container>]
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import ComposableNodeContainer, LoadComposableNodes
from launch_ros.descriptions import ComposableNode
from launch_ros.substitutions import FindPackageShare


def launch_setup(context):
    node = ComposableNode(
        package='fleet_telemetry',
        plugin='fleet_telemetry::Agent',
        name='fleet_telemetry',
        parameters=[
            LaunchConfiguration('param_file'),
            {'streams_file': LaunchConfiguration('streams_file')},
        ],
    )
    container = LaunchConfiguration('container').perform(context)
    if container:
        return [
            LoadComposableNodes(target_container=container, composable_node_descriptions=[node])
        ]
    return [
        ComposableNodeContainer(
            package='capa_ros',
            executable='capa_component_container',
            name='fleet_telemetry_container',
            namespace='',
            composable_node_descriptions=[node],
            output='screen',
        )
    ]


def generate_launch_description():
    def config(name):
        return PathJoinSubstitution([FindPackageShare('fleet_telemetry'), 'config', name])

    return LaunchDescription(
        [
            DeclareLaunchArgument('container', default_value=''),
            DeclareLaunchArgument('param_file', default_value=config('fleet_telemetry.param.yaml')),
            DeclareLaunchArgument('streams_file', default_value=config('streams.yaml')),
            OpaqueFunction(function=launch_setup),
        ]
    )

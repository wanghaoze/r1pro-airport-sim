import os
import json

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.conditions import IfCondition
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, EnvironmentVariable, PythonExpression
from launch_ros.substitutions import FindPackageShare


def _read_hardware_info(context):
    """Read hardware.json and return (robot_name, ecu).

    robot_name: 'R1LITE' or 'R1PRO'
    ecu:        value of the 'ECU' field under the robot key (e.g. 'E1', 'E3'), or '' if absent
    """
    json_path = LaunchConfiguration('hardware_json').perform(context)
    if not os.path.isfile(json_path):
        raise RuntimeError(f"[ERROR] Hardware config file not found: {json_path}")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"[ERROR] Failed to parse hardware JSON: {json_path}\nReason: {e}")

    if isinstance(data, dict) and 'R1-LITE' in data:
        robot_section = data['R1-LITE'] if isinstance(data['R1-LITE'], dict) else {}
        return 'R1LITE', robot_section.get('ECU', '')
    elif isinstance(data, dict) and 'R1-PRO' in data:
        robot_section = data['R1-PRO'] if isinstance(data['R1-PRO'], dict) else {}
        return 'R1PRO', robot_section.get('ECU', '')
    else:
        keys = list(data.keys()) if isinstance(data, dict) else []
        raise RuntimeError(
            f"[ERROR] Cannot detect robot type from hardware JSON. "
            f"Expected top-level key 'R1-LITE' or 'R1-PRO', got keys: {keys} (file: {json_path})")


def _check_key(context, *args, **kwargs):
    if LaunchConfiguration('independent_mode').perform(context) == 'true':
        return
    key = LaunchConfiguration('GALAXEA_WHOLE_BODY_TELEOPATION_KEY').perform(context)
    if not key:
        raise RuntimeError("[ERROR] GALAXEA_WHOLE_BODY_TELEOPATION_KEY is empty. Please set the environment variable "
                           "GALAXEA_WHOLE_BODY_TELEOPATION_KEY, or explicitly pass it during launch "
                           "using GALAXEA_WHOLE_BODY_TELEOPATION_KEY:=...")


def _setup_nodes(context, *args, **kwargs):
    pkg_path = FindPackageShare('teleoperation_ros2').perform(context)
    robot_name, ecu = _read_hardware_info(context)

    debug_flag = LaunchConfiguration('debug').perform(context)
    gdb_prefix = 'gnome-terminal -- gdb --ex run --args' if debug_flag == 'true' else ''

    if ecu == 'E3':
        r1pro_urdf = os.path.join(pkg_path, 'config/urdf/r1_pro_2026_whole_body.urdf')
    else:
        r1pro_urdf = os.path.join(pkg_path, 'config/urdf/r1_pro_whole_body.urdf')
    r1lite_urdf = LaunchConfiguration('R1LITE_urdf').perform(context)

    return [
        Node(package='teleoperation_ros2',
             executable='vr_vr_data_receiver_node',
             name='vr_data_receiver',
             output='screen',
             parameters=[
                 {'robot_name': robot_name},
                 {'enable_engage_by_operator': LaunchConfiguration('enable_engage_by_operator')},
             ]),
        Node(
            package='teleoperation_ros2',
            executable='vr_vr_controller_node',
            name='vr_controller',
            output='screen',
            prefix=gdb_prefix,
            parameters=[{
                'robot_name': robot_name
            }, {
                'ik_interp': LaunchConfiguration('ik_interp')
            }, {
                'enable_elbow_angle_cons': LaunchConfiguration('enable_elbow_angle_cons')
            }, {
                'enable_engage_by_operator': LaunchConfiguration('enable_engage_by_operator')
            }, {
                'left_gripper_openning_threshold': LaunchConfiguration('left_gripper_openning_threshold')
            }, {
                'left_gripper_closing_threshold': LaunchConfiguration('left_gripper_closing_threshold')
            }, {
                'right_gripper_openning_threshold': LaunchConfiguration('right_gripper_openning_threshold')
            }, {
                'right_gripper_closing_threshold': LaunchConfiguration('right_gripper_closing_threshold')
            }, {
                'enable_torso_tracking': LaunchConfiguration('enable_torso_tracking')
            }, {
                'gripper_pressed_closing': LaunchConfiguration('gripper_pressed_closing')
            }, {
                'arm_length_ratio': LaunchConfiguration('arm_length_ratio')
            }, {
                'independent_mode': LaunchConfiguration('independent_mode')
            }, {
                'GALAXEA_WHOLE_BODY_TELEOPATION_KEY': LaunchConfiguration('GALAXEA_WHOLE_BODY_TELEOPATION_KEY')
            }, {
                'R1PRO_urdf': r1pro_urdf
            }, {
                'R1LITE_urdf': r1lite_urdf
            }, {
                'vr_initializer_left_target_joint_states_r1pro': [0.0, 0.0, 0.0, -1.62, 0.0, 0.0, 0.0]
            }, {
                'vr_initializer_right_target_joint_states_r1pro': [0.0, 0.0, 0.0, -1.62, 0.0, 0.0, 0.0]
            }, {
                'vr_initializer_torso_target_joint_states_r1pro': [0.2, -0.5, -0.72, 0]#[0.3507, -0.7681, -0.6094, 0.0]
            }, {
                'vr_initializer_left_target_joint_states_r1lite': [0.0, 0.536, -0.017454, -0.5, 0.0, 0.0]
            }, {
                'vr_initializer_right_target_joint_states_r1lite': [0.0, 0.536, -0.017454, -0.5, 0.0, 0.0]
            }, {
                'vr_initializer_torso_target_joint_states_r1lite': [-0.4289, 1.4837, 1.0530]
            }],
        ),
        Node(package='teleoperation_ros2',
             executable='ik_interaction_marker_node',
             name='ik_interaction_marker',
             output='screen',
             condition=IfCondition(LaunchConfiguration('enable_ik_interaction_vize'))),
        Node(package='teleoperation_ros2',
             executable='target_pose_markers_node',
             name='target_pose_markers',
             output='screen',
             condition=IfCondition(LaunchConfiguration('enable_target_pose_vize')))
    ]


def generate_launch_description():
    pkg_path = FindPackageShare('teleoperation_ros2')

    return LaunchDescription([
        DeclareLaunchArgument('hardware_json', default_value='/opt/galaxea/body/hardware.json',
                              description='Path to hardware JSON for auto-detecting robot type'),
        DeclareLaunchArgument('ik_interp', default_value='true'),
        DeclareLaunchArgument('enable_elbow_angle_cons', default_value='true'),
        DeclareLaunchArgument('left_gripper_openning_threshold', default_value='80.0'),
        DeclareLaunchArgument('left_gripper_closing_threshold', default_value='0.0'),
        DeclareLaunchArgument('right_gripper_openning_threshold', default_value='80.0'),
        DeclareLaunchArgument('right_gripper_closing_threshold', default_value='0.0'),
        DeclareLaunchArgument('enable_engage_by_operator', default_value='false'),
        DeclareLaunchArgument('enable_torso_tracking', default_value='true'),
        DeclareLaunchArgument('gripper_pressed_closing', default_value='false'),
        DeclareLaunchArgument('arm_length_ratio', default_value='1.2'),
        DeclareLaunchArgument('independent_mode', default_value='false'),
        DeclareLaunchArgument('enable_ik_interaction_vize', default_value='false'),
        DeclareLaunchArgument('enable_target_pose_vize', default_value='false'),
        DeclareLaunchArgument('debug', default_value='false'),
        DeclareLaunchArgument('GALAXEA_WHOLE_BODY_TELEOPATION_KEY',
                              default_value=EnvironmentVariable('GALAXEA_WHOLE_BODY_TELEOPATION_KEY',
                                                                default_value='')),
        DeclareLaunchArgument('R1PRO_urdf',
                              default_value=PathJoinSubstitution([pkg_path, 'config/urdf/r1_pro_whole_body.urdf'])),
        DeclareLaunchArgument('R1LITE_urdf',
                              default_value=PathJoinSubstitution([pkg_path, 'config/urdf/r1_lite_whole_body.urdf'])),
        OpaqueFunction(function=_check_key),
        OpaqueFunction(function=_setup_nodes),
    ])

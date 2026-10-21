from pathlib import Path
from xml.etree import ElementTree as ET

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


URDF_PATH = Path.home() / "XLeRobot" / "simulation" / "xlerobot_urdf" / "xlerobot" / "xlerobot.urdf"


def generate_launch_description():
    if not URDF_PATH.is_file():
        raise FileNotFoundError(
            f"XLeRobot URDF not found at {URDF_PATH}. Extract simulation/xlerobot_urdf.zip first."
        )

    tree = ET.parse(URDF_PATH)
    root = tree.getroot()

    # The published MuJoCo joint_states include the arm joints, while the
    # URDF's floating base joint has no matching ROS state in this setup.
    # Fix the base in world so its full arm subtree remains available in TF.
    base_joint = root.find("./joint[@name='joint_0']")
    if base_joint is not None:
        base_joint.set("type", "fixed")

    mesh_root = URDF_PATH.parent
    for mesh in root.findall(".//mesh"):
        filename = mesh.get("filename", "")
        if filename.startswith("package://") or filename.startswith("file://"):
            continue
        mesh_path = (mesh_root / filename).resolve()
        if not mesh_path.is_file():
            raise FileNotFoundError(f"URDF mesh not found: {mesh_path}")
        mesh.set("filename", mesh_path.as_uri())

    robot_description = ET.tostring(root, encoding="unicode")
    rviz_config = Path(get_package_share_directory("nomi_xlerobot_sim")) / "rviz" / "xlerobot.rviz"
    return LaunchDescription([
        DeclareLaunchArgument(
            "start_rviz",
            default_value="true",
            description="Start RViz alongside the state and visualization bridges",
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[{"robot_description": robot_description}],
        ),
        # The MuJoCo state topic is the source of truth; this existing bridge
        # translates it to Odometry, Path, and Marker for RViz visualization.
        Node(
            package="nomi_rviz_bridge",
            executable="bridge_node",
            name="nomi_rviz_bridge",
            output="screen",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            arguments=["-d", str(rviz_config)],
            output="screen",
            condition=IfCondition(LaunchConfiguration("start_rviz")),
        ),
    ])

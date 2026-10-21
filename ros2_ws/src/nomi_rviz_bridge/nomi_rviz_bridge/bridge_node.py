import json
import math

import rclpy
from rclpy.node import Node

from std_msgs.msg import String
from nav_msgs.msg import Odometry, Path
from geometry_msgs.msg import PoseStamped
from visualization_msgs.msg import Marker


class NomiRvizBridge(Node):
    def __init__(self):
        super().__init__('nomi_rviz_bridge')

        self.odom_pub = self.create_publisher(
            Odometry, '/nomi/rviz/odom', 10
        )
        self.path_pub = self.create_publisher(
            Path, '/nomi/rviz/trajectory', 10
        )
        self.marker_pub = self.create_publisher(
            Marker, '/nomi/rviz/robot_marker', 10
        )

        self.create_subscription(
            String,
            '/nomi/xlerobot/state',
            self.state_callback,
            10
        )

        self.path = Path()
        self.path.header.frame_id = 'nomi_map'
        self.last_point = None

        self.get_logger().info(
            'NOMI RViz Bridge started (simulation observation only)'
        )

    def state_callback(self, msg):
        try:
            state = json.loads(msg.data)
            if state.get('status') != 'connected':
                return

            pos = state['position']
            rot = state['rotation']
            vel = state.get('velocity', {})

            x = float(pos['x'])
            y = float(pos['y'])
            yaw = float(rot['yaw'])

            stamp = self.get_clock().now().to_msg()

            # ROS quaternion from yaw
            qz = math.sin(yaw / 2.0)
            qw = math.cos(yaw / 2.0)

            odom = Odometry()
            odom.header.stamp = stamp
            odom.header.frame_id = 'nomi_map'
            odom.child_frame_id = 'nomi_base_link'

            odom.pose.pose.position.x = x
            odom.pose.pose.position.y = y
            odom.pose.pose.orientation.z = qz
            odom.pose.pose.orientation.w = qw

            linear = vel.get('linear', {})
            angular = vel.get('angular', {})

            # Current state linear velocity is map-frame.
            # Odometry twist convention requires child-frame.
            vx = float(linear.get('x', 0.0))
            vy = float(linear.get('y', 0.0))

            odom.twist.twist.linear.x = (
                math.cos(yaw) * vx + math.sin(yaw) * vy
            )
            odom.twist.twist.linear.y = (
                -math.sin(yaw) * vx + math.cos(yaw) * vy
            )
            odom.twist.twist.angular.z = float(
                angular.get('z', 0.0)
            )

            self.odom_pub.publish(odom)

            pose = PoseStamped()
            pose.header = odom.header
            pose.pose = odom.pose.pose

            if (
                self.last_point is None or
                math.hypot(
                    x - self.last_point[0],
                    y - self.last_point[1]
                ) >= 0.02
            ):
                self.path.poses.append(pose)
                self.last_point = (x, y)

                # Bound memory usage
                self.path.poses = self.path.poses[-3000:]

            self.path.header.stamp = stamp
            self.path_pub.publish(self.path)

            marker = Marker()
            marker.header = odom.header
            marker.ns = 'nomi_robot'
            marker.id = 0
            marker.type = Marker.ARROW
            marker.action = Marker.ADD
            marker.pose = odom.pose.pose

            marker.scale.x = 0.45
            marker.scale.y = 0.14
            marker.scale.z = 0.14

            marker.color.r = 0.1
            marker.color.g = 0.6
            marker.color.b = 1.0
            marker.color.a = 1.0

            self.marker_pub.publish(marker)

        except (ValueError, KeyError, TypeError) as exc:
            self.get_logger().warning(
                f'Invalid robot state: {exc}'
            )


def main(args=None):
    rclpy.init(args=args)
    node = NomiRvizBridge()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

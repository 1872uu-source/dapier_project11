"""Read the latest verified robot state from the NOMI ROS state topic."""

import json
import math
import threading
import time


class StateSkill:
    TOPIC = "/nomi/xlerobot/state"
    MAX_AGE_SECONDS = 1.5

    def __init__(self, node=None):
        self.node = node
        self._lock = threading.Lock()
        self._state = None
        self._received_at = None
        self._subscription = None
        if node is not None and hasattr(node, "create_subscription"):
            from std_msgs.msg import String
            self._subscription = node.create_subscription(String, self.TOPIC, self._state_callback, 10)

    def _state_callback(self, message):
        try:
            payload = json.loads(message.data)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        position = payload.get("position")
        rotation = payload.get("rotation")
        velocity = payload.get("velocity")
        if not isinstance(position, dict) or not isinstance(rotation, dict) or not isinstance(velocity, dict):
            return
        linear, angular = velocity.get("linear"), velocity.get("angular")
        values = [position.get("x"), position.get("y"), rotation.get("yaw")]
        if not isinstance(linear, dict) or not isinstance(angular, dict):
            return
        values += [linear.get("x"), linear.get("y"), angular.get("z")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            return
        with self._lock:
            self._state = payload
            self._received_at = time.monotonic()

    def get_robot_state(self) -> dict:
        with self._lock:
            state = self._state
            received_at = self._received_at
        if state is None or received_at is None:
            return {"success": False, "message": "로봇 상태 데이터가 아직 수신되지 않았습니다.",
                    "data": {"error_code": "state_unavailable", "topic": self.TOPIC}}
        age = time.monotonic() - received_at
        if age > self.MAX_AGE_SECONDS:
            return {"success": False, "message": f"로봇 상태 데이터가 오래됐습니다 ({age:.1f}초).",
                    "data": {"error_code": "state_stale", "topic": self.TOPIC, "age_ms": round(age * 1000)}}

        position = state["position"]
        rotation = state["rotation"]
        velocity = state["velocity"]
        data = {
            "source": "ros", "topic": self.TOPIC, "connection": state.get("status", "connected"),
            "age_ms": round(age * 1000, 1),
            "position": {"x": float(position["x"]), "y": float(position["y"]),
                         **({"z": float(position["z"])} if isinstance(position.get("z"), (int, float)) and not isinstance(position.get("z"), bool) else {})},
            "yaw": float(rotation["yaw"]),
            "velocity": {
                "linear": {"x": float(velocity["linear"]["x"]), "y": float(velocity["linear"]["y"])},
                "angular_z": float(velocity["angular"]["z"]),
            },
        }
        for key in ("obstacle_scan_status", "status"):
            if key in state:
                data[key] = state[key]
        message = (f"ROS 상태 수신 {age * 1000:.0f}ms 전: 위치 ({data['position']['x']:.2f}, "
                   f"{data['position']['y']:.2f})m, yaw {data['yaw']:.3f}rad, "
                   f"선속도 ({data['velocity']['linear']['x']:.2f}, {data['velocity']['linear']['y']:.2f})m/s, "
                   f"각속도 {data['velocity']['angular_z']:.3f}rad/s")
        if self.node:
            self.node.get_logger().info(message)
        return {"success": True, "message": message, "data": data}

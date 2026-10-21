"""Optional bridge between the Web Control server and the NOMI ROS graph."""

from __future__ import annotations

import threading
import json
from typing import Callable


class NomiBridge:
    """Publish NOMI commands and forward ROS responses to the asyncio server."""

    def __init__(
        self,
        on_response: Callable[[str], None] | None,
        on_model_status: Callable[[str], None],
        on_task_status: Callable[[dict], None] | None = None,
        on_connection_status: Callable[[bool, str | None], None] | None = None,
        on_navigation_request: Callable[[dict], None] | None = None,
        on_navigation_cancel: Callable[[str], None] | None = None,
    ):
        self._on_response = on_response
        self._on_model_status = on_model_status
        self._on_task_status = on_task_status or (lambda _payload: None)
        self._on_connection_status = on_connection_status or (lambda _connected, _error: None)
        self._on_navigation_request = on_navigation_request or (lambda _payload: None)
        self._on_navigation_cancel = on_navigation_cancel or (lambda _request_id: None)
        self._node = None
        self._thread: threading.Thread | None = None
        self._executor = None
        self._rclpy = None
        self._string_type = None
        self._owns_rclpy_context = False
        self.available = False
        self.agent_connected = False
        self.error: str | None = None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return self.available
        try:
            import rclpy
            from rclpy.node import Node
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from std_msgs.msg import String

            self._rclpy = rclpy
            self._string_type = String
            self._owns_rclpy_context = not rclpy.ok()
            if not rclpy.ok():
                rclpy.init(args=None)

            bridge = self

            class BridgeNode(Node):
                def __init__(self):
                    super().__init__("xlerobot_web_nomi_bridge")
                    self.command_pub = self.create_publisher(String, "/nomi/command", 10)
                    self.cancel_pub = self.create_publisher(String, "/nomi/cancel", 10)
                    self.model_pub = self.create_publisher(String, "/nomi/model_switch", 10)
                    self.navigation_result_pub = self.create_publisher(String, "/nomi/navigation_result", 10)
                    destinations_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                                  durability=DurabilityPolicy.TRANSIENT_LOCAL)
                    self.destinations_pub = self.create_publisher(
                        String, "/nomi/navigation_destinations", destinations_qos
                    )
                    if bridge._on_response is not None:
                        self.create_subscription(String, "/nomi/response", lambda msg: bridge._on_response(msg.data), 10)
                    self.create_subscription(String, "/nomi/model_status", lambda msg: bridge._on_model_status(msg.data), 10)
                    self.create_subscription(String, "/nomi/task_status", bridge._task_status_callback, 10)
                    self.create_subscription(String, "/nomi/navigation_request", bridge._navigation_request_callback, 10)
                    self.create_subscription(String, "/nomi/navigation_cancel", bridge._navigation_cancel_callback, 10)
                    self.create_timer(0.5, self._refresh_agent_status)

                def _refresh_agent_status(self):
                    connected = (
                        self.count_subscribers("/nomi/command") > 0
                        and self.count_subscribers("/nomi/model_switch") > 0
                        and self.count_subscribers("/nomi/navigation_result") > 0
                        and self.count_publishers("/nomi/task_status") > 0
                    )
                    if connected != bridge.agent_connected:
                        bridge.agent_connected = connected
                        bridge._on_connection_status(connected, None)

                def publish(self, topic: str, value: str):
                    msg = String()
                    msg.data = value
                    publishers = {
                        "command": self.command_pub,
                        "cancel": self.cancel_pub,
                        "model": self.model_pub,
                    }
                    publishers[topic].publish(msg)

            self._node = BridgeNode()
            self._executor = SingleThreadedExecutor()
            self._executor.add_node(self._node)
            self._thread = threading.Thread(target=self._executor.spin, name="nomi-ros-bridge", daemon=True)
            self._thread.start()
            self.available = True
            self.error = None
            self.agent_connected = False
        except Exception as exc:  # ROS 2 is optional for standalone Web Control.
            self.available = False
            self.error = str(exc)
            self.agent_connected = False
            self._on_connection_status(False, self.error)
        return self.available

    def _task_status_callback(self, message) -> None:
        try:
            payload = json.loads(message.data)
        except (TypeError, json.JSONDecodeError):
            return
        if isinstance(payload, dict):
            self._on_task_status(payload)

    def _navigation_request_callback(self, message) -> None:
        try:
            payload = json.loads(message.data)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        name = payload.get("name")
        request_id = payload.get("request_id")
        if (isinstance(name, str) and name.strip() and len(name.strip()) <= 120
                and isinstance(request_id, str) and request_id.strip() and len(request_id) <= 120):
            self._on_navigation_request({"name": name.strip(), "request_id": request_id.strip()})

    def _navigation_cancel_callback(self, message) -> None:
        try:
            payload = json.loads(message.data)
        except (TypeError, json.JSONDecodeError):
            return
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        if isinstance(request_id, str) and request_id.strip() and len(request_id) <= 120:
            self._on_navigation_cancel(request_id.strip())

    def publish_navigation_result(self, payload: dict) -> bool:
        if not self.available or not self.agent_connected or self._node is None:
            return False
        message = self._string_type()
        message.data = json.dumps(payload, ensure_ascii=False)
        self._node.navigation_result_pub.publish(message)
        return True

    def send_command(self, text: str, request_id: str, validate_only: bool = False) -> bool:
        if not self.available or not self.agent_connected or self._node is None:
            return False
        self._node.publish("command", json.dumps({
            "request_id": request_id, "text": text, "validate_only": bool(validate_only),
        }, ensure_ascii=False))
        return True

    def sync_destinations(self, destinations: list[dict]) -> bool:
        if not self.available or not self.agent_connected or self._node is None:
            return False
        message = self._string_type()
        message.data = json.dumps({"destinations": destinations}, ensure_ascii=False)
        self._node.destinations_pub.publish(message)
        return True

    def cancel_task(self, task_id: str) -> bool:
        if not self.available or not self.agent_connected or self._node is None:
            return False
        self._node.publish("cancel", json.dumps({"task_id": task_id}, ensure_ascii=False))
        return True

    def switch_model(self, profile: str) -> bool:
        if not self.available or not self.agent_connected or self._node is None:
            return False
        self._node.publish("model", profile)
        return True

    def stop(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(timeout_sec=1.0)
            self._executor = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._node is not None:
            self._node.destroy_node()
            self._node = None
        if self._owns_rclpy_context and self._rclpy is not None and self._rclpy.ok():
            self._rclpy.shutdown()
        self._owns_rclpy_context = False
        self.available = False
        self.agent_connected = False

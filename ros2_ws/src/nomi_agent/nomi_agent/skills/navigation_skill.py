import json
import threading
import time
import uuid

from geometry_msgs.msg import Twist
from std_msgs.msg import String


class NavigationSkill:
    """Dispatch short movement or await browser verified arrival for named places."""

    DIRECTIONS = {
        "앞으로": (0.25, 0.0, 0.0), "전진": (0.25, 0.0, 0.0), "forward": (0.25, 0.0, 0.0),
        "뒤로": (-0.25, 0.0, 0.0), "후진": (-0.25, 0.0, 0.0), "backward": (-0.25, 0.0, 0.0),
        "왼쪽": (0.0, 0.2, 0.0), "left": (0.0, 0.2, 0.0),
        "오른쪽": (0.0, -0.2, 0.0), "right": (0.0, -0.2, 0.0),
        "왼쪽 회전": (0.0, 0.0, 0.35), "rotate_left": (0.0, 0.0, 0.35),
        "오른쪽 회전": (0.0, 0.0, -0.35), "rotate_right": (0.0, 0.0, -0.35),
    }
    ARRIVAL_TIMEOUT_S = 120.0

    def __init__(self, node=None):
        self.node = node
        self.publisher = node.create_publisher(Twist, "/nomi/xlerobot/base_cmd_vel", 10) if node else None
        self.destination_publisher = node.create_publisher(String, "/nomi/navigation_request", 10) if node else None
        self.cancel_publisher = node.create_publisher(String, "/nomi/navigation_cancel", 10) if node else None
        self.result_subscription = (
            node.create_subscription(String, "/nomi/navigation_result", self._navigation_result_callback, 10)
            if node else None
        )
        self._pending_lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._active_request_id: str | None = None

    def _navigation_result_callback(self, message):
        try:
            result = json.loads(message.data)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(result, dict):
            return
        request_id = result.get("request_id")
        if not isinstance(request_id, str):
            return
        with self._pending_lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return
            pending["result"] = result
            pending["event"].set()

    def _cancel_request(self, request_id: str):
        if self.cancel_publisher is None:
            return
        message = String()
        message.data = json.dumps({"request_id": request_id}, ensure_ascii=False)
        self.cancel_publisher.publish(message)

    def navigate_to(self, location: str | None = None) -> dict:
        normalized = (location or "").strip().lower()
        command = self.DIRECTIONS.get(normalized)
        if command is None:
            destination = (location or "").strip()
            if not destination or self.destination_publisher is None:
                return {"success": False, "message": "저장 목적지 주행 요청을 웹 내비게이션에 전달할 수 없습니다. 웹 브리지 연결을 확인해 주세요."}
            request_id = str(uuid.uuid4())
            pending = {"event": threading.Event(), "result": None}
            with self._pending_lock:
                self._pending[request_id] = pending
                self._active_request_id = request_id
            message = String()
            message.data = json.dumps({"name": destination, "request_id": request_id}, ensure_ascii=False)
            self.destination_publisher.publish(message)
            if not pending["event"].wait(self.ARRIVAL_TIMEOUT_S):
                self._cancel_request(request_id)
                with self._pending_lock:
                    self._pending.pop(request_id, None)
                    if self._active_request_id == request_id:
                        self._active_request_id = None
                return {
                    "success": False,
                    "message": f"'{destination}' 도착 확인 시간이 초과되어 완료로 처리하지 않았습니다.",
                    "data": {"destination": destination, "request_dispatched": True, "completion_verified": False, "error_code": "arrival_timeout"},
                }
            with self._pending_lock:
                result = pending["result"] or {}
                self._pending.pop(request_id, None)
                if self._active_request_id == request_id:
                    self._active_request_id = None
            verified = (
                result.get("status") == "SUCCEEDED"
                and result.get("completion_verified") is True
                and isinstance(result.get("distance_m"), (int, float))
                and 0 <= result["distance_m"] <= 0.3
                and isinstance(result.get("position"), dict)
            )
            if verified:
                return {
                    "success": True,
                    "message": result.get("message") or f"'{destination}' 목적지 도착을 확인했습니다.",
                    "data": {
                        "destination": destination,
                        "request_dispatched": True,
                        "completion_verified": True,
                        "position": result["position"],
                        "distance_m": result["distance_m"],
                    },
                }
            return {
                "success": False,
                "message": result.get("message") or f"'{destination}' 주행이 완료되지 않았습니다.",
                "data": {
                    "destination": destination,
                    "request_dispatched": True,
                    "completion_verified": False,
                    "navigation_status": result.get("status", "UNKNOWN"),
                    "error_code": "navigation_not_arrived",
                },
            }
        if self.publisher is None:
            return {"success": False, "message": "MuJoCo 방향 이동 연결이 없습니다."}

        msg = Twist()
        msg.linear.x, msg.linear.y, msg.angular.z = command
        self.publisher.publish(msg)
        time.sleep(0.8)
        self.publisher.publish(Twist())
        message = f"'{location}' 방향으로 짧게 이동했습니다."
        if self.node:
            self.node.get_logger().info(message)
        return {"success": True, "message": message, "data": {"direction": location, "duration_s": 0.8}}

    def stop(self) -> bool:
        """Request a stop and cancel the currently awaited web navigation."""
        stopped = False
        if self.publisher is not None:
            self.publisher.publish(Twist())
            stopped = True
        with self._pending_lock:
            request_id = self._active_request_id
        if request_id:
            self._cancel_request(request_id)
            stopped = True
        return stopped

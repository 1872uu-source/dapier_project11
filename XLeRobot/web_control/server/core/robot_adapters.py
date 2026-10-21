"""Robot adapter contracts for NOMI integration preparation.

This module is deliberately not wired into the live control server yet. The
DAPier adapter is a fail-closed placeholder and performs no HTTP or ROS calls.
"""

from __future__ import annotations

from typing import Any, Protocol


def _result(success: bool, message: str, **data: Any) -> dict[str, Any]:
    return {"success": success, "message": message, "data": data}


class RobotAdapter(Protocol):
    """Common asynchronous contract for robot backends."""

    name: str

    async def get_state(self) -> dict[str, Any]: ...
    async def drive(self, *, direction: str, speed: float = 0.0,
                    linear_x: float = 0.0, linear_y: float = 0.0,
                    angular: float = 0.0) -> dict[str, Any]: ...
    async def navigate_to(self, location: str) -> dict[str, Any]: ...
    async def cancel_navigation(self) -> dict[str, Any]: ...
    async def stop(self) -> dict[str, Any]: ...
    async def pick_object(self, object_name: str) -> dict[str, Any]: ...
    async def place_object(self, location: str) -> dict[str, Any]: ...


class MujocoAdapter:
    """Thin wrapper over the existing ZeroMQ RemoteCore contract.

    Named navigation remains owned by the existing NOMI ROS bridge and browser
    path follower; unsupported manipulation is reported instead of simulated.
    """

    name = "mujoco"

    def __init__(self, remote_core):
        if remote_core is None or getattr(getattr(remote_core, "config", None), "robot_type", None) != "mujoco":
            raise ValueError("MujocoAdapter requires a RemoteCore configured for robot_type=mujoco")
        self.remote_core = remote_core

    async def get_state(self) -> dict[str, Any]:
        state = await self.remote_core.get_state()
        return _result(True, "MuJoCo 상태를 받았습니다.", source="mujoco", state=state)

    async def drive(self, *, direction: str, speed: float = 0.0,
                    linear_x: float = 0.0, linear_y: float = 0.0,
                    angular: float = 0.0) -> dict[str, Any]:
        result = await self.remote_core.move(direction, speed, angular, linear_x, linear_y)
        success = result.get("status") == "success"
        return _result(success, result.get("message", "MuJoCo 명령 전달 결과"),
                       source="mujoco", command_dispatched=success,
                       completion_verified=False, robot_result=result)

    async def stop(self) -> dict[str, Any]:
        result = await self.remote_core.stop()
        success = result.get("status") == "success"
        return _result(success, result.get("message", "MuJoCo 정지 요청 결과"),
                       source="mujoco", command_dispatched=success,
                       completion_verified=False, robot_result=result)

    async def navigate_to(self, location: str) -> dict[str, Any]:
        return _result(False, "목적지 내비게이션은 NOMI ROS 브리지 경로에서만 지원됩니다.",
                       error_code="NOT_IMPLEMENTED", source="mujoco_adapter", location=location)

    async def cancel_navigation(self) -> dict[str, Any]:
        return _result(False, "내비게이션 취소는 NOMI ROS 브리지에서 처리해야 합니다.",
                       error_code="NOT_IMPLEMENTED", source="mujoco_adapter")

    async def pick_object(self, object_name: str) -> dict[str, Any]:
        return _result(False, "MuJoCo 물체 인식·집기 기능은 연결되지 않았습니다.",
                       error_code="NOT_IMPLEMENTED", source="mujoco_adapter", object_name=object_name)

    async def place_object(self, location: str) -> dict[str, Any]:
        return _result(False, "MuJoCo 물체 놓기 기능은 연결되지 않았습니다.",
                       error_code="NOT_IMPLEMENTED", source="mujoco_adapter", location=location)


class DapierAdapter:
    """Fail-closed DAPier contract placeholder.

    These paths are documented from dapier_project's map_web API and are
    descriptive only. No request is sent and no robot command can be issued.
    """

    name = "dapier"
    enabled = False
    API_CONTRACT = {
        "state": "GET /api/state",
        "saved_locations": "GET /api/labels",
        "navigate": "POST /api/nav/goto",
        "cancel_navigation": "POST /api/nav/cancel",
        "stop": "POST /api/drive/stop",
        "camera": "GET /stream/rgb.mjpg",
        "arm_state": "GET /get_state",
        "pick": "GET /pick?x=&y=",
        "place": "GET /place?x=&y=",
    }

    def __init__(self, *, enabled: bool = False, base_url: str | None = None):
        # Even an enabled flag cannot activate hardware in this preparation build.
        self.enabled = False
        self.base_url = base_url

    def _disabled(self, action: str) -> dict[str, Any]:
        return _result(False, f"DAPier {action}은 통합 전이라 비활성화되어 있습니다.",
                       error_code="NOT_IMPLEMENTED", source="dapier_mock",
                       command_dispatched=False, completion_verified=False)

    async def get_state(self) -> dict[str, Any]:
        return self._disabled("상태 조회")

    async def drive(self, *, direction: str, speed: float = 0.0,
                    linear_x: float = 0.0, linear_y: float = 0.0,
                    angular: float = 0.0) -> dict[str, Any]:
        return self._disabled("이동")

    async def navigate_to(self, location: str) -> dict[str, Any]:
        return self._disabled("목적지 이동")

    async def cancel_navigation(self) -> dict[str, Any]:
        return self._disabled("내비게이션 취소")

    async def stop(self) -> dict[str, Any]:
        return self._disabled("정지")

    async def pick_object(self, object_name: str) -> dict[str, Any]:
        return self._disabled("물체 집기")

    async def place_object(self, location: str) -> dict[str, Any]:
        return self._disabled("물체 놓기")


class MockRobotAdapter:
    """In-memory adapter for tests; contains no ROS, socket, or HTTP client."""

    name = "mock"

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def _record(self, action: str, **data: Any) -> dict[str, Any]:
        self.calls.append({"action": action, **data})
        return _result(True, f"MockRobot {action} 완료", source="mock",
                       completion_verified=True, **data)

    async def get_state(self) -> dict[str, Any]:
        return self._record("get_state", state={"connection": "mock", "position": None})

    async def drive(self, *, direction: str, speed: float = 0.0,
                    linear_x: float = 0.0, linear_y: float = 0.0,
                    angular: float = 0.0) -> dict[str, Any]:
        return self._record("drive", direction=direction, speed=speed,
                            linear_x=linear_x, linear_y=linear_y, angular=angular)

    async def navigate_to(self, location: str) -> dict[str, Any]:
        return self._record("navigate_to", location=location)

    async def cancel_navigation(self) -> dict[str, Any]:
        return self._record("cancel_navigation")

    async def stop(self) -> dict[str, Any]:
        return self._record("stop")

    async def pick_object(self, object_name: str) -> dict[str, Any]:
        return self._record("pick_object", object_name=object_name)

    async def place_object(self, location: str) -> dict[str, Any]:
        return self._record("place_object", location=location)


def create_adapter(name: str, *, remote_core=None) -> RobotAdapter:
    """Explicit adapter factory; no implicit DAPier or mock activation."""
    normalized = str(name).strip().lower()
    if normalized == "mujoco":
        return MujocoAdapter(remote_core)
    if normalized == "dapier":
        return DapierAdapter()
    if normalized == "mock":
        return MockRobotAdapter()
    raise ValueError(f"지원하지 않는 로봇 어댑터: {name}")

import json

from std_msgs.msg import String


class ManipulationSkill:
    def __init__(self, node=None):
        self.node = node
        self.publisher = node.create_publisher(String, "/nomi/xlerobot/gripper_command", 10) if node else None

    def _set_gripper(self, angle: float, action: str, description: str) -> dict:
        if self.publisher is None:
            return {"success": False, "message": "MuJoCo 그리퍼 연결이 없습니다."}
        message = String()
        message.data = json.dumps({"arm": "left", "angle": angle})
        self.publisher.publish(message)
        return {"success": True, "message": description, "data": {"action": action, "arm": "left", "target_angle": angle}}

    def open_gripper(self) -> dict:
        return self._set_gripper(0.7, "open_gripper", "왼쪽 그리퍼 열기 명령을 보냈습니다.")

    def close_gripper(self) -> dict:
        return self._set_gripper(-0.7, "close_gripper", "왼쪽 그리퍼 닫기 명령을 보냈습니다.")

    def pick_object(self, object_name: str | None = None) -> dict:
        return {"success": False, "message": "물체 인식과 접근 경로가 연결되지 않아 집기 작업은 아직 지원하지 않습니다."}

    def place_object(self, location: str | None = None) -> dict:
        return {"success": False, "message": "물체 인식과 접근 경로가 연결되지 않아 놓기 작업은 아직 지원하지 않습니다."}

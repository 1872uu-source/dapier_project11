from .result import SkillResult


class TaskManager:
    """
    Qwen Router가 분류한 명령을 실제 ToolRegistry로 전달한다.

    현재 단계에서는 Hermes Worker 연결 전이므로
    모든 등록된 Skill을 직접 실행할 수 있도록 한다.
    """

    SIMPLE_INTENTS = {
        "get_weather",
        "get_user_location",
        "open_gripper",
        "close_gripper",
        "get_robot_state",
    }

    COMPLEX_INTENTS = {
        "navigate_to",
        "pick_object",
        "place_object",
    }

    def __init__(self, tool_registry):
        self.tool_registry = tool_registry

    def is_simple_intent(self, intent: str) -> bool:
        return intent in self.SIMPLE_INTENTS

    def is_complex_intent(self, intent: str) -> bool:
        return intent in self.COMPLEX_INTENTS

    def process(self, route_result: dict) -> SkillResult:
        """
        Qwen Router 결과를 분석하고 ToolRegistry를 실행한다.
        """

        route = route_result.get("route", "")
        intent = route_result.get("intent", "")
        arguments = route_result.get("arguments", {}) or {}
        reply = route_result.get("reply", "")

        # ========================================================
        # CHAT
        # ========================================================

        if route == "CHAT":
            if reply:
                return SkillResult.ok(reply)

            return SkillResult.ok(
                "안녕하세요. 무엇을 도와드릴까요?"
            )

        # ========================================================
        # Intent 없음
        # ========================================================

        if not intent:
            return SkillResult.fail(
                "실행할 작업을 찾지 못했습니다.",
                {
                    "route_result": route_result,
                },
            )

        # ========================================================
        # 등록된 Tool인지 확인
        # ========================================================

        tool_names = self.tool_registry.get_tool_names()

        if intent not in tool_names:
            return SkillResult.fail(
                f"등록되지 않은 도구입니다: {intent}",
                {
                    "intent": intent,
                    "available_tools": tool_names,
                },
            )

        # ========================================================
        # Tool 실행
        # ========================================================

        return self.tool_registry.execute(
            intent,
            arguments,
        )

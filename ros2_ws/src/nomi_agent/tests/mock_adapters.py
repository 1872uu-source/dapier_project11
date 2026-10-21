"""Deterministic LLM and robot adapters for hardware-free NOMI tests."""

from __future__ import annotations

from nomi_agent.core.result import SkillResult


class MockLLM:
    """Routes exact fixture utterances and executes only planned registry tools."""

    profile = "mock"

    def __init__(self, routes):
        self.routes = routes
        self.inputs = []
        self.tool_calls = []
        self.history = []

    def route_command(self, text):
        self.inputs.append(text)
        route = self.routes.get(text)
        if isinstance(route, BaseException):
            raise route
        return route

    def run_worker_with_tools(self, *, initial_actions, tool_executor, **_kwargs):
        for action in initial_actions:
            result = tool_executor(action["intent"], action["arguments"])
            self.tool_calls.append({"tool": action["intent"], "arguments": action["arguments"]})
            if not result.success:
                break
        return "모의 실행 결과를 받았습니다."

    def add_assistant_message(self, text):
        self.history.append(text)


class MockNavigation:
    def __init__(self, *, result=None, started=None, release=None):
        self.result = result or {"success": True, "message": "모의 이동 완료", "data": {"completion_verified": True}}
        self.started = started
        self.release = release
        self.calls = []
        self.stops = 0

    def navigate_to(self, location=None):
        self.calls.append(location)
        if self.started:
            self.started.set()
        if self.release:
            self.release.wait(3)
        return self.result

    def stop(self):
        self.stops += 1
        return True


class MockManipulation:
    def __init__(self):
        self.calls = []

    def open_gripper(self):
        self.calls.append("open")
        return {"success": True, "message": "모의 그리퍼 열기 완료", "data": {"completion_verified": True}}

    def close_gripper(self):
        self.calls.append("close")
        return {"success": True, "message": "모의 그리퍼 닫기 완료", "data": {"completion_verified": True}}

    def pick_object(self, object_name=None):
        self.calls.append(("pick", object_name))
        return {"success": True, "message": "모의 집기 완료", "data": {"completion_verified": True}}

    def place_object(self, location=None):
        self.calls.append(("place", location))
        return {"success": True, "message": "모의 놓기 완료", "data": {"completion_verified": True}}


class MockState:
    def __init__(self):
        self.calls = 0

    def get_robot_state(self):
        self.calls += 1
        return SkillResult.ok("모의 상태", {"source": "test", "battery": 100})


class MockLocation:
    def __init__(self):
        self.calls = 0

    def get_user_location(self):
        self.calls += 1
        return {"success": True, "message": "모의 위치", "data": {"city": "서울", "source": "test"}}


class MockWeather:
    def __init__(self, *, result=None, started=None, release=None):
        self.result = result or {"success": True, "message": "모의 날씨", "data": {"source": "test"}}
        self.started = started
        self.release = release
        self.calls = []

    def get_weather(self, city="서울"):
        self.calls.append(city)
        if self.started:
            self.started.set()
        if self.release:
            self.release.wait(3)
        result = dict(self.result)
        if result.get("success"):
            result["data"] = {**result.get("data", {}), "city": city}
        return result


def mock_skills(*, navigation=None, manipulation=None, state=None, location=None, weather=None):
    return {
        "navigation": navigation or MockNavigation(),
        "manipulation": manipulation or MockManipulation(),
        "state": state or MockState(),
        "location": location or MockLocation(),
        "weather": weather or MockWeather(),
    }


class MockRobot:
    """Aggregate robot adapter whose skill objects match the production APIs."""

    def __init__(self, **skills):
        self.skills = mock_skills(**skills)

    def as_registry_skills(self):
        return self.skills

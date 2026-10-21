"""End-to-end Harness tests using only deterministic MockLLM/MockRobot adapters."""

import threading
import time
import unittest
from dataclasses import replace

from nomi_agent.core.execution_harness import ExecutionHarness, TaskStatus
from nomi_agent.tool_registry import ToolRegistry
from tests.mock_adapters import MockLLM, MockNavigation, MockRobot, MockWeather, mock_skills


AUDIT_EVENTS = []


class NaturalLanguageHarnessIntegrationTests(unittest.TestCase):
    def wait_terminal(self, harness, task_id, timeout=2):
        deadline = time.monotonic() + timeout
        terminal = {s.value for s in (TaskStatus.NEEDS_CLARIFICATION, TaskStatus.VALIDATED, TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED)}
        while time.monotonic() < deadline:
            task = harness.get_task(task_id)
            if task and task["status"] in terminal:
                return task
            time.sleep(0.005)
        self.fail(f"Harness 작업이 종료되지 않았습니다: {harness.get_task(task_id)}")

    def build(self, text, route, skills=None):
        llm = MockLLM({text: route})
        robot = MockRobot(**(skills or {}))
        registry = ToolRegistry(skills=skills if skills is not None else robot.as_registry_skills())
        registry.update_destinations([{"name": "집", "aliases": ["home"], "x": 0.0, "y": 0.0}])
        harness = ExecutionHarness(llm, registry, lambda _text: None, audit_callback=AUDIT_EVENTS.append)
        return harness, llm, registry

    def run_task(self, text, route, skills=None):
        harness, llm, registry = self.build(text, route, skills)
        status, task_id = harness.submit(text)
        self.assertEqual(status, "started")
        return self.wait_terminal(harness, task_id), llm, registry

    def test_natural_language_selects_and_executes_the_expected_tool(self):
        text = "서울 날씨 알려줘"
        result, llm, registry = self.run_task(text, {"route": "TASK", "actions": [
            {"intent": "get_weather", "arguments": {"city": "서울"}},
        ]})
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(llm.inputs, [text])
        self.assertEqual([call["tool"] for call in llm.tool_calls], ["get_weather"])
        self.assertEqual(registry.skills["weather"].calls, ["서울"])
        relevant = [event for event in AUDIT_EVENTS if event.get("input") == text]
        event_names = {event.get("event") for event in relevant}
        self.assertTrue({"task_submitted", "route_selected", "plan_validation", "tool_validation", "tool_started", "tool_finished"} <= event_names)
        finished = next(event for event in relevant if event.get("event") == "tool_finished")
        self.assertEqual(finished["arguments"], {"city": "서울"})
        self.assertIn("duration_seconds", finished)

    def test_home_navigation_is_corrected_from_user_location_tool_to_registry_navigation(self):
        skills = mock_skills()
        result, llm, _registry = self.run_task("집으로 가자", {"route": "TASK", "actions": [
            {"intent": "get_user_location", "arguments": {}},
        ]}, skills)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual([call["tool"] for call in llm.tool_calls], ["navigate_to"])
        self.assertEqual(llm.tool_calls[0]["arguments"], {"location": "집"})
        self.assertEqual(skills["navigation"].calls, ["집"])
        self.assertEqual(skills["location"].calls, 0)

    def test_home_navigation_without_a_tool_call_is_not_reported_as_chat_success(self):
        result, llm, registry = self.run_task("집으로 가자", {"route": "CHAT", "actions": [], "reply": "사용자의 위치는 서울입니다."})
        self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
        self.assertEqual(registry.skills["navigation"].calls, [])
        self.assertEqual(registry.skills["location"].calls, 0)
        self.assertEqual(llm.tool_calls, [])

    def test_ambiguous_destination_requests_clarification_without_tool_execution(self):
        skills = mock_skills()
        result, llm, _ = self.run_task("그쪽으로 가", {"route": "TASK", "actions": [
            {"intent": "navigate_to", "arguments": {"location": "그쪽"}},
        ]}, skills)
        self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
        self.assertEqual(llm.tool_calls, [])
        self.assertEqual(skills["navigation"].calls, [])

    def test_invalid_argument_and_unregistered_tool_are_blocked(self):
        cases = [
            ("날씨", {"route": "TASK", "actions": [{"intent": "get_weather", "arguments": {"city": 7}}]}),
            ("작업", {"route": "TASK", "actions": [{"intent": "shell_exec", "arguments": {"cmd": "move"}}]}),
        ]
        for text, route in cases:
            with self.subTest(text=text):
                skills = mock_skills()
                result, llm, _ = self.run_task(text, route, skills)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(llm.tool_calls, [])
                self.assertEqual(skills["navigation"].calls, [])
                self.assertEqual(skills["weather"].calls, [])

    def test_failure_prevents_dependent_follow_up_step(self):
        text = "서울 날씨 확인 후 상태 확인"
        skills = mock_skills(weather=MockWeather(result={"success": False, "message": "모의 API 오류", "data": {"error_code": "mock_failure"}}))
        result, llm, registry = self.run_task(text, {"route": "TASK", "actions": [
            {"intent": "get_weather", "arguments": {"city": "서울"}},
            {"intent": "get_robot_state", "arguments": {}},
        ]}, skills)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual([c["tool"] for c in llm.tool_calls], ["get_weather"])
        self.assertEqual(registry.skills["state"].calls, 0)

    def test_successful_multi_step_plan_preserves_requested_order(self):
        text = "서울 날씨와 로봇 상태를 확인해줘"
        result, llm, _registry = self.run_task(text, {"route": "TASK", "actions": [
            {"intent": "get_weather", "arguments": {"city": "서울"}},
            {"intent": "get_robot_state", "arguments": {}},
        ]})
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual([call["tool"] for call in llm.tool_calls], ["get_weather", "get_robot_state"])
        self.assertEqual([step["index"] for step in result["steps"]], [1, 2])

    def test_tool_timeout_is_reported_and_logged(self):
        started, release = threading.Event(), threading.Event()
        weather = MockWeather(started=started, release=release)
        skills = mock_skills(weather=weather)
        text = "서울 날씨 알려줘"
        harness, _llm, registry = self.build(text, {"route": "TASK", "actions": [
            {"intent": "get_weather", "arguments": {"city": "서울"}},
        ]}, skills)
        registry._specs["get_weather"] = replace(registry._specs["get_weather"], timeout_seconds=0.05)
        _, task_id = harness.submit(text)
        self.assertTrue(started.wait(1))
        result = self.wait_terminal(harness, task_id)
        release.set()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["steps"][0]["error_code"], "timeout")

    def test_cancel_stops_active_sequence_and_calls_mock_emergency_stop(self):
        started, release = threading.Event(), threading.Event()
        navigation = MockNavigation(started=started, release=release)
        skills = mock_skills(navigation=navigation)
        text = "앞으로 가"
        harness, _llm, _registry = self.build(text, {"route": "TASK", "actions": [
            {"intent": "navigate_to", "arguments": {"location": "forward"}},
        ]}, skills)
        _, task_id = harness.submit(text)
        self.assertTrue(started.wait(1))
        cancelled, cancelled_id = harness.cancel_active()
        release.set()
        self.assertTrue(cancelled)
        self.assertEqual(cancelled_id, task_id)
        self.assertEqual(self.wait_terminal(harness, task_id)["status"], "CANCELLED")
        self.assertEqual(navigation.stops, 1)


if __name__ == "__main__":
    unittest.main()

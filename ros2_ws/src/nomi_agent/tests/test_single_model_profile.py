import json
import threading
import time
import unittest
from unittest.mock import patch

from nomi_agent.core.execution_harness import ExecutionHarness, TaskStatus
from nomi_agent.core.result import SkillResult
from nomi_agent.llm_client import LLMClient
from nomi_agent.llm_provider import MODEL_PROFILES, NativeChatResponse, NativeToolCall
from nomi_agent.tool_registry import ToolRegistry
from tests.mock_adapters import MockRobot


def native_response(*calls, content=""):
    calls = [call if isinstance(call, NativeToolCall) else NativeToolCall(*call) for call in calls]
    return NativeChatResponse(
        content=content,
        tool_calls=calls,
        assistant_message={
            "role": "assistant",
            "content": content,
            "tool_calls": [{"function": {"name": call.name, "arguments": call.arguments}} for call in calls],
        },
    )


def tool_call(name, arguments, call_id="fixture-call"):
    return NativeToolCall(call_id=call_id, name=name, arguments=arguments)


class ScriptedSingleProvider:
    provider = "ollama"
    model = "qwen3.5:9b"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat_native(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if not self.responses:
            raise AssertionError("Unexpected additional model request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def single_client(responses):
    client = LLMClient.__new__(LLMClient)
    client.profile = "qwen35_single"
    client.is_single_model_profile = True
    client.single_model_provider = ScriptedSingleProvider(responses)
    client.last_model_call_count = 0
    client.conversation_history = []
    client.max_history = 12
    client.add_assistant_message = lambda _text: None
    return client


class FailingPick:
    def open_gripper(self):
        return SkillResult.ok("ok")

    def close_gripper(self):
        return SkillResult.ok("ok")

    def pick_object(self, object_name=None):
        return SkillResult.fail("모의 집기 실패", {"error_code": "pick_failed"})

    def place_object(self, location=None):
        raise AssertionError("Place must not be called after a failed pick")


class SingleModelHarnessTests(unittest.TestCase):
    def make_harness(self, llm, robot=None):
        registry = ToolRegistry(skills=(robot or MockRobot()).as_registry_skills())
        registry.update_destinations([{"name": "집", "aliases": ["home"], "x": 0.0, "y": 0.0}])
        responses = []
        harness = ExecutionHarness(llm, registry, responses.append)
        return harness, registry, responses

    def wait_task(self, harness, task_id):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            task = harness.get_task(task_id)
            if task["status"] in {status.value for status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.NEEDS_CLARIFICATION, TaskStatus.VALIDATED)}:
                return task
            time.sleep(0.01)
        self.fail("task did not finish")

    def test_profile_is_separate_and_qwen_hermes_is_preserved(self):
        self.assertEqual(MODEL_PROFILES["qwen_hermes"]["worker_model"], "hermes3:8b")
        self.assertEqual(MODEL_PROFILES["qwen35_single"]["router_model"], "qwen3.5:9b")
        self.assertEqual(MODEL_PROFILES["qwen35_single"]["router_model"], MODEL_PROFILES["qwen35_single"]["worker_model"])

    def test_single_profile_constructs_one_provider_instead_of_two_model_clients(self):
        from nomi_agent.llm_client import LLMClient
        client = LLMClient.__new__(LLMClient)
        config = dict(MODEL_PROFILES["qwen35_single"])
        with patch("nomi_agent.llm_client.LLMProvider") as provider_type:
            client._apply_config(config, "qwen35_single")
        self.assertEqual(provider_type.call_count, 1)
        self.assertIs(client.router_provider, client.worker_provider)
        self.assertIs(client.single_model_provider, client.router_provider)

    def test_single_model_environment_override_keeps_single_profile(self):
        with patch.dict("os.environ", {"NOMI_MODEL_PROFILE": "qwen35_single", "NOMI_SINGLE_MODEL": "qwen3.5:9b"}, clear=False):
            with patch("nomi_agent.llm_client.LLMProvider") as provider_type:
                client = LLMClient()
        self.assertEqual(client.profile, "qwen35_single")
        self.assertTrue(client.is_single_model_profile)
        self.assertEqual(provider_type.call_count, 1)

    def test_true_single_model_call_uses_registry_schemas_and_can_chain_tools(self):
        llm = single_client([
            native_response(tool_call("pick_object", {"object_name": "책"}, "pick-1"),
                            tool_call("place_object", {"location": "책상"}, "place-1")),
            native_response(content="책을 집어 책상에 놓았습니다."),
        ])
        harness, registry, _ = self.make_harness(llm)
        state, task_id = harness.submit("책을 집어서 책상에 놓아줘")
        self.assertEqual(state, "started")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.SUCCEEDED.value)
        self.assertEqual([step["tool"] for step in task["steps"]], ["pick_object", "place_object"])
        self.assertEqual(task["model_calls"], 2)
        self.assertEqual(set(llm.single_model_provider.calls[0]["tools"][i]["function"]["name"] for i in range(len(registry.get_tool_schemas()))), set(registry.get_tool_names()))
        next_messages = llm.single_model_provider.calls[1]["messages"]
        assistant = next(message for message in next_messages if message.get("role") == "assistant")
        tool_messages = [message for message in next_messages if message.get("role") == "tool"]
        self.assertEqual(len(assistant["tool_calls"]), 2)
        self.assertEqual([message["tool_name"] for message in tool_messages], ["pick_object", "place_object"])
        tool_payloads = [json.loads(message["content"]) for message in tool_messages]
        self.assertEqual([payload["tool_call_id"] for payload in tool_payloads], ["pick-1", "place-1"])

    def test_failed_pick_stops_place_even_when_both_calls_are_in_one_reply(self):
        llm = single_client([
            native_response(tool_call("pick_object", {"object_name": "책"}, "pick-fail"),
                            tool_call("place_object", {"location": "책상"}, "place-blocked")),
        ])
        robot = MockRobot(manipulation=FailingPick())
        harness, _, _ = self.make_harness(llm, robot)
        _, task_id = harness.submit("책을 집어서 책상에 놓아줘")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        self.assertEqual([step["tool"] for step in task["steps"]], ["pick_object"])

    def test_missing_required_argument_becomes_clarification_not_execution(self):
        llm = single_client([native_response(tool_call("pick_object", {}, "missing-object"))])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("그 물체를 집어줘")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.NEEDS_CLARIFICATION.value)
        self.assertEqual(registry.skills["manipulation"].calls, [])

    def test_place_without_named_or_confirmed_object_needs_clarification(self):
        llm = single_client([native_response(tool_call("place_object", {"location": "테이블"}, "place-only"))])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("테이블 위에 놓아 줘.")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.NEEDS_CLARIFICATION.value)
        self.assertEqual(registry.skills["manipulation"].calls, [])

    def test_ambiguous_object_and_destination_are_blocked_and_queried(self):
        llm = single_client([native_response(tool_call("place_object", {"location": "저기"}, "ambiguous-place"))])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("그거 저기에 놓아 줘.")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.NEEDS_CLARIFICATION.value)
        self.assertEqual(registry.skills["manipulation"].calls, [])

    def test_forward_motion_uses_registry_allowlist_before_mock_dispatch(self):
        llm = single_client([native_response(tool_call("navigate_to", {"location": "forward"}, "forward-1")),
                             native_response(content="앞으로 이동 요청을 처리했습니다.")])
        robot = MockRobot()
        harness, _, _ = self.make_harness(llm, robot)
        _, task_id = harness.submit("앞으로 이동해.")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.SUCCEEDED.value)
        self.assertEqual(robot.skills["navigation"].calls, ["forward"])

    def test_home_navigation_never_executes_user_location_tool(self):
        llm = single_client([
            native_response(tool_call("get_user_location", {}, "wrong-location-tool")),
            native_response(content="집으로 이동 요청을 전달했습니다."),
        ])
        robot = MockRobot()
        registry = ToolRegistry(skills=robot.as_registry_skills())
        registry.update_destinations([{"name": "집", "aliases": ["home"], "x": 0.0, "y": 0.0}])
        harness = ExecutionHarness(llm, registry, lambda _text: None)
        _, task_id = harness.submit("집으로 가자", request_id="single-home-routing")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], "SUCCEEDED")
        self.assertEqual([step["tool"] for step in task["steps"]], ["navigate_to"])
        self.assertEqual(task["steps"][0]["arguments"], {"location": "집"})
        self.assertEqual(robot.skills["navigation"].calls, ["집"])
        self.assertEqual(robot.skills["location"].calls, 0)

    def test_no_tool_call_cannot_complete_robot_motion_but_chat_can_succeed(self):
        llm = single_client([native_response(content="이동을 완료했습니다.")])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("앞으로 이동해.")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.NEEDS_CLARIFICATION.value)
        self.assertEqual(registry.skills["navigation"].calls, [])

        llm = single_client([native_response(content="안녕하세요!")])
        harness, _, _ = self.make_harness(llm)
        _, task_id = harness.submit("안녕하세요")
        self.assertEqual(self.wait_task(harness, task_id)["status"], TaskStatus.SUCCEEDED.value)

    def test_explicit_gripper_negation_is_a_normal_no_action_response(self):
        llm = single_client([native_response(tool_call("open_gripper", {}, "must-not-call"))])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("그리퍼를 열지 마.")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.SUCCEEDED.value)
        self.assertEqual(llm.single_model_provider.calls, [])
        self.assertEqual(registry.skills["manipulation"].calls, [])

    def test_http_500_after_pick_preserves_step_and_same_request_retry_deduplicates(self):
        llm = single_client([
            native_response(tool_call("pick_object", {"object_name": "분홍색 수건"}, "pick-before-500")),
            RuntimeError("Ollama HTTP 500 EOF"),
        ])
        robot = MockRobot()
        harness, _, _ = self.make_harness(llm, robot)
        state, task_id = harness.submit("분홍색 수건을 집어서 테이블 위에 놓아 줘.", request_id="retry-safe-500")
        task = self.wait_task(harness, task_id)
        self.assertEqual(state, "started")
        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        self.assertEqual([step["tool"] for step in task["steps"]], ["pick_object"])
        self.assertEqual(robot.skills["manipulation"].calls, [("pick", "분홍색 수건")])
        self.assertEqual(task["model_calls"], 2)
        self.assertEqual(task["error"]["code"], "llm_provider_error")
        self.assertEqual(harness.submit("분홍색 수건을 집어서 테이블 위에 놓아 줘.", request_id="retry-safe-500")[0], "duplicate")
        self.assertEqual(robot.skills["manipulation"].calls, [("pick", "분홍색 수건")])

    def test_repeated_single_and_composite_mock_runs_are_stable(self):
        single_results = []
        for index in range(3):
            llm = single_client([native_response(tool_call("get_robot_state", {}, f"state-{index}")),
                                 native_response(content="상태 조회 완료")])
            harness, _, _ = self.make_harness(llm)
            _, task_id = harness.submit("현재 로봇 상태를 알려줘.")
            task = self.wait_task(harness, task_id)
            single_results.append((task["status"], tuple(step["tool"] for step in task["steps"])))
        composite_results = []
        for index in range(3):
            llm = single_client([native_response(
                tool_call("pick_object", {"object_name": "분홍색 수건"}, f"pick-{index}"),
                tool_call("place_object", {"location": "테이블"}, f"place-{index}")),
                native_response(content="순서대로 처리했습니다.")])
            harness, _, _ = self.make_harness(llm)
            _, task_id = harness.submit("분홍색 수건을 집어서 테이블 위에 놓아 줘.")
            task = self.wait_task(harness, task_id)
            composite_results.append((task["status"], tuple(step["tool"] for step in task["steps"])))
        self.assertEqual(len(set(single_results)), 1)
        self.assertEqual(len(set(composite_results)), 1)

    def test_repeated_model_tool_call_is_blocked_before_second_execution(self):
        llm = single_client([
            native_response(tool_call("get_robot_state", {}, "state-1")),
            native_response(tool_call("get_robot_state", {}, "state-2")),
        ])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("로봇 상태를 알려줘")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        self.assertEqual(len(task["steps"]), 1)
        self.assertEqual(registry.skills["state"].calls, 1)

    def test_mismatched_native_assistant_payload_stops_before_execution(self):
        malformed = NativeChatResponse(
            content="",
            tool_calls=[tool_call("get_robot_state", {}, "state-malformed")],
            assistant_message={"role": "assistant", "content": "", "tool_calls": []},
        )
        llm = single_client([malformed])
        harness, registry, _ = self.make_harness(llm)
        _, task_id = harness.submit("로봇 상태를 알려줘")
        task = self.wait_task(harness, task_id)
        self.assertEqual(task["status"], TaskStatus.FAILED.value)
        self.assertEqual(registry.skills["state"].calls, 0)

    def test_cancel_before_request_and_model_timeout_are_counted_safely(self):
        llm = single_client(["should not be read"])
        cancel = threading.Event()
        cancel.set()
        response = llm.run_single_model_with_tools("상태", [], lambda *_args: self.fail("cancelled tool"), cancel_event=cancel)
        self.assertIn("취소", response)
        self.assertEqual(llm.single_model_provider.calls, [])

        class TimeoutProvider(ScriptedSingleProvider):
            def chat_native(self, *_args, **_kwargs):
                raise TimeoutError("mock timeout")

        llm = single_client([])
        llm.single_model_provider = TimeoutProvider([])
        with self.assertRaises(TimeoutError):
            llm.run_single_model_with_tools("상태", [], lambda *_args: None)
        self.assertEqual(llm.last_model_call_count, 1)

    def test_max_tool_call_limit_stops_within_one_model_reply(self):
        llm = single_client([
            native_response(tool_call("get_weather", {"city": "서울"}, "weather-1"),
                            tool_call("get_weather", {"city": "부산"}, "weather-2")),
        ])
        executed = []
        with self.assertRaisesRegex(RuntimeError, "최대 도구 호출 횟수"):
            llm.run_single_model_with_tools(
                "날씨", [], lambda name, args: executed.append((name, args)) or SkillResult.ok("mock"),
                max_tool_calls=1,
            )
        self.assertEqual(len(executed), 1)


if __name__ == "__main__":
    unittest.main()

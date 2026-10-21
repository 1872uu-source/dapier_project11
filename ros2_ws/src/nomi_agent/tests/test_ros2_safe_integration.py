"""Opt-in ROS graph integration tests; never start MuJoCo or emit motion commands.

Enable only after sourcing ROS and the built NOMI overlay:
  NOMI_ROS_TEST=1 NOMI_MODEL_PROFILE=qwen_hermes python -m unittest ...
The node's LLM and skills are replaced with deterministic mocks before commands
are published to /nomi/command.
"""

import os
import json
import time
import unittest
from threading import Event
from pathlib import Path

try:
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from std_msgs.msg import String
    from nomi_agent.agent_node import NomiAgentNode
except ImportError:  # Keep the ordinary mock suite runnable outside ROS shells.
    rclpy = None
    SingleThreadedExecutor = None
    String = None
    NomiAgentNode = None
from nomi_agent.core.execution_harness import ExecutionHarness, TaskStatus
from nomi_agent.tool_registry import ToolRegistry
from tests.mock_adapters import MockLLM, MockNavigation, MockRobot


ROS_TEST_ENABLED = os.getenv("NOMI_ROS_TEST") == "1" and rclpy is not None


@unittest.skipUnless(ROS_TEST_ENABLED, "requires sourced ROS 2 Jazzy, built overlay, and NOMI_ROS_TEST=1")
class SafeRosGraphIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_profile = os.environ.get("NOMI_MODEL_PROFILE")
        os.environ["NOMI_MODEL_PROFILE"] = "qwen_hermes"
        ros_log_dir = Path(os.environ.setdefault("ROS_LOG_DIR", "/tmp/nomi-ros-test-logs"))
        ros_log_dir.mkdir(parents=True, exist_ok=True)
        # Use a dedicated domain so the test node cannot discover a robot on the
        # normal workspace domain. Override only when an isolated domain is reserved.
        cls.test_domain = int(os.getenv("NOMI_ROS_TEST_DOMAIN_ID", "222"))
        rclpy.init(domain_id=cls.test_domain)
        cls.agent = NomiAgentNode()
        assert isinstance(cls.agent.harness, ExecutionHarness)
        assert cls.agent.harness.tool_registry is cls.agent.tool_registry
        assert cls.agent.harness.llm_client is cls.agent.llm_client

        cls.probe = rclpy.create_node("nomi_safe_ros_test_probe")
        cls.executor = SingleThreadedExecutor()
        cls.executor.add_node(cls.agent)
        cls.executor.add_node(cls.probe)
        cls.command_pub = cls.probe.create_publisher(String, "/nomi/command", 10)
        cls.cancel_pub = cls.probe.create_publisher(String, "/nomi/cancel", 10)
        cls.responses = []
        cls.statuses = []
        cls.response_sub = cls.probe.create_subscription(String, "/nomi/response", lambda msg: cls.responses.append(msg.data), 10)
        cls.status_sub = cls.probe.create_subscription(String, "/nomi/task_status", lambda msg: cls.statuses.append(msg.data), 10)

    @classmethod
    def tearDownClass(cls):
        if not ROS_TEST_ENABLED:
            return
        if getattr(cls, "release_tool", None):
            cls.release_tool.set()
        cls.executor.remove_node(cls.agent)
        cls.executor.remove_node(cls.probe)
        cls.executor.shutdown()
        cls.agent.destroy_node()
        cls.probe.destroy_node()
        rclpy.shutdown()
        if cls.previous_profile is None:
            os.environ.pop("NOMI_MODEL_PROFILE", None)
        else:
            os.environ["NOMI_MODEL_PROFILE"] = cls.previous_profile

    def setUp(self):
        self.release_tool = None
        self.responses.clear()
        self.statuses.clear()
        self.audit = []
        self.release_tool = None
        self.started_tool = None
        self.routes = {}
        self.robot = MockRobot()
        self._install_mocks()

    def tearDown(self):
        if self.release_tool:
            self.release_tool.set()

    def _install_mocks(self, navigation=None):
        self.llm = MockLLM(self.routes)
        self.robot = MockRobot(**({"navigation": navigation} if navigation else {}))
        self.registry = ToolRegistry(skills=self.robot.as_registry_skills())
        self.agent.llm_client = self.llm
        self.agent.tool_registry = self.registry
        self.agent.harness = ExecutionHarness(
            self.llm,
            self.registry,
            self.agent.publish_response,
            self.agent.publish_task_status,
            logger=self.agent.get_logger(),
            audit_callback=self.audit.append,
        )

    def _spin_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.02)
            if predicate():
                return True
        return False

    def _publish_command(self, request_id, text):
        msg = String()
        msg.data = json.dumps({"request_id": request_id, "text": text}, ensure_ascii=False)
        self.command_pub.publish(msg)

    def _final_status(self, request_id):
        for raw in reversed(self.statuses):
            status = json.loads(raw)
            if status.get("task_id") == request_id and status.get("status") in {s.value for s in (
                TaskStatus.NEEDS_CLARIFICATION, TaskStatus.SUCCEEDED,
                TaskStatus.FAILED, TaskStatus.CANCELLED,
            )}:
                return status
        return None

    def _response_correlated(self, request_id):
        status = self._final_status(request_id)
        return bool(status and status.get("response_text") and status["response_text"] in self.responses)

    def test_topic_contract_and_request_id_response_status_correlation(self):
        topic_types = dict(self.agent.get_topic_names_and_types())
        names = set(topic_types)
        self.assertTrue({"/nomi/command", "/nomi/response", "/nomi/cancel", "/nomi/task_status"} <= names)
        for topic in ("/nomi/command", "/nomi/response", "/nomi/cancel", "/nomi/task_status"):
            self.assertEqual(topic_types[topic], ["std_msgs/msg/String"])
        text = "로봇 상태 확인해줘"
        self.routes[text] = {"route": "TASK", "actions": [{"intent": "get_robot_state", "arguments": {}}]}
        self._publish_command("ros-safe-state-1", text)
        self.assertTrue(self._spin_until(lambda: self._response_correlated("ros-safe-state-1")))
        final = self._final_status("ros-safe-state-1")
        self.assertEqual(final["status"], "SUCCEEDED")
        self.assertEqual(final["steps"][0]["tool"], "get_robot_state")
        self.assertIn("모의 실행 결과", final["response_text"])
        self.assertTrue(any(event.get("event") == "tool_finished" for event in self.audit))

    def test_unregistered_tool_is_rejected_over_command_topic(self):
        text = "시험 도구 실행"
        self.routes[text] = {"route": "TASK", "actions": [{"intent": "shell_exec", "arguments": {}}]}
        self._publish_command("ros-safe-invalid-1", text)
        self.assertTrue(self._spin_until(lambda: self._response_correlated("ros-safe-invalid-1")))
        final = self._final_status("ros-safe-invalid-1")
        self.assertEqual(final["status"], "FAILED")
        self.assertEqual(final["error"]["code"], "unknown_tool")
        self.assertIn("등록되지 않은 도구", final["response_text"])
        self.assertEqual(self.llm.tool_calls, [])

    def test_ambiguous_motion_is_blocked_without_navigation_dispatch(self):
        text = "그쪽으로 가"
        self.routes[text] = {"route": "TASK", "actions": [{"intent": "navigate_to", "arguments": {"location": "그쪽"}}]}
        self._publish_command("ros-safe-ambiguous-1", text)
        self.assertTrue(self._spin_until(lambda: self._response_correlated("ros-safe-ambiguous-1")))
        final = self._final_status("ros-safe-ambiguous-1")
        self.assertEqual(final["status"], "NEEDS_CLARIFICATION")
        self.assertIn("이동할 장소를 구체적으로", final["response_text"])
        self.assertEqual(self.robot.skills["navigation"].calls, [])

    def test_cancel_topic_cancels_active_mock_tool(self):
        self.started_tool, self.release_tool = Event(), Event()
        navigation = MockNavigation(started=self.started_tool, release=self.release_tool)
        self._install_mocks(navigation=navigation)
        text = "앞으로 가"
        self.routes[text] = {"route": "TASK", "actions": [{"intent": "navigate_to", "arguments": {"location": "forward"}}]}
        self._publish_command("ros-safe-cancel-1", text)
        self.assertTrue(self._spin_until(self.started_tool.is_set))
        cancel = String()
        cancel.data = "취소"
        self.cancel_pub.publish(cancel)
        self.assertTrue(self._spin_until(lambda:
            self._final_status("ros-safe-cancel-1") is not None
            and any("작업 중단을 요청" in response for response in self.responses)
        ))
        self.release_tool.set()
        self.assertEqual(self._final_status("ros-safe-cancel-1")["status"], "CANCELLED")
        self.assertEqual(navigation.stops, 1)

    def test_llm_timeout_and_provider_error_become_failed_task_statuses(self):
        for request_id, text, error, code in (
            ("ros-safe-timeout-1", "mock timeout", TimeoutError("mock router timeout"), "llm_timeout"),
            ("ros-safe-provider-1", "mock provider error", RuntimeError("mock provider failure"), "execution_error"),
        ):
            with self.subTest(request_id=request_id):
                self.routes[text] = error
                self._publish_command(request_id, text)
                self.assertTrue(self._spin_until(lambda: self._response_correlated(request_id)))
                final = self._final_status(request_id)
                self.assertEqual(final["status"], "FAILED")
                self.assertEqual(final["error"]["code"], code)
                self.assertIn(str(error), final["response_text"])


if __name__ == "__main__":
    unittest.main()

import unittest

from nomi_agent.core.execution_harness import (
    ExecutionHarness,
    TaskRecord,
)


class FakeSpec:
    def __init__(self, name):
        self.name = name


class FakeRegistry:
    def __init__(self):
        self.executed = []

    def validate_call(self, name, arguments):
        return FakeSpec(name), dict(arguments)

    def execute(self, name, arguments, **kwargs):
        self.executed.append((name, arguments))

        from nomi_agent.core.result import SkillResult
        return SkillResult.ok("Mock 실행 성공")


class WorkerSafetyTests(unittest.TestCase):

    def setUp(self):
        self.registry = FakeRegistry()

        self.harness = ExecutionHarness(
            llm_client=None,
            tool_registry=self.registry,
            publish_response=lambda text: None,
        )

    def make_record(self, text):
        return TaskRecord(
            task_id="test",
            request_key="test",
            user_text=text,
        )

    def test_worker_ambiguous_place_is_blocked(self):
        record = self.make_record("수건을 테이블 위에 놓아 줘")

        result = self.harness.execute_tool(
            record,
            "place_object",
            {"location": "저기"},
        )

        self.assertFalse(result.success)
        self.assertEqual(self.registry.executed, [])

    def test_worker_negated_gripper_is_blocked(self):
        record = self.make_record("그리퍼 열지 마")

        result = self.harness.execute_tool(
            record,
            "open_gripper",
            {},
        )

        self.assertFalse(result.success)
        self.assertEqual(self.registry.executed, [])

    def test_worker_valid_call_is_allowed(self):
        record = self.make_record("분홍색 수건을 집어 줘")

        result = self.harness.execute_tool(
            record,
            "pick_object",
            {"object_name": "분홍색 수건"},
        )

        self.assertTrue(result.success)
        self.assertEqual(len(self.registry.executed), 1)


if __name__ == "__main__":
    unittest.main()

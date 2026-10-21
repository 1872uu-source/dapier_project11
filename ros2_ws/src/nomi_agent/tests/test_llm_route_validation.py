import unittest
from types import SimpleNamespace

from nomi_agent.llm_client import LLMClient
from nomi_agent.llm_provider import LLMProvider


class FakeRouterProvider:
    def __init__(self, content):
        self.content = content

    def chat(self, *_args, **_kwargs):
        return self.content


class FakeArkWorker:
    provider = "ark"

    def __init__(self):
        self.tools = None

    def chat(self, _messages, **kwargs):
        self.tools = kwargs.get("tools")
        return "작업 계획을 확인했습니다."


class LLMRouteValidationTests(unittest.TestCase):
    def client(self, content):
        client = LLMClient.__new__(LLMClient)
        client.max_history = 12
        client.conversation_history = []
        client.last_intent = ""
        client.last_arguments = {}
        client.router_provider = FakeRouterProvider(content)
        return client

    def test_malformed_json_is_invalid_not_chat(self):
        result = self.client("not json").route_command("go forward")
        self.assertEqual(result["route"], "INVALID")
        self.assertEqual(result["error"], "router_invalid_json")

    def test_unknown_tool_is_preserved_for_registry_to_reject(self):
        content = '{"route":"TASK","actions":[{"intent":"run_shell","arguments":{"command":"x"}}]}'
        result = self.client(content).route_command("run this")
        self.assertEqual(result["route"], "TASK")
        self.assertEqual(result["actions"][0]["intent"], "run_shell")

    def test_malformed_top_level_fields_are_invalid(self):
        cases = [
            '{"route":"TASK","arguments":[],"actions":[]}',
            '{"route":"TASK","actions":"navigate"}',
            '{"route":[],"actions":[]}',
        ]
        for content in cases:
            with self.subTest(content=content):
                self.assertEqual(self.client(content).route_command("x")["route"], "INVALID")

    def test_worker_uses_registry_schemas_passed_by_harness(self):
        client = LLMClient.__new__(LLMClient)
        client.conversation_history = [{"role": "user", "content": "상태 확인"}]
        client.worker_provider = FakeArkWorker()
        schema = [{"type": "function", "function": {"name": "only_registry_tool"}}]
        result = client.run_worker_with_tools(
            user_text="상태 확인",
            initial_intent="get_robot_state",
            initial_arguments={},
            tool_schemas=schema,
            tool_executor=lambda *_args: None,
            max_rounds=1,
        )
        self.assertEqual(result, "작업 계획을 확인했습니다.")
        self.assertIs(client.worker_provider.tools, schema)

    def test_malformed_provider_tool_arguments_cannot_become_empty_arguments(self):
        function = SimpleNamespace(name="get_robot_state", arguments="{")
        call = SimpleNamespace(function=function)
        message = SimpleNamespace(content=None, tool_calls=[call])
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])

        class Completions:
            def create(self, **_kwargs):
                return response

        provider = LLMProvider.__new__(LLMProvider)
        provider.provider = "ark"
        provider.model = "fake"
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        content = provider.chat([{"role": "user", "content": "상태 확인"}], tools=[])

        client = LLMClient.__new__(LLMClient)
        calls = client._extract_tool_calls(content)
        self.assertEqual(calls[0]["name"], "get_robot_state")
        self.assertEqual(calls[0]["arguments"], {"__invalid_json__": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)

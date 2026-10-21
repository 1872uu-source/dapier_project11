import json
import unittest
from types import SimpleNamespace

from nomi_agent.llm_provider import LLMProvider


class FakeOllama:
    def __init__(self, message):
        self.message = message
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=self.message)


_MISSING = object()


def native_call(name="pick_object", arguments=_MISSING, call_id=None):
    function = SimpleNamespace(name=name, arguments={} if arguments is _MISSING else arguments)
    call = SimpleNamespace(function=function)
    if call_id is not None:
        call.id = call_id
    return call


class NativeToolProtocolTests(unittest.TestCase):
    def provider(self, message):
        provider = LLMProvider.__new__(LLMProvider)
        provider.provider = "ollama"
        provider.model = "qwen3.5:9b"
        provider.client = FakeOllama(message)
        return provider

    def test_native_call_and_assistant_message_are_preserved_without_xml(self):
        provider = self.provider(SimpleNamespace(content="", thinking=None,
                                                 tool_calls=[native_call(arguments={"object_name": "컵"}, call_id="server-id-1")]))
        result = provider.chat_native(
            [{"role": "user", "content": "컵을 집어"}],
            [{"type": "function", "function": {"name": "pick_object"}}],
            call_id_prefix="task-1:round:1",
        )
        self.assertEqual(result.tool_calls[0].call_id, "server-id-1")
        self.assertEqual(result.tool_calls[0].name, "pick_object")
        self.assertEqual(result.tool_calls[0].arguments, {"object_name": "컵"})
        self.assertEqual(result.assistant_message["tool_calls"][0]["function"]["name"], "pick_object")
        self.assertNotIn("<tool_call>", result.content)
        self.assertEqual(provider.client.calls[0]["messages"][0]["role"], "user")
        from ollama._types import Message
        Message(**result.assistant_message)
        Message(role="tool", tool_name="pick_object", content='{"tool_call_id":"server-id-1"}')

    def test_id_fallback_and_bad_arguments_are_not_silently_coerced_to_empty(self):
        provider = self.provider(SimpleNamespace(content=None, thinking=None,
                                                 tool_calls=[native_call(arguments=None)]))
        result = provider.chat_native([], [], call_id_prefix="task-2:round:1")
        self.assertEqual(result.tool_calls[0].call_id, "task-2:round:1:call:1")
        self.assertEqual(result.tool_calls[0].arguments, {"__invalid_arguments__": True})

    def test_role_tool_messages_pass_through_using_ollama_supported_fields(self):
        provider = self.provider(SimpleNamespace(content="계속 진행할까요?", thinking=None, tool_calls=[]))
        tool_message = {"role": "tool", "tool_name": "pick_object", "content": json.dumps({"tool_call_id": "n-1"})}
        result = provider.chat_native([tool_message], [], call_id_prefix="task-3:round:2")
        self.assertEqual(provider.client.calls[0]["messages"][0], tool_message)
        self.assertEqual(result.content, "계속 진행할까요?")

    def test_legacy_chat_keeps_xml_adapter_for_existing_hermes_flow(self):
        provider = self.provider(SimpleNamespace(content="", tool_calls=[native_call(arguments={"object_name": "컵"})]))
        result = provider.chat([{"role": "user", "content": "컵을 집어"}])
        self.assertIn("<tool_call>", result)
        self.assertIn('"name": "pick_object"', result)


if __name__ == "__main__":
    unittest.main()

"""Opt-in router-only checks against the configured LLM provider.

Enable with NOMI_LIVE_LLM=1. These tests never instantiate the tool registry or
execute robot skills, so model routing accuracy remains separate from tool
execution accuracy.
"""

import os
import unittest

from nomi_agent.llm_client import LLMClient


@unittest.skipUnless(os.getenv("NOMI_LIVE_LLM") == "1", "set NOMI_LIVE_LLM=1 to call the configured model")
class LiveLLMRouteTests(unittest.TestCase):
    def test_fixed_korean_intents_are_routed_without_executing_tools(self):
        client = LLMClient(max_history=0)
        cases = (
            ("서울 날씨 알려줘", "get_weather"),
            ("부산 현재 기온 알려줘", "get_weather"),
            ("종로구 비 와?", "get_weather"),
            ("오늘 대전 날씨 어때", "get_weather"),
            ("지금 날씨 알려줘", "get_weather"),
            ("앞으로 가", "navigate_to"),
            ("앞으로 이동해", "navigate_to"),
            ("전진해", "navigate_to"),
            ("뒤로 가", "navigate_to"),
            ("오른쪽으로 움직여", "navigate_to"),
            ("로봇 상태 확인해줘", "get_robot_state"),
            ("로봇 괜찮아?", "get_robot_state"),
            ("현재 로봇 상태 알려줘", "get_robot_state"),
            ("그리퍼 열어", "open_gripper"),
            ("그리퍼 열어줘", "open_gripper"),
            ("그리퍼 닫아", "close_gripper"),
            ("그리퍼를 닫아줘", "close_gripper"),
            ("내 위치 알려줘", "get_user_location"),
            ("컵 집어", "pick_object"),
            ("책상에 컵 놓아", "place_object"),
        )
        correct = 0
        for prompt, expected_tool in cases:
            with self.subTest(prompt=prompt):
                client.clear_history()
                routed = client.route_command(prompt)
                self.assertEqual(routed.get("route"), "TASK")
                actions = routed.get("actions")
                self.assertTrue(actions, f"router returned no planned action: {routed}")
                self.assertEqual(actions[0].get("intent"), expected_tool)
                correct += 1
        self.assertEqual(correct / len(cases), 1.0)


if __name__ == "__main__":
    unittest.main()

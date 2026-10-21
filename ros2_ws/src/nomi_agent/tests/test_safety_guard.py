import unittest

from nomi_agent.safety_guard import validate_actions


class SafetyGuardTests(unittest.TestCase):
    def check(self, text, *actions):
        return validate_actions(text, list(actions))

    def test_valid_pick(self):
        ok, actions, message = self.check(
            "분홍색 수건을 집어 줘",
            {"intent": "pick_object", "arguments": {"object_name": "분홍색 수건"}},
        )
        self.assertTrue(ok, message)
        self.assertEqual(len(actions), 1)

    def test_valid_place(self):
        ok, _, message = self.check(
            "수건을 테이블 위에 놓아 줘",
            {"intent": "place_object", "arguments": {"location": "테이블 위"}},
        )
        self.assertTrue(ok, message)

    def test_ambiguous_object_blocked(self):
        ok, actions, _ = self.check(
            "그거 집어 줘",
            {"intent": "pick_object", "arguments": {"object_name": "그거"}},
        )
        self.assertFalse(ok)
        self.assertEqual(actions, [])

    def test_ambiguous_location_blocked(self):
        for location in ("저기", "there", "그쪽", ""):
            with self.subTest(location=location):
                ok, actions, _ = self.check(
                    "거기에 놓아 줘",
                    {"intent": "place_object", "arguments": {"location": location}},
                )
                self.assertFalse(ok)
                self.assertEqual(actions, [])

    def test_missing_field_blocked(self):
        ok, actions, _ = self.check(
            "수건을 집어 줘",
            {"intent": "pick_object", "arguments": {}},
        )
        self.assertFalse(ok)
        self.assertEqual(actions, [])

    def test_negated_open_blocked(self):
        for text in ("그리퍼 열지 마", "그리퍼를 열지 말고 상태만 확인해"):
            with self.subTest(text=text):
                ok, actions, _ = self.check(
                    text,
                    {"intent": "open_gripper", "arguments": {}},
                )
                self.assertFalse(ok)
                self.assertEqual(actions, [])

    def test_negated_close_blocked(self):
        ok, actions, _ = self.check(
            "그리퍼 닫으면 안 돼",
            {"intent": "close_gripper", "arguments": {}},
        )
        self.assertFalse(ok)
        self.assertEqual(actions, [])

    def test_composite_rejected_if_one_action_is_ambiguous(self):
        ok, actions, _ = self.check(
            "수건을 집어서 저기에 놓아 줘",
            {"intent": "pick_object", "arguments": {"object_name": "수건"}},
            {"intent": "place_object", "arguments": {"location": "저기"}},
        )
        self.assertFalse(ok)
        self.assertEqual(actions, [])

    def test_no_action_is_valid(self):
        ok, actions, message = validate_actions("안녕", [])
        self.assertTrue(ok, message)
        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

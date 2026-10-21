import unittest

from core.nomi_motion import parse_destination_command


class NomiDestinationParsingTests(unittest.TestCase):
    def test_home_phrases_resolve_to_home_navigation_not_user_location(self):
        for text in ("집으로 가자", "집에 가줘", "집으로 돌아가", "집으로 이동해"):
            with self.subTest(text=text):
                self.assertEqual(parse_destination_command(text), {"destination": "home", "name": "집"})

    def test_charging_place_and_custom_saved_name_are_preserved(self):
        self.assertEqual(parse_destination_command("충전소로 이동해"), {
            "destination": "charging_dock", "name": "충전 도크",
        })
        self.assertEqual(parse_destination_command("서재로 가줘"), {
            "destination": "saved", "name": "서재",
        })

    def test_indoor_table_and_charging_location_names_are_preserved(self):
        self.assertEqual(parse_destination_command("테이블 1로 이동해"), {
            "destination": "saved", "name": "테이블 1",
        })
        self.assertEqual(parse_destination_command("테이블 3으로 가줘"), {
            "destination": "saved", "name": "테이블 3",
        })
        self.assertEqual(parse_destination_command("충전 위치로 이동해"), {
            "destination": "saved", "name": "충전 위치",
        })

    def test_ambiguous_saved_destination_is_marked_for_ui_resolution(self):
        self.assertEqual(parse_destination_command("저장된 목적지로 가줘"), {
            "destination": "saved", "name": "저장된 목적지",
        })

    def test_location_question_is_not_a_navigation_request(self):
        self.assertIsNone(parse_destination_command("내 인터넷 위치가 어디야?"))
        self.assertIsNone(parse_destination_command("서울 날씨 알려줘"))


if __name__ == "__main__":
    unittest.main()

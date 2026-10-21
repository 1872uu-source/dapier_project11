"""Regression checks for screen-relative controls after robot turns."""

import math
import unittest

from drive_frame import (
    body_velocity_to_slide,
    map_to_slide,
    slide_delta_to_body,
    slide_to_map,
)


class DriveFrameRegressionTests(unittest.TestCase):
    def test_map_to_slide_is_minus_y_then_x_and_round_trips(self):
        self.assertEqual(map_to_slide(1.0, 0.0), (0.0, 1.0))
        self.assertEqual(map_to_slide(0.0, 1.0), (-1.0, 0.0))
        for map_delta in ((1.0, 0.0), (0.0, 1.0), (-2.0, 3.0)):
            self.assertEqual(slide_to_map(*map_to_slide(*map_delta)), map_delta)

    def test_body_forward_matches_map_heading_at_cardinal_yaws(self):
        cases = (
            (0.0, (0.0, 1.0)),
            (math.pi / 2, (-1.0, 0.0)),
            (math.pi, (0.0, -1.0)),
            (-math.pi / 2, (1.0, 0.0)),
        )
        for yaw, expected_world in cases:
            with self.subTest(yaw=yaw):
                actual_world = body_velocity_to_slide(1.0, 0.0, yaw)
                self.assertAlmostEqual(actual_world[0], expected_world[0], places=7)
                self.assertAlmostEqual(actual_world[1], expected_world[1], places=7)
                map_velocity = slide_to_map(*actual_world)
                self.assertAlmostEqual(map_velocity[0], math.cos(yaw), places=7)
                self.assertAlmostEqual(map_velocity[1], math.sin(yaw), places=7)

    def test_left_velocity_is_map_left_and_yaw_sign_is_consistent(self):
        for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 2):
            actual_world = body_velocity_to_slide(0.0, 1.0, yaw)
            map_x, map_y = slide_to_map(*actual_world)
            self.assertAlmostEqual(map_x, -math.sin(yaw), places=7)
            self.assertAlmostEqual(map_y, math.cos(yaw), places=7)

    def test_waypoint_projection_is_inverse_of_control_conversion(self):
        yaw = 1.17
        map_dx, map_dy = 2.3, -0.8
        world_delta = map_to_slide(map_dx, map_dy)
        forward, left = slide_delta_to_body(*world_delta, yaw)
        round_trip = slide_to_map(*body_velocity_to_slide(forward, left, yaw))
        self.assertAlmostEqual(round_trip[0], map_dx, places=7)
        self.assertAlmostEqual(round_trip[1], map_dy, places=7)


if __name__ == "__main__":
    unittest.main()

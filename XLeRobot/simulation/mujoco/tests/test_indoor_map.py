"""Regression checks for the indoor MuJoCo map and web-map frame alignment."""

from pathlib import Path
import math
import unittest

import mujoco

from obstacle_scan import scan_obstacles
from drive_frame import map_to_slide, slide_to_map


SCENE_PATH = Path(__file__).resolve().parents[1] / "scene.xml"
TABLES = {
    "table_1": (-2.45, 1.1, 0.7, 0.45),
    "table_2": (0.0, 3.0, 0.7, 0.45),
    "table_3": (2.45, 1.1, 0.7, 0.45),
}


class IndoorMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
        cls.data = mujoco.MjData(cls.model)
        mujoco.mj_forward(cls.model, cls.data)

    def test_room_walls_door_and_tables_are_present_and_collidable(self):
        for wall in (
            "room_wall_west", "room_wall_east", "room_wall_north",
            "room_wall_south_left", "room_wall_south_right",
        ):
            geom_id = self.model.geom(wall).id
            self.assertGreater(self.model.geom_contype[geom_id], 0)
            self.assertGreater(self.model.geom_conaffinity[geom_id], 0)
        for name in TABLES:
            geom_id = self.model.geom(name).id
            self.assertGreater(self.model.geom_contype[geom_id], 0)
            self.assertGreater(self.model.geom_conaffinity[geom_id], 0)

    def test_table_collision_centers_and_footprints_match_web_map_frame(self):
        for name, (map_x, map_y, half_width, half_height) in TABLES.items():
            geom_id = self.model.geom(name).id
            world_x, world_y, _ = self.model.geom_pos[geom_id]
            # Chassis map coordinates map to MuJoCo world (-map_y, map_x).
            self.assertAlmostEqual(float(world_x), -map_y, places=5)
            self.assertAlmostEqual(float(world_y), map_x, places=5)
            size_x, size_y, _ = self.model.geom_size[geom_id]
            self.assertAlmostEqual(float(size_x), half_height, places=5)
            self.assertAlmostEqual(float(size_y), half_width, places=5)

    def test_static_table_boxes_are_reported_by_the_range_scan(self):
        hits, status = scan_obstacles(self.model, self.data)
        self.assertGreater(status["hit_count"], 0)
        for map_x, map_y, half_width, half_height in TABLES.values():
            self.assertTrue(any(
                abs(hit["x"] - map_x) <= half_width + 0.1
                and abs(hit["y"] - map_y) <= half_height + 0.1
                for hit in hits
            ), f"no scan returns near table at ({map_x}, {map_y})")

    def test_model_actuator_names_and_base_wheel_transmissions_are_distinct(self):
        expected = [
            "slider_actuator_x", "slider_actuator_y", "hinge_actuator_z",
            "Rotation_R", "Pitch_R", "Elbow_R", "Wrist_Pitch_R", "Wrist_Roll_R", "Jaw_R",
            "Rotation_L", "Pitch_L", "Elbow_L", "Wrist_Pitch_L", "Wrist_Roll_L", "Jaw_L",
            "wheel1", "wheel2", "wheel3",
        ]
        names = [mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(self.model.nu)]
        self.assertEqual(names, expected)
        base_joint_ids = set(self.model.actuator_trnid[:3, 0].tolist())
        wheel_joint_ids = set(self.model.actuator_trnid[15:18, 0].tolist())
        self.assertEqual(len(base_joint_ids), 3)
        self.assertEqual(len(wheel_joint_ids), 3)
        self.assertTrue(base_joint_ids.isdisjoint(wheel_joint_ids))

    def test_loaded_chassis_heading_and_hinge_yaw_share_the_map_frame(self):
        chassis_id = self.model.body("chassis").id
        yaw_address = self.model.jnt_qposadr[self.model.joint("hinge_joint_z").id]
        for yaw in (0.0, 1.5707963267948966, 3.141592653589793, -1.5707963267948966):
            with self.subTest(yaw=yaw):
                data = mujoco.MjData(self.model)
                data.qpos[yaw_address] = yaw
                mujoco.mj_forward(self.model, data)
                world_heading = data.xmat[chassis_id].reshape(3, 3)[:, 0]
                map_heading = slide_to_map(float(world_heading[0]), float(world_heading[1]))
                self.assertAlmostEqual(map_heading[0], math.cos(yaw), places=7)
                self.assertAlmostEqual(map_heading[1], math.sin(yaw), places=7)

    def test_low_speed_map_axis_commands_move_the_loaded_model_in_that_map_direction(self):
        for map_velocity in ((0.08, 0.0), (0.0, 0.08)):
            with self.subTest(map_velocity=map_velocity):
                data = mujoco.MjData(self.model)
                mujoco.mj_forward(self.model, data)
                start_world = (
                    float(data.qpos[self.model.jnt_qposadr[self.model.joint("slide_joint_x").id]]),
                    float(data.qpos[self.model.jnt_qposadr[self.model.joint("slide_joint_y").id]]),
                )
                slide_x, slide_y = map_to_slide(*map_velocity)
                data.ctrl[self.model.actuator("slider_actuator_x").id] = slide_x
                data.ctrl[self.model.actuator("slider_actuator_y").id] = slide_y
                # Offline MjModel only: no viewer, ROS, ZMQ, or hardware connection.
                for _ in range(500):
                    mujoco.mj_step(self.model, data)
                end_world = (
                    float(data.qpos[self.model.jnt_qposadr[self.model.joint("slide_joint_x").id]]),
                    float(data.qpos[self.model.jnt_qposadr[self.model.joint("slide_joint_y").id]]),
                )
                actual_map_delta = slide_to_map(
                    end_world[0] - start_world[0],
                    end_world[1] - start_world[1],
                )
                map_speed = (map_velocity[0] ** 2 + map_velocity[1] ** 2) ** 0.5
                projected_progress = (actual_map_delta[0] * map_velocity[0] + actual_map_delta[1] * map_velocity[1]) / map_speed
                self.assertGreater(projected_progress, 0.02)
                cross_track = abs(actual_map_delta[0] * map_velocity[1] - actual_map_delta[1] * map_velocity[0])
                self.assertLess(cross_track, 0.002)


if __name__ == "__main__":
    unittest.main()

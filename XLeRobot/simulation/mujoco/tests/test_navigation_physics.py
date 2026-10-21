"""Offline MuJoCo checks for planner-frame drive direction and base actuation."""

import math
from pathlib import Path
import unittest

import mujoco
import numpy as np

from drive_frame import map_to_slide, slide_delta_to_body, slide_to_map

MODEL_PATH = Path(__file__).resolve().parents[1] / "scene.xml"
WHEEL_NAMES = ("wheel1", "wheel2", "wheel3")


class NavigationPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = mujoco.MjModel.from_xml_path(str(MODEL_PATH))

    def simulate_map_velocity(self, map_velocity, yaw, drive_wheels):
        model = self.model
        data = mujoco.MjData(model)
        yaw_address = model.jnt_qposadr[model.joint("hinge_joint_z").id]
        data.qpos[yaw_address] = yaw
        mujoco.mj_forward(model, data)
        x_address = model.jnt_qposadr[model.joint("slide_joint_x").id]
        y_address = model.jnt_qposadr[model.joint("slide_joint_y").id]
        initial = (float(data.qpos[x_address]), float(data.qpos[y_address]))
        slide_velocity = map_to_slide(*map_velocity)
        matrix = np.array([
            [0.0, 1.0, -0.1],
            [-math.sqrt(3) * 0.5, -0.5, -0.1],
            [math.sqrt(3) * 0.5, -0.5, -0.1],
        ])
        for _ in range(300):
            data.ctrl[model.actuator("slider_actuator_x").id] = slide_velocity[0]
            data.ctrl[model.actuator("slider_actuator_y").id] = slide_velocity[1]
            data.ctrl[model.actuator("hinge_actuator_z").id] = 0.0
            if drive_wheels:
                body_velocity = slide_delta_to_body(*slide_velocity, float(data.qpos[yaw_address]))
                wheel_commands = 20.0 * matrix @ np.array([*body_velocity, 0.0])
                for name, command in zip(WHEEL_NAMES, wheel_commands):
                    data.ctrl[model.actuator(name).id] = float(command)
            mujoco.mj_step(model, data)
        world_delta = (float(data.qpos[x_address]) - initial[0], float(data.qpos[y_address]) - initial[1])
        return slide_to_map(*world_delta)

    def test_map_cardinals_move_in_requested_direction_at_each_cardinal_yaw(self):
        axes = ((0.08, 0.0), (-0.08, 0.0), (0.0, 0.08), (0.0, -0.08))
        for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 2):
            for command in axes:
                with self.subTest(yaw=yaw, command=command):
                    delta = self.simulate_map_velocity(command, yaw, drive_wheels=True)
                    magnitude = math.hypot(*command)
                    progress = (delta[0] * command[0] + delta[1] * command[1]) / magnitude
                    cross_track = abs(delta[0] * command[1] - delta[1] * command[0])
                    self.assertGreater(progress, 0.01)
                    self.assertLess(cross_track, 0.004)

    def test_wheel_actuators_do_not_reverse_or_materially_change_slide_command(self):
        for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 2):
            for command in ((0.08, 0.0), (0.0, 0.08)):
                with self.subTest(yaw=yaw, command=command):
                    slider_only = self.simulate_map_velocity(command, yaw, drive_wheels=False)
                    host_combined = self.simulate_map_velocity(command, yaw, drive_wheels=True)
                    self.assertGreater(host_combined[0] * command[0] + host_combined[1] * command[1], 0)
                    self.assertLess(math.hypot(host_combined[0] - slider_only[0], host_combined[1] - slider_only[1]), 0.003)

    def test_positive_hinge_command_increases_map_yaw(self):
        model = self.model
        data = mujoco.MjData(model)
        yaw_address = model.jnt_qposadr[model.joint("hinge_joint_z").id]
        initial_yaw = float(data.qpos[yaw_address])
        data.ctrl[model.actuator("hinge_actuator_z").id] = 0.2
        for _ in range(300):
            mujoco.mj_step(model, data)
        self.assertGreater(float(data.qpos[yaw_address]) - initial_yaw, 0.05)


if __name__ == "__main__":
    unittest.main()

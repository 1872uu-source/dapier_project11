"""Closed-loop web planner/controller to MuJoCo Host physics regression.

Run after sourcing ROS 2 Jazzy and the xlerobot_mujoco venv. The Host object is
constructed without Node.__init__, so this test creates no ROS nodes, sockets,
viewer, backend, or hardware connection. It still calls the production
handle_move() and step() methods against the loaded MuJoCo scene.
"""

import json
import math
from pathlib import Path
import subprocess
import threading
import unittest

import mujoco
import numpy as np

import nomi_xlerobot_sim.mujoco_host as host_module
from nomi_xlerobot_sim.mujoco_host import XLeRobotMujocoHost


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CLIENT_ROOT = PROJECT_ROOT / "web_control" / "client"
SCENE_PATH = Path(__file__).resolve().parents[1] / "scene.xml"

NODE_BRIDGE = r"""
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const readline = require('node:readline');
const root = path.resolve('src/utils');
function loadTs(name, dependencies = {}) {
  const source = fs.readFileSync(path.join(root, `${name}.ts`), 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output)(
    (id) => dependencies[id] ?? (() => { throw new Error(`unexpected import ${id}`); })(),
    module,
    module.exports,
  );
  return module.exports;
}
const map = loadTs('indoorMap');
const planner = loadTs('pathPlanner', { './indoorMap': map });
const controller = loadTs('navigationController');
readline.createInterface({ input: process.stdin, crlfDelay: Infinity }).on('line', (line) => {
  try {
    const request = JSON.parse(line);
    const result = request.op === 'route'
      ? planner.findRoute(request.start, request.goal, [])
      : controller.computeWaypointCommand(
          request.pose, request.target, request.speed, request.turnDirection,
          request.actualYawRate,
        );
    console.log(JSON.stringify(result));
  } catch (error) {
    console.log(JSON.stringify({ error: String(error) }));
  }
});
"""


class SimClock:
    """Advance Host watchdog time by the simulated 10 Hz command cadence."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def time(self):
        return 1_000_000.0 + self.now


class ClosedLoopNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (CLIENT_ROOT / "node_modules" / "typescript").exists():
            raise unittest.SkipTest("Install web_control/client dependencies to run the TypeScript controller bridge")
        cls.bridge = subprocess.Popen(
            ["node", "-e", NODE_BRIDGE],
            cwd=CLIENT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        cls.model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "bridge", None) is not None:
            cls.bridge.terminate()
            cls.bridge.wait(timeout=3)

    @classmethod
    def planner_or_controller(cls, request):
        cls.bridge.stdin.write(json.dumps(request) + "\n")
        cls.bridge.stdin.flush()
        result = json.loads(cls.bridge.stdout.readline())
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def make_host(self):
        data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model, data)
        host = XLeRobotMujocoHost.__new__(XLeRobotMujocoHost)
        host.model = self.model
        host.data = data
        host.command_lock = threading.Lock()
        host.base_cmd = np.zeros(3, dtype=np.float64)
        host.base_target_cmd = np.zeros(3, dtype=np.float64)
        host.last_web_command_time = 0.0
        host.watchdog_timeout = 0.5
        host.last_state_publish = float("inf")
        host.viewer = None
        return host

    def pose(self, host):
        x_addr = self.model.jnt_qposadr[self.model.joint("slide_joint_x").id]
        y_addr = self.model.jnt_qposadr[self.model.joint("slide_joint_y").id]
        # MuJoCo world -> web map, same conversion used by current_state().
        return {
            "x": float(host.data.qpos[y_addr]),
            "y": -float(host.data.qpos[x_addr]),
            "yaw": host.joint_qpos("hinge_joint_z"),
        }

    def follow_route(self, goal):
        host = self.make_host()
        sim_clock = SimClock()
        original_time = host_module.time
        host_module.time = sim_clock
        try:
            start = self.pose(host)
            route = self.planner_or_controller({
                "op": "route",
                "start": {"x": start["x"], "y": start["y"]},
                "goal": goal,
            })
            self.assertIsNotNone(route, f"A* found no route to {goal}")
            waypoint_index = 0
            turn_direction = None
            controller_ticks = 0
            max_ticks = 600

            while waypoint_index < len(route) and controller_ticks < max_ticks:
                pose = self.pose(host)
                waypoint = route[waypoint_index]
                distance = math.hypot(waypoint["x"] - pose["x"], waypoint["y"] - pose["y"])
                yaw_joint_id = self.model.joint("hinge_joint_z").id
                yaw_dof_addr = self.model.jnt_dofadr[yaw_joint_id]
                actual_yaw_rate = float(host.data.qvel[yaw_dof_addr])
                if distance <= 0.3 and abs(actual_yaw_rate) <= 0.05:
                    waypoint_index += 1
                    turn_direction = None
                    host.handle_move("stop", 0.0)
                    continue

                command = self.planner_or_controller({
                    "op": "control",
                    "pose": pose,
                    "target": waypoint,
                    "speed": 0.35,
                    "turnDirection": turn_direction,
                    "actualYawRate": actual_yaw_rate,
                })
                turn_direction = command["turnDirection"]
                host.handle_move(
                    "drive_vector",
                    math.hypot(command["linearX"], command["linearY"]),
                    command["angular"],
                    command["linearX"],
                    command["linearY"],
                )
                # 10 Hz controller cadence, 50 MuJoCo steps at 2 ms each.
                sim_clock.now += 0.1
                for _ in range(50):
                    host.step()
                    sim_clock.now += float(self.model.opt.timestep)
                controller_ticks += 1

            host.handle_move("stop", 0.0)
            end = self.pose(host)
            error = math.hypot(goal["x"] - end["x"], goal["y"] - end["y"])
            self.assertEqual(waypoint_index, len(route), f"did not complete route {route}")
            self.assertLessEqual(error, 0.3, f"goal error {error:.3f} m at {end}")
            return {"route": route, "end": end, "error": error, "ticks": controller_ticks}
        finally:
            host_module.time = original_time

    def test_table_1_2_3_approach_goals_with_production_controller_and_host(self):
        goals = {
            "table_1": {"x": -2.45, "y": -0.4},
            "table_2": {"x": 0.0, "y": 1.5},
            "table_3": {"x": 2.45, "y": -0.4},
        }
        for name, goal in goals.items():
            with self.subTest(destination=name):
                result = self.follow_route(goal)
                print(
                    f"{name}: waypoints={len(result['route'])}, "
                    f"final=({result['end']['x']:.3f},{result['end']['y']:.3f}), "
                    f"yaw={result['end']['yaw']:.3f}, "
                    f"error={result['error']:.3f}m, "
                    f"sim_time={result['ticks'] * 0.1:.1f}s"
                )

    def test_stationary_turn_uses_yaw_rate_damping_before_translation(self):
        host = self.make_host()
        sim_clock = SimClock()
        original_time = host_module.time
        host_module.time = sim_clock
        try:
            target = {"x": 0.0, "y": 2.0}
            turn_direction = None
            max_angular_command = 0.0
            elapsed = 0.0
            saw_braking = False
            while elapsed < 8.0:
                pose = self.pose(host)
                yaw_joint_id = self.model.joint("hinge_joint_z").id
                yaw_dof_addr = self.model.jnt_dofadr[yaw_joint_id]
                actual_yaw_rate = float(host.data.qvel[yaw_dof_addr])
                command = self.planner_or_controller({
                    "op": "control", "pose": pose, "target": target,
                    "speed": 0.35, "turnDirection": turn_direction,
                    "actualYawRate": actual_yaw_rate,
                })
                turn_direction = command["turnDirection"]
                max_angular_command = max(max_angular_command, abs(command["angular"]))
                saw_braking = saw_braking or command["phase"] == "braking"
                if command["phase"] == "driving":
                    self.assertLessEqual(abs(actual_yaw_rate), 0.05, "translation became available before yaw rate settled")
                    break
                self.assertEqual(command["linearX"], 0.0, "translation must stay disabled during turn alignment")
                self.assertEqual(command["linearY"], 0.0, "translation must stay disabled during turn alignment")
                host.handle_move(
                    "drive_vector", 0.0, command["angular"],
                    command["linearX"], command["linearY"],
                )
                sim_clock.now += 0.1
                for _ in range(50):
                    host.step()
                    sim_clock.now += float(self.model.opt.timestep)
                elapsed += 0.1
            final_yaw_rate = float(host.data.qvel[yaw_dof_addr])
            self.assertLessEqual(abs(final_yaw_rate), 0.05, f"yaw rate did not settle: {final_yaw_rate:.3f} rad/s")
            self.assertLessEqual(max_angular_command, 0.55)
            self.assertTrue(saw_braking, "controller never entered the measured-yaw braking phase")
            self.assertLess(elapsed, 8.0)
            print(
                f"stationary_turn: elapsed={elapsed:.1f}s, "
                f"max_command={max_angular_command:.3f}rad/s, "
                f"final_yaw_rate={final_yaw_rate:.3f}rad/s"
            )
        finally:
            host.handle_move("stop", 0.0)
            host_module.time = original_time


if __name__ == "__main__":
    unittest.main(verbosity=2)

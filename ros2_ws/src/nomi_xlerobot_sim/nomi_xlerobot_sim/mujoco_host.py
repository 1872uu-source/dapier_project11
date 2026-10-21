#!/usr/bin/env python3

import json
import math
import queue
import sys
import threading
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np
import zmq

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import JointState
from std_msgs.msg import String


# ============================================================
# XLeRobot 공식 MuJoCo 파일
# ============================================================

SCENE_PATH = Path.home() / "XLeRobot" / "simulation" / "mujoco" / "scene.xml"

CMD_PORT = 5555
DATA_PORT = 5556

# The range-scan implementation is shared with its MuJoCo regression scenarios.
sys.path.insert(0, str(SCENE_PATH.parent))
from drive_frame import body_velocity_to_slide, map_to_slide, slide_delta_to_body, slide_to_map
from obstacle_scan import scan_obstacles as cast_obstacle_scan


RIGHT_ARM = [
    "Rotation_R",
    "Pitch_R",
    "Elbow_R",
    "Wrist_Pitch_R",
    "Wrist_Roll_R",
    "Jaw_R",
]

LEFT_ARM = [
    "Rotation_L",
    "Pitch_L",
    "Elbow_L",
    "Wrist_Pitch_L",
    "Wrist_Roll_L",
    "Jaw_L",
]

BASE_JOINTS = [
    "slide_joint_x",
    "slide_joint_y",
    "hinge_joint_z",
]

WHEEL_ACTUATORS = [
    "wheel1",
    "wheel2",
    "wheel3",
]


class XLeRobotMujocoHost(Node):
    """
    XLeRobot 공식 MuJoCo scene.xml을 열고
    - ROS 2
    - XLeRobot Web Control의 ZeroMQ
    둘 다 연결하는 시뮬레이터 Host.
    """

    def __init__(self):
        super().__init__("nomi_xlerobot_mujoco_host")

        if not SCENE_PATH.exists():
            raise FileNotFoundError(
                f"MuJoCo scene 파일을 찾지 못했습니다: {SCENE_PATH}"
            )

        self.model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
        self.data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model, self.data)

        # MuJoCo 공식 viewer는 run() 안에서 launch_passive()로 생성한다.
        # ROS 2/ZMQ callback thread가 viewer 객체를 직접 만들지 않도록 한다.
        self.viewer = None

        self.camera_azimuth = 90
        self.camera_elevation = -30
        self.camera_distance = 3.0
        self.camera_target = np.zeros(3, dtype=np.float64)

        self.command_lock = threading.Lock()

        # base command = vx, vy, wz
        self.base_cmd = np.zeros(3, dtype=np.float64)
        self.base_target_cmd = np.zeros(3, dtype=np.float64)

        # current target for arm actuators
        self.arm_targets = np.zeros(12, dtype=np.float64)

        # watchdog
        self.last_web_command_time = time.monotonic()
        self.watchdog_timeout = 0.5

        # ------------------------------------------------------
        # ROS 2 publishers
        # ------------------------------------------------------
        self.joint_pub = self.create_publisher(
            JointState,
            "/joint_states",
            20,
        )

        self.state_pub = self.create_publisher(
            String,
            "/nomi/xlerobot/state",
            10,
        )

        # ------------------------------------------------------
        # ROS 2 subscribers
        # ------------------------------------------------------
        self.create_subscription(
            Twist,
            "/nomi/xlerobot/base_cmd_vel",
            self.base_cmd_callback,
            20,
        )

        self.create_subscription(
            String,
            "/nomi/xlerobot/arm_command",
            self.arm_command_callback,
            20,
        )

        self.create_subscription(
            String,
            "/nomi/xlerobot/gripper_command",
            self.gripper_command_callback,
            20,
        )

        self.create_subscription(
            String,
            "/nomi/xlerobot/reset",
            self.reset_callback,
            10,
        )

        # ------------------------------------------------------
        # ZeroMQ: official Web Control protocol
        # ------------------------------------------------------
        self.zmq_context = zmq.Context.instance()

        self.cmd_socket = self.zmq_context.socket(zmq.PULL)
        self.cmd_socket.bind(f"tcp://0.0.0.0:{CMD_PORT}")

        self.data_socket = self.zmq_context.socket(zmq.PUSH)
        self.data_socket.setsockopt(zmq.SNDHWM, 10)
        self.data_socket.setsockopt(zmq.LINGER, 0)
        self.data_socket.bind(f"tcp://0.0.0.0:{DATA_PORT}")

        # send_response() is called by both the simulation and ZMQ threads.
        # Queue from callers and keep all PUSH socket I/O in zmq_loop().
        self._command_response_queue = queue.Queue(maxsize=100)
        self._latest_state_response = None
        self._state_response_lock = threading.Lock()
        self._pending_zmq_response = None
        self._zmq_send_counters = {
            "sent": 0, "state_again": 0, "command_again": 0,
            "errors": 0, "queue_full": 0,
        }
        self._zmq_last_warning_at = 0.0

        self.zmq_running = True
        self.zmq_thread = threading.Thread(
            target=self.zmq_loop,
            daemon=True,
        )
        self.zmq_thread.start()

        self.last_state_publish = 0.0
        self.last_obstacle_scan_time = 0.0
        self.obstacle_scan_cache = []
        self.obstacle_scan_status_cache = {
            "healthy": False,
            "timestamp": 0.0,
            "age_ms": 0.0,
            "status": "error",
            "error": "range scan has not run yet",
            "beam_count": 180,
            "layer_heights_m": [0.12, 0.38, 0.72],
            "ray_count": 540,
            "range_m": 8.0,
            "hit_count": 0,
            "scan_duration_ms": 0.0,
        }
        self.last_scan_error_log_time = 0.0

        self.get_logger().info("========================================")
        self.get_logger().info("NOMI XLeRobot MuJoCo Host 시작")
        self.get_logger().info(f"Scene: {SCENE_PATH}")
        self.get_logger().info(f"ZMQ CMD : tcp://0.0.0.0:{CMD_PORT}")
        self.get_logger().info(f"ZMQ DATA: tcp://0.0.0.0:{DATA_PORT}")
        self.get_logger().info("========================================")

    # ========================================================
    # ROS 2 callbacks
    # ========================================================

    def base_cmd_callback(self, message: Twist):
        body_forward = float(message.linear.x)
        body_left = float(message.linear.y)
        angular = float(message.angular.z)
        if not np.all(np.isfinite([body_forward, body_left, angular])):
            self.get_logger().warning("Ignoring non-finite base velocity command")
            return
        yaw = float(self.joint_qpos("hinge_joint_z"))
        world_x, world_y = body_velocity_to_slide(body_forward, body_left, yaw)
        target = np.array([world_x, world_y, angular], dtype=np.float64)
        linear_speed = float(np.linalg.norm(target[:2]))
        if linear_speed > 1.0:
            target[:2] *= 1.0 / linear_speed
        target[2] = float(np.clip(target[2], -1.0, 1.0))
        with self.command_lock:
            self.base_target_cmd[:] = target
            self.last_web_command_time = time.monotonic()

    def arm_command_callback(self, message: String):
        try:
            payload = json.loads(message.data)
            arm = payload["arm"]
            joint_index = int(payload["joint_index"])
            angle = float(payload["angle"])
            self.set_arm_joint(arm, joint_index, angle)
        except Exception as exc:
            self.get_logger().error(
                f"arm command 오류: {exc}"
            )

    def gripper_command_callback(self, message: String):
        try:
            payload = json.loads(message.data)
            arm = payload["arm"]
            angle = float(payload["angle"])
            self.set_arm_joint(arm, 5, angle)
        except Exception as exc:
            self.get_logger().error(
                f"gripper command 오류: {exc}"
            )

    def reset_callback(self, _message: String):
        self.reset_robot()

    # ========================================================
    # MuJoCo helpers
    # ========================================================

    def joint_qpos(self, joint_name: str) -> float:
        jid = self.model.joint(joint_name).id
        qpos_addr = self.model.jnt_qposadr[jid]
        return float(self.data.qpos[qpos_addr])

    def set_joint_qpos(self, joint_name: str, value: float):
        jid = self.model.joint(joint_name).id
        qpos_addr = self.model.jnt_qposadr[jid]
        self.data.qpos[qpos_addr] = value

    def set_arm_joint(
        self,
        arm: str,
        joint_index: int,
        angle: float,
    ):
        if arm == "left":
            names = LEFT_ARM
        elif arm == "right":
            names = RIGHT_ARM
        else:
            return

        if not 0 <= joint_index < len(names):
            return

        name = names[joint_index]
        actuator_id = self.model.actuator(name).id

        self.data.ctrl[actuator_id] = angle


    def reset_robot(self):
        with self.command_lock:
            self.base_cmd[:] = 0.0
            self.base_target_cmd[:] = 0.0

        self.data.qpos[:] = 0.0
        self.data.qvel[:] = 0.0
        self.data.ctrl[:] = 0.0
        mujoco.mj_forward(self.model, self.data)

    def stop_robot(self):
        with self.command_lock:
            self.base_cmd[:] = 0.0
            self.base_target_cmd[:] = 0.0

        # velocity actuator인 base + wheel을 모두 정지시킨다.
        for name in (
            "slider_actuator_x",
            "slider_actuator_y",
            "hinge_actuator_z",
            "wheel1",
            "wheel2",
            "wheel3",
        ):
            actuator_id = self.model.actuator(name).id
            self.data.ctrl[actuator_id] = 0.0

    # ========================================================
    # 공식 Web Control용 ZeroMQ
    # ========================================================

    def send_response(self, response_type: str, data=None):
        """Queue a response; only zmq_loop() touches the PUSH socket."""
        message = {
            "type": "response",
            "response": response_type,
            "data": data or {},
            "timestamp": time.time(),
        }
        if response_type == "state":
            # State is replaceable; keep only the newest snapshot under load.
            with self._state_response_lock:
                self._latest_state_response = message
            return True
        try:
            self._command_response_queue.put_nowait(message)
            return True
        except queue.Full:
            self._zmq_send_counters["queue_full"] += 1
            self._log_zmq_send_warning(
                "ZMQ command response queue full; response not queued "
                f"(count={self._zmq_send_counters['queue_full']})"
            )
            return False

    def _log_zmq_send_warning(self, message, *, error=False):
        now = time.monotonic()
        if now - self._zmq_last_warning_at < 5.0:
            return
        self._zmq_last_warning_at = now
        if error:
            self.get_logger().error(message)
        else:
            self.get_logger().warning(message)

    def _next_zmq_response(self):
        if self._pending_zmq_response is not None:
            return self._pending_zmq_response
        try:
            self._pending_zmq_response = self._command_response_queue.get_nowait()
            return self._pending_zmq_response
        except queue.Empty:
            pass
        with self._state_response_lock:
            message = self._latest_state_response
            self._latest_state_response = None
        if message is not None:
            self._pending_zmq_response = message
        return self._pending_zmq_response

    def _flush_zmq_responses(self, max_messages=16):
        """Send queued responses without blocking simulation or command handling."""
        for _ in range(max_messages):
            message = self._next_zmq_response()
            if message is None:
                return
            is_state = message.get("response") == "state"
            try:
                self.data_socket.send_json(message, flags=zmq.NOBLOCK)
            except zmq.Again:
                key = "state_again" if is_state else "command_again"
                self._zmq_send_counters[key] += 1
                if is_state:
                    # Old state snapshots are disposable; the next tick replaces them.
                    self._pending_zmq_response = None
                    self._log_zmq_send_warning(
                        "ZMQ DATA queue full; dropping stale state snapshots "
                        f"(count={self._zmq_send_counters[key]})"
                    )
                else:
                    # Keep command replies for retry; never report them as delivered.
                    self._log_zmq_send_warning(
                        "ZMQ DATA queue full; retaining command response for retry "
                        f"(count={self._zmq_send_counters[key]})"
                    )
                return
            except Exception as exc:
                self._zmq_send_counters["errors"] += 1
                self._log_zmq_send_warning(
                    "Unexpected ZMQ response send error; retaining response: "
                    f"{exc} (count={self._zmq_send_counters['errors']})",
                    error=True,
                )
                return
            else:
                self._zmq_send_counters["sent"] += 1
                self._pending_zmq_response = None

    def scan_obstacles(self):
        """Return a cached live scan and health summary; refresh at 5 Hz."""
        now_monotonic = time.monotonic()
        if now_monotonic - self.last_obstacle_scan_time < 0.2:
            return self.obstacle_scan_cache, {
                **self.obstacle_scan_status_cache,
                "age_ms": round((now_monotonic - self.last_obstacle_scan_time) * 1000.0, 1),
            }

        try:
            hits, metrics = cast_obstacle_scan(self.model, self.data)
            duration_ms = float(metrics["scan_duration_ms"])
            healthy = duration_ms <= 250.0
            self.obstacle_scan_cache = hits
            self.obstacle_scan_status_cache = {
                **metrics,
                "healthy": healthy,
                "timestamp": time.time(),
                "status": "ok" if healthy else "slow",
                "error": None if healthy else "scan exceeded the 250 ms processing budget",
            }
        except Exception as exc:
            self.obstacle_scan_cache = []
            self.obstacle_scan_status_cache = {
                **self.obstacle_scan_status_cache,
                "healthy": False,
                "timestamp": time.time(),
                "status": "error",
                "error": str(exc)[:240],
                "hit_count": 0,
            }
            if now_monotonic - self.last_scan_error_log_time >= 5.0:
                self.get_logger().error(f"MuJoCo obstacle scan failed: {exc}")
                self.last_scan_error_log_time = now_monotonic

        self.last_obstacle_scan_time = time.monotonic()
        return self.obstacle_scan_cache, {
            **self.obstacle_scan_status_cache,
            "age_ms": round((self.last_obstacle_scan_time - now_monotonic) * 1000.0, 1),
        }

    def current_state(self):
        left = [self.joint_qpos(name) for name in LEFT_ARM]
        right = [self.joint_qpos(name) for name in RIGHT_ARM]

        world_x = self.joint_qpos("slide_joint_x")
        world_y = self.joint_qpos("slide_joint_y")
        map_x, map_y = slide_to_map(world_x, world_y)
        map_vx, map_vy = slide_to_map(float(self.data.qvel[0]), float(self.data.qvel[1]))
        position = {
            "x": map_x,
            "y": map_y,
            "z": 0.0,
        }

        rotation = {
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": self.joint_qpos("hinge_joint_z"),
        }

        velocity = {
            "linear": {
                "x": map_vx,
                "y": map_vy,
                "z": 0.0,
            },
            "angular": {
                "x": 0.0,
                "y": 0.0,
                "z": float(self.data.qvel[2]),
            },
        }

        wheel_joint_names = [
            "ST3215_Servo_Motor-v1-2_Hub---Servo",
            "ST3215_Servo_Motor-v1-1_Hub-2---Servo",
            "ST3215_Servo_Motor-v1_Revolute-40",
        ]

        wheel_velocities = [
            float(self.data.joint(name).qvel)
            for name in wheel_joint_names
        ]
        obstacle_scan, obstacle_scan_status = self.scan_obstacles()

        return {
            "position": position,
            "rotation": rotation,
            "arm_joints": {
                "left": left,
                "right": right,
            },
            "base_joints": [
                position["x"],
                position["y"],
                rotation["yaw"],
            ],
            "velocity": velocity,
            "wheel_velocities": wheel_velocities,
            "obstacle_scan": obstacle_scan,
            "obstacle_scan_status": obstacle_scan_status,
            "status": "connected",
        }

    def handle_zmq_command(self, message):
        if message.get("type") != "command":
            return

        command = message.get("command")
        data = message.get("data", {})

        if command == "ping":
            self.send_response("pong", {})
            return

        if command == "move":
            sequence = data.get("sequence")
            try:
                sequence = int(sequence) if sequence is not None else None
            except (TypeError, ValueError):
                sequence = None
            self.get_logger().info(
                f"[navigation-trace] host_received sequence={sequence} "
                f"direction={data.get('direction', 'stop')} "
                f"map=({float(data.get('linear_x', 0.0)):+.3f},{float(data.get('linear_y', 0.0)):+.3f}) "
                f"angular={float(data.get('angular', 0.0)):+.3f}"
            )
            self.handle_move(
                data.get("direction", "stop"),
                float(data.get("speed", 1.0)),
                float(data.get("angular", 0.0)),
                float(data.get("linear_x", 0.0)),
                float(data.get("linear_y", 0.0)),
                trace_sequence=sequence,
            )
            self.send_response(
                "success",
                {
                    "status": "success",
                    "command": "move",
                    "sequence": sequence,
                    "host_status": "target_applied",
                },
            )
            return

        if command == "stop":
            self.stop_robot()
            self.send_response(
                "success",
                {"status": "stopped"},
            )
            return

        if command == "reset":
            self.reset_robot()
            self.send_response(
                "success",
                {"status": "reset"},
            )
            return

        if command == "get_state":
            self.send_response(
                "state",
                self.current_state(),
            )
            return

        if command == "set_arm_joint":
            self.set_arm_joint(
                data.get("arm", "left"),
                int(data.get("joint_index", 0)),
                float(data.get("angle", 0.0)),
            )
            self.send_response(
                "success",
                {"status": "success"},
            )
            return

        if command == "reset_camera":
            self.camera_azimuth = 90
            self.camera_elevation = -30
            self.camera_distance = 3.0
            self.send_response(
                "success",
                {"status": "camera_reset"},
            )
            return

        if command == "set_camera_position":
            position = data.get("position") or [2.0, 2.0, 2.0]
            target = data.get("target") or [0.0, 0.0, 0.0]

            self.camera_target = np.array(target, dtype=np.float64)
            self.camera_distance = float(
                np.linalg.norm(
                    np.array(position) - np.array(target)
                )
            )

            self.send_response(
                "success",
                {
                    "status": "camera_updated",
                    "position": position,
                    "target": target,
                },
            )
            return

        self.send_response(
            "error",
            {
                "message": f"지원하지 않는 command: {command}"
            },
        )

    def handle_move(self, direction: str, speed: float, requested_angular: float = 0.0, requested_x: float = 0.0, requested_y: float = 0.0, trace_sequence=None):
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = 0.0
        if not np.isfinite(speed):
            speed = 0.0
        speed = float(np.clip(speed, 0.0, 1.0))
        try:
            requested_angular = float(requested_angular)
        except (TypeError, ValueError):
            requested_angular = 0.0
        if not np.isfinite(requested_angular):
            requested_angular = 0.0
        try:
            requested_x, requested_y = float(requested_x), float(requested_y)
        except (TypeError, ValueError):
            requested_x = requested_y = 0.0
        if not np.all(np.isfinite([requested_x, requested_y])):
            requested_x = requested_y = 0.0

        forward = 0.0
        left = 0.0
        angular = 0.0
        if direction == "drive_vector":
            map_x, map_y = float(requested_x), float(requested_y)
            vector_norm = float(np.hypot(map_x, map_y))
            if vector_norm > 1.0:
                map_x, map_y = map_x / vector_norm, map_y / vector_norm
            world_x, world_y = map_to_slide(map_x, map_y)
            angular = float(np.clip(requested_angular, -1.0, 1.0))
        elif direction == "forward":
            forward = speed
            angular = float(np.clip(requested_angular, -1.0, 1.0))
        elif direction == "backward":
            forward = -speed
            angular = float(np.clip(requested_angular, -1.0, 1.0))
        elif direction == "left":
            left = speed
        elif direction == "right":
            left = -speed
        elif direction == "rotate_left":
            angular = speed
        elif direction == "rotate_right":
            angular = -speed

        if direction != "drive_vector":
            yaw = float(self.joint_qpos("hinge_joint_z"))
            map_x, map_y = body_velocity_to_slide(forward, left, yaw)
        if direction == "drive_vector":
            # Web/planner vectors use the map frame; actuator slides use MuJoCo world.
            target = np.array([world_x, world_y, angular], dtype=np.float64)
        else:
            target = np.array([map_x, map_y, angular], dtype=np.float64)

        with self.command_lock:
            self.base_target_cmd[:] = target
            if trace_sequence is not None:
                self._navigation_trace_pending = {
                    "sequence": trace_sequence,
                    "target": target.copy(),
                    "actuator_logged": False,
                }
                self.get_logger().info(
                    f"[navigation-trace] target_applied sequence={trace_sequence} "
                    f"base_target_cmd=({target[0]:+.3f},{target[1]:+.3f},{target[2]:+.3f})"
                )
            if direction == "stop" or direction not in {
                "forward", "backward", "left", "right", "rotate_left", "rotate_right", "drive_vector"
            }:
                # Explicit stop and unknown commands bypass the ramp.
                self.base_cmd[:] = 0.0
                self.base_target_cmd[:] = 0.0

            self.last_web_command_time = time.monotonic()

    def zmq_loop(self):
        poller = zmq.Poller()
        poller.register(
            self.cmd_socket,
            zmq.POLLIN,
        )

        while self.zmq_running and rclpy.ok():
            try:
                events = dict(
                    poller.poll(100)
                )

                if self.cmd_socket in events:
                    raw = self.cmd_socket.recv_json()
                    self.handle_zmq_command(raw)

                self._flush_zmq_responses()

            except Exception as exc:
                if not self.zmq_running or not rclpy.ok():
                    break
                self.get_logger().error(
                    f"ZMQ loop 오류: {exc}"
                )
                time.sleep(0.1)

    # ========================================================
    # ROS 2 state publishing
    # ========================================================

    def publish_joint_state(self):
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()

        names = []
        positions = []

        for name in BASE_JOINTS:
            names.append(name)
            positions.append(self.joint_qpos(name))

        for name in RIGHT_ARM:
            names.append(name)
            positions.append(self.joint_qpos(name))

        for name in LEFT_ARM:
            names.append(name)
            positions.append(self.joint_qpos(name))

        message.name = names
        message.position = positions

        self.joint_pub.publish(message)

    def publish_state(self):
        payload = self.current_state()
        message = String()
        message.data = json.dumps(
            payload,
            ensure_ascii=False,
        )
        self.state_pub.publish(message)

        try:
            self.send_response(
                "state",
                payload,
            )
        except Exception:
            pass

    # ========================================================
    # simulation step
    # ========================================================

    def step(self):
        now = time.time()

        # 현재 공식 XLeRobot 모델은 총 18개 actuator를 사용한다.
        # base: 0~2 / arms: 3~14 / wheels: 15~17

        # Web Control이 일정 시간 동안 명령을 보내지 않으면 정지
        dt = max(float(self.model.opt.timestep), 0.0)
        with self.command_lock:
            if time.monotonic() - self.last_web_command_time > self.watchdog_timeout:
                # A dropped browser/server link must stop the base immediately.
                self.base_target_cmd[:] = 0.0
                self.base_cmd[:] = 0.0
            else:
                max_delta = np.array([2.5, 2.5, 4.0], dtype=np.float64) * dt
                difference = self.base_target_cmd - self.base_cmd
                self.base_cmd += np.clip(difference, -max_delta, max_delta)
            base_command = self.base_cmd.copy()

        # ------------------------------------------------------
        # Base velocity actuator
        # ------------------------------------------------------
        base_values = {
            "slider_actuator_x": float(base_command[0]),
            "slider_actuator_y": float(base_command[1]),
            "hinge_actuator_z": float(base_command[2]),
        }

        for actuator_name, value in base_values.items():
            actuator_id = self.model.actuator(actuator_name).id
            self.data.ctrl[actuator_id] = value

        # ------------------------------------------------------
        # Wheel velocity actuator
        #
        # 현재 공식 XLeRobot controller의 3-wheel mapping과 같은
        # 형태를 사용한다. 먼저 고수준의 (vx, vy, wz)를 받고
        # 이를 각 wheel 속도로 변환한다.
        # ------------------------------------------------------
        world_vx, world_vy, wz = base_command
        yaw = float(self.joint_qpos("hinge_joint_z"))
        vx, vy = slide_delta_to_body(world_vx, world_vy, yaw)
        wheel_radius = 0.1

        vel2wheel_matrix = np.array(
            [
                [0.0, 1.0, -wheel_radius],
                [-np.sqrt(3) * 0.5, -0.5, -wheel_radius],
                [np.sqrt(3) * 0.5, -0.5, -wheel_radius],
            ],
            dtype=np.float64,
        )

        wheel_scale = 20.0
        wheel_commands = wheel_scale * vel2wheel_matrix.dot(
            np.array([vx, vy, wz], dtype=np.float64)
        )

        for actuator_name, value in zip(
            WHEEL_ACTUATORS,
            wheel_commands,
        ):
            actuator_id = self.model.actuator(actuator_name).id
            self.data.ctrl[actuator_id] = float(value)

        mujoco.mj_step(
            self.model,
            self.data,
        )

        trace = getattr(self, "_navigation_trace_pending", None)
        if trace is not None and not trace["actuator_logged"]:
            trace["actuator_logged"] = True
            x_joint = self.model.joint("slide_joint_x")
            y_joint = self.model.joint("slide_joint_y")
            x_pos = float(self.data.qpos[x_joint.qposadr])
            y_pos = float(self.data.qpos[y_joint.qposadr])
            x_vel = float(self.data.qvel[x_joint.dofadr])
            y_vel = float(self.data.qvel[y_joint.dofadr])
            yaw = float(self.joint_qpos("hinge_joint_z"))
            yaw_joint = self.model.joint("hinge_joint_z")
            yaw_vel = float(self.data.qvel[yaw_joint.dofadr])
            self.get_logger().info(
                f"[navigation-trace] actuator_applied sequence={trace['sequence']} "
                f"base_cmd=({base_command[0]:+.3f},{base_command[1]:+.3f},{base_command[2]:+.3f}) "
                f"ctrl=({self.data.ctrl[self.model.actuator('slider_actuator_x').id]:+.3f},"
                f"{self.data.ctrl[self.model.actuator('slider_actuator_y').id]:+.3f},"
                f"{self.data.ctrl[self.model.actuator('hinge_actuator_z').id]:+.3f}) "
                f"pose_map=({y_pos:+.3f},{-x_pos:+.3f},{yaw:+.3f}) "
                f"velocity_map=({y_vel:+.3f},{-x_vel:+.3f},{yaw_vel:+.3f})"
            )

        # 공식 MuJoCo viewer는 렌더링을 직접 호출하지 않고 sync()로 갱신한다.
        if self.viewer is not None:
            try:
                self.viewer.cam.azimuth = self.camera_azimuth
                self.viewer.cam.elevation = self.camera_elevation
                self.viewer.cam.distance = self.camera_distance
                self.viewer.cam.lookat[:] = self.camera_target
                self.viewer.sync()
            except Exception:
                pass

        # ROS2 state 20Hz
        if now - self.last_state_publish >= 0.05:
            self.publish_joint_state()
            self.publish_state()
            self.last_state_publish = now

    def run(self):
        # MuJoCo 3.x 공식 Python viewer.
        # launch_passive()에서는 프로그램이 mj_step()을 직접 수행하고
        # viewer.sync()로 화면을 동기화한다.
        with mujoco.viewer.launch_passive(
            self.model,
            self.data,
        ) as viewer:
            self.viewer = viewer

            viewer.cam.azimuth = self.camera_azimuth
            viewer.cam.elevation = self.camera_elevation
            viewer.cam.distance = self.camera_distance
            viewer.cam.lookat[:] = self.camera_target

            try:
                while viewer.is_running():
                    self.step()
                    time.sleep(0.002)
            finally:
                self.stop_robot()
                self.viewer = None
                self.zmq_running = False
                self.zmq_thread.join(timeout=1.0)
                self.cmd_socket.close(0)
                self.data_socket.close(0)


def main():
    rclpy.init()

    node = XLeRobotMujocoHost()

    def spin_ros():
        try:
            rclpy.spin(node)
        except ExternalShutdownException:
            # Normal when main() shuts ROS down after the viewer exits.
            pass

    ros_thread = threading.Thread(
        target=spin_ros,
        daemon=True,
    )
    ros_thread.start()

    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_robot()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        ros_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()

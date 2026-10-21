# Setup Instructions

## Prerequisites
- Install Python 3.11 or newer — required for the server runtime.
- Install Node.js 22 or newer with npm — required for the client build tooling.
- Install Git and make sure `pip` and `npm` are on your PATH — needed for dependency management.

## Prepare Server Environment
1. `cd web_control/server` — switch to the server workspace.
2. `python -m venv .venv` — create an isolated Python environment.
3. `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows) — activate the environment.
4. `pip install -r requirements.txt` — install server dependencies.
5. `cp .env.example .env` — create the server environment file.
6. Edit `.env` and set at minimum:
   - `UI_HOST=0.0.0.0` — choose the bind address.
   - `UI_PORT=8000` — choose the HTTP port.
   - `ROBOT_HOST=localhost` — point to the robot or simulator host.
   - `ROBOT_PORT_CMD=5555` and `ROBOT_PORT_DATA=5556` — configure ZeroMQ ports.
7. `python main.py` — start the FastAPI and Socket.IO server.

## Prepare Client Environment
1. `cd web_control/client` — switch to the client workspace.
2. `npm install` — install client dependencies.
3. `cp .env.example .env` (create if absent) — define client environment variables.
4. Edit `.env` and set at minimum:
   - `VITE_SERVER_PROTOCOL=http` — protocol used to reach the server.
   - `VITE_SERVER_HOST=localhost` — hostname or IP of the server.
   - `VITE_SERVER_PORT=8000` — port that matches the server.
5. `npm run dev` — launch the Vite dev server.
6. `npm run build` — produce a production build when needed.

## Operate the Stack
1. Ensure the server is running and reachable — required before opening the UI.
2. Ensure the client dev server or production build is served — needed for browser access.
3. Open `http://localhost:5173` (default dev URL) — verify the dashboard loads.
4. Monitor terminal logs for telemetry, errors, or reconnect issues — helps with troubleshooting.

## Destination Route Planning

The browser plans destination routes with a 0.5 m A* grid using the static obstacle footprints in `client/src/utils/pathPlanner.ts`. The same three collidable boxes are defined in `../simulation/mujoco/scene.xml`. The MuJoCo host reports chassis slide coordinates; the scene boxes are rotated into world coordinates to match the chassis' fixed 90-degree orientation.

Keyboard and joystick translation is relative to the robot's current on-screen heading. The MuJoCo host rotates those body-relative commands into its fixed slide-joint axes, and automatic navigation projects map-frame waypoint deltas back into the same body frame. This keeps forward, backward, and strafe directions aligned after the robot turns.

The MuJoCo host casts a 180-beam, 360-degree scan at three heights, out to 8 m, at 10 Hz. The state packet includes hit points and sensor health, timestamp, age, hit count, scan duration, coverage, and range. A scan taking over 80 ms or older than 350 ms is considered unhealthy; automatic navigation stops if the scan is unhealthy or stale. The game view draws only fresh hits in orange and shows sensor status. Destination navigation replans around newly detected obstacles and stops if it cannot find a clear detour. Manual control shows the scan but does not yet automatically avoid obstacles; keep an operator ready to stop.

MuJoCo regression scenarios inject a temporary moving box into a copy of the scene and check multi-height detection, scan coverage/performance, and updates when the obstacle moves. Run them with the same Python environment used by the MuJoCo host:

```bash
cd ~/XLeRobot/simulation/mujoco
~/venvs/xlerobot_mujoco/bin/python -B -m unittest discover -s tests -v
```

After changing `simulation/mujoco/scene.xml`, `simulation/mujoco/obstacle_scan.py`, or the ROS2 host source, rebuild and source the ROS2 package before launching it:

```bash
cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select nomi_xlerobot_sim --symlink-install
source ~/ros2_ws/install/setup.bash
```

The Vite development server reloads browser changes automatically. Stop and restart `mujoco_host` after rebuilding so it loads the updated host and scene.

## NOMI Web Chat and Model Profiles

NOMI chat requests go through the ROS 2 `/nomi/command` topic and the Agent Execution Harness. The web server adds a unique `request_id` to each command, subscribes to `/nomi/task_status`, and forwards task updates to the browser session that started the request. The chat does not parse movement phrases or call the simulator directly; manual keyboard/gamepad movement remains on the existing `move_command` path.

Named-place requests also pass through the Harness `navigate_to` tool. The Agent publishes the requested place name on `/nomi/navigation_request`; the web bridge forwards it only to the browser session that owns that task. That browser resolves `집` from `xlerobot.homeWaypoint` first, then checks the existing `xlerobot.savedDestinations` list. Missing or ambiguous places do not use fallback coordinates. The browser starts its route follower only after fresh MuJoCo pose and range-sensor data pass validation.

Autonomous MuJoCo navigation is disabled by default. It requires `ROBOT_TYPE=mujoco`, `NOMI_MUJOCO_NAV_ENABLED=1`, a connected MuJoCo host, pose data no older than 2.5 seconds, and a healthy range scan no older than 1.2 seconds. Mock mode always disables it. The backend also rejects `drive_vector` commands that do not satisfy these conditions.

To explicitly enable the MuJoCo route follower, start the host in terminal 1:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source ~/venvs/xlerobot_mujoco/bin/activate
ros2 run nomi_xlerobot_sim mujoco_host
```

Start the web backend in terminal 2 with:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source ~/venvs/xlerobot_mujoco/bin/activate
export ROBOT_TYPE=mujoco NOMI_MUJOCO_NAV_ENABLED=1
cd ~/XLeRobot/web_control/server
python main.py
```

Start the frontend separately if it is not already running:

```bash
cd ~/XLeRobot/web_control/client
pnpm run dev
```

The model selector includes `qwen35_single` (`qwen3.5:9b`, Ollama) alongside the existing profiles. The active model label changes only after `/nomi/model_status` confirms the profile. Task cancellation publishes to `/nomi/cancel`; this is separate from the manual control panel's emergency stop. Harness status values are displayed as published, including `PENDING` (the current Harness does not publish a `QUEUED` state).

Web server Socket.IO events used by the NOMI panel: `nomi_command`, `nomi_command_received`, `nomi_task_status`, `nomi_task_cancel`, `nomi_cancel_result`, `nomi_model_switch`, `nomi_model_switch_sent`, `nomi_model_status`, `nomi_bridge_status`, and `nomi_get_status`.

Run the server route tests without starting a ROS node or robot host:

```bash
cd ~/XLeRobot/web_control/server
source ~/venvs/xlerobot_mujoco/bin/activate
python -m unittest discover -s tests -v
```

### Real Qwen3.5 Socket.IO E2E with MockRobot

This test starts the actual NOMI Agent and web Socket.IO server, switches the Agent to `qwen35_single`, and sends the 12 Korean cases through the same `nomi_command` event used by the panel. The test replaces the Agent's registry with the production registry backed only by `MockRobot`, uses ROS domain 222 with localhost-only discovery, and blocks `RemoteCore.connect`. It does not start MuJoCo or publish movement-control topics. Ollama must already be running with `qwen3.5:9b` installed; no model download is performed.

Run from a terminal where ROS Jazzy, the `ros2_ws` overlay, and the existing `xlerobot_mujoco` virtual environment are available:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
source ~/venvs/xlerobot_mujoco/bin/activate
export PYTHONPATH="$HOME/ros2_ws/src/nomi_agent:$PYTHONPATH"
python ~/XLeRobot/web_control/server/tests/run_qwen35_socket_e2e.py --timeout 120
```

The runner writes the 12-case results to `~/XLeRobot/nomi_benchmarks/webapp_qwen35_socket_e2e.csv` and the cancellation, duplicate-request, and two-browser isolation results to `~/XLeRobot/nomi_benchmarks/webapp_qwen35_socket_e2e.safety.json`. The runner starts its own temporary web server on an available localhost port and shuts it down when finished.

### Persistent Mock Development Stack

To keep the real NOMI Harness and Qwen3.5 agent connected while using the UI, run:

```bash
bash ~/XLeRobot/web_control/scripts/start_nomi_mock_dev.sh
```

The script uses ROS domain 222 with localhost-only discovery, starts the dedicated `server/dev/nomi_mock_agent.py` entry point with MockRobot-only skills, and starts the backend in `NOMI_MOCK_DEV=1` mode. In that mode the backend does not call `RemoteCore.connect()` or disconnect an existing robot host; manual robot control stays offline. The script checks Ollama and the installed model, refuses to stop processes using port 8000 or an existing `/nomi_agent` in domain 222, and starts the Vite client if port 5173 is free. Press Ctrl+C in the script terminal to stop only the processes it started. If the backend port is already occupied, stop the current backend yourself with Ctrl+C before rerunning so it can restart under domain 222.

If you need to keep another web instance running, use free alternate ports; for example `UI_PORT=8001 NOMI_MOCK_CLIENT_PORT=5174 bash ~/XLeRobot/web_control/scripts/start_nomi_mock_dev.sh`. The mock backend binds to `127.0.0.1` by default. To opt into LAN access, set `NOMI_MOCK_UI_HOST=0.0.0.0` explicitly.

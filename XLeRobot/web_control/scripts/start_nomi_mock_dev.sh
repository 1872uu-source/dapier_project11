#!/usr/bin/env bash
set -Eeo pipefail

ROOT="$HOME/XLeRobot"
WEB="$ROOT/web_control"
SERVER="$WEB/server"
CLIENT="$WEB/client"
ROS_WS="$HOME/ros2_ws"
VENV="$HOME/venvs/xlerobot_mujoco"
DOMAIN_ID=222
CHILD_PIDS=()

port_open() {
  python - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.2)
try:
    raise SystemExit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
finally:
    s.close()
PY
}

env_file_value() {
  local file="$1" key="$2"
  if [[ -f "$file" ]]; then
    awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file" | tr -d '\r'
  fi
}

cleanup() {
  local pid remaining=0
  trap - EXIT INT TERM
  for pid in "${CHILD_PIDS[@]:-}"; do
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  for _ in $(seq 1 50); do
    remaining=0
    for pid in "${CHILD_PIDS[@]:-}"; do
      kill -0 -- "-$pid" 2>/dev/null && remaining=1 || kill -0 "$pid" 2>/dev/null && remaining=1 || true
    done
    [[ "$remaining" == 0 ]] && break
    sleep 0.1
  done
  if [[ "$remaining" != 0 ]]; then
    echo "A managed child did not stop after SIGTERM; terminating only child PIDs started here."
    for pid in "${CHILD_PIDS[@]:-}"; do
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    done
  fi
  for pid in "${CHILD_PIDS[@]:-}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ -f /opt/ros/jazzy/setup.bash ]] || { echo "ROS Jazzy not found." >&2; exit 1; }
[[ -f "$ROS_WS/install/setup.bash" ]] || { echo "ROS workspace overlay not found: $ROS_WS/install/setup.bash" >&2; exit 1; }
[[ -f "$VENV/bin/activate" ]] || { echo "Python venv not found: $VENV/bin/activate" >&2; exit 1; }
command -v setsid >/dev/null 2>&1 || { echo "setsid is required for reliable child-process cleanup." >&2; exit 1; }
source /opt/ros/jazzy/setup.bash
source "$ROS_WS/install/setup.bash"
source "$VENV/bin/activate"

export ROS_DOMAIN_ID="$DOMAIN_ID"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY || true
export NOMI_MODEL_PROFILE=qwen35_single
export NOMI_MOCK_DEV=1
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

FILE_PORT="$(env_file_value "$SERVER/.env" UI_PORT)"
BACKEND_PORT="${UI_PORT:-${FILE_PORT:-8000}}"
BACKEND_HOST="${NOMI_MOCK_UI_HOST:-127.0.0.1}"
CLIENT_PORT="${NOMI_MOCK_CLIENT_PORT:-5173}"
export UI_HOST="$BACKEND_HOST" UI_PORT="$BACKEND_PORT"
if port_open "$BACKEND_PORT"; then
  echo "Backend port $BACKEND_PORT is already in use. No process was stopped." >&2
  echo "Stop the existing backend yourself with Ctrl+C, then rerun this script." >&2
  exit 2
fi
if ros2 node list 2>/dev/null | grep -Fxq '/nomi_agent'; then
  echo "A /nomi_agent already exists in safe ROS_DOMAIN_ID=$DOMAIN_ID. No process was stopped." >&2
  echo "Inspect and stop that Agent yourself before rerunning." >&2
  exit 2
fi

echo "Checking Ollama at $OLLAMA_HOST ..."
python - "$OLLAMA_HOST" <<'PY'
import json, sys, urllib.request
host = sys.argv[1].rstrip("/")
try:
    with urllib.request.urlopen(host + "/api/tags", timeout=4) as response:
        tags = json.load(response).get("models", [])
except Exception as exc:
    raise SystemExit(f"Ollama unavailable at {host}: {exc}; start Ollama and retry.")
models = [item.get("name", "") for item in tags]
if not any(name == "qwen3.5:9b" or name.startswith("qwen3.5:9b-") for name in models):
    raise SystemExit("qwen3.5:9b is not installed. Available models: " + ", ".join(models))
print("Ollama reachable; qwen3.5:9b is installed.")
PY

echo "Starting Mock-only NOMI Agent in ROS_DOMAIN_ID=$DOMAIN_ID ..."
setsid env PYTHONPATH="$HOME/ros2_ws/src/nomi_agent:$HOME/ros2_ws/src/nomi_agent/tests${PYTHONPATH:+:$PYTHONPATH}" \
  python -u "$SERVER/dev/nomi_mock_agent.py" &
CHILD_PIDS+=("$!")
agent_ready=0
for _ in $(seq 1 100); do
  kill -0 "${CHILD_PIDS[0]}" 2>/dev/null || { echo "Mock Agent exited during startup." >&2; exit 1; }
  if ros2 node list 2>/dev/null | grep -Fxq '/nomi_agent'; then agent_ready=1; break; fi
  sleep 0.2
done
[[ "$agent_ready" == 1 ]] || { echo "Mock Agent did not appear within 20 seconds." >&2; exit 1; }

echo "Starting Mock-safe Web Control backend on $BACKEND_HOST:$BACKEND_PORT ..."
setsid bash -c 'cd "$1" && exec env UI_HOST="$2" UI_PORT="$3" python -u main.py' _ "$SERVER" "$BACKEND_HOST" "$BACKEND_PORT" &
CHILD_PIDS+=("$!")
backend_ready=0
for _ in $(seq 1 100); do
  kill -0 "${CHILD_PIDS[1]}" 2>/dev/null || { echo "Backend exited during startup." >&2; exit 1; }
  if port_open "$BACKEND_PORT"; then backend_ready=1; break; fi
  sleep 0.2
done
[[ "$backend_ready" == 1 ]] || { echo "Backend did not open port $BACKEND_PORT." >&2; exit 1; }

echo "Mock Agent and backend are active. Robot/MuJoCo connection is disabled."
echo "Backend: http://localhost:$BACKEND_PORT"
echo "Backend bind is localhost only. For LAN access, opt in with NOMI_MOCK_UI_HOST=0.0.0.0."
if port_open "$CLIENT_PORT"; then
  echo "Port $CLIENT_PORT is occupied; leaving that process untouched. If it is XLeRobot Vite, open http://localhost:$CLIENT_PORT."
elif command -v pnpm >/dev/null 2>&1; then
  echo "Starting Vite client on http://localhost:$CLIENT_PORT ..."
  setsid bash -c 'cd "$1" && exec env VITE_SERVER_HOST=localhost VITE_SERVER_PORT="$2" VITE_SERVER_PROTOCOL=http pnpm exec vite --host 127.0.0.1 --port "$3"' _ "$CLIENT" "$BACKEND_PORT" "$CLIENT_PORT" &
  CHILD_PIDS+=("$!")
  echo "Open http://localhost:$CLIENT_PORT"
else
  echo "pnpm unavailable; in another terminal run: cd ~/XLeRobot/web_control/client && pnpm run dev -- --host 127.0.0.1"
fi
echo "Press Ctrl+C to stop only processes started by this script."

while true; do
  for pid in "${CHILD_PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      status=0; wait "$pid" || status=$?
      echo "A managed process exited (status $status); stopping remaining managed processes."
      exit "$status"
    fi
  done
  sleep 1
done

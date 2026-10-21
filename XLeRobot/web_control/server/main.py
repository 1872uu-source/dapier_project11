import time
import asyncio
import math
import json
import uuid
import os

import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.streaming import video_manager
from core.config import ServerConfig
from core.remote_core import RemoteCore
from core.nomi_bridge import NomiBridge
from core.model_profiles import MODEL_PROFILES

# Load simplified configuration
config = ServerConfig.from_env('.env')
config.validate()

print(f"Server Configuration:")
print(config)

# Create unified remote control core
remote_core = RemoteCore(config)
video_manager.attach_remote_core(remote_core)
main_event_loop = None
nomi_bridge = None
nomi_task_owners: dict[str, str] = {}
nomi_task_payloads: dict[str, dict] = {}
nomi_navigation_owners: dict[str, str] = {}
nomi_active_task_id: str | None = None
nomi_recent_task_id: str | None = None
nomi_pending_model_switch: dict | None = None
state_broadcast_task: asyncio.Task | None = None
NOMI_MOCK_DEV = os.getenv('NOMI_MOCK_DEV', '').strip() == '1'
NOMI_MUJOCO_NAV_ENABLED = (
    os.getenv('NOMI_MUJOCO_NAV_ENABLED', '0').strip() == '1'
    and not NOMI_MOCK_DEV
    and str(config.robot_type).strip().lower() == 'mujoco'
)
MUJOCO_MAP_BOUNDS = {'min_x': -5.0, 'max_x': 5.0, 'min_y': -4.0, 'max_y': 8.0}
MUJOCO_NAV_CLEARANCE_M = 0.8
MUJOCO_HOST_WATCHDOG_S = 0.5


def _navigation_execution_enabled() -> bool:
    return (
        NOMI_MUJOCO_NAV_ENABLED
        and not NOMI_MOCK_DEV
        and str(config.robot_type).strip().lower() == 'mujoco'
    )


def _decorate_robot_state(state: dict) -> dict:
    decorated = dict(state)
    decorated['navigation_execution_enabled'] = _navigation_execution_enabled()
    decorated['nomi_mock_mode'] = NOMI_MOCK_DEV
    return decorated


def _init_client_state() -> dict:
    now = time.time()
    return {
        'last_command_time': 0.0,
        'command_count': 0,
        'window_start': now,
        'throttle_violations': 0,
        'last_throttle_time': 0.0,
        'last_sequence': 0,
    }


client_states: dict[str, dict] = {}

RATE_LIMIT_CONFIG = {
    'max_commands_per_second': 20,
    'min_command_interval': 0.05,
    'rate_limit_window': 1.0,
    'throttle_penalty_duration': 2.0,
    'max_throttle_violations': 3,
}

async def startup_event():
    global main_event_loop, nomi_bridge, state_broadcast_task
    main_event_loop = asyncio.get_running_loop()
    nomi_bridge = NomiBridge(
        on_response=None,
        on_model_status=_forward_nomi_model_status,
        on_task_status=_forward_nomi_task_status,
        on_connection_status=_forward_nomi_bridge_status,
        on_navigation_request=_forward_nomi_navigation_request,
        on_navigation_cancel=_forward_nomi_navigation_cancel,
    )
    if nomi_bridge.start():
        print("NOMI ROS 2 bridge started")
    else:
        print(f"NOMI ROS 2 bridge unavailable: {nomi_bridge.error}")
    if NOMI_MOCK_DEV:
        # Safe development mode keeps manual motion and simulator paths offline.
        remote_core.connected = False
        print("NOMI_MOCK_DEV: RemoteCore.connect blocked; manual robot control stays offline")
    else:
        print("Starting remote core connection monitor...")
        state_broadcast_task = asyncio.create_task(_maintain_remote_connection())

async def shutdown_event():
    if state_broadcast_task is not None:
        state_broadcast_task.cancel()
        try:
            await state_broadcast_task
        except asyncio.CancelledError:
            pass
    if nomi_bridge is not None:
        nomi_bridge.stop()
    if not NOMI_MOCK_DEV:
        # Safe mock mode never initialized or connected the remote control core.
        print("Shutting down remote control core...")
        await remote_core.disconnect()
        print("Remote core shut down")


async def _maintain_remote_connection():
    """Retry the MuJoCo connection and keep publishing current readiness state."""
    connected_at: float | None = None
    while True:
        if not remote_core.connected:
            print(f"Attempting {config.robot_type} host connection...")
            if await remote_core.connect():
                connected_at = time.monotonic()
                print(f"Remote core connected to {config.robot_type} host successfully")
            else:
                state = _decorate_robot_state(await remote_core.get_state())
                await sio.emit('robot_state_snapshot', {'state': state})
                await asyncio.sleep(2.0)
                continue

        state = _decorate_robot_state(await remote_core.get_state())
        await sio.emit('robot_state_snapshot', {'state': state})

        last_state_received = remote_core.last_state_received
        telemetry_stale = last_state_received > 0 and time.time() - last_state_received > 2.5
        telemetry_missing = (
            last_state_received <= 0
            and connected_at is not None
            and time.monotonic() - connected_at > 3.0
        )
        if telemetry_stale or telemetry_missing:
            print("MuJoCo telemetry became stale; reconnecting remote core")
            await remote_core.disconnect()
            connected_at = None
            await asyncio.sleep(0.2)
            continue

        await asyncio.sleep(0.1)

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=False,
    engineio_logger=False,
)

app = FastAPI(title="XLeRobot Web Control API", version="0.1.0")

app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

socket_app = socketio.ASGIApp(sio, app)


def _forward_nomi_event(event: str, payload: dict, recipient: str | None = None) -> None:
    """Forward callbacks from the ROS thread through the server event loop."""
    loop = main_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(asyncio.create_task, sio.emit(event, payload, to=recipient))


async def _publish_nomi_task_status(payload: dict) -> None:
    global nomi_active_task_id
    task_id = str(payload.get('task_id', ''))
    recipient = nomi_task_owners.get(task_id)
    if not task_id or not recipient:
        return
    nomi_task_payloads[task_id] = payload
    if task_id == nomi_active_task_id and payload.get('status') in {'NEEDS_CLARIFICATION', 'VALIDATED', 'SUCCEEDED', 'FAILED', 'CANCELLED'}:
        nomi_active_task_id = None
    if len(nomi_task_payloads) > 200:
        oldest = next(iter(nomi_task_payloads))
        nomi_task_payloads.pop(oldest, None)
        nomi_task_owners.pop(oldest, None)
    await sio.emit('nomi_task_status', payload, to=recipient)


def _forward_nomi_task_status(payload: dict) -> None:
    loop = main_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(asyncio.create_task, _publish_nomi_task_status(payload))


async def _publish_nomi_navigation_request(payload: dict) -> None:
    # The tool may publish its request immediately before the Harness publishes
    # terminal SUCCEEDED, so retain the last accepted task as a short routing
    # fallback after the active slot is cleared.
    task_id = nomi_active_task_id or nomi_recent_task_id
    recipient = nomi_task_owners.get(task_id or "")
    name = str(payload.get('name', '')).strip()
    request_id = str(payload.get('request_id', '')).strip()
    if not recipient or not name or not request_id:
        return
    normalized = ''.join(name.casefold().split()).replace('_', '').replace('-', '')
    destination = 'home' if normalized in {'집', 'home'} else 'saved'
    nomi_navigation_owners[request_id] = recipient
    if len(nomi_navigation_owners) > 200:
        nomi_navigation_owners.pop(next(iter(nomi_navigation_owners)), None)
    await sio.emit('nomi_navigation_request', {
        'destination': destination,
        'name': name,
        'request_id': request_id,
    }, to=recipient)


def _forward_nomi_navigation_request(payload: dict) -> None:
    loop = main_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(asyncio.create_task, _publish_nomi_navigation_request(payload))


async def _publish_nomi_navigation_cancel(request_id: str) -> None:
    recipient = nomi_navigation_owners.get(request_id)
    if recipient:
        await sio.emit('nomi_navigation_cancel', {'request_id': request_id}, to=recipient)


def _forward_nomi_navigation_cancel(request_id: str) -> None:
    loop = main_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(asyncio.create_task, _publish_nomi_navigation_cancel(request_id))


async def _publish_nomi_model_status(value: str) -> None:
    global nomi_pending_model_switch
    pending = nomi_pending_model_switch
    if pending is None:
        return
    if value.startswith('ERROR: '):
        payload = {
            'status': 'error', 'profile': pending['profile'],
            'request_id': pending['request_id'], 'message': value[7:],
        }
    elif value == pending['profile']:
        payload = {
            'status': 'success', 'profile': value,
            'request_id': pending['request_id'],
            'label': MODEL_PROFILES[value]['label'],
        }
    else:
        return
    recipient = pending['sid']
    nomi_pending_model_switch = None
    await sio.emit('nomi_model_status', payload, to=recipient)


def _forward_nomi_model_status(value: str) -> None:
    loop = main_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(asyncio.create_task, _publish_nomi_model_status(value))


async def _publish_nomi_bridge_status(connected: bool, error: str | None) -> None:
    global nomi_pending_model_switch
    await sio.emit('nomi_bridge_status', {
        'connected': connected,
        'message': 'NOMI Agent 연결됨' if connected else (error or 'NOMI Agent 연결 안 됨'),
    })
    if not connected and nomi_pending_model_switch is not None:
        pending = nomi_pending_model_switch
        nomi_pending_model_switch = None
        await sio.emit('nomi_model_status', {
            'status': 'error', 'profile': pending['profile'],
            'request_id': pending['request_id'],
            'message': error or '모델 변경 중 NOMI Agent 연결이 끊겼습니다.',
        }, to=pending['sid'])


def _forward_nomi_bridge_status(connected: bool, error: str | None) -> None:
    loop = main_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(asyncio.create_task, _publish_nomi_bridge_status(connected, error))


@sio.event
async def get_robot_state(sid):
    state = _decorate_robot_state(await remote_core.get_state())
    await sio.emit('robot_state_snapshot', {'state': state}, to=sid)


@sio.event
async def reset_robot(sid):
    result = await remote_core.reset()
    await sio.emit('robot_reset_result', result, to=sid)


@sio.event
async def nomi_command(sid, data):
    global nomi_active_task_id, nomi_recent_task_id
    data = data if isinstance(data, dict) else {}
    text = str(data.get('text', '')).strip()
    validate_only = data.get('validate_only', False) is True
    if not text:
        await sio.emit('nomi_response', {'status': 'error', 'request_id': (data or {}).get('request_id'), 'message': '명령을 입력해 주세요.'}, to=sid)
        return
    request_id = str((data or {}).get('request_id') or uuid.uuid4()).strip()
    if not request_id or len(request_id) > 128 or len(text) > 4000:
        await sio.emit('nomi_response', {'status': 'error', 'request_id': request_id, 'message': '명령 또는 요청 ID 형식이 올바르지 않습니다.'}, to=sid)
        return
    existing_owner = nomi_task_owners.get(request_id)
    if existing_owner:
        if existing_owner == sid:
            prior = nomi_task_payloads.get(request_id)
            await sio.emit('nomi_command_received', {
                'status': 'duplicate', 'request_id': request_id,
            }, to=sid)
            if prior:
                await sio.emit('nomi_task_status', prior, to=sid)
        else:
            await sio.emit('nomi_response', {'status': 'error', 'request_id': request_id, 'message': '이미 사용 중인 요청 ID입니다.'}, to=sid)
        return
    if nomi_active_task_id is not None:
        active_status = nomi_task_payloads.get(nomi_active_task_id, {}).get('status')
        if active_status not in {'NEEDS_CLARIFICATION', 'VALIDATED', 'SUCCEEDED', 'FAILED', 'CANCELLED'}:
            await sio.emit('nomi_response', {
                'status': 'error', 'request_id': request_id,
                'message': f'다른 사용자의 NOMI 작업이 진행 중입니다. 작업 ID: {nomi_active_task_id}',
            }, to=sid)
            return
        nomi_active_task_id = None
    if nomi_bridge is None or not nomi_bridge.available or not nomi_bridge.agent_connected:
        await sio.emit('nomi_response', {
            'status': 'error',
            'request_id': request_id,
            'message': 'NOMI ROS 2 브리지에 연결되지 않아 Harness에 명령을 전달하지 못했습니다.',
        }, to=sid)
        return
    nomi_task_owners[request_id] = sid
    nomi_task_payloads[request_id] = {'task_id': request_id, 'status': 'PENDING'}
    nomi_active_task_id = request_id
    nomi_recent_task_id = request_id
    if not nomi_bridge.send_command(text, request_id, validate_only=validate_only):
        nomi_task_owners.pop(request_id, None)
        nomi_task_payloads.pop(request_id, None)
        nomi_active_task_id = None
        await sio.emit('nomi_response', {
            'status': 'error',
            'request_id': request_id,
            'message': 'NOMI ROS 2 브리지에 연결되지 않아 Harness에 명령을 전달하지 못했습니다.',
        }, to=sid)
        return
    await sio.emit('nomi_command_received', {
        'status': 'accepted', 'text': text, 'request_id': request_id,
        'validate_only': validate_only,
    }, to=sid)


@sio.event
async def nomi_destinations_sync(sid, data):
    """Forward the browser's validated navigation destinations to the Agent."""
    destinations = (data or {}).get('destinations') if isinstance(data, dict) else None
    if not isinstance(destinations, list) or len(destinations) > 100:
        return
    checked = []
    for item in destinations:
        if not isinstance(item, dict):
            continue
        name = item.get('name')
        x, y = item.get('x'), item.get('y')
        aliases = item.get('aliases', [])
        if (not isinstance(name, str) or not name.strip() or len(name) > 120
                or isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                or isinstance(y, bool) or not isinstance(y, (int, float)) or not math.isfinite(y)
                or not -18 <= x <= 18 or not -4 <= y <= 24):
            continue
        if not isinstance(aliases, list):
            aliases = []
        checked.append({
            'name': name.strip(), 'x': float(x), 'y': float(y),
            'aliases': [alias.strip() for alias in aliases[:10]
                        if isinstance(alias, str) and alias.strip() and len(alias) <= 120],
            'kind': str(item.get('kind', 'saved'))[:40],
        })
    if nomi_bridge is not None and checked:
        nomi_bridge.sync_destinations(checked)


@sio.event
async def nomi_task_cancel(sid, data):
    task_id = str((data or {}).get('task_id', '')).strip()
    if not task_id or nomi_task_owners.get(task_id) != sid or nomi_active_task_id != task_id:
        await sio.emit('nomi_cancel_result', {
            'status': 'error', 'task_id': task_id,
            'message': '이 연결에서 취소할 수 있는 작업을 찾지 못했습니다.',
        }, to=sid)
        return
    status = nomi_task_payloads.get(task_id, {}).get('status')
    if status in {'NEEDS_CLARIFICATION', 'VALIDATED', 'SUCCEEDED', 'FAILED', 'CANCELLED'}:
        await sio.emit('nomi_cancel_result', {
            'status': 'error', 'task_id': task_id,
            'message': '이미 종료된 작업입니다.',
        }, to=sid)
        return
    if nomi_bridge is None or not nomi_bridge.available or not nomi_bridge.agent_connected or not nomi_bridge.cancel_task(task_id):
        await sio.emit('nomi_cancel_result', {
            'status': 'error', 'task_id': task_id,
            'message': 'NOMI ROS 2 브리지에 연결되지 않아 취소를 전달하지 못했습니다.',
        }, to=sid)
        return
    await sio.emit('nomi_cancel_result', {'status': 'accepted', 'task_id': task_id}, to=sid)


@sio.event
async def nomi_navigation_result(sid, data):
    payload = data if isinstance(data, dict) else {}
    request_id = str(payload.get('request_id', '')).strip()
    status = payload.get('status')
    owner = nomi_navigation_owners.get(request_id)
    if not request_id or owner != sid or status not in {'SUCCEEDED', 'FAILED', 'CANCELLED'}:
        await sio.emit('nomi_navigation_result_ack', {
            'status': 'error', 'request_id': request_id,
            'message': '유효한 내비게이션 요청과 결과 상태를 확인하지 못했습니다.',
        }, to=sid)
        return
    result = {
        'request_id': request_id,
        'status': status,
        'message': str(payload.get('message', ''))[:500],
    }
    if status == 'SUCCEEDED':
        position = payload.get('position')
        distance = payload.get('distance_m')
        valid_arrival = (
            payload.get('completion_verified') is True
            and isinstance(position, dict)
            and all(isinstance(position.get(axis), (int, float)) and math.isfinite(position[axis]) for axis in ('x', 'y'))
            and isinstance(distance, (int, float)) and math.isfinite(distance) and 0 <= distance <= 0.3
        )
        if not valid_arrival:
            await sio.emit('nomi_navigation_result_ack', {
                'status': 'error', 'request_id': request_id,
                'message': '현재 위치가 목적지 0.3m 이내라는 도착 확인이 없어 완료 결과를 거부했습니다.',
            }, to=sid)
            return
        result.update({'completion_verified': True, 'position': position, 'distance_m': distance})
    if nomi_bridge is None or not nomi_bridge.publish_navigation_result(result):
        await sio.emit('nomi_navigation_result_ack', {
            'status': 'error', 'request_id': request_id,
            'message': 'NOMI ROS 2 브리지로 실제 도착 결과를 전달하지 못했습니다.',
        }, to=sid)
        return
    nomi_navigation_owners.pop(request_id, None)
    await sio.emit('nomi_navigation_result_ack', {'status': 'forwarded', 'request_id': request_id}, to=sid)


@sio.event
async def nomi_model_switch(sid, data):
    global nomi_pending_model_switch
    profile = str((data or {}).get('profile', '')).strip()
    if profile not in MODEL_PROFILES:
        await sio.emit('nomi_model_status', {'status': 'error', 'message': '지원하지 않는 모델 프로필입니다.'}, to=sid)
        return
    if nomi_pending_model_switch is not None:
        await sio.emit('nomi_model_status', {
            'status': 'error', 'message': '다른 모델 변경 결과를 확인 중입니다.',
        }, to=sid)
        return
    request_id = str((data or {}).get('request_id') or uuid.uuid4()).strip()
    if not request_id or len(request_id) > 128:
        await sio.emit('nomi_model_status', {'status': 'error', 'message': '요청 ID 형식이 올바르지 않습니다.'}, to=sid)
        return
    if nomi_bridge is None or not nomi_bridge.available or not nomi_bridge.agent_connected:
        await sio.emit('nomi_model_status', {'status': 'error', 'message': 'NOMI ROS 2 브리지에 연결되지 않았습니다.'}, to=sid)
        return
    nomi_pending_model_switch = {'sid': sid, 'profile': profile, 'request_id': request_id}
    if not nomi_bridge.switch_model(profile):
        nomi_pending_model_switch = None
        await sio.emit('nomi_model_status', {'status': 'error', 'message': 'NOMI ROS 2 브리지에 연결되지 않았습니다.'}, to=sid)
        return
    await sio.emit('nomi_model_switch_sent', {'profile': profile, 'request_id': request_id}, to=sid)


@sio.event
async def nomi_get_status(sid):
    connected = bool(nomi_bridge and nomi_bridge.available and nomi_bridge.agent_connected)
    await sio.emit('nomi_bridge_status', {
        'connected': connected,
        'message': 'NOMI Agent 연결됨' if connected else 'NOMI Agent 연결 안 됨',
    }, to=sid)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "XLeRobot Web Control Server is running"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    controller_info = {
        'type': config.robot_type,
        'connected': remote_core.connected,
        'capabilities': remote_core.get_capabilities()
    }

    return {
        "status": "healthy",
        "service": "XLeRobot Web Control",
        "controller": controller_info
    }

@app.get("/robot/info")
async def robot_info():
    """Robot controller info endpoint"""
    return {
        'controller_type': config.robot_type,
        'connected': remote_core.connected,
        'capabilities': remote_core.get_capabilities(),
        'state': await remote_core.get_state() if remote_core.connected else None
    }

@app.get("/robot/controllers")
async def available_controllers():
    """Get available controllers"""
    return {
        'available': ['maniskill', 'mujoco', 'xlerobot'],
        'current': config.robot_type,
        'description': 'Unified remote control supports all robot types via host programs'
    }

@app.post("/robot/camera/reset")
async def reset_camera():
    """Reset camera to default position"""
    try:
        result = await remote_core.reset_camera()
        return result
    except Exception as e:
        return {"error": f"Camera reset failed: {str(e)}"}

@app.post("/robot/camera/position")
async def set_camera_position(request: dict):
    """Set camera position"""
    position = request.get('position')
    target = request.get('target')

    if not position:
        return {"error": "Position is required"}

    try:
        result = await remote_core.set_camera_position(position, target)
        return result
    except Exception as e:
        return {"error": f"Set camera position failed: {str(e)}"}

@app.get("/robot/camera/info")
async def get_camera_info():
    """Get camera info"""
    try:
        # For simplified architecture, return basic camera info
        return {
            'camera_id': 0,
            'position': [2.0, 2.0, 2.0],
            'target': [0.0, 0.0, 0.0],
            'frame_size': {'width': config.video_width, 'height': config.video_height},
            'fps': config.video_fps,
            'quality': config.video_quality
        }
    except Exception as e:
        return {"error": f"Get camera info failed: {str(e)}"}

# Rate limiting and throttling functions
def check_rate_limit(sid: str) -> bool:
    """Check if client is within rate limits"""
    current_time = time.time()
    client_state = client_states.get(sid)

    if not client_state:
        return True

    # Reset command count if window has passed
    if current_time - client_state['window_start'] >= RATE_LIMIT_CONFIG['rate_limit_window']:
        client_state['command_count'] = 0
        client_state['window_start'] = current_time

    return client_state['command_count'] < RATE_LIMIT_CONFIG['max_commands_per_second']

def check_throttle(sid: str) -> bool:
    """Check if client is throttling commands too fast"""
    current_time = time.time()
    client_state = client_states.get(sid)

    if not client_state:
        return True

    # Check if client is in penalty period
    if (client_state['throttle_violations'] >= RATE_LIMIT_CONFIG['max_throttle_violations'] and
        current_time - client_state['last_throttle_time'] < RATE_LIMIT_CONFIG['throttle_penalty_duration']):
        return False

    # Reset violations if penalty period has passed
    if current_time - client_state['last_throttle_time'] >= RATE_LIMIT_CONFIG['throttle_penalty_duration']:
        client_state['throttle_violations'] = 0

    # Check minimum interval between commands
    if current_time - client_state['last_command_time'] < RATE_LIMIT_CONFIG['min_command_interval']:
        client_state['throttle_violations'] += 1
        client_state['last_throttle_time'] = current_time
        return False

    return True

def update_client_state(sid: str, *, timestamp: float) -> None:
    """Update client state after successful command"""
    client_state = client_states.setdefault(sid, _init_client_state())
    client_state['last_command_time'] = timestamp
    client_state['command_count'] += 1

@sio.event
async def connect(sid, environ, auth):
    """Client connection event"""
    print(f"Client connected: {sid}")
    # Initialize client state
    client_states[sid] = _init_client_state()
    await sio.emit('connection_established', {'message': 'Connected to XLeRobot control server'}, to=sid)
    await nomi_get_status(sid)

@sio.event
async def disconnect(sid):
    """Client disconnect event"""
    print(f"Client disconnected: {sid}")

    if sid in video_manager.stream_tasks:
        task = video_manager.stream_tasks[sid]
        if not task.cancelled():
            task.cancel()
            print(f"Cancelled video stream task for disconnected client {sid}")
        del video_manager.stream_tasks[sid]

    if client_states.pop(sid, None) is not None:
        print(f"Cleaned up state for client {sid}")
    for request_id, owner in list(nomi_navigation_owners.items()):
        if owner == sid:
            nomi_navigation_owners.pop(request_id, None)

@sio.event
async def ping(sid, data):
    """Ping-pong test event"""
    print(f"Received ping from {sid}: {data}")
    await sio.emit('pong', {'message': 'pong', 'timestamp': data.get('timestamp')}, to=sid)

@sio.event
async def move_command(sid, data):
    """Movement command handler with rate limiting and throttling"""
    data = data if isinstance(data, dict) else {}
    direction = data.get('direction')
    sequence = data.get('sequence')
    timestamp = data.get('timestamp', time.time() * 1000)
    try:
        speed = float(data.get('speed', 1.0))
        angular = float(data.get('angular', 0.0))
        linear_x = float(data.get('linear_x', 0.0))
        linear_y = float(data.get('linear_y', 0.0))
        client_timestamp = float(timestamp)
    except (TypeError, ValueError):
        speed, angular, linear_x, linear_y, client_timestamp = float('nan'), float('nan'), float('nan'), float('nan'), 0.0
    if not math.isfinite(client_timestamp):
        client_timestamp = 0.0

    current_time = time.time()
    client_state = client_states.setdefault(sid, _init_client_state())
    if sequence is not None:
        try:
            sequence = int(sequence)
        except (TypeError, ValueError):
            sequence = -1
        if sequence <= client_state['last_sequence']:
            await sio.emit('command_received', {
                'type': 'move', 'status': 'stale', 'sequence': sequence,
                'server_timestamp': current_time * 1000,
            }, to=sid)
            return
        client_state['last_sequence'] = sequence

    allowed_directions = {'forward', 'backward', 'left', 'right', 'rotate_left', 'rotate_right', 'drive_vector', 'stop'}
    if direction not in allowed_directions or not all(math.isfinite(value) for value in (speed, angular, linear_x, linear_y)):
        await sio.emit('command_received', {
            'type': 'move', 'status': 'error', 'message': 'Invalid movement direction or speed',
            'sequence': sequence, 'server_timestamp': current_time * 1000,
        }, to=sid)
        return
    requested_speed = speed
    speed = min(1.0, max(0.0, speed))
    angular = min(1.0, max(-1.0, angular))
    linear_x = min(1.0, max(-1.0, linear_x))
    linear_y = min(1.0, max(-1.0, linear_y))

    def emit_command_status(status, **extra):
        if direction == 'drive_vector':
            diagnostic_status = 'accepted' if status in {'success', 'executed', 'accepted'} else (
                'rejected' if status == 'error' else status
            )
            print(
                f"[navigation-command] {diagnostic_status} sequence={sequence} "
                f"requested=({linear_x:+.2f},{linear_y:+.2f}) angular={angular:+.2f} "
                f"reason={extra.get('message', '')}"
            )
        return sio.emit('command_received', {
            'type': 'move', 'direction': direction, 'speed': speed,
            'status': status, 'sequence': sequence,
            'client_timestamp': client_timestamp,
            'server_timestamp': time.time() * 1000,
            'speed_limited': speed != requested_speed,
            **extra,
        }, to=sid)

    # Stops are safety commands: never reject them because of movement throttling.
    if direction == 'stop':
        if not remote_core.connected:
            await emit_command_status('error', message='Remote core not connected to robot host')
            return
        result = await remote_core.stop(sequence=sequence)
        update_client_state(sid, timestamp=current_time)
        await emit_command_status(
            result.get('status', 'success'),
            robot_state=_decorate_robot_state(await remote_core.get_state()),
            metrics={'latency': max(0.0, time.time() * 1000 - client_timestamp) if client_timestamp else None},
        )
        return

    # The browser's route follower uses drive_vector. Keep a server-side gate
    # as well so stale sensors, non-MuJoCo profiles, and Mock-only mode cannot
    # issue autonomous navigation commands through a hand-crafted socket call.
    if direction == 'drive_vector':
        if (not NOMI_MUJOCO_NAV_ENABLED or NOMI_MOCK_DEV
                or str(config.robot_type).strip().lower() != 'mujoco'):
            await emit_command_status(
                'error', message='MuJoCo 자동 주행이 명시적으로 활성화되지 않아 이동 명령을 차단했습니다.',
            )
            return
        nav_state = await remote_core.get_state()
        scan_status = nav_state.get('obstacle_scan_status') or {}
        state_age = nav_state.get('state_age')
        scan_age = scan_status.get('age_ms')
        state_valid = (
            remote_core.connected
            and nav_state.get('host_connected') is True
            and isinstance(state_age, (int, float)) and math.isfinite(state_age) and state_age <= 2.5
            and nav_state.get('robot_type') == 'mujoco'
        )
        scan_valid = (
            scan_status.get('healthy') is True
            and isinstance(scan_age, (int, float)) and math.isfinite(scan_age) and scan_age <= 1200
            and isinstance(nav_state.get('obstacle_scan'), list)
        )
        if not state_valid or not scan_valid:
            await emit_command_status(
                'error', message='최신 MuJoCo 위치 또는 거리 센서 데이터가 없어 자동 주행 명령을 차단했습니다.',
            )
            return
        position = nav_state.get('position') or {}
        map_x, map_y = position.get('x'), position.get('y')
        if (not isinstance(map_x, (int, float)) or isinstance(map_x, bool)
                or not isinstance(map_y, (int, float)) or isinstance(map_y, bool)
                or not math.isfinite(map_x) or not math.isfinite(map_y)):
            await emit_command_status(
                'error', message='MuJoCo 지도 좌표를 확인할 수 없어 자동 주행 명령을 차단했습니다.',
            )
            return
        safe_bounds = {
            'min_x': MUJOCO_MAP_BOUNDS['min_x'] + MUJOCO_NAV_CLEARANCE_M,
            'max_x': MUJOCO_MAP_BOUNDS['max_x'] - MUJOCO_NAV_CLEARANCE_M,
            'min_y': MUJOCO_MAP_BOUNDS['min_y'] + MUJOCO_NAV_CLEARANCE_M,
            'max_y': MUJOCO_MAP_BOUNDS['max_y'] - MUJOCO_NAV_CLEARANCE_M,
        }
        predicted_x = map_x + linear_x * MUJOCO_HOST_WATCHDOG_S
        predicted_y = map_y + linear_y * MUJOCO_HOST_WATCHDOG_S
        if not (
            safe_bounds['min_x'] <= map_x <= safe_bounds['max_x']
            and safe_bounds['min_y'] <= map_y <= safe_bounds['max_y']
            and safe_bounds['min_x'] <= predicted_x <= safe_bounds['max_x']
            and safe_bounds['min_y'] <= predicted_y <= safe_bounds['max_y']
        ):
            await emit_command_status(
                'error', message='로봇 여유 공간을 포함한 MuJoCo 지도 경계를 벗어날 수 있어 자동 주행 명령을 차단했습니다.',
            )
            return

    # Check rate limiting
    if not check_rate_limit(sid):
        await emit_command_status(
            'rate_limited',
            message=f'Rate limit exceeded: maximum {RATE_LIMIT_CONFIG["max_commands_per_second"]} commands per second',
            max_rate=RATE_LIMIT_CONFIG['max_commands_per_second'],
        )
        return

    # Check throttling
    if not check_throttle(sid):
        client_state = client_states.setdefault(sid, _init_client_state())
        await emit_command_status(
            'throttled',
            message=f'Command throttled: minimum {RATE_LIMIT_CONFIG["min_command_interval"]*1000:.0f}ms interval required',
            min_interval=RATE_LIMIT_CONFIG['min_command_interval'] * 1000,
            violations=client_state['throttle_violations'],
            penalty_remaining=max(0, RATE_LIMIT_CONFIG['throttle_penalty_duration'] - (current_time - client_state['last_throttle_time'])) if client_state['throttle_violations'] >= RATE_LIMIT_CONFIG['max_throttle_violations'] else 0,
        )
        return

    if not remote_core.connected:
        await emit_command_status(
            'error',
            message='Remote core not connected to robot host',
        )
        return

    # Log command with rate limiting info
    client_state = client_states.setdefault(sid, _init_client_state())
    next_count = client_state['command_count'] + 1
    if next_count == 1 or next_count % 10 == 0:
        if direction == 'drive_vector':
            print(f"[{sid[:8]}] Move command: map=({linear_x:+.2f},{linear_y:+.2f}) angular={angular:+.2f} - count={next_count}/{RATE_LIMIT_CONFIG['max_commands_per_second']}")
        else:
            print(f"[{sid[:8]}] Move command: {direction} (speed={speed:.2f}) - count={next_count}/{RATE_LIMIT_CONFIG['max_commands_per_second']}")

    # Execute robot command
    try:
        result = await remote_core.move(
            direction, speed, angular, linear_x, linear_y, sequence=sequence,
        )

        # Update client state after successful command
        update_client_state(sid, timestamp=current_time)

        # Get current robot state
        robot_state = _decorate_robot_state(await remote_core.get_state())

        # Calculate latency
        latency = (current_time * 1000) - client_timestamp if client_timestamp else 0

        # Send success response with detailed metrics
        response_status = result.get('status', 'executed')
        transport_status = result.get('transport_status')
        if direction == 'drive_vector' and response_status in {'success', 'executed', 'accepted'}:
            # RemoteCore confirms only that ZeroMQ accepted the bytes. Host receipt
            # and actuator application are traced asynchronously by sequence.
            response_status = 'queued_to_zmq'
            transport_status = transport_status or 'queued_to_zmq'
        await sio.emit('command_received', {
            'type': 'move', 'direction': direction, 'speed': speed,
            'status': response_status, 'transport_status': transport_status, 'sequence': sequence,
            'speed_limited': speed != requested_speed,
            'robot_state': robot_state,
            'metrics': {
                'latency': latency,
                'commands_in_window': client_state['command_count'],
                'max_commands': RATE_LIMIT_CONFIG['max_commands_per_second'],
                'throttle_violations': client_state['throttle_violations']
            },
            'client_timestamp': client_timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)
        if direction == 'drive_vector':
            print(
                f"[navigation-command] queued_to_zmq sequence={sequence} "
                f"requested=({linear_x:+.2f},{linear_y:+.2f}) angular={angular:+.2f} "
                f"state_age={nav_state.get('state_age')} scan_healthy={((nav_state.get('obstacle_scan_status') or {}).get('healthy'))} "
                f"scan_age_ms={((nav_state.get('obstacle_scan_status') or {}).get('age_ms'))}"
            )

    except Exception as e:
        await sio.emit('command_received', {
            'type': 'move',
            'status': 'error',
            'sequence': sequence,
            'message': f'Command execution failed: {str(e)}',
            'client_timestamp': timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)
        if direction == 'drive_vector':
            print(f"[navigation-command] rejected sequence={sequence} reason={e}")

@sio.event
async def start_video_stream(sid):
    """Start video streaming"""
    print(f"Client {sid} requested start video stream")
    
    if sid in video_manager.stream_tasks:
        task = video_manager.stream_tasks[sid]
        if not task.cancelled():
            task.cancel()
        del video_manager.stream_tasks[sid]
    
    result = await video_manager.start_stream()
    await sio.emit('stream_status', result, to=sid)
    
    task = asyncio.create_task(video_manager.stream_frames(sio, sid))
    video_manager.stream_tasks[sid] = task

@sio.event
async def stop_video_stream(sid):
    """Stop video streaming"""
    print(f"Client {sid} requested stop video stream")
    result = await video_manager.stop_stream(sid)
    await sio.emit('stream_status', result, to=sid)


@sio.event
async def reset_camera(sid):
    """Reset camera event handler"""
    print(f"Client {sid} requested camera reset")

    try:
        result = await remote_core.reset_camera()
        await sio.emit('camera_action_result', {
            'action': 'reset',
            **result
        }, to=sid)
        print(f"Camera reset result: {result['status']}")
    except Exception as e:
        await sio.emit('camera_action_result', {
            'action': 'reset',
            'status': 'error',
            'message': f'Camera reset failed: {str(e)}'
        }, to=sid)

@sio.event
async def set_camera_position(sid, data):
    """Set camera position event handler"""
    print(f"Client {sid} requested set camera position")

    position = data.get('position')
    target = data.get('target')

    if not position:
        await sio.emit('camera_action_result', {
            'action': 'set_position',
            'status': 'error',
            'message': 'Position is required'
        }, to=sid)
        return

    try:
        result = await remote_core.set_camera_position(position, target)
        await sio.emit('camera_action_result', {
            'action': 'set_position',
            **result
        }, to=sid)
        print(f"Camera position set result: {result['status']}")
    except Exception as e:
        await sio.emit('camera_action_result', {
            'action': 'set_position',
            'status': 'error',
            'message': f'Set camera position failed: {str(e)}'
        }, to=sid)

@sio.event
async def get_camera_info(sid):
    """Get camera info event handler"""
    print(f"Client {sid} requested camera info")

    try:
        # Return basic camera info for simplified architecture
        camera_info = {
            'camera_id': 0,
            'position': [2.0, 2.0, 2.0],
            'target': [0.0, 0.0, 0.0],
            'frame_size': {'width': config.video_width, 'height': config.video_height},
            'fps': config.video_fps,
            'quality': config.video_quality
        }
        await sio.emit('camera_info_result', {
            'status': 'success',
            'camera_info': camera_info
        }, to=sid)
    except Exception as e:
        await sio.emit('camera_info_result', {
            'status': 'error',
            'message': f'Get camera info failed: {str(e)}'
        }, to=sid)

if __name__ == "__main__":
    uvicorn.run(
        socket_app,
        host=config.ui_host,
        port=config.ui_port,
        reload=False,  # Disable reload for simplified architecture
        log_level="info"
    )

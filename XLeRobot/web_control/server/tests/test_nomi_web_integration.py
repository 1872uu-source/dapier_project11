import asyncio
import sys
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
import main
from core.config import ServerConfig
from core.nomi_bridge import NomiBridge


class MockBridge:
    available = True
    agent_connected = True

    def __init__(self):
        self.commands = []
        self.cancelled = []
        self.profiles = []
        self.switch_result = True
        self.cancel_result = True

    def send_command(self, text, request_id):
        self.commands.append((text, request_id))
        return True

    def switch_model(self, profile):
        self.profiles.append(profile)
        return self.switch_result

    def cancel_task(self, task_id):
        self.cancelled.append(task_id)
        return self.cancel_result

    def publish_navigation_result(self, payload):
        self.navigation_result = payload
        return True


class NomiWebIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = MockBridge()
        self.old_bridge = main.nomi_bridge
        self.old_emit = main.sio.emit
        self.old_recent_task_id = main.nomi_recent_task_id
        main.nomi_bridge = self.bridge
        main.sio.emit = AsyncMock()
        main.nomi_task_owners.clear()
        main.nomi_task_payloads.clear()
        main.nomi_navigation_owners.clear()
        main.nomi_active_task_id = None
        main.nomi_recent_task_id = None
        main.nomi_pending_model_switch = None

    def tearDown(self):
        main.nomi_bridge = self.old_bridge
        main.sio.emit = self.old_emit
        main.nomi_task_owners.clear()
        main.nomi_task_payloads.clear()
        main.nomi_navigation_owners.clear()
        main.nomi_active_task_id = None
        main.nomi_recent_task_id = self.old_recent_task_id
        main.nomi_pending_model_switch = None

    async def test_movement_chat_goes_only_to_harness_with_stable_request_id(self):
        remote_move = AsyncMock()
        old_move = main.remote_core.move
        main.remote_core.move = remote_move
        try:
            await main.nomi_command('browser-1', {'text': '앞으로 이동해', 'request_id': 'task-1'})
        finally:
            main.remote_core.move = old_move
        self.assertEqual(self.bridge.commands, [('앞으로 이동해', 'task-1')])
        remote_move.assert_not_awaited()
        self.assertEqual(main.nomi_task_owners['task-1'], 'browser-1')

    async def test_manual_move_event_still_uses_the_existing_control_path(self):
        remote = main.remote_core
        old_connected, old_move, old_stop, old_state = remote.connected, remote.move, remote.stop, remote.get_state
        mock_move = AsyncMock(return_value={'status': 'success'})
        remote.connected = True
        remote.move = mock_move
        remote.get_state = AsyncMock(return_value={'position': {'x': 0, 'y': 0}})
        main.client_states['browser-manual'] = main._init_client_state()
        try:
            await main.move_command('browser-manual', {
                'direction': 'forward', 'speed': 0.4, 'sequence': 1,
                'angular': 0, 'linear_x': 0, 'linear_y': 0,
            })
        finally:
            remote.connected, remote.move, remote.stop, remote.get_state = old_connected, old_move, old_stop, old_state
            main.client_states.pop('browser-manual', None)
        mock_move.assert_awaited_once_with('forward', 0.4, 0.0, 0.0, 0.0, sequence=1)

    async def test_command_received_state_matches_snapshot_safety_decoration(self):
        remote = main.remote_core
        old_connected, old_move, old_stop, old_state = remote.connected, remote.move, remote.stop, remote.get_state
        old_mode, old_flag, old_robot_type = main.NOMI_MOCK_DEV, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type
        raw_state = {'robot_type': 'mujoco', 'host_connected': True}
        remote.connected = True
        remote.move = AsyncMock(return_value={'status': 'success'})
        remote.stop = AsyncMock(return_value={'status': 'success'})
        remote.get_state = AsyncMock(return_value=raw_state)
        cases = [
            ('enabled', False, True, 'mujoco', True, False),
            ('mock', True, True, 'mujoco', False, True),
            ('non-mujoco', False, True, 'xlerobot', False, False),
            ('flag-off', False, False, 'mujoco', False, False),
        ]
        try:
            for name, mock_mode, nav_enabled, robot_type, expected_nav, expected_mock in cases:
                with self.subTest(profile=name):
                    main.NOMI_MOCK_DEV = mock_mode
                    main.NOMI_MUJOCO_NAV_ENABLED = nav_enabled
                    main.config.robot_type = robot_type
                    sid = f'browser-state-{name}'
                    main.client_states[sid] = main._init_client_state()
                    direction = 'stop' if name == 'enabled' else 'forward'
                    await main.move_command(sid, {
                        'direction': direction, 'speed': 0.2, 'sequence': 1,
                        'angular': 0, 'linear_x': 0, 'linear_y': 0,
                    })
                    payload = next(
                        call.args[1] for call in reversed(main.sio.emit.await_args_list)
                        if call.args[0] == 'command_received' and call.kwargs.get('to') == sid
                    )
                    command_state = payload['robot_state']
                    snapshot_state = main._decorate_robot_state(raw_state)
                    self.assertEqual(command_state, snapshot_state)
                    self.assertIs(command_state['navigation_execution_enabled'], expected_nav)
                    self.assertIs(command_state['nomi_mock_mode'], expected_mock)
                    main.client_states.pop(sid, None)
        finally:
            remote.connected, remote.move, remote.stop, remote.get_state = old_connected, old_move, old_stop, old_state
            main.NOMI_MOCK_DEV, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type = old_mode, old_flag, old_robot_type

    async def test_autonomous_drive_vector_requires_explicit_mujoco_enablement(self):
        remote = main.remote_core
        old_connected, old_flag, old_move = remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, remote.move
        move = AsyncMock(return_value={'status': 'success'})
        remote.connected = True
        remote.move = move
        main.NOMI_MUJOCO_NAV_ENABLED = False
        try:
            await main.move_command('browser-nav-disabled', {
                'direction': 'drive_vector', 'linear_x': 0.2, 'linear_y': 0.0,
                'angular': 0.0, 'speed': 0.2, 'sequence': 1,
            })
        finally:
            remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, remote.move = old_connected, old_flag, old_move
        move.assert_not_awaited()
        main.sio.emit.assert_any_await('command_received', {
            'type': 'move', 'direction': 'drive_vector', 'speed': 0.2,
            'status': 'error', 'sequence': 1,
            'client_timestamp': unittest.mock.ANY,
            'server_timestamp': unittest.mock.ANY,
            'speed_limited': False,
            'message': 'MuJoCo 자동 주행이 명시적으로 활성화되지 않아 이동 명령을 차단했습니다.',
        }, to='browser-nav-disabled')

    async def test_autonomous_drive_vector_remains_blocked_in_mock_and_non_mujoco_modes(self):
        remote = main.remote_core
        old_connected, old_flag, old_mode, old_robot_type = (
            remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.NOMI_MOCK_DEV, main.config.robot_type
        )
        old_move = remote.move
        remote.connected = True
        main.NOMI_MUJOCO_NAV_ENABLED = True
        move = AsyncMock(return_value={'status': 'success'})
        remote.move = move
        cases = [
            ('mock', True, 'mujoco'),
            ('non-mujoco', False, 'xlerobot'),
        ]
        try:
            for name, mock_mode, robot_type in cases:
                with self.subTest(profile=name):
                    main.NOMI_MOCK_DEV = mock_mode
                    main.config.robot_type = robot_type
                    sid = f'browser-nav-{name}'
                    await main.move_command(sid, {
                        'direction': 'drive_vector', 'linear_x': 0.2, 'linear_y': 0.0,
                        'angular': 0.0, 'speed': 0.2, 'sequence': 1,
                    })
                    move.assert_not_awaited()
                    payload = next(
                        call.args[1] for call in reversed(main.sio.emit.await_args_list)
                        if call.args[0] == 'command_received' and call.kwargs.get('to') == sid
                    )
                    self.assertEqual(payload['status'], 'error')
                    self.assertIn('명시적으로 활성화되지 않아', payload['message'])
        finally:
            remote.connected, remote.move = old_connected, old_move
            main.NOMI_MUJOCO_NAV_ENABLED, main.NOMI_MOCK_DEV, main.config.robot_type = old_flag, old_mode, old_robot_type

    async def test_autonomous_drive_vector_requires_fresh_state_and_range_scan(self):
        remote = main.remote_core
        old_connected, old_flag, old_robot_type = remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type
        old_move, old_state = remote.move, remote.get_state
        remote.connected = True
        main.NOMI_MUJOCO_NAV_ENABLED = True
        main.config.robot_type = 'mujoco'
        remote.get_state = AsyncMock(return_value={
            'robot_type': 'mujoco', 'host_connected': True, 'state_age': 0.1,
            'obstacle_scan_status': {'healthy': True, 'age_ms': 2000}, 'obstacle_scan': [],
        })
        move = AsyncMock(return_value={'status': 'success'})
        remote.move = move
        try:
            await main.move_command('browser-nav-stale', {
                'direction': 'drive_vector', 'linear_x': 0.2, 'linear_y': 0.0,
                'angular': 0.0, 'speed': 0.2, 'sequence': 1,
            })
        finally:
            remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type = old_connected, old_flag, old_robot_type
            remote.move, remote.get_state = old_move, old_state
        move.assert_not_awaited()
        self.assertTrue(any('최신 MuJoCo 위치 또는 거리 센서 데이터' in str(call) for call in main.sio.emit.await_args_list))

    async def test_autonomous_drive_vector_passes_only_with_explicit_mode_and_fresh_sensors(self):
        remote = main.remote_core
        sid = 'browser-nav-safe'
        old_connected, old_flag, old_robot_type = remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type
        old_move, old_state = remote.move, remote.get_state
        remote.connected = True
        main.NOMI_MUJOCO_NAV_ENABLED = True
        main.config.robot_type = 'mujoco'
        state = {
            'robot_type': 'mujoco', 'host_connected': True, 'state_age': 0.1,
            'position': {'x': 0.0, 'y': 0.0},
            'obstacle_scan_status': {'healthy': True, 'age_ms': 100}, 'obstacle_scan': [],
        }
        remote.get_state = AsyncMock(return_value=state)
        move = AsyncMock(return_value={'status': 'success'})
        remote.move = move
        main.client_states[sid] = main._init_client_state()
        try:
            await main.move_command(sid, {
                'direction': 'drive_vector', 'linear_x': 0.2, 'linear_y': 0.0,
                'angular': 0.0, 'speed': 0.2, 'sequence': 1,
            })
        finally:
            remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type = old_connected, old_flag, old_robot_type
            remote.move, remote.get_state = old_move, old_state
            main.client_states.pop(sid, None)
        move.assert_awaited_once_with('drive_vector', 0.2, 0.0, 0.2, 0.0, sequence=1)
        payload = next(
            call.args[1] for call in reversed(main.sio.emit.await_args_list)
            if call.args[0] == 'command_received' and call.kwargs.get('to') == sid
        )
        self.assertEqual(payload['status'], 'queued_to_zmq')
        self.assertEqual(payload['transport_status'], 'queued_to_zmq')

    async def test_autonomous_drive_vector_is_rejected_before_leaving_map_clearance(self):
        remote = main.remote_core
        old_connected, old_flag, old_robot_type = remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type
        old_move, old_state = remote.move, remote.get_state
        remote.connected = True
        main.NOMI_MUJOCO_NAV_ENABLED = True
        main.config.robot_type = 'mujoco'
        remote.get_state = AsyncMock(return_value={
            'robot_type': 'mujoco', 'host_connected': True, 'state_age': 0.1,
            'position': {'x': 4.0, 'y': 0.0},
            'obstacle_scan_status': {'healthy': True, 'age_ms': 100}, 'obstacle_scan': [],
        })
        move = AsyncMock(return_value={'status': 'success'})
        remote.move = move
        try:
            await main.move_command('browser-nav-boundary', {
                'direction': 'drive_vector', 'linear_x': 0.5, 'linear_y': 0.0,
                'angular': 0.0, 'speed': 0.5, 'sequence': 1,
            })
        finally:
            remote.connected, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type = old_connected, old_flag, old_robot_type
            remote.move, remote.get_state = old_move, old_state
        move.assert_not_awaited()
        payload = next(
            call.args[1] for call in reversed(main.sio.emit.await_args_list)
            if call.args[0] == 'command_received' and call.kwargs.get('to') == 'browser-nav-boundary'
        )
        self.assertEqual(payload['status'], 'error')
        self.assertIn('지도 경계를 벗어날 수 있어', payload['message'])

    async def test_duplicate_request_id_is_not_published_twice(self):
        payload = {'text': '분홍색 수건을 집어 줘', 'request_id': 'task-dup'}
        await main.nomi_command('browser-1', payload)
        await main.nomi_command('browser-1', payload)
        self.assertEqual(len(self.bridge.commands), 1)
        main.sio.emit.assert_any_await('nomi_command_received', {'status': 'duplicate', 'request_id': 'task-dup'}, to='browser-1')

    async def test_concurrent_second_browser_is_rejected_without_cross_session_routing(self):
        await main.nomi_command('browser-1', {'text': '현재 로봇 상태 알려줘', 'request_id': 'task-owner'})
        await main.nomi_command('browser-2', {'text': '서울 날씨 알려줘', 'request_id': 'task-other'})
        self.assertEqual(self.bridge.commands, [('현재 로봇 상태 알려줘', 'task-owner')])
        self.assertEqual(main.nomi_task_owners['task-owner'], 'browser-1')
        self.assertNotIn('task-other', main.nomi_task_owners)
        main.sio.emit.assert_any_await('nomi_response', {
            'status': 'error', 'request_id': 'task-other',
            'message': '다른 사용자의 NOMI 작업이 진행 중입니다. 작업 ID: task-owner',
        }, to='browser-2')

    async def test_other_browser_cannot_cancel_active_task(self):
        await main.nomi_command('browser-1', {'text': '현재 로봇 상태 알려줘', 'request_id': 'task-private'})
        await main.nomi_task_cancel('browser-2', {'task_id': 'task-private'})
        self.assertEqual(self.bridge.cancelled, [])
        main.sio.emit.assert_any_await('nomi_cancel_result', {
            'status': 'error', 'task_id': 'task-private',
            'message': '이 연결에서 취소할 수 있는 작업을 찾지 못했습니다.',
        }, to='browser-2')

    async def test_ros_bridge_without_agent_does_not_accept_ai_command(self):
        self.bridge.agent_connected = False
        await main.nomi_command('browser-1', {'text': '앞으로 이동해', 'request_id': 'task-offline'})
        self.assertEqual(self.bridge.commands, [])
        self.assertNotIn('task-offline', main.nomi_task_owners)
        main.sio.emit.assert_any_await('nomi_response', {
            'status': 'error',
            'request_id': 'task-offline',
            'message': 'NOMI ROS 2 브리지에 연결되지 않아 Harness에 명령을 전달하지 못했습니다.',
        }, to='browser-1')

    async def test_qwen35_profile_changes_ui_only_after_agent_success(self):
        await main.nomi_model_switch('browser-1', {'profile': 'qwen35_single', 'request_id': 'switch-1'})
        self.assertEqual(self.bridge.profiles, ['qwen35_single'])
        self.assertEqual(main.nomi_pending_model_switch['profile'], 'qwen35_single')
        await main._publish_nomi_model_status('qwen35_single')
        main.sio.emit.assert_any_await('nomi_model_status', {
            'status': 'success', 'profile': 'qwen35_single', 'request_id': 'switch-1',
            'label': 'Qwen3.5 9B (Single)',
        }, to='browser-1')
        self.assertIsNone(main.nomi_pending_model_switch)

    async def test_model_switch_failure_does_not_report_success(self):
        self.bridge.switch_result = False
        await main.nomi_model_switch('browser-1', {'profile': 'qwen35_single', 'request_id': 'switch-fail'})
        self.assertIsNone(main.nomi_pending_model_switch)
        self.assertFalse(any(call.args[0] == 'nomi_model_switch_sent' for call in main.sio.emit.await_args_list))

    async def test_task_cancel_uses_harness_cancel_topic_not_motion_or_estop(self):
        main.nomi_task_owners['task-cancel'] = 'browser-1'
        main.nomi_task_payloads['task-cancel'] = {'status': 'RUNNING'}
        main.nomi_active_task_id = 'task-cancel'
        await main.nomi_task_cancel('browser-1', {'task_id': 'task-cancel'})
        self.assertEqual(self.bridge.cancelled, ['task-cancel'])
        main.sio.emit.assert_any_await('nomi_cancel_result', {'status': 'accepted', 'task_id': 'task-cancel'}, to='browser-1')

    async def test_task_status_is_forwarded_only_to_originating_browser(self):
        main.nomi_task_owners['task-status'] = 'browser-1'
        payload = {'task_id': 'task-status', 'status': 'NEEDS_CLARIFICATION', 'response_text': '어떤 물체를 말하나요?'}
        await main._publish_nomi_task_status(payload)
        main.sio.emit.assert_awaited_once_with('nomi_task_status', payload, to='browser-1')

    async def test_harness_navigation_request_routes_to_originating_browser_by_saved_name(self):
        main.nomi_task_owners['nav-task'] = 'browser-1'
        main.nomi_active_task_id = 'nav-task'
        await main._publish_nomi_navigation_request({'name': '집', 'request_id': 'nav-request-1'})
        main.sio.emit.assert_awaited_once_with('nomi_navigation_request', {
            'destination': 'home', 'name': '집', 'request_id': 'nav-request-1',
        }, to='browser-1')
        self.assertEqual(main.nomi_navigation_owners['nav-request-1'], 'browser-1')

    async def test_navigation_request_without_active_browser_is_dropped(self):
        await main._publish_nomi_navigation_request({'name': '충전소', 'request_id': 'nav-unowned'})
        main.sio.emit.assert_not_awaited()

    async def test_navigation_request_survives_task_status_delivery_race(self):
        main.nomi_task_owners['nav-race'] = 'browser-1'
        main.nomi_recent_task_id = 'nav-race'
        # Harness has already published SUCCEEDED, clearing the active slot.
        main.nomi_active_task_id = None
        await main._publish_nomi_navigation_request({'name': '거실', 'request_id': 'nav-request-race'})
        main.sio.emit.assert_awaited_once_with('nomi_navigation_request', {
            'destination': 'saved', 'name': '거실', 'request_id': 'nav-request-race',
        }, to='browser-1')

    async def test_navigation_success_requires_verified_arrival_and_is_forwarded_to_agent(self):
        main.nomi_navigation_owners['nav-result-1'] = 'browser-1'
        await main.nomi_navigation_result('browser-1', {
            'request_id': 'nav-result-1', 'status': 'SUCCEEDED', 'completion_verified': True,
            'position': {'x': 1.0, 'y': 2.0}, 'distance_m': 0.2, 'message': '도착',
        })
        self.assertEqual(self.bridge.navigation_result, {
            'request_id': 'nav-result-1', 'status': 'SUCCEEDED', 'message': '도착',
            'completion_verified': True, 'position': {'x': 1.0, 'y': 2.0}, 'distance_m': 0.2,
        })
        main.sio.emit.assert_awaited_with('nomi_navigation_result_ack', {
            'status': 'forwarded', 'request_id': 'nav-result-1',
        }, to='browser-1')

    async def test_navigation_success_without_close_pose_is_rejected(self):
        main.nomi_navigation_owners['nav-result-far'] = 'browser-1'
        await main.nomi_navigation_result('browser-1', {
            'request_id': 'nav-result-far', 'status': 'SUCCEEDED', 'completion_verified': True,
            'position': {'x': 1.0, 'y': 2.0}, 'distance_m': 0.8,
        })
        self.assertFalse(hasattr(self.bridge, 'navigation_result'))
        main.sio.emit.assert_awaited_with('nomi_navigation_result_ack', {
            'status': 'error', 'request_id': 'nav-result-far',
            'message': '현재 위치가 목적지 0.3m 이내라는 도착 확인이 없어 완료 결과를 거부했습니다.',
        }, to='browser-1')

    async def test_mock_dev_startup_never_connects_remote_robot_core(self):
        old_mode = main.NOMI_MOCK_DEV
        old_bridge_class = main.NomiBridge
        old_bridge = main.nomi_bridge
        old_loop = main.main_event_loop
        old_connected = main.remote_core.connected
        old_connect = main.remote_core.connect

        class SafeBridge:
            def __init__(self, **_kwargs):
                self.available = True
                self.agent_connected = False

            def start(self):
                return True

        main.NOMI_MOCK_DEV = True
        main.NomiBridge = SafeBridge
        main.remote_core.connect = AsyncMock(side_effect=AssertionError('remote connect must be blocked'))
        main.remote_core.connected = True
        try:
            await main.startup_event()
            main.remote_core.connect.assert_not_awaited()
            self.assertFalse(main.remote_core.connected)
        finally:
            main.NOMI_MOCK_DEV = old_mode
            main.NomiBridge = old_bridge_class
            main.nomi_bridge = old_bridge
            main.main_event_loop = old_loop
            main.remote_core.connected = old_connected
            main.remote_core.connect = old_connect

    async def test_remote_connection_monitor_retries_until_host_and_telemetry_are_available(self):
        remote = main.remote_core
        old_connected = remote.connected
        old_last_state_received = remote.last_state_received
        old_connect, old_get_state, old_disconnect = remote.connect, remote.get_state, remote.disconnect
        old_sleep = main.asyncio.sleep
        recovered = asyncio.Event()
        attempts = 0

        async def connect_after_host_starts():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                remote.connected = False
                remote.last_state_received = 0.0
                return False
            remote.connected = True
            remote.last_state_received = main.time.time()
            return True

        async def get_state():
            return {'robot_type': 'mujoco', 'host_connected': remote.connected}

        async def emit(event, payload):
            if event == 'robot_state_snapshot' and payload['state']['host_connected']:
                recovered.set()

        async def cooperative_sleep(_seconds):
            await old_sleep(0)

        remote.connected = False
        remote.last_state_received = 0.0
        remote.connect = connect_after_host_starts
        remote.get_state = get_state
        remote.disconnect = AsyncMock()
        main.sio.emit = emit
        main.asyncio.sleep = cooperative_sleep
        task = asyncio.create_task(main._maintain_remote_connection())
        try:
            await asyncio.wait_for(recovered.wait(), timeout=1.0)
            self.assertGreaterEqual(attempts, 2, 'the monitor must retry after the initial host connection fails')
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            remote.connected = old_connected
            remote.last_state_received = old_last_state_received
            remote.connect, remote.get_state, remote.disconnect = old_connect, old_get_state, old_disconnect
            main.sio.emit = self.old_emit
            main.asyncio.sleep = old_sleep

    async def test_navigation_execution_state_requires_explicit_mujoco_and_non_mock_mode(self):
        old_mode, old_flag, old_robot_type = main.NOMI_MOCK_DEV, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type
        main.NOMI_MUJOCO_NAV_ENABLED = True
        try:
            main.NOMI_MOCK_DEV = True
            main.config.robot_type = 'mujoco'
            self.assertFalse(main._decorate_robot_state({})['navigation_execution_enabled'])
            main.NOMI_MOCK_DEV = False
            self.assertTrue(main._decorate_robot_state({})['navigation_execution_enabled'])
            main.config.robot_type = 'xlerobot'
            self.assertFalse(main._decorate_robot_state({})['navigation_execution_enabled'])
        finally:
            main.NOMI_MOCK_DEV, main.NOMI_MUJOCO_NAV_ENABLED, main.config.robot_type = old_mode, old_flag, old_robot_type

    async def test_explicit_shell_ros_domain_and_mock_mode_override_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / '.env'
            env_path.write_text('ROS_DOMAIN_ID=0\nNOMI_MOCK_DEV=0\n', encoding='utf-8')
            with patch.dict(os.environ, {'ROS_DOMAIN_ID': '222', 'NOMI_MOCK_DEV': '1'}):
                ServerConfig._load_env_file(str(env_path))
                self.assertEqual(os.environ['ROS_DOMAIN_ID'], '222')
                self.assertEqual(os.environ['NOMI_MOCK_DEV'], '1')

    async def test_bridge_publishes_correlated_command_and_cancel_payloads(self):
        class FakeNode:
            def __init__(self):
                self.published = []

            def publish(self, topic, value):
                self.published.append((topic, value))

        bridge = NomiBridge(None, lambda _value: None)
        bridge.available = True
        bridge.agent_connected = True
        bridge._node = FakeNode()
        self.assertTrue(bridge.send_command('앞으로 이동해', 'web-task-1'))
        self.assertTrue(bridge.cancel_task('web-task-1'))
        self.assertEqual(bridge._node.published[0], (
            'command', '{"request_id": "web-task-1", "text": "앞으로 이동해"}',
        ))
        self.assertEqual(bridge._node.published[1], (
            'cancel', '{"task_id": "web-task-1"}',
        ))

    async def test_bridge_accepts_only_bounded_navigation_name_payloads(self):
        calls = []
        cancelled = []
        bridge = NomiBridge(None, lambda _value: None, on_navigation_request=calls.append,
                             on_navigation_cancel=cancelled.append)
        bridge._navigation_request_callback(type('Message', (), {'data': '{"name": "집", "request_id": "nav-1"}'})())
        bridge._navigation_request_callback(type('Message', (), {'data': '{"name": "  "}'})())
        bridge._navigation_request_callback(type('Message', (), {'data': '{bad json'})())
        bridge._navigation_request_callback(type('Message', (), {'data': '{"name": "x", "request_id": "nav-2"}'})())
        self.assertEqual(calls, [
            {'name': '집', 'request_id': 'nav-1'},
            {'name': 'x', 'request_id': 'nav-2'},
        ])
        bridge._navigation_cancel_callback(type('Message', (), {'data': '{"request_id": "nav-1"}'})())
        bridge._navigation_cancel_callback(type('Message', (), {'data': '{"request_id": 3}'})())
        self.assertEqual(cancelled, ['nav-1'])


if __name__ == '__main__':
    unittest.main()

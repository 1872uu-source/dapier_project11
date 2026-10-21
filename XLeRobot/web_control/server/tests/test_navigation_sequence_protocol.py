import asyncio
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest

from core.config import ServerConfig
from core.protocol import RobotProtocol, ResponseType
from core.remote_core import RemoteCore


class NavigationSequenceProtocolTests(unittest.TestCase):
    def test_move_sequence_is_optional_and_preserved(self):
        with_sequence = json.loads(RobotProtocol.encode_move_command(
            'drive_vector', 0.4, 0.1, 0.3, -0.2, sequence=57,
        ))
        without_sequence = json.loads(RobotProtocol.encode_move_command(
            'forward', 0.4,
        ))

        self.assertEqual(with_sequence['command'], 'move')
        self.assertEqual(with_sequence['data']['sequence'], 57)
        self.assertEqual(with_sequence['data']['linear_x'], 0.3)
        self.assertNotIn('sequence', without_sequence['data'])


class _OneAckSocket:
    def __init__(self, owner, response):
        self.owner = owner
        self.response = response
        self.received = False

    async def recv(self):
        if not self.received:
            self.received = True
            return self.response
        self.owner.connected = False
        raise asyncio.TimeoutError()


class NavigationHostAckTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_acknowledgement_is_correlated_and_logged(self):
        core = RemoteCore(ServerConfig(robot_type='mujoco'))
        core.connected = True
        core.data_socket = _OneAckSocket(core, RobotProtocol.encode_response(
            ResponseType.SUCCESS,
            {'command': 'move', 'sequence': 91, 'host_status': 'target_applied'},
        ))
        output = StringIO()
        try:
            with redirect_stdout(output):
                await core._data_receiver_loop()
        finally:
            core.context.term()
        self.assertIn('host_ack sequence=91 host_status=target_applied', output.getvalue())


if __name__ == '__main__':
    unittest.main()

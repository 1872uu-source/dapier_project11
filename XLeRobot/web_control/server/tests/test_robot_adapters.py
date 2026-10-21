"""Adapter contracts must not enable DAPier hardware during integration prep."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.robot_adapters import DapierAdapter, MockRobotAdapter, MujocoAdapter, create_adapter


class RobotAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_dapier_adapter_is_always_disabled_and_never_claims_dispatch(self):
        adapter = DapierAdapter(enabled=True, base_url="http://127.0.0.1:8081")
        self.assertFalse(adapter.enabled)
        outcomes = [
            await adapter.get_state(),
            await adapter.navigate_to("집"),
            await adapter.cancel_navigation(),
            await adapter.stop(),
            await adapter.pick_object("컵"),
            await adapter.place_object("테이블"),
            await adapter.drive(direction="forward", speed=0.1),
        ]
        for outcome in outcomes:
            self.assertFalse(outcome["success"])
            self.assertEqual(outcome["data"]["error_code"], "NOT_IMPLEMENTED")
            self.assertFalse(outcome["data"]["command_dispatched"])
            self.assertFalse(outcome["data"]["completion_verified"])

    async def test_mock_adapter_records_calls_and_only_reports_mock_completion(self):
        adapter = MockRobotAdapter()
        nav = await adapter.navigate_to("테이블 2")
        state = await adapter.get_state()
        self.assertTrue(nav["success"])
        self.assertTrue(nav["data"]["completion_verified"])
        self.assertEqual(state["data"]["state"]["connection"], "mock")
        self.assertEqual([call["action"] for call in adapter.calls], ["navigate_to", "get_state"])

    async def test_mujoco_adapter_forwards_only_to_injected_remote_core(self):
        core = SimpleNamespace(
            config=SimpleNamespace(robot_type="mujoco"),
            get_state=AsyncMock(return_value={"position": {"x": 1.0, "y": 2.0}}),
            move=AsyncMock(return_value={"status": "success", "direction": "stop"}),
            stop=AsyncMock(return_value={"status": "success"}),
        )
        adapter = MujocoAdapter(core)
        state = await adapter.get_state()
        self.assertEqual(state["data"]["state"]["position"]["x"], 1.0)
        moved = await adapter.drive(direction="forward", speed=0.2)
        self.assertTrue(moved["success"])
        self.assertFalse(moved["data"]["completion_verified"])
        core.move.assert_awaited_once_with("forward", 0.2, 0.0, 0.0, 0.0)

    async def test_mujoco_adapter_rejects_wrong_robot_type(self):
        with self.assertRaises(ValueError):
            MujocoAdapter(SimpleNamespace(config=SimpleNamespace(robot_type="xlerobot")))

    async def test_factory_requires_explicit_adapter_name(self):
        self.assertIsInstance(create_adapter("dapier"), DapierAdapter)
        self.assertIsInstance(create_adapter("mock"), MockRobotAdapter)
        with self.assertRaises(ValueError):
            create_adapter("unknown")


if __name__ == "__main__":
    unittest.main()

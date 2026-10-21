"""Run the production NOMI node/Harness with MockRobot-only skills.

This entry point is for the long-running local development stack. It refuses
ROS domains other than 222 and patches AgentNode's registry constructor before
the node can create any real robot skills.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AGENT_SRC = Path.home() / "ros2_ws" / "src" / "nomi_agent"
AGENT_TESTS = AGENT_SRC / "tests"
sys.path.insert(0, str(AGENT_SRC))
sys.path.insert(0, str(AGENT_TESTS))

DOMAIN_ID = int(os.environ.get("ROS_DOMAIN_ID", "-1"))
if DOMAIN_ID != 222:
    raise SystemExit(f"Refusing to start Mock Agent on ROS_DOMAIN_ID={DOMAIN_ID}; required safe domain is 222")
if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
    raise SystemExit("Refusing to start: ROS_AUTOMATIC_DISCOVERY_RANGE must be LOCALHOST")
if os.environ.get("NOMI_MODEL_PROFILE") != "qwen35_single":
    raise SystemExit("Refusing to start: NOMI_MODEL_PROFILE must be qwen35_single")

from mock_adapters import MockRobot
from nomi_agent.tool_registry import ToolRegistry as RegistryWithMockSkills


class MockOnlyToolRegistry:
    """Production schemas, SafetyGuard, and dispatch with only MockRobot skills."""

    def __init__(self, node=None):
        self.robot = MockRobot()
        self.delegate = RegistryWithMockSkills(skills=self.robot.as_registry_skills())
        self.skills = self.delegate.skills
        self.node = None
        skill_types = {type(skill).__name__ for skill in self.skills.values()}
        if not skill_types or any(not name.startswith("Mock") for name in skill_types):
            raise RuntimeError(f"Non-mock skill found in registry: {sorted(skill_types)}")

    def __getattr__(self, name):
        return getattr(self.delegate, name)


def main() -> int:
    import rclpy
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
    import nomi_agent.agent_node as agent_node_module

    # Patch before constructing the node. No production skill constructor runs.
    agent_node_module.ToolRegistry = MockOnlyToolRegistry
    rclpy.init(args=None, domain_id=DOMAIN_ID)
    node = None
    executor = None
    try:
        node = agent_node_module.NomiAgentNode()
        if not isinstance(node.tool_registry, MockOnlyToolRegistry):
            raise RuntimeError("Agent node did not receive MockOnlyToolRegistry")
        if node.llm_client.profile != "qwen35_single":
            raise RuntimeError(f"Unexpected active model profile: {node.llm_client.profile}")
        node.get_logger().info(
            "SAFE MOCK DEV: MockRobot only; no real robot skills; "
            f"ROS_DOMAIN_ID={DOMAIN_ID}; model={node.llm_client.profile}"
        )
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            # This dispatches only to the mock registry created above.
            try:
                node.harness.cancel_active()
                node.tool_registry.emergency_stop()
            finally:
                node.destroy_node()
        if executor is not None:
            executor.shutdown(timeout_sec=2.0)
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Real Ollama + real NOMI Harness + MockRobot over the web Socket.IO route.

Run only from a sourced ROS 2/Jazzy shell. This harness uses ROS_DOMAIN_ID=222
and localhost-only ROS discovery, replaces AgentNode's ToolRegistry constructor before
creating the node, and patches RemoteCore.connect to fail closed. No robot or
MuJoCo host is started and no motion/control topics are published.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import socket
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1]
AGENT_SRC = Path.home() / "ros2_ws" / "src" / "nomi_agent"
AGENT_TESTS = AGENT_SRC / "tests"
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(AGENT_SRC))
sys.path.insert(0, str(AGENT_TESTS))

# These values are set before importing/initializing rclpy.
ROS_DOMAIN = int(os.getenv("NOMI_E2E_ROS_DOMAIN", "222"))
os.environ["ROS_DOMAIN_ID"] = str(ROS_DOMAIN)
os.environ["ROS_AUTOMATIC_DISCOVERY_RANGE"] = "LOCALHOST"
os.environ["NOMI_MODEL_PROFILE"] = "qwen_hermes"
os.environ["OLLAMA_HOST"] = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

from mock_adapters import MockRobot
from nomi_agent.tool_registry import ToolRegistry as RegistryWithMockSkills


class MockOnlyToolRegistry:
    """The production registry/schema/guards with only deterministic mock skills."""

    instances = []

    def __init__(self, node=None):
        self.robot = MockRobot()
        self.delegate = RegistryWithMockSkills(skills=self.robot.as_registry_skills())
        self.skills = self.delegate.skills
        self.node = None
        self.__class__.instances.append(self)
        assert all(type(skill).__name__.startswith("Mock") for skill in self.skills.values())

    def __getattr__(self, name):
        return getattr(self.delegate, name)


CASES = [
    ("state", "현재 로봇 상태를 알려줘.", ["get_robot_state"], "SUCCEEDED"),
    ("open", "그리퍼를 열어 줘.", ["open_gripper"], "SUCCEEDED"),
    ("close", "그리퍼를 닫아 줘.", ["close_gripper"], "SUCCEEDED"),
    ("pick", "분홍색 수건을 집어 줘.", ["pick_object"], "SUCCEEDED"),
    ("place_without_context", "테이블 위에 놓아 줘.", [], "NEEDS_CLARIFICATION"),
    ("pick_place", "분홍색 수건을 집어서 테이블 위에 놓아 줘.", ["pick_object", "place_object"], "SUCCEEDED"),
    ("forward", "앞으로 이동해.", ["navigate_to"], "SUCCEEDED"),
    ("ambiguous", "그거 저기에 놓아 줘.", [], "NEEDS_CLARIFICATION"),
    ("negated", "그리퍼를 열지 마.", [], "SUCCEEDED"),
    ("location", "현재 위치를 알려줘.", ["get_user_location"], "SUCCEEDED"),
    ("weather", "서울 날씨를 알려줘.", ["get_weather"], "SUCCEEDED"),
    ("multi_info", "현재 로봇 상태와 서울 날씨를 알려줘.", ["get_robot_state", "get_weather"], "SUCCEEDED"),
]
TERMINAL = {"NEEDS_CLARIFICATION", "SUCCEEDED", "FAILED", "CANCELLED"}


async def run(args):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    import nomi_agent.agent_node as agent_node_module

    agent_node_module.ToolRegistry = MockOnlyToolRegistry
    rclpy.init(args=None, domain_id=ROS_DOMAIN)
    agent = agent_node_module.NomiAgentNode()
    assert isinstance(agent.tool_registry, MockOnlyToolRegistry), "unsafe ToolRegistry was constructed"
    assert agent.llm_client.profile == "qwen_hermes"
    assert all(type(skill).__name__.startswith("Mock") for skill in agent.tool_registry.skills.values())

    executor = SingleThreadedExecutor()
    executor.add_node(agent)
    ros_spin = asyncio.create_task(asyncio.to_thread(executor.spin))

    import main as web_main
    import uvicorn

    async def refuse_robot_host_connection():
        print("SAFE_TEST: RemoteCore.connect blocked; no robot/MuJoCo host connection")
        return False

    async def no_robot_host_disconnect():
        return None

    web_main.remote_core.connect = refuse_robot_host_connection
    web_main.remote_core.disconnect = no_robot_host_disconnect
    web_main.remote_core.connected = False

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        web_main.socket_app, host="127.0.0.1", port=port,
        log_level="warning", lifespan="on",
    ))
    web_task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        if web_task.done():
            await web_task
        await asyncio.sleep(0.02)
    if not server.started:
        raise RuntimeError("test Socket.IO server did not start")

    client_script = REPO / "web_control" / "client" / "scripts" / "nomi_socket_e2e_client.mjs"
    client_proc = await asyncio.create_subprocess_exec(
        "node", str(client_script), f"http://127.0.0.1:{port}",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    status_by_task: dict[str, list[dict]] = {}
    terminal_events: dict[str, asyncio.Event] = {}
    model_switch_results: list[dict] = []
    model_event = asyncio.Event()
    bridge_events: list[dict] = []
    connected = asyncio.Event()
    connected_clients: set[str] = set()
    client_event_queue: asyncio.Queue[tuple[str, str, dict]] = asyncio.Queue()
    client_error: list[str] = []
    safety_summary: dict = {}

    async def read_socket_events():
        assert client_proc.stdout is not None
        while line := await client_proc.stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                client_error.append(f"invalid Node Socket.IO output: {line!r}")
                continue
            if message.get("type") == "connected":
                client_id = str(message.get("client_id", "primary"))
                connected_clients.add(client_id)
                if client_id == "primary":
                    connected.set()
            elif message.get("type") == "client_error":
                client_error.append(str(message.get("error", "Socket.IO client error")))
            elif message.get("type") == "event":
                client_id = str(message.get("client_id", "primary"))
                event, payload = message.get("event"), message.get("payload") or {}
                await client_event_queue.put((client_id, event, payload))
                if event == "nomi_task_status":
                    task_id = str(payload.get("task_id", ""))
                    status_by_task.setdefault(task_id, []).append(payload)
                    if payload.get("status") in TERMINAL:
                        terminal_events.setdefault(task_id, asyncio.Event()).set()
                elif event == "nomi_model_status":
                    model_switch_results.append(payload)
                    model_event.set()
                elif event == "nomi_bridge_status":
                    bridge_events.append(payload)

    socket_reader = asyncio.create_task(read_socket_events())

    async def emit(event, payload=None, client_id="primary"):
        if client_error:
            raise RuntimeError("Socket.IO client failed: " + "; ".join(client_error))
        assert client_proc.stdin is not None
        message = {"event": event, "client_id": client_id}
        if payload is not None:
            message["payload"] = payload
        client_proc.stdin.write((json.dumps(message) + "\n").encode())
        await client_proc.stdin.drain()

    async def wait_client_event(client_id, event, predicate=lambda _payload: True, timeout=10):
        async def find_event():
            while True:
                found_client, found_event, payload = await client_event_queue.get()
                if found_client == client_id and found_event == event and predicate(payload):
                    return payload
        return await asyncio.wait_for(find_event(), timeout=timeout)

    async def wait_task_status(task_id, wanted_status, timeout=20):
        async def find_status():
            while True:
                if any(item.get("status") == wanted_status for item in status_by_task.get(task_id, [])):
                    return
                await asyncio.sleep(0.02)
        await asyncio.wait_for(find_status(), timeout=timeout)

    async def wait_task_response(task_id, timeout=10):
        async def find_response():
            while True:
                for item in reversed(status_by_task.get(task_id, [])):
                    if item.get("status") in TERMINAL and item.get("response_text"):
                        return
                await asyncio.sleep(0.02)
        await asyncio.wait_for(find_response(), timeout=timeout)

    try:
        await asyncio.wait_for(connected.wait(), timeout=15)
        await emit("nomi_get_status")
        await asyncio.sleep(0.7)
        if not bridge_events or bridge_events[-1].get("connected") is not True:
            raise RuntimeError(f"test Agent not discovered on isolated ROS domain {ROS_DOMAIN}: {bridge_events}")

        await emit("nomi_model_switch", {"profile": "qwen35_single", "request_id": "e2e-model-qwen35"})
        await asyncio.wait_for(model_event.wait(), timeout=10)
        switch_result = model_switch_results[-1]
        if switch_result.get("status") != "success" or switch_result.get("profile") != "qwen35_single":
            raise RuntimeError(f"Qwen profile switch failed: {switch_result}")
        if agent.llm_client.profile != "qwen35_single" or not agent.llm_client.is_single_model_profile:
            raise RuntimeError("Agent did not activate the qwen35_single profile")
        print(f"SAFE_TEST: profile={agent.llm_client.profile}, registry=MockOnlyToolRegistry, ROS_DOMAIN_ID={ROS_DOMAIN}")

        # Exercise actual multi-client isolation and cancellation while the real model call is active.
        await emit("__connect_secondary")
        for _ in range(250):
            if "secondary" in connected_clients:
                break
            await asyncio.sleep(0.02)
        if "secondary" not in connected_clients:
            raise RuntimeError("secondary Socket.IO client failed to connect")
        cancel_request_id = f"e2e-cancel-{int(time.time() * 1000)}"
        cancel_registry = MockOnlyToolRegistry(agent)
        agent.tool_registry = cancel_registry
        agent.harness.tool_registry = cancel_registry
        await emit("nomi_command", {"text": "현재 로봇 상태를 자세히 설명해줘.", "request_id": cancel_request_id})
        await wait_task_status(cancel_request_id, "RUNNING", timeout=args.timeout)
        await emit("nomi_command", {"text": "현재 로봇 상태를 자세히 설명해줘.", "request_id": cancel_request_id})
        duplicate_event = await wait_client_event(
            "primary", "nomi_command_received",
            lambda payload: payload.get("request_id") == cancel_request_id and payload.get("status") == "duplicate",
        )
        if duplicate_event.get("status") != "duplicate":
            raise RuntimeError(f"duplicate request was not rejected: {duplicate_event}")
        await emit("nomi_task_cancel", {"task_id": cancel_request_id}, client_id="secondary")
        rejected_cancel = await wait_client_event(
            "secondary", "nomi_cancel_result", lambda payload: payload.get("task_id") == cancel_request_id,
        )
        if rejected_cancel.get("status") != "error":
            raise RuntimeError(f"secondary client incorrectly cancelled another user's task: {rejected_cancel}")
        await emit("nomi_command", {"text": "서울 날씨를 알려줘.", "request_id": f"e2e-secondary-{int(time.time() * 1000)}"}, client_id="secondary")
        rejected_command = await wait_client_event("secondary", "nomi_response", lambda payload: payload.get("status") == "error")
        if "다른 사용자의 NOMI 작업" not in rejected_command.get("message", ""):
            raise RuntimeError(f"second client was not safely rejected: {rejected_command}")
        await emit("nomi_task_cancel", {"task_id": cancel_request_id})
        accepted_cancel = await wait_client_event(
            "primary", "nomi_cancel_result", lambda payload: payload.get("task_id") == cancel_request_id,
        )
        if accepted_cancel.get("status") != "accepted":
            raise RuntimeError(f"owner cancel request was not accepted: {accepted_cancel}")
        await asyncio.wait_for(terminal_events.setdefault(cancel_request_id, asyncio.Event()).wait(), timeout=20)
        cancel_final = next(item for item in reversed(status_by_task[cancel_request_id]) if item.get("status") in TERMINAL)
        state_skill = cancel_registry.skills.get("state")
        state_calls = getattr(state_skill, "calls", 0) if state_skill else 0
        if cancel_final.get("status") != "CANCELLED" or state_calls:
            raise RuntimeError(f"cancel did not stop cleanly before mock tool execution: {cancel_final}")
        safety_summary = {
            "safety_case": "cancel_and_multi_client_isolation",
            "task_id": cancel_request_id,
            "cancel_status": cancel_final.get("status"),
            "owner_cancel": accepted_cancel.get("status"),
            "other_client_cancel": rejected_cancel.get("status"),
            "other_client_command": rejected_command.get("status"),
            "duplicate_request": duplicate_event.get("status"),
            "mock_tool_calls": 0,
        }
        print(json.dumps(safety_summary, ensure_ascii=False))

        rows = []
        failures = []
        for case_id, utterance, expected_tools, expected_status in CASES:
            request_id = f"e2e-{case_id}-{int(time.time() * 1000)}"
            # Reset conversation and mock robot for each independent scenario.
            agent.llm_client.clear_history()
            mock_registry = MockOnlyToolRegistry(agent)
            agent.tool_registry = mock_registry
            agent.harness.tool_registry = mock_registry
            started = time.perf_counter()
            await emit("nomi_command", {"text": utterance, "request_id": request_id})
            await asyncio.wait_for(terminal_events.setdefault(request_id, asyncio.Event()).wait(), timeout=args.timeout)
            if expected_status != "CANCELLED":
                await wait_task_response(request_id, timeout=10)
            elapsed = time.perf_counter() - started
            history = status_by_task.get(request_id, [])
            final = next((item for item in reversed(history) if item.get("status") in TERMINAL and item.get("response_text")), {})
            steps = final.get("steps") or []
            actual_tools = [str(step.get("tool")) for step in steps if step.get("tool")]
            actual_status = final.get("status", "MISSING")

            if case_id == "negated":
                matched = actual_status == expected_status and len(steps) == 0
            elif case_id == "pick_place":
                matched = actual_status == expected_status and actual_tools == expected_tools and all(step.get("success") for step in steps)
            elif case_id == "multi_info":
                matched = actual_status == expected_status and set(actual_tools) == set(expected_tools) and len(actual_tools) == 2
            else:
                matched = actual_status == expected_status and actual_tools == expected_tools
            mock_calls = {}
            for name, skill in mock_registry.skills.items():
                calls = getattr(skill, "calls", None)
                if calls:
                    mock_calls[name] = list(calls) if isinstance(calls, (list, tuple)) else calls
            row = {
                "case_id": case_id,
                "command": utterance,
                "request_id": request_id,
                "task_id": final.get("task_id", request_id),
                "profile": agent.llm_client.profile,
                "tools": json.dumps(actual_tools, ensure_ascii=False),
                "tool_calls": len(steps),
                "status_history": json.dumps([item.get("status") for item in history], ensure_ascii=False),
                "final_status": actual_status,
                "response": final.get("response_text", ""),
                "latency_seconds": round(elapsed, 3),
                "model_calls": final.get("model_calls", ""),
                "expected_tools": json.dumps(expected_tools, ensure_ascii=False),
                "expected_status": expected_status,
                "passed": matched,
                "error": json.dumps(final.get("error"), ensure_ascii=False) if final.get("error") else "",
                "mock_skill_calls": json.dumps(mock_calls, ensure_ascii=False),
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
            if not matched:
                failures.append(case_id)

        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        safety_output = output.with_suffix(".safety.json")
        safety_output.write_text(json.dumps(safety_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"E2E_CSV={output}")
        print(f"E2E_SAFETY_JSON={safety_output}")
        print(f"E2E_SUMMARY passed={len(rows)-len(failures)}/{len(rows)} avg_latency_seconds={sum(row['latency_seconds'] for row in rows)/len(rows):.3f} failures={','.join(failures) or 'none'}")
        return 0 if not failures else 2
    finally:
        if client_proc.returncode is None:
            assert client_proc.stdin is not None
            client_proc.stdin.write(b'{"event":"__close"}\n')
            await client_proc.stdin.drain()
            try:
                await asyncio.wait_for(client_proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                client_proc.kill()
                await client_proc.wait()
        socket_reader.cancel()
        await asyncio.gather(socket_reader, return_exceptions=True)
        if client_proc.stderr is not None:
            stderr = await client_proc.stderr.read()
            if stderr:
                print("SOCKET_CLIENT_STDERR=" + stderr.decode(errors="replace"))
        server.should_exit = True
        await asyncio.wait_for(web_task, timeout=15)
        executor.shutdown(timeout_sec=2.0)
        agent.destroy_node()
        rclpy.shutdown()
        await asyncio.wait_for(ros_spin, timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per LLM-backed case")
    parser.add_argument("--output", default=str(REPO / "nomi_benchmarks" / "webapp_qwen35_socket_e2e.csv"))
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compare qwen_hermes and qwen35_single through Harness + mock tools only."""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from nomi_agent.core.execution_harness import ExecutionHarness, TERMINAL
from nomi_agent.llm_client import LLMClient
from nomi_agent.tool_registry import ToolRegistry
from tests.mock_adapters import MockRobot

CASES = [
    ("state", "현재 로봇 상태를 알려줘.", [("get_robot_state", {})], False),
    ("open", "그리퍼를 열어 줘.", [("open_gripper", {})], False),
    ("close", "그리퍼를 닫아 줘.", [("close_gripper", {})], False),
    ("pick", "분홍색 수건을 집어 줘.", [("pick_object", {"object_name": "분홍색 수건"})], False),
    ("place", "테이블 위에 놓아 줘.", [], True),
    ("pick_place", "분홍색 수건을 집어서 테이블 위에 놓아 줘.", [
        ("pick_object", {"object_name": "분홍색 수건"}), ("place_object", {"location": "테이블"})], False),
    ("navigation", "앞으로 이동해.", [("navigate_to", {"location": "forward"})], False),
    ("weather", "서울 날씨 알려줘.", [("get_weather", {"city": "서울"})], False),
    ("location", "내 위치를 알려줘.", [("get_user_location", {})], False),
    ("multi_info", "서울 날씨와 로봇 상태를 알려줘.", [
        ("get_weather", {"city": "서울"}), ("get_robot_state", {})], False),
    ("ambiguous", "그거 저기에 놓아 줘.", [], True),
    ("negated", "그리퍼를 열지 마.", [], False),
]
PROFILES = ("qwen_hermes", "qwen35_single")


def ollama_models():
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    with urllib.request.urlopen(host + "/api/tags", timeout=3) as response:
        return {item["name"] for item in json.load(response).get("models", [])}


def required_models(profile):
    return ({"qwen2.5:7b", "hermes3:8b"} if profile == "qwen_hermes"
            else {os.getenv("NOMI_SINGLE_MODEL", "qwen3.5:9b")})


def wait_task(harness, task_id, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = harness.get_task(task_id)
        if task and task["status"] in {status.value for status in TERMINAL}:
            return task
        time.sleep(0.01)
    raise TimeoutError("Harness task did not finish within benchmark timeout")


def execute(profile, case, repeat):
    case_id, prompt, expected, clarification = case
    started = time.monotonic()
    llm = LLMClient(profile=profile)
    registry = ToolRegistry(skills=MockRobot().as_registry_skills())
    harness = ExecutionHarness(llm, registry, lambda _text: None)
    _, task_id = harness.submit(prompt, request_id=f"bench-{profile}-{case_id}-{repeat}")
    task = wait_task(harness, task_id)
    actual = [(item["tool"], item["arguments"]) for item in task["steps"]]
    correct = actual == expected
    if clarification:
        correct = correct and task["status"] == "NEEDS_CLARIFICATION"
    elif expected:
        correct = correct and task["status"] == "SUCCEEDED"
    elif clarification:
        correct = correct and task["status"] == "NEEDS_CLARIFICATION"
    elif case_id == "negated":
        correct = correct and task["status"] != "SUCCEEDED"
    return {
        "profile": profile, "case_id": case_id, "repeat": repeat, "command": prompt,
        "status": task["status"], "expected_tools": json.dumps(expected, ensure_ascii=False),
        "actual_tools": json.dumps(actual, ensure_ascii=False), "accuracy": int(bool(correct)),
        "latency_seconds": round(time.monotonic() - started, 4),
        "model_calls": task.get("model_calls", 0),
        "failed": int(task["status"] not in {"SUCCEEDED", "NEEDS_CLARIFICATION"}),
        "error": json.dumps(task.get("error"), ensure_ascii=False) if task.get("error") else "",
        "hardware_used": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("/tmp/nomi_profile_comparison.csv"))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    try:
        available, connection_error = ollama_models(), ""
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        available, connection_error = set(), f"Ollama unavailable: {type(exc).__name__}: {exc}"
    rows = []
    for profile in PROFILES:
        missing = required_models(profile) - available
        reason = connection_error or ("Missing Ollama model(s): " + ", ".join(sorted(missing)) if missing else "")
        for repeat in range(1, args.repeats + 1):
            for case in CASES:
                if reason:
                    case_id, prompt, expected, _ = case
                    rows.append({"profile": profile, "case_id": case_id, "repeat": repeat, "command": prompt,
                                 "status": "UNAVAILABLE", "expected_tools": json.dumps(expected, ensure_ascii=False),
                                 "actual_tools": "", "accuracy": "", "latency_seconds": "", "model_calls": "",
                                 "failed": "", "error": reason, "hardware_used": 0})
                else:
                    try:
                        rows.append(execute(profile, case, repeat))
                    except Exception as exc:
                        rows.append({"profile": profile, "case_id": case[0], "repeat": repeat, "command": case[1],
                                     "status": "ERROR", "expected_tools": json.dumps(case[2], ensure_ascii=False),
                                     "actual_tools": "", "accuracy": 0, "latency_seconds": "", "model_calls": "",
                                     "failed": 1, "error": f"{type(exc).__name__}: {exc}", "hardware_used": 0})
    summaries = []
    for profile in PROFILES:
        measured = [row for row in rows if row["profile"] == profile and row["status"] not in {"UNAVAILABLE", "ERROR"}]
        if measured:
            summaries.append({
                "profile": profile, "row_type": "SUMMARY", "case_id": "__SUMMARY__", "repeat": args.repeats,
                "status": "MEASURED", "accuracy_percent": round(100 * sum(int(r["accuracy"]) for r in measured) / len(measured), 2),
                "mean_latency_seconds": round(sum(float(r["latency_seconds"]) for r in measured) / len(measured), 4),
                "mean_model_calls": round(sum(int(r["model_calls"]) for r in measured) / len(measured), 3),
                "failure_rate_percent": round(100 * sum(int(r["failed"]) for r in measured) / len(measured), 2),
                "hardware_used": 0,
            })
        else:
            failure = next((r["error"] for r in rows if r["profile"] == profile), "No measurements")
            summaries.append({"profile": profile, "row_type": "SUMMARY", "case_id": "__SUMMARY__",
                              "repeat": args.repeats, "status": "UNAVAILABLE", "accuracy_percent": "",
                              "mean_latency_seconds": "", "mean_model_calls": "", "failure_rate_percent": "",
                              "error": failure, "hardware_used": 0})
    rows.extend(summaries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["profile", "row_type", "case_id", "repeat", "command", "status", "expected_tools", "actual_tools", "accuracy",
              "latency_seconds", "model_calls", "failed", "accuracy_percent", "mean_latency_seconds",
              "mean_model_calls", "failure_rate_percent", "error", "hardware_used"]
    with args.output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV: {args.output}")
    for profile in PROFILES:
        measured = [row for row in rows if row["profile"] == profile and row.get("row_type") != "SUMMARY"
                    and row["status"] not in {"UNAVAILABLE", "ERROR"}]
        if not measured:
            print(f"{profile}: 측정 불가 (CSV error 열 참조)")
            continue
        print(json.dumps({"profile": profile, "cases": len(measured),
                          "accuracy_percent": round(100 * sum(int(r["accuracy"]) for r in measured) / len(measured), 2),
                          "mean_latency_seconds": round(sum(float(r["latency_seconds"]) for r in measured) / len(measured), 4),
                          "mean_model_calls": round(sum(int(r["model_calls"]) for r in measured) / len(measured), 3),
                          "failure_rate_percent": round(100 * sum(int(r["failed"]) for r in measured) / len(measured), 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Run the offline Registry/Harness regression suite and save JSONL audit data."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import unittest

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from tests.test_natural_language_integration import AUDIT_EVENTS

    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py", top_level_dir=str(root))
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    elapsed = round(time.monotonic() - started, 3)

    now = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    log_dir = Path(os.getenv("NOMI_TEST_LOG_DIR", "/tmp/nomi-agent-test-logs")).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"registry-harness-{now}.jsonl"

    tool_events = [event for event in AUDIT_EVENTS if event.get("event") == "tool_finished"]
    validation_events = [event for event in AUDIT_EVENTS if event.get("event") == "tool_validation"]
    plan_validation_events = [event for event in AUDIT_EVENTS if event.get("event") == "plan_validation"]
    durations = [event["duration_seconds"] for event in tool_events if isinstance(event.get("duration_seconds"), (int, float))]
    statuses = [event.get("status") for event in AUDIT_EVENTS if event.get("event") == "task_status"]
    summary = {
        "event": "test_run_summary",
        "test_count": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "suite_duration_seconds": elapsed,
        "tool_execution_count": len(tool_events),
        "tool_validations_accepted": sum(bool(e.get("accepted")) for e in validation_events),
        "tool_validations_rejected": sum(not bool(e.get("accepted")) for e in validation_events),
        "plan_validations_accepted": sum(bool(e.get("accepted")) for e in plan_validation_events),
        "plan_validations_rejected": sum(not bool(e.get("accepted")) for e in plan_validation_events),
        "task_status_counts": {status: statuses.count(status) for status in sorted(set(statuses))},
        "tool_duration_average_seconds": round(sum(durations) / len(durations), 4) if durations else None,
        "tool_duration_max_seconds": max(durations) if durations else None,
        "live_llm_called": False,
        "robot_hardware_used": False,
    }
    with log_path.open("w", encoding="utf-8") as stream:
        for event in AUDIT_EVENTS:
            stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        stream.write(json.dumps(summary, ensure_ascii=False) + "\n")

    print("\n오프라인 평가 요약")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"JSONL 로그: {log_path}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    route: str = "TASK"
    task_type: str = ""
    intent: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    instruction: str = ""
    reply: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            route=data.get("route", "TASK"),
            task_type=data.get("type", data.get("task_type", "")),
            intent=data.get("intent", ""),
            arguments=data.get("arguments", {}),
            instruction=data.get("instruction", ""),
            reply=data.get("reply"),
        )

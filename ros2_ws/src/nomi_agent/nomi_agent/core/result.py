from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }

    @classmethod
    def ok(cls, message: str, data: dict[str, Any] | None = None) -> "SkillResult":
        return cls(success=True, message=message, data=data or {})

    @classmethod
    def fail(cls, message: str, data: dict[str, Any] | None = None) -> "SkillResult":
        return cls(success=False, message=message, data=data or {})


def success_result(data: dict[str, Any] | None = None, message: str = "") -> SkillResult:
    return SkillResult.ok(message=message, data=data)


def error_result(message: str, data: dict[str, Any] | None = None) -> SkillResult:
    return SkillResult.fail(message=message, data=data)


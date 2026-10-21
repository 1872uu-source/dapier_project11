from typing import Any


def format_task_result(result: Any) -> str:
    if result is None:
        return "실행 결과가 없습니다."

    if isinstance(result, str):
        return result

    if hasattr(result, "to_dict"):
        result = result.to_dict()

    if not isinstance(result, dict):
        return str(result)

    success = result.get("success", False)
    message = result.get("message", "")

    if success:
        return message or "작업을 완료했습니다."

    error = result.get("error", "")
    return error or message or "작업을 실행하지 못했습니다."


class ResponseFormatter:
    def format_result(self, result: Any) -> str:
        return format_task_result(result)

"""Bounded Korean/English movement command parser for NOMI chat."""

from __future__ import annotations

import re

DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(초|초간|seconds?|secs?)", re.IGNORECASE)
SPEED_RE = re.compile(r"속도\s*(\d+(?:\.\d+)?)\s*(%|퍼센트)?", re.IGNORECASE)
QUESTION_HINTS = ("어떻게", "방법", "가능", "할 수", "왜", "무엇", "뭐")
SPLIT_RE = re.compile(
    r"\s*(?:,|그리고|그\s*다음(?:에)?|그\s*후(?:에)?|이어서|갔다가|가서|가고|돌고|회전하고|간\s*다음(?:에)?|간\s*뒤(?:에)?)\s*"
)
DESTINATION_VERB_RE = re.compile(
    r"(?:가자|가줘|가요|가세요|갑시다|가(?:\s|$)|돌아가|돌아오|향해|찾아가|이동(?:해|해줘|하세요)?|navigate|\bgo\b|\bhead\b|\breturn\b)",
    re.IGNORECASE,
)


def parse_destination_command(text: str) -> dict | None:
    """Recognize explicit requests to navigate to supported saved/preset places."""
    value = re.sub(r"[.!?。！？]+", " ", text.strip().lower())
    if not value or any(hint in value for hint in QUESTION_HINTS):
        return None
    if not DESTINATION_VERB_RE.search(value):
        return None
    if re.search(r"(?:집|home)", value):
        return {"destination": "home", "name": "집"}
    if re.search(r"(?:충전\s*도크|충전\s*소|도킹\s*스테이션|충전기|\bdock\b|\bcharging\s+station\b)", value):
        return {"destination": "charging_dock", "name": "충전 도크"}
    if re.search(r"(?:저장된\s*)?(?:목적지|장소)(?:로|으로)?\s*(?:가자|가줘|가요|가세요|가|이동(?:해|해줘|하세요)?)", value):
        return {"destination": "saved", "name": "저장된 목적지"}
    place_match = re.search(
        r"(?P<name>[가-힣A-Za-z0-9][가-힣A-Za-z0-9 _-]{0,78}?)(?:으로|로|에)\s*(?:돌아가|가자|가줘|가요|가세요|가(?:\s|$)|이동(?:해|해줘|하세요)?|향해|찾아가)",
        value,
        re.IGNORECASE,
    )
    if place_match:
        name = place_match.group("name").strip()
        if name:
            return {"destination": "saved", "name": name}
    return None


def _parse_step(text: str) -> dict | None:
    value = re.sub(r"[.!?。！？]+", " ", text.strip().lower())
    if not value or any(hint in value for hint in QUESTION_HINTS):
        return None
    if re.search(r"(?:멈춰|멈추|정지|중지|그만|stop|halt|비상정지)", value):
        return {"direction": "stop", "speed": 0.0, "duration": 0.0}

    imperative = re.search(r"(?:가|가줘|가 주세요|이동|움직|회전|돌아|돌려|틀어|전진|후진|move|drive|turn|rotate)", value)
    duration_match = DURATION_RE.search(value)
    if not imperative and not duration_match:
        return None

    direction = None
    if re.search(r"(?:앞으로|전진|forward|ahead)", value):
        direction = "forward"
    elif re.search(r"(?:뒤로|후진|backward|reverse|back)", value):
        direction = "backward"
    elif re.search(r"(?:좌회전|왼쪽|left)", value):
        direction = "rotate_left"
    elif re.search(r"(?:우회전|오른쪽|right)", value):
        direction = "rotate_right"
    if direction is None:
        return None

    duration = min(5.0, max(0.2, float(duration_match.group(1)))) if duration_match else 1.0
    speed_match = SPEED_RE.search(value)
    if speed_match:
        speed = float(speed_match.group(1))
        if speed_match.group(2) == "%" or "퍼센트" in (speed_match.group(2) or ""):
            speed /= 100.0
    elif "천천히" in value:
        speed = 0.2
    elif "빠르게" in value or "최대 속도" in value:
        speed = 0.7
    else:
        speed = 0.35
    return {"direction": direction, "speed": min(1.0, max(0.05, speed)), "duration": duration}


def parse_motion_command(text: str) -> dict | None:
    """Parse one explicit movement or a short ordered list of only movements."""
    clauses = [clause.strip() for clause in SPLIT_RE.split(text.strip()) if clause.strip()]
    if not clauses:
        return None
    steps = [_parse_step(clause) for clause in clauses]
    # Do not swallow mixed requests (for example, a weather question plus movement).
    if any(step is None for step in steps):
        return None
    valid_steps = [step for step in steps if step is not None]
    if len(valid_steps) > 5:
        return None
    total_duration = sum(step["duration"] for step in valid_steps)
    if total_duration > 10:
        return None
    if len(valid_steps) == 1:
        return valid_steps[0]
    return {"steps": valid_steps}

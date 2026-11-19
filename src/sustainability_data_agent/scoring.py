"""Score an answer against the plain-script reference. The rule is fixed before any run:

A question is right when the agent's final `ANSWER: {...}` line has every requested key, each
number is within its tolerance of the reference value, and each code or hour matches exactly
(after trimming case and a missing leading zero, so "4:00" equals "04:00").
"""

from __future__ import annotations

import json
import re
from typing import Any

ANSWER_LINE = re.compile(r"^\s*\**ANSWER:?\**\s*:?\s*(\{.*\})\s*$", re.MULTILINE)


def prompt_for(question: dict[str, Any]) -> str:
    keys = ", ".join(f'"{k}": <{v}>' for k, v in question["answer"].items())
    return f"{question['question']}\n\nEnd with one final line: ANSWER: {{{keys}}}"


def parse_answer(text: str) -> dict[str, Any] | None:
    found = ANSWER_LINE.findall(text or "")
    if not found:
        return None
    try:
        value = json.loads(found[-1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _norm(value: Any) -> str:
    text = str(value).strip().upper()
    hour = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    return f"{int(hour.group(1)):02d}:{hour.group(2)}" if hour else text


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip().rstrip("%"))
    except ValueError:
        return None


def score(question: dict[str, Any], expected: dict[str, Any], text: str) -> dict[str, Any]:
    """Returns {"right": bool, "checks": {key: (got, expected, ok)}, "parsed": dict | None}."""
    parsed = parse_answer(text)
    checks: dict[str, tuple[Any, Any, bool]] = {}
    for key in question["answer"]:
        want = expected[key]
        got = None if parsed is None else parsed.get(key)
        tol = question.get("tolerance", {}).get(key)
        if isinstance(want, (int, float)) and not isinstance(want, bool):
            num = _number(got)
            if num is None:
                ok = False
            elif isinstance(tol, dict):
                ok = abs(num - want) <= tol["rel"] * abs(want)
            else:
                ok = abs(num - want) <= (tol if tol is not None else 0.0) + 1e-9
        else:
            ok = got is not None and _norm(got) == _norm(want)
        checks[key] = (got, want, ok)
    return {"right": parsed is not None and all(ok for *_, ok in checks.values()), "checks": checks, "parsed": parsed}

"""LLM 출력 JSON 복구 헬퍼 — loads_lenient의 2·3단계 복구 로직.

이 모듈은 llm_output.py의 private 헬퍼를 SRP에 따라 분리한 것이다. 외부에서 직접
임포트하지 말고 llm_output.loads_lenient를 통해 간접 사용한다.

복구 단계:
    2단계 — trailing comma 제거 + LaTeX/코드 백슬래시 교정.
    3단계 — JSON 문자열 리터럴 내 raw 제어문자 이스케이프 (Qwen xgrammar 갭 대응).
"""
from __future__ import annotations

import re

# JSON 표준에서 유효한 이스케이프 시퀀스.
_VALID_ESCAPES = re.compile(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})')
# 처리 대상 raw 제어문자 → JSON 이스케이프 표현.
_CTRL_MAP: dict[str, str] = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def strip_trailing_commas(text: str) -> str:
    """객체/배열 닫기 직전의 trailing comma를 제거한다.

    ``{"a":1,}`` 또는 ``[1,2,]`` 같은 비표준 출력을 표준 JSON으로 교정한다.
    문자열 내부는 건드리지 않도록 닫는 괄호 직전 콤마만 대상으로 한다.
    """
    return re.sub(r",(\s*[}\]])", r"\1", text)


def fix_unescaped_backslashes(text: str) -> str:
    r"""유효한 JSON 이스케이프를 제외한 백슬래시를 이중 처리한다.

    LaTeX(\psi, \frac)나 코드에서 나오는 잘못된 이스케이프를 안전한 이중 백슬래시로
    바꿔 json.loads가 통과하도록 만든다.
    """
    result: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\":
            match = _VALID_ESCAPES.match(text, i)
            if match:
                result.append(match.group())
                i = match.end()
            else:
                result.append("\\\\")
                i += 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def escape_raw_control_chars_in_strings(text: str) -> str:
    r"""JSON 문자열 리터럴 안의 raw 제어문자를 이스케이프 시퀀스로 바꾼다.

    xgrammar가 긴 한국어 script_text 안의 개행·탭·캐리지리턴을 완전히 이스케이프 못 해
    json.loads가 "Expecting value"로 실패하는 Qwen 실측 갭을 처리한다.
    문자열 밖의 구조적 공백(들여쓰기·줄바꿈)은 건드리지 않는다.

    상태: in_string — 현재 위치가 JSON 문자열 리터럴 내부인지 추적.
    백슬래시 직후 문자는 이미 이스케이프된 것이므로 두 문자를 통째로 보존한다.
    """
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                # 이미 이스케이프된 시퀀스 — 두 문자 그대로 보존.
                result.append(ch)
                result.append(text[i + 1] if i + 1 < len(text) else "")
                i += 2
                continue
            if ch == '"':
                in_string = False
                result.append(ch)
            elif ch in _CTRL_MAP:
                # 문자열 내 raw 제어문자 → 이스케이프 치환.
                result.append(_CTRL_MAP[ch])
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_string = True
            result.append(ch)
        i += 1
    return "".join(result)


__all__ = [
    "escape_raw_control_chars_in_strings",
    "fix_unescaped_backslashes",
    "strip_trailing_commas",
]

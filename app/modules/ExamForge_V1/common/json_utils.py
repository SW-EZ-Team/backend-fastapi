"""JSON 추출 유틸리티."""
from __future__ import annotations

from typing import Any
import re

from app.modules.ExamForge_V1.common.json_yaml_fallback import parse_yaml_jsonish
# 루트 common/ 패키지 재사용 (모델 스왑 시 think 블록 파싱 붕괴를 한 곳에서 차단).
from common.llm_output import strip_thinking

# JSON 표준에서 유효한 이스케이프 시퀀스 패턴
_VALID_ESCAPES = re.compile(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})')


def _fix_unescaped_backslashes(text: str) -> str:
    r"""유효한 JSON 이스케이프를 제외한 백슬래시를 이중 처리한다(LaTeX \psi 등 교정)."""
    result: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == '\\':
            m = _VALID_ESCAPES.match(text, i)
            if m:
                # 유효한 이스케이프 시퀀스는 그대로 유지
                result.append(m.group())
                i = m.end()
            else:
                # 유효하지 않은 백슬래시는 이중 처리
                result.append('\\\\')
                i += 1
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


def extract_json(text: str) -> str:
    """AI 응답에서 JSON 부분만 추출한다.

    진입부에서 reasoning(<think>, 잘린 think 포함)을 제거해 ExamForge 전 노드를
    한 번에 보호한다. codex 출력엔 think가 없어 no-op이므로 회귀가 없다.
    """
    text = strip_thinking(text)
    if "```" in text:
        try:
            start = text.index("```") + 3
            if text[start:start + 4] == "json":
                start += 4
            start = text.index("\n", start) + 1
            try:
                end = text.index("```", start)
            except ValueError:
                end = len(text)
            fenced = text[start:end].strip()
            return _fix_unescaped_backslashes(_trim_to_first_json(fenced))
        except (ValueError, IndexError):
            pass

    arr_idx = text.find("[")
    obj_idx = text.find("{")

    if arr_idx == -1 and obj_idx == -1:
        return _fix_unescaped_backslashes(text.strip())

    if obj_idx == -1:
        start_idx = arr_idx
        open_char, close_char = "[", "]"
    elif arr_idx == -1:
        start_idx = obj_idx
        open_char, close_char = "{", "}"
    elif arr_idx < obj_idx:
        start_idx = arr_idx
        open_char, close_char = "[", "]"
    else:
        start_idx = obj_idx
        open_char, close_char = "{", "}"

    end = _find_matching_close(text, start_idx, open_char, close_char)
    if end != -1:
        return _fix_unescaped_backslashes(text[start_idx:end + 1].strip())
    return _fix_unescaped_backslashes(text[start_idx:].strip())


def parse_llm_json(text: str) -> Any:
    """LLM 응답에서 JSON을 엄격하게 파싱하되, 후행 설명은 잘라낸다."""
    import json

    json_text = extract_json(text)
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        stripped = json_text.lstrip()
        try:
            data, _ = decoder.raw_decode(stripped)
            return data
        except json.JSONDecodeError:
            for candidate in _candidate_json_blocks(strip_thinking(text)):
                fixed = _fix_unescaped_backslashes(candidate)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    continue
            yaml_data = parse_yaml_jsonish(stripped)
            if yaml_data is not None:
                return yaml_data
            raise first_error


def unwrap_json_array(data: Any) -> list:
    """LLM이 배열을 객체로 감쌌을 때 자동 언래핑한다."""
    if isinstance(data, dict) and len(data) == 1:
        value = next(iter(data.values()))
        if isinstance(value, list):
            return value
    if isinstance(data, list):
        return data
    return [data]


def normalize_question_fields(item: dict) -> dict:
    """LLM이 다양한 필드명을 사용할 때 표준 필드명으로 정규화한다."""
    normalized = dict(item)
    if "stem" not in normalized:
        for alt in ("question", "problem", "문제", "text"):
            if alt in normalized:
                normalized["stem"] = normalized.pop(alt)
                break
    if "options" not in normalized:
        for alt in ("choices", "answers", "선택지", "보기"):
            if alt in normalized:
                normalized["options"] = normalized.pop(alt)
                break
    if "correct_answer" not in normalized:
        for alt in ("answer", "correct", "정답"):
            if alt in normalized:
                normalized["correct_answer"] = normalized.pop(alt)
                break
    for key in ("correct_answer", "explanation", "source_reference"):
        if key in normalized:
            normalized[key] = coerce_text_value(normalized[key])
    return normalized


def coerce_text_value(value: object) -> str:
    """LLM이 객체/배열로 준 답안 필드를 안전한 문자열로 바꾼다."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    import json
    return json.dumps(value, ensure_ascii=False)


def _trim_to_first_json(text: str) -> str:
    """코드블록 안의 첫 번째 JSON 객체/배열만 남긴다."""
    arr_idx = text.find("[")
    obj_idx = text.find("{")
    if arr_idx == -1 and obj_idx == -1:
        return text.strip()
    if obj_idx == -1 or (arr_idx != -1 and arr_idx < obj_idx):
        start_idx = arr_idx
        open_char, close_char = "[", "]"
    else:
        start_idx = obj_idx
        open_char, close_char = "{", "}"
    end = _find_matching_close(text, start_idx, open_char, close_char)
    if end == -1:
        return text[start_idx:].strip()
    return text[start_idx:end + 1].strip()


def _candidate_json_blocks(text: str) -> list[str]:
    """설명문 속 모든 JSON 객체/배열 후보를 앞에서부터 반환한다."""
    candidates: list[str] = []
    for index, char in enumerate(text):
        if char == "{":
            end = _find_matching_close(text, index, "{", "}")
        elif char == "[":
            end = _find_matching_close(text, index, "[", "]")
        else:
            continue
        if end != -1:
            candidates.append(text[index:end + 1].strip())
    return candidates


def _find_matching_close(
    text: str, start: int, open_char: str, close_char: str
) -> int:
    """괄호 깊이를 추적해 outermost 닫는 괄호 위치를 반환한다(문자열 내부 무시, 없으면 -1)."""
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\" and in_string:
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return i

    return -1

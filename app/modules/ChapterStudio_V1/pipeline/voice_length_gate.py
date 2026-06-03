"""voice_script 결정적 길이 게이트 — plan-first 슬롯 단위 검증.

기존 단일 len() 게이트를 섹션 슬롯별 min/max 게이트로 확장한다.
sections가 있으면 슬롯별 길이를 검증하고, sections가 없는 레거시 경로는
기존 단일 게이트로 폴백해 하위호환성을 유지한다.

설계 원칙:
    - LLM을 호출하지 않는 순수 함수만 둔다.
    - 오류 dict 형태는 content_verify_merge._VerifyError 계약과 동일하게 맞춘다
      (field="voice", slide_idx, what_is_wrong, correction, location).
    - 모두 합격이면 빈 목록 반환(완전한 no-op).

공개 API:
    - length_gate_errors(payload, min_chars) -> list[dict[str, object]]
    - short_voice_indices(payload, min_chars) -> list[int]
    - voice_extend_user_prompt(payload, short_indices, min_chars) -> str
"""
from __future__ import annotations

from app.modules.ChapterStudio_V1.common.config import VOICE_SECTION_RANGES
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload

# content_verify_merge._VerifyError.location의 관례 접두어.
_LOCATION_PREFIX = "voice_length_gate"


def length_gate_errors(
    payload: GeneratedLessonPayload, min_chars: int
) -> list[dict[str, object]]:
    """voice_script를 검증해 오류 dict 목록을 만든다(빈 목록 = 모두 합격).

    sections가 있으면 슬롯별 min/max를 검사한다.
    sections가 없으면(레거시) 단일 script_text len()으로 폴백한다.

    오류 dict 형태는 content_verify_merge._VerifyError 스키마와 호환된다:
        field="voice", slide_idx=..., what_is_wrong=..., correction=..., location=...
    """
    errors: list[dict[str, object]] = []
    for script in payload.voice_scripts:
        if script.sections:
            # plan-first 경로: 슬롯별 길이 검사.
            errors.extend(_slot_errors(script.slide_idx, script.sections))
        else:
            # 레거시 경로: 단일 len() 게이트.
            length = len(script.script_text.strip())
            if length < min_chars:
                errors.append(_length_error(script.slide_idx, length, min_chars))
    return errors


def short_voice_indices(payload: GeneratedLessonPayload, min_chars: int) -> list[int]:
    """min_chars 미만인 voice_script의 slide_idx 목록을 반환한다(교정 지시 생성용)."""
    result: list[int] = []
    for s in payload.voice_scripts:
        if s.sections:
            # sections가 있으면 슬롯 오류가 있는 경우만 포함.
            if _slot_errors(s.slide_idx, s.sections):
                result.append(s.slide_idx)
        elif len(s.script_text.strip()) < min_chars:
            result.append(s.slide_idx)
    return result


def voice_extend_user_prompt(
    payload: GeneratedLessonPayload, short_indices: list[int], min_chars: int
) -> str:
    """길이 미달 voice_script의 확장 교정 지시 user 프롬프트를 만든다.

    섹션이 있으면 미달 슬롯만 슬롯 단위로 확장 지시를 만든다.
    레거시(sections 없음)면 기존 전체 script_text 확장 지시를 만든다.
    """
    lines = [
        f"아래 음성대본들이 길이 기준에 미달한다. "
        "기존 내용을 유지·확장한다. 절대 내용을 줄이거나 다른 주제로 바꾸지 않는다.\n",
    ]
    for idx in sorted(short_indices):
        script = _find_script(payload, idx)
        if script is None:
            continue
        if script.sections:
            lines.append(f"[slide {idx}] 아래 슬롯들이 길이 미달이다:")
            for sec in script.sections:
                min_c, max_c = VOICE_SECTION_RANGES.get(sec.role, (80, 250))
                actual = len(sec.text.strip())
                if actual < min_c:
                    lines.append(
                        f"  - role={sec.role} (현재 {actual}자, 목표 {min_c}~{max_c}자):\n"
                        f"    현재 내용: {sec.text}\n"
                        f"    ↑ 위 내용을 기반으로 {min_c}자 이상 {max_c}자 이하로 확장한다.\n"
                    )
        else:
            current = script.script_text
            lines.append(
                f"slide {idx} 현재 대본({len(current.strip())}자, 미달):\n{current}\n"
                f"↑ 위 내용을 기반으로 {min_chars}자 이상으로 확장한다.\n"
            )
    lines.append("출력 형식: slide_idx와 sections(또는 script_text) 키를 가진 JSON 항목으로 교정한다.")
    return "\n".join(lines)


def _slot_errors(
    slide_idx: int, sections: list  # list[VoiceSection]
) -> list[dict[str, object]]:
    """sections 목록에서 슬롯별 길이 오류를 반환한다."""
    errors: list[dict[str, object]] = []
    for sec in sections:
        min_c, max_c = VOICE_SECTION_RANGES.get(sec.role, (80, 250))
        actual = len(sec.text.strip())
        if actual < min_c:
            errors.append(_slot_length_error(slide_idx, sec.role, actual, min_c, max_c, short=True))
        elif actual > max_c:
            errors.append(_slot_length_error(slide_idx, sec.role, actual, min_c, max_c, short=False))
    return errors


def _slot_length_error(
    slide_idx: int, role: str, actual: int, min_c: int, max_c: int, *, short: bool
) -> dict[str, object]:
    """슬롯 길이 오류 dict를 만든다(location은 슬롯까지 포함해 정밀하게 표기)."""
    direction = f"{min_c}자 미만" if short else f"{max_c}자 초과"
    fix = f"{min_c}~{max_c}자"
    return {
        "location": f"{_LOCATION_PREFIX}:slide_{slide_idx}:{role}",
        "field": "voice",
        "slide_idx": slide_idx,
        "what_is_wrong": f"voice[{slide_idx}].{role} 섹션이 {actual}자로 {direction}이다.",
        "correction": (
            f"내용을 유지하며 {role} 섹션을 {fix} 범위로 {'확장' if short else '축소'}한다."
        ),
    }


def _length_error(slide_idx: int, length: int, min_chars: int) -> dict[str, object]:
    """레거시 단일 script_text 길이 오류 dict(기존 포맷 유지)."""
    return {
        "location": f"{_LOCATION_PREFIX}:slide_{slide_idx}",
        "field": "voice",
        "slide_idx": slide_idx,
        "what_is_wrong": f"음성대본이 {length}자로 {min_chars}자 기준에 미달한다(실측 갭: xgrammar minLength 미강제).",
        "correction": f"기존 내용을 유지하며 도입→핵심→예시→복습 구조로 {min_chars}자 이상 확장한다(축소·내용 변경 금지).",
    }


def _find_script(payload: GeneratedLessonPayload, slide_idx: int):
    """payload에서 slide_idx에 해당하는 voice_script를 찾는다."""
    for script in payload.voice_scripts:
        if script.slide_idx == slide_idx:
            return script
    return None


__all__ = ["length_gate_errors", "short_voice_indices", "voice_extend_user_prompt"]

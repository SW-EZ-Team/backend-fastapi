"""voice_script 결정적 길이 게이트 — len() 기준으로 미달 항목을 찾는 순수 함수 모듈.

xgrammar가 voice_script 스키마의 minLength(850)를 완전히 강제하지 못해 560~841자 대본이
통과하는 실측 갭을 LLM 판단 없이 코드로 막는다. payload의 각 voice_script 길이를 측정해
min_chars 미만인 항목을 "voice" 필드 오류 dict 형태로 만들어 반환한다. 이 오류 dict는
기존 content_verify_parallel의 _affected_groups → 교정 루프에 그대로 투입된다.

설계 원칙:
    - LLM을 호출하지 않는 순수 함수만 둔다.
    - 오류 dict 형태는 content_verify_merge._VerifyError 계약과 동일하게 맞춘다
      (field="voice", slide_idx, what_is_wrong, correction).
    - min_chars 이상이면 빈 목록 반환(완전한 no-op).

공개 API:
    - length_gate_errors(payload, min_chars) -> list[dict[str, object]]
    - voice_extend_prompt(payload, short_indices) -> str  (교정 user 프롬프트용)
"""
from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload

# content_verify_merge._VerifyError.location의 관례 접두어.
_LOCATION_PREFIX = "voice_length_gate"


def length_gate_errors(
    payload: GeneratedLessonPayload, min_chars: int
) -> list[dict[str, object]]:
    """min_chars 미만인 voice_script를 찾아 오류 dict 목록을 만든다(빈 목록 = 모두 합격).

    오류 dict 형태는 content_verify_merge._VerifyError 스키마와 호환된다:
        field="voice", slide_idx=..., what_is_wrong=..., correction=..., location=...
    """
    errors: list[dict[str, object]] = []
    for script in payload.voice_scripts:
        length = len(script.script_text.strip())
        if length < min_chars:
            errors.append(_length_error(script.slide_idx, length, min_chars))
    return errors


def short_voice_indices(payload: GeneratedLessonPayload, min_chars: int) -> list[int]:
    """min_chars 미만인 voice_script의 slide_idx 목록을 반환한다(교정 지시 생성용)."""
    return [
        s.slide_idx
        for s in payload.voice_scripts
        if len(s.script_text.strip()) < min_chars
    ]


def voice_extend_user_prompt(
    payload: GeneratedLessonPayload, short_indices: list[int], min_chars: int
) -> str:
    """길이 미달 voice_script의 확장 교정 지시 user 프롬프트를 만든다.

    내용을 유지·확장해 min_chars 이상으로 늘린다(축소 금지). 현재 초안을 인용해 모델이
    기존 내용을 버리지 않고 도입→핵심→예시→복습 구조로 확장하도록 안내한다.
    """
    lines = [
        f"아래 음성대본들이 {min_chars}자 미만으로 너무 짧다. "
        "기존 내용을 유지·확장해 각각 900~1600자로 만든다. 절대 내용을 줄이거나 다른 주제로 바꾸지 않는다.\n",
        "확장 구조: ① 도입(왜 중요한지) ② 핵심 설명(원리) ③ 구체적 예시 ④ 마무리 복습.\n",
    ]
    for idx in sorted(short_indices):
        current = _voice_text(payload, idx)
        if current is None:
            continue
        lines.append(
            f"slide {idx} 현재 대본({len(current.strip())}자, 미달):\n{current}\n"
            f"↑ 위 내용을 기반으로 {min_chars}자 이상으로 확장한다.\n"
        )
    lines.append("출력 형식: slide_idx와 script_text 키만 가진 JSON 배열 항목으로 교정한다.")
    return "\n".join(lines)


def _length_error(slide_idx: int, length: int, min_chars: int) -> dict[str, object]:
    return {
        "location": f"{_LOCATION_PREFIX}:slide_{slide_idx}",
        "field": "voice",
        "slide_idx": slide_idx,
        "what_is_wrong": f"음성대본이 {length}자로 {min_chars}자 기준에 미달한다(실측 갭: xgrammar minLength 미강제).",
        "correction": f"기존 내용을 유지하며 도입→핵심→예시→복습 구조로 {min_chars}자 이상 확장한다(축소·내용 변경 금지).",
    }


def _voice_text(payload: GeneratedLessonPayload, slide_idx: int) -> str | None:
    for script in payload.voice_scripts:
        if script.slide_idx == slide_idx:
            return script.script_text
    return None


__all__ = ["length_gate_errors", "short_voice_indices", "voice_extend_user_prompt"]

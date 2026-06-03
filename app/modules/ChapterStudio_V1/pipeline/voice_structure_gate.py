"""voice_script 결정적 구조 게이트 — plan-first 섹션 구조를 LLM 없이 검증한다.

sections가 있는 voice_script에 대해 다음을 순수 함수로 검사한다:
    1. 섹션 수: 정확히 4개
    2. role 완전집합: intro/core/example/closing 모두 있는지
    3. 순서: [intro, core, example, closing] 순서 준수
    4. intro 모드: slide_idx>0인데 intro text가 인사말로 시작하면 오류

sections가 없는 레거시 경로는 no-op(구조 게이트 미적용).

공개 API:
    - structure_gate_errors(payload) -> list[dict[str, object]]
"""
from __future__ import annotations

import re

from app.modules.ChapterStudio_V1.pipeline.payload import (
    VOICE_SECTION_ROLES,
    GeneratedLessonPayload,
)

# 인사말 감지 정규식(voice_cohesion.py의 _GREETING_RE와 동기화).
_GREETING_RE = re.compile(r"^\s*(?:안녕하세요|안녕\b|반갑습니다|반가워요|다들\s*안녕)")

# _VerifyError 계약 접두어.
_LOCATION_PREFIX = "voice_structure_gate"

# 결정적 순서 테이블 — 코드 상수로 관리해 AI가 변경 불가.
_EXPECTED_ROLES: tuple[str, ...] = VOICE_SECTION_ROLES


def structure_gate_errors(
    payload: GeneratedLessonPayload,
) -> list[dict[str, object]]:
    """sections가 있는 voice_script의 구조 오류를 찾아 오류 dict 목록으로 반환한다.

    오류 dict는 content_verify_merge._VerifyError 스키마와 호환된다:
        field="voice", slide_idx=..., location=..., what_is_wrong=..., correction=...
    """
    errors: list[dict[str, object]] = []
    for script in payload.voice_scripts:
        if not script.sections:
            # 레거시 경로: sections 없으면 구조 게이트 미적용.
            continue
        errors.extend(_validate_sections(script.slide_idx, script.sections))
    return errors


def _validate_sections(slide_idx: int, sections: list) -> list[dict[str, object]]:  # list[VoiceSection]
    """단일 voice_script의 sections 구조를 검증한다."""
    errors: list[dict[str, object]] = []
    actual_roles = [sec.role for sec in sections]

    # 검사 1: 섹션 수 정확히 4개.
    if len(sections) != 4:
        errors.append(_struct_error(
            slide_idx,
            "count",
            f"sections 수가 {len(sections)}개이다(정확히 4개 필요).",
            "sections를 [intro, core, example, closing] 4개로 재생성한다.",
        ))
        # 수가 틀리면 이후 순서·role 검사가 의미 없으므로 조기 반환.
        return errors

    # 검사 2: role 완전집합.
    missing = [r for r in _EXPECTED_ROLES if r not in actual_roles]
    if missing:
        errors.append(_struct_error(
            slide_idx,
            "roles",
            f"sections에 {missing} role이 없다.",
            "intro/core/example/closing 4개 role을 모두 포함해야 한다.",
        ))

    # 검사 3: 순서 일치.
    if actual_roles != list(_EXPECTED_ROLES):
        errors.append(_struct_error(
            slide_idx,
            "order",
            f"sections 순서가 {actual_roles}이다(기대: {list(_EXPECTED_ROLES)}).",
            "sections 순서를 [intro, core, example, closing]으로 맞춘다.",
        ))

    # 검사 4: intro 모드 — slide_idx>0인데 인사말로 시작하면 오류.
    if slide_idx > 0:
        intro_sec = next((s for s in sections if s.role == "intro"), None)
        if intro_sec and _GREETING_RE.search(intro_sec.text[:12]):
            errors.append(_struct_error(
                slide_idx,
                "intro_mode",
                f"slide_idx={slide_idx}(첫 슬라이드 아님)인데 intro가 인사말로 시작한다.",
                "첫 슬라이드가 아니므로 인사말 없이 직전 화면에서 이어지는 bridge 문장으로 시작한다.",
            ))

    return errors


def _struct_error(
    slide_idx: int, check: str, what_is_wrong: str, correction: str
) -> dict[str, object]:
    return {
        "location": f"{_LOCATION_PREFIX}:slide_{slide_idx}:{check}",
        "field": "voice",
        "slide_idx": slide_idx,
        "what_is_wrong": what_is_wrong,
        "correction": correction,
    }


__all__ = ["structure_gate_errors"]

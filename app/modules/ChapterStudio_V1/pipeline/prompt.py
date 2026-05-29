from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.app.frontend_contract import depth_label, teacher_label
from app.modules.ChapterStudio_V1.app.study_templates import frame_contract, study_quality_contract, template_contract
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_contract
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState


def build_generation_request(state: ChapterStudioState) -> ChapterAIRequest:
    """상태와 템플릿 계약을 모델이 따를 수 있는 단일 JSON 요청으로 압축한다."""
    slide_count = _state_int(state, "slide_count")
    template_key = _state_text(state, "template_key")
    return ChapterAIRequest(
        system=_system_prompt(slide_count),
        user=_user_prompt(state, slide_count, template_key),
        max_tokens=24000,
        temperature=0.35,
        extra={"slide_count": slide_count, "template_key": template_key},
    )


def _system_prompt(slide_count: int) -> str:
    return (
        "너는 ChapterStudio_V1 프로덕션 강의 생성기다. "
        "응답은 JSON 객체 하나만 출력하고 markdown fence, 설명문, 사고과정은 금지한다. "
        "최상위 키는 slides, quizzes, note_blocks, assignment, voice_scripts 다섯 개만 쓴다. "
        f"slides, quizzes, voice_scripts는 각각 정확히 {slide_count}개다. "
        "slides[i]는 slide_idx, title, focus, checkpoint, category, html, css를 가진다. "
        "category는 text, diagram, code, math, chart, interactive, table 중 하나다. "
        "quizzes[i]는 slide_idx, question, choices, answer_idx, difficulty, explanation을 가진다. "
        "difficulty는 기억, 이해, 적용, 함정 교정, 실전 판단, 오해 중 하나만 쓴다. "
        "voice_scripts[i]는 slide_idx, script_text를 가진다. "
        "모든 html은 section 내부 조각이어야 하며 script 태그와 외부 URL을 쓰지 않는다."
    )


def _user_prompt(state: ChapterStudioState, slide_count: int, template_key: str) -> str:
    reference_block = _optional_state_text(state, "reference_context_prompt")
    return (
        f"강의 요청: {_state_text(state, 'enriched_brief')}\n"
        f"원주제: {_state_text(state, 'topic')}\n"
        f"자료 모드: {_optional_state_text(state, 'source_mode') or 'topic'}\n"
        f"PDF 파일명: {_optional_state_text(state, 'pdf_file_name') or '없음'}\n"
        f"학습 기간: {_state_int(state, 'duration_days')}일\n"
        f"난이도: {depth_label(_optional_state_text(state, 'depth') or 'normal')}\n"
        f"튜터: {teacher_label(_optional_state_text(state, 'teacher') or 'owl')}\n"
        f"튜터 조절값: tone={_state_int(state, 'tone')}, pace={_state_int(state, 'pace')}, "
        f"depth={_state_int(state, 'tutor_depth')}, socratic={_state_int(state, 'socratic')}\n"
        f"참고도서 컨텍스트:\n{reference_block or '제공된 참고도서 없음'}\n"
        f"슬라이드 수: {slide_count}\n"
        f"선택 템플릿: {template_key}\n"
        f"템플릿 계약: {template_contract(template_key)}\n"
        f"튜터 설계 계약: {blueprint_contract(template_key)}\n"
        f"확정 슬라이드 역할:\n{_outline_contract(state)}\n"
        f"슬라이드 프레임:\n{frame_contract(template_key)}\n"
        f"품질 계약: {study_quality_contract()}\n"
        "각 슬라이드는 한국어 1:1 과외 말투로 만들고, 화면에는 핵심 시각자료와 짧은 설명을 둔다. "
        "긴 설명은 voice_scripts에 넣는다. "
        "note_blocks는 3~5개이며 각 블록은 heading과 bullets를 가진다. "
        "assignment는 title, assignment_format, expected_minutes, steps, rubric을 모두 포함한다. "
        "응답 JSON은 Pydantic strict 검증을 통과해야 한다."
    )


def _state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{key} 문자열이 필요하다.")
    return value


def _optional_state_text(state: ChapterStudioState, key: str) -> str:
    value = state.get(key)
    if isinstance(value, str):
        return value
    return ""


def _outline_contract(state: ChapterStudioState) -> str:
    value = state.get("slide_outline")
    if not isinstance(value, list) or not value:
        return "슬라이드 역할 목록 없음"
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            required = item.get("must_have")
            must_have = ", ".join(required) if _is_str_list(required) else ""
            lines.append(
                f"slide {item.get('slide_idx')}: category={item.get('category')}, "
                f"role={item.get('role')}, must_have={must_have}"
            )
    return "\n".join(lines) or "슬라이드 역할 목록 없음"


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _state_int(state: ChapterStudioState, key: str) -> int:
    value = state.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} 정수가 필요하다.")
    return value


__all__ = ["build_generation_request"]

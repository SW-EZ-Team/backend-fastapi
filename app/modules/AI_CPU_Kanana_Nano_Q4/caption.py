"""캡션 생성 진입점. 3단 폴백: Kanana → Jinja2."""
from dataclasses import dataclass
from typing import Literal, Optional

from .config import (
    MAX_TOKENS,
    REPEAT_PENALTY,
    SYSTEM_PROMPT,
    TEMPERATURE,
    TOP_P,
)
from .fallback import render_jinja_caption
from .model_loader import get_llama
from .validator import sanitize


@dataclass(frozen=True)
class CaptionResult:
    text: str
    source: Literal["kanana", "fallback"]
    char_count: int


def generate_caption(
    *,
    student_name: str,
    assignment_name: str,
    weakness: Optional[str] = None,
    difficulty: Optional[str] = None,
    deadline: Optional[str] = None,
) -> CaptionResult:
    """학생·과제 정보 기반 20~100자 캡션을 만든다.

    Kanana 추론 실패 또는 검증 실패 시 Jinja2 템플릿으로 폴백한다.
    """
    user_prompt = _build_user_prompt(
        student_name, assignment_name, weakness, difficulty, deadline
    )

    raw = _run_kanana(user_prompt)
    clean = sanitize(raw)
    if clean is not None:
        return CaptionResult(text=clean, source="kanana", char_count=len(clean))

    fb = render_jinja_caption(
        student_name=student_name,
        assignment_name=assignment_name,
        weakness=weakness,
        deadline=deadline,
    )
    return CaptionResult(text=fb, source="fallback", char_count=len(fb))


def _build_user_prompt(name, assignment, weakness, difficulty, deadline) -> str:
    """유저 프롬프트 문자열을 조립한다."""
    parts = [f"학생명: {name}", f"과제명: {assignment}"]
    if weakness:
        parts.append(f"약점: {weakness}")
    if difficulty:
        parts.append(f"난이도: {difficulty}")
    if deadline:
        parts.append(f"마감: {deadline}")
    return ", ".join(parts)


def _run_kanana(user_prompt: str) -> str:
    """Kanana 모델로 캡션을 생성하고 원시 문자열을 반환한다."""
    llm = get_llama()
    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=TEMPERATURE,
        top_p=TOP_P,
        max_tokens=MAX_TOKENS,
        repeat_penalty=REPEAT_PENALTY,
    )
    return resp["choices"][0]["message"]["content"]

"""캡션 생성 진입점. 3단 폴백: Gemini → Kanana → Jinja2."""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from common.text_config import google_api_key
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

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptionResult:
    text: str
    source: Literal["gemini", "kanana", "fallback"]
    char_count: int


def generate_caption(
    *,
    student_name: str,
    assignment_name: str,
    weakness: str | None = None,
    difficulty: str | None = None,
    deadline: str | None = None,
) -> CaptionResult:
    """학생·과제 정보 기반 20~100자 캡션을 만든다.

    Gemini/Kanana 추론 실패 또는 검증 실패 시 Jinja2 템플릿으로 폴백한다.
    """
    user_prompt = _build_user_prompt(
        student_name, assignment_name, weakness, difficulty, deadline
    )

    clean = sanitize(_run_gemini(user_prompt))
    if clean is not None:
        return CaptionResult(text=clean, source="gemini", char_count=len(clean))

    clean = sanitize(_run_kanana_safely(user_prompt))
    if clean is not None:
        return CaptionResult(text=clean, source="kanana", char_count=len(clean))

    fb = render_jinja_caption(
        student_name=student_name,
        assignment_name=assignment_name,
        weakness=weakness,
        deadline=deadline,
    )
    return CaptionResult(text=fb, source="fallback", char_count=len(fb))


def _build_user_prompt(
    name: str,
    assignment: str,
    weakness: str | None,
    difficulty: str | None,
    deadline: str | None,
) -> str:
    """유저 프롬프트 문자열을 조립한다."""
    parts = [f"학생명: {name}", f"과제명: {assignment}"]
    if weakness:
        parts.append(f"약점: {weakness}")
    if difficulty:
        parts.append(f"난이도: {difficulty}")
    if deadline:
        parts.append(f"마감: {deadline}")
    return ", ".join(parts)


def _run_gemini(user_prompt: str) -> str | None:
    """시연용 Gemini 캡션을 생성한다. 실패하면 다음 백엔드로 넘긴다."""
    if not _should_try_gemini():
        return None
    try:
        return _run_gemini_sync(user_prompt)
    except Exception as exc:
        # 캡션은 알림 보조 문구라 외부 API 장애보다 폴백 보장이 우선이다
        _LOG.warning("[caption] Gemini 캡션 생성 실패, Kanana 폴백으로 이동 — error=%s", exc)
        return None


def _should_try_gemini() -> bool:
    """CAPTION_BACKEND와 Gemini 키 존재 여부로 시연 경로를 켠다."""
    backend = os.getenv("CAPTION_BACKEND", "auto").strip().lower()
    return backend in {"auto", "gemini"} and google_api_key() is not None


def _run_gemini_sync(user_prompt: str) -> str:
    """비동기 커넥터를 동기 캡션 API에서 안전하게 실행한다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_generate_gemini_text(user_prompt))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            lambda: asyncio.run(_generate_gemini_text(user_prompt))
        )
        return future.result()


async def _generate_gemini_text(user_prompt: str) -> str:
    """Gemini 텍스트 커넥터를 캡션 공통 스키마로 호출한다."""
    from ai_connectors.text.gemini_connector import GeminiGenAIConnector
    from ai_connectors.text_schemas import ChapterAIRequest

    connector = GeminiGenAIConnector()
    try:
        response = await connector.generate(
            ChapterAIRequest(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )
        )
        return response.text
    finally:
        await connector.aclose()


def _run_kanana_safely(user_prompt: str) -> str | None:
    """Kanana 모델이 없거나 실패해도 Jinja 폴백까지 진행한다."""
    try:
        return _run_kanana(user_prompt)
    except Exception as exc:
        # 로컬 GGUF 파일 부재는 정상 폴백 조건이므로 파이프라인은 계속 진행한다
        _LOG.warning("[caption] Kanana 캡션 생성 실패, Jinja2 폴백으로 이동 — error=%s", exc)
        return None


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

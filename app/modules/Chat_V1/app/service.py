"""Chat_V1 핵심 서비스 — 강의 컨텍스트 주입 후 Claude Sonnet 호출.

강의 자료를 시스템 프롬프트에 삽입하고 학생 질문에 답변한다.
슬라이드 참조 번호는 응답 텍스트에서 파싱해 구조화한다.
"""
from __future__ import annotations

import re

from ai_connectors.text.claude_sonnet_connector import ClaudeSonnetConnector
from ai_connectors.text_schemas import ChapterAIRequest

from app.modules.Chat_V1.app.schemas import ChatRequest, ChatResponse, SlideContext, VoiceChatRequest
from app.modules.Chat_V1.pipeline.graph import run_chat_pipeline

# Claude Sonnet 요청 설정 상수
_MAX_TOKENS: int = 1024
_TEMPERATURE: float = 0.3


async def answer_question(request: ChatRequest) -> ChatResponse:
    """채팅 요청을 파이프라인에 통과시켜 구조화된 응답을 반환한다.

    파이프라인이 validate_input → generate_answer → format_response 순으로
    실행되며, 최종 상태에서 ChatResponse를 조립한다.
    """
    final_state = await run_chat_pipeline(request)
    return ChatResponse(
        session_id=request.session_id,
        answer=final_state["answer"],
        referenced_slides=final_state["referenced_slides"],
    )


def build_system_prompt(request: ChatRequest | VoiceChatRequest) -> str:
    """강의 컨텍스트를 포함한 시스템 프롬프트를 생성한다.

    Claude에게 강의 내용 범위 안에서만 답변하고 슬라이드 번호를
    명시하도록 지시한다. 범위 밖 질문은 정중히 안내한다.
    """
    ctx = request.lecture_context
    slides_text = _format_slides(ctx.slides)

    optional_sections: list[str] = []
    if ctx.voice_scripts:
        joined = "\n".join(ctx.voice_scripts)
        optional_sections.append(f"[음성대본]\n{joined}")
    if ctx.quiz_items:
        joined = "\n".join(ctx.quiz_items)
        optional_sections.append(f"[퀴즈 항목]\n{joined}")

    extra = ("\n\n" + "\n\n".join(optional_sections)) if optional_sections else ""

    return (
        f"당신은 '{ctx.chapter_title}' 강의의 학습 도우미예요.\n"
        "아래 강의 자료를 바탕으로 학생의 질문에 친절하게 답변해 주세요.\n\n"
        f"[강의 슬라이드]\n{slides_text}{extra}\n\n"
        "답변 규칙:\n"
        "1. 반드시 위 강의 자료에 있는 내용만 근거로 답변해요.\n"
        "2. 슬라이드 번호를 인용할 때는 '[슬라이드 N]' 형식을 사용해요.\n"
        "3. 강의 범위 밖의 질문이면 '이 강의에서는 다루지 않는 내용이에요. "
        "관련 슬라이드를 함께 확인해 보시겠어요?'라고 안내해요.\n"
        "4. 해요체(~해요, ~예요)를 사용해요."
    )


def extract_referenced_slides(answer: str) -> list[int]:
    """답변 텍스트에서 '[슬라이드 N]' 패턴의 슬라이드 인덱스를 추출한다.

    중복 제거 후 오름차순으로 반환한다. 인덱스는 0-based로 변환한다.
    """
    # '[슬라이드 N]' 패턴에서 N을 추출 — 1-based 표기를 0-based로 변환
    matches = re.findall(r"\[슬라이드\s+(\d+)\]", answer)
    seen: set[int] = set()
    result: list[int] = []
    for m in matches:
        idx = int(m) - 1  # 1-based → 0-based
        if idx >= 0 and idx not in seen:
            seen.add(idx)
            result.append(idx)
    return sorted(result)


async def call_claude_sonnet(system_prompt: str, user_message: str) -> str:
    """Claude Sonnet 커넥터를 호출해 답변 텍스트를 반환한다."""
    connector = ClaudeSonnetConnector()
    try:
        req = ChapterAIRequest(
            system=system_prompt,
            user=user_message,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
        )
        response = await connector.generate(req)
        return response.text
    finally:
        await connector.aclose()


def _format_slides(slides: list[SlideContext]) -> str:
    """슬라이드 목록을 프롬프트용 텍스트로 변환한다."""
    lines: list[str] = []
    for slide in slides:
        # slide_idx는 0-based이므로 프롬프트에는 1-based로 표시
        lines.append(
            f"[슬라이드 {slide.slide_idx + 1}] {slide.title}\n{slide.content}"
        )
    return "\n\n".join(lines)

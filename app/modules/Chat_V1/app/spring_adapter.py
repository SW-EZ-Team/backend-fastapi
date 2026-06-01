"""Spring ↔ FastAPI 채팅 연결 어댑터.

Spring `ChatService.callFastapi`가 `POST {base}/api/chat` 로 snake_case 바디를
전송하고 동기 JSON 응답을 기대한다(2xx + body, 실패 시 CHAT_001).

이 어댑터의 책임은 순수 매핑 + 호출뿐이다:
  Spring 바디(dict) → ChatRequest 변환 → answer_question 호출 →
  ChatResponse → Spring이 추출하는 키(response_text, citations) 형태로 반환.

Spring과 Chat_V1의 스키마 필드명이 다르므로(예: message↔user_message,
referenced_slides↔citations) 불일치는 전부 이 어댑터 안에서 변환한다.
AI 커넥터·파이프라인은 일절 건드리지 않는다(answer_question 내부 위임).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.modules.Chat_V1.app.schemas import (
    ChatRequest,
    ChatResponse,
    LectureContext,
    SlideContext,
)
from app.modules.Chat_V1.app.service import answer_question

_LOG = logging.getLogger(__name__)

# 데코레이터에 절대 경로를 직접 적어 prefix 없이 Spring 기대 경로(/api/chat)에 노출한다.
router = APIRouter(tags=["chat-spring-adapter"])


@router.post("/api/chat")
async def chat_from_spring(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Spring 채팅 요청을 Chat_V1 파이프라인으로 프록시한다(동기).

    Spring은 2xx + body 를 성공으로 간주하므로, 내부 처리 실패 시에도
    5xx로 떨어뜨려 Spring이 CHAT_001을 일관되게 처리하도록 한다.
    """
    chat_request = _to_chat_request(body)
    try:
        result = await answer_question(chat_request)
    except ValueError as exc:
        # 입력 검증 실패 — Spring 입장에선 비정상 요청
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 모델·커넥터 실행 실패
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _to_spring_response(result)


def _to_chat_request(body: dict[str, Any]) -> ChatRequest:
    """Spring snake_case 바디를 Chat_V1 ChatRequest로 변환한다.

    Spring은 슬라이드 본문을 보내지 않고 식별자(slide_id/slide_idx)와
    context(tutor/course/recent_qa)만 보낸다. 그러나 ChatRequest는
    비어 있지 않은 LectureContext.slides 를 요구하므로, context에서
    얻은 메타로 최소한의 유효한 LectureContext를 합성한다.
    """
    message = _as_str(body.get("message")).strip()
    if not message:
        # ChatRequest.user_message 는 min_length=1 — 빈 메시지는 명시적 거부
        raise HTTPException(status_code=422, detail="message는 비어 있을 수 없어요.")

    context = body.get("context")
    context = context if isinstance(context, dict) else {}

    # 선택 텍스트가 있으면 질문 앞에 인용으로 덧붙여 모델이 맥락을 잡게 한다.
    selected_text = _as_str(body.get("selected_text")).strip()
    user_message = (
        f"[선택한 내용]\n{selected_text}\n\n[질문]\n{message}" if selected_text else message
    )

    return ChatRequest(
        session_id=_build_session_id(body),
        user_message=user_message,
        lecture_context=_build_lecture_context(context),
    )


def _build_session_id(body: dict[str, Any]) -> str:
    """tutoring_id + lesson_id 조합으로 안정적인 세션 식별자를 만든다.

    Spring은 명시적 session_id를 보내지 않으므로 과외·강의 식별자로 합성한다.
    둘 다 없으면 'unknown'으로 폴백해 min_length=1 검증을 통과시킨다.
    """
    tutoring_id = _as_str(body.get("tutoring_id")).strip()
    lesson_id = _as_str(body.get("lesson_id")).strip()
    parts = [p for p in (tutoring_id, lesson_id) if p]
    return ":".join(parts) if parts else "unknown"


def _build_lecture_context(context: dict[str, Any]) -> LectureContext:
    """Spring context 메타로 최소 유효 LectureContext를 합성한다.

    Spring은 슬라이드 본문을 전달하지 않으므로 lesson_title/course_subject로
    단일 안내 슬라이드를 구성한다. recent_qa(이전 문답)는 voice_scripts 자리에
    실어 모델이 대화 맥락을 참고하도록 한다.
    """
    lesson_title = _as_str(context.get("lesson_title")).strip()
    course_subject = _as_str(context.get("course_subject")).strip()

    chapter_title = lesson_title or course_subject or "학습 대화"
    # SlideContext.title/content 는 min_length=1 — 빈 값이 되지 않도록 폴백을 둔다.
    slide_content = (
        f"과목: {course_subject or '미지정'} / 강의: {lesson_title or '미지정'}.\n"
        "별도 슬라이드 본문 없이 전달된 학습 대화 요청이에요."
    )
    slides = [SlideContext(slide_idx=0, title=chapter_title, content=slide_content)]

    voice_scripts = _format_recent_qa(context.get("recent_qa"))

    return LectureContext(
        chapter_title=chapter_title,
        slides=slides,
        voice_scripts=voice_scripts,
        quiz_items=None,
    )


def _format_recent_qa(recent_qa: Any) -> list[str] | None:
    """Spring recent_qa([{question, answer}, ...])를 텍스트 줄 목록으로 변환한다.

    voice_scripts(list[str]) 자리에 실어 모델이 직전 대화를 참고하게 한다.
    형식이 어긋나면 None을 반환해 선택 필드를 비운다.
    """
    if not isinstance(recent_qa, list) or not recent_qa:
        return None
    lines: list[str] = []
    for qa in recent_qa:
        if not isinstance(qa, dict):
            continue
        question = _as_str(qa.get("question")).strip()
        answer = _as_str(qa.get("answer")).strip()
        if question or answer:
            lines.append(f"Q: {question}\nA: {answer}")
    return lines or None


def _to_spring_response(result: ChatResponse) -> dict[str, Any]:
    """Chat_V1 ChatResponse를 Spring이 추출하는 키 형태로 변환한다.

    Spring extractString("response_text") + extractStringList("citations").
    Chat_V1의 referenced_slides(0-based int)는 Spring 표시 규약에 맞춰
    '[슬라이드 N]'(1-based) 문자열 목록으로 변환한다.
    """
    citations = [f"[슬라이드 {idx + 1}]" for idx in result.referenced_slides]
    return {
        "response_text": result.answer,
        "citations": citations,
        # 디버깅·추적용 부가 필드 — Spring extractString/extractStringList는 무시한다.
        "session_id": result.session_id,
    }


def _as_str(value: Any) -> str:
    """None-안전 문자열 변환. None이면 빈 문자열을 반환한다."""
    return "" if value is None else str(value)

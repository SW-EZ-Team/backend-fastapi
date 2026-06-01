"""Chat_V1 핵심 서비스 — 강의 컨텍스트 주입 후 활성 텍스트 모델 호출.

강의 자료를 시스템 프롬프트에 삽입하고 학생 질문에 답변한다.
슬라이드 참조 번호는 응답 텍스트에서 파싱해 구조화한다.

벤더 중립: 특정 커넥터(Claude 등)를 직접 생성하지 않고 registry 의
get_text_connector() 로 ACTIVE_TEXT_MODEL 이 가리키는 커넥터를 받는다.
관리자가 .env 값 하나(codex_cli ↔ claude_sonnet ↔ Qwen 등)만 바꾸면
Chat 호출 경로도 함께 스왑된다.
"""
from __future__ import annotations

from ai_connectors.registry import get_text_connector
from ai_connectors.text_schemas import ChapterAIRequest

from app.modules.Chat_V1.app.schemas import ChatRequest, ChatResponse, SlideContext, VoiceChatRequest
from app.modules.Chat_V1.app.scope_guard import (
    OUT_OF_SCOPE_REPLY,
    apply_hallucination_guard,
    build_lecture_keywords,
    extract_referenced_slides,
)
from app.modules.Chat_V1.pipeline.graph import run_chat_pipeline

# 범위 가드 순수 함수는 scope_guard 모듈에 두고 여기서 재수출한다 — 기존 호출부
# (voice_nodes 등)가 service 경유 import 를 유지하도록 facade 역할을 한다.
__all__ = [
    "answer_question",
    "build_system_prompt",
    "call_text_model",
    "extract_referenced_slides",
    "build_lecture_keywords",
    "apply_hallucination_guard",
]

# 텍스트 모델 요청 설정 상수 (벤더 무관)
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
        "2. 강의 자료를 근거로 답할 때는 반드시 '[슬라이드 N]' 형식으로 출처를 표기해요 "
        "(인용이 자연스럽지 않아도 문장 끝에 붙여요).\n"
        "3. 두 개념을 비교하거나 학생이 헷갈릴 만한 질문이면, 정의 뒤에 강의 자료 범위 안에서 "
        "짧은 대조 예시 1개를 들어 구분을 명확히 해요. 예시는 1~2줄, 장황하지 않게.\n"
        "4. 단순 정의만 나열하지 말고, 핵심 + 짧은 예시(강의 자료 범위 안)로 과외쌤처럼 "
        "설명해요. 단, 강의에 없는 내용을 만들어 내지 않아요.\n"
        f"5. 강의 범위 밖의 질문이면 '{OUT_OF_SCOPE_REPLY}'라고 안내해요.\n"
        "6. 해요체(~해요, ~예요)를 사용해요.\n\n"
        + _FEW_SHOT_BLOCK
    )


# few-shot 예시 — 세 가지 답변 형식을 한 번에 보여준다.
#   예시 A: 단순 개념 질문 → 핵심 + 예시 + 슬라이드 인용(항상 붙임)
#   예시 B: 비교/혼동 가능 질문 → 정의 + 대조 예시 + 슬라이드 인용
#   예시 C: 강의 범위 밖 질문 → 거절문
_FEW_SHOT_BLOCK: str = (
    "[예시]\n"
    "질문: 이 개념이 왜 중요한지 알려줘.\n"
    "답변: 이 개념은 뒤에 나오는 내용을 이해하는 핵심 토대예요. 예를 들어, "
    "이 개념을 모르면 다음 단계에서 막히는 경우가 많아요. [슬라이드 2]\n"
    "질문: A랑 B가 어떻게 달라요?\n"
    "답변: 둘이 헷갈리기 쉽죠! [슬라이드 1]에 따르면 A는 ○○이고, B는 △△예요. "
    "간단히 비교하면, A는 '입력을 받는 이름'이고 B는 '실제로 넣는 값'이에요. "
    "예: def f(x)에서 x가 A, f(3)의 3이 B예요.\n"
    "질문: 오늘 환율 전망이 어때?\n"
    f"답변: {OUT_OF_SCOPE_REPLY}"
)


async def call_text_model(system_prompt: str, user_message: str) -> str:
    """활성 텍스트 모델 커넥터를 호출해 답변 텍스트를 반환한다.

    registry 의 get_text_connector() 로 ACTIVE_TEXT_MODEL 커넥터를 받으므로
    Claude·codex·Qwen 어느 모델로 바뀌어도 호출 코드는 동일하다.

    root 레지스트리(_registry_text)는 호출마다 새 인스턴스를 만들고 lifespan 이
    텍스트 커넥터를 관리하지 않는다. 따라서 이 호출이 만든 커넥터는 이 호출이
    책임지고 닫되, 네트워크 클라이언트를 가진 커넥터(예: Claude)만 aclose 를
    노출하므로 aclose 가 있을 때만 호출한다(codex CLI 등은 닫을 자원이 없다).
    """
    connector = get_text_connector()
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
        await _aclose_if_supported(connector)


async def _aclose_if_supported(connector: object) -> None:
    """커넥터가 aclose 를 노출하면 호출해 네트워크 리소스를 정리한다.

    codex CLI 처럼 닫을 자원이 없는 커넥터는 aclose 가 없으므로 건너뛴다.
    벤더별 커넥터 종류를 호출부가 알 필요 없도록 능력 유무로만 판단한다.
    """
    aclose = getattr(connector, "aclose", None)
    if callable(aclose):
        await aclose()


def _format_slides(slides: list[SlideContext]) -> str:
    """슬라이드 목록을 프롬프트용 텍스트로 변환한다."""
    lines: list[str] = []
    for slide in slides:
        # slide_idx는 0-based이므로 프롬프트에는 1-based로 표시
        lines.append(
            f"[슬라이드 {slide.slide_idx + 1}] {slide.title}\n{slide.content}"
        )
    return "\n\n".join(lines)

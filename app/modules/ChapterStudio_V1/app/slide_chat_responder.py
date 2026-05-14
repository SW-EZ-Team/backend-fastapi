from __future__ import annotations

from collections.abc import AsyncIterator

from app.modules.ChapterStudio_V1.app.codex_chat_pipeline import generate_codex_chat_answer
from app.modules.ChapterStudio_V1.app.slide_chat_types import ChatIntent, SlideChatContext, SlideChatRequest


async def stream_chat_response(req: SlideChatRequest, ctx: SlideChatContext) -> AsyncIterator[str]:
    """엔진 선택에 따라 mock 또는 Codex OAuth 답변을 스트림처럼 흘린다."""
    text = await generate_codex_chat_answer(req, ctx) if req.engine == "codex_cli" else _answer(req, ctx)
    for chunk in _chunk(text):
        yield chunk


def classify_question(message: str) -> ChatIntent:
    """질문 유형을 먼저 좁혀 채팅 AI 프롬프트를 작게 만든다."""
    lowered = message.lower()
    if any(word in lowered for word in ("코드", "class", "def", "변수", "함수", "import")):
        return "code"
    if any(word in lowered for word in ("차트", "그래프", "색", "막대", "통계")):
        return "chart"
    if any(word in lowered for word in ("퀴즈", "정답", "선지", "문제")):
        return "quiz"
    if any(word in lowered for word in ("헷갈", "모르", "왜", "이해")):
        return "confusion"
    if any(word in lowered for word in ("예시", "적용", "다른", "실전")):
        return "transfer"
    return "definition"


def _answer(req: SlideChatRequest, ctx: SlideChatContext) -> str:
    intent = classify_question(req.message)
    selected = f"\n선택한 문장: {req.selected_text}" if req.selected_text else ""
    return (
        f"질문 의도: {_intent_label(intent)}\n"
        f"현재 슬라이드: {ctx.slide_title} ({ctx.slide_role}, {ctx.category})\n"
        f"사용자가 막힌 지점: {req.message}{selected}\n\n"
        f"핵심 답변: 이 슬라이드는 '{ctx.focus}'를 잡기 위한 장면입니다. "
        f"방금 음성대본에서는 '{_short(ctx.voice_script)}'라고 설명했으니, "
        f"답은 슬라이드 밖 새 지식보다 그 설명을 다시 머리에 들어오게 정리하는 쪽이 맞습니다.\n\n"
        f"머리에 넣을 문장: {ctx.note_bullets[0]}\n"
        f"취약점 연결: {ctx.weak_points}\n"
        f"바로 점검: {ctx.checkpoint}\n"
        f"다음으로 볼 부분: {ctx.next_role}\n\n"
        f"튜터 방식: {ctx.tutor_style}. {_follow_up(intent)}"
    )


def _intent_label(intent: ChatIntent) -> str:
    return {
        "definition": "개념 확인",
        "code": "코드 해석",
        "chart": "시각 자료 해석",
        "quiz": "퀴즈 풀이",
        "confusion": "오개념 정리",
        "transfer": "적용 예시",
    }[intent]


def _follow_up(intent: ChatIntent) -> str:
    if intent == "quiz":
        return "정답은 DB의 answer_idx로 판정하고, 저는 왜 그 선지가 맞는지 설명합니다."
    if intent == "code":
        return "변수명, 함수, class 역할을 한 줄씩 끊어 설명하겠습니다."
    if intent == "chart":
        return "색은 분류 의미를 유지하고, 수치보다 비교 관계를 먼저 읽게 하겠습니다."
    return "답을 외우기보다 왜 그런 관점이 나왔는지 한 번 더 물어보겠습니다."


def _short(value: str) -> str:
    return value[:130] + ("..." if len(value) > 130 else "")


def _chunk(value: str) -> list[str]:
    lines = value.splitlines(keepends=True)
    return [line for line in lines if line]

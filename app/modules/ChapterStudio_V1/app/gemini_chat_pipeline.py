from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.app.slide_chat_types import SlideChatContext, SlideChatRequest

# 강의 범위 밖 질문에 대한 한 줄 안내문 — Chat_V1 scope_guard.SCOPE_NOTICE와 동일 문구.
# 모듈 간 직접 의존 금지 규칙 때문에 import 대신 같은 문구를 미러링한다(거절 금지 정책).
SCOPE_NOTICE: str = "이 내용은 이번 강의 범위 밖이에요."


async def generate_gemini_chat_answer(req: SlideChatRequest, ctx: SlideChatContext) -> str:
    """활성 Gemini 커넥터로 슬라이드 동반 튜터 답변을 만든다."""
    response = await get_text_connector().generate(
        ChapterAIRequest(
            # gemini_flash thinking 토큰(~21000)이 max_output_tokens 예산을 먼저 잠식한다.
            # 1200에서는 thinking만으로 즉시 절단돼 답변 본문이 비거나 잘린다. thinking 헤드룸을
            # 확보해 24000으로 올린다(짧은 채팅 답변이라 실제 과금 토큰은 작다).
            system=_system_prompt(),
            user=_user_prompt(req, ctx),
            max_tokens=24000,
            temperature=0.2,
        )
    )
    return response.text.strip()


def _system_prompt() -> str:
    return (
        "너는 ChapterStudio_V1의 현재 슬라이드 동반 AI 과외 튜터다. "
        "리포지토리, 파일, 웹, 개인정보 같은 외부 시스템은 보지 않는다. "
        "강의 자료(슬라이드·음성대본)는 참고 자료이지 답변의 한계가 아니다 — "
        "자료에 있는 내용은 자료를 우선 근거로 답하고, 자료 밖 질문도 절대 거절하지 말고 "
        "정확한 일반 지식으로 답한 뒤 마지막에 "
        f"'{SCOPE_NOTICE}' 한 줄만 덧붙인다. "
        "'슬라이드에 없어서 답변할 수 없다'류의 거절문은 어떤 경우에도 출력하지 않는다. "
        "답변은 한국어로, 과외처럼 짧은 진단 → 핵심 관점 → 예시 → 바로 확인 질문 순서로 쓴다. "
        "퀴즈 정답은 문제와 분리해 설명하고, 모르면 새 정답을 만들지 말고 확인 기준을 말한다."
    )


def _user_prompt(req: SlideChatRequest, ctx: SlideChatContext) -> str:
    selected = req.selected_text or "없음"
    bullets = "\n".join(f"- {item}" for item in ctx.note_bullets[:5])
    return (
        f"주제: {req.topic}\n"
        f"사용자 질문: {req.message}\n"
        f"선택 문장: {selected}\n"
        f"재생 위치: {req.playback_sec:.1f}초\n"
        f"튜터 스타일: {ctx.tutor_style}\n"
        f"학습자 수준: {req.audience_level}\n"
        f"취약점: {ctx.weak_points}\n\n"
        f"현재 슬라이드: {ctx.slide_title}\n"
        f"슬라이드 역할: {ctx.slide_role}\n"
        f"카테고리: {ctx.category}\n"
        "강의 구조: 이 테스트는 커리큘럼 전체 중 강의 1개를 5슬라이드로 생성하고, 퀴즈는 강의 끝에 별도 평가로 둔다.\n"
        f"학습 초점: {ctx.focus}\n"
        f"자가 점검: {ctx.checkpoint}\n"
        f"이전/다음 역할: {ctx.previous_role} / {ctx.next_role}\n\n"
        f"음성대본:\n{ctx.voice_script}\n\n"
        f"핵심노트:\n{bullets}\n\n"
        "출력 규칙:\n"
        "1. 첫 줄은 사용자가 왜 헷갈렸는지 한 문장으로 진단한다.\n"
        "2. 개요라는 단어를 쓰지 말고, 이 주제를 보는 철학과 관점을 설명한다.\n"
        "3. 추가 질문과 확장 질문도 가능하면 현재 강의 내용에서 출발해 답한다.\n"
        "4. 슬라이드와 음성대본에 있는 내용은 그것을 우선 근거로 답한다. "
        f"자료 밖 질문이면 일반 지식으로 정확히 답하고 끝에 '{SCOPE_NOTICE}'를 덧붙인다. 거절은 금지다.\n"
        "5. 마지막 줄은 사용자가 바로 대답할 수 있는 점검 질문으로 끝낸다."
    )

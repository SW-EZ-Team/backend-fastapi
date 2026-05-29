"""Chat_V1 LangGraph 노드 함수들.

각 노드는 순수하게 상태를 받아 업데이트된 상태를 반환한다.
노드마다 단일 책임을 갖도록 분리되어 있다.
"""
from __future__ import annotations

from ai_connectors.errors import AIConnectorError

from app.modules.Chat_V1.pipeline.state import ChatState


def validate_input(state: ChatState) -> ChatState:
    """입력 유효성을 검증하고 시스템 프롬프트를 상태에 기록한다.

    user_message나 system_prompt가 비어 있으면 error_message를 설정한다.
    """
    if not state.get("user_message", "").strip():
        return {**state, "error_message": "학생 질문이 비어 있어요.", "pipeline_status": "invalid_input"}
    if not state.get("system_prompt", "").strip():
        return {**state, "error_message": "강의 컨텍스트가 없어요.", "pipeline_status": "invalid_input"}
    return {**state, "pipeline_status": "validated"}


async def generate_answer(state: ChatState) -> ChatState:
    """Claude Sonnet을 호출해 raw_answer를 채운다.

    오류 발생 시 error_message에 기록하고 파이프라인 상태를 failed로 설정한다.
    """
    if state.get("error_message"):
        # 이전 노드에서 오류가 났으면 그대로 통과
        return state

    from app.modules.Chat_V1.app.service import call_claude_sonnet

    try:
        raw = await call_claude_sonnet(
            system_prompt=state["system_prompt"],
            user_message=state["user_message"],
        )
    except AIConnectorError as exc:
        return {**state, "error_message": str(exc), "pipeline_status": "failed"}

    return {**state, "raw_answer": raw, "pipeline_status": "answered"}


def format_response(state: ChatState) -> ChatState:
    """raw_answer에서 슬라이드 참조를 추출하고 최종 answer를 확정한다.

    오류 상태이면 answer에 안내 문구를 설정해 사용자가 빈 응답을 받지 않도록 한다.
    """
    if state.get("error_message"):
        return {
            **state,
            "answer": "죄송해요, 답변을 생성하는 중에 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
            "referenced_slides": [],
            "pipeline_status": "error_handled",
        }

    from app.modules.Chat_V1.app.service import extract_referenced_slides

    raw = state.get("raw_answer", "")
    refs = extract_referenced_slides(raw)
    return {**state, "answer": raw, "referenced_slides": refs, "pipeline_status": "done"}

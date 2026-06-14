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
    """활성 텍스트 모델을 호출해 raw_answer를 채운다.

    벤더 중립 커넥터(get_text_connector)를 거치므로 모델이 바뀌어도 동일하다.
    오류 발생 시 error_message에 기록하고 파이프라인 상태를 failed로 설정한다.
    """
    if state.get("error_message"):
        # 이전 노드에서 오류가 났으면 그대로 통과
        return state

    from app.modules.Chat_V1.app.service import call_text_model

    try:
        raw = await call_text_model(
            system_prompt=state["system_prompt"],
            user_message=state["user_message"],
        )
    except AIConnectorError as exc:
        return {**state, "error_message": str(exc), "pipeline_status": "failed"}

    return {**state, "raw_answer": raw, "pipeline_status": "answered"}


def format_response(state: ChatState) -> ChatState:
    """raw_answer를 정제해 최종 answer·슬라이드 참조를 확정한다.

    처리 순서:
      1) strip_thinking — Qwen 류의 <think> reasoning 이 채팅에 노출되지 않게 제거.
      2) 범위 가드 — 강의 자료와 안 겹치는 답변은 유지하되 끝에 범위 밖 안내문만 덧붙인다.
      3) 슬라이드 인용 추출 — slide_count 상한까지 검증해 없는 슬라이드 참조를 버린다.
    오류 상태이면 answer에 안내 문구를 설정해 사용자가 빈 응답을 받지 않도록 한다.
    """
    if state.get("error_message"):
        return {
            **state,
            "answer": "죄송해요, 답변을 생성하는 중에 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
            "referenced_slides": [],
            "pipeline_status": "error_handled",
        }

    from common.llm_output import strip_thinking

    from app.modules.Chat_V1.app.service import (
        apply_hallucination_guard,
        extract_referenced_slides,
    )

    raw = state.get("raw_answer", "")
    # 1) reasoning 블록 제거 — 모델이 바뀌어도 <think> 가 답변에 새지 않게 한다.
    answer = strip_thinking(raw)

    # 2) 범위 가드 — 강의 키워드와 매칭 안 되면 답변은 유지하고 범위 밖 안내문만 덧붙인다.
    answer, guarded = apply_hallucination_guard(
        answer, state.get("lecture_keywords", [])
    )

    # 3) 슬라이드 인용 추출 + 상한 검증. 범위 밖 답변엔 인용이 없으므로 자연히 [].
    slide_count = state.get("slide_count")
    refs = extract_referenced_slides(answer, slide_count)
    status = "guarded" if guarded else "done"
    return {**state, "answer": answer, "referenced_slides": refs, "pipeline_status": status}

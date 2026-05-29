from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector
from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload, payload_to_state
from app.modules.ChapterStudio_V1.pipeline.prompt import build_generation_request
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState


async def generate_lesson_node(state: ChapterStudioState) -> ChapterStudioState:
    """활성 텍스트 커넥터로 강의 JSON을 생성하고 상태 조각으로 변환한다."""
    connector = get_text_connector()
    request = build_generation_request(state)
    response = await connector.generate(request)
    payload = parse_payload(response.text, _state_int(state, "slide_count"))
    delta = payload_to_state(payload)
    delta["generation_model"] = response.model
    return delta


def _state_int(state: ChapterStudioState, key: str) -> int:
    value = state.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} 정수가 필요하다.")
    return value


__all__ = ["generate_lesson_node"]

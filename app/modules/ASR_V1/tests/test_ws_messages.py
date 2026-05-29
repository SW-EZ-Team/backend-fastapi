"""ws_messages Pydantic 모델 단위 테스트.

각 메시지 타입의 직렬화/역직렬화와 필드 검증을 확인한다.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ASR_V1.schemas.ws_messages import (
    ErrorMessage,
    FinalTranscript,
    FlushSegment,
    PartialTranscript,
    SessionAck,
    VADStateMessage,
)


def test_vad_state_message_speaking_true() -> None:
    """VADStateMessage speaking=True가 정확히 직렬화된다."""
    msg = VADStateMessage(speaking=True)
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "vad_state"
    assert data["speaking"] is True


def test_vad_state_message_speaking_false() -> None:
    """VADStateMessage speaking=False가 정확히 직렬화된다."""
    msg = VADStateMessage(speaking=False)
    data = json.loads(msg.model_dump_json())
    assert data["speaking"] is False


def test_partial_transcript() -> None:
    """PartialTranscript type 필드와 text가 올바르다."""
    msg = PartialTranscript(text="안녕하세요")
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "partial"
    assert data["text"] == "안녕하세요"


def test_final_transcript_all_fields() -> None:
    """FinalTranscript의 모든 필드가 직렬화된다."""
    msg = FinalTranscript(
        text="확정 전사 텍스트",
        turn_id="abc-123",
        duration_sec=2.5,
        latency_ms=120.0,
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "final"
    assert data["text"] == "확정 전사 텍스트"
    assert data["turn_id"] == "abc-123"
    assert data["duration_sec"] == pytest.approx(2.5)
    assert data["latency_ms"] == pytest.approx(120.0)


def test_flush_segment_list() -> None:
    """FlushSegment segments 목록이 올바르다."""
    msg = FlushSegment(segments=["첫 문장.", "두 번째 문장!"])
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "flush"
    assert len(data["segments"]) == 2


def test_error_message() -> None:
    """ErrorMessage detail 필드가 올바르다."""
    msg = ErrorMessage(detail="추론 오류 발생")
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "error"
    assert data["detail"] == "추론 오류 발생"


def test_session_ack_started() -> None:
    """SessionAck started 동작이 올바르다."""
    msg = SessionAck(session_id="session-uuid", action="started")
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "session_ack"
    assert data["action"] == "started"


def test_session_ack_stopped() -> None:
    """SessionAck stopped 동작이 올바르다."""
    msg = SessionAck(session_id="session-uuid", action="stopped")
    data = json.loads(msg.model_dump_json())
    assert data["action"] == "stopped"


def test_final_transcript_missing_required_field() -> None:
    """필수 필드 누락 시 ValidationError가 발생한다."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FinalTranscript(text="텍스트")  # turn_id, duration_sec, latency_ms 누락

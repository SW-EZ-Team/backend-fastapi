"""고정 튜터 음성 프로필 및 라우터 연결 테스트."""
from __future__ import annotations

import base64
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from app.modules.TTS_V2.app.main import app
from app.modules.TTS_V2.pipeline.nodes.plan_reading_node import plan_reading_node
from app.modules.TTS_V2.pipeline.nodes.postfx_node import postfx_node
from app.modules.TTS_V2.pipeline.nodes.qc_node import qc_node
from app.modules.TTS_V2.schemas.state import AudiobookState, ChunkRecord
from app.modules.TTS_V2.voice_profiles import resolve_voice_profile


class _FakeGraph:
    """라우터가 만든 초기 상태를 보존하는 테스트용 그래프."""

    def __init__(self) -> None:
        self.seen_state: AudiobookState | None = None

    def _make_result(self, state: AudiobookState) -> AudiobookState:
        """실제 모델 호출 없이 응답 변환에 필요한 필드만 채워 반환한다."""
        self.seen_state = state
        return {
            **state,
            "merged_audio_bytes": b"fake-wav",
            "total_duration_sec": 1.25,
            "chunks": [
                {
                    "chunk_id": "ch_001",
                    "chapter_idx": 0,
                    "section_title": "",
                    "original_text": state["raw_text"] or "",
                    "normalized_text": state["raw_text"] or "",
                    "planned_text": state["raw_text"] or "",
                    "audio_np": None,
                    "sample_rate": 24000,
                    "duration_sec": 1.25,
                    "cer": 0.0,
                    "wer": 0.0,
                    "qc_passed": True,
                    "retry_count": 0,
                    "qc_reason": "ok",
                }
            ],
            "pipeline_status": "done",
            "timings": {"merge": 1.0},
        }

    def invoke(self, state: AudiobookState) -> AudiobookState:
        """동기 invoke — 기존 호환성 유지용."""
        return self._make_result(state)

    async def ainvoke(self, state: AudiobookState, *args: object, **kwargs: object) -> AudiobookState:
        """비동기 ainvoke — Sprint 2에서 라우터가 await graph.ainvoke() 로 전환됨."""
        return self._make_result(state)


def test_resolve_tutor_voice_profiles_read_files() -> None:
    """tutor_1/tutor_2 프로필이 실제 참조 오디오와 대본을 읽어야 한다."""
    for profile_id in ("tutor_1", "tutor_2"):
        profile = resolve_voice_profile(profile_id)
        audio_bytes, ref_text = profile.read_ref()
        assert profile.ref_audio_path.suffix == ".wav"
        assert profile.sample_rate == 24000
        assert len(audio_bytes) > 100_000
        assert len(ref_text) > 20


def test_text_endpoint_uses_requested_voice_profile_and_options() -> None:
    """JSON 엔드포인트가 voice_profile_id 와 요청별 옵션을 파이프라인에 전달해야 한다."""
    graph = _FakeGraph()
    with TestClient(app) as client, patch(
        "app.modules.TTS_V2.app.routers.tts_v2.get_compiled_graph",
        return_value=graph,
    ):
        response = client.post(
            "/api/tts-v2",
            json={
                "text": "테스트 문장입니다.",
                "voice_profile_id": "tutor_2",
                "skip_planner": True,
                "skip_postfx": True,
                "qc_engine": "both",
            },
        )

    assert response.status_code == 200
    assert response.json()["qc_engine_used"] == "both"
    assert graph.seen_state is not None
    assert graph.seen_state["voice_profile_id"] == "tutor_2"
    assert graph.seen_state["skip_planner"] is True
    assert graph.seen_state["skip_postfx"] is True
    assert graph.seen_state["qc_engine"] == "both"
    assert "낯선 사람" in graph.seen_state["ref_text"]
    assert response.json()["qc_reason_counts"] == {"ok": 1}
    assert response.json()["chunk_qc_reasons"] == [
        {"chunk_id": "ch_001", "qc_reason": "ok"}
    ]


def test_text_endpoint_accepts_complete_custom_reference() -> None:
    """직접 레퍼런스는 오디오와 대본이 모두 있을 때만 custom 으로 전달된다."""
    graph = _FakeGraph()
    audio_b64 = base64.b64encode(b"fake-audio").decode("ascii")
    with TestClient(app) as client, patch(
        "app.modules.TTS_V2.app.routers.tts_v2.get_compiled_graph",
        return_value=graph,
    ):
        response = client.post(
            "/api/tts-v2",
            json={
                "text": "테스트 문장입니다.",
                "ref_audio_base64": audio_b64,
                "ref_text": "직접 올린 음성 대본입니다.",
            },
        )

    assert response.status_code == 200
    assert graph.seen_state is not None
    assert graph.seen_state["voice_profile_id"] == "custom"
    assert graph.seen_state["ref_audio_bytes"] == b"fake-audio"
    assert graph.seen_state["ref_text"] == "직접 올린 음성 대본입니다."


def test_text_endpoint_rejects_partial_custom_reference() -> None:
    """직접 레퍼런스 오디오와 대본 중 하나만 오면 품질 위험이라 400 으로 막는다."""
    audio_b64 = base64.b64encode(b"fake-audio").decode("ascii")
    with TestClient(app) as client:
        no_text = client.post(
            "/api/tts-v2",
            json={"text": "테스트 문장입니다.", "ref_audio_base64": audio_b64},
        )
        no_audio = client.post(
            "/api/tts-v2",
            json={"text": "테스트 문장입니다.", "ref_text": "대본만 있음"},
        )
        empty_audio = client.post(
            "/api/tts-v2",
            json={"text": "테스트 문장입니다.", "ref_audio_base64": "", "ref_text": "대본"},
        )
    assert no_text.status_code == 400
    assert no_audio.status_code == 400
    assert empty_audio.status_code == 400


def test_file_endpoint_rejects_custom_audio_without_ref_text() -> None:
    """파일 모드에서도 직접 레퍼런스 음성만 올리는 경로를 막아야 한다."""
    with TestClient(app) as client:
        response = client.post(
            "/api/tts-v2/file",
            files={
                "text_file": ("lesson.txt", b"hello", "text/plain"),
                "ref_audio": ("ref.wav", b"fake-audio", "audio/wav"),
            },
        )
    assert response.status_code == 400
    assert "ref_text" in response.json()["detail"]


def test_file_endpoint_rejects_empty_custom_audio() -> None:
    """빈 직접 레퍼런스 음성은 모델 호출 전에 400 으로 거부한다."""
    with TestClient(app) as client:
        response = client.post(
            "/api/tts-v2/file",
            files={
                "text_file": ("lesson.txt", b"hello", "text/plain"),
                "ref_audio": ("empty.wav", b"", "audio/wav"),
            },
            data={"ref_text": "대본입니다."},
        )
    assert response.status_code == 400
    assert "빈" in response.json()["detail"]


def test_unknown_voice_profile_returns_400() -> None:
    """없는 voice_profile_id 는 서버 설정 오류가 아니라 클라이언트 400 이다."""
    with TestClient(app) as client:
        response = client.post(
            "/api/tts-v2",
            json={"text": "테스트 문장입니다.", "voice_profile_id": "missing"},
        )
    assert response.status_code == 400
    assert "missing" in response.json()["detail"]


def test_voice_list_endpoint_contains_fixed_tutors() -> None:
    """프론트가 고정 튜터 1,2 목록을 조회할 수 있어야 한다."""
    with TestClient(app) as client:
        response = client.get("/api/tts-v2/voices")
    assert response.status_code == 200
    ids = {item["profile_id"] for item in response.json()["profiles"]}
    assert {"tutor_1", "tutor_2"} <= ids


def test_skip_planner_copies_normalized_text() -> None:
    """skip_planner=True 이면 LLM 플래너 없이 planned_text 를 채운다."""
    chunk = _chunk("정규화된 문장입니다.")
    state = _state([chunk], skip_planner=True)
    result = plan_reading_node(state)
    assert result["chunks"][0]["planned_text"] == "정규화된 문장입니다."


def test_skip_postfx_preserves_chunks() -> None:
    """skip_postfx=True 이면 후처리 노드가 청크를 그대로 반환한다."""
    chunks = [_chunk("후처리 건너뛰기")]
    state = _state(chunks, skip_postfx=True)
    result = postfx_node(state)
    assert result["chunks"] == chunks


def test_qc_node_uses_request_engine(monkeypatch) -> None:
    """qc_engine 은 전역 config 가 아니라 요청 상태값을 우선해야 한다."""
    called: dict[str, bool] = {"v1": False}

    def fake_apply_v1(chunk: ChunkRecord, *args: object) -> ChunkRecord:
        called["v1"] = True
        return {**chunk, "qc_passed": True, "qc_reason": "ok"}

    monkeypatch.setattr(
        "app.modules.TTS_V2.pipeline.nodes.qc_node._apply_v1asr",
        fake_apply_v1,
    )
    chunk = _chunk("검증 문장")
    chunk["audio_np"] = np.zeros(1600, dtype=np.float32)
    state = _state([chunk], qc_engine="v1_asr")
    qc_node(state)
    assert called["v1"] is True


def _chunk(text: str) -> ChunkRecord:
    """테스트용 최소 청크를 생성한다."""
    return {
        "chunk_id": "ch_001",
        "chapter_idx": 0,
        "section_title": "",
        "original_text": text,
        "normalized_text": text,
        "planned_text": "",
        "audio_np": None,
        "sample_rate": 24000,
        "duration_sec": 0.0,
        "cer": None,
        "wer": None,
        "qc_passed": False,
        "retry_count": 0,
        "qc_reason": "",
    }


def _state(
    chunks: list[ChunkRecord],
    skip_planner: bool = False,
    skip_postfx: bool = False,
    qc_engine: str = "whisperx",
) -> AudiobookState:
    """노드 단위 테스트용 상태를 생성한다."""
    return {
        "input_type": "text",
        "raw_text": "테스트",
        "file_content": None,
        "ref_audio_bytes": b"ref",
        "ref_text": "레퍼런스",
        "ref_sample_rate": 24000,
        "language": "ko",
        "sections": [],
        "chunks": chunks,
        "current_phase": "init",
        "max_retries": 1,
        "failed_chunks": [],
        "merged_audio_bytes": None,
        "total_duration_sec": 0.0,
        "pipeline_status": "loading",
        "error_message": None,
        "timings": {},
        "skip_planner": skip_planner,
        "skip_postfx": skip_postfx,
        "qc_engine": qc_engine,
        "voice_profile_id": "tutor_1",
    }

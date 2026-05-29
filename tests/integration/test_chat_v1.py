"""Chat_V1 통합 테스트 — 스프링이 보내는 실제 JSON 페이로드로 검증한다.

mock, MagicMock, @patch, monkeypatch 절대 금지.
POST /api/chat/v1/ask   — 텍스트 채팅 (Claude Sonnet)
POST /api/chat/v1/voice — 음성 채팅 (Gemini Flash Live)
POST /api/chat/v1/health
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ─── 헬스체크 ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_chat_v1_health(client: AsyncClient) -> None:
    """Chat_V1 헬스체크 엔드포인트가 200을 반환한다."""
    response = await client.post("/api/chat/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "chat-v1"


# ─── 정상 요청: 학생 질문 답변 ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_ask_with_full_context(client: AsyncClient) -> None:
    """스프링이 완전한 강의 컨텍스트와 함께 학생 질문을 전달할 때 스키마를 통과한다."""
    payload: dict = {
        "session_id": "spring-session-student-42-lesson-7",
        "user_message": "역전파 알고리즘에서 연쇄법칙이 어떻게 적용되는지 다시 설명해 주실 수 있나요?",
        "lecture_context": {
            "chapter_title": "역전파: 신경망이 학습하는 방법",
            "slides": [
                {
                    "slide_idx": 0,
                    "title": "신경망과 경사하강법",
                    "content": "신경망의 가중치를 업데이트하려면 손실 함수의 기울기가 필요합니다.",
                },
                {
                    "slide_idx": 1,
                    "title": "연쇄법칙이란",
                    "content": "복합 함수의 미분에서 연쇄법칙을 사용합니다. f(g(x))의 도함수는 f'(g(x)) × g'(x)입니다.",
                },
                {
                    "slide_idx": 2,
                    "title": "역전파 수식 전개",
                    "content": "출력층에서 입력층 방향으로 편미분을 계산합니다.",
                },
            ],
            "voice_scripts": [
                "신경망 학습의 핵심은 손실을 줄이는 방향으로 가중치를 업데이트하는 것입니다.",
                "연쇄법칙 덕분에 복잡한 합성함수도 단계별로 미분할 수 있습니다.",
                "역전파는 출력에서 입력 방향으로 그래디언트를 전파하는 효율적인 알고리즘입니다.",
            ],
            "quiz_items": [
                "연쇄법칙을 사용하여 f(x) = sin(x²)의 도함수를 구하세요.",
            ],
        },
    }

    response = await client.post("/api/chat/v1/ask", json=payload)
    # 실제 Claude API 없이는 500이 발생할 수 있으나 스키마는 통과해야 한다
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
async def test_ask_with_minimal_context(client: AsyncClient) -> None:
    """voice_scripts·quiz_items 없이 슬라이드만으로 요청이 스키마를 통과한다."""
    payload: dict = {
        "session_id": "session-minimal-0001",
        "user_message": "재귀 함수가 무한 루프에 빠지지 않으려면 어떻게 해야 하나요?",
        "lecture_context": {
            "chapter_title": "재귀 함수와 기저 조건",
            "slides": [
                {
                    "slide_idx": 0,
                    "title": "재귀 함수 개요",
                    "content": "재귀 함수는 자기 자신을 호출하는 함수입니다. 반드시 기저 조건이 필요합니다.",
                },
            ],
            # voice_scripts, quiz_items 생략 (선택 필드)
        },
    }

    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
async def test_ask_multiple_slides(client: AsyncClient) -> None:
    """여러 슬라이드가 있는 완전한 강의 컨텍스트 요청이 스키마를 통과한다."""
    payload: dict = {
        "session_id": "session-algo-ds-001",
        "user_message": "정렬 알고리즘 중 어떤 것이 가장 효율적인가요?",
        "lecture_context": {
            "chapter_title": "정렬 알고리즘 비교",
            "slides": [
                {
                    "slide_idx": i,
                    "title": f"정렬 알고리즘 {i + 1}번",
                    "content": f"슬라이드 {i + 1}의 핵심 내용 — 정렬 알고리즘의 특징과 시간 복잡도",
                }
                for i in range(5)
            ],
        },
    }

    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code in {200, 500}
    assert response.status_code != 422


# ─── 유효성 검사 오류 ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_missing_session_id_returns_422(client: AsyncClient) -> None:
    """session_id 누락 시 422를 반환한다."""
    payload: dict = {
        "user_message": "질문입니다",
        "lecture_context": {
            "chapter_title": "테스트 챕터",
            "slides": [
                {"slide_idx": 0, "title": "슬라이드 1", "content": "내용"},
            ],
        },
    }
    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_empty_slides_list_returns_422(client: AsyncClient) -> None:
    """slides 가 빈 리스트이면 422를 반환한다 (min_length=1 위반)."""
    payload: dict = {
        "session_id": "session-test-001",
        "user_message": "질문입니다",
        "lecture_context": {
            "chapter_title": "테스트 챕터",
            "slides": [],  # min_length=1 위반
        },
    }
    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_missing_lecture_context_returns_422(client: AsyncClient) -> None:
    """lecture_context 누락 시 422를 반환한다."""
    payload: dict = {
        "session_id": "session-no-context-001",
        "user_message": "강의 컨텍스트 없이 질문합니다",
    }
    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_empty_user_message_returns_422(client: AsyncClient) -> None:
    """빈 user_message는 422를 반환한다."""
    payload: dict = {
        "session_id": "session-empty-msg-001",
        "user_message": "",  # min_length=1 위반
        "lecture_context": {
            "chapter_title": "테스트",
            "slides": [{"slide_idx": 0, "title": "제목", "content": "내용"}],
        },
    }
    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_slide_missing_content_returns_422(client: AsyncClient) -> None:
    """슬라이드에 content 필드가 없으면 422를 반환한다."""
    payload: dict = {
        "session_id": "session-incomplete-slide-001",
        "user_message": "질문입니다",
        "lecture_context": {
            "chapter_title": "테스트 챕터",
            "slides": [
                {"slide_idx": 0, "title": "슬라이드 제목"},  # content 누락
            ],
        },
    }
    response = await client.post("/api/chat/v1/ask", json=payload)
    assert response.status_code == 422


# ─── 음성 채팅 (Gemini Flash Live) ──────────────────────────────────────────

# 최소 유효 WAV 파일 (무음 0.1초) 의 base64 표현 — 실제 Gemini 호출 없이 스키마만 검증
_MINIMAL_WAV_B64 = (
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAAAAAZGF0YQAAAAA="
)


@pytest.mark.anyio
async def test_voice_chat_schema_validation(client: AsyncClient) -> None:
    """음성 채팅 엔드포인트가 올바른 페이로드에서 422를 반환하지 않는다."""
    payload: dict = {
        "session_id": "voice-session-test-001",
        "audio_data": _MINIMAL_WAV_B64,
        "audio_format": "wav",
        "sample_rate": 16000,
        "lecture_context": {
            "chapter_title": "역전파: 신경망이 학습하는 방법",
            "slides": [
                {
                    "slide_idx": 0,
                    "title": "연쇄법칙이란",
                    "content": "복합 함수의 미분에서 연쇄법칙을 사용합니다.",
                },
            ],
        },
    }
    response = await client.post("/api/chat/v1/voice", json=payload)
    # 실제 Gemini API 없이는 500이 발생할 수 있으나 스키마는 통과해야 한다
    assert response.status_code in {200, 500}
    assert response.status_code != 422


@pytest.mark.anyio
async def test_voice_chat_missing_audio_returns_422(client: AsyncClient) -> None:
    """audio_data 누락 시 422를 반환한다."""
    payload: dict = {
        "session_id": "voice-session-no-audio-001",
        # audio_data 누락
        "lecture_context": {
            "chapter_title": "테스트 챕터",
            "slides": [{"slide_idx": 0, "title": "제목", "content": "내용"}],
        },
    }
    response = await client.post("/api/chat/v1/voice", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_voice_chat_empty_audio_returns_422(client: AsyncClient) -> None:
    """audio_data 가 빈 문자열이면 422를 반환한다 (min_length=1 위반)."""
    payload: dict = {
        "session_id": "voice-session-empty-audio-001",
        "audio_data": "",  # min_length=1 위반
        "lecture_context": {
            "chapter_title": "테스트 챕터",
            "slides": [{"slide_idx": 0, "title": "제목", "content": "내용"}],
        },
    }
    response = await client.post("/api/chat/v1/voice", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_voice_chat_missing_session_id_returns_422(client: AsyncClient) -> None:
    """session_id 누락 시 422를 반환한다."""
    payload: dict = {
        "audio_data": _MINIMAL_WAV_B64,
        "lecture_context": {
            "chapter_title": "테스트 챕터",
            "slides": [{"slide_idx": 0, "title": "제목", "content": "내용"}],
        },
    }
    response = await client.post("/api/chat/v1/voice", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_voice_chat_with_full_context(client: AsyncClient) -> None:
    """완전한 강의 컨텍스트(slides + voice_scripts + quiz_items)로 음성 채팅 스키마를 통과한다."""
    payload: dict = {
        "session_id": "voice-session-full-context-001",
        "audio_data": _MINIMAL_WAV_B64,
        "audio_format": "webm",
        "sample_rate": 48000,
        "lecture_context": {
            "chapter_title": "정렬 알고리즘 비교",
            "slides": [
                {
                    "slide_idx": i,
                    "title": f"정렬 알고리즘 {i + 1}",
                    "content": f"슬라이드 {i + 1}: 정렬 알고리즘의 특징",
                }
                for i in range(3)
            ],
            "voice_scripts": ["이번 시간에는 정렬 알고리즘을 비교합니다."],
            "quiz_items": ["버블 정렬의 시간복잡도는?"],
        },
    }
    response = await client.post("/api/chat/v1/voice", json=payload)
    assert response.status_code in {200, 500}
    assert response.status_code != 422

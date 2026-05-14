from __future__ import annotations

from fastapi.testclient import TestClient

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse
from app.modules.ChapterStudio_V1.app.main import app
from app.modules.ChapterStudio_V1.app.slide_chat_context import build_demo_chat_context
from app.modules.ChapterStudio_V1.app.slide_chat_responder import classify_question, stream_chat_response
from app.modules.ChapterStudio_V1.app.slide_chat_types import SlideChatRequest


def test_chat_context_uses_current_slide_and_voice_script() -> None:
    req = _request("현재 그래프 색이 무슨 뜻이야?", slide_idx=1)
    ctx = build_demo_chat_context(req)

    assert ctx.slide_idx == 1
    assert "p-value" in ctx.slide_title
    assert ctx.voice_script
    assert ctx.next_role != ""


def test_chat_classifier_distinguishes_quiz_and_code() -> None:
    assert classify_question("이 퀴즈 정답은 왜 1번이야?") == "quiz"
    assert classify_question("class 변수명은 왜 이렇게 썼어?") == "code"


async def test_chat_stream_mentions_slide_context() -> None:
    req = _request("왜 헷갈리지?")
    ctx = build_demo_chat_context(req)
    text = "".join([chunk async for chunk in stream_chat_response(req, ctx)])

    assert "현재 슬라이드" in text
    assert "방금 음성대본" in text
    assert "바로 점검" in text


def test_chat_context_endpoint_returns_compressed_context() -> None:
    with TestClient(app) as client:
        response = client.post("/demo/chapter-studio/chat/context", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["slide_idx"] == 0
    assert "voice_script" in data


def test_chat_stream_endpoint_returns_text_stream() -> None:
    with TestClient(app) as client:
        response = client.post("/demo/chapter-studio/chat/stream", json=_payload())

    assert response.status_code == 200
    assert "질문 의도" in response.text
    assert "현재 슬라이드" in response.text


async def test_chat_stream_can_use_codex_oauth_engine(monkeypatch) -> None:
    class FakeCodex:
        async def generate(self, req):
            return ChapterAIResponse(
                text=f"Codex 답변: {req.user[:10]}",
                model="codex-test",
                input_tokens=1,
                output_tokens=1,
                finish_reason="stop",
            )

    monkeypatch.setattr("app.modules.ChapterStudio_V1.app.codex_chat_pipeline.CodexCLIConnector", FakeCodex)
    req = SlideChatRequest(**_payload(engine="codex_cli"))
    ctx = build_demo_chat_context(req)
    text = "".join([chunk async for chunk in stream_chat_response(req, ctx)])

    assert text.startswith("Codex 답변")


def _request(message: str, slide_idx: int = 0) -> SlideChatRequest:
    return SlideChatRequest(**_payload(message=message, slide_idx=slide_idx))


def _payload(
    message: str = "p-value가 왜 작은데 기각해?", slide_idx: int = 0, engine: str = "mock"
) -> dict[str, object]:
    return {
        "topic": "p-value와 신뢰구간",
        "message": message,
        "engine": engine,
        "slide_idx": slide_idx,
        "template": "statistics_inference",
        "teacher": "fox",
        "weak_points": "표본분포와 검정 해석",
        "selected_text": "p-value가 작다",
        "tone": 55,
        "pace": 45,
        "tutor_depth": 75,
        "socratic": 80,
    }

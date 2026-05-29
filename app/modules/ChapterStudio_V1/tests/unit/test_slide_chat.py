from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse
from app.modules.ChapterStudio_V1.app.slide_chat_responder import classify_question, stream_chat_response
from app.modules.ChapterStudio_V1.app.slide_chat_types import SlideChatContext, SlideChatRequest


def test_chat_classifier_distinguishes_quiz_and_code() -> None:
    assert classify_question("이 퀴즈 정답은 왜 1번이야?") == "quiz"
    assert classify_question("class 변수명은 왜 이렇게 썼어?") == "code"


async def test_chat_stream_mentions_slide_context() -> None:
    req = _request("왜 헷갈리지?")
    ctx = _context()
    text = "".join([chunk async for chunk in stream_chat_response(req, ctx)])

    assert "현재 슬라이드" in text
    assert "방금 음성대본" in text
    assert "바로 점검" in text


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
    req = _request("Codex로 답해줘", engine="codex_cli")
    text = "".join([chunk async for chunk in stream_chat_response(req, _context())])

    assert text.startswith("Codex 답변")


def _request(message: str, engine: str = "mock") -> SlideChatRequest:
    return SlideChatRequest(
        topic="p-value와 신뢰구간",
        message=message,
        engine=engine,
        slide_idx=0,
        template="statistics_inference",
        teacher="fox",
        weak_points="표본분포와 검정 해석",
        selected_text="p-value가 작다",
    )


def _context() -> SlideChatContext:
    return SlideChatContext(
        lesson_id="lesson-1",
        slide_id="slide-1",
        slide_idx=0,
        slide_title="p-value의 의미",
        slide_role="개념 정리",
        category="text",
        focus="검정 해석",
        checkpoint="p-value가 작은 상황을 설명할 수 있다.",
        voice_script="p-value가 작다는 말은 관측 결과가 귀무가설 아래에서 보기 드물다는 뜻입니다.",
        note_bullets=["p-value는 효과 크기가 아니라 귀무가설 아래의 드문 정도를 나타냅니다."],
        weak_points="표본분포와 검정 해석",
        tutor_style="차분하게 되묻기",
        previous_role="표본분포",
        next_role="신뢰구간",
    )

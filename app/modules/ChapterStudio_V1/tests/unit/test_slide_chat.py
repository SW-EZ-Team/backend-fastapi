from __future__ import annotations

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse
from app.modules.ChapterStudio_V1.app.gemini_chat_pipeline import SCOPE_NOTICE
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


# (삭제됨) test_chat_stream_can_use_codex_oauth_engine — codex_chat_pipeline.py가
# 커밋 7abc300(codex CLI 커넥터 제거)에서 삭제됨(gemini_chat_pipeline으로 대체).
# 채팅 엔진 경로는 아래 gemini 계열 테스트들이 계속 가드한다.


async def test_gemini_chat_answers_out_of_scope_without_refusal(monkeypatch) -> None:
    # 자료 밖 질문이라도 모델 답변을 거절문으로 교체하지 않고 그대로 흘려보내는지 검증한다.
    out_of_scope_answer = (
        "환율이 오르면 같은 외화를 사는 데 더 많은 원화가 필요해서 수입 물가가 올라요. "
        f"{SCOPE_NOTICE}"
    )

    class FakeGemini:
        async def generate(self, req):
            return ChapterAIResponse(
                text=out_of_scope_answer,
                model="gemini-test",
                input_tokens=1,
                output_tokens=1,
                finish_reason="stop",
            )

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.gemini_chat_pipeline.get_text_connector",
        lambda: FakeGemini(),
    )
    req = _request("환율이 오르면 수입 물가는 왜 올라요?", engine="gemini")
    text = "".join([chunk async for chunk in stream_chat_response(req, _context())])

    # 답변 본문 + 범위 밖 안내문이 살아 있어야 하고, 거절문이 끼어들면 안 된다.
    assert "수입 물가" in text
    assert SCOPE_NOTICE in text
    assert "답변할 수 없" not in text
    assert "다루지 않" not in text


async def test_gemini_chat_prompt_forbids_refusal(monkeypatch) -> None:
    # 시스템/유저 프롬프트가 거절 금지 + 범위 밖 안내문 정책을 담고 있는지 검증한다.
    captured: dict[str, str] = {}

    class FakeGemini:
        async def generate(self, req):
            captured["system"] = req.system
            captured["user"] = req.user
            return ChapterAIResponse(
                text="답변", model="gemini-test", input_tokens=1, output_tokens=1, finish_reason="stop"
            )

    monkeypatch.setattr(
        "app.modules.ChapterStudio_V1.app.gemini_chat_pipeline.get_text_connector",
        lambda: FakeGemini(),
    )
    req = _request("강의 밖 질문이에요", engine="gemini")
    "".join([chunk async for chunk in stream_chat_response(req, _context())])

    assert "거절" in captured["system"]
    assert SCOPE_NOTICE in captured["system"]
    assert SCOPE_NOTICE in captured["user"]


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

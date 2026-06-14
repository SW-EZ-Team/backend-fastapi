"""AI 총평 출력 정제 회귀 테스트 (2026-06-13 스크래치패드 누출 장애).

검증 범위:
1. sanitize_analysis — 사고/글자수계산/초안 라벨/작성단계 헤더 제거, 한국어 본문 보존
2. generate_analysis — 누출 입력(mock)→정제된 한국어 총평만, 약점주제 파싱, 빈본문 폴백
3. 프롬프트 — 메타 금지 + 약점주제 필수 문구 포함

라이브 AI 호출 없이 가짜 커넥터(fixture)로만 검증한다.
"""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.app._analysis_prompt import (
    split_weak_topics,
    system_prompt,
    _INSTRUCTION_PERFECT,
    _INSTRUCTION_WITH_WEAKNESS,
)
from app.modules.ExamForge_V1.app._analysis_sanitize import sanitize_analysis
from app.modules.ExamForge_V1.app.exam_analysis import (
    AnalysisGenerationError,
    MockExamAnalyzeRequest,
    MockExamResultItem,
    _EMPTY_BODY_FALLBACK,
    generate_analysis,
)


# ── 실측 장애 입력 픽스처 ─────────────────────────────────────────────

# DB에 실제로 저장됐던 오염 응답 형태(앞쪽 글자수계산 + 작성단계 라벨 + 한국어 본문).
_LEAKED_RAW = (
    "Total is around 750 characters. Need to trim it slightly to fit the "
    "350-700 range precisely.\n"
    "\n"
    "5.  **Trimming the Draft:**\n"
    "    이번 모의고사에서 6점을 받아 F등급을 기록했어요. 비록 아쉬운 점수이지만, "
    "이진 탐색 트리의 기본 정의와 편향 트리의 시간 복잡도를 다시 정리하면 충분히 끌어올릴 수 있어요. "
    "3번에서 '큐'를 골랐는데, 이는 스택과 큐를 뒤바꾼 경우예요(FIFO/LIFO 혼동).\n"
    "약점주제: 이진 탐색 트리 | FIFO/LIFO 혼동 | 시간 복잡도"
)


# ── 1. sanitize_analysis 단위 테스트 ─────────────────────────────────


class TestSanitizeAnalysis:
    def test_strips_leaked_scratchpad_keeps_korean(self) -> None:
        """실측 누출 입력에서 영문 메타를 제거하고 한국어 본문 + 약점주제만 남긴다."""
        out = sanitize_analysis(_LEAKED_RAW)
        # 영문 메타가 모두 제거된다
        assert "Total is around" not in out
        assert "Trimming the Draft" not in out
        assert "350-700" not in out
        assert "**" not in out
        # 한국어 본문은 보존된다
        assert "이번 모의고사에서 6점을 받아 F등급" in out
        assert "FIFO/LIFO 혼동" in out
        # 파싱 계약 줄(약점주제)은 보존된다
        assert "약점주제: 이진 탐색 트리 | FIFO/LIFO 혼동 | 시간 복잡도" in out

    def test_removes_think_block(self) -> None:
        """<think>...</think> reasoning 블록은 제거된다(strip_thinking 재사용)."""
        text = "<think>내부 사고 750자 계산</think>총평 본문이에요."
        assert sanitize_analysis(text) == "총평 본문이에요."

    def test_removes_truncated_think(self) -> None:
        """닫히지 않은 <think> 이후는 모두 절단된다."""
        text = "총평 본문이에요.\n<think>여기부터 사고가 잘려서"
        assert sanitize_analysis(text) == "총평 본문이에요."

    def test_removes_char_count_meta_variants(self) -> None:
        """다양한 글자수 계산 메타 변형을 제거한다."""
        text = (
            "This is about 600 characters.\n"
            "Word count: 540\n"
            "총평 본문만 남아야 해요.\n"
            "Need to trim it slightly."
        )
        out = sanitize_analysis(text)
        assert out == "총평 본문만 남아야 해요."

    def test_removes_english_step_headers(self) -> None:
        """'**Step 1: Overall Assessment**' 같은 영문 작성단계 헤더를 제거한다."""
        text = (
            "**Step 1: Overall Assessment**\n"
            "전반적으로 잘했어요.\n"
            "2. **Weakness Analysis:**\n"
            "3번이 약점이에요."
        )
        out = sanitize_analysis(text)
        assert "Step 1" not in out and "Weakness Analysis" not in out
        assert "전반적으로 잘했어요." in out
        assert "3번이 약점이에요." in out

    def test_preserves_korean_line_with_english_terms(self) -> None:
        """한국어 줄에 영어 약어(BST, FIFO)가 섞여 있어도 절대 지우지 않는다."""
        text = "BST의 시간 복잡도는 O(N)까지 나빠질 수 있어요(편향 트리)."
        assert sanitize_analysis(text) == text

    def test_empty_input_returns_empty(self) -> None:
        """빈/공백 입력은 빈 문자열을 반환한다(크래시 금지)."""
        assert sanitize_analysis("") == ""
        assert sanitize_analysis("   \n  ") == ""

    def test_meta_only_input_returns_empty(self) -> None:
        """메타만 있는(한국어 0) 입력은 전부 제거돼 빈 문자열이 된다."""
        text = "Total is around 750 characters.\n**Trimming the Draft:**\nFinal version."
        assert sanitize_analysis(text) == ""

    def test_collapses_blank_lines(self) -> None:
        """메타 제거 후 생긴 연속 빈 줄을 하나로 압축한다."""
        text = "Total is around 700 chars.\n\n\n첫 단락이에요.\n\n\n둘째 단락이에요."
        out = sanitize_analysis(text)
        assert "\n\n\n" not in out
        assert "첫 단락이에요." in out and "둘째 단락이에요." in out

    def test_sanitize_then_split_round_trip(self) -> None:
        """정제 → split_weak_topics 파이프라인이 본문/약점주제를 정확히 분리한다."""
        body, topics = split_weak_topics(sanitize_analysis(_LEAKED_RAW))
        assert "약점주제" not in body
        assert "Total is around" not in body
        assert "이번 모의고사에서 6점을 받아 F등급" in body
        assert topics == ["이진 탐색 트리", "FIFO/LIFO 혼동", "시간 복잡도"]


# ── 2. generate_analysis 통합(가짜 커넥터) 테스트 ─────────────────────


class _StubResponse:
    """커넥터 응답 더블 — text 속성만 노출한다."""

    def __init__(self, text: str) -> None:
        self.text = text


class _StubConnector:
    """generate(req)에서 고정 텍스트를 돌려주는 가짜 텍스트 커넥터."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def generate(self, req: object) -> _StubResponse:  # noqa: ANN401
        return _StubResponse(self._text)


def _make_request(score: int = 6, total: int = 22) -> MockExamAnalyzeRequest:
    """오답 1개를 포함한 분석 요청 픽스처."""
    return MockExamAnalyzeRequest(
        examId="exam_test",
        subject="자료구조",
        score=score,
        totalPoints=total,
        grade="F",
        results=[
            MockExamResultItem(
                questionIdx=3,
                questionText="스택과 큐의 차이로 옳은 것은?",
                correct=False,
                selectedText="큐",
                correctText="스택",
                explanation="스택은 LIFO 구조이다.",
            )
        ],
    )


@pytest.mark.asyncio
async def test_generate_analysis_sanitizes_leaked_output(monkeypatch) -> None:
    """누출된 모델 응답(mock)→정제된 한국어 총평만 반환하고 약점주제를 파싱한다."""
    monkeypatch.setattr(
        "app.modules.ExamForge_V1.app.exam_analysis.get_grading_connector",
        lambda: _StubConnector(_LEAKED_RAW),
    )
    body, weak_topics = await generate_analysis(_make_request())

    # 영문 메타/스크래치패드가 본문에 없어야 한다(실측 장애의 핵심)
    assert "Total is around" not in body
    assert "Trimming the Draft" not in body
    assert "**" not in body
    assert "약점주제" not in body
    # 한국어 본문은 보존
    assert "이번 모의고사에서 6점을 받아 F등급" in body
    # 약점주제 파싱 성공 — 빈 목록이 아니어야 한다(실측 버그: weakTopics 빈 목록)
    assert weak_topics == ["이진 탐색 트리", "FIFO/LIFO 혼동", "시간 복잡도"]


@pytest.mark.asyncio
async def test_generate_analysis_clean_output_unchanged(monkeypatch) -> None:
    """정상(메타 없는) 응답은 정제로 인한 손실 없이 그대로 통과한다(회귀 방지)."""
    clean = (
        "이번 모의고사에서 6점을 받았어요. 이진 탐색 트리 개념을 다시 정리하면 좋아요.\n"
        "약점주제: 이진 탐색 트리 | 시간 복잡도"
    )
    monkeypatch.setattr(
        "app.modules.ExamForge_V1.app.exam_analysis.get_grading_connector",
        lambda: _StubConnector(clean),
    )
    body, weak_topics = await generate_analysis(_make_request())
    assert body == "이번 모의고사에서 6점을 받았어요. 이진 탐색 트리 개념을 다시 정리하면 좋아요."
    assert weak_topics == ["이진 탐색 트리", "시간 복잡도"]


@pytest.mark.asyncio
async def test_generate_analysis_meta_only_falls_back(monkeypatch) -> None:
    """메타만 누출돼 정제 후 본문이 비면 안전 폴백 문구로 대체한다."""
    meta_only = "Total is around 750 characters.\n**Trimming the Draft:**"
    monkeypatch.setattr(
        "app.modules.ExamForge_V1.app.exam_analysis.get_grading_connector",
        lambda: _StubConnector(meta_only),
    )
    body, weak_topics = await generate_analysis(_make_request())
    assert body == _EMPTY_BODY_FALLBACK
    assert weak_topics == []


@pytest.mark.asyncio
async def test_generate_analysis_empty_response_raises(monkeypatch) -> None:
    """모델이 완전 빈 응답이면 AnalysisGenerationError로 올린다(기존 동작 보존)."""
    monkeypatch.setattr(
        "app.modules.ExamForge_V1.app.exam_analysis.get_grading_connector",
        lambda: _StubConnector("   "),
    )
    with pytest.raises(AnalysisGenerationError):
        await generate_analysis(_make_request())


# ── 3. 프롬프트 메타 금지 + 약점주제 필수 문구 검증 ──────────────────


class TestPromptMetaGuards:
    def test_system_prompt_forbids_meta(self) -> None:
        """시스템 프롬프트가 사고/글자수/초안 메타·영어 메타 발화를 금지한다."""
        sp = system_prompt()
        assert "사고 과정" in sp
        assert "글자수 계산" in sp
        assert "Trimming the Draft" in sp
        assert "영어" in sp

    def test_weakness_instruction_forbids_meta_and_requires_topic_line(self) -> None:
        """약점 지침이 메타를 금지하고 약점주제 줄을 필수로 못 박는다."""
        assert "사고 과정" in _INSTRUCTION_WITH_WEAKNESS
        assert "Trimming the Draft" in _INSTRUCTION_WITH_WEAKNESS
        assert "약점주제: 주제1 | 주제2 | 주제3" in _INSTRUCTION_WITH_WEAKNESS
        assert "빠뜨리지 마세요" in _INSTRUCTION_WITH_WEAKNESS

    def test_perfect_instruction_forbids_meta(self) -> None:
        """만점 지침에도 메타 금지가 명시된다."""
        assert "사고 과정" in _INSTRUCTION_PERFECT
        assert "영어 메타 발화" in _INSTRUCTION_PERFECT


class TestInlineReasoningLeak:
    """2026-06-14 라이브 발견: gemini-3.x 가 <think> 태그 없이 인라인 reasoning 을
    흘리고 그 줄에 한글 토큰('(미응답)' 등)이 섞여 기존 Hangul-보존 휴리스틱을 우회했다.
    영문 reasoning 서두 + ASCII 우세 줄은 한글이 섞여도 제거하도록 강화한 회귀 테스트.
    """

    def test_bilingual_reasoning_line_stripped(self) -> None:
        leaked = (
            "이번 모의고사에서 2문항을 맞혀 아쉬운 결과예요. 개념부터 다시 다지면 올릴 수 있어요.\n"
            'Wait, the user\'s selected option for all incorrect questions is "(미응답)" (Unanswered).\n'
            "So I should mention that for the incorrect questions\n"
            "약점주제: print와 return 차이 | 중복 코드"
        )
        out = sanitize_analysis(leaked)
        assert "Wait," not in out
        assert "So I should" not in out
        assert "이번 모의고사에서" in out
        assert "약점주제:" in out

    def test_normal_korean_body_not_dropped(self) -> None:
        """영문 서두가 아닌 정상 한국어 본문은 그대로 보존한다(false positive 방지)."""
        body = (
            "이번 시험은 4문항을 맞혔어요. 2번에서 큐를 골랐는데 FIFO/LIFO 혼동이에요.\n"
            "나중에 스택과 큐를 비교 정리해 보세요.\n"
            "약점주제: 스택과 큐"
        )
        out = sanitize_analysis(body)
        assert "이번 시험은" in out
        assert "나중에 스택과 큐" in out
        assert "약점주제:" in out

    def test_korean_starting_with_so_like_word_kept(self) -> None:
        """한글 본문이 우세하면(ASCII<60%) 보존된다 — 영문서두 오탐 방지."""
        body = "소스 코드를 다시 보면 print 사용이 핵심이에요. 잘 정리했어요."
        out = sanitize_analysis(body)
        assert "소스 코드를 다시 보면" in out

"""슬라이드 내 퀴즈 메타 문항 결정론적 2차 차단 필터 검증.

- is_meta_quiz_question: 메타 패턴 적중 / 정당한 과목 문항(오탐 가드) 통과
- check_payload: 메타 퀴즈를 quiz_meta Deficiency로 보고
- repair_payload: quiz_rewrites 병합 / 재작성도 메타면 원본 유지(graceful)
"""
from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload
from app.modules.ChapterStudio_V1.pipeline.quality import check_payload
from app.modules.ChapterStudio_V1.pipeline.quiz_meta_filter import is_meta_quiz_question
from app.modules.ChapterStudio_V1.pipeline.repair import repair_payload

_LONG_EXPLANATION = (
    "정답은 A이며, 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "특히 경계 조건을 놓쳐서 마지막 한 칸을 검사하지 못하는 약점과 직접 연결되므로, 종료 조건을 끝까지 따져 보는 습관이 필요합니다."
)


# ── is_meta_quiz_question: 메타 문항 적중 ─────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "이 강의는 총 몇 개의 슬라이드로 구성되어 있는가?",
        "이 슬라이드는 몇 번째 슬라이드인가?",
        "재귀 함수는 몇 번째 슬라이드에서 다루는가?",
        "슬라이드는 총 몇 개인가요?",
        "이 강의의 목차 순서로 옳은 것은?",
        "이 슬라이드의 제목은 무엇인가?",
        "이 퀴즈의 정답 번호는 무엇인가?",
        "해당 챕터는 몇 개의 퀴즈로 구성되어 있는가?",
        "How many slides are in this lecture?",
    ],
)
def test_meta_questions_detected(question: str) -> None:
    assert is_meta_quiz_question(question) is True


# ── is_meta_quiz_question: 정당한 과목 문항 오탐 가드 ─────────────────


@pytest.mark.parametrize(
    "question",
    [
        # CSS 주제 — '슬라이드 레이아웃'은 과목 내용이다.
        "CSS에서 슬라이드 레이아웃을 구현할 때 가장 적절한 속성은?",
        # 발표 도구 주제 — '슬라이드 마스터'는 기능 이름이다.
        "파워포인트에서 슬라이드 마스터의 역할로 옳은 것은?",
        # 슬라이드 귀속 퀴즈의 정상 발문 — 자기참조여도 내용을 묻는다.
        "이 슬라이드에서 설명한 정렬 알고리즘의 시간복잡도는?",
        # 자기참조 + '몇'이라도 구조물 명사가 없으면 내용 문항이다.
        "이 강의에서 배운 정렬 알고리즘 중 시간복잡도가 O(n log n)인 것은 몇 개인가?",
        # 일반 개념 문항.
        "스택 자료구조의 LIFO 특성을 가장 잘 설명한 것은?",
        # 영어 내용 문항.
        "What does this slide's example demonstrate about recursion?",
        # 빈 문자열 — 구조 검증 영역이므로 통과.
        "",
    ],
)
def test_legit_questions_pass(question: str) -> None:
    assert is_meta_quiz_question(question) is False


# ── check_payload: quiz_meta Deficiency 보고 ─────────────────────────


def test_check_payload_flags_meta_quiz() -> None:
    payload = parse_payload(json.dumps(_payload_with_meta_quiz(10, meta_idx=3), ensure_ascii=False), 10)

    report = check_payload(payload)

    assert report.quiz_meta_targets() == {3}
    assert report.supporting_needs_repair()
    reasons = [d.reason for d in report.deficiencies if d.field == "quiz_meta"]
    assert reasons and "메타 문항" in reasons[0]


def test_check_payload_no_meta_flag_for_content_quizzes() -> None:
    payload = parse_payload(json.dumps(_payload_with_meta_quiz(10, meta_idx=None), ensure_ascii=False), 10)

    assert check_payload(payload).quiz_meta_targets() == set()


# ── repair_payload: quiz_rewrites 병합 ───────────────────────────────


class _RewriteConnector:
    """메타 퀴즈를 내용 문항으로 재작성해 주는 repair 커넥터(테스트용)."""

    name = "rewrite_fake"

    def __init__(self, rewrite_question: str) -> None:
        self._rewrite_question = rewrite_question
        self.last_user: str = ""

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        self.last_user = req.user
        body = {
            "voice_scripts": [],
            "quiz_explanations": [],
            "quiz_rewrites": [
                {
                    "slide_idx": 3,
                    "question": self._rewrite_question,
                    "choices": ["O(n)", "O(n log n)", "O(n^2)", "O(1)"],
                    "answer_idx": 1,
                    "explanation": _LONG_EXPLANATION,
                }
            ],
        }
        return ChapterAIResponse(
            text=json.dumps(body, ensure_ascii=False), model="fake", input_tokens=1, output_tokens=1, finish_reason="stop"
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


@pytest.mark.anyio
async def test_repair_rewrites_meta_quiz_into_content_quiz() -> None:
    payload = parse_payload(json.dumps(_payload_with_meta_quiz(10, meta_idx=3), ensure_ascii=False), 10)
    report = check_payload(payload)
    connector = _RewriteConnector("병합 정렬의 평균 시간복잡도는 무엇인가?")

    repaired = await repair_payload(connector, payload, report, 10)

    rewritten = next(q for q in repaired.quizzes if q.slide_idx == 3)
    assert rewritten.question == "병합 정렬의 평균 시간복잡도는 무엇인가?"
    assert rewritten.answer_idx == 1
    assert rewritten.difficulty == payload.quizzes[3].difficulty  # 난이도는 불변
    # repair 요청 프롬프트에 메타 재작성 지시가 포함된다.
    assert "quiz_rewrites" in connector.last_user
    # 인덱스 계약은 그대로 유지된다.
    assert {q.slide_idx for q in repaired.quizzes} == set(range(10))


@pytest.mark.anyio
async def test_repair_keeps_original_when_rewrite_is_still_meta() -> None:
    payload = parse_payload(json.dumps(_payload_with_meta_quiz(10, meta_idx=3), ensure_ascii=False), 10)
    report = check_payload(payload)
    # 모델이 또 메타 문항을 내놓은 경우 — 원본 유지(절대 죽지 않음).
    connector = _RewriteConnector("이 강의는 총 몇 개의 슬라이드로 구성되어 있는가?")

    repaired = await repair_payload(connector, payload, report, 10)

    kept = next(q for q in repaired.quizzes if q.slide_idx == 3)
    assert kept.question == payload.quizzes[3].question
    assert {q.slide_idx for q in repaired.quizzes} == set(range(10))


# ── payload 빌더 ─────────────────────────────────────────────────────


def _payload_with_meta_quiz(slide_count: int, meta_idx: int | None) -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(slide_count)],
        "quizzes": [
            _meta_quiz(idx) if idx == meta_idx else _content_quiz(idx) for idx in range(slide_count)
        ],
        "note_blocks": [_note(idx) for idx in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [{"slide_idx": idx, "script_text": _long_voice()} for idx in range(slide_count)],
    }


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": (
            "<section><h2>핵심 개념을 한 화면에서 차근차근 정리해 보겠습니다.</h2>"
            "<p>먼저 이 개념이 왜 중요한지, 어디에서 쓰이는지 배경부터 천천히 설명합니다.</p>"
            "<p>다음으로 실제 동작 방식을 작은 예시와 함께 한 단계씩 살펴봅니다.</p>"
            "<p>마지막으로 자주 틀리는 지점과 직접 점검하는 방법을 함께 짚어 봅니다.</p></section>"
        ),
        "css": "",
    }


def _content_quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": "스택 자료구조의 LIFO 특성을 가장 잘 설명한 것은?",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": _LONG_EXPLANATION,
    }


def _meta_quiz(idx: int) -> dict[str, object]:
    return {**_content_quiz(idx), "question": "이 강의는 총 몇 개의 슬라이드로 구성되어 있는가?"}


def _note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서, 이 개념이 왜 중요한지 배경까지 함께 복습합니다.",
            "실수하기 쉬운 경계 조건을 작은 예시로 직접 손으로 점검하는 습관을 평소에 만들어 둡니다.",
            "오해하기 쉬운 부분을 반례와 함께 다시 한 번 짚어 가며, 정확한 판단 기준을 세워 둡니다.",
        ],
    }


def _assignment() -> dict[str, object]:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이+근거 표시",
        "expected_minutes": 30,
        "steps": ["핵심 개념을 직접 적용해 봅니다.", "결과를 근거와 함께 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }


def _long_voice() -> str:
    base = (
        "자, 이번 화면에서는 핵심 개념을 왜 이렇게 봐야 하는지 직관부터 아주 차근차근 풀어서 설명해 보겠습니다. "
        "먼저 이 개념이 실제로 어디에서 쓰이는지, 구체적인 예시 두세 가지를 머릿속에 떠올리며 감을 잡아 봅시다. "
        "그다음 작동 방식을 한 단계씩 따라가면서, 어떤 값이 들어와서 어떤 값으로 바뀌어 나가는지 천천히 살펴보겠습니다. "
        "여기서 많은 학습자가 헷갈리는 지점은 경계 조건을 정확히 나누는 부분인데요, 직접 손으로 그려 보면 또렷해집니다. "
        "실전에서는 입력이 비어 있거나 원소가 하나만 남는 경우를 따로 점검하는 습관이 정말 중요합니다. "
        "자주 빠지는 오답 함정은 종료 조건을 잘못 잡아 마지막 한 칸을 놓치는 경우이니 꼭 기억해 두세요. "
        "작은 예시 두세 개를 직접 끝까지 돌려 보면 이런 약점은 의외로 금방 교정됩니다. "
        "마지막으로 다음 화면에서는 지금 설명한 내용을 실제 코드로 한 줄씩 직접 확인해 보면서 마무리하겠습니다."
    )
    return base

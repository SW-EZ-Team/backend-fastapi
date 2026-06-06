"""seal 생성↔채점 스키마 교차 검증 단위 테스트.

배경:
    생성 경로(Question)와 채점 경로(GradeQuestion)의 canonical payload 불일치로
    HMAC 다름 → FastAPI 403 → Spring 502가 발생했다.
    _canonical_payload에서 draft_id·topic·difficulty·bloom_level을 제외해
    양 경로가 동일한 HMAC을 생성하도록 수정한 결과를 검증한다.

검증 범위:
    1. Question으로 생성한 seal을 GradeQuestion(4필드 없음)으로 verify → True
    2. Question으로 생성한 seal을 GradeQuestion(4필드 값 있음)으로 verify → True
    3. correct_answer 변조 시 verify → False (무결성 유지)
    4. stem 변조 시 verify → False (무결성 유지)
    5. points 변조 시 verify → False (무결성 유지)
    6. 7개 문항 유형(객관식·빈칸·순서·연결·서술·실기·단답)에 대해 seal round-trip True
    7. GradeQuestion(4필드 null)로 생성한 seal을 Question(4필드 포함)으로 verify → True
    8. GradeQuestion(4필드 null)로 생성하고 GradeQuestion(4필드 값 있음)으로 verify → True
"""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.grading.seal import (
    attach_answer_key_seal,
    create_answer_key_seal,
    verify_answer_key_seal,
)
from app.modules.ExamForge_V1.schemas.grading import GradeQuestion
from app.modules.ExamForge_V1.schemas.question import MatchingPair, Question, QuestionOption


# ---------------------------------------------------------------------------
# 픽스처 — Question(생성 경로) 빌더
# ---------------------------------------------------------------------------

def _make_question(
    *,
    question_id: str = "q-test",
    template_id: str = "ko_multiple_choice_5",
    stem: str = "애자일의 핵심 원칙은?",
    correct_answer: str = "2",
    explanation: str = "변화 대응이 핵심이다.",
    points: float = 2.0,
    **extra,
) -> Question:
    """테스트용 Question(생성 경로) 객체를 만든다."""
    return Question(
        question_id=question_id,
        draft_id="d-test",
        template_id=template_id,
        topic="소프트웨어공학",
        difficulty=3,
        bloom_level="이해",
        stem=stem,
        options=[
            QuestionOption(label="1", text="순차 진행"),
            QuestionOption(label="2", text="변화 대응", is_correct=True),
        ],
        correct_answer=correct_answer,
        explanation=explanation,
        source_reference="애자일 선언문",
        points=points,
        **extra,
    )


def _make_grade_question_no_meta(
    *,
    question_id: str = "q-test",
    template_id: str = "ko_multiple_choice_5",
    stem: str = "애자일의 핵심 원칙은?",
    correct_answer: str = "2",
    explanation: str = "변화 대응이 핵심이다.",
    points: float = 2.0,
) -> GradeQuestion:
    """4개 메타 필드가 모두 없는 GradeQuestion(채점 경로) 객체를 만든다."""
    return GradeQuestion(
        question_id=question_id,
        template_id=template_id,
        stem=stem,
        options=[
            QuestionOption(label="1", text="순차 진행"),
            QuestionOption(label="2", text="변화 대응", is_correct=True),
        ],
        correct_answer=correct_answer,
        explanation=explanation,
        source_reference="애자일 선언문",
        points=points,
        # draft_id, topic, difficulty, bloom_level 모두 생략(None)
    )


def _make_grade_question_with_meta(
    *,
    question_id: str = "q-test",
    template_id: str = "ko_multiple_choice_5",
    stem: str = "애자일의 핵심 원칙은?",
    correct_answer: str = "2",
    explanation: str = "변화 대응이 핵심이다.",
    points: float = 2.0,
) -> GradeQuestion:
    """4개 메타 필드를 포함한 GradeQuestion(채점 경로) 객체를 만든다."""
    return GradeQuestion(
        question_id=question_id,
        draft_id="d-test",
        template_id=template_id,
        topic="소프트웨어공학",
        difficulty=3,
        bloom_level="이해",
        stem=stem,
        options=[
            QuestionOption(label="1", text="순차 진행"),
            QuestionOption(label="2", text="변화 대응", is_correct=True),
        ],
        correct_answer=correct_answer,
        explanation=explanation,
        source_reference="애자일 선언문",
        points=points,
    )


# ---------------------------------------------------------------------------
# 1. 핵심: Question seal → GradeQuestion(4필드 없음) verify = True
# ---------------------------------------------------------------------------

def test_seal_created_with_question_verified_with_grade_question_no_meta() -> None:
    """Question(생성 경로)으로 만든 seal을 GradeQuestion(4필드 null)로 검증하면 True다.

    이것이 502 버그의 근본 재현 케이스다.
    수정 전: draft_id·topic·difficulty·bloom_level이 canonical에 포함 → HMAC 불일치 → False
    수정 후: 4개 필드 제외 → 동일 canonical → HMAC 일치 → True
    """
    exam_id = "exam-cross-1"
    question = _make_question()
    seal = create_answer_key_seal(exam_id, [question])

    grade_q = _make_grade_question_no_meta()

    assert verify_answer_key_seal(exam_id, [grade_q], seal) is True


# ---------------------------------------------------------------------------
# 2. Question seal → GradeQuestion(4필드 값 있음) verify = True
# ---------------------------------------------------------------------------

def test_seal_created_with_question_verified_with_grade_question_with_meta() -> None:
    """Question으로 만든 seal을 4개 메타 필드가 있는 GradeQuestion으로도 검증하면 True다."""
    exam_id = "exam-cross-2"
    question = _make_question()
    seal = create_answer_key_seal(exam_id, [question])

    grade_q = _make_grade_question_with_meta()

    assert verify_answer_key_seal(exam_id, [grade_q], seal) is True


# ---------------------------------------------------------------------------
# 3. correct_answer 변조 시 verify = False (무결성 유지)
# ---------------------------------------------------------------------------

def test_tampered_correct_answer_fails_verification() -> None:
    """정답(correct_answer)을 변조하면 seal 검증이 False를 반환한다."""
    exam_id = "exam-tamper-answer"
    question = _make_question(correct_answer="2")
    seal = create_answer_key_seal(exam_id, [question])

    tampered = _make_grade_question_no_meta(correct_answer="1")  # 변조
    assert verify_answer_key_seal(exam_id, [tampered], seal) is False


# ---------------------------------------------------------------------------
# 4. stem 변조 시 verify = False
# ---------------------------------------------------------------------------

def test_tampered_stem_fails_verification() -> None:
    """문제 줄기(stem)를 변조하면 seal 검증이 False를 반환한다."""
    exam_id = "exam-tamper-stem"
    question = _make_question(stem="애자일의 핵심 원칙은?")
    seal = create_answer_key_seal(exam_id, [question])

    tampered = _make_grade_question_no_meta(stem="폭포수 모델의 특징은?")  # 변조
    assert verify_answer_key_seal(exam_id, [tampered], seal) is False


# ---------------------------------------------------------------------------
# 5. points 변조 시 verify = False
# ---------------------------------------------------------------------------

def test_tampered_points_fails_verification() -> None:
    """배점(points)을 변조하면 seal 검증이 False를 반환한다."""
    exam_id = "exam-tamper-points"
    question = _make_question(points=2.0)
    seal = create_answer_key_seal(exam_id, [question])

    tampered = _make_grade_question_no_meta(points=10.0)  # 배점 변조
    assert verify_answer_key_seal(exam_id, [tampered], seal) is False


# ---------------------------------------------------------------------------
# 6. 7개 유형별 seal round-trip (attach → verify) = True
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_id,extra_kwargs,grade_extra", [
    # 객관식 4지선다
    (
        "ko_multiple_choice_4",
        {"options": [QuestionOption(label="1", text="A"), QuestionOption(label="2", text="B", is_correct=True)]},
        {"options": [QuestionOption(label="1", text="A"), QuestionOption(label="2", text="B", is_correct=True)]},
    ),
    # 객관식 5지선다
    (
        "ko_multiple_choice_5",
        {"options": [QuestionOption(label="1", text="A"), QuestionOption(label="2", text="B", is_correct=True)]},
        {"options": [QuestionOption(label="1", text="A"), QuestionOption(label="2", text="B", is_correct=True)]},
    ),
    # 빈칸 채우기
    (
        "ko_fill_blank",
        {"blank_positions": [1, 2], "blank_answers": ["애자일", "스크럼"], "options": None},
        {"blank_positions": [1, 2], "blank_answers": ["애자일", "스크럼"], "options": None},
    ),
    # 순서 배열
    (
        "ko_ordering",
        {"ordering_items": ["구현", "요구사항", "설계"], "correct_ordering": ["요구사항", "설계", "구현"], "options": None},
        {"ordering_items": ["구현", "요구사항", "설계"], "correct_ordering": ["요구사항", "설계", "구현"], "options": None},
    ),
    # 연결형 (matching) — Question/GradeQuestion 모두 MatchingPair 지원
    (
        "ko_matching",
        {"matching_pairs": [MatchingPair(left="A", right="B")], "options": None},
        {"matching_pairs": [MatchingPair(left="A", right="B")], "options": None},
    ),
    # 서술형
    ("ko_descriptive", {"options": None}, {"options": None}),
    # 단답형
    ("ko_short_answer", {"options": None}, {"options": None}),
])
def test_seal_round_trip_by_template(
    template_id: str,
    extra_kwargs: dict,
    grade_extra: dict,
) -> None:
    """7개 문항 유형에 대해 Question(생성) → GradeQuestion(채점) seal round-trip이 True다."""
    exam_id = f"exam-roundtrip-{template_id}"
    q = Question(
        question_id="q-rt",
        draft_id="d-rt",
        template_id=template_id,
        topic="테스트주제",
        difficulty=2,
        bloom_level="이해",
        stem="테스트 문제 줄기",
        correct_answer="정답",
        explanation="해설 내용",
        source_reference="출처",
        points=1.0,
        **extra_kwargs,
    )
    seal = create_answer_key_seal(exam_id, [q])

    gq = GradeQuestion(
        question_id="q-rt",
        template_id=template_id,
        stem="테스트 문제 줄기",
        correct_answer="정답",
        explanation="해설 내용",
        source_reference="출처",
        points=1.0,
        # draft_id·topic·difficulty·bloom_level 모두 생략
        **grade_extra,
    )
    assert verify_answer_key_seal(exam_id, [gq], seal) is True, (
        f"template_id={template_id}: Question으로 생성한 seal을 "
        "GradeQuestion으로 verify했을 때 True여야 한다."
    )


# ---------------------------------------------------------------------------
# 7. GradeQuestion(4필드 null)로 생성 → Question(4필드 포함)으로 verify = True
# ---------------------------------------------------------------------------

def test_seal_created_with_grade_question_no_meta_verified_with_question() -> None:
    """GradeQuestion(4필드 null)로 만든 seal을 Question(4필드 포함)으로 검증하면 True다."""
    exam_id = "exam-cross-reverse"
    grade_q = _make_grade_question_no_meta()
    seal = create_answer_key_seal(exam_id, [grade_q])

    question = _make_question()
    assert verify_answer_key_seal(exam_id, [question], seal) is True


# ---------------------------------------------------------------------------
# 8. GradeQuestion(null) → GradeQuestion(값 있음) verify = True
# ---------------------------------------------------------------------------

def test_seal_created_with_grade_question_null_verified_with_grade_question_meta() -> None:
    """GradeQuestion(4필드 null)로 만든 seal을 4필드 있는 GradeQuestion으로도 True다."""
    exam_id = "exam-cross-grade"
    no_meta = _make_grade_question_no_meta()
    seal = create_answer_key_seal(exam_id, [no_meta])

    with_meta = _make_grade_question_with_meta()
    assert verify_answer_key_seal(exam_id, [with_meta], seal) is True


# ---------------------------------------------------------------------------
# 9. attach_answer_key_seal + verify 통합 (파이프라인 엔드투엔드 모의)
# ---------------------------------------------------------------------------

def test_attach_answer_key_seal_and_verify_with_grade_question() -> None:
    """attach_answer_key_seal이 생성한 seal을 채점 경로 GradeQuestion으로 검증한다."""
    q = _make_question()
    state = {
        "exam_id": "exam-attach-verify",
        "calibrated_questions": [q.model_dump(mode="json")],
    }

    enriched = attach_answer_key_seal(state)
    seal = enriched["answer_key_seal"]

    # 채점 경로에서 4필드 없는 GradeQuestion으로 verify
    grade_q = _make_grade_question_no_meta()
    assert verify_answer_key_seal("exam-attach-verify", [grade_q], seal) is True


# ---------------------------------------------------------------------------
# 10. explanation 변조 시 verify = False (explanation은 채점 근거 — 보호 대상)
# ---------------------------------------------------------------------------

def test_tampered_explanation_fails_verification() -> None:
    """해설(explanation)을 변조하면 seal 검증이 False를 반환한다."""
    exam_id = "exam-tamper-explanation"
    question = _make_question(explanation="변화 대응이 핵심이다.")
    seal = create_answer_key_seal(exam_id, [question])

    tampered = _make_grade_question_no_meta(explanation="임의로 바뀐 해설")  # 변조
    assert verify_answer_key_seal(exam_id, [tampered], seal) is False

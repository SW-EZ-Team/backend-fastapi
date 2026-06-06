"""GradeQuestion 스키마 분리 수정 검증 테스트.

수정 배경:
    Spring이 서술형 채점 요청 시 draft_id·topic·difficulty·bloom_level을 null로 전송하면
    기존 Question 스키마가 이 4개 필드를 required로 강제 → Pydantic 422 → Spring 502 발생.
    GradeQuestion 스키마를 분리하여 채점 경로에서 해당 필드를 Optional로 처리한다.

검증 범위:
    1. null/누락 메타 필드로 GradeQuestion 인스턴스 생성 성공
    2. GradeSubmissionRequest에서 null 메타 필드 허용
    3. 채점 필수 필드(stem·correct_answer·explanation)는 여전히 required
    4. Question 스키마는 기존 required 유지 (생성 경로 회귀 없음)
    5. 봉인 계산이 GradeQuestion에서도 정상 동작
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ExamForge_V1.grading.seal import create_answer_key_seal
from app.modules.ExamForge_V1.schemas.grading import GradeQuestion, GradeSubmissionRequest, SubmittedAnswer
from app.modules.ExamForge_V1.schemas.question import Question
from app.modules.ExamForge_V1.tests.grading_samples import (
    grade_choice_question_null_meta,
    grade_essay_question_null_meta,
)


# ---------------------------------------------------------------------------
# 1. null/누락 메타 필드로 GradeQuestion 생성 성공
# ---------------------------------------------------------------------------


def test_grade_question_allows_null_draft_id() -> None:
    """draft_id가 None이어도 GradeQuestion 생성이 성공한다."""
    q = GradeQuestion(
        question_id="qid-1",
        template_id="ko_descriptive",
        stem="문제 줄기",
        correct_answer="정답",
        explanation="해설",
        draft_id=None,
    )
    assert q.draft_id is None


def test_grade_question_allows_null_topic() -> None:
    """topic이 None이어도 GradeQuestion 생성이 성공한다."""
    q = GradeQuestion(
        question_id="qid-2",
        template_id="ko_descriptive",
        stem="문제 줄기",
        correct_answer="정답",
        explanation="해설",
        topic=None,
    )
    assert q.topic is None


def test_grade_question_allows_null_difficulty() -> None:
    """difficulty가 None이어도 GradeQuestion 생성이 성공한다."""
    q = GradeQuestion(
        question_id="qid-3",
        template_id="ko_descriptive",
        stem="문제 줄기",
        correct_answer="정답",
        explanation="해설",
        difficulty=None,
    )
    assert q.difficulty is None


def test_grade_question_allows_null_bloom_level() -> None:
    """bloom_level이 None이어도 GradeQuestion 생성이 성공한다."""
    q = GradeQuestion(
        question_id="qid-4",
        template_id="ko_descriptive",
        stem="문제 줄기",
        correct_answer="정답",
        explanation="해설",
        bloom_level=None,
    )
    assert q.bloom_level is None


def test_grade_question_allows_all_four_fields_omitted() -> None:
    """draft_id·topic·difficulty·bloom_level 4개 모두 생략해도 GradeQuestion이 생성된다."""
    q = GradeQuestion(
        question_id="qid-5",
        template_id="ko_essay",
        stem="문제 줄기",
        correct_answer="정답",
        explanation="해설",
    )
    assert q.draft_id is None
    assert q.topic is None
    assert q.difficulty is None
    assert q.bloom_level is None


# ---------------------------------------------------------------------------
# 2. GradeSubmissionRequest에서 null 메타 필드 허용 (Spring → FastAPI 실제 경로)
# ---------------------------------------------------------------------------


def test_grade_submission_request_accepts_null_meta_in_questions() -> None:
    """Spring이 4개 메타 필드를 null로 보내도 GradeSubmissionRequest가 422 없이 파싱된다."""
    essay_q = grade_essay_question_null_meta()
    seal = create_answer_key_seal("exam-null-test", [essay_q])

    # Spring이 null을 dict로 직렬화해 전송하는 패턴을 재현
    request_dict = {
        "attempt_id": "attempt-null",
        "exam_id": "exam-null-test",
        "answer_key_seal": seal,
        "questions": [
            {
                "question_id": "q-essay-null",
                "template_id": "ko_descriptive",
                "draft_id": None,
                "topic": None,
                "difficulty": None,
                "bloom_level": None,
                "stem": "애자일 방법론이 변화 대응에 유리한 이유를 설명하시오.",
                "correct_answer": "짧은 반복과 피드백으로 변화에 유연하게 대응한다.",
                "explanation": "핵심 개념 3점, 근거 제시 2점으로 채점한다.",
                "source_reference": "짧은 주기의 반복적 개발",
                "points": 5.0,
            }
        ],
        "submitted_answers": [
            {"question_id": "q-essay-null", "answer": "변화에 유연하게 대응합니다."}
        ],
    }

    # ValidationError 없이 파싱되어야 한다
    req = GradeSubmissionRequest.model_validate(request_dict)
    assert req.questions[0].draft_id is None
    assert req.questions[0].topic is None
    assert req.questions[0].difficulty is None
    assert req.questions[0].bloom_level is None


def test_grade_submission_request_accepts_missing_meta_fields() -> None:
    """Spring이 4개 메타 필드를 아예 키 자체를 포함하지 않아도 파싱된다."""
    choice_q = grade_choice_question_null_meta()
    seal = create_answer_key_seal("exam-missing-test", [choice_q])

    request_dict = {
        "attempt_id": "attempt-missing",
        "exam_id": "exam-missing-test",
        "answer_key_seal": seal,
        "questions": [
            {
                "question_id": "q-choice-null",
                "template_id": "ko_multiple_choice_5",
                # draft_id, topic, difficulty, bloom_level 키 자체가 없음
                "stem": "애자일의 특징은?",
                "options": [
                    {"label": "1", "text": "순차 진행", "is_correct": False},
                    {"label": "2", "text": "변화 대응", "is_correct": True},
                ],
                "correct_answer": "2",
                "explanation": "애자일은 변화에 유연하게 대응한다.",
                "source_reference": "애자일 방법론",
                "points": 2.0,
            }
        ],
        "submitted_answers": [
            {"question_id": "q-choice-null", "answer": "2"}
        ],
    }

    req = GradeSubmissionRequest.model_validate(request_dict)
    assert req.questions[0].draft_id is None
    assert req.questions[0].bloom_level is None


# ---------------------------------------------------------------------------
# 3. 채점 필수 필드는 여전히 required — ValidationError 발생 확인
# ---------------------------------------------------------------------------


def test_grade_question_rejects_missing_stem() -> None:
    """stem이 없으면 GradeQuestion 생성이 실패한다."""
    with pytest.raises(ValidationError) as exc_info:
        GradeQuestion(
            question_id="qid-bad",
            template_id="ko_descriptive",
            # stem 누락
            correct_answer="정답",
            explanation="해설",
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("stem",) for e in errors)


def test_grade_question_rejects_missing_correct_answer() -> None:
    """correct_answer가 없으면 GradeQuestion 생성이 실패한다."""
    with pytest.raises(ValidationError) as exc_info:
        GradeQuestion(
            question_id="qid-bad2",
            template_id="ko_descriptive",
            stem="문제",
            # correct_answer 누락
            explanation="해설",
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("correct_answer",) for e in errors)


def test_grade_question_rejects_missing_explanation() -> None:
    """explanation이 없으면 GradeQuestion 생성이 실패한다."""
    with pytest.raises(ValidationError) as exc_info:
        GradeQuestion(
            question_id="qid-bad3",
            template_id="ko_descriptive",
            stem="문제",
            correct_answer="정답",
            # explanation 누락
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("explanation",) for e in errors)


def test_grade_question_rejects_missing_question_id() -> None:
    """question_id가 없으면 GradeQuestion 생성이 실패한다."""
    with pytest.raises(ValidationError) as exc_info:
        GradeQuestion(
            # question_id 누락
            template_id="ko_descriptive",
            stem="문제",
            correct_answer="정답",
            explanation="해설",
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("question_id",) for e in errors)


# ---------------------------------------------------------------------------
# 4. Question 스키마는 기존 required 유지 (생성 경로 회귀 없음)
# ---------------------------------------------------------------------------


def test_question_schema_still_requires_draft_id() -> None:
    """생성 경로 Question 스키마는 draft_id가 없으면 여전히 ValidationError를 발생시킨다."""
    with pytest.raises(ValidationError) as exc_info:
        Question(
            question_id="q-gen",
            # draft_id 누락
            template_id="ko_descriptive",
            topic="주제",
            difficulty=3,
            bloom_level="이해",
            stem="문제",
            correct_answer="정답",
            explanation="해설",
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("draft_id",) for e in errors)


def test_question_schema_still_requires_topic() -> None:
    """생성 경로 Question 스키마는 topic이 없으면 여전히 ValidationError를 발생시킨다."""
    with pytest.raises(ValidationError) as exc_info:
        Question(
            question_id="q-gen2",
            draft_id="d-gen2",
            template_id="ko_descriptive",
            # topic 누락
            difficulty=3,
            bloom_level="이해",
            stem="문제",
            correct_answer="정답",
            explanation="해설",
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("topic",) for e in errors)


def test_question_schema_still_requires_difficulty() -> None:
    """생성 경로 Question 스키마는 difficulty가 없으면 여전히 ValidationError를 발생시킨다."""
    with pytest.raises(ValidationError) as exc_info:
        Question(
            question_id="q-gen3",
            draft_id="d-gen3",
            template_id="ko_descriptive",
            topic="주제",
            # difficulty 누락
            bloom_level="이해",
            stem="문제",
            correct_answer="정답",
            explanation="해설",
        )
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("difficulty",) for e in errors)


# ---------------------------------------------------------------------------
# 5. 봉인 계산이 GradeQuestion에서도 정상 동작
# ---------------------------------------------------------------------------


def test_seal_creation_works_with_grade_question() -> None:
    """create_answer_key_seal이 GradeQuestion 목록을 인자로 받아 서명을 생성한다."""
    questions = [grade_essay_question_null_meta(), grade_choice_question_null_meta()]
    seal = create_answer_key_seal("exam-seal-test", questions)
    assert seal.startswith("v1.")
    assert len(seal) >= 46


def test_seal_verification_works_with_grade_question() -> None:
    """verify_answer_key_seal이 GradeQuestion 목록으로 서명 일치를 검증한다."""
    from app.modules.ExamForge_V1.grading.seal import verify_answer_key_seal

    questions = [grade_essay_question_null_meta()]
    seal = create_answer_key_seal("exam-verify-test", questions)

    # 동일 목록으로 검증하면 True
    assert verify_answer_key_seal("exam-verify-test", questions, seal) is True

    # 변경된 목록으로 검증하면 False
    altered = [grade_choice_question_null_meta()]
    assert verify_answer_key_seal("exam-verify-test", altered, seal) is False

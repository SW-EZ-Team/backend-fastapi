"""객관 문항 피드백 실질성 회귀 테스트 (2026-06-14 사용자 신고).

기존 결정론 채점기는 feedback에 '참거짓 판정 일치', '정답 보기 선택' 같은
짧은 상태 라벨만 넣어, 결과지의 '피드백' 칸이 무의미하게 보였다.
이제 모든 객관 문항 feedback이 정/오 판정 + 정답 내용 + 안내를 담는지 검증한다.
라이브 AI 호출 없이 결정론 경로만 검증한다(추가 비용 0).
"""
from __future__ import annotations

from app.modules.ExamForge_V1.grading.deterministic import (
    grade_blank_question,
    grade_choice_question,
    grade_matching_question,
    grade_ordering_question,
    grade_true_false_question,
    grade_unanswered_question,
)
from app.modules.ExamForge_V1.schemas.grading import GradeQuestion
from app.modules.ExamForge_V1.schemas.question import QuestionOption
from app.modules.ExamForge_V1.tests.grading_samples import (
    blank_question,
    choice_question,
    matching_question,
    ordering_question,
)

# 회귀 방지: 더 이상 나오면 안 되는 옛 짧은 라벨들
_STALE_LABELS = {
    "정답 보기 선택", "오답 보기 선택",
    "참거짓 판정 일치", "참거짓 판정 불일치",
    "빈칸 위치별 채점", "순서 위치별 채점", "연결 항목별 채점",
    "허용 답안과 일치", "허용 답안과 불일치", "답안 미제출",
}


def _assert_substantive(feedback: str) -> None:
    """피드백이 옛 라벨이 아니고, 판정 어휘를 담은 실질 문장인지 확인한다."""
    assert feedback not in _STALE_LABELS, f"옛 짧은 라벨이 그대로 노출됨: {feedback}"
    assert len(feedback) >= 12, f"피드백이 너무 짧음: {feedback}"
    assert any(token in feedback for token in ("맞혔", "정답", "오답", "제출하지")), feedback


def test_choice_correct_feedback_has_answer() -> None:
    """객관식 정답: 판정 + 정답 보기 문장을 담는다."""
    fb = grade_choice_question(choice_question(), "2").feedback
    _assert_substantive(fb)
    assert "맞혔" in fb
    assert "변화 대응" in fb  # 정답 보기 문장이 들어가야 한다


def test_choice_wrong_feedback_reveals_answer_and_hint() -> None:
    """객관식 오답: 오답 판정 + 정답 공개 + 해설 안내."""
    fb = grade_choice_question(choice_question(), "1").feedback
    _assert_substantive(fb)
    assert "오답" in fb
    assert "변화 대응" in fb
    assert "해설" in fb


def test_true_false_feedback_uses_human_label() -> None:
    """참거짓: '참거짓 판정 일치'가 아니라 참(O)/거짓(X) 사람이 읽는 라벨을 쓴다."""
    q = GradeQuestion(
        question_id="q-tf",
        template_id="ko_true_false",
        stem="프로세스는 독립된 메모리 공간을 가진다.",
        correct_answer="참",
        explanation="프로세스는 독립 메모리 공간을 가진다.",
        points=2.0,
    )
    correct = grade_true_false_question(q, "참").feedback
    wrong = grade_true_false_question(q, "거짓").feedback
    _assert_substantive(correct)
    _assert_substantive(wrong)
    assert "참(O)" in correct and "참(O)" in wrong


def test_blank_partial_feedback_counts_and_lists() -> None:
    """빈칸: 맞힌 개수와 정답 목록을 보여준다."""
    full = grade_blank_question(blank_question(), ["애자일", "스크럼"]).feedback
    partial = grade_blank_question(blank_question(), ["애자일", "워터폴"]).feedback
    _assert_substantive(full)
    _assert_substantive(partial)
    assert "애자일" in full and "스크럼" in full
    assert "1개" in partial  # 2개 중 1개 정답


def test_ordering_feedback_shows_correct_sequence() -> None:
    """순서: 정답 순서를 화살표로 보여준다."""
    fb = grade_ordering_question(ordering_question(), ["구현", "요구사항", "설계"]).feedback
    _assert_substantive(fb)
    assert "요구사항" in fb and "→" in fb


def test_matching_feedback_shows_correct_pairs() -> None:
    """연결: 정답 연결 쌍을 보여준다."""
    fb = grade_matching_question(
        matching_question(), {"Singleton": "구조 패턴", "Adapter": "생성 패턴"}
    ).feedback
    _assert_substantive(fb)
    assert "Singleton" in fb and "생성 패턴" in fb


def test_unanswered_feedback_reveals_answer() -> None:
    """미제출: '답안 미제출'이 아니라 미제출 안내 + 정답 공개."""
    q = GradeQuestion(
        question_id="q-skip",
        template_id="ko_multiple_choice_5",
        stem="애자일의 특징은?",
        options=[
            QuestionOption(label="1", text="순차 진행"),
            QuestionOption(label="2", text="변화 대응", is_correct=True),
        ],
        correct_answer="2",
        explanation="애자일은 변화에 대응한다.",
        points=2.0,
    )
    fb = grade_unanswered_question(q).feedback
    _assert_substantive(fb)
    assert "제출하지" in fb
    assert "변화 대응" in fb

"""품질 모듈 테스트."""
from __future__ import annotations

from app.modules.ExamForge_V1.quality.answer_positions import answer_position_counts
from app.modules.ExamForge_V1.quality.answer_positions import balance_correct_answer_positions
from app.modules.ExamForge_V1.quality.deduplicator import check_duplicates
from app.modules.ExamForge_V1.quality.deduplicator import deduplicate_questions
from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
from app.modules.ExamForge_V1.quality.difficulty_scorer import score_bloom_distribution
from app.modules.ExamForge_V1.quality.coverage_analyzer import analyze_coverage
from app.modules.ExamForge_V1.quality.explanation_checker import check_explanation_quality
from app.modules.ExamForge_V1.quality.metrics import compute_quality_metrics
from app.modules.ExamForge_V1.quality.cjk_sanitizer import sanitize_exam_question


class TestDeduplicator:
    """중복 검사 테스트."""

    def test_no_duplicates(self) -> None:
        """서로 다른 문제는 중복 없음."""
        questions = [
            {"stem": "운영체제의 역할을 설명하시오.", "question_id": "q1"},
            {"stem": "TCP/IP 프로토콜의 계층 구조는?", "question_id": "q2"},
            {"stem": "객체지향 프로그래밍의 4대 특성은?", "question_id": "q3"},
        ]
        score, pairs = check_duplicates(questions)
        assert score == 1.0
        assert pairs == []

    def test_exact_duplicates(self) -> None:
        """동일한 문제는 중복으로 탐지된다."""
        questions = [
            {"stem": "운영체제의 역할을 설명하시오.", "question_id": "q1"},
            {"stem": "운영체제의 역할을 설명하시오.", "question_id": "q2"},
        ]
        score, pairs = check_duplicates(questions)
        assert score < 1.0
        assert len(pairs) == 1

    def test_semantic_rule_duplicates(self) -> None:
        """표현이 달라도 같은 풀이 규칙이면 중복 후보로 잡는다."""
        questions = [
            {"stem": "절댓값을 먼저 계산하고 가장 큰 값을 고르는 문제이다.", "question_id": "q1"},
            {"stem": "절댓값 계산 후 가장 큰 값을 선택하는 문제이다.", "question_id": "q2"},
            {"stem": "분수의 통분 원리를 설명하는 문항이다.", "question_id": "q3"},
        ]
        score, pairs = check_duplicates(questions)
        assert score < 1.0
        assert ("q1", "q2") in pairs

    def test_deduplicate_questions_removes_later_item(self) -> None:
        """중복 문항 제거는 뒤쪽 문항만 재생성 대상으로 돌린다."""
        questions = [
            {"stem": "같은 개념을 묻는 문제", "draft_id": "d1"},
            {"stem": "같은 개념을 묻는 문제", "draft_id": "d2"},
        ]
        unique, removed = deduplicate_questions(questions)
        assert [q["draft_id"] for q in unique] == ["d1"]
        assert removed == ["d2"]


class TestConsistencyChecker:
    """일관성 검사 테스트."""

    def test_consistent_question(self) -> None:
        """일관된 문제는 통과한다."""
        questions = [{
            "question_id": "q1",
            "correct_answer": "2",
            "options": [
                {"label": "1", "text": "A", "is_correct": False},
                {"label": "2", "text": "B", "is_correct": True},
            ],
            "explanation": "정답은 2번이다.",
        }]
        issues = check_consistency(questions)
        assert issues == []

    def test_mismatched_correct_answer(self) -> None:
        """정답 불일치를 감지한다."""
        questions = [{
            "question_id": "q1",
            "correct_answer": "3",
            "options": [
                {"label": "1", "text": "A", "is_correct": False},
                {"label": "2", "text": "B", "is_correct": True},
            ],
            "explanation": "정답은 3번이다.",
        }]
        issues = check_consistency(questions)
        assert len(issues) > 0


class TestAnswerPositionBalance:
    """정답 위치 균등화 테스트."""

    def test_balances_five_option_answer_positions(self) -> None:
        """10문항이면 5개 위치가 2회씩 배정된다."""
        questions = [
            {
                "question_id": f"q{i}",
                "options": [
                    {"label": "1", "text": "정답", "is_correct": True},
                    {"label": "2", "text": "오답", "is_correct": False},
                    {"label": "3", "text": "오답", "is_correct": False},
                    {"label": "4", "text": "오답", "is_correct": False},
                    {"label": "5", "text": "오답", "is_correct": False},
                ],
            }
            for i in range(10)
        ]
        balanced = balance_correct_answer_positions(questions)
        assert answer_position_counts(balanced) == {0: 2, 1: 2, 2: 2, 3: 2, 4: 2}
        assert [opt["label"] for opt in balanced[4]["options"]] == ["1", "2", "3", "4", "5"]


class TestExplanationChecker:
    """오답별 해설 품질 검사 테스트."""

    def test_missing_wrong_option_explanation_is_flagged(self) -> None:
        """객관식 해설이 오답 일부를 빼먹으면 실패한다."""
        question = {
            "correct_answer": "1",
            "explanation": "정답 근거: 1번은 맞다. 오답 해설: 2번은 오개념이다.",
            "options": [
                {"label": "1", "text": "정답", "is_correct": True},
                {"label": "2", "text": "오답", "is_correct": False},
                {"label": "3", "text": "오답", "is_correct": False},
                {"label": "4", "text": "오답", "is_correct": False},
                {"label": "5", "text": "오답", "is_correct": False},
            ],
        }
        issues = check_explanation_quality(question)
        assert any("오답별 해설 누락" in issue for issue in issues)


class TestCjkSanitizer:
    """모의고사 표시 텍스트 CJK 정리 테스트."""

    def test_sanitizes_stem_explanation_and_option_text(self) -> None:
        """발문·해설·보기 텍스트에서 한자·가나 런을 제거한다."""
        question = {
            "stem": "정렬 순서가 颠倒되면 무엇이 문제인가?",
            "correct_answer": "2",
            "explanation": "정답 근거는 颠倒了 상태를 바로잡는 것이다.",
            "options": [
                {"label": "1", "text": "그대로 둔다 颠倒了", "is_correct": False},
                {"label": "2", "text": "순서를 바로잡는다", "is_correct": True},
            ],
        }

        sanitized = sanitize_exam_question(question)

        assert "颠倒" not in sanitized["stem"]
        assert "颠倒了" not in sanitized["explanation"]
        assert "颠倒了" not in sanitized["options"][0]["text"]
        assert sanitized["correct_answer"] == "2"
        assert sanitized["options"][0]["label"] == "1"


class TestDifficultyScorer:
    """블룸 분포 테스트."""

    def test_distribution_calculation(self) -> None:
        """분포를 올바르게 계산한다."""
        questions = [
            {"bloom_level": "기억"},
            {"bloom_level": "기억"},
            {"bloom_level": "이해"},
            {"bloom_level": "적용"},
        ]
        dist = score_bloom_distribution(questions)
        assert dist["기억"] == 0.5
        assert dist["이해"] == 0.25
        assert dist["적용"] == 0.25


class TestCoverageAnalyzer:
    """커버리지 분석 테스트."""

    def test_full_coverage(self) -> None:
        """모든 주제가 커버되면 점수 1.0."""
        questions = [
            {"topic": "A"},
            {"topic": "B"},
        ]
        score, uncovered = analyze_coverage(
            questions, {"A": 0.5, "B": 0.5}
        )
        assert score == 1.0
        assert uncovered == []

    def test_partial_coverage(self) -> None:
        """일부 주제 미커버 시 점수 하락."""
        questions = [{"topic": "A"}]
        score, uncovered = analyze_coverage(
            questions, {"A": 0.5, "B": 0.5}
        )
        assert score < 1.0
        assert "B" in uncovered


class TestMetrics:
    """통합 메트릭 계산 테스트."""

    def test_compute_all_metrics(self) -> None:
        """모든 메트릭이 계산된다."""
        questions = [
            {
                "question_id": "q1",
                "stem": "문제1",
                "topic": "A",
                "bloom_level": "이해",
                "options": [
                    {"label": "1", "text": "보기A입니다", "is_correct": False},
                    {"label": "2", "text": "보기B입니다", "is_correct": True},
                ],
            }
        ]
        metrics = compute_quality_metrics(
            questions=questions,
            topic_weights={"A": 1.0},
            verification_results=[{"passed": True}],
            generation_time_sec=10.5,
            retry_count=0,
        )
        assert "answer_accuracy_rate" in metrics
        assert "dedup_score" in metrics
        assert "coverage_score" in metrics
        assert metrics["answer_accuracy_rate"] == 1.0

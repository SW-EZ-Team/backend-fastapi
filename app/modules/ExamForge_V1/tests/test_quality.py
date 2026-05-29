"""품질 모듈 테스트."""
from __future__ import annotations

from app.modules.ExamForge_V1.quality.deduplicator import check_duplicates
from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
from app.modules.ExamForge_V1.quality.difficulty_scorer import score_bloom_distribution
from app.modules.ExamForge_V1.quality.coverage_analyzer import analyze_coverage
from app.modules.ExamForge_V1.quality.metrics import compute_quality_metrics


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

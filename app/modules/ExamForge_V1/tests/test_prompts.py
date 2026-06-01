"""프롬프트 모듈 테스트."""
from __future__ import annotations

from app.modules.ExamForge_V1.prompts.question_gen import get_system_prompt
from app.modules.ExamForge_V1.prompts.distractor_gen import get_distractor_system
from app.modules.ExamForge_V1.prompts.answer_gen import get_answer_system
from app.modules.ExamForge_V1.prompts.verification import build_verification_prompt
from app.modules.ExamForge_V1.prompts.difficulty_calibration import build_calibration_prompt


class TestSystemPrompts:
    """시스템 프롬프트 로케일 분기 테스트."""

    def test_korean_question_gen(self) -> None:
        """한국어 프롬프트가 반환된다."""
        prompt = get_system_prompt("ko")
        assert "교육 평가 전문가" in prompt

    def test_english_question_gen(self) -> None:
        """영문 프롬프트가 반환된다."""
        prompt = get_system_prompt("en")
        assert "educational assessment" in prompt

    def test_korean_distractor(self) -> None:
        """한국어 오답 프롬프트."""
        prompt = get_distractor_system("ko")
        assert "오개념" in prompt

    def test_korean_distractor_same_subject_rule(self) -> None:
        """오답을 '같은 주제 영역의 그럴듯한 오개념'으로 만들라는 규칙이 포함된다(갭1)."""
        prompt = get_distractor_system("ko")
        assert "동일한 주제 영역" in prompt
        # 과목 밖 보기 금지 규칙과 좋은/나쁜 오답 대조 예시가 포함돼야 한다
        assert "과목 밖" in prompt
        assert "나쁜 오답" in prompt and "좋은 오답" in prompt

    def test_english_distractor(self) -> None:
        """영문 오답 프롬프트."""
        prompt = get_distractor_system("en")
        assert "Misconception" in prompt
        assert "same subject domain" in prompt

    def test_korean_answer(self) -> None:
        """한국어 정답 프롬프트."""
        prompt = get_answer_system("ko")
        assert "Chain-of-Thought" in prompt

    def test_korean_answer_per_distractor_label_rule(self) -> None:
        """오답마다 왜 틀렸는지 + 오개념 라벨 규칙이 포함된다(갭1-E6)."""
        prompt = get_answer_system("ko")
        assert "오답 보기마다" in prompt or "오개념 라벨" in prompt
        assert "괄호로" in prompt

    def test_korean_distractor_balance_rule(self) -> None:
        """보기 균형(정답 단서 제거) 규칙이 포함된다(갭2-E6)."""
        prompt = get_distractor_system("ko")
        assert "보기 균형" in prompt or "정답 단서" in prompt

    def test_english_distractor_balance_rule(self) -> None:
        """영문 오답 프롬프트에도 균형 규칙이 포함된다(갭2-E6)."""
        prompt = get_distractor_system("en")
        assert "Balance" in prompt


class TestPromptBuilders:
    """프롬프트 빌더 함수 테스트."""

    def test_verification_prompt(self) -> None:
        """검증 프롬프트가 올바르게 구성된다."""
        prompt = build_verification_prompt(
            question_json='{"stem": "테스트"}',
            source_excerpt="원본 자료 내용",
        )
        assert "테스트" in prompt
        assert "원본 자료" in prompt

    def test_calibration_prompt(self) -> None:
        """보정 프롬프트가 올바르게 구성된다."""
        prompt = build_calibration_prompt('[{"question_id": "q1"}]')
        assert "q1" in prompt
        assert "블룸" in prompt

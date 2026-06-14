"""프롬프트 모듈 테스트."""
from __future__ import annotations

from app.modules.ExamForge_V1.prompts.question_gen import get_system_prompt
from app.modules.ExamForge_V1.prompts.distractor_gen import get_distractor_system
from app.modules.ExamForge_V1.prompts.answer_gen import get_answer_system
from app.modules.ExamForge_V1.prompts.verification import (
    VERIFICATION_SYSTEM,
    build_verification_prompt,
)
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

    def test_korean_answer_concise_high_signal_rule(self) -> None:
        """해설이 간결·고신호 지침과 길이채우기 금지·전제 재진술 금지를 담는다(통찰형 개선)."""
        prompt = get_answer_system("ko")
        # 길이 채우기 금지 메타 지침
        assert "글자수 채우기 금지" in prompt
        # 전제(보기·지문) 재진술 금지 → 원리/메커니즘 설명 요구
        assert "재진술" in prompt
        assert "메커니즘" in prompt or "원리" in prompt
        # 학습 자료 밖 일반 상식 정당화 금지
        assert "일반 상식 정당화 금지" in prompt
        # takeaway(핵심 요약 한 줄) 요소 유지
        assert "takeaway" in prompt
        # 모든 오답을 장황히 나열하지 않고 가장 함정인 오답만 짚는다
        assert "가장 함정인 오답" in prompt
        # 과거의 장황한 길이 목표(400~800자)는 더 이상 강제하지 않는다
        assert "400~800" not in prompt

    def test_english_answer_concise_high_signal_rule(self) -> None:
        """영문 정답 프롬프트도 간결화·메타 금지 규칙이 ko와 일관되게 포함된다."""
        prompt = get_answer_system("en")
        assert "Chain-of-Thought" in prompt
        assert "Do not pad for length" in prompt
        assert "No restatement" in prompt
        assert "Takeaway" in prompt or "takeaway" in prompt
        # 모든 오답 나열 대신 가장 함정인 1~2개만
        assert "most tempting distractors" in prompt

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


class TestDistractorValidityPrompts:
    """오답 타당성 삼중 검증 규칙이 프롬프트에 포함되는지 확인한다."""

    def test_ko_distractor_system_contains_triple_validity_rule(self) -> None:
        """한국어 오답 프롬프트에 금지 A/B/C 삼중 조건이 명시된다."""
        prompt = get_distractor_system("ko")
        # 독립 참(사실) 오답 금지
        assert "금지 A" in prompt or "독립적으로 참" in prompt
        # 정답과 동치인 오답 금지
        assert "금지 B" in prompt or "논리적으로 동치" in prompt
        # 동시에 옳을 수 있는 오답 금지
        assert "금지 C" in prompt or "동시에 옳을 수" in prompt

    def test_en_distractor_system_contains_triple_validity_rule(self) -> None:
        """영문 오답 프롬프트에도 동치·참 오답 금지 규칙이 포함된다."""
        prompt = get_distractor_system("en")
        assert "Forbidden A" in prompt or "independently true" in prompt
        assert "Forbidden B" in prompt or "logically equivalent" in prompt
        assert "Forbidden C" in prompt or "simultaneously" in prompt

    def test_ko_distractor_system_shows_bad_example_of_true_distractor(self) -> None:
        """참인 오답의 구체적 예시(스택 바텀)가 포함된다."""
        prompt = get_distractor_system("ko")
        # 스택 바텀 오답 예시가 명시적으로 나쁜 오답으로 표시되어야 한다
        assert "가장 먼저 삽입된 원소가 가장 나중에 삭제" in prompt or "스택 바텀" in prompt

    def test_verification_system_contains_distractor_validity_criteria(self) -> None:
        """VERIFICATION_SYSTEM에 오답 타당성 검사(기준 7)가 포함된다."""
        assert "오답 타당성 검사" in VERIFICATION_SYSTEM
        # 세 조건이 모두 포함된다
        assert "조건 A" in VERIFICATION_SYSTEM
        assert "조건 B" in VERIFICATION_SYSTEM
        assert "조건 C" in VERIFICATION_SYSTEM
        # fix_instructions 생성 지시가 포함된다
        assert "fix_instructions" in VERIFICATION_SYSTEM or "교체하라" in VERIFICATION_SYSTEM

    def test_verification_prompt_includes_distractor_validity_section(self) -> None:
        """build_verification_prompt 결과에도 오답 타당성 점검 섹션이 포함된다."""
        prompt = build_verification_prompt(
            question_json='{"stem": "테스트", "options": []}',
            source_excerpt="스택은 LIFO 자료구조이다.",
        )
        assert "오답 타당성" in prompt or "조건 A" in prompt
        assert "독립적으로 참" in prompt or "independently true" in prompt

    def test_verification_system_has_stack_lifo_example(self) -> None:
        """검증 시스템 프롬프트에 스택/LIFO 동치 오답 구체 예시가 있다."""
        assert "스택" in VERIFICATION_SYSTEM and "LIFO" in VERIFICATION_SYSTEM
        # 실제 결함 케이스 예시가 있어야 한다
        assert "동치" in VERIFICATION_SYSTEM or "passed=false" in VERIFICATION_SYSTEM


class TestVerifyAnswersDistractorValidity:
    """verify_answers_node가 동치/참 오답을 repair 대상으로 보내는지 검증한다."""

    @staticmethod
    def _make_mcq_with_true_distractor() -> dict:
        """정답과 동치인 오답을 포함한 MCQ 문항 픽스처."""
        return {
            "question_id": "q_distractortest",
            "draft_id": "d_distractortest",
            "template_id": "ko_multiple_choice_4",
            "topic": "자료구조",
            "difficulty": 3,
            "bloom_level": "이해",
            "stem": "스택(Stack)의 삽입·삭제 동작 원리로 옳은 것은?",
            "options": [
                {
                    "label": "1",
                    "text": "마지막에 삽입된 원소가 가장 먼저 삭제된다 (LIFO)",
                    "is_correct": True,
                },
                {
                    "label": "2",
                    "text": "가장 먼저 삽입된 원소가 가장 나중에 삭제되는 선형 자료구조",
                    "is_correct": False,
                },
                {
                    "label": "3",
                    "text": "큐(Queue)와 동일한 FIFO 방식으로 동작한다",
                    "is_correct": False,
                },
                {
                    "label": "4",
                    "text": "양쪽 끝에서 삽입과 삭제가 모두 가능한 이중 큐(Deque)이다",
                    "is_correct": False,
                },
            ],
            "correct_answer": "1",
            "explanation": "스택은 LIFO(Last In First Out) 구조로, 마지막에 삽입된 원소가 먼저 제거된다.",
            "source_reference": "스택은 후입선출(LIFO) 자료구조이다.",
        }

    @staticmethod
    def _make_verification_fail_response_for_distractor() -> str:
        """오답 타당성 결함을 감지한 검증기 응답 JSON."""
        import json
        return json.dumps({
            "passed": False,
            "issues": [
                "보기 2: 조건 A 위반 — '가장 먼저 삽입된 원소가 가장 나중에 삭제되는 선형 자료구조'는"
                " 스택 바텀 원소 특성과 동일하므로 실제로 참인 진술"
            ],
            "fix_instructions": "보기 2를 '먼저 삽입된 원소가 먼저 삭제되는 FIFO 구조(큐)'로 교체하라",
            "confidence": 0.92,
        }, ensure_ascii=False)

    import pytest
    from unittest.mock import patch

    @pytest.mark.asyncio
    async def test_verify_node_marks_true_distractor_as_genuine_fail(self) -> None:
        """동치/참 오답을 포함한 문항이 genuine fail로 표시된다."""
        import pytest
        from unittest.mock import patch
        from app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node import verify_answers_node
        from app.modules.ExamForge_V1.pipeline.state import ExamForgeState

        question = self._make_mcq_with_true_distractor()
        fail_response = self._make_verification_fail_response_for_distractor()

        class _FailConnector:
            async def generate(self, req: object) -> object:
                class _R:
                    text = fail_response
                return _R()

        state: ExamForgeState = {
            "answered_questions": [question],
            "source_text": "스택은 후입선출(LIFO) 자료구조이다. 마지막 삽입 원소가 먼저 제거된다.",
        }

        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.get_connector",
            return_value=_FailConnector(),
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.active_verifier_model",
            return_value="stub",
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.verification_concurrency",
            return_value=4,
        ):
            result = await verify_answers_node(state)

        # 오답 타당성 결함은 genuine fail로 검출되어야 한다
        # verify_answers_node는 question_id를 기준으로 failures 목록을 만든다
        assert result["verification_failures"] == ["q_distractortest"]
        verified_q = result["verified_questions"][0]
        assert verified_q["_verification"]["passed"] is False
        assert verified_q["_verification"]["parse_failed"] is False
        # issues에 오답 결함 정보가 포함된다
        assert any("보기 2" in issue for issue in verified_q["_verification"]["issues"])

    @pytest.mark.asyncio
    async def test_verify_node_passes_clean_distractors(self) -> None:
        """명확히 틀린 오답만 있는 문항은 genuine fail 없이 통과한다."""
        import pytest
        from unittest.mock import patch
        import json
        from app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node import verify_answers_node
        from app.modules.ExamForge_V1.pipeline.state import ExamForgeState

        question = {
            "question_id": "q_clean",
            "draft_id": "d_clean",
            "template_id": "ko_multiple_choice_4",
            "topic": "자료구조",
            "difficulty": 3,
            "bloom_level": "이해",
            "stem": "스택(Stack)의 삽입·삭제 동작 원리로 옳은 것은?",
            "options": [
                {"label": "1", "text": "LIFO — 마지막 삽입이 가장 먼저 삭제", "is_correct": True},
                {"label": "2", "text": "FIFO — 먼저 삽입된 것이 먼저 삭제(큐)", "is_correct": False},
                {"label": "3", "text": "양방향 삽입·삭제 가능한 덱(Deque)", "is_correct": False},
                {"label": "4", "text": "우선순위 기준으로 삭제되는 힙(Heap)", "is_correct": False},
            ],
            "correct_answer": "1",
            "explanation": "스택은 LIFO 구조이다.",
            "source_reference": "스택은 LIFO 자료구조이다.",
        }
        pass_response = json.dumps(
            {"passed": True, "issues": [], "fix_instructions": "", "confidence": 0.97},
            ensure_ascii=False,
        )

        class _PassConnector:
            async def generate(self, req: object) -> object:
                class _R:
                    text = pass_response
                return _R()

        state: ExamForgeState = {
            "answered_questions": [question],
            "source_text": "스택은 LIFO 자료구조이다.",
        }

        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.get_connector",
            return_value=_PassConnector(),
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.active_verifier_model",
            return_value="stub",
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.verification_concurrency",
            return_value=4,
        ):
            result = await verify_answers_node(state)

        assert result["verification_failures"] == []
        assert result["verified_questions"][0]["_verification"]["passed"] is True

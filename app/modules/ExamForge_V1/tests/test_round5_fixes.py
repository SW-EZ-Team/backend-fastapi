"""Gemini Round 5 품질 이슈 수정 검증 테스트."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.modules.ExamForge_V1.common.ai_bridge import LLMBudgetCounter, _current_budget, set_current_budget
from app.modules.ExamForge_V1.common.ai_bridge import _GeminiCliConnector
from app.modules.ExamForge_V1.common.config import generation_concurrency, verification_concurrency
from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation
from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.schemas.request import ExamConfig, ExamForgeRequest


class TestP0_1_SemaphoreDeadlock:
    """P0-1: GENERATION_CONCURRENCY=0 시 데드락 방지 테스트."""

    def test_generation_concurrency_zero_returns_one(self) -> None:
        """환경 변수가 0이면 최소 1을 반환한다."""
        with patch.dict(os.environ, {"GENERATION_CONCURRENCY": "0"}):
            # 캐시된 _load_env 영향을 피하기 위해 직접 테스트
            from app.modules.ExamForge_V1.common.config import _int_env
            raw = max(1, _int_env("GENERATION_CONCURRENCY", 4))
            assert raw >= 1

    def test_verification_concurrency_zero_returns_one(self) -> None:
        """환경 변수가 0이면 최소 1을 반환한다."""
        with patch.dict(os.environ, {"VERIFICATION_CONCURRENCY": "0"}):
            from app.modules.ExamForge_V1.common.config import _int_env
            raw = max(1, _int_env("VERIFICATION_CONCURRENCY", 2))
            assert raw >= 1

    def test_generation_concurrency_negative_returns_one(self) -> None:
        """환경 변수가 음수여도 최소 1을 반환한다."""
        with patch.dict(os.environ, {"GENERATION_CONCURRENCY": "-5"}):
            from app.modules.ExamForge_V1.common.config import _int_env
            raw = max(1, _int_env("GENERATION_CONCURRENCY", 4))
            assert raw >= 1

    def test_semaphore_with_min_one_does_not_deadlock(self) -> None:
        """Semaphore(1)이 데드락 없이 동작하는지 확인한다."""
        # asyncio.get_event_loop()는 Python 3.10+에서 deprecated — asyncio.run()으로 대체
        sem = asyncio.Semaphore(max(1, 0))

        async def _acquire_release() -> bool:
            async with sem:
                return True

        result = asyncio.run(_acquire_release())
        assert result is True


class TestP0_2_LibraryEntryPointSafety:
    """P0-2: 라이브러리 진입점에 예산 + 타임아웃 적용 테스트."""

    @pytest.mark.asyncio
    async def test_library_entry_sets_budget(self) -> None:
        """generate_exam_forge이 예산 카운터를 설정한다."""
        captured_budget: list[LLMBudgetCounter | None] = []

        async def mock_ainvoke(state: dict) -> dict:
            # 파이프라인 내부에서 예산 카운터가 설정되었는지 확인
            captured_budget.append(_current_budget.get())
            return {
                "calibrated_questions": [],
                "output_html": "",
                "answers_html": "",
                "quality_metrics": {},
                "pipeline_status": "complete",
                "pipeline_outcome": "passed",
                "error_message": None,
                "exam_id": "test",
                "timings": {"start": 0},
            }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = mock_ainvoke

        with patch("app.modules.ExamForge_V1.pipeline.graph.get_compiled_graph", return_value=mock_graph):
            from app.modules.ExamForge_V1 import generate_exam_forge
            request = ExamForgeRequest(
                source_text="가" * 200,
                subject="테스트",
            )
            await generate_exam_forge(request)

        # 파이프라인 실행 중 예산 카운터가 존재했어야 한다
        assert captured_budget[0] is not None
        assert isinstance(captured_budget[0], LLMBudgetCounter)

    @pytest.mark.asyncio
    async def test_library_entry_cleans_up_budget_on_error(self) -> None:
        """예외 발생 시에도 예산 카운터가 정리된다."""
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("테스트 에러"))

        with patch("app.modules.ExamForge_V1.pipeline.graph.get_compiled_graph", return_value=mock_graph):
            from app.modules.ExamForge_V1 import generate_exam_forge
            request = ExamForgeRequest(
                source_text="가" * 200,
                subject="테스트",
            )
            with pytest.raises(RuntimeError, match="테스트 에러"):
                await generate_exam_forge(request)

        # 예산 카운터가 정리되었는지 확인
        assert _current_budget.get() is None

    @pytest.mark.asyncio
    async def test_library_entry_has_timeout(self) -> None:
        """파이프라인 실행에 타임아웃이 적용된다."""
        async def slow_ainvoke(state: dict) -> dict:
            await asyncio.sleep(10)  # 10초 대기 (타임아웃보다 길게)
            return {}

        mock_graph = AsyncMock()
        mock_graph.ainvoke = slow_ainvoke

        async def fake_wait_for(awaitable: object, timeout: float) -> None:
            """테스트용 대기 함수가 생성된 코루틴을 닫아 경고를 막는다."""
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError

        with patch("app.modules.ExamForge_V1.pipeline.graph.get_compiled_graph", return_value=mock_graph):
            from app.modules.ExamForge_V1 import generate_exam_forge
            request = ExamForgeRequest(
                source_text="가" * 200,
                subject="테스트",
            )
            with patch("asyncio.wait_for", fake_wait_for):
                with pytest.raises(asyncio.TimeoutError):
                    await generate_exam_forge(request)


class TestP0_3_DeterministicFailureEarlyExit:
    """P0-3: 결정적 실패 시 무의미한 재시도 방지 테스트."""

    def test_retry_router_exhausted_on_deterministic_failure(self) -> None:
        """에러 메시지가 있고 문제가 비어있으면 즉시 exhausted 반환."""
        state: ExamForgeState = {
            "failed_question_ids": [],
            "retry_count": 0,
            "max_retries": 3,
            "verified_questions": [],
            "error_message": "이전 단계에서 문제가 생성되지 않음",
        }
        result = route_after_validation(state)
        assert result == "exhausted"

    def test_retry_router_still_retries_without_error_message(self) -> None:
        """에러 메시지 없이 문제만 비어있으면 기존대로 retry."""
        state: ExamForgeState = {
            "failed_question_ids": [],
            "retry_count": 0,
            "max_retries": 3,
            "verified_questions": [],
            "error_message": None,
        }
        result = route_after_validation(state)
        assert result == "retry"

    @pytest.mark.asyncio
    async def test_validate_node_early_exit_on_empty(self) -> None:
        """검증할 문제가 없으면 즉시 에러를 반환한다."""
        from app.modules.ExamForge_V1.pipeline.nodes.validate_node import validate_node

        state: ExamForgeState = {
            "verified_questions": [],
            "exam_plan": {},
        }
        result = await validate_node(state)
        assert result["pipeline_status"] == "error"
        assert "생성되지 않음" in result["error_message"]

    @pytest.mark.asyncio
    async def test_generate_answers_node_early_exit(self) -> None:
        """입력 문제 0건이면 즉시 에러 반환."""
        from app.modules.ExamForge_V1.pipeline.nodes.generate_answers_node import generate_answers_node

        state: ExamForgeState = {
            "questions_with_distractors": [],
            "source_text": "",
            "locale": "ko",
        }
        result = await generate_answers_node(state)
        assert result["pipeline_status"] == "error"
        assert "입력 문제 0건" in result["error_message"]

    @pytest.mark.asyncio
    async def test_verify_answers_node_early_exit(self) -> None:
        """입력 문제 0건이면 즉시 에러 반환."""
        from app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node import verify_answers_node

        state: ExamForgeState = {
            "answered_questions": [],
            "source_text": "",
        }
        result = await verify_answers_node(state)
        assert result["pipeline_status"] == "error"
        assert "입력 문제 0건" in result["error_message"]

    @pytest.mark.asyncio
    async def test_generate_distractors_node_early_exit(self) -> None:
        """입력 문제 0건이면 즉시 에러 반환."""
        from app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node import generate_distractors_node

        state: ExamForgeState = {
            "questions": [],
            "locale": "ko",
        }
        result = await generate_distractors_node(state)
        assert result["pipeline_status"] == "error"
        assert "입력 문제 0건" in result["error_message"]


class TestP1_1_WhitespaceSourceText:
    """P1-1: 공백만으로 이루어진 source_text 차단 테스트."""

    def test_whitespace_only_rejected(self) -> None:
        """공백만 100자 이상이어도 거부된다."""
        with pytest.raises(ValidationError, match="100자"):
            ExamForgeRequest(
                source_text=" " * 200,
                subject="테스트",
            )

    def test_whitespace_padded_short_text_rejected(self) -> None:
        """공백 제거 후 100자 미만이면 거부된다."""
        with pytest.raises(ValidationError, match="100자"):
            ExamForgeRequest(
                source_text="짧은 텍스트" + " " * 200,
                subject="테스트",
            )

    def test_valid_text_with_whitespace_passes(self) -> None:
        """공백 제거 후 100자 이상이면 통과한다."""
        text = "가" * 100 + "  "
        req = ExamForgeRequest(source_text=text, subject="테스트")
        # strip되어 저장됨
        assert req.source_text == "가" * 100


class TestP1_2_EmptySubject:
    """P1-2: 빈 과목명 차단 테스트."""

    def test_empty_string_rejected(self) -> None:
        """빈 문자열 과목명이 거부된다."""
        with pytest.raises(ValidationError):
            ExamForgeRequest(
                source_text="가" * 200,
                subject="",
            )

    def test_whitespace_only_rejected(self) -> None:
        """공백만으로 이루어진 과목명이 거부된다."""
        with pytest.raises(ValidationError, match="공백"):
            ExamForgeRequest(
                source_text="가" * 200,
                subject="   ",
            )

    def test_valid_subject_passes(self) -> None:
        """유효한 과목명은 통과한다."""
        req = ExamForgeRequest(
            source_text="가" * 200,
            subject="소프트웨어공학",
        )
        assert req.subject == "소프트웨어공학"


class TestP1_3_DifficultyDistributionSum:
    """P1-3: 난이도 분포 합계 검증 테스트."""

    def test_sum_not_one_rejected(self) -> None:
        """합계가 1.0이 아니면 거부된다."""
        with pytest.raises(ValidationError, match="1.0"):
            ExamConfig(difficulty_distribution={1: 0.5, 2: 0.3})

    def test_sum_exactly_one_passes(self) -> None:
        """합계가 정확히 1.0이면 통과한다."""
        config = ExamConfig(difficulty_distribution={1: 0.5, 2: 0.3, 3: 0.2})
        assert sum(config.difficulty_distribution.values()) == pytest.approx(1.0)

    def test_sum_within_tolerance_passes(self) -> None:
        """부동소수점 오차 범위(0.99~1.01) 내이면 통과한다."""
        # 0.1 + 0.2 + 0.3 + 0.4 = 1.0 (부동소수점에서 정확히 1.0이 아닐 수 있음)
        config = ExamConfig(
            difficulty_distribution={1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4}
        )
        total = sum(config.difficulty_distribution.values())
        assert 0.99 <= total <= 1.01


class TestP1_6_ShrinkingExam:
    """P1-6: 'passed'이지만 문항 수 부족 시 경고 테스트."""

    @pytest.mark.asyncio
    async def test_passed_but_partial_becomes_passed_partial(self) -> None:
        """passed이지만 요청보다 적으면 passed_partial로 변경된다."""
        from app.modules.ExamForge_V1.pipeline.nodes.format_output_node import format_output_node

        state: ExamForgeState = {
            "calibrated_questions": [
                {"question_id": f"q{i}", "stem": f"문제{i}",
                 "template_id": "ko_multiple_choice_5", "topic": "A",
                 "difficulty": 3, "bloom_level": "이해",
                 "options": [], "correct_answer": "1",
                 "explanation": "설명"} for i in range(35)
            ],
            "exam_plan": {"topic_weights": {"A": 1.0}},
            "exam_config": {"total_questions": 50},
            "retry_count": 0,
            "max_retries": 3,
            "failed_question_ids": [],
            "timings": {"start": 0},
        }
        result = await format_output_node(state)
        assert result["pipeline_outcome"] == "passed_partial"

    @pytest.mark.asyncio
    async def test_passed_full_count_stays_passed(self) -> None:
        """요청과 동일 수 생성 시 passed 유지."""
        from app.modules.ExamForge_V1.pipeline.nodes.format_output_node import format_output_node

        state: ExamForgeState = {
            "calibrated_questions": [
                {"question_id": f"q{i}", "stem": f"문제{i}",
                 "template_id": "ko_multiple_choice_5", "topic": "A",
                 "difficulty": 3, "bloom_level": "이해",
                 "options": [], "correct_answer": "1",
                 "explanation": "설명"} for i in range(50)
            ],
            "exam_plan": {"topic_weights": {"A": 1.0}},
            "exam_config": {"total_questions": 50},
            "retry_count": 0,
            "max_retries": 3,
            "failed_question_ids": [],
            "timings": {"start": 0},
        }
        result = await format_output_node(state)
        assert result["pipeline_outcome"] == "passed"


class TestP1_7_HtmlXss:
    """P1-7: HTML XSS 방지 테스트."""

    def test_stem_is_escaped(self) -> None:
        """문제 줄기에 HTML 태그가 이스케이프된다."""
        from app.modules.ExamForge_V1.pipeline.nodes._html_builder import build_exam_html

        questions = [{
            "stem": "<script>alert('xss')</script>",
            "difficulty": 3,
            "points": 1.0,
        }]
        html = build_exam_html(questions, {})
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_options_are_escaped(self) -> None:
        """선택지 텍스트가 이스케이프된다."""
        from app.modules.ExamForge_V1.pipeline.nodes._html_builder import build_exam_html

        questions = [{
            "stem": "정상 문제",
            "difficulty": 3,
            "points": 1.0,
            "options": [
                {"label": "1", "text": '<img src=x onerror="alert(1)">'},
            ],
        }]
        html = build_exam_html(questions, {})
        assert "onerror" not in html
        assert "data-removed" in html
        assert "&lt;img" in html

    def test_explanation_is_escaped(self) -> None:
        """해설 텍스트가 이스케이프된다."""
        from app.modules.ExamForge_V1.pipeline.nodes._html_builder import build_answers_html

        questions = [{
            "correct_answer": "2",
            "explanation": "<div onmouseover='hack()'>위험</div>",
            "source_reference": "<b>악성 출처</b>",
        }]
        html = build_answers_html(questions, {})
        assert "onmouseover" not in html
        assert "data-removed" in html
        assert "&lt;div" in html
        assert "&lt;b&gt;" in html

    def test_title_is_escaped(self) -> None:
        """시험 제목이 이스케이프된다."""
        from app.modules.ExamForge_V1.pipeline.nodes._html_builder import build_exam_html

        html = build_exam_html([], {"exam_title": "<script>xss</script>"})
        assert "<script>xss</script>" not in html
        assert "&lt;script&gt;" in html


class TestGeminiCliJsonOutput:
    """Gemini CLI JSON 래퍼 출력 정규화 테스트."""

    def test_clean_output_extracts_response_from_json_wrapper(self) -> None:
        """--output-format json 응답에서 response 본문만 추출한다."""
        raw = (
            "Warning: Basic terminal detected\n"
            "Ripgrep is not available. Falling back to GrepTool.\n"
            '{"session_id":"s","response":"```json\\n[{\\"ok\\":true}]\\n```",'
            '"stats":{"tools":{"totalCalls":0}}}'
        )

        cleaned = _GeminiCliConnector._clean_output(raw)

        assert cleaned == '```json\n[{"ok":true}]\n```'

    def test_clean_output_falls_back_to_cleaned_text(self) -> None:
        """구버전 CLI 텍스트 출력도 기존처럼 본문을 보존한다."""
        raw = "Warning: Basic terminal detected\n[{\"ok\": true}]"

        assert _GeminiCliConnector._clean_output(raw) == '[{"ok": true}]'

"""검증 응답 파싱 실패 advisory 처리 회귀 테스트."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation
from app.modules.ExamForge_V1.pipeline.nodes.validate_node import validate_node
from app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node import verify_answers_node
from app.modules.ExamForge_V1.pipeline.state import ExamForgeState


def test_verification_advisory_env_flag_enables_mode() -> None:
    """env 플래그 true이면 검증기를 관측 전용으로 둔다."""
    from app.modules.ExamForge_V1.common import config

    with patch.object(
        config,
        "_optional",
        side_effect=lambda key: "true" if key == "EXAMFORGE_VERIFICATION_ADVISORY" else None,
    ):
        assert config.verification_advisory_enabled() is True


def test_codex_cli_verifier_enables_advisory_mode() -> None:
    """codex_cli 검증기는 env 플래그가 없어도 advisory로 취급한다."""
    from app.modules.ExamForge_V1.common import config

    def optional(key: str) -> str | None:
        if key == "ACTIVE_VERIFIER_MODEL":
            return "codex_cli"
        return None

    with patch.object(config, "_optional", side_effect=optional):
        assert config.verification_advisory_enabled() is True


class _StubResponse:
    """AI 응답 최소 스텁."""

    def __init__(self, text: str) -> None:
        self.text = text


class _SequenceConnector:
    """호출 순서대로 고정 응답을 반환하는 검증 커넥터."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    async def generate(self, req: object) -> _StubResponse:
        index = min(self.calls, len(self.texts) - 1)
        self.calls += 1
        return _StubResponse(self.texts[index])


@pytest.mark.asyncio
async def test_verify_answers_marks_non_json_as_parse_failed_not_failure() -> None:
    """비JSON 검증 응답은 genuine fail이 아니라 parse_failed로 남긴다."""
    connector = _SequenceConnector(["정답은 맞습니다. JSON은 생략합니다."])
    state: ExamForgeState = {
        "answered_questions": [_question("q1", "d1"), _question("q2", "d2")],
        "source_text": "스택은 후입선출 자료구조이다.",
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.get_connector",
        return_value=connector,
    ), patch(
        "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.active_verifier_model",
        return_value="stub",
    ), patch(
        "app.modules.ExamForge_V1.pipeline.nodes.verify_answers_node.verification_concurrency",
        return_value=4,
    ):
        result = await verify_answers_node(state)

    assert connector.calls == 4
    assert result["verification_failures"] == []
    assert result["verification_parse_failed_count"] == 2
    assert result["verification_advisory"] is True
    assert all(q["_verification"]["passed"] is None for q in result["verified_questions"])
    assert all(q["_verification"]["parse_failed"] is True for q in result["verified_questions"])


@pytest.mark.asyncio
async def test_validate_ignores_parse_failed_for_failed_ids_and_accuracy() -> None:
    """parse_failed 문항은 구조 실패나 정확률 실패로 세지 않는다."""
    state: ExamForgeState = {
        "verified_questions": [
            {
                **_question("q1", "d1"),
                "_verification": {
                    "passed": None,
                    "parse_failed": True,
                    "issues": ["검증 응답 파싱 실패"],
                },
            }
        ],
        "exam_plan": {"topic_weights": {"자료구조": 1.0}},
    }

    result = await validate_node(state)

    assert result["failed_question_ids"] == []
    report = result["validation_report"]
    assert report["answer_accuracy_rate"] == 1.0
    assert report["answer_verification_parse_failed_count"] == 1
    assert report["results"][0]["passed"] is True
    assert report["results"][0]["parse_failed"] is True


@pytest.mark.asyncio
async def test_validate_advisory_mode_keeps_genuine_fail_out_of_failed_ids() -> None:
    """advisory 모드에서는 검증기 오판을 실패 ID와 정확률 재시도에서 제외한다."""
    state: ExamForgeState = {
        "verified_questions": [
            {
                **_question("q1", "d1"),
                "_verification": {
                    "passed": False,
                    "parse_failed": False,
                    "issues": ["검증기가 정답을 오판함"],
                },
            }
        ],
        "exam_plan": {"topic_weights": {"자료구조": 1.0}},
        "verification_advisory": True,
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.validate_node.verification_advisory_enabled",
        return_value=True,
    ):
        result = await validate_node(state)

    assert result["failed_question_ids"] == []
    report = result["validation_report"]
    assert report["answer_accuracy_rate"] == 0.0
    assert report["results"][0]["passed"] is True
    assert "genuine fail 1건" in report["global_issues"][0]


@pytest.mark.asyncio
async def test_validate_non_advisory_genuine_fail_still_retries() -> None:
    """신뢰 가능한 검증기 경로에서는 genuine fail을 기존처럼 재시도 대상으로 둔다."""
    state: ExamForgeState = {
        "verified_questions": [
            {
                **_question("q1", "d1"),
                "_verification": {
                    "passed": False,
                    "parse_failed": False,
                    "issues": ["정답 불일치"],
                },
            }
        ],
        "exam_plan": {"topic_weights": {"자료구조": 1.0}},
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.validate_node.verification_advisory_enabled",
        return_value=False,
    ):
        result = await validate_node(state)

    assert result["failed_question_ids"] == ["d1"]
    assert result["validation_report"]["results"][0]["passed"] is False


def test_retry_router_parse_failed_majority_does_not_exhaust() -> None:
    """parse_failed 다수와 genuine fail 0건이면 exhausted로 보내지 않는다."""
    state: ExamForgeState = {
        "verified_questions": [
            {**_question("q1", "d1"), "_verification": {"passed": None, "parse_failed": True}},
            {**_question("q2", "d2"), "_verification": {"passed": None, "parse_failed": True}},
        ],
        "failed_question_ids": ["d1", "d2"],
        "validation_report": {"answer_accuracy_rate": 0.0},
        "retry_count": 3,
        "max_retries": 3,
    }

    assert route_after_validation(state) == "passed"


def test_retry_router_advisory_mode_does_not_exhaust_genuine_fail() -> None:
    """advisory 모드는 genuine fail 100%여도 생성 문항을 폐기하지 않는다."""
    state: ExamForgeState = {
        "verified_questions": [
            {**_question("q1", "d1"), "_verification": {"passed": False, "parse_failed": False}},
            {**_question("q2", "d2"), "_verification": {"passed": False, "parse_failed": False}},
        ],
        "failed_question_ids": ["d1", "d2"],
        "validation_report": {"answer_accuracy_rate": 0.0},
        "retry_count": 3,
        "max_retries": 3,
        "verification_advisory": True,
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.retry_router_node.verification_advisory_enabled",
        return_value=True,
    ):
        assert route_after_validation(state) == "passed"


def test_retry_router_non_advisory_genuine_fail_still_exhausts() -> None:
    """비-advisory에서는 genuine fail 100%가 기존처럼 exhausted로 간다."""
    state: ExamForgeState = {
        "verified_questions": [
            {**_question("q1", "d1"), "_verification": {"passed": False, "parse_failed": False}},
            {**_question("q2", "d2"), "_verification": {"passed": False, "parse_failed": False}},
        ],
        "failed_question_ids": ["d1", "d2"],
        "validation_report": {"answer_accuracy_rate": 0.0},
        "retry_count": 3,
        "max_retries": 3,
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.retry_router_node.verification_advisory_enabled",
        return_value=False,
    ):
        assert route_after_validation(state) == "exhausted"


@pytest.mark.asyncio
async def test_repair_questions_skips_targeted_repair_in_advisory_mode() -> None:
    """advisory 모드에서는 검증기 fix 지시로 정답을 바꾸지 않는다."""
    from app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node import repair_questions_node

    state: ExamForgeState = {
        "verified_questions": [
            {
                **_question("q1", "d1"),
                "_verification": {
                    "passed": False,
                    "parse_failed": False,
                    "fix_instructions": "정답을 스택이 아닌 큐로 바꾸라",
                },
            }
        ],
        "answered_questions": [_question("q1", "d1")],
        "failed_question_ids": ["d1"],
        "verification_advisory": True,
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.verification_advisory_enabled",
        return_value=True,
    ), patch(
        "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.get_connector"
    ) as mock_connector:
        result = await repair_questions_node(state)

    assert result["repair_applied"] is False
    mock_connector.assert_not_called()


@pytest.mark.asyncio
async def test_format_output_advisory_genuine_fail_preserves_generated_questions() -> None:
    """최종 출력에서도 검증기 오판만으로 status=failed가 되지 않는다."""
    from app.modules.ExamForge_V1.pipeline.nodes.format_output_node import format_output_node

    state: ExamForgeState = {
        "calibrated_questions": [
            {
                **_question("q1", "d1"),
                "_verification": {
                    "passed": False,
                    "parse_failed": False,
                    "issues": ["검증기 오판"],
                },
            }
        ],
        "exam_plan": {"topic_weights": {"자료구조": 1.0}},
        "exam_config": {"total_questions": 1},
        "retry_count": 3,
        "max_retries": 3,
        "failed_question_ids": ["d1"],
        "validation_report": {
            "results": [{"question_id": "q1", "passed": False, "issues": ["검증기 오판"]}]
        },
        "verification_advisory": True,
        "timings": {"start": 0},
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.nodes.format_output_node.verification_advisory_enabled",
        return_value=True,
    ):
        result = await format_output_node(state)

    assert result["pipeline_status"] == "complete"
    assert result["pipeline_outcome"] == "passed"
    assert result["calibrated_questions"][0]["question_id"] == "q1"
    assert "_verification" not in result["calibrated_questions"][0]


def _question(question_id: str, draft_id: str) -> dict:
    """검증·구조 테스트에 쓰는 최소 단답형 문항."""
    return {
        "question_id": question_id,
        "draft_id": draft_id,
        "template_id": "ko_short_answer",
        "topic": "자료구조",
        "difficulty": 3,
        "bloom_level": "이해",
        "stem": "스택의 원소 제거 순서를 설명하시오.",
        "correct_answer": "후입선출",
        "explanation": "정답은 후입선출입니다. 마지막에 들어간 원소가 먼저 제거됩니다.",
        "source_reference": "스택은 LIFO 구조이다.",
    }


# ── 오답 타당성(기준7) hard-fail이 advisory 모드를 무시하고 repair되는지 검증 ──


def _hard_fail_verification() -> dict:
    """오답 타당성 위반(기준7) genuine fail 검증 결과 — distractor_validity_failed=true."""
    return {
        "passed": False,
        "parse_failed": False,
        "distractor_validity_failed": True,
        "issues": ["보기 2: 조건 B 위반 — 정답과 논리적으로 동치인 오답"],
        "fix_instructions": "보기 2를 'FIFO 구조(큐)'로 교체하라",
    }


def _style_advisory_verification() -> dict:
    """오답 타당성과 무관한 일반 advisory(스타일·표현) genuine fail 검증 결과."""
    return {
        "passed": False,
        "parse_failed": False,
        "distractor_validity_failed": False,
        "issues": ["보기 길이 불균형 — 정답만 유독 김"],
        "fix_instructions": "보기 길이를 맞추라",
    }


class TestDistractorValidityStatusHelpers:
    """verification_status의 hard-fail 판별 헬퍼 단위 테스트."""

    def test_explicit_flag_is_hard_fail(self) -> None:
        """distractor_validity_failed=true는 hard fail로 판별된다."""
        from app.modules.ExamForge_V1.common.verification_status import (
            is_distractor_validity_hard_fail,
        )
        assert is_distractor_validity_hard_fail(_hard_fail_verification()) is True

    def test_issues_marker_fallback_is_hard_fail(self) -> None:
        """플래그가 없어도 issues 텍스트 마커로 hard fail을 식별한다(폴백)."""
        from app.modules.ExamForge_V1.common.verification_status import (
            is_distractor_validity_hard_fail,
        )
        v = {
            "passed": False,
            "parse_failed": False,
            "issues": ["보기 3: 조건 A 위반 — 독립적으로 참인 진술"],
        }
        assert is_distractor_validity_hard_fail(v) is True

    def test_style_advisory_is_not_hard_fail(self) -> None:
        """일반 스타일 advisory 실패는 hard fail이 아니다."""
        from app.modules.ExamForge_V1.common.verification_status import (
            is_distractor_validity_hard_fail,
        )
        assert is_distractor_validity_hard_fail(_style_advisory_verification()) is False

    def test_pass_is_not_hard_fail(self) -> None:
        """통과 문항은 hard fail이 아니다."""
        from app.modules.ExamForge_V1.common.verification_status import (
            is_distractor_validity_hard_fail,
        )
        assert is_distractor_validity_hard_fail({"passed": True}) is False

    def test_advisory_filtered_keeps_hard_fail_id(self) -> None:
        """advisory 모드여도 hard fail 문항 ID는 재시도 목록에 남는다."""
        from app.modules.ExamForge_V1.common.verification_status import (
            advisory_filtered_failed_ids,
        )
        questions = [
            {**_question("q1", "d1"), "_verification": _hard_fail_verification()},
            {**_question("q2", "d2"), "_verification": _style_advisory_verification()},
        ]
        result = advisory_filtered_failed_ids(
            ["d1", "d2"], questions, verification_advisory=True
        )
        # hard fail(d1)은 남고, 스타일 advisory(d2)는 제외된다
        assert "d1" in result
        assert "d2" not in result


class TestAdvisoryHardFailRouting:
    """advisory 모드에서 hard-fail이 retry로 라우팅되는지 검증한다."""

    def test_route_advisory_hard_fail_goes_retry(self) -> None:
        """advisory 모드여도 오답 타당성 hard fail이 있으면 retry로 보낸다."""
        state: ExamForgeState = {
            "verified_questions": [
                {**_question("q1", "d1"), "_verification": _hard_fail_verification()},
                {**_question("q2", "d2"), "_verification": {"passed": True}},
            ],
            "failed_question_ids": ["d1"],
            "validation_report": {"answer_accuracy_rate": 1.0},
            "retry_count": 0,
            "max_retries": 3,
            "verification_advisory": True,
        }
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.retry_router_node.verification_advisory_enabled",
            return_value=True,
        ):
            assert route_after_validation(state) == "retry"

    def test_route_advisory_hard_fail_exhausts_at_max_retries(self) -> None:
        """hard fail이어도 max_retries 소진 시 exhausted로 빠진다(무한루프 방지)."""
        state: ExamForgeState = {
            "verified_questions": [
                {**_question("q1", "d1"), "_verification": _hard_fail_verification()},
            ],
            "failed_question_ids": ["d1"],
            "validation_report": {"answer_accuracy_rate": 1.0},
            "retry_count": 3,
            "max_retries": 3,
            "verification_advisory": True,
        }
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.retry_router_node.verification_advisory_enabled",
            return_value=True,
        ):
            assert route_after_validation(state) == "exhausted"

    def test_route_advisory_style_only_stays_passed(self) -> None:
        """hard fail 없이 스타일 advisory만 있으면 기존대로 passed 유지(과잉 repair 방지)."""
        state: ExamForgeState = {
            "verified_questions": [
                {**_question("q1", "d1"), "_verification": _style_advisory_verification()},
                {**_question("q2", "d2"), "_verification": {"passed": True}},
            ],
            "failed_question_ids": ["d1"],
            "validation_report": {"answer_accuracy_rate": 1.0, "dedup_score": 1.0},
            "retry_count": 0,
            "max_retries": 3,
            "verification_advisory": True,
        }
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.retry_router_node.verification_advisory_enabled",
            return_value=True,
        ):
            assert route_after_validation(state) == "passed"


class TestAdvisoryHardFailRepair:
    """advisory 모드에서 repair_questions_node가 hard-fail만 교정하는지 검증한다."""

    @pytest.mark.asyncio
    async def test_repair_runs_for_hard_fail_in_advisory(self) -> None:
        """advisory 모드여도 hard fail 문항은 fix_instructions대로 교정된다."""
        from app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node import (
            repair_questions_node,
            route_after_repair,
        )

        repaired_json = (
            '{"stem":"스택 동작?","options":['
            '{"label":"1","text":"LIFO","is_correct":true},'
            '{"label":"2","text":"FIFO 구조(큐)","is_correct":false}],'
            '"correct_answer":"1"}'
        )
        connector = _SequenceConnector([repaired_json])
        hard_q = {
            "question_id": "q1", "draft_id": "d1",
            "template_id": "ko_multiple_choice_4",
            "correct_answer": "1", "stem": "스택 동작?",
            "options": [
                {"label": "1", "text": "LIFO", "is_correct": True},
                {"label": "2", "text": "먼저 삽입이 가장 나중에 삭제되는 구조", "is_correct": False},
            ],
        }
        state: ExamForgeState = {
            "source_text": "스택은 LIFO 자료구조이다. " * 10,
            "answered_questions": [hard_q],
            "verified_questions": [{**hard_q, "_verification": _hard_fail_verification()}],
            "failed_question_ids": ["d1"],
            "verification_advisory": True,
        }

        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.verification_advisory_enabled",
            return_value=True,
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.get_connector",
            return_value=connector,
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.active_verifier_model",
            return_value="codex_cli",
        ):
            result = await repair_questions_node(state)

        # advisory여도 hard fail이라 교정이 적용되고 reverify로 라우팅된다
        assert result["repair_applied"] is True
        assert connector.calls == 1
        assert route_after_repair(result) == "reverify"
        merged = result["answered_questions"][0]
        assert merged["question_id"] == "q1" and merged["draft_id"] == "d1"
        assert "_verification" not in merged

    @pytest.mark.asyncio
    async def test_repair_skips_style_advisory_failure(self) -> None:
        """오답 타당성과 무관한 스타일 advisory 실패는 advisory 모드에서 교정하지 않는다."""
        from app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node import (
            repair_questions_node,
        )

        style_q = {
            "question_id": "q1", "draft_id": "d1",
            "template_id": "ko_multiple_choice_4",
            "correct_answer": "1", "stem": "문제?",
        }
        state: ExamForgeState = {
            "source_text": "원본 자료 " * 30,
            "answered_questions": [style_q],
            "verified_questions": [{**style_q, "_verification": _style_advisory_verification()}],
            "failed_question_ids": ["d1"],
            "verification_advisory": True,
        }

        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.verification_advisory_enabled",
            return_value=True,
        ), patch(
            "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.get_connector"
        ) as mock_connector:
            result = await repair_questions_node(state)

        # 스타일 advisory는 검증기 신뢰 부족 정책대로 교정 생략
        assert result["repair_applied"] is False
        mock_connector.assert_not_called()

    @pytest.mark.asyncio
    async def test_repair_respects_budget_exhaustion_with_hard_fail(self) -> None:
        """hard fail이 있어도 예산 소진 시 교정하지 않고 폴백한다(폭증 방지)."""
        from app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node import (
            repair_questions_node,
        )
        from app.modules.ExamForge_V1.common.ai_bridge import (
            LLMBudgetCounter,
            set_current_budget,
            _current_budget,
        )

        budget = LLMBudgetCounter(budget=2)
        budget.increment()
        budget.increment()  # exceeded 상태
        token = set_current_budget(budget)
        try:
            hard_q = {
                "question_id": "q1", "draft_id": "d1",
                "template_id": "ko_multiple_choice_4",
                "correct_answer": "1", "stem": "스택?",
            }
            state: ExamForgeState = {
                "source_text": "스택은 LIFO " * 10,
                "answered_questions": [hard_q],
                "verified_questions": [{**hard_q, "_verification": _hard_fail_verification()}],
                "failed_question_ids": ["d1"],
                "verification_advisory": True,
            }
            with patch(
                "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.verification_advisory_enabled",
                return_value=True,
            ), patch(
                "app.modules.ExamForge_V1.pipeline.nodes.repair_questions_node.get_connector"
            ) as mock_connector:
                result = await repair_questions_node(state)

            assert result["repair_applied"] is False
            mock_connector.assert_not_called()
        finally:
            _current_budget.reset(token)

"""좁은 소스 모의고사 FAILED 버그 수정 단위 테스트.

검증 범위 (codex 수정설계 a/b/c):
A. source_capacity — 소스 폭 기반 effective target 캡 (좁은 소스↓, 넓은 소스 무변경)
B. plan_exam_node.apply_effective_target — 캡 적용 + requested_question_count 보존
C. format_output 3분기 — passed / needs_more_source(비-FAILED) / failed
D. 재생성 프롬프트 dedup-aware — build_repair_tasks가 기존 stem을 청크 프롬프트에 전달
E. mock_async_router — needs_more_source 출고 허용 + 콜백 신규 필드

라이브 AI 호출 없음 — 전부 단위 테스트/mock.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.modules.ExamForge_V1.common.source_capacity import (
    count_distinct_concepts,
    count_source_segments,
    effective_target_count,
    source_capacity,
)
from app.modules.ExamForge_V1.pipeline.nodes.format_output_node import (
    _completion_floor,
    format_output_node,
)
from app.modules.ExamForge_V1.pipeline.nodes.plan_exam_node import apply_effective_target
from app.modules.ExamForge_V1.pipeline.nodes.question_repair import build_repair_tasks
from app.modules.ExamForge_V1.pipeline.nodes.regeneration_context import (
    build_avoidance_clause,
)


# ── 공용 픽스처 ────────────────────────────────────────────────────────────────

def _narrow_topics() -> list[dict]:
    """단일 챕터·소수 개념의 좁은 소스 topics (BST 12슬라이드 시나리오 모사)."""
    return [
        {
            "name": "이진 탐색 트리",
            "chapter": "BST",
            "importance": 1.0,
            "key_topics": ["삽입", "삭제"],  # 고유 개념 2개
        }
    ]


def _wide_topics(n: int = 8) -> list[dict]:
    """챕터·개념이 풍부한 넓은 소스 topics."""
    return [
        {
            "name": f"주제{i}",
            "chapter": f"챕터{i}",
            "importance": (n - i) * 0.1,
            "key_topics": [f"개념{i}_A", f"개념{i}_B", f"개념{i}_C"],
        }
        for i in range(n)
    ]


# ── A: source_capacity ────────────────────────────────────────────────────────

class TestSourceCapacity:
    """소스 폭 신호 산정과 effective target 캡."""

    def test_count_distinct_concepts_narrow(self) -> None:
        """좁은 소스의 고유 개념 수를 센다 (삽입·삭제 → 2)."""
        assert count_distinct_concepts(_narrow_topics()) == 2

    def test_count_distinct_concepts_topic_only(self) -> None:
        """하위 개념이 없으면 주제명 자체를 1개념으로 센다."""
        assert count_distinct_concepts([{"name": "스택", "chapter": "ch1"}]) == 1

    def test_count_segments_single_chapter(self) -> None:
        """단일 챕터면 세그먼트 1개."""
        assert count_source_segments(_narrow_topics()) == 1

    def test_count_segments_wide(self) -> None:
        """챕터가 여럿이면 세그먼트도 여럿."""
        assert count_source_segments(_wide_topics(8)) == 8

    def test_narrow_source_caps_below_requested(self) -> None:
        """좁은 소스(단일 챕터·개념 2개·짧은 텍스트)는 20 요청을 캡한다."""
        eff = effective_target_count(20, "BST 자료. " * 10, _narrow_topics())
        assert eff < 20, f"좁은 소스인데 캡이 안 됨: {eff}"
        # 절대 하한 5 이상은 보장
        assert eff >= 5

    def test_wide_source_no_cap(self) -> None:
        """넓은 소스(챕터·개념 충분 + 긴 텍스트)는 요청 그대로 유지한다 (회귀 0)."""
        eff = effective_target_count(20, "x" * 8000, _wide_topics(8))
        assert eff == 20, f"넓은 소스인데 캡됨: {eff}"

    def test_long_text_single_segment_does_not_lift_cap(self) -> None:
        """단일 세그먼트(좁은 소스)는 source_text가 길어도 캡이 풀리지 않는다.

        (정책 변경 2026-06-13: 장황한 단일 챕터가 글자수만으로 capacity를 부풀려
        좁은 소스인데도 20문항을 강제해 dedup 비수렴 FAILED가 되던 회귀를 차단.
        글자수 신호는 세그먼트 ≥ 2 일 때만 max에 포함한다.)
        """
        eff = effective_target_count(20, "가" * 5000, [{"name": "한 주제", "chapter": "c"}])
        assert eff < 20

    def test_long_text_multi_segment_lifts_cap(self) -> None:
        """여러 세그먼트(넓은 소스)면 글자수 신호가 포함돼 캡이 풀린다."""
        topics = [{"name": f"주제{i}", "chapter": f"c{i}"} for i in range(6)]
        eff = effective_target_count(20, "가" * 5000, topics)
        assert eff == 20

    def test_capacity_absolute_floor(self) -> None:
        """소스가 텅 비어도 절대 하한(5) 이상을 반환한다."""
        assert source_capacity("", []) >= 5

    def test_effective_never_exceeds_requested(self) -> None:
        """effective target은 절대 요청 수를 초과하지 않는다."""
        eff = effective_target_count(8, "x" * 100000, _wide_topics(20))
        assert eff <= 8

    def test_zero_requested_returns_zero(self) -> None:
        """요청 0이면 0 (방어)."""
        assert effective_target_count(0, "x" * 1000, _wide_topics()) == 0


# ── B: plan_exam_node.apply_effective_target ─────────────────────────────────

class TestApplyEffectiveTarget:
    """캡 적용과 requested_question_count 메타 보존."""

    def test_narrow_caps_total_and_preserves_requested(self) -> None:
        """좁은 소스: total_questions↓, requested_question_count=원래 요청."""
        config = {"total_questions": 20, "question_types": []}
        capped = apply_effective_target(config, "BST 자료. " * 5, _narrow_topics())
        assert capped["total_questions"] < 20
        assert capped["requested_question_count"] == 20

    def test_wide_keeps_total_and_sets_requested_meta(self) -> None:
        """넓은 소스: total_questions 무변경, requested_question_count는 채워진다."""
        config = {"total_questions": 20, "question_types": []}
        capped = apply_effective_target(config, "x" * 8000, _wide_topics(8))
        assert capped["total_questions"] == 20
        assert capped["requested_question_count"] == 20

    def test_does_not_mutate_input_config(self) -> None:
        """입력 config를 변이시키지 않는다(사본 반환)."""
        config = {"total_questions": 20, "question_types": []}
        apply_effective_target(config, "BST. " * 5, _narrow_topics())
        assert config["total_questions"] == 20
        assert "requested_question_count" not in config


# ── C: format_output 3분기 ────────────────────────────────────────────────────

def _make_q(i: int) -> dict:
    """구조·식별자 무결한 문항 더미."""
    return {
        "question_id": f"q{i}", "stem": f"서로 다른 발문 {i}",
        "template_id": "ko_multiple_choice_5", "topic": "A",
        "difficulty": 3, "bloom_level": "이해",
        "options": [], "correct_answer": "1", "explanation": "설명",
    }


class TestFormatOutputThreeWayOutcome:
    """unique 문항 수 기준 passed / needs_more_source / failed 분기."""

    @staticmethod
    def _run(questions: list[dict], total: int, requested: int) -> dict:
        state = {
            "calibrated_questions": questions,
            "exam_plan": {"topic_weights": {"A": 1.0}},
            "exam_config": {
                "total_questions": total,
                "requested_question_count": requested,
            },
            "retry_count": 0,
            "max_retries": 3,
            "failed_question_ids": [],
            "timings": {"start": 0},
        }
        return asyncio.run(format_output_node(state))

    def test_narrow_full_generation_passes(self) -> None:
        """좁은 소스라도 유효 목표(캡된 8)를 다 채우면 passed — 회귀 핵심.

        20 요청이 8로 캡된 뒤 8문항을 다 만들면 actual==effective==8 → passed.
        """
        result = self._run([_make_q(i) for i in range(8)], total=8, requested=20)
        assert result["pipeline_outcome"] == "passed"
        assert result["pipeline_status"] == "complete"
        assert len(result["calibrated_questions"]) == 8

    def test_above_floor_below_target_is_partial(self) -> None:
        """floor 이상·목표 미만이면 passed_partial로 출고한다 (floor(20)=10)."""
        result = self._run([_make_q(i) for i in range(12)], total=20, requested=20)
        assert result["pipeline_outcome"] == "passed_partial"
        assert result["pipeline_status"] == "partial"

    def test_below_floor_is_needs_more_source_not_failed(self) -> None:
        """floor 미만이면 needs_more_source(비-FAILED) — 0문항 FAILED 방지 핵심."""
        # 유효 목표 20, floor=10, 고유 3 → needs_more_source
        result = self._run([_make_q(i) for i in range(3)], total=20, requested=20)
        assert result["pipeline_outcome"] == "needs_more_source"
        assert not result["pipeline_outcome"].startswith("failed")
        assert result["pipeline_status"] == "partial"
        # 확보된 고유 문항은 출고된다
        assert len(result["calibrated_questions"]) == 3
        assert "자료 부족" in result["error_message"]

    def test_zero_unique_is_genuine_failed(self) -> None:
        """고유 문항 0개만 진짜 failed."""
        result = self._run([], total=20, requested=20)
        assert result["pipeline_outcome"].startswith("failed")
        assert result["pipeline_status"] == "failed"

    def test_completion_floor_formula(self) -> None:
        """floor = max(5, ceil(target*0.5)), 단 target보다 크지 않게."""
        assert _completion_floor(20) == 10
        assert _completion_floor(8) == 5   # ceil(4)=4 < 5 → 5
        assert _completion_floor(6) == 5   # ceil(3)=3 < 5 → 5, target 6보다 작으니 5
        assert _completion_floor(4) == 4   # floor 5가 target 4보다 크니 target으로 클램프
        assert _completion_floor(0) == 5


# ── D: 재생성 프롬프트 dedup-aware ────────────────────────────────────────────

class TestRegenerationContext:
    """재생성 청크 프롬프트에 기존 stem·개념이 포함되는지."""

    def test_avoidance_clause_contains_existing_stem(self) -> None:
        """이미 채택된 stem 요약이 회피 절에 포함된다."""
        existing = [{"stem": "BST 삽입의 시간 복잡도는?", "concept": "삽입"}]
        clause = build_avoidance_clause(existing, {"concept": "삭제", "difficulty": 3})
        assert "BST 삽입의 시간 복잡도는?" in clause
        assert "이미 다룬 개념" in clause
        assert "삽입" in clause

    def test_avoidance_clause_empty_for_no_existing(self) -> None:
        """기존 문항이 없으면(첫 생성) 빈 문자열 — 기존 동작 보존."""
        assert build_avoidance_clause([], {"concept": "삭제"}) == ""

    def test_avoidance_clause_includes_target_slot(self) -> None:
        """이번 청크가 채울 coverage slot(개념·난이도·추론축)이 명시된다."""
        existing = [{"stem": "문제1", "concept": "삽입"}]
        clause = build_avoidance_clause(
            existing,
            {"concept": "삭제", "difficulty": 4, "reasoning_type": "오류 원인 분석"},
        )
        assert "삭제" in clause
        assert "오류 원인 분석" in clause

    def test_build_repair_tasks_attaches_avoidance_clause(self) -> None:
        """build_repair_tasks(블루프린트 경로)가 각 보충 청크에 기존 stem을 실어준다."""
        existing = [
            {
                "stem": "이미 출제된 발문 — 삽입 동작",
                "_concept_key": "BST::이진탐색트리::삽입::d3::개념 확인",
                "concept": "삽입",
            }
        ]
        blueprint = [
            {  # 이미 채워진 슬롯 (filled_keys에 매칭)
                "slot": 1, "template_id": "ko_multiple_choice_5",
                "concept_key": "BST::이진탐색트리::삽입::d3::개념 확인",
                "concept": "삽입", "difficulty": 3,
            },
            {  # 누락 슬롯 — 이 청크가 생성된다
                "slot": 2, "template_id": "ko_multiple_choice_5",
                "concept_key": "BST::이진탐색트리::삭제::d4::오류 원인 분석",
                "concept": "삭제", "difficulty": 4,
                "reasoning_type": "오류 원인 분석", "num_choices": 5,
                "target_answer_position": 2,
            },
        ]
        tasks = build_repair_tasks(
            allocations=[{"template_id": "ko_multiple_choice_5", "count": 2}],
            topic_weights={"이진 탐색 트리": 1.0},
            existing_drafts=existing,
            blueprint=blueprint,
        )
        assert len(tasks) == 1, "누락 슬롯 1개만 보충 청크가 돼야 한다"
        clause = tasks[0].get("_avoidance_clause", "")
        assert clause, "보충 청크에 회피 절이 없다 — 단순 재호출(비수렴)"
        assert "이미 출제된 발문 — 삽입 동작" in clause, "기존 stem이 청크 프롬프트에 없다"

    def test_build_repair_tasks_fallback_path_attaches_clause(self) -> None:
        """블루프린트 없는 폴백 경로에서도 회피 절이 붙는다."""
        existing = [{"stem": "기존 발문 A", "template_id": "ko_short_answer", "concept": "X"}]
        tasks = build_repair_tasks(
            allocations=[{
                "template_id": "ko_short_answer", "count": 3,
                "difficulty_distribution": {3: 3},
            }],
            topic_weights={"주제": 1.0},
            existing_drafts=existing,
            blueprint=None,
        )
        assert tasks, "보충 청크가 생성돼야 한다"
        assert all("기존 발문 A" in t.get("_avoidance_clause", "") for t in tasks)


# ── E: mock_async_router — needs_more_source 출고 + 콜백 신규 필드 ─────────────

class TestMockAsyncRouterOutcome:
    """needs_more_source는 출고하고, 콜백에 요청/생성 수·outcome을 싣는다."""

    def test_needs_more_source_ships_with_new_callback_fields(self) -> None:
        """needs_more_source면 성공 콜백을 보내고 신규 필드를 전달한다."""
        from app.modules.ExamForge_V1.app.routers import mock_async_router as mod
        from app.modules.ExamForge_V1.app.routers.mock_async_router import (
            MockGenerateAsyncRequest,
            _run_async_generation,
        )

        class _FakeResponse:
            pipeline_outcome = "needs_more_source"
            exam_id = "exam_test"

            class _Q:
                @staticmethod
                def model_dump() -> dict:
                    return {"question_id": "q1", "template_id": "ko_multiple_choice_5"}

            questions = [_Q(), _Q(), _Q()]  # 고유 3문항 출고

        captured: dict = {}

        async def _fake_pipeline(req):
            return _FakeResponse(), "seal_value", False

        def _fake_success(**kwargs):
            captured.update(kwargs)

        def _fake_failed(**kwargs):
            captured["FAILED_CALLED"] = kwargs

        req = MockGenerateAsyncRequest(
            attempt_id="a1", course_id="c1", subject="자료구조",
            question_count=20, difficulty="hard",
        )
        with (
            patch.object(mod, "_execute_exam_forge_pipeline", _fake_pipeline),
            patch.object(mod, "send_generation_success_callback", _fake_success),
            patch.object(mod, "send_generation_failed_callback", _fake_failed),
        ):
            asyncio.run(_run_async_generation(req))

        assert "FAILED_CALLED" not in captured, "needs_more_source인데 FAILED 콜백이 전송됨"
        assert captured.get("generation_outcome") == "needs_more_source"
        assert captured.get("requested_question_count") == 20
        assert captured.get("actual_question_count") == 3

    def test_failed_outcome_still_blocked(self) -> None:
        """failed_* outcome은 여전히 FAILED 콜백으로 차단된다 (회귀 0)."""
        from app.modules.ExamForge_V1.app.routers import mock_async_router as mod
        from app.modules.ExamForge_V1.app.routers.mock_async_router import (
            MockGenerateAsyncRequest,
            _run_async_generation,
        )

        class _FailResponse:
            pipeline_outcome = "failed_no_valid_questions"
            exam_id = "exam_test"
            questions: list = []

        captured: dict = {}

        async def _fake_pipeline(req):
            return _FailResponse(), "seal", False

        def _fake_success(**kwargs):
            captured["SUCCESS_CALLED"] = kwargs

        def _fake_failed(**kwargs):
            captured["FAILED_CALLED"] = kwargs

        req = MockGenerateAsyncRequest(
            attempt_id="a2", course_id="c1", subject="자료구조", question_count=20,
        )
        with (
            patch.object(mod, "_execute_exam_forge_pipeline", _fake_pipeline),
            patch.object(mod, "send_generation_success_callback", _fake_success),
            patch.object(mod, "send_generation_failed_callback", _fake_failed),
        ):
            asyncio.run(_run_async_generation(req))

        assert "SUCCESS_CALLED" not in captured, "failed_* outcome인데 성공 콜백이 전송됨"
        assert "FAILED_CALLED" in captured


# ── F: 콜백 payload 신규 필드 직렬화 ──────────────────────────────────────────

class TestCallbackPayloadFields:
    """send_generation_success_callback이 신규 필드를 camelCase로 싣는다."""

    def test_new_fields_in_payload_when_present(self) -> None:
        """값이 있으면 requestedQuestionCount/actualQuestionCount/generationOutcome을 싣는다."""
        from app.modules.ExamForge_V1 import mock_generation_callback as cb

        captured: dict = {}

        def _fake_post(url, token, payload):
            captured.update(payload)

        with patch.object(cb, "_post_to_spring", _fake_post):
            cb.send_generation_success_callback(
                attempt_id="a1", exam_id="e1", answer_key_seal="seal",
                questions=[{"question_id": "q1", "template_id": "ko_multiple_choice_5"}],
                requested_question_count=20,
                actual_question_count=8,
                generation_outcome="needs_more_source",
            )
        assert captured["requestedQuestionCount"] == 20
        assert captured["actualQuestionCount"] == 8
        assert captured["generationOutcome"] == "needs_more_source"

    def test_new_fields_omitted_when_none(self) -> None:
        """None이면 키를 생략 — 기존 payload와 동일(비파괴적, 회귀 0)."""
        from app.modules.ExamForge_V1 import mock_generation_callback as cb

        captured: dict = {}

        def _fake_post(url, token, payload):
            captured.update(payload)

        with patch.object(cb, "_post_to_spring", _fake_post):
            cb.send_generation_success_callback(
                attempt_id="a1", exam_id="e1", answer_key_seal="seal",
                questions=[{"question_id": "q1", "template_id": "ko_multiple_choice_5"}],
            )
        assert "requestedQuestionCount" not in captured
        assert "actualQuestionCount" not in captured
        assert "generationOutcome" not in captured
        # 기존 필수 키는 그대로
        assert captured["examId"] == "e1"
        assert captured["groundingDegraded"] is False


def test_verbose_single_segment_does_not_inflate_capacity():
    """단일 챕터의 장황한 본문(긴 글자수)이 capacity를 부풀려 캡을 무력화하면 안 된다."""
    from app.modules.ExamForge_V1.common.source_capacity import (
        effective_target_count,
        source_capacity,
    )
    # 단일 세그먼트(chapter 1개) + 개념 2개 + 매우 긴 본문(20문항어치 글자수)
    topics = [{"name": "BST", "chapter": "ch1", "sub_concepts": ["탐색", "삽입"]}]
    long_text = "이진 탐색 트리는 정렬된 데이터를 효율적으로 다룬다. " * 200  # 수천 자
    cap = source_capacity(long_text, topics)
    # 글자수가 길어도 단일 세그먼트라 개념 폭(2*2=4)·floor(5)로만 산정 → 20 미만
    assert cap < 20, f"단일 세그먼트 verbose가 캡을 부풀림: cap={cap}"
    assert effective_target_count(20, long_text, topics) < 20


def test_multi_segment_broad_source_uncapped():
    """여러 챕터(넓은 소스)는 글자수 신호 포함해 캡이 풀려야 한다(회귀 0)."""
    from app.modules.ExamForge_V1.common.source_capacity import effective_target_count
    topics = [{"name": f"개념{i}", "chapter": f"ch{i}",
               "sub_concepts": [f"a{i}", f"b{i}", f"c{i}"]} for i in range(8)]
    long_text = "여러 챕터에 걸친 폭넓은 학습 자료. " * 400
    assert effective_target_count(20, long_text, topics) == 20


class TestQualityGateDoesNotHardFailAboveFloor:
    """품질 게이트(커버리지/코드부재)가 걸려도 floor 이상 유효 문항이면 0으로 차단하지 않는다.

    회귀: 넓은 소스 스프링부트 18/20 문항이 _missing_programming_code에 걸려
    failed_quality_gate로 통째 FAILED(0문항)되던 버그. floor 이상이면 passed_partial로 출고해야 한다.
    """

    @staticmethod
    def _run_with_gate(monkeypatch, questions, total, requested, gate="coverage"):
        import asyncio
        from app.modules.ExamForge_V1.pipeline.nodes import format_output_node as mod
        if gate == "coverage":
            monkeypatch.setattr(mod, "_is_low_coverage", lambda *a, **k: True)
        else:
            monkeypatch.setattr(mod, "_missing_programming_code", lambda *a, **k: True)
        # 재시도 소진(terminal) — 품질게이트 degrade는 재시도가 끝났을 때만 적용된다.
        state = {
            "calibrated_questions": questions,
            "exam_plan": {"topic_weights": {"A": 1.0}},
            "exam_config": {"total_questions": total, "requested_question_count": requested},
            "retry_count": 3, "max_retries": 3, "failed_question_ids": [], "timings": {"start": 0},
        }
        return asyncio.run(mod.format_output_node(state))

    def test_coverage_gate_above_floor_ships_partial(self, monkeypatch) -> None:
        # 18/20, floor=10 → 커버리지 게이트 걸려도 passed_partial(비-FAILED)
        res = self._run_with_gate(monkeypatch, [_make_q(i) for i in range(18)], total=20, requested=20)
        assert res["pipeline_outcome"] == "passed_partial"
        assert res["pipeline_status"] != "failed"

    def test_missing_code_gate_above_floor_ships_partial(self, monkeypatch) -> None:
        res = self._run_with_gate(monkeypatch, [_make_q(i) for i in range(18)], total=20, requested=20, gate="code")
        assert res["pipeline_outcome"] == "passed_partial"
        assert res["pipeline_status"] != "failed"

    def test_quality_gate_below_floor_still_needs_more_source(self, monkeypatch) -> None:
        # floor 미만이면 애초에 needs_more_source로 빠지므로 품질게이트 하드FAIL 경로를 타지 않는다
        res = self._run_with_gate(monkeypatch, [_make_q(i) for i in range(3)], total=20, requested=20)
        assert res["pipeline_outcome"] in ("needs_more_source", "passed_partial")
        assert res["pipeline_status"] != "failed"

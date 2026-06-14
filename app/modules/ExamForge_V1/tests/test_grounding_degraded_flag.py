"""grounding degraded 추적 회귀 테스트 (codex 백로그 #9).

course 기반 모의고사에서 DB 본문이 hard-gate(최소 글자수) 미달이면 subject/topic
스텁으로 조용히 폴백하던 동작을, 명시적으로 추적 가능하게 강화한 것을 검증한다.

- grounded source 충분 → grounding_degraded=False
- DB 실패/본문 부재(hard-gate 미달) → grounding_degraded=True + WARNING 로그
- 성공 콜백 payload에 groundingDegraded 키가 실린다(상위 인지 가능)
- 생성 자체는 막지 않는다(데모 진행 가능 — degraded 여도 출고 경로 정상)

실 AI/실 DB 호출 없이 monkeypatch fixture 만 쓴다.
"""
from __future__ import annotations

import logging

import pytest

from app.modules.ExamForge_V1 import mock_generation_callback as cb
from app.modules.ExamForge_V1.app.routers import mock_async_router


def _req(**kw: object) -> "mock_async_router.MockGenerateAsyncRequest":
    base = {
        "attempt_id": "eat_g1",
        "course_id": "course_g1",
        "subject": "운영체제",
        "topic": "프로세스 스케줄링",
    }
    base.update(kw)
    return mock_async_router.MockGenerateAsyncRequest(**base)


class _FakeConn:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


# ── _load_grounded_source_text degraded 플래그 ─────────────────────────────


class TestGroundingDegradedFlag:
    @pytest.mark.asyncio
    async def test_sufficient_grounding_not_degraded(self, monkeypatch) -> None:
        """본문이 hard-gate 이상이면 degraded=False 로 정상 grounding 인정."""
        import common.db as common_db

        long_text = "프로세스 스케줄링 알고리즘과 문맥 교환 비용을 설명한다. " * 8

        async def fake_build(conn: object, course_id: str, topic: str | None) -> str:
            return long_text

        monkeypatch.setattr(common_db, "get_connection", lambda: _FakeConn())
        monkeypatch.setattr(mock_async_router, "build_db_source_text", fake_build)

        source, degraded = await mock_async_router._load_grounded_source_text(_req())
        assert degraded is False
        assert "프로세스 스케줄링 알고리즘" in source

    @pytest.mark.asyncio
    async def test_db_failure_marks_degraded_and_warns(
        self, monkeypatch, caplog
    ) -> None:
        """DB 조회 실패 → degraded=True + WARNING 로그가 명확히 남는다."""
        import common.db as common_db

        def boom() -> object:
            raise RuntimeError("DB 미설정")

        monkeypatch.setattr(common_db, "get_connection", boom)

        with caplog.at_level(logging.WARNING, logger=mock_async_router._LOG.name):
            source, degraded = await mock_async_router._load_grounded_source_text(
                _req(topic=None)
            )

        assert degraded is True
        assert len(source) >= mock_async_router._SOURCE_MIN_LEN
        # WARNING 로그에 degraded 신호가 명확히 들어가야 한다
        assert any(
            "grounding degraded" in rec.getMessage().lower()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_short_db_content_below_hard_gate_marks_degraded(
        self, monkeypatch
    ) -> None:
        """본문이 hard-gate(100자) 미만이면 degraded=True 로 스텁 폴백한다."""
        import common.db as common_db

        async def fake_build(conn: object, course_id: str, topic: str | None) -> str:
            return "아주 짧은 강의 메모"

        monkeypatch.setattr(common_db, "get_connection", lambda: _FakeConn())
        monkeypatch.setattr(mock_async_router, "build_db_source_text", fake_build)

        source, degraded = await mock_async_router._load_grounded_source_text(_req())
        assert degraded is True
        assert len(source) >= mock_async_router._SOURCE_MIN_LEN

    @pytest.mark.asyncio
    async def test_hard_gate_boundary_exactly_at_threshold(
        self, monkeypatch
    ) -> None:
        """hard-gate 경계 — 정확히 임계 글자수면 grounding 인정(degraded=False)."""
        import common.db as common_db

        exactly = "가" * mock_async_router._GROUNDING_HARD_GATE_LEN

        async def fake_build(conn: object, course_id: str, topic: str | None) -> str:
            return exactly

        monkeypatch.setattr(common_db, "get_connection", lambda: _FakeConn())
        monkeypatch.setattr(mock_async_router, "build_db_source_text", fake_build)

        _source, degraded = await mock_async_router._load_grounded_source_text(_req())
        assert degraded is False


# ── 성공 콜백 payload 에 groundingDegraded 노출 ────────────────────────────


class TestCallbackExposesGroundingDegraded:
    def _patch_callback_io(self, monkeypatch) -> dict:
        """콜백의 외부 I/O(URL/토큰/POST)를 막고 payload만 포착한다."""
        captured: dict = {}

        monkeypatch.setattr(cb, "_get_spring_base_url", lambda: "http://spring.test")
        monkeypatch.setattr(cb, "_get_internal_token", lambda: "tok")

        def fake_post(url: str, token: str, payload: dict) -> None:
            captured["url"] = url
            captured["payload"] = payload

        monkeypatch.setattr(cb, "_post_to_spring", fake_post)
        return captured

    def _valid_question(self) -> dict:
        # options는 QuestionOption dict 형태(label/text/is_correct)로 전달한다 —
        # _to_spring_question 이 dict.get 으로 변환하기 때문이다.
        return {
            "question_id": "q1",
            "template_id": "MCQ_4",
            "stem": "스케줄링이란?",
            "options": [
                {"label": "A", "text": "선점형", "is_correct": True},
                {"label": "B", "text": "비선점형", "is_correct": False},
            ],
            "points": 1.0,
            "correct_answer": "A",
            "explanation": "해설",
        }

    def test_payload_includes_grounding_degraded_true(self, monkeypatch) -> None:
        """degraded=True 시 payload에 groundingDegraded=True 가 실린다."""
        captured = self._patch_callback_io(monkeypatch)
        cb.send_generation_success_callback(
            attempt_id="eat_g1",
            exam_id="exam_x",
            answer_key_seal="seal",
            questions=[self._valid_question()],
            grounding_degraded=True,
        )
        assert captured["payload"]["groundingDegraded"] is True
        # 기존 필수 키는 그대로 유지된다(비파괴적)
        assert captured["payload"]["examId"] == "exam_x"
        assert captured["payload"]["answerKeySeal"] == "seal"
        assert captured["payload"]["questions"]

    def test_payload_defaults_grounding_degraded_false(self, monkeypatch) -> None:
        """flag 미전달 시 기본값 False — 기존 호출자 하위호환."""
        captured = self._patch_callback_io(monkeypatch)
        cb.send_generation_success_callback(
            attempt_id="eat_g1",
            exam_id="exam_y",
            answer_key_seal="seal",
            questions=[self._valid_question()],
        )
        assert captured["payload"]["groundingDegraded"] is False


# ── 라우터 _safe_send_success_callback 가 flag를 전달하는지 ─────────────────


class TestSafeSendCallbackThreadsFlag:
    @pytest.mark.asyncio
    async def test_flag_passed_through_to_callback(self, monkeypatch) -> None:
        """라우터 헬퍼가 grounding_degraded 를 콜백 함수까지 그대로 넘긴다."""
        seen: dict = {}

        def fake_callback(**kwargs: object) -> None:
            seen.update(kwargs)

        monkeypatch.setattr(
            mock_async_router, "send_generation_success_callback", fake_callback
        )

        await mock_async_router._safe_send_success_callback(
            attempt_id="eat_g1",
            exam_id="exam_z",
            answer_key_seal="seal",
            questions=[{"question_id": "q1"}],
            grounding_degraded=True,
        )
        assert seen.get("grounding_degraded") is True

"""LLM 비정상/부분 JSON 출력 방어 회귀 테스트 (2026-06-13).

plan_exam_node의 "난이도 dict만 반환 → ValidationError → 0건" 부류와 동일한,
'unit은 녹색인데 실 LLM 출력에서만 터지는' 크래시를 async 생성 경로에서 추가로 막는다.

대상 결함:
1. calibrate_difficulty_node — parse_llm_json이 배열/스칼라를 주면 data.get()이
   AttributeError로 죽고(except 미포착) 정상 생성된 시험 전체가 파이프라인 실패로
   전환되던 버그. dict가 아니면 보정 생략으로 흡수해야 한다(원본 문항 보존).
2. generate_distractors_node — 동일 패턴. dict가 아니면 원본 선택지를 유지해야 한다.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class _Resp:
    """connector.generate 응답 최소 스텁."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.finish_reason = "stop"


# ── calibrate_difficulty_node: 배열/스칼라 응답 방어 ──────────────────────


class TestCalibrateMalformedOutput:
    @pytest.mark.asyncio
    async def test_array_response_does_not_fail_pipeline(self) -> None:
        """LLM이 calibrations 객체 대신 bare 배열을 줘도 크래시/실패 전환이 없다."""
        from app.modules.ExamForge_V1.pipeline.nodes.calibrate_difficulty_node import (
            calibrate_difficulty_node,
        )

        questions = [
            {"question_id": "q1", "stem": "문제1", "difficulty": 2, "bloom_level": "이해"},
            {"question_id": "q2", "stem": "문제2", "difficulty": 3, "bloom_level": "적용"},
        ]
        # bloom 불균형을 강제해 _is_balanced=False → 실제 AI 보정 경로로 진입시킨다
        state = {
            "verified_questions": questions,
            "exam_plan": {"bloom_distribution": {"이해": 0.9, "적용": 0.1}},
        }
        # 과거 크래시 입력: calibrations 객체가 아닌 bare 배열
        resp = _Resp('[{"question_id": "q1", "suggested_difficulty": 5}]')
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.calibrate_difficulty_node.get_planner_connector"
        ) as conn:
            conn.return_value.generate = AsyncMock(return_value=resp)
            result = await calibrate_difficulty_node(state)

        # 파이프라인 실패(status=error/빈 결과)로 전환되지 않고 정상 진행한다
        assert result["pipeline_status"] == "formatting"
        calibrated = result["calibrated_questions"]
        assert len(calibrated) == 2
        # 보정 미적용(원본 난이도 보존) — 배열 응답은 보정 생략으로 흡수됐다
        diffs = {q["question_id"]: q["difficulty"] for q in calibrated}
        assert diffs == {"q1": 2, "q2": 3}
        # 비정상 응답은 보정 파싱 실패로 기록된다(조용한 통과 아님)
        assert "error_message" in result

    @pytest.mark.asyncio
    async def test_scalar_calibration_items_skipped(self) -> None:
        """calibrations가 dict가 아닌 항목(문자열 등)을 포함해도 죽지 않는다."""
        from app.modules.ExamForge_V1.pipeline.nodes.calibrate_difficulty_node import (
            calibrate_difficulty_node,
        )

        questions = [
            {"question_id": "q1", "stem": "문제1", "difficulty": 2, "bloom_level": "이해"},
            {"question_id": "q2", "stem": "문제2", "difficulty": 3, "bloom_level": "적용"},
        ]
        # 현재 분포(이해 0.5/적용 0.5) vs 목표(이해 0.9/적용 0.1) 불균형 → AI 보정 경로 진입
        state = {
            "verified_questions": questions,
            "exam_plan": {"bloom_distribution": {"이해": 0.9, "적용": 0.1}},
        }
        # calibrations 안에 dict와 스칼라가 섞임 — 스칼라 항목의 .get() 크래시 방어
        resp = _Resp(
            '{"calibrations": ["깨진항목", {"question_id": "q1", "suggested_difficulty": 4}]}'
        )
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.calibrate_difficulty_node.get_planner_connector"
        ) as conn:
            conn.return_value.generate = AsyncMock(return_value=resp)
            result = await calibrate_difficulty_node(state)

        assert result["pipeline_status"] == "formatting"
        calibrated = result["calibrated_questions"]
        # 유효한 dict 항목(q1)의 보정은 정상 적용된다
        assert calibrated[0]["difficulty"] == 4


# ── generate_distractors_node: 배열 응답 방어 ────────────────────────────


def _mcq() -> dict:
    """오답 개선 대상 5지선다 문항."""
    return {
        "draft_id": "d1",
        "template_id": "ko_multiple_choice_5",
        "topic": "A",
        "difficulty": 3,
        "bloom_level": "이해",
        "stem": "테스트?",
        "options": [
            {"label": "1", "text": "보기1", "is_correct": True},
            {"label": "2", "text": "보기2", "is_correct": False},
            {"label": "3", "text": "보기3", "is_correct": False},
            {"label": "4", "text": "보기4", "is_correct": False},
            {"label": "5", "text": "보기5", "is_correct": False},
        ],
    }


class TestDistractorMalformedOutput:
    @pytest.mark.asyncio
    async def test_array_response_keeps_original_options(self) -> None:
        """LLM이 객체 대신 bare 배열을 줘도 크래시 없이 원본 선택지를 유지한다."""
        from app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node import (
            generate_distractors_node,
        )

        state = {"questions": [_mcq()], "locale": "ko"}
        # 과거 AttributeError 입력: {"options": ...} 객체가 아닌 bare 배열
        resp = _Resp('[{"label": "1", "text": "DEEP"}]')
        with patch(
            "app.modules.ExamForge_V1.pipeline.nodes.generate_distractors_node.get_text_connector"
        ) as conn:
            conn.return_value.generate = AsyncMock(return_value=resp)
            result = await generate_distractors_node(state)

        # 다음 단계로 정상 진행한다
        assert result["pipeline_status"] == "answering"
        out = result["questions_with_distractors"]
        assert len(out) == 1
        # 비정상 응답이므로 원본 5개 선택지가 그대로 보존됐다(배열로 덮어쓰이지 않음)
        opts = out[0].get("options") or []
        assert len(opts) == 5
        labels = [o.get("text") for o in opts]
        assert labels == ["보기1", "보기2", "보기3", "보기4", "보기5"]

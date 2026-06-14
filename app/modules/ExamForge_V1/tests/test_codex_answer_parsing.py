"""P0/P1 회귀 방지: codex 정답 파싱 견고성 + 개수 정합 테스트.

검증 항목:
  1. codex 정답 응답이 JSON이면 정상 파싱
  2. codex 응답이 래핑된 object {"correct_answer":...} 이면 정상 파싱
  3. JSON 파싱 전체 실패 시 regex fallback이 correct_answer·explanation을 추출
  4. _extract_answer_by_regex 가 bare 텍스트 응답에서도 동작
  5. _empty_answer → _has_answer_payload(False) 를 validate_node가 실패로 분류
  6. passed_partial 상태일 때 _coerce_exam_plan이 total_questions를 실제 수로 조정
  7. (삭제됨) codex 커넥터 _build_command 검증 — codex CLI 커넥터 제거(7abc300)로 함께 삭제
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.ExamForge_V1.pipeline.nodes.generate_answers_node import (
    _empty_answer,
    _extract_answer_by_regex,
    _has_answer_payload,
)
from app.modules.ExamForge_V1.schemas.question import QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.schemas.response import _coerce_exam_plan


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _make_draft(draft_id: str = "draft_test") -> QuestionDraft:
    return QuestionDraft(
        draft_id=draft_id,
        template_id="ko_multiple_choice_4",
        topic="운영체제",
        difficulty=3,
        bloom_level="이해",
        stem="다음 중 선점 스케줄링 기법은?",
        options=[
            QuestionOption(label="1", text="FCFS", is_correct=False),
            QuestionOption(label="2", text="Round Robin", is_correct=True),
            QuestionOption(label="3", text="SJF", is_correct=False),
            QuestionOption(label="4", text="HRN", is_correct=False),
        ],
    )


# ── 정상 JSON 파싱 ────────────────────────────────────────────────────────────

def test_parse_clean_json_correct_answer() -> None:
    """깨끗한 JSON 응답은 _extract_answer_by_regex 없이도 정상 파싱된다."""
    from app.modules.ExamForge_V1.common.json_utils import parse_llm_json
    raw = '{"correct_answer":"2","explanation":"정답 근거다. 1번은 비선점이고 3번은 SJF다.","source_reference":"p.32"}'
    data = parse_llm_json(raw)
    assert data["correct_answer"] == "2"
    assert "정답" in data["explanation"]


def test_parse_wrapped_object_json() -> None:
    """래핑된 {"correct_answer":...} 도 unwrap 없이 바로 파싱된다."""
    from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, normalize_question_fields
    raw = json.dumps({
        "correct_answer": "3",
        "explanation": "정답은 3번입니다. 1번은 FCFS이며 비선점입니다. 2번은 RR이지만 조건이 다릅니다.",
        "source_reference": "스케줄링 섹션"
    }, ensure_ascii=False)
    data = parse_llm_json(raw)
    data = normalize_question_fields(data)
    assert data["correct_answer"] == "3"
    assert len(data["explanation"]) > 20


# ── regex fallback ────────────────────────────────────────────────────────────

def test_regex_fallback_basic_json_fragment() -> None:
    """JSON 파싱 실패 상황에서 regex fallback이 correct_answer를 추출한다."""
    draft = _make_draft()
    # JSON이지만 explanation 필드에 unescaped 큰따옴표가 있어 직접 파싱 실패하는 상황 시뮬레이션
    raw = (
        '{"correct_answer": "2", "explanation": "정답은 2번 Round Robin입니다. '
        '1번 FCFS는 비선점이고 3번 SJF도 비선점입니다. 4번 HRN은 응답 비율 계산 방식입니다.", '
        '"source_reference": "스케줄링"}'
    )
    result = _extract_answer_by_regex(raw, draft)
    assert result is not None
    assert result["correct_answer"] == "2"
    assert len(result["explanation"]) >= 20


def test_regex_fallback_sets_draft_fields() -> None:
    """regex fallback 결과에 draft의 stem·options·topic이 담겨있다."""
    draft = _make_draft("draft_abc123")
    raw = '{"correct_answer": "1", "explanation": "정답은 1번입니다. 나머지는 틀립니다."}'
    result = _extract_answer_by_regex(raw, draft)
    assert result is not None
    assert result["draft_id"] == "draft_abc123"
    assert result["stem"] == "다음 중 선점 스케줄링 기법은?"
    assert isinstance(result["options"], list)
    assert len(result["options"]) == 4


def test_regex_fallback_unescaped_quotes_in_explanation() -> None:
    """P0 핵심 케이스: explanation 내부에 이스케이프되지 않은 큰따옴표가 있는 Qwen3 출력.

    JSON 파싱은 실패하지만 regex fallback이 설명문을 정확하게 추출한다.
    """
    draft = _make_draft()
    # Qwen3가 코드 예시에 이스케이프 없는 따옴표를 넣는 실제 실패 패턴
    bad_json = (
        '{"correct_answer": "2", "explanation": "정답은 2번 LIFO입니다. '
        'stack.push("item") 연산으로 삽입합니다. 1번 FCFS는 큐의 특성입니다(FIFO/LIFO 혼동).", '
        '"source_reference": "스택 단원"}'
    )
    import json as _json
    # JSON 파싱이 실제로 실패하는지 확인
    try:
        _json.loads(bad_json)
        assert False, "이 테스트는 JSON 파싱이 실패해야 한다"
    except _json.JSONDecodeError:
        pass
    # regex fallback이 올바른 값을 추출해야 한다
    result = _extract_answer_by_regex(bad_json, draft)
    assert result is not None
    assert result["correct_answer"] == "2"
    assert 'LIFO' in result["explanation"]
    assert 'stack.push' in result["explanation"]  # 코드 조각도 보존
    assert result["source_reference"] == "스택 단원"


def test_regex_fallback_returns_none_on_no_match() -> None:
    """correct_answer가 전혀 없는 응답에서는 None을 반환한다."""
    draft = _make_draft()
    result = _extract_answer_by_regex("아무것도 없는 텍스트입니다.", draft)
    assert result is None


# ── _has_answer_payload ───────────────────────────────────────────────────────

def test_has_answer_payload_false_on_empty() -> None:
    """correct_answer 또는 explanation이 비어있으면 False를 반환한다."""
    assert _has_answer_payload({"correct_answer": "", "explanation": "설명"}) is False
    assert _has_answer_payload({"correct_answer": "2", "explanation": ""}) is False
    assert _has_answer_payload({}) is False


def test_has_answer_payload_true_on_filled() -> None:
    """correct_answer와 explanation이 모두 있으면 True를 반환한다."""
    assert _has_answer_payload({"correct_answer": "2", "explanation": "설명입니다."}) is True


# ── _empty_answer → validate_node 실패 ───────────────────────────────────────

def test_empty_answer_fails_validate_node() -> None:
    """_empty_answer로 만든 문항은 validate_node가 실패로 분류한다."""
    from app.modules.ExamForge_V1.pipeline.nodes.validate_node import _check_single_structure
    q: dict = {
        "draft_id": "draft_x",
        "question_id": "q_x",
        "template_id": "ko_multiple_choice_4",
        "stem": "다음 중 선점 스케줄링은?",
        "options": [
            {"label": "1", "text": "FCFS", "is_correct": False},
            {"label": "2", "text": "RR", "is_correct": True},
            {"label": "3", "text": "SJF", "is_correct": False},
            {"label": "4", "text": "HRN", "is_correct": False},
        ],
        "correct_answer": "",
        "explanation": "",
        "source_reference": "",
        "difficulty": 3,
        "bloom_level": "이해",
        "topic": "스케줄링",
    }
    issues = _check_single_structure(q, "ko_multiple_choice_4")
    assert any("해설" in i or "정답" in i for i in issues), f"예상 이슈 없음: {issues}"


# ── P1: passed_partial total_questions 정합 ───────────────────────────────────

def test_coerce_exam_plan_partial_syncs_total_questions() -> None:
    """passed_partial 상태일 때 total_questions가 실제 문항 수로 조정된다."""
    state = {
        "exam_plan": {
            "exam_title": "테스트 모의고사",
            "subject": "운영체제",
            "total_questions": 5,
            "total_points": 5.0,
            "time_limit_minutes": 60,
            "locale": "ko",
            "category": "korean",
            "type_allocations": [],
            "topic_weights": {},
            "passing_score": 60.0,
            "bloom_distribution": {},
        },
        "pipeline_outcome": "passed_partial",
    }
    result = _coerce_exam_plan(state, question_count=4)
    # 실제 문항 4개이므로 선언수도 4로 조정돼야 한다
    assert result["total_questions"] == 4
    assert result["total_points"] == 4.0


def test_coerce_exam_plan_passed_keeps_original() -> None:
    """passed 상태에서는 total_questions를 원본(선언값)으로 유지한다."""
    state = {
        "exam_plan": {
            "exam_title": "테스트 모의고사",
            "subject": "운영체제",
            "total_questions": 5,
            "total_points": 5.0,
            "time_limit_minutes": 60,
            "locale": "ko",
            "category": "korean",
            "type_allocations": [],
            "topic_weights": {},
            "passing_score": 60.0,
            "bloom_distribution": {},
        },
        "pipeline_outcome": "passed",
    }
    result = _coerce_exam_plan(state, question_count=5)
    assert result["total_questions"] == 5


# ── codex 커넥터 --output-schema 플래그 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_answer_all_connector_errors_no_crash() -> None:
    """P1 회귀: 3회 connector.generate가 모두 예외(400 등)여도 resp unbound 크래시 없이
    graceful하게 빈 정답을 반환한다.
    """
    from app.modules.ExamForge_V1.pipeline.nodes import generate_answers_node as gan

    state = {
        "pipeline_status": "generating",
        "questions_with_distractors": [
            {
                "draft_id": "draft_err",
                "template_id": "ko_multiple_choice_4",
                "topic": "자료구조",
                "difficulty": 3,
                "bloom_level": "이해",
                "stem": "스택의 특성은?",
                "options": [
                    {"label": "1", "text": "FCFS", "is_correct": False},
                    {"label": "2", "text": "LIFO", "is_correct": True},
                    {"label": "3", "text": "FILO", "is_correct": False},
                    {"label": "4", "text": "LILO", "is_correct": False},
                ],
            }
        ],
        "source_text": "스택은 LIFO 구조다." * 10,
        "locale": "ko",
    }

    class _AlwaysErrorConnector:
        name = "codex_cli"

        async def generate(self, req: object) -> object:
            # 모든 호출이 400 류 예외를 던지는 상황 시뮬레이션
            raise RuntimeError("400 invalid_request")

        def supports(self, feature: str) -> bool:
            return False

    with patch.object(gan, "get_text_connector", return_value=_AlwaysErrorConnector()):
        # 크래시 없이 정상 반환돼야 한다 (resp unbound NameError 발생 금지)
        result = await gan.generate_answers_node(state)

    assert result["pipeline_status"] == "verifying"
    answered = result["answered_questions"]
    assert len(answered) == 1
    # 모든 호출이 실패했으므로 빈 정답 — 단 크래시는 없어야 한다
    assert answered[0]["explanation"] == ""
    assert answered[0]["correct_answer"] == ""


# (삭제됨) test_codex_connector_includes_output_schema_flag / test_codex_connector_no_schema_no_flag
# — _connector_codex.py가 커밋 7abc300(codex CLI 커넥터 제거)에서 삭제되어 함께 제거함.
# 아래 schema 파일 테스트는 codex_answer_gen.schema.json이 현존하므로 유지한다.


def test_codex_answer_schema_file_exists() -> None:
    """codex 정답 생성용 output-schema JSON 파일이 실제로 존재한다."""
    # tests/ → ExamForge_V1/ (parents[1]) → common/
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "common"
        / "codex_answer_gen.schema.json"
    )
    assert schema_path.exists(), f"스키마 파일 없음: {schema_path}"
    data = json.loads(schema_path.read_text())
    assert data.get("type") == "object"
    assert "correct_answer" in data.get("properties", {})
    assert "explanation" in data.get("properties", {})


def test_codex_answer_schema_is_openai_strict_compliant() -> None:
    """P0 회귀: OpenAI strict 모드(--output-schema)는 모든 property를 required에 +
    additionalProperties:false 를 요구한다. source_reference 누락 시 400을 유발하므로
    properties 키 집합 == required 집합 임을 강제한다.
    """
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "common"
        / "codex_answer_gen.schema.json"
    )
    data = json.loads(schema_path.read_text())
    # additionalProperties는 반드시 false
    assert data.get("additionalProperties") is False, "additionalProperties:false 필요"
    # 모든 property가 required에 포함돼야 한다 (OpenAI strict 규격)
    properties = set(data.get("properties", {}).keys())
    required = set(data.get("required", []))
    assert properties == required, (
        f"OpenAI strict 위반 — properties={properties}, required={required}. "
        "모든 property가 required에 있어야 한다."
    )
    # source_reference가 누락되지 않았는지 명시 확인 (이번 버그의 직접 원인)
    assert "source_reference" in required, "source_reference가 required에 누락됨"

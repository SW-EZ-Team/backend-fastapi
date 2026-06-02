"""모의고사 템플릿 계약 검증 테스트."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.modules.ExamForge_V1.app.main import app
from app.modules.ExamForge_V1.common.ai_bridge import ChapterAIRequest
from app.modules.ExamForge_V1.pipeline.nodes.generate_questions_node import _generate_chunk
from app.modules.ExamForge_V1.pipeline.nodes.generate_questions_node import _build_chunks
from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import apply_task_metadata
from app.modules.ExamForge_V1.pipeline.nodes.question_repair import build_repair_tasks, trim_to_missing_quota
from app.modules.ExamForge_V1.pipeline.nodes.format_output_node import _apply_plan_points
from app.modules.ExamForge_V1.pipeline.nodes.format_output_node import format_output_node
from app.modules.ExamForge_V1.pipeline.nodes.plan_exam_node import _normalize_plan
from app.modules.ExamForge_V1.pipeline.nodes.plan_exam_node import _build_fallback_plan
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import attach_source_code_if_needed
from app.modules.ExamForge_V1.pipeline.nodes.validate_node import validate_node
from app.modules.ExamForge_V1.templates.catalog import (
    allocation_contract,
    get_template_spec,
    template_contract,
    template_options,
)
from app.modules.ExamForge_V1.templates.registry import list_templates


class _FakeResponse:
    """생성기 더블 응답."""

    text: str

    def __init__(self, text: str) -> None:
        self.text = text


class _CaptureConnector:
    """문항 생성 프롬프트를 캡처하는 테스트 커넥터."""

    last_user: str = ""

    async def generate(self, req: ChapterAIRequest) -> _FakeResponse:
        """요청 프롬프트를 기록하고 최소 JSON 응답을 반환한다."""
        self.last_user = req.user
        return _FakeResponse(
            """
            [
              {
                "stem": "러스트 소유권의 핵심 목적은 무엇인가?",
	                "topic": "Rust",
	                "difficulty": 3,
	                "bloom_level": "이해",
	                "code_snippet": "fn main() { let x = 1; }",
	                "options": [
                  {"label": "1", "text": "메모리 안전성 확보", "is_correct": true},
                  {"label": "2", "text": "동적 타입 변환", "is_correct": false},
                  {"label": "3", "text": "런타임 GC 강제", "is_correct": false},
                  {"label": "4", "text": "전역 상태 공유", "is_correct": false},
                  {"label": "5", "text": "컴파일 생략", "is_correct": false}
                ]
              }
            ]
            """
        )


class _RetryConnector:
    """깨진 JSON 후 정상 JSON을 반환하는 테스트 커넥터."""

    prompts: list[str]

    def __init__(self) -> None:
        self.prompts = []

    async def generate(self, req: ChapterAIRequest) -> _FakeResponse:
        """첫 호출은 깨진 응답, 두 번째 호출은 정상 응답을 반환한다."""
        self.prompts.append(req.user)
        if len(self.prompts) == 1:
            return _FakeResponse('[{"stem": "깨진')
        return _FakeResponse(
            '[{"stem":"Rust move 결과는?","topic":"Rust","difficulty":3,'
            '"bloom_level":"적용","options":['
            '{"label":"1","text":"소유권 이동","is_correct":true},'
            '{"label":"2","text":"GC 실행","is_correct":false},'
            '{"label":"3","text":"암시적 복사","is_correct":false},'
            '{"label":"4","text":"타입 삭제","is_correct":false},'
            '{"label":"5","text":"스레드 생성","is_correct":false}]}]'
        )


class _RouteGraph:
    """HTTP 라우트 계약 검증용 파이프라인 더블."""

    async def ainvoke(self, state: dict) -> dict:
        """FastAPI 라우터가 응답 스키마로 변환할 수 있는 완료 상태를 반환한다."""
        plan = {
            "exam_title": "Rust 실전 모의고사",
            "subject": state["subject"],
            "total_questions": 5,
            "total_points": 5.0,
            "time_limit_minutes": 30,
            "locale": state["locale"],
            "category": state["category"],
            "type_allocations": [{
                "template_id": "ko_short_answer",
                "count": 5,
                "difficulty_distribution": {3: 5},
                "points_per_question": 1.0,
            }],
            "topic_weights": {"소유권": 1.0},
            "passing_score": 60.0,
            "bloom_distribution": {"이해": 1.0},
        }
        return {
            **state,
            "pipeline_status": "complete",
            "pipeline_outcome": "passed",
            "exam_plan": plan,
            "calibrated_questions": [{
                "question_id": "q1",
                "draft_id": "d1",
                "template_id": "ko_short_answer",
                "topic": "소유권",
                "difficulty": 3,
                "bloom_level": "이해",
                "stem": "Rust 소유권의 핵심 목적은 무엇인가?",
                "correct_answer": "메모리 안전성",
                "explanation": "소유권은 컴파일 타임에 메모리 안전성을 보장한다.",
                "source_reference": "소유권 규칙",
                "points": 1.0,
            }],
            "quality_metrics": {
                "answer_accuracy_rate": 1.0,
                "dedup_score": 1.0,
                "coverage_score": 1.0,
                "distractor_plausibility_score": 1.0,
                "length_variance_ratio": 0.0,
                "bloom_distribution_actual": {"이해": 1.0},
                "retry_count": 0,
                "generation_time_sec": 0.01,
            },
            "output_html": "<main>시험지</main>",
            "answers_html": "<main>정답지</main>",
        }


def test_catalog_covers_every_registered_template() -> None:
    """등록된 모든 템플릿에 렌더링/생성 계약이 존재한다."""
    for template in list_templates():
        spec = get_template_spec(template.template_id)
        assert spec.template_id == template.template_id
        assert spec.display_name
        assert spec.render_layout
        assert spec.must_have
        assert spec.prompt_contract


def test_template_contract_is_prompt_ready() -> None:
    """단일 템플릿 계약이 LLM 프롬프트에 넣을 수 있는 형태다."""
    contract = template_contract("ko_multiple_choice_5")
    assert "template_id: ko_multiple_choice_5" in contract
    assert "보기 정확히 5개" in contract
    assert "렌더링: choice-list" in contract
    assert "[실전 시험지 틀]" in contract
    assert "답안란: omr-5" in contract


def test_us_template_contract_is_prompt_ready_in_english() -> None:
    """영문 템플릿 계약은 실전 시험지 지시문까지 영어로 제공한다."""
    contract = template_contract("us_multiple_choice_4")

    assert "Display name" in contract
    assert "Student action" in contract
    assert "[Real exam paper frame]" in contract
    assert "Answer area: omr-4" in contract
    assert "문항" not in contract
    assert "정답" not in contract


def test_allocation_contract_restricts_template_ids() -> None:
    """계획 노드용 계약이 선택 템플릿만 쓰도록 지시한다."""
    contract = allocation_contract(["ko_short_answer", "ko_ordering"])
    assert "ko_short_answer" in contract
    assert "ko_ordering" in contract
    assert "total_questions" in contract
    assert "type_allocations" in contract


def test_template_options_are_api_ready() -> None:
    """HTML 테스트 페이지가 바로 사용할 옵션 구조를 반환한다."""
    options = template_options()
    assert len(options) >= 20
    assert {"template_id", "answer_mode", "render_layout"} <= set(options[0])
    assert {"paper_section", "question_frame", "answer_frame"} <= set(options[0])


def test_templates_endpoint_returns_contract_fields() -> None:
    """템플릿 API가 UI용 계약 필드를 함께 반환한다."""
    client = TestClient(app)
    response = client.get("/api/exam-forge/templates?locale=ko")
    assert response.status_code == 200
    data = response.json()
    assert data
    assert {"answer_mode", "render_layout", "student_action"} <= set(data[0])
    assert {"paper_section", "paper_instruction", "scoring_rule"} <= set(data[0])


def test_paper_templates_endpoint_returns_real_exam_frames() -> None:
    """시험지 기본 틀 API가 실전 렌더링 후보를 반환한다."""
    client = TestClient(app)
    response = client.get("/api/exam-forge/paper-templates")
    assert response.status_code == 200
    data = response.json()
    assert {item["paper_id"] for item in data} >= {
        "ko_standard_mock_exam",
        "ko_professional_cert_exam",
        "us_standard_mock_exam",
    }
    assert "수험번호" in data[0]["examinee_fields"]


def test_exam_forge_health_endpoint_is_exposed() -> None:
    """ExamForge 라우터 헬스체크가 HTTP 레벨에서 응답한다."""
    client = TestClient(app)

    assert client.get("/api/exam-forge/health").json() == {
        "status": "ok",
        "service": "exam-forge",
    }


def test_generate_endpoint_returns_exam_contract() -> None:
    """생성 라우트가 TestClient 경유로 응답 스키마 계약을 지킨다."""
    client = TestClient(app)
    payload = {
        "source_text": "Rust는 소유권과 빌림 규칙으로 메모리 안전성을 보장한다. " * 5,
        "subject": "Rust",
        "exam_config": {
            "total_questions": 5,
            "time_limit_minutes": 30,
            "locale": "ko",
            "category": "korean",
            "question_types": ["ko_short_answer"],
            "difficulty_distribution": {"3": 1.0},
            "passing_score": 60.0,
            "include_explanations": True,
        },
    }

    with patch(
        "app.modules.ExamForge_V1.pipeline.graph.get_compiled_graph",
        return_value=_RouteGraph(),
    ):
        response = client.post("/api/exam-forge/generate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["pipeline_outcome"] == "passed"
    assert data["exam_plan"]["exam_title"] == "Rust 실전 모의고사"
    assert data["questions"][0]["template_id"] == "ko_short_answer"
    assert data["exam_html"] == "<main>시험지</main>"


def test_fallback_plan_preserves_requested_total() -> None:
    """AI 계획 실패 시에도 문항 수 합계가 요청값과 일치한다."""
    plan = _build_fallback_plan(
        subject="Rust",
        total=11,
        config={
            "question_types": [
                "ko_multiple_choice_5",
                "ko_short_answer",
                "ko_ordering",
            ],
        },
        topics=[{"name": "소유권", "importance": 1.0}],
    )
    total = sum(a["count"] for a in plan["type_allocations"])
    assert total == 11


def test_fallback_plan_uses_default_when_question_types_empty() -> None:
    """직접 state에 빈 유형 목록이 들어와도 기본 객관식으로 수렴한다."""
    plan = _build_fallback_plan(
        subject="Rust",
        total=5,
        config={"question_types": []},
        topics=[{"name": "소유권", "importance": 1.0}],
    )

    assert sum(a["count"] for a in plan["type_allocations"]) == 5
    assert plan["type_allocations"][0]["template_id"] == "ko_multiple_choice_5"


def test_generation_chunks_rotate_topics() -> None:
    """작은 시험에서도 한 주제에만 몰리지 않도록 청크 주제를 순환한다."""
    chunks = _build_chunks(
        allocations=[{
            "template_id": "ko_multiple_choice_5",
            "difficulty_distribution": {3: 5},
        }],
        topic_weights={"소유권": 0.4, "빌림": 0.3, "Result": 0.3},
    )
    topics = [chunk["topic"] for chunk in chunks]
    assert topics[:3] == ["소유권", "빌림", "Result"]


def test_generation_chunks_use_blueprint_concepts() -> None:
    """blueprint가 있으면 청크가 강의·개념 메타데이터를 갖는다."""
    chunks = _build_chunks(
        allocations=[{
            "template_id": "ko_multiple_choice_5",
            "difficulty_distribution": {3: 1},
        }],
        topic_weights={"정수": 1.0},
        blueprint=[{
            "slot": 1,
            "chapter": "1강 정수",
            "topic": "절댓값",
            "concept": "절댓값과 대소비교",
            "difficulty": 3,
            "reasoning_type": "2단계 계산/비교",
        }],
    )
    assert chunks[0]["topic"] == "절댓값"
    assert chunks[0]["_concept_key"] == "1강 정수::절댓값과 대소비교"
    assert chunks[0]["_reasoning_type"] == "2단계 계산/비교"


def test_task_metadata_overrides_llm_difficulty() -> None:
    """LLM이 난이도/블룸을 흔들어도 청크 계약을 우선한다."""
    draft = {"difficulty": 1, "bloom_level": "기억", "stem": "문제"}
    result = apply_task_metadata(draft, {"difficulty": 4})
    assert result["difficulty"] == 4
    assert result["bloom_level"] == "분석"


def test_plan_topics_trimmed_to_question_count() -> None:
    """문항 수보다 많은 계획 주제는 커버리지 계산 전에 줄인다."""
    plan = {
        "total_questions": 3,
        "topic_weights": {
            "A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1,
        },
    }
    normalized = _normalize_plan(plan, {"total_questions": 3})
    assert list(normalized["topic_weights"]) == ["A", "B", "C"]
    assert sum(normalized["topic_weights"].values()) == pytest.approx(1.0)


def test_plan_bloom_distribution_matches_allocations() -> None:
    """작은 시험 계획은 실제 난이도 배분과 블룸 분포를 일치시킨다."""
    plan = {
        "total_questions": 3,
        "topic_weights": {"A": 1.0},
        "type_allocations": [{
            "template_id": "ko_multiple_choice_5",
            "count": 3,
            "difficulty_distribution": {2: 1, 3: 1, 4: 1},
        }],
        "bloom_distribution": {"평가": 1.0},
    }
    normalized = _normalize_plan(plan, {"total_questions": 3})
    assert normalized["bloom_distribution"] == {
        "이해": pytest.approx(1 / 3),
        "적용": pytest.approx(1 / 3),
        "분석": pytest.approx(1 / 3),
    }


def test_normalize_plan_adds_blueprint_and_reasoning_quota() -> None:
    """계획 정규화가 개념 blueprint와 2단계 추론 비중을 보강한다."""
    plan = {
        "total_questions": 5,
        "topic_weights": {"정수": 1.0},
        "type_allocations": [{
            "template_id": "ko_multiple_choice_5",
            "count": 5,
            "difficulty_distribution": {1: 5},
        }],
    }
    topics = [{
        "name": "정수",
        "chapter": "1강",
        "importance": 1.0,
        "sub_concepts": ["절댓값", "대소비교", "사칙연산"],
    }]
    normalized = _normalize_plan(plan, {"total_questions": 5}, topics)
    high_count = sum(
        count
        for diff, count in normalized["type_allocations"][0]["difficulty_distribution"].items()
        if int(diff) >= 3
    )
    assert high_count >= 2
    assert len(normalized["question_blueprint"]) == 5
    assert normalized["question_blueprint"][0]["chapter"] == "1강"


def test_repair_tasks_fill_missing_by_template() -> None:
    """계획 대비 부족한 템플릿 수량만 보충 청크로 만든다."""
    tasks = build_repair_tasks(
        allocations=[
            {"template_id": "ko_multiple_choice_5", "count": 3,
             "difficulty_distribution": {3: 3}},
            {"template_id": "ko_short_answer", "count": 2,
             "difficulty_distribution": {2: 2}},
        ],
        topic_weights={"소유권": 0.5, "빌림": 0.5},
        existing_drafts=[
            {"template_id": "ko_multiple_choice_5"},
            {"template_id": "ko_short_answer"},
        ],
    )
    assert [task["template_id"] for task in tasks].count("ko_multiple_choice_5") == 2
    assert [task["template_id"] for task in tasks].count("ko_short_answer") == 1


def test_repair_result_is_trimmed_to_quota() -> None:
    """보충 생성이 초과해도 목표 수량을 넘기지 않는다."""
    repaired = trim_to_missing_quota(
        allocations=[{"template_id": "ko_short_answer", "count": 2}],
        existing_drafts=[{"template_id": "ko_short_answer"}],
        repaired_drafts=[
            {"template_id": "ko_short_answer", "stem": "A"},
            {"template_id": "ko_short_answer", "stem": "B"},
        ],
    )
    assert len(repaired) == 1
    assert repaired[0]["stem"] == "A"


def test_format_output_applies_plan_points() -> None:
    """시험 계획의 문항당 배점이 실제 문항에 반영된다."""
    questions = [{"template_id": "ko_multiple_choice_5", "points": 1.0}]
    plan = {
        "type_allocations": [
            {"template_id": "ko_multiple_choice_5", "points_per_question": 20.0}
        ]
    }
    adjusted = _apply_plan_points(questions, plan)
    assert adjusted[0]["points"] == 20.0
    assert questions[0]["points"] == 1.0


async def test_low_topic_coverage_fails_quality_gate() -> None:
    """문항 수가 맞아도 주제 커버리지가 낮으면 품질 게이트에서 실패한다."""
    state = {
        "calibrated_questions": [
            {"question_id": f"q{i}", "draft_id": f"d{i}",
             "template_id": "ko_short_answer", "topic": "소유권",
             "difficulty": 3, "bloom_level": "이해", "stem": f"문제{i}",
             "correct_answer": "정답", "explanation": "해설"}
            for i in range(5)
        ],
        "exam_plan": {
            "topic_weights": {"소유권": 0.2, "빌림": 0.4, "Result": 0.4},
            "type_allocations": [
                {"template_id": "ko_short_answer", "points_per_question": 20.0}
            ],
        },
        "exam_config": {"total_questions": 5},
        "retry_count": 0,
        "max_retries": 3,
        "failed_question_ids": [],
        "timings": {"start": 0},
    }
    result = await format_output_node(state)
    assert result["pipeline_outcome"] == "failed_quality_gate"
    assert "커버리지" in result["error_message"]


async def test_stale_failed_ids_do_not_force_exhausted() -> None:
    """최신 검증 리포트가 통과면 이전 실패 ID만으로 exhausted 처리하지 않는다."""
    state = {
        "calibrated_questions": [
            {"question_id": "q1", "draft_id": "d1",
             "template_id": "ko_short_answer", "topic": "소유권",
             "difficulty": 3, "bloom_level": "이해", "stem": "문제",
             "correct_answer": "정답", "explanation": "해설"}
        ],
        "exam_plan": {
            "topic_weights": {"소유권": 1.0},
            "type_allocations": [
                {"template_id": "ko_short_answer", "points_per_question": 20.0}
            ],
        },
        "exam_config": {"total_questions": 1},
        "retry_count": 0,
        "max_retries": 0,
        "failed_question_ids": ["stale"],
        "validation_report": {
            "results": [{"question_id": "q1", "passed": True, "issues": []}]
        },
        "timings": {"start": 0},
    }
    result = await format_output_node(state)
    assert result["pipeline_outcome"] == "passed"


async def test_format_output_strips_cjk_from_final_questions_and_html() -> None:
    """최종 API/HTML 노출 전에 발문과 해설의 CJK 잔존을 제거한다."""
    state = {
        "calibrated_questions": [
            {"question_id": "q1", "draft_id": "d1",
             "template_id": "ko_short_answer", "topic": "정렬",
             "difficulty": 3, "bloom_level": "이해", "stem": "순서가 颠倒되면?",
             "correct_answer": "정렬", "explanation": "颠倒了 상태는 순서를 바로잡아야 한다."}
        ],
        "exam_plan": {"topic_weights": {"정렬": 1.0}},
        "exam_config": {"total_questions": 1},
        "retry_count": 0,
        "max_retries": 0,
        "failed_question_ids": [],
        "validation_report": {
            "results": [{"question_id": "q1", "passed": True, "issues": []}]
        },
        "timings": {"start": 0},
    }

    result = await format_output_node(state)

    assert "颠倒" not in result["calibrated_questions"][0]["stem"]
    assert "颠倒了" not in result["calibrated_questions"][0]["explanation"]
    assert "颠倒" not in result["output_html"]
    assert "颠倒了" not in result["answers_html"]


async def test_programming_output_without_code_fails_gate() -> None:
    """Rust 같은 코드 과목은 코드 예제 문항이 없으면 최종 게이트에서 막힌다."""
    state = {
        "source_text": "Rust의 fn main, let, match, trait 사용법을 평가한다.",
        "calibrated_questions": [
            {"question_id": "q1", "draft_id": "d1",
             "template_id": "ko_short_answer", "topic": "소유권",
             "difficulty": 3, "bloom_level": "이해", "stem": "소유권은?",
             "correct_answer": "소유자", "explanation": "값의 소유자를 묻는다."}
        ],
        "exam_plan": {"topic_weights": {"소유권": 1.0}},
        "exam_config": {"total_questions": 1},
        "retry_count": 0,
        "max_retries": 0,
        "failed_question_ids": [],
        "validation_report": {
            "results": [{"question_id": "q1", "passed": True, "issues": []}]
        },
        "timings": {"start": 0},
    }
    result = await format_output_node(state)
    assert result["pipeline_outcome"] == "failed_quality_gate"
    assert "코드 예제" in result["error_message"]


async def test_validate_retries_programming_exam_without_code() -> None:
    """검증 단계에서 코드 예제 누락을 재시도 대상으로 표시한다."""
    state = {
        "source_text": "Rust는 fn main과 match 표현식으로 흐름을 제어한다.",
        "verified_questions": [
            {"question_id": "q1", "draft_id": "d1",
             "template_id": "ko_short_answer", "topic": "match",
             "difficulty": 3, "bloom_level": "적용", "stem": "match는?",
             "correct_answer": "분기", "explanation": "패턴별 분기 처리"}
        ],
        "exam_plan": {"topic_weights": {"match": 1.0}},
    }
    result = await validate_node(state)
    assert result["failed_question_ids"] == ["d1"]
    assert "code_snippet" in result["validation_report"]["global_issues"][0]


def test_generation_prompt_includes_template_contract() -> None:
    """문항 생성 노드가 실제 생성 프롬프트에 템플릿 계약을 덧붙인다."""
    connector = _CaptureConnector()
    result = asyncio.run(
        _generate_chunk(
            task={
                "template_id": "ko_multiple_choice_5",
                "topic": "Rust",
                "difficulty": 3,
                "count": 1,
                "_blueprint_slot": 1,
                "_chapter": "1강 Rust",
                "_concept_key": "1강 Rust::소유권 이동",
                "_reasoning_type": "2단계 적용 추론",
            },
            connector=connector,
            source_text="Rust는 소유권과 빌림 규칙으로 메모리 안전성을 보장한다.",
            locale="ko",
            semaphore=asyncio.Semaphore(1),
        )
    )
    assert result
    assert "[템플릿 계약]" in connector.last_user
    assert "[문항 blueprint 계약]" in connector.last_user
    assert "2단계 적용 추론" in connector.last_user
    assert "보기 정확히 5개" in connector.last_user
    assert "코드 예제의 결과" in connector.last_user
    assert '"code_snippet"' not in connector.last_user
    assert result[0]["code_snippet"].startswith("fn main")


def test_generation_chunk_retries_broken_json() -> None:
    """문항 생성 JSON이 깨지면 같은 청크를 strict 계약으로 한 번 재호출한다."""
    connector = _RetryConnector()
    result = asyncio.run(
        _generate_chunk(
            task={"template_id": "ko_multiple_choice_5", "topic": "Rust",
                  "difficulty": 3, "count": 1},
            connector=connector,
            source_text="Rust는 move 후 이전 변수를 사용할 수 없다.",
            locale="ko",
            semaphore=asyncio.Semaphore(1),
        )
    )
    assert result[0]["stem"] == "Rust move 결과는?"
    assert len(connector.prompts) == 2
    assert "[JSON 재출력 강제]" in connector.prompts[1]


def test_programming_code_is_attached_from_source_when_model_omits_it() -> None:
    """모델이 code_snippet을 비워도 원본 코드 예제를 안전하게 첨부한다."""
    questions = [{"stem": "move 이후 변수 사용은?", "template_id": "ko_short_answer"}]
    source = "설명\nfn main() {\n    let name = String::from(\"rust\");\n    let moved = name;\n}\n\n끝"
    enriched = attach_source_code_if_needed(questions, source)
    assert enriched[0]["code_snippet"].startswith("fn main")
    assert "String::from" in enriched[0]["code_snippet"]
    assert "code_snippet" not in questions[0]

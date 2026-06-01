"""ExamForge 파이프라인 상태."""
from __future__ import annotations

from typing import NotRequired, TypedDict


class ValidationResult(TypedDict):
    """개별 문제 검증 결과."""

    question_id: str
    passed: bool
    issues: list[str]
    # validate_node가 항상 생성하지 않으므로 선택 필드로 선언
    fix_instructions: NotRequired[str]
    retry_count: NotRequired[int]


class ValidationReport(TypedDict):
    """전체 검증 보고서."""

    results: list[ValidationResult]
    global_issues: list[str]
    coverage_score: float
    dedup_score: float
    answer_accuracy_rate: float


class ExamForgeState(TypedDict, total=False):
    """LangGraph 파이프라인 전체 상태.

    pipeline_status 값:
        - (없음)        : 아직 시작 전
        - "planning"     : 시험 계획 수립 중
        - "generating"   : 문제 생성 중
        - "distractors"  : 오답 생성 중
        - "answering"    : 정답/해설 생성 중
        - "verifying"    : 교차 검증 중
        - "validating"   : 구조 검증 중
        - "calibrating"  : 난이도 보정 중
        - "formatting"   : 최종 출력 생성 중
        - "complete"     : 전체 파이프라인 정상 완료
        - "partial"      : 일부 문제 누락, 나머지는 사용 가능 (passed_partial)
        - "failed"       : 품질 미달 또는 재시도 소진 (failed_*/exhausted)
        - "error"        : 인프라 오류로 진행 불가 — 하위 노드 즉시 반환

    pipeline_outcome 값:
        - "passed"                   : 품질 검증 통과, 정상 완료
        - "passed_partial"           : 일부 문제 제외 후 통과
        - "exhausted"                : 최대 재시도 소진, 최선 결과 반환
        - "failed_minimum_threshold" : 최소 문제 수 미달
        - "failed_quality_gate"      : 품질 게이트 미통과
    """

    # 입력
    source_text: str
    exam_config: dict
    locale: str
    category: str
    subject: str
    exam_id: str

    # parse_source 출력
    topics: list[dict]
    concept_graph: dict

    # plan_exam 출력
    exam_plan: dict

    # generate_questions 출력
    questions: list[dict]
    source_truncated: bool

    # generate_distractors 출력
    questions_with_distractors: list[dict]

    # generate_answers 출력
    answered_questions: list[dict]

    # verify_answers 출력
    verified_questions: list[dict]
    verification_failures: list[str]

    # validate 출력
    validation_report: dict
    failed_question_ids: list[str]

    # 제어
    retry_count: int
    max_retries: int
    pipeline_status: str
    error_message: str | None
    # repair_questions 노드가 표적 교정을 적용했는지 여부.
    # True면 재검증(verify) 경로로, False면 기존 blind 재생성 경로로 라우팅한다.
    repair_applied: bool
    # LLM 호출 예산 서킷 브레이커 (P0 DoS 방지)
    llm_call_count: int
    llm_budget_exceeded: bool

    # calibrate 출력
    calibrated_questions: list[dict]

    # format_output 출력
    output_html: str | None
    answers_html: str | None
    output_json: dict | None
    quality_metrics: dict
    timings: dict
    # 파이프라인 종료 사유 — 상단 docstring 참조
    pipeline_outcome: str

"""ExamForge_V1 전용 Spring 콜백 원자적 모듈.

비동기 모의고사 생성 결과를 Spring /internal/exam-attempts/{attempt_id}/generated 로
전달하고, 실패 시 /internal/exam-attempts/{attempt_id}/generation-failed 로 통보한다.

AssignmentGrader_V1.spring_callback 과 완전히 분리된 독립 파일이다.
두 모듈은 서로 import 하지 않는다.

IN : attempt_id, exam_id, answer_key_seal, questions(list[dict])
OUT: 없음 (실패 시 MockGenerationCallbackError raise)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

_LOG = logging.getLogger(__name__)

# Spring 콜백 전송 타임아웃(초) — 환경변수로 조정 가능
_CALLBACK_TIMEOUT_SEC = int(os.getenv("EXAM_FORGE_CALLBACK_TIMEOUT_SECONDS", "15"))


class MockGenerationCallbackError(RuntimeError):
    """Spring 모의고사 생성 콜백 전송 실패를 정규화한다."""


def _get_spring_base_url() -> str:
    """Spring Boot 베이스 URL — 환경변수 SPRING_BASE_URL에서 읽는다."""
    return os.getenv("SPRING_BASE_URL", "http://localhost:8080/api").rstrip("/")


def _get_internal_token() -> str:
    """Spring X-Internal-Token 헤더 값 — APP_INTERNAL_TOKEN 환경변수에서 읽는다."""
    return os.getenv("APP_INTERNAL_TOKEN", "local-dev-token")


def send_generation_success_callback(
    attempt_id: str,
    exam_id: str,
    answer_key_seal: str,
    questions: list[dict],
) -> None:
    """Spring /internal/exam-attempts/{attempt_id}/generated 에 생성 완료를 동기 POST 한다.

    Spring 측 DTO와 정확히 일치하는 필드를 전송한다:
    - exam_id, answer_key_seal: 시험 식별자 및 무결성 봉인값
    - questions: 각 문항의 question_id, template_id, display_order, stem,
                 options, points, correct_answer, explanation,
                 source_reference, grading_metadata

    questions 리스트는 ExamForge Question 모델 dict 형태를 그대로 수신한다.
    Spring이 필요한 필드만 전달하고 나머지는 정보 손실 없이 grading_metadata에 담는다.
    """
    base_url = _get_spring_base_url()
    token = _get_internal_token()
    url = f"{base_url}/internal/exam-attempts/{attempt_id}/generated"

    # Spring DTO 계약에 맞게 questions 리스트를 변환한다
    spring_questions = [_to_spring_question(idx, q) for idx, q in enumerate(questions)]

    # Spring 콜백 전송 전 필수 식별자 무결성 검증.
    # templateId 또는 questionId가 빈값(공백 포함)이면 Spring이 VALIDATION_001로 거부한다.
    # 근본 수정(format_output_node의 _drop_invalid_questions)에서 이미 차단하지만,
    # 콜백 경계에서 2차 방어선으로 .strip() 기반 검증을 유지한다.
    # camelCase 키를 사용해야 _to_spring_question 변환 결과와 일치한다.
    invalid_orders: list[str] = []
    for sq in spring_questions:
        order = sq.get("displayOrder", "?")
        if not str(sq.get("templateId") or "").strip():
            invalid_orders.append(f"displayOrder={order}(templateId 없음)")
        elif not str(sq.get("questionId") or "").strip():
            invalid_orders.append(f"displayOrder={order}(questionId 없음)")
    if invalid_orders:
        _LOG.error(
            "[MockGenCallback] 식별자 누락 문항 발견 — %s, attemptId=%s",
            invalid_orders,
            attempt_id,
        )
        raise MockGenerationCallbackError(
            f"식별자 누락 문항 {invalid_orders} — Spring 콜백 전송 중단"
        )

    # Spring GenerationCompletedCallbackRequest는 camelCase Jackson 역직렬화.
    # examId, answerKeySeal, questions 키를 사용한다.
    payload = {
        "examId": exam_id,
        "answerKeySeal": answer_key_seal,
        "questions": spring_questions,
    }

    _post_to_spring(url, token, payload)
    _LOG.info(
        "[MockGenCallback] 생성 완료 콜백 전송 | attemptId=%s, examId=%s, 문항=%d개",
        attempt_id,
        exam_id,
        len(spring_questions),
    )


def send_generation_failed_callback(attempt_id: str, reason: str) -> None:
    """Spring /internal/exam-attempts/{attempt_id}/generation-failed 에 실패를 동기 POST 한다.

    생성 파이프라인에서 예외가 발생하거나 결과가 없을 때 호출한다.
    Spring 측은 이 콜백으로 시도(attempt) 상태를 FAILED로 전이한다.
    """
    base_url = _get_spring_base_url()
    token = _get_internal_token()
    url = f"{base_url}/internal/exam-attempts/{attempt_id}/generation-failed"

    payload = {"reason": reason}
    _post_to_spring(url, token, payload)
    _LOG.info(
        "[MockGenCallback] 생성 실패 콜백 전송 | attemptId=%s, reason=%s",
        attempt_id,
        reason,
    )


def _to_spring_question(display_order: int, q: dict) -> dict:
    """ExamForge Question dict를 Spring DTO 계약 형태(camelCase)로 변환한다.

    Spring GenerationCallbackQuestionRequest는 Jackson 기본 camelCase 역직렬화를 사용하므로
    모든 키를 camelCase로 전송해야 한다. snake_case 키는 Spring이 무시해 null이 된다.

    Spring 필드:
      questionId, templateId, displayOrder, stem, options,
      points, correctAnswer, explanation, sourceReference, gradingMetadata
    """
    # options는 QuestionOption 형태(label, text, is_correct) 리스트가 올 수 있다.
    # isCorrect도 camelCase로 전송한다.
    raw_options = q.get("options") or []
    spring_options = [
        {
            "label": opt.get("label", ""),
            "text": opt.get("text", ""),
            "isCorrect": opt.get("is_correct", False),
        }
        for opt in raw_options
    ]

    # Spring이 채점 시 필요로 하는 메타데이터를 gradingMetadata에 포함한다
    grading_metadata: dict = {}
    for key in (
        "matching_pairs",
        "ordering_items",
        "correct_ordering",
        "blank_positions",
        "blank_answers",
        "code_snippet",
        "distractor_rationale",
        "bloom_level",
        "topic",
        "difficulty",
    ):
        value = q.get(key)
        if value is not None:
            grading_metadata[key] = value

    return {
        "questionId": q.get("question_id", ""),
        "templateId": q.get("template_id", ""),
        "displayOrder": display_order + 1,  # 1-based 순서
        "stem": q.get("stem", ""),
        "options": spring_options,
        "points": q.get("points", 1.0),
        "correctAnswer": q.get("correct_answer", ""),
        "explanation": q.get("explanation", ""),
        "sourceReference": q.get("source_reference", ""),
        "gradingMetadata": grading_metadata,
    }


def _post_to_spring(url: str, token: str, payload: dict) -> None:
    """Spring 내부 엔드포인트에 X-Internal-Token 인증으로 JSON POST 한다.

    HTTP 오류 및 연결 실패는 MockGenerationCallbackError 로 정규화한다.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Internal-Token": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_CALLBACK_TIMEOUT_SEC) as response:
            _ = response.read()
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")[:300]
        raise MockGenerationCallbackError(
            f"Spring 모의고사 생성 콜백 HTTP 오류 (status={exc.code}): {raw_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise MockGenerationCallbackError(
            f"Spring 모의고사 생성 콜백 연결 실패: {exc.reason}"
        ) from exc

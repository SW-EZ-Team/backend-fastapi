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
import time
import urllib.error
import urllib.request

_LOG = logging.getLogger(__name__)

# Spring 콜백 전송 타임아웃(초) — 환경변수로 조정 가능
_CALLBACK_TIMEOUT_SEC = int(os.getenv("EXAM_FORGE_CALLBACK_TIMEOUT_SECONDS", "15"))

# 재시도 백오프 지연(초) — 연결 실패·5xx·404(Spring attempt 커밋 전 레이스) 대응.
# 404 재시도 근거: FastAPI 생성이 매우 빠르면 Spring의 attempt INSERT 트랜잭션이
# 커밋되기 전에 콜백이 도착해 ATTEMPT_NOT_FOUND(404)가 발생할 수 있다.
_RETRY_DELAYS_SEC = (0.5, 1.0, 2.0, 4.0, 8.0)
# 5xx 외에 재시도 대상으로 추가하는 HTTP 상태 코드
_RETRYABLE_EXTRA_STATUS = frozenset({404})


class MockGenerationCallbackError(RuntimeError):
    """Spring 모의고사 생성 콜백 전송 실패를 정규화한다."""


def _get_spring_base_url() -> str:
    """Spring Boot 베이스 URL — 환경변수 SPRING_BASE_URL에서 읽는다.

    미설정이면 로컬 개발 기본값을 쓴다(기존 동작 보존). 빈 문자열/스킴 누락은
    재시도해도 결과가 같은 영구 설정 오류이므로, 백오프 재시도 루프에 들어가기 전에
    명확한 에러로 즉시 실패한다(재시도 폭주 방지).
    """
    raw = os.getenv("SPRING_BASE_URL")
    if raw is None:
        return "http://localhost:8080/api"
    base = raw.strip().rstrip("/")
    if not base or not base.startswith(("http://", "https://")):
        raise MockGenerationCallbackError(
            f"SPRING_BASE_URL 설정이 비었거나 형식이 잘못됐다(재시도 없이 즉시 실패): {raw!r}"
        )
    return base


def _get_internal_token() -> str:
    """Spring X-Internal-Token 헤더 값 — APP_INTERNAL_TOKEN 환경변수에서 읽는다."""
    return os.getenv("APP_INTERNAL_TOKEN", "local-dev-token")


def send_generation_success_callback(
    attempt_id: str,
    exam_id: str,
    answer_key_seal: str,
    questions: list[dict],
    grounding_degraded: bool = False,
    requested_question_count: int | None = None,
    actual_question_count: int | None = None,
    generation_outcome: str | None = None,
) -> None:
    """Spring /internal/exam-attempts/{attempt_id}/generated 에 생성 완료를 동기 POST 한다.

    Spring 측 DTO와 정확히 일치하는 필드를 전송한다:
    - exam_id, answer_key_seal: 시험 식별자 및 무결성 봉인값
    - questions: 각 문항의 question_id, template_id, display_order, stem,
                 options, points, correct_answer, explanation,
                 source_reference, grading_metadata

    questions 리스트는 ExamForge Question 모델 dict 형태를 그대로 수신한다.
    Spring이 필요한 필드만 전달하고 나머지는 정보 손실 없이 grading_metadata에 담는다.

    grounding_degraded=True 이면 course 본문 grounding 실패로 일반론 출제된 시험이다.
    payload에 groundingDegraded 키로 함께 실어 상위(Spring)가 인지할 수 있게 한다.
    Spring DTO에 해당 필드가 없어도 Jackson ignoreUnknown(Spring Boot 기본값)으로
    무해하게 무시되므로 콜백 호환성을 깨지 않는다(부가 정보, 비파괴적).

    requested_question_count / actual_question_count / generation_outcome 는
    "요청 N문항 / 실제 생성 M문항"과 생성 결과(passed/passed_partial/needs_more_source/
    exhausted)를 Spring이 사용자에게 표기·안내하기 위한 부가 정보다. None이면 payload에서
    생략하며, 값이 있으면 camelCase(requestedQuestionCount/actualQuestionCount/
    generationOutcome) 키로 싣는다. 역시 Spring DTO에 없어도 무해하게 무시된다(비파괴적).
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
    # groundingDegraded는 부가 추적 정보 — Spring DTO에 없으면 무해하게 무시된다.
    payload: dict = {
        "examId": exam_id,
        "answerKeySeal": answer_key_seal,
        "questions": spring_questions,
        "groundingDegraded": grounding_degraded,
    }
    # 요청/생성 문항 수와 생성 outcome — 값이 있을 때만 싣는다(비파괴적).
    # None이면 키를 생략해 기존 콜백 페이로드와 완전히 동일하게 동작한다(회귀 0).
    if requested_question_count is not None:
        payload["requestedQuestionCount"] = requested_question_count
    if actual_question_count is not None:
        payload["actualQuestionCount"] = actual_question_count
    if generation_outcome is not None:
        payload["generationOutcome"] = generation_outcome

    _post_to_spring(url, token, payload)
    _LOG.info(
        "[MockGenCallback] 생성 완료 콜백 전송 | attemptId=%s, examId=%s, 문항=%d개, "
        "groundingDegraded=%s, outcome=%s, 요청=%s/생성=%s",
        attempt_id,
        exam_id,
        len(spring_questions),
        grounding_degraded,
        generation_outcome,
        requested_question_count,
        actual_question_count,
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

    연결 실패·5xx·404는 백오프(0.5/1/2/4/8초)로 최대 6회(최초 1회 + 재시도 5회)까지
    재시도한다. 404는 Spring attempt 커밋 전 레이스의 일시 오류일 수 있어 포함한다.
    그 외 4xx(인증 오류·검증 실패 등)는 재시도해도 결과가 같으므로 즉시 실패 처리한다.
    최종 실패는 MockGenerationCallbackError 로 정규화한다.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_error: MockGenerationCallbackError | None = None
    total_attempts = len(_RETRY_DELAYS_SEC) + 1
    for attempt in range(total_attempts):
        if attempt > 0:
            delay = _RETRY_DELAYS_SEC[attempt - 1]
            _LOG.warning(
                "[MockGenCallback] 콜백 재시도 %d/%d — %.1fs 대기 후 재전송 | url=%s, 직전 오류=%s",
                attempt,
                len(_RETRY_DELAYS_SEC),
                delay,
                url,
                last_error,
            )
            time.sleep(delay)

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
            return
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")[:300]
            last_error = MockGenerationCallbackError(
                f"Spring 모의고사 생성 콜백 HTTP 오류 (status={exc.code}): {raw_body}"
            )
            last_error.__cause__ = exc
            # 5xx와 404만 재시도 — 그 외 4xx는 영구 오류로 즉시 중단
            retryable = exc.code >= 500 or exc.code in _RETRYABLE_EXTRA_STATUS
            if not retryable:
                raise last_error
        except urllib.error.URLError as exc:
            # 연결 거부·DNS 실패·타임아웃 — 전부 일시 오류로 보고 재시도
            last_error = MockGenerationCallbackError(
                f"Spring 모의고사 생성 콜백 연결 실패: {exc.reason}"
            )
            last_error.__cause__ = exc

    # 모든 재시도 소진 — 크게 로깅하고 기존 예외 전파 동작 유지
    _LOG.error(
        "[MockGenCallback] 콜백 최종 실패 — %d회 시도 모두 소진 | url=%s, error=%s",
        total_attempts,
        url,
        last_error,
    )
    raise last_error if last_error else MockGenerationCallbackError(
        f"Spring 모의고사 생성 콜백 실패 (원인 미상): {url}"
    )

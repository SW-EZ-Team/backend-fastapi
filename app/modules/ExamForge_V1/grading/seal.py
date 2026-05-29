"""채점용 정답 키 봉인과 검증."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence

from app.modules.ExamForge_V1.common.config import examforge_answer_key_secret
from app.modules.ExamForge_V1.schemas.question import Question

_SEAL_PREFIX = "v1."


def create_answer_key_seal(exam_id: str, questions: Sequence[Question]) -> str:
    """시험지 정답 키의 위변조 방지 서명을 만든다."""
    payload = _canonical_payload(exam_id, questions)
    digest = hmac.new(_secret_bytes(), payload, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{_SEAL_PREFIX}{encoded}"


def verify_answer_key_seal(
    exam_id: str,
    questions: Sequence[Question],
    seal: str,
) -> bool:
    """제출 채점 전에 정답 키 서명이 맞는지 확인한다."""
    if not seal.startswith(_SEAL_PREFIX):
        return False
    expected = create_answer_key_seal(exam_id, questions)
    return hmac.compare_digest(expected, seal)


def attach_answer_key_seal(state: dict) -> dict:
    """파이프라인 결과 상태에 정답 키 서명을 추가한다."""
    questions = [Question(**q) for q in state.get("calibrated_questions", [])]
    state_copy = dict(state)
    state_copy["answer_key_seal"] = create_answer_key_seal(
        str(state_copy.get("exam_id", "")),
        questions,
    )
    return state_copy


def _canonical_payload(exam_id: str, questions: Sequence[Question]) -> bytes:
    """서명 대상 payload를 안정적인 JSON 바이트로 만든다."""
    payload = {
        "version": 1,
        "exam_id": exam_id,
        "questions": [
            question.model_dump(mode="json", exclude_none=True)
            for question in questions
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _secret_bytes() -> bytes:
    """환경 변수 secret을 HMAC 키 바이트로 변환한다."""
    return examforge_answer_key_secret().encode("utf-8")

"""채점용 정답 키 봉인과 검증."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from collections.abc import Sequence
from typing import Protocol

from app.modules.ExamForge_V1.common.config import examforge_answer_key_secret
from app.modules.ExamForge_V1.schemas.question import Question

_SEAL_PREFIX = "v1."
_LOG = logging.getLogger(__name__)

# 생성(Question)·채점(GradeQuestion) 양쪽 모두에 존재하지 않거나
# 채점 경로에서 null로 올 수 있는 필드 — canonical payload에서 제외해
# 생성 시 HMAC == 채점 시 HMAC 이 항상 성립하도록 보장한다.
# 이 4개 필드가 없어도 정답 무결성(correct_answer·points 등) 검증에는 영향 없다.
_SEAL_EXCLUDED_FIELDS = frozenset({"draft_id", "topic", "difficulty", "bloom_level"})


class _GradableQuestion(Protocol):
    """봉인 대상 문항이 갖춰야 할 최소 인터페이스.

    Question(생성 경로)과 GradeQuestion(채점 경로) 모두 이 Protocol을 만족한다.
    seal 계산에 사용하는 model_dump만 요구한다.
    """

    def model_dump(self, *, mode: str, exclude_none: bool) -> dict: ...  # noqa: D102


def create_answer_key_seal(exam_id: str, questions: Sequence[_GradableQuestion]) -> str:
    """시험지 정답 키의 위변조 방지 서명을 만든다."""
    payload = _canonical_payload(exam_id, questions)
    digest = hmac.new(_secret_bytes(), payload, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{_SEAL_PREFIX}{encoded}"


def verify_answer_key_seal(
    exam_id: str,
    questions: Sequence[_GradableQuestion],
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


def _canonical_payload(exam_id: str, questions: Sequence[_GradableQuestion]) -> bytes:
    """서명 대상 payload를 안정적인 JSON 바이트로 만든다.

    채점 경로(GradeQuestion)에서는 draft_id·topic·difficulty·bloom_level이 null이거나
    아예 전송되지 않는다. 생성 경로(Question)에서 이 4개 필드가 포함된 채로 서명을 만들면
    채점 시 재현한 payload와 달라져 HMAC 불일치 → 403이 발생한다.

    추가 불일치 원인: Spring ExamGradingPersistenceMapper가 null 옵션 목록·연결형·순서형·빈칸형 필드를
    Collections.emptyList()로 채워 반환하기 때문에, 채점 경로 GradeQuestion의 options·matching_pairs 등이
    None이 아닌 빈 리스트 []로 FastAPI에 도달한다. 생성 경로 Question은 해당 필드가 None이어서
    exclude_none=True 시 payload에서 누락된다 — 양쪽의 canonical JSON이 달라져 HMAC 불일치가 발생한다.

    해결: None과 빈 컬렉션(list, dict) 모두를 canonical에서 제거해 두 경로가 항상 동일한 payload를
    생성하도록 보장한다. 정답 무결성은 correct_answer·points·stem 등 실질 채점 필드로 충분히 보장된다.
    """
    def _stable_fields(q: _GradableQuestion) -> dict:
        """문항 dict에서 seal 안정 필드셋만 추출한다.

        None·빈 컬렉션([]·{})을 함께 제거해 생성/채점 두 경로의 canonical이 동일하도록 한다.
        Spring mapper가 null 필드를 emptyList()로 치환하므로 exclude_none만으로는 부족하다.
        """
        raw = q.model_dump(mode="json", exclude_none=True)
        return {
            k: v
            for k, v in raw.items()
            if k not in _SEAL_EXCLUDED_FIELDS and v != [] and v != {}
        }

    payload = {
        "version": 1,
        "exam_id": exam_id,
        "questions": [_stable_fields(q) for q in questions],
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

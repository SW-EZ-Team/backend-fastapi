"""교차 검증 결과 상태 판별 헬퍼."""
from __future__ import annotations

from collections.abc import Mapping

Verification = Mapping[str, object]


def verification_map(value: object) -> Verification:
    """검증 결과가 dict일 때만 읽고, 없거나 깨진 값은 빈 매핑으로 본다."""
    return value if isinstance(value, Mapping) else {}


def is_parse_failed(value: object) -> bool:
    """검증 모델 응답 파싱 실패는 정답 오류와 분리한다."""
    return verification_map(value).get("parse_failed") is True


def is_genuine_fail(value: object) -> bool:
    """검증자가 명시적으로 틀렸다고 판단한 경우만 genuine fail이다."""
    verification = verification_map(value)
    return verification.get("passed") is False and not is_parse_failed(verification)


def is_verified_pass(value: object) -> bool:
    """검증자가 명시적으로 통과시킨 결과인지 확인한다."""
    return verification_map(value).get("passed") is True


def question_keys(question: Mapping[str, object]) -> set[str]:
    """draft_id와 question_id 어느 쪽으로 실패 목록이 와도 대조되게 한다."""
    keys: set[str] = set()
    for key in ("draft_id", "question_id", "id"):
        value = question.get(key)
        if value not in (None, ""):
            keys.add(str(value))
    return keys


def parse_failed_keys(questions: list[dict]) -> set[str]:
    """parse_failed 문항의 식별자 집합을 반환한다."""
    keys: set[str] = set()
    for question in questions:
        if is_parse_failed(question.get("_verification")):
            keys.update(question_keys(question))
    return keys


def verification_advisory_keys(questions: list[dict]) -> set[str]:
    """advisory 모드에서 품질 게이트에 반영하지 않을 검증 실패 식별자를 모은다."""
    keys: set[str] = set()
    for question in questions:
        verification = question.get("_verification")
        if is_parse_failed(verification) or is_genuine_fail(verification):
            keys.update(question_keys(question))
    return keys


def genuine_failed_ids(failed_ids: list[str], questions: list[dict]) -> list[str]:
    """기존 실패 목록에서 parse_failed 문항만 제외한다."""
    advisory_keys = parse_failed_keys(questions)
    return [item for item in failed_ids if str(item) not in advisory_keys]


def advisory_filtered_failed_ids(
    failed_ids: list[str],
    questions: list[dict],
    *,
    verification_advisory: bool,
) -> list[str]:
    """검증 advisory 모드면 검증기 판단에서 온 실패 ID를 재시도 대상에서 제외한다."""
    if not verification_advisory:
        return genuine_failed_ids(failed_ids, questions)
    advisory_keys = verification_advisory_keys(questions)
    return [item for item in failed_ids if str(item) not in advisory_keys]


def verification_counts(questions: list[dict]) -> dict[str, int]:
    """검증 상태별 개수를 계산한다."""
    counts = {"passed": 0, "failed": 0, "parse_failed": 0, "missing": 0, "evaluable": 0}
    for question in questions:
        verification = question.get("_verification")
        if is_parse_failed(verification):
            counts["parse_failed"] += 1
            continue
        if is_verified_pass(verification):
            counts["passed"] += 1
            counts["evaluable"] += 1
            continue
        if is_genuine_fail(verification):
            counts["failed"] += 1
            counts["evaluable"] += 1
            continue
        counts["missing"] += 1
    return counts


def parse_failed_ratio(questions: list[dict]) -> float:
    """전체 문항 대비 검증 파싱 실패 비율을 반환한다."""
    if not questions:
        return 0.0
    return verification_counts(questions)["parse_failed"] / len(questions)


def answer_accuracy_rate(questions: list[dict]) -> float:
    """parse_failed를 분모에서 제외한 검증 통과율을 계산한다."""
    counts = verification_counts(questions)
    if counts["evaluable"] == 0:
        return 1.0 if questions and counts["parse_failed"] == len(questions) else 0.0
    return counts["passed"] / counts["evaluable"]


def has_parse_failed_majority(questions: list[dict], threshold: float = 0.5) -> bool:
    """검증기 출력 포맷을 신뢰하기 어려운지 판단한다."""
    return bool(questions) and parse_failed_ratio(questions) >= threshold

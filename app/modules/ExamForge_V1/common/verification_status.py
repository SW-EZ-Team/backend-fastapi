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


# 오답 타당성(기준7) 위반을 issues 텍스트에서 식별하기 위한 폴백 키워드.
# 검증기가 distractor_validity_failed 플래그를 명시하지 않아도, issues에 아래
# 마커가 있으면 콘텐츠 정확성 결함(hard fail)으로 본다. 일반 스타일 권고와 구분된다.
_DISTRACTOR_VALIDITY_MARKERS: tuple[str, ...] = (
    "오답 타당성",
    "distractor_validity",
    "distractor validity",
    "독립적으로 참",
    "논리적으로 동치",
    "정답과 동치",
    "동시에 옳",
    "조건 a 위반",
    "조건 b 위반",
    "조건 c 위반",
)


def _issues_signal_distractor_validity(verification: Verification) -> bool:
    """issues 텍스트에 오답 타당성 위반 마커가 있으면 True (플래그 폴백)."""
    issues = verification.get("issues", [])
    if not isinstance(issues, (list, tuple)):
        issues = [issues]
    joined = " ".join(str(item) for item in issues).lower()
    return any(marker.lower() in joined for marker in _DISTRACTOR_VALIDITY_MARKERS)


def is_distractor_validity_hard_fail(value: object) -> bool:
    """오답 타당성(기준7) 위반인 genuine fail인지 판별한다.

    이 결함은 표현·스타일 권고가 아니라 콘텐츠 정확성 결함이므로 advisory 모드여도
    반드시 repair돼야 한다. 판별 우선순위:
      1) 검증기가 distractor_validity_failed=true를 명시 → hard fail
      2) (폴백) issues 텍스트에 오답 타당성 위반 마커가 있음 → hard fail
    단, genuine fail(passed=false, parse_failed 아님)이 아니면 hard fail이 아니다.
    """
    verification = verification_map(value)
    if not is_genuine_fail(verification):
        return False
    if verification.get("distractor_validity_failed") is True:
        return True
    return _issues_signal_distractor_validity(verification)


def has_distractor_validity_hard_fail(questions: list[dict]) -> bool:
    """문항 목록에 오답 타당성 hard fail이 하나라도 있으면 True."""
    return any(
        is_distractor_validity_hard_fail(q.get("_verification"))
        for q in questions
    )


def distractor_validity_hard_fail_keys(questions: list[dict]) -> set[str]:
    """오답 타당성 hard fail 문항의 식별자 집합을 반환한다.

    advisory 게이트가 이 키들은 재시도 대상에서 제외하지 않도록(=교정 강제) 쓰인다.
    """
    keys: set[str] = set()
    for question in questions:
        if is_distractor_validity_hard_fail(question.get("_verification")):
            keys.update(question_keys(question))
    return keys


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
    """검증 advisory 모드면 검증기 판단에서 온 실패 ID를 재시도 대상에서 제외한다.

    예외: 오답 타당성(기준7) hard fail은 콘텐츠 정확성 결함이므로 advisory 모드여도
    재시도 대상에서 제외하지 않는다 → 결함 오답이 repair로 교정되도록 강제한다.
    """
    if not verification_advisory:
        return genuine_failed_ids(failed_ids, questions)
    advisory_keys = verification_advisory_keys(questions)
    # hard fail 키는 advisory suppression에서 되살린다(=재시도 대상 유지).
    hard_fail_keys = distractor_validity_hard_fail_keys(questions)
    advisory_keys -= hard_fail_keys
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

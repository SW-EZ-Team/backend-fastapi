"""3계층 검증 노드: 구조 + 교차문제 + 전체."""
from __future__ import annotations

import time

from pydantic import ValidationError as PydanticValidationError

from app.modules.ExamForge_V1.common.errors import ExamForgeError
from app.modules.ExamForge_V1.common.config import verification_advisory_enabled
from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.templates.registry import get_template
from app.modules.ExamForge_V1.quality.deduplicator import check_duplicates
from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
from app.modules.ExamForge_V1.quality.coverage_analyzer import analyze_coverage
from app.modules.ExamForge_V1.quality.explanation_checker import (
    check_explanation_quality,
    is_explanation_complete,
)
from app.modules.ExamForge_V1.quality.meta_question_filter import is_meta_question
from app.modules.ExamForge_V1.quality.difficulty_scorer import check_difficulty_manifestation
from app.modules.ExamForge_V1.quality.relevance_gate import check_questions_relevance
from app.modules.ExamForge_V1.quality.scenario_gate import check_scenario_quality
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import has_code_snippets
from app.modules.ExamForge_V1.pipeline.nodes.programming_context import looks_like_programming_source
from app.modules.ExamForge_V1.common.verification_status import (
    answer_accuracy_rate,
    is_distractor_validity_hard_fail,
    is_genuine_fail,
    is_parse_failed,
    is_verified_pass,
    parse_failed_ratio,
    verification_counts,
)

logger = get_logger(__name__)


async def validate_node(state: ExamForgeState) -> dict:
    """3계층 검증을 오케스트레이션한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환해 불필요한 검증 비용을 방지한다
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: validate_node")
    questions = state.get("verified_questions", [])

    # 상위 노드에서 데이터가 비었으면 즉시 반환 — 결정적 실패에 대한 무의미한 재시도 방지
    if not questions:
        logger.warning("validate_node: 검증할 문제 없음 — 즉시 종료")
        return {
            "validation_report": {},
            "failed_question_ids": [],
            "pipeline_status": "error",
            "error_message": "이전 단계에서 검증 가능한 문제가 생성되지 않음",
        }

    plan = state.get("exam_plan", {})
    topic_weights = plan.get("topic_weights", {})
    verification_advisory = _is_verification_advisory(state)

    # 1계층: 개별 구조 검증
    results, failed_ids = _validate_structure(
        questions,
        verification_advisory=verification_advisory,
    )

    # 2계층: 교차 문제 검증
    global_issues, cross_failed, dedup_score = _validate_cross_question(questions)
    for did in cross_failed:
        if did not in failed_ids:
            failed_ids.append(did)

    # plan-first E 요구사항: concept_key 유일성 재확인
    ck_issues, ck_failed = _validate_concept_key_uniqueness(questions)
    global_issues.extend(ck_issues)
    for did in ck_failed:
        if did not in failed_ids:
            failed_ids.append(did)

    # 3계층: 전체 수준 검증
    coverage_score, uncovered = _validate_global(questions, topic_weights)
    if uncovered:
        global_issues.append(f"미커버 주제: {', '.join(uncovered[:5])}")
    global_issues.extend(_verification_advisory_issues(questions, verification_advisory))
    _apply_programming_code_gate(state, questions, failed_ids, global_issues)
    # 출처 관련성 게이트: 출처 어휘와 겹치지 않는 일반 상식 문항을 재시도 대상으로 표시
    _apply_relevance_gate(state, questions, failed_ids, global_issues)
    # 시나리오 중복·개념 과대표현 게이트: 같은 수치 예시 재활용·동일 개념 과점유 문항을
    # 재시도(교체) 대상으로 표시한다. 구조 신호만 사용(subject-agnostic).
    _apply_scenario_gate(questions, failed_ids, global_issues)

    # plan-first E 요구사항: 정답 위치 분포가 계획(answer_position_plan)과 일치하는지 검증.
    # 불일치는 global_issues에만 두지 않고 별도 플래그로 보고서에 올려 라우팅에 반영한다.
    pos_issues = _validate_answer_position_plan(questions, plan)
    global_issues.extend(pos_issues)
    answer_position_mismatch = bool(pos_issues)

    # plan-first E 요구사항(P1-B 수정): 개수 충족 하드 게이트.
    # len(questions) != total_questions 또는 누락 슬롯이 있으면 부족 슬롯을 failed_ids에 넣고
    # missing_count를 보고서에 기록해 route_after_validation이 retry/exhausted로 보내게 한다.
    count_issues, missing_count = _validate_question_count(questions, plan, failed_ids)
    global_issues.extend(count_issues)

    # 정답 정확률 계산
    accuracy_rate = _compute_accuracy_rate(questions)
    verification_summary = verification_counts(questions)

    # AKAR: 정확률 0.95 미만이면 미통과 문제를 재시도 목록에 추가
    if accuracy_rate < 0.95 and not verification_advisory:
        for q in questions:
            verification = q.get("_verification")
            if _needs_accuracy_retry(verification):
                draft_id = q.get("draft_id", q.get("question_id", ""))
                if draft_id and draft_id not in failed_ids:
                    failed_ids.append(draft_id)

    report = {
        "results": results,
        "global_issues": global_issues,
        "coverage_score": coverage_score,
        "dedup_score": dedup_score,
        "answer_accuracy_rate": accuracy_rate,
        # P1-B: 개수 부족·위치 불일치를 라우팅이 직접 참조할 수 있게 보고서에 노출
        "missing_count": missing_count,
        "answer_position_mismatch": answer_position_mismatch,
        "answer_verification_parse_failed_count": verification_summary["parse_failed"],
        "answer_verification_parse_failed_ratio": parse_failed_ratio(questions),
        "answer_verification_evaluable_count": verification_summary["evaluable"],
    }

    logger.info("노드 완료: validate_node (%.2fs)", time.time() - node_start)
    return {
        "validation_report": report,
        "failed_question_ids": failed_ids,
        "pipeline_status": "routing",
    }


def _validate_structure(
    questions: list[dict],
    *,
    verification_advisory: bool = False,
) -> tuple[list[dict], list[str]]:
    """개별 문제의 구조를 검증한다."""
    results: list[dict] = []
    failed_ids: list[str] = []

    for q in questions:
        template_id = q.get("template_id", "")
        q_id = q.get("question_id", q.get("draft_id", ""))
        # 재시도 필터링은 draft_id 기준으로 수행하므로 draft_id를 실패 목록에 저장
        draft_id = q.get("draft_id", q_id)
        issues = _check_single_structure(q, template_id)

        # 교차 모델 검증 결과 포함
        verification = q.get("_verification", {})
        # 오답 타당성(기준7) hard fail은 advisory 모드여도 콘텐츠 정확성 결함이므로
        # 구조 실패로 반영해 repair 대상으로 만든다.
        hard_fail = is_distractor_validity_hard_fail(verification)
        if is_genuine_fail(verification) and (not verification_advisory or hard_fail):
            issues.extend(verification.get("issues", []))
        elif verification == {} and not verification_advisory:
            issues.append("정답 검증 결과 없음")

        passed = len(issues) == 0
        if not passed:
            failed_ids.append(draft_id)

        results.append({
            "question_id": q_id,
            "passed": passed,
            "issues": issues,
            "parse_failed": is_parse_failed(verification),
            "distractor_validity_hard_fail": hard_fail,
        })

    return results, failed_ids


def _check_single_structure(q: dict, template_id: str) -> list[str]:
    """단일 문제의 구조 유효성을 확인한다.

    객관식 문항(options 4개 이상)에 한해 해설 완결성 게이트를 적용한다.
    단답형·주관식은 해설이 짧아도 정상이므로 게이트를 건너뛴다.
    """
    if not q.get("stem", "").strip():
        return ["문제 줄기(stem)가 비어 있음"]
    # 시험 메타 문항(문항 수·배점·응시 방법 등) 결정론 차단 — repair 경로로 재생성된다
    if is_meta_question(q.get("stem", "")):
        return ["시험 메타 문항(시험 구성 자체를 묻는 문항) — 과목 내용 문항으로 재생성 필요"]
    # 객관식 문항에 한해 해설 완결성 게이트 적용 — truncation 조용한 통과 방지
    options = q.get("options") or []
    explanation = str(q.get("explanation", "")).strip()
    if explanation and len(options) >= 4 and not is_explanation_complete(explanation):
        return [
            f"해설 미완성(truncation) — {len(explanation)}자, "
            "정답 근거·오답 해설을 포함한 완결 문장으로 repair 필요"
        ]
    try:
        template = get_template(template_id)
        from app.modules.ExamForge_V1.schemas.question import Question
        question_obj = Question(**q)
        # 난이도 발현 게이트: 상위 블룸(4~5) 문항이 정의 회상형으로 퇴화하면 결함 처리
        return (
            template.validate_structure(question_obj)
            + check_explanation_quality(q)
            + check_difficulty_manifestation(q)
        )
    except (ExamForgeError, PydanticValidationError, ValueError, TypeError) as e:
        return [f"구조 검증 오류: {str(e)[:100]}"]


def _validate_cross_question(
    questions: list[dict],
) -> tuple[list[str], list[str], float]:
    """교차 문제 검증 (중복, 일관성)을 수행하고 dedup_score를 함께 반환한다."""
    global_issues: list[str] = []
    failed_ids: list[str] = []

    try:
        dedup_score, dup_pairs = check_duplicates(questions)
    except Exception as exc:
        logger.warning("중복 검사 실패 — 건너뜀: %s", exc)
        dedup_score, dup_pairs = 0.0, []
    if dup_pairs:
        global_issues.append(f"중복 의심 쌍 {len(dup_pairs)}건 발견")
        failed_ids.extend(_duplicate_targets_to_draft_ids(questions, dup_pairs))

    try:
        inconsistencies = check_consistency(questions)
    except Exception as exc:
        logger.warning("일관성 검사 실패 — 건너뜀: %s", exc)
        inconsistencies = []
    if inconsistencies:
        global_issues.append(f"정답-보기 불일치 {len(inconsistencies)}건")
        # question_id → 문제 매핑을 미리 생성해 반복 탐색 방지
        q_map = {q.get("question_id", ""): q for q in questions}
        for inc in inconsistencies:
            inc_qid = inc.get("question_id", "")
            matched_q = q_map.get(inc_qid, {})
            # draft_id 기준으로 실패 목록 관리 (generate_questions_node와 일치)
            failed_ids.append(matched_q.get("draft_id", inc_qid))

    return global_issues, failed_ids, dedup_score


def _duplicate_targets_to_draft_ids(
    questions: list[dict],
    dup_pairs: list[tuple[str, str]],
) -> list[str]:
    """중복 쌍의 뒤쪽 문항을 재생성 대상으로 변환한다."""
    q_map = {
        str(q.get("question_id") or q.get("draft_id") or index): q
        for index, q in enumerate(questions)
    }
    failed: list[str] = []
    for _, duplicate_id in dup_pairs:
        matched = q_map.get(str(duplicate_id), {})
        draft_id = str(matched.get("draft_id") or duplicate_id)
        if draft_id and draft_id not in failed:
            failed.append(draft_id)
    return failed


def _validate_global(
    questions: list[dict], topic_weights: dict[str, float],
) -> tuple[float, list[str]]:
    """전체 수준 검증 (커버리지)을 수행한다."""
    try:
        return analyze_coverage(questions, topic_weights)
    except Exception as exc:
        logger.warning("커버리지 분석 실패 — 폴백 사용: %s", exc)
        return 0.0, []


def _compute_accuracy_rate(questions: list[dict]) -> float:
    """교차 검증 통과율을 계산한다."""
    return answer_accuracy_rate(questions)


def _needs_accuracy_retry(verification: object) -> bool:
    """정확률 게이트에서 재시도 대상으로 볼 검증 상태인지 확인한다."""
    if is_parse_failed(verification):
        return False
    return not is_verified_pass(verification)


def _verification_advisory_issues(
    questions: list[dict],
    verification_advisory: bool,
) -> list[str]:
    """검증 파싱 실패는 경고만 남기고 실패 목록에는 넣지 않는다."""
    counts = verification_counts(questions)
    if verification_advisory:
        if counts["failed"] == 0 and counts["parse_failed"] == 0 and counts["missing"] == 0:
            return []
        logger.warning(
            "정답 검증 advisory 모드 — genuine fail %d건, parse_failed %d건, missing %d건 제외",
            counts["failed"],
            counts["parse_failed"],
            counts["missing"],
        )
        return [
            "정답 검증 advisory 모드 — "
            f"genuine fail {counts['failed']}건, parse_failed {counts['parse_failed']}건, "
            f"missing {counts['missing']}건을 재시도 게이트에서 제외"
        ]
    if counts["parse_failed"] == 0:
        return []
    return [f"검증 응답 파싱 실패 {counts['parse_failed']}건 — 정답 오류가 아닌 advisory로 분리"]


def _is_verification_advisory(state: ExamForgeState) -> bool:
    """상태 플래그나 env 설정 중 하나라도 advisory면 검증 게이트를 경고 전용으로 둔다."""
    return state.get("verification_advisory") is True or verification_advisory_enabled()


def _apply_programming_code_gate(
    state: ExamForgeState,
    questions: list[dict],
    failed_ids: list[str],
    global_issues: list[str],
) -> None:
    """프로그래밍 과목에서 코드 예시 문항 누락을 재시도 대상으로 표시한다."""
    source_text = state.get("source_text", "")
    if not looks_like_programming_source(source_text) or has_code_snippets(questions):
        return
    global_issues.append("프로그래밍 과목인데 code_snippet 문항이 없음")
    for q in questions:
        draft_id = q.get("draft_id", q.get("question_id", ""))
        if draft_id and draft_id not in failed_ids:
            failed_ids.append(draft_id)


def _apply_relevance_gate(
    state: ExamForgeState,
    questions: list[dict],
    failed_ids: list[str],
    global_issues: list[str],
) -> None:
    """출처 어휘와 겹치지 않는 일반 상식 의심 문항을 재시도 대상으로 표시한다.

    출처 어휘가 빈약하면(스텁 source_text) 게이트가 자체 생략되므로
    폴백 경로(과목명만으로 생성)에서는 동작하지 않는다 — 오탐 방지.
    """
    source_text = state.get("source_text", "")
    topics = state.get("topics", [])
    try:
        flagged = check_questions_relevance(questions, source_text, topics)
    except Exception as exc:
        logger.warning("관련성 게이트 검사 실패 — 건너뜀: %s", exc)
        return
    if not flagged:
        return
    global_issues.append(f"출처 무관 의심 문항 {len(flagged)}건 — 출처 발췌 기반 재출제 필요")
    for draft_id in flagged:
        if draft_id and draft_id not in failed_ids:
            failed_ids.append(draft_id)


def _apply_scenario_gate(
    questions: list[dict],
    failed_ids: list[str],
    global_issues: list[str],
) -> None:
    """시나리오 중복·개념 과대표현 문항을 교체(재시도) 대상으로 표시한다.

    구조 신호(숫자 시퀀스·정규화 토큰·concept_key)만으로 판단하므로 과목 불문이다.
    교체는 기존 repair/재생성 경로가 수행하고, 좁은 소스로 교체가 불가하면
    route_after_validation 의 기존 재시도 캡이 1~2회 시도 후 graceful 통과시킨다.
    deduplicator/relevance_gate 와는 failed_ids 합류 시 중복 추가를 막아 충돌이 없다.
    """
    try:
        flagged = check_scenario_quality(questions)
    except Exception as exc:
        logger.warning("시나리오/과대표현 게이트 검사 실패 — 건너뜀: %s", exc)
        return
    if not flagged:
        return
    global_issues.append(
        f"시나리오 중복·개념 과대표현 의심 문항 {len(flagged)}건 — 다른 시나리오·개념으로 교체 필요"
    )
    for draft_id in flagged:
        if draft_id and draft_id not in failed_ids:
            failed_ids.append(draft_id)


def _validate_question_count(
    questions: list[dict],
    plan: dict,
    failed_ids: list[str],
) -> tuple[list[str], int]:
    """plan-first P1-B: 개수 충족·슬롯 1:1 채움을 하드 검사한다.

    1) 블루프린트가 있으면 채워진 slot_id 집합 == 블루프린트 slot_id 집합을 검사하고
       누락 슬롯을 식별해 부족분을 failed_ids에 placeholder로 넣는다.
    2) 블루프린트가 없으면 len(questions) != total_questions 를 검사한다.

    Returns:
        (issues, missing_count) — missing_count > 0 이면 라우팅이 retry/exhausted로 보낸다.
    """
    issues: list[str] = []

    try:
        total_questions = int(plan.get("total_questions", 0) or 0)
    except (ValueError, TypeError):
        total_questions = 0

    blueprint = plan.get("question_blueprint", [])
    if blueprint:
        # 슬롯 1:1 채움 검사: 블루프린트 slot_id 집합과 실제 채워진 slot_id 집합 비교
        plan_slots = {
            int(s["slot"]) for s in blueprint if s.get("slot") is not None
        }
        filled_slots = {
            int(q["_blueprint_slot"])
            for q in questions
            if q.get("_blueprint_slot") is not None
        }
        missing_slots = plan_slots - filled_slots
        missing_count = len(missing_slots)
        if missing_count > 0:
            issues.append(
                f"슬롯 누락 {missing_count}개 — 블루프린트 {len(plan_slots)}슬롯 중 "
                f"{len(filled_slots)}개만 채워짐 (누락 slot_id={sorted(missing_slots)[:10]})"
            )
            # 누락 슬롯을 식별 가능한 placeholder로 failed_ids에 추가 (개수 부족을 재시도로)
            for slot_id in sorted(missing_slots):
                marker = f"__missing_slot_{slot_id}"
                if marker not in failed_ids:
                    failed_ids.append(marker)
        return issues, missing_count

    # 폴백: 블루프린트 없는 경로 — 단순 개수 비교
    if total_questions > 0 and len(questions) != total_questions:
        missing_count = max(0, total_questions - len(questions))
        issues.append(
            f"문항 수 불일치 — 계획={total_questions}, 실제={len(questions)} "
            f"(누락 {missing_count}개)"
        )
        for i in range(missing_count):
            marker = f"__missing_count_{i}"
            if marker not in failed_ids:
                failed_ids.append(marker)
        return issues, missing_count

    return issues, 0


def _validate_concept_key_uniqueness(
    questions: list[dict],
) -> tuple[list[str], list[str]]:
    """plan-first: 슬롯 concept_key 유일성을 재확인한다.

    블루프린트 단계에서 이미 보장됐어야 하므로 중복 발견은 구조 경고로만 처리한다.
    중복된 뒤쪽 문항을 재생성 대상으로 표시한다.
    """
    issues: list[str] = []
    failed: list[str] = []
    seen_keys: dict[str, str] = {}  # concept_key → 첫 번째 draft_id

    for q in questions:
        ck = str(q.get("_concept_key", "") or q.get("concept_key", ""))
        if not ck:
            continue
        draft_id = str(q.get("draft_id") or q.get("question_id") or "")
        if ck in seen_keys:
            issues.append(f"concept_key 중복: '{ck}' (draft_id={draft_id})")
            if draft_id and draft_id not in failed:
                failed.append(draft_id)
        else:
            seen_keys[ck] = draft_id

    return issues, failed


def _validate_answer_position_plan(
    questions: list[dict],
    plan: dict,
) -> list[str]:
    """plan-first: 실제 정답 위치 분포가 사전 배정 계획과 정확히 일치하는지 검증한다.

    answer_position_plan이 없으면 검사를 생략한다 (블루프린트 미적용 경로 호환).
    """
    from app.modules.ExamForge_V1.quality.answer_positions import answer_position_counts

    position_plan: dict[int, int] = plan.get("answer_position_plan", {})
    if not position_plan:
        return []

    actual = answer_position_counts(questions)
    # int/str 키 혼재 방지를 위해 int로 정규화
    plan_normalized = {int(k): int(v) for k, v in position_plan.items()}
    actual_normalized = {int(k): int(v) for k, v in actual.items()}

    if plan_normalized == actual_normalized:
        return []

    # 편차 상세 보고 (어느 위치에서 몇 개 차이인지)
    all_positions = set(plan_normalized) | set(actual_normalized)
    diff_parts = [
        f"위치{pos}: 계획={plan_normalized.get(pos, 0)} 실제={actual_normalized.get(pos, 0)}"
        for pos in sorted(all_positions)
        if plan_normalized.get(pos, 0) != actual_normalized.get(pos, 0)
    ]
    return [
        f"정답 위치 분포 계획 불일치 — {'; '.join(diff_parts)} "
        "(plan-first 블루프린트 사전 배정이 지켜지지 않았음)"
    ]

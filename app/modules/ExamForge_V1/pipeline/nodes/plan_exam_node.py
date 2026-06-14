"""시험 계획을 수립하는 노드."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json

import json
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.common.ai_bridge import get_planner_connector, ChapterAIRequest
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.common.source_capacity import effective_target_count
from app.modules.ExamForge_V1.templates.catalog import allocation_contract
from app.modules.ExamForge_V1.pipeline.nodes._plan_prompts import PLAN_PROMPT as _PLAN_PROMPT
from app.modules.ExamForge_V1.pipeline.nodes.concept_blueprint import (
    build_question_blueprint,
    compute_answer_position_plan,
)

logger = get_logger(__name__)
# question_types 미지정(빈 목록) 시 적용하는 기본 혼합 유형 — 객관식 비중을 높게 두되
# 모든 유형이 고르게 출제되도록 가중치 기반으로 분배한다 (최종모의고사 기본 동작).
_DEFAULT_QUESTION_TYPES = [
    "ko_multiple_choice_5",
    "ko_multiple_choice_4",
    "ko_short_answer",
    "ko_fill_blank",
    "ko_true_false",
    "ko_descriptive",
]
# 기본 혼합 유형별 분배 가중치 (예: 20문항 → mc5 6, mc4 3, 단답 4, 빈칸 3, OX 2, 서술 2)
_DEFAULT_TYPE_WEIGHTS: dict[str, float] = {
    "ko_multiple_choice_5": 0.30,
    "ko_multiple_choice_4": 0.15,
    "ko_short_answer": 0.20,
    "ko_fill_blank": 0.15,
    "ko_true_false": 0.10,
    "ko_descriptive": 0.10,
}
# 모의고사 최소 문항 수 — 이보다 작게 요청돼도 계획 단계에서 클램프한다
# (exam_config.allow_small_exam=True 인 경우에만 우회 허용)
_MIN_TOTAL_QUESTIONS = 20
# 유형별 최소 1문항 보장을 적용하는 총 문항 하한
_MIN_TOTAL_FOR_TYPE_GUARANTEE = 12
# 난이도 3 이상(적용·분석·평가) 문항의 최소 비율
_MIN_REASONING_RATIO = 0.6


def clamp_total_questions(config: dict) -> dict:
    """총 문항 수를 최소 기준(20)으로 클램프한 exam_config 사본을 반환한다.

    allow_small_exam=True 면 호출자가 의도적으로 작은 시험을 요청한 것이므로 우회한다.
    최대값(100)은 스키마 검증이 이미 강제하지만 직접 유입 state 방어를 위해 함께 클램프한다.
    """
    try:
        total = int(config.get("total_questions", 0) or 0)
    except (ValueError, TypeError):
        total = 0
    if config.get("allow_small_exam"):
        clamped = min(max(total, 1), 100)
    else:
        clamped = min(max(total, _MIN_TOTAL_QUESTIONS), 100)
    if clamped != total:
        logger.info(
            "plan_exam_node: total_questions %s → %d 클램프 (allow_small_exam=%s)",
            total,
            clamped,
            bool(config.get("allow_small_exam")),
        )
    return {**config, "total_questions": clamped}


def apply_effective_target(config: dict, source_text: str, topics: list[dict]) -> dict:
    """소스 폭으로 산정한 유효 목표 문항 수로 total_questions를 캡한 config 사본을 반환한다.

    - requested_question_count: 원래 요청 수를 메타로 보존(사용자 "요청 N / 생성 M" 표기용).
    - total_questions: 소스 폭 캡이 적용된 유효 목표(넓은 소스면 요청과 동일 — 회귀 0).
    캡 이후의 모든 하위 노드(블루프린트·검증·출력)는 이 유효 목표를 기준으로 수렴한다.
    """
    try:
        requested = int(config.get("total_questions", 0) or 0)
    except (ValueError, TypeError):
        requested = 0
    if requested <= 0:
        return config
    effective = effective_target_count(requested, source_text, topics)
    # requested_question_count는 항상 원래 요청 수로 기록한다(이미 있으면 보존).
    requested_meta = config.get("requested_question_count")
    if not isinstance(requested_meta, int) or requested_meta <= 0:
        requested_meta = requested
    if effective == requested:
        # 넓은 소스 — 캡 영향 없음. requested 메타만 채워 하위 노드와 정합시킨다.
        return {**config, "requested_question_count": requested_meta}
    logger.info(
        "plan_exam_node: 소스 폭 캡 — 요청 %d → 유효 목표 %d (총 문항 수 하향)",
        requested,
        effective,
    )
    return {
        **config,
        "total_questions": effective,
        "requested_question_count": requested_meta,
    }


async def plan_exam_node(state: ExamForgeState) -> dict:
    """주제와 설정을 기반으로 시험 계획을 생성한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: plan_exam_node")
    topics = state.get("topics", [])
    # 최소 문항 수 클램프 — 너무 짧은 모의고사를 계획 단계에서 차단한다
    config = clamp_total_questions(state.get("exam_config", {}))
    # 소스 폭 기반 유효 목표 캡 — 좁은 자료에 큰 시험을 요청하면 고유 문항이
    # 부족해 dedup 비수렴(0문항 FAILED)이 된다. 계획 단계에서 total_questions를
    # 소스가 지탱 가능한 수로 캡하고, 원래 요청 수는 requested_question_count로 보존한다.
    config = apply_effective_target(config, state.get("source_text", ""), topics)
    subject = state.get("subject", "")

    try:
        connector = get_planner_connector()
    except Exception as exc:
        logger.warning("시험 계획 커넥터 초기화 실패 — 기본 계획 사용: %s", exc)
        total = config.get("total_questions", 50)
        plan = _build_fallback_plan(subject, total, config, topics)
        plan = _normalize_plan(plan, config, topics)
        return {
            "exam_plan": plan,
            "exam_config": config,
            "pipeline_status": "generating",
            "error_message": f"시험 계획 커넥터 초기화 실패 — 기본 계획 사용: {exc}",
        }
    req = ChapterAIRequest(
        system="교육 평가 설계 전문가. 균형 잡힌 시험 계획 수립.",
        user=_PLAN_PROMPT.format(
            topics_json=json.dumps(topics, ensure_ascii=False),
            config_json=json.dumps(config, ensure_ascii=False),
            subject=subject,
            template_contract=allocation_contract(_question_types(config)),
        ),
        max_tokens=3000,
        temperature=0.3,
    )
    plan = None
    # AI 호출/파싱 실패 시 폴백 경로를 추적하는 플래그
    used_fallback = False
    try:
        resp = await connector.generate(req)
        plan = parse_llm_json(resp.text)
    except (ValueError, KeyError, TypeError):
        logger.warning("시험 계획 파싱 실패 — 기본 계획 사용")
    except Exception as exc:
        logger.warning("시험 계획 AI 호출 실패 — 기본 계획 사용: %s", exc)
    # AI 계획이 부분/비정상 JSON이어도 ExamPlan 필수 필드(exam_title·subject·
    # total_points·time_limit_minutes·locale)가 비지 않도록 항상 폴백 계획을
    # 베이스로 깔고 AI 출력을 그 위에 덮어쓴다. (실측: Gemini가 난이도 dict만
    # 반환해 응답 직렬화가 ValidationError로 죽고 생성 0건이 된 사례)
    total = config.get("total_questions", 50)
    base_plan = _build_fallback_plan(subject, total, config, topics)
    if not isinstance(plan, dict) or not plan:
        plan = base_plan
        used_fallback = True
    else:
        # 폴백 계획의 키 집합을 캐노니컬 스키마로 삼아, AI가 만든 쓰레기 키
        # ('3','4','5' 같은 난이도 키 등)가 plan에 섞여 들어가지 않게 한다.
        merged = dict(base_plan)
        for key, value in plan.items():
            if key in merged and value is not None:
                merged[key] = value
        plan = merged
    plan = _normalize_plan(plan, config, topics)
    # 정규화 후에도 유형 배분이 비면(AI가 깨진 type_allocations를 준 경우)
    # 폴백 배분으로 복구한다 — 배분 0건은 곧 생성 0건이므로 절대 통과시키지 않는다.
    if not plan.get("type_allocations"):
        logger.warning("plan_exam_node: type_allocations가 비어 폴백 계획으로 복구")
        plan = _normalize_plan(base_plan, config, topics)
        used_fallback = True

    logger.info("노드 완료: plan_exam_node (%.2fs)", time.time() - node_start)
    result: dict = {
        "exam_plan": plan,
        # 클램프된 exam_config를 state에 반영해 하위 노드(품질 게이트 등)와 정합시킨다
        "exam_config": config,
        "pipeline_status": "generating",
    }
    if used_fallback:
        result["error_message"] = "시험 계획 AI 호출/파싱 실패 — 기본 계획 사용"
    return result


def _coerce_to_list(value: object, field_name: str) -> list:
    """LLM이 리스트 필드에 스칼라(float/int/str/None)를 줄 때 안전하게 리스트로 변환한다.

    Gemini가 type_allocations 같은 배열 필드를 단일 숫자로 줄 경우
    TypeError: 'float' object is not iterable 크래시가 발생한다.
    명시적 isinstance 가드로 비정상 타입을 잡아 빈 리스트로 정규화한다.
    """
    if isinstance(value, list):
        return value
    # None이나 스칼라(float/int/str/dict)는 전부 빈 리스트로 처리한다
    logger.warning(
        "_normalize_plan: %s 필드가 list가 아닌 %s 타입(%r)으로 수신 → 빈 리스트로 정규화",
        field_name,
        type(value).__name__,
        value,
    )
    return []


def _coerce_to_dict(value: object, field_name: str) -> dict:
    """LLM이 dict 필드에 스칼라를 줄 때 안전하게 dict로 변환한다.

    topic_weights 같은 딕셔너리 필드에 float가 오면
    AttributeError: 'float' object has no attribute 'items' 크래시가 발생한다.
    명시적 isinstance 가드로 비정상 타입을 잡아 빈 딕셔너리로 정규화한다.
    """
    if isinstance(value, dict):
        return value
    logger.warning(
        "_normalize_plan: %s 필드가 dict가 아닌 %s 타입(%r)으로 수신 → 빈 딕셔너리로 정규화",
        field_name,
        type(value).__name__,
        value,
    )
    return {}


def _normalize_plan(
    plan: dict,
    config: dict,
    topics: list[dict] | None = None,
) -> dict:
    """작은 시험에서도 계획이 생성/커버리지 계산에 맞게 수렴하도록 보정한다."""
    # plan 자체가 dict가 아니면(Gemini가 최상위를 float/None으로 줄 경우)
    # dict 변환이 TypeError를 일으키므로 먼저 타입을 확인한다.
    if not isinstance(plan, dict):
        logger.warning(
            "_normalize_plan: plan이 dict가 아닌 %s 타입으로 수신 → 빈 plan으로 대체",
            type(plan).__name__,
        )
        plan = {}
    normalized = dict(plan)
    # 비정수 값이 들어올 수 있으므로 변환 실패 시 내부 값으로 안전하게 폴백한다
    try:
        total = int(config.get("total_questions", normalized.get("total_questions", 0)))
    except (ValueError, TypeError):
        total = int(normalized.get("total_questions", 0) or 0)
    normalized["total_questions"] = total
    # LLM이 hallucination으로 잘못된 template_id를 생성할 수 있으므로
    # 허용된 question_types 목록과 대조해 유효하지 않은 template_id를 보정한다.
    # Gemini가 type_allocations에 float/None/dict를 줄 경우 리스트로 정규화한다.
    raw_allocations = _coerce_to_list(normalized.get("type_allocations"), "type_allocations")
    normalized["type_allocations"] = _sanitize_template_ids(
        raw_allocations,
        _question_types(config),
    )
    normalized["type_allocations"] = _ensure_reasoning_distribution(
        normalized.get("type_allocations", []),
        total,
    )
    # Gemini가 topic_weights에 float/None/list를 줄 경우 빈 dict로 정규화한다.
    raw_topic_weights = _coerce_to_dict(normalized.get("topic_weights"), "topic_weights")
    normalized["topic_weights"] = _trim_topic_weights(
        raw_topic_weights,
        max_topics=max(1, total),
    )
    normalized["bloom_distribution"] = _bloom_distribution_from_allocations(
        normalized.get("type_allocations", [])
    )
    if topics is not None:
        # exam_id를 넘겨 정답 위치 배정이 시험 단위로 재현 가능하게 한다
        exam_id = str(config.get("exam_id", "") or "")
        blueprint = build_question_blueprint(
            topics,
            normalized.get("type_allocations", []),
            exam_id=exam_id,
        )
        normalized["question_blueprint"] = blueprint
        # plan-first 검증 게이트용: 배정된 정답 위치 분포를 계획에 기록한다
        normalized["answer_position_plan"] = compute_answer_position_plan(blueprint)
    return normalized


def _sanitize_template_ids(
    allocations: list[dict],
    allowed_types: list[str],
) -> list[dict]:
    """LLM이 생성한 allocations의 template_id를 허용 목록 기준으로 보정한다.

    - template_id가 빈 문자열이거나 허용 목록에 없으면 allowed_types[0]으로 대체한다.
    - allowed_types가 비어 있으면 원본 그대로 반환한다.
    - Spring 콜백 "templateId must not be blank" 오류의 근본 원인 차단.
    """
    if not allowed_types:
        return allocations
    fallback = allowed_types[0]
    sanitized: list[dict] = []
    for alloc in allocations:
        t_id = alloc.get("template_id", "")
        if not t_id or t_id not in allowed_types:
            # LLM 환각 template_id를 가장 가까운 허용 유형으로 교체한다
            logger.warning(
                "plan_exam_node: 유효하지 않은 template_id=%r → %r 로 보정",
                t_id,
                fallback,
            )
            alloc = {**alloc, "template_id": fallback}
        sanitized.append(alloc)
    return sanitized


def _ensure_reasoning_distribution(allocations: list[dict], total: int) -> list[dict]:
    """난이도 3 이상 문항이 최소 비율에 닿도록 낮은 난이도 일부를 이동한다."""
    if total < 5:
        return allocations
    adjusted = [{**alloc, "difficulty_distribution": dict(alloc.get("difficulty_distribution", {}))}
                for alloc in allocations]
    target = max(1, int(total * _MIN_REASONING_RATIO))
    current = sum(
        int(count)
        for alloc in adjusted
        for diff, count in alloc.get("difficulty_distribution", {}).items()
        if int(diff) >= 3
    )
    needed = target - current
    if needed <= 0:
        return adjusted
    for alloc in adjusted:
        dist = alloc.get("difficulty_distribution", {})
        for low in (1, 2):
            while needed > 0 and int(dist.get(low, 0)) > 0:
                dist[low] = int(dist.get(low, 0)) - 1
                dist[3] = int(dist.get(3, 0)) + 1
                needed -= 1
        alloc["difficulty_distribution"] = {k: v for k, v in dist.items() if int(v) > 0}
        if needed <= 0:
            break
    return adjusted


def _trim_topic_weights(topic_weights: dict, max_topics: int) -> dict[str, float]:
    """문항 수보다 많은 계획 주제는 상위 주제로 줄이고 가중치를 재정규화한다."""
    if not topic_weights:
        return {}
    items = sorted(topic_weights.items(), key=lambda item: item[1], reverse=True)
    trimmed = items[:max_topics]
    total_weight = sum(float(weight) for _, weight in trimmed) or 1.0
    return {
        str(topic): float(weight) / total_weight
        for topic, weight in trimmed
    }


def _bloom_distribution_from_allocations(allocations: list[dict]) -> dict[str, float]:
    """난이도 배분에서 실제 달성 가능한 블룸 분포를 계산한다."""
    counts: dict[str, int] = {}
    total = 0
    for alloc in allocations:
        for difficulty, count in alloc.get("difficulty_distribution", {}).items():
            # 비정수 문자열 키/값이 들어올 수 있으므로 변환 실패 시 해당 항목을 건너뛴다
            try:
                level = _bloom_for_difficulty(int(difficulty))
                int_count = int(count)
            except (ValueError, TypeError):
                continue
            counts[level] = counts.get(level, 0) + int_count
            total += int_count
    if total == 0:
        return {}
    return {level: count / total for level, count in counts.items()}


def _bloom_for_difficulty(difficulty: int) -> str:
    """난이도에 대응하는 블룸 레벨을 반환한다."""
    return {
        1: "기억",
        2: "이해",
        3: "적용",
        4: "분석",
        5: "평가",
    }.get(difficulty, "이해")


def _build_fallback_plan(
    subject: str,
    total: int,
    config: dict,
    topics: list[dict],
) -> dict:
    """AI 파싱 실패 시 기본 계획을 구성한다."""
    q_types = _question_types(config)
    counts = _allocate_type_counts(q_types, total)
    difficulty_weights = _difficulty_weights(config)
    allocations = []
    for t_id in q_types:
        count_for_type = counts.get(t_id, 0)
        if count_for_type <= 0:
            continue
        diff_dist = _split_by_difficulty(count_for_type, difficulty_weights)
        allocations.append({
            "template_id": t_id,
            "count": count_for_type,
            "difficulty_distribution": diff_dist,
            "points_per_question": 2.0,
        })
    topic_weights = {}
    for t in topics[:5]:
        topic_weights[t.get("name", "")] = t.get("importance", 0.2)
    return {
        "exam_title": f"{subject} 모의고사",
        "subject": subject,
        "total_questions": total,
        "total_points": total * 2.0,
        "time_limit_minutes": config.get("time_limit_minutes", 60),
        "locale": config.get("locale", "ko"),
        "category": config.get("category", "korean"),
        "type_allocations": allocations,
        "topic_weights": topic_weights,
        "passing_score": config.get("passing_score", 60.0),
        "bloom_distribution": {},
    }


def _question_types(config: dict) -> list[str]:
    """빈 유형 목록(=자동 분배 요청)이면 기본 혼합 유형으로 수렴시킨다.

    호출자가 명시적으로 유형을 지정하면 그 목록을 정확히 그대로 사용한다.
    """
    raw = config.get("question_types")
    if not isinstance(raw, list):
        return list(_DEFAULT_QUESTION_TYPES)
    q_types = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if not q_types:
        logger.info("question_types가 비어 있어 기본 혼합 유형으로 분배합니다.")
        return list(_DEFAULT_QUESTION_TYPES)
    return q_types


def _allocate_type_counts(q_types: list[str], total: int) -> dict[str, int]:
    """유형별 문항 수를 가중치 기반 비례 배분(최대 잔여법)으로 계산한다.

    - 기본 혼합 유형에는 _DEFAULT_TYPE_WEIGHTS 가중치를 적용하고,
      목록에 없는 유형은 균등 가중치로 처리한다.
    - total이 _MIN_TOTAL_FOR_TYPE_GUARANTEE(12) 이상이면 모든 유형에 최소 1문항을 보장한다.
    """
    if not q_types:
        return {}
    uniform = 1.0 / len(q_types)
    weights = [
        _DEFAULT_TYPE_WEIGHTS.get(t, uniform)
        if set(q_types) <= set(_DEFAULT_QUESTION_TYPES)
        else uniform
        for t in q_types
    ]
    weight_sum = sum(weights) or 1.0
    raw = [total * w / weight_sum for w in weights]
    counts = [int(r) for r in raw]
    # 최대 잔여법 — 소수점 잔여가 큰 유형부터 남은 문항을 배분한다
    remainder = total - sum(counts)
    order = sorted(range(len(q_types)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in range(remainder):
        counts[order[i % len(order)]] += 1
    # 충분히 큰 시험이면 모든 유형 최소 1문항 보장 — 가장 많은 유형에서 차감한다
    if total >= _MIN_TOTAL_FOR_TYPE_GUARANTEE:
        for i in range(len(counts)):
            while counts[i] < 1:
                donor = max(range(len(counts)), key=lambda j: counts[j])
                if counts[donor] <= 1:
                    break
                counts[donor] -= 1
                counts[i] += 1
    return {t: c for t, c in zip(q_types, counts)}


def _difficulty_weights(config: dict) -> dict[int, float]:
    """요청의 difficulty_distribution을 정규화해 반환한다. 비정상 값은 기본 분포로 폴백."""
    raw = config.get("difficulty_distribution")
    weights: dict[int, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                level = int(key)
                weight = float(value)
            except (ValueError, TypeError):
                continue
            if 1 <= level <= 5 and weight > 0:
                weights[level] = weight
    if not weights:
        # ExamConfig 기본값과 동일한 실전형 분포
        weights = {2: 0.2, 3: 0.35, 4: 0.3, 5: 0.15}
    total_weight = sum(weights.values())
    return {level: weight / total_weight for level, weight in weights.items()}


def _split_by_difficulty(count: int, weights: dict[int, float]) -> dict[int, int]:
    """유형별 문항 수를 난이도 분포 가중치로 쪼갠다(최대 잔여법)."""
    levels = sorted(weights)
    raw = {level: count * weights[level] for level in levels}
    split = {level: int(raw[level]) for level in levels}
    remainder = count - sum(split.values())
    order = sorted(levels, key=lambda lv: raw[lv] - split[lv], reverse=True)
    for i in range(remainder):
        split[order[i % len(order)]] += 1
    return {level: c for level, c in split.items() if c > 0}

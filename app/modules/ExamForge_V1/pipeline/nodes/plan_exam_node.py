"""시험 계획을 수립하는 노드."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json

import json
import time

from app.modules.ExamForge_V1.pipeline.state import ExamForgeState
from app.modules.ExamForge_V1.common.ai_bridge import get_planner_connector, ChapterAIRequest
from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.templates.catalog import allocation_contract
from app.modules.ExamForge_V1.pipeline.nodes._plan_prompts import PLAN_PROMPT as _PLAN_PROMPT
from app.modules.ExamForge_V1.pipeline.nodes.concept_blueprint import (
    build_question_blueprint,
    compute_answer_position_plan,
)

logger = get_logger(__name__)
_DEFAULT_QUESTION_TYPES = ["ko_multiple_choice_5"]


async def plan_exam_node(state: ExamForgeState) -> dict:
    """주제와 설정을 기반으로 시험 계획을 생성한다."""
    # 상위 노드에서 에러가 전파된 경우 즉시 반환
    if state.get("pipeline_status") == "error":
        return {}
    node_start = time.time()
    logger.info("노드 시작: plan_exam_node")
    topics = state.get("topics", [])
    config = state.get("exam_config", {})
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
    if plan is None:
        total = config.get("total_questions", 50)
        plan = _build_fallback_plan(subject, total, config, topics)
        used_fallback = True
    plan = _normalize_plan(plan, config, topics)

    logger.info("노드 완료: plan_exam_node (%.2fs)", time.time() - node_start)
    result: dict = {
        "exam_plan": plan,
        "pipeline_status": "generating",
    }
    if used_fallback:
        result["error_message"] = "시험 계획 AI 호출/파싱 실패 — 기본 계획 사용"
    return result


def _normalize_plan(
    plan: dict,
    config: dict,
    topics: list[dict] | None = None,
) -> dict:
    """작은 시험에서도 계획이 생성/커버리지 계산에 맞게 수렴하도록 보정한다."""
    normalized = dict(plan)
    # 비정수 값이 들어올 수 있으므로 변환 실패 시 내부 값으로 안전하게 폴백한다
    try:
        total = int(config.get("total_questions", normalized.get("total_questions", 0)))
    except (ValueError, TypeError):
        total = int(normalized.get("total_questions", 0) or 0)
    normalized["total_questions"] = total
    normalized["type_allocations"] = _ensure_reasoning_distribution(
        normalized.get("type_allocations", []),
        total,
    )
    normalized["topic_weights"] = _trim_topic_weights(
        normalized.get("topic_weights", {}),
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


def _ensure_reasoning_distribution(allocations: list[dict], total: int) -> list[dict]:
    """난이도 3 이상 문항이 최소 비율에 닿도록 낮은 난이도 일부를 이동한다."""
    if total < 5:
        return allocations
    adjusted = [{**alloc, "difficulty_distribution": dict(alloc.get("difficulty_distribution", {}))}
                for alloc in allocations]
    target = max(1, int(total * 0.4))
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
    per_type = total // len(q_types)
    remainder_total = total % len(q_types)
    allocations = []
    for idx, t_id in enumerate(q_types):
        count_for_type = per_type + (1 if idx < remainder_total else 0)
        # 유형별 예산을 중간 난이도(2·3·4)에 배분하고 나머지는 3에 추가
        base = count_for_type // 3
        remainder = count_for_type % 3
        diff_dist: dict[int, int] = {2: base, 3: base + remainder, 4: base}
        # 값이 0인 항목 제거 (per_type=0 등 극단적 케이스 대응)
        diff_dist = {k: v for k, v in diff_dist.items() if v > 0}
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
    """빈 유형 목록이 직접 유입돼도 기본 객관식으로 수렴시킨다."""
    raw = config.get("question_types")
    if not isinstance(raw, list):
        return list(_DEFAULT_QUESTION_TYPES)
    q_types = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if not q_types:
        logger.warning("question_types가 비어 있어 기본 유형으로 보정합니다.")
        return list(_DEFAULT_QUESTION_TYPES)
    return q_types

"""문항 생성 누락분 보충 유틸리티."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.modules.ExamForge_V1.common.ai_bridge import AIConnector
from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

GenerateChunk = Callable[
    [dict, AIConnector, str, str, asyncio.Semaphore],
    Awaitable[list[dict]],
]


async def repair_missing_questions(
    allocations: list[dict],
    topic_weights: dict[str, float],
    existing_drafts: list[dict],
    connector: AIConnector,
    source_text: str,
    locale: str,
    semaphore: asyncio.Semaphore,
    generate_chunk: GenerateChunk,
) -> list[dict]:
    """계획 대비 부족한 문항을 템플릿별로 한 번 보충 생성한다."""
    tasks = build_repair_tasks(allocations, topic_weights, existing_drafts)
    if not tasks:
        return []
    logger.info("누락 문항 보충 생성 시작: %d개 청크", len(tasks))
    results = await asyncio.gather(
        *[
            generate_chunk(t, connector, source_text, locale, semaphore)
            for t in tasks
        ],
        return_exceptions=True,
    )
    repaired: list[dict] = []
    for result in results:
        if isinstance(result, list):
            repaired.extend(result)
        elif isinstance(result, BaseException):
            logger.warning("보충 생성 중 예외 발생: %s", result)
    return trim_to_missing_quota(allocations, existing_drafts, repaired)


def build_repair_tasks(
    allocations: list[dict],
    topic_weights: dict[str, float],
    existing_drafts: list[dict],
) -> list[dict]:
    """템플릿별 부족 수량을 계산해 보충 생성 청크를 만든다."""
    existing_counts = count_by_template(existing_drafts)
    topic_names = list(topic_weights.keys()) or ["일반"]
    topic_cursor = len(existing_drafts)
    tasks: list[dict] = []
    for alloc in allocations:
        # template_id 키 누락 시 빈 문자열로 폴백해 KeyError 방지
        template_id = alloc.get("template_id", "")
        target = int(alloc.get("count", 0))
        missing = max(0, target - existing_counts.get(template_id, 0))
        difficulties = difficulty_sequence(alloc, missing)
        for difficulty in difficulties:
            topic = topic_names[topic_cursor % len(topic_names)]
            topic_cursor += 1
            tasks.append({
                "template_id": template_id,
                "topic": topic,
                "difficulty": difficulty,
                "count": 1,
            })
    return tasks


def trim_to_missing_quota(
    allocations: list[dict],
    existing_drafts: list[dict],
    repaired_drafts: list[dict],
) -> list[dict]:
    """보충 결과가 초과되면 템플릿별 부족 수량만 남긴다."""
    existing_counts = count_by_template(existing_drafts)
    # template_id 키 누락 시 빈 문자열로 폴백해 KeyError 방지
    target_counts = {a.get("template_id", ""): int(a.get("count", 0)) for a in allocations}
    accepted: list[dict] = []
    for draft in repaired_drafts:
        template_id = draft.get("template_id", "")
        current = existing_counts.get(template_id, 0)
        if current >= target_counts.get(template_id, 0):
            continue
        accepted.append(draft)
        existing_counts[template_id] = current + 1
    return accepted


def difficulty_sequence(alloc: dict, missing: int) -> list[int]:
    """배분표를 기반으로 보충 문항 난이도 순서를 만든다."""
    diff_dist = alloc.get("difficulty_distribution", {})
    sequence: list[int] = []
    for diff_level, count in diff_dist.items():
        sequence.extend([int(diff_level)] * max(0, int(count)))
    if not sequence:
        sequence = [3]
    return [sequence[i % len(sequence)] for i in range(missing)]


def count_by_template(drafts: list[dict]) -> dict[str, int]:
    """문항 초안 수를 템플릿별로 센다."""
    counts: dict[str, int] = {}
    for draft in drafts:
        template_id = draft.get("template_id", "")
        counts[template_id] = counts.get(template_id, 0) + 1
    return counts

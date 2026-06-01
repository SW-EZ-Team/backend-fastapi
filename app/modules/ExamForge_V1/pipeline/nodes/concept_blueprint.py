"""문항별 개념 청사진 생성 유틸리티."""
from __future__ import annotations

from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import bloom_for_difficulty


def build_question_blueprint(topics: list[dict], allocations: list[dict]) -> list[dict]:
    """계획된 문항 수만큼 강의·개념·난이도 슬롯을 만든다."""
    concepts = _concept_pool(topics)
    tasks = _allocation_slots(allocations)
    if not tasks:
        return []
    if not concepts:
        concepts = [{"chapter": "일반", "topic": "일반", "concept": "핵심 개념"}]
    blueprint: list[dict] = []
    for index, task in enumerate(tasks):
        concept = concepts[index % len(concepts)]
        difficulty = int(task.get("difficulty", 3))
        blueprint.append({
            "slot": index + 1,
            "template_id": task.get("template_id", ""),
            "chapter": concept["chapter"],
            "topic": concept["topic"],
            "concept": concept["concept"],
            "difficulty": difficulty,
            "bloom_level": bloom_for_difficulty(difficulty),
            "reasoning_type": _reasoning_type(difficulty, index),
        })
    return blueprint


def blueprint_prompt(slot: dict | None) -> str:
    """단일 생성 작업에 주입할 청사진 계약 문구를 만든다."""
    if not slot:
        return ""
    chapter = slot.get("chapter") or slot.get("_chapter") or "일반"
    concept = slot.get("concept") or str(slot.get("_concept_key", "핵심 개념")).split("::")[-1]
    reasoning = slot.get("reasoning_type") or slot.get("_reasoning_type") or "개념 확인"
    return (
        "\n\n[문항 blueprint 계약]\n"
        f"- 강의/챕터: {chapter}\n"
        f"- 핵심 개념: {concept}\n"
        f"- 난이도: {slot.get('difficulty', 3)}/5\n"
        f"- 인지 수준: {slot.get('bloom_level', '이해')}\n"
        f"- 추론 방식: {reasoning}\n"
        "- 이 문항은 위 핵심 개념 하나를 중심으로 출제하고, 같은 발문 구조를 반복하지 마시오.\n"
        "- 난이도 3 이상이면 개념 확인 뒤 적용/계산/비교를 한 번 더 요구하는 2단계 추론으로 작성하시오."
    )


def _concept_pool(topics: list[dict]) -> list[dict]:
    """주제 목록에서 중복 없는 개념 후보를 중요도 순으로 펼친다."""
    pool: list[dict] = []
    seen: set[str] = set()
    ordered = sorted(
        topics,
        key=lambda item: float(item.get("importance", 0.0) or 0.0),
        reverse=True,
    )
    for topic in ordered:
        topic_name = str(topic.get("name") or topic.get("title") or "일반")
        chapter = str(topic.get("chapter") or topic_name)
        for concept in _topic_concepts(topic, topic_name):
            key = f"{chapter}::{topic_name}::{concept}"
            if key in seen:
                continue
            seen.add(key)
            pool.append({"chapter": chapter, "topic": topic_name, "concept": concept})
    return pool


def _topic_concepts(topic: dict, fallback: str) -> list[str]:
    """sub_concepts/key_topics/keywords 순으로 개념 이름을 추출한다."""
    candidates: list[str] = []
    for key in ("key_topics", "sub_concepts", "keywords"):
        value = topic.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if str(item).strip())
    return candidates or [fallback]


def _allocation_slots(allocations: list[dict]) -> list[dict]:
    """유형·난이도 배분을 문항 단위 슬롯으로 펼친다."""
    slots: list[dict] = []
    for alloc in allocations:
        template_id = str(alloc.get("template_id", ""))
        for diff, count in alloc.get("difficulty_distribution", {}).items():
            for _ in range(max(0, int(count))):
                slots.append({"template_id": template_id, "difficulty": int(diff)})
    return slots


def _reasoning_type(difficulty: int, index: int) -> str:
    """난이도와 순번에 맞는 추론 목표를 반환한다."""
    if difficulty <= 2:
        return "개념 확인"
    variants = ("2단계 적용 추론", "2단계 계산/비교", "오류 원인 분석")
    return variants[index % len(variants)]

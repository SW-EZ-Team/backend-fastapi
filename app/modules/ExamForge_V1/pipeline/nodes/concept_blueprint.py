"""문항별 개념 청사진 생성 유틸리티.

plan-first 원칙:
  - num_choices : 카탈로그 spec.must_have에서 MCQ 보기 수를 결정적으로 읽어 고정
  - target_answer_position : ChapterStudio 동일 알고리즘(balanced_target_positions)으로
    AI 호출 전에 전체 슬롯에 걸쳐 균등 배정 (seed = exam_id 기반)
  - concept_key 고유성 : (concept, difficulty, reasoning_type) 조합으로 슬롯 중복 0 보장
  - answer_position_plan : 배정 결과 summary → ExamPlan에 기록해 검증 게이트에서 사용
"""
from __future__ import annotations

import hashlib

from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import bloom_for_difficulty

# 5보기 템플릿 집합 — 카탈로그 spec 없이도 결정 가능한 명시 목록
_FIVE_OPTION_TEMPLATES: frozenset[str] = frozenset([
    "ko_multiple_choice_5",
    "us_multiple_choice_5",
    "engineer_written",
    "cert_base",
])

# 기본 MCQ 보기 수: 카탈로그에서 읽지 못할 때 폴백
_DEFAULT_NUM_CHOICES = 4


def _num_choices_for_template(template_id: str) -> int:
    """템플릿 spec의 must_have에서 MCQ 보기 수를 결정적으로 반환한다.

    spec 로드가 실패하면 명시 집합 → 기본값 순으로 폴백해 항상 양의 정수를 반환한다.
    """
    try:
        from app.modules.ExamForge_V1.templates.catalog import get_template_spec
        spec = get_template_spec(template_id)
        # must_have 예: ("보기 정확히 5개", "정답 1개", ...)
        for clause in spec.must_have:
            if "5개" in clause and ("보기" in clause or "선택지" in clause):
                return 5
            if "4개" in clause and ("보기" in clause or "선택지" in clause):
                return 4
    except Exception:
        pass
    # 명시 집합으로 2차 폴백
    if template_id in _FIVE_OPTION_TEMPLATES:
        return 5
    return _DEFAULT_NUM_CHOICES


def _seed_from_key(seed_key: str) -> int:
    """파이썬 해시 랜덤화에 영향받지 않는 고정 seed를 만든다."""
    if not seed_key:
        return 0
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _balanced_target_positions(
    count: int, num_choices: int = 4, seed: int = 0
) -> list[int]:
    """count개 문항에 목표 정답 위치를 균등하게 만들고 결정적으로 섞는다.

    ChapterStudio_V1.postprocess.quiz_balance.balanced_target_positions 와
    동일한 알고리즘을 사용해 모의고사 슬롯에 재적용한다.
    """
    import random
    if count <= 0:
        return []
    positions = [idx % num_choices for idx in range(count)]
    random.Random(seed).shuffle(positions)
    return positions


def build_question_blueprint(
    topics: list[dict],
    allocations: list[dict],
    exam_id: str = "",
) -> list[dict]:
    """계획된 문항 수만큼 강의·개념·난이도·정답위치 슬롯을 만든다.

    plan-first 보장:
    1. num_choices  — 카탈로그 spec에서 결정, AI 개입 0
    2. target_answer_position — 전체 슬롯에 걸쳐 균등 배정, AI 개입 0
    3. concept_key 고유성 — (chapter::topic::concept::diff::reasoning) 조합 유일화
    """
    concepts = _concept_pool(topics)
    tasks = _allocation_slots(allocations)
    if not tasks:
        return []
    if not concepts:
        concepts = [{"chapter": "일반", "topic": "일반", "concept": "핵심 개념"}]

    seed = _seed_from_key(exam_id)

    # 1단계: 각 슬롯에 개념/메타 배정 (중복 없는 concept_key 보장)
    pre_slots: list[dict] = []
    seen_keys: set[str] = set()
    for index, task in enumerate(tasks):
        concept = concepts[index % len(concepts)]
        difficulty = int(task.get("difficulty", 3))
        reasoning = _reasoning_type(difficulty, index)
        # (chapter::topic::concept::difficulty::reasoning) 조합으로 유일화
        base_key = f"{concept['chapter']}::{concept['topic']}::{concept['concept']}"
        unique_key = _make_unique_key(base_key, difficulty, reasoning, seen_keys)
        seen_keys.add(unique_key)
        pre_slots.append({
            "slot": index + 1,
            "template_id": task.get("template_id", ""),
            "chapter": concept["chapter"],
            "topic": concept["topic"],
            "concept": concept["concept"],
            "difficulty": difficulty,
            "bloom_level": bloom_for_difficulty(difficulty),
            "reasoning_type": reasoning,
            "concept_key": unique_key,
            # num_choices는 2단계에서 채운다
            "num_choices": 0,
        })

    # 2단계: template_id → num_choices 결정적 배정
    for slot in pre_slots:
        slot["num_choices"] = _num_choices_for_template(slot["template_id"])

    # 3단계: num_choices 그룹별로 균등 정답 위치 배정
    _assign_target_positions(pre_slots, seed)

    return pre_slots


def compute_answer_position_plan(blueprint: list[dict]) -> dict[int, int]:
    """블루프린트에서 정답 위치 분포 계획을 요약한다.

    반환값: {위치(0-index): 목표 문항 수}
    ExamPlan.answer_position_plan 에 저장해 검증 게이트에서 사용한다.
    """
    plan: dict[int, int] = {}
    for slot in blueprint:
        pos = slot.get("target_answer_position")
        if pos is None:
            continue
        plan[pos] = plan.get(pos, 0) + 1
    return plan


def blueprint_prompt(slot: dict | None) -> str:
    """단일 생성 작업에 주입할 청사진 계약 문구를 만든다.

    plan-first 강제: num_choices·target_answer_position을 명시해
    AI가 보기 수·정답 위치를 스스로 결정하지 못하게 한다.
    """
    if not slot:
        return ""
    chapter = slot.get("chapter") or slot.get("_chapter") or "일반"
    concept = (
        slot.get("concept")
        or str(slot.get("concept_key", slot.get("_concept_key", "핵심 개념"))).split("::")[-1]
    )
    reasoning = slot.get("reasoning_type") or slot.get("_reasoning_type") or "개념 확인"
    num_choices: int = slot.get("num_choices") or _DEFAULT_NUM_CHOICES
    target_pos: int | None = slot.get("target_answer_position")

    lines = [
        "\n\n[문항 blueprint 계약]",
        f"- 강의/챕터: {chapter}",
        f"- 핵심 개념: {concept}",
        f"- 난이도: {slot.get('difficulty', 3)}/5",
        f"- 인지 수준: {slot.get('bloom_level', '이해')}",
        f"- 추론 방식: {reasoning}",
        f"- 보기 수: 정확히 {num_choices}개 (이 값은 고정이며 절대 바꾸지 마시오)",
    ]
    if target_pos is not None:
        lines.append(
            f"- 정답 위치: 보기 중 {target_pos}번 인덱스(0-index)에 정답을 배치하시오 "
            f"(즉 label='{target_pos + 1}'이 정답). 이 위치는 고정이며 절대 바꾸지 마시오."
        )
    lines += [
        "- 이 문항은 위 핵심 개념 하나를 중심으로 출제하고, 같은 발문 구조를 반복하지 마시오.",
        "- 난이도 3 이상이면 개념 확인 뒤 적용/계산/비교를 한 번 더 요구하는 2단계 추론으로 작성하시오.",
        "- question(stem)/choices/correct_answer/explanation만 채워라. "
        "  개수·개념·난이도·정답위치·보기수·template 결정은 절대 금지.",
    ]
    return "\n".join(lines)


# ── 내부 함수 ────────────────────────────────────────────────────────────────

def _assign_target_positions(slots: list[dict], seed: int) -> None:
    """num_choices 그룹별로 균등 정답 위치를 결정적으로 배정한다 (in-place)."""
    # num_choices 값별로 슬롯 인덱스를 모은다
    groups: dict[int, list[int]] = {}
    for idx, slot in enumerate(slots):
        nc = slot.get("num_choices", _DEFAULT_NUM_CHOICES)
        groups.setdefault(nc, []).append(idx)

    for num_choices, indices in groups.items():
        positions = _balanced_target_positions(
            len(indices), num_choices=num_choices, seed=seed
        )
        for group_pos, slot_idx in enumerate(indices):
            slots[slot_idx]["target_answer_position"] = positions[group_pos]


def _make_unique_key(
    base_key: str,
    difficulty: int,
    reasoning: str,
    seen: set[str],
) -> str:
    """base_key에 diff·reasoning 조합을 붙여 seen에 없는 유일 키를 만든다."""
    candidate = f"{base_key}::d{difficulty}::{reasoning}"
    if candidate not in seen:
        return candidate
    # 추가 suffix로 유일화 (동일 조합이 다수 슬롯에 요구될 때)
    counter = 2
    while True:
        extended = f"{candidate}::v{counter}"
        if extended not in seen:
            return extended
        counter += 1


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

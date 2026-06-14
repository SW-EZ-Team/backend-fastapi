"""문항별 개념 청사진 생성 유틸리티.

plan-first 원칙:
  - num_choices : 카탈로그 spec.must_have에서 MCQ 보기 수를 결정적으로 읽어 고정
  - target_answer_position : ChapterStudio 동일 알고리즘(balanced_target_positions)으로
    AI 호출 전에 전체 슬롯에 걸쳐 균등 배정 (seed = exam_id 기반)
  - concept_key 고유성 : (concept, difficulty, reasoning_type) 조합으로 슬롯 중복 0 보장
  - answer_position_plan : 배정 결과 summary → ExamPlan에 기록해 검증 게이트에서 사용
"""
from __future__ import annotations

import logging
import math

from app.core.planfirst.positions import (
    balanced_target_positions as _balanced_target_positions_impl,
    seed_from_key as _seed_from_key_impl,
)
from app.modules.ExamForge_V1.pipeline.nodes.question_metadata import bloom_for_difficulty

_LOG = logging.getLogger(__name__)

# 5보기 템플릿 집합 — 카탈로그 spec 없이도 결정 가능한 명시 목록
_FIVE_OPTION_TEMPLATES: frozenset[str] = frozenset([
    "ko_multiple_choice_5",
    "us_multiple_choice_5",
    "engineer_written",
    "cert_base",
])

# 기본 MCQ 보기 수: 카탈로그에서 읽지 못할 때 폴백
_DEFAULT_NUM_CHOICES = 4

# 난이도별 출제 요구사항 — 블룸 레벨이 프롬프트에서 조작적(operational)으로
# 발현되도록 레벨마다 무엇을 요구해야 하는지 명시한다. 특히 상위 레벨(4~5)이
# 정의 회상 문항으로 퇴화하는 것을 막는다 (validate_node의 난이도 발현 게이트와 쌍).
_DIFFICULTY_DIRECTIVES: dict[int, str] = {
    1: "핵심 용어·사실의 정확한 회상을 확인한다 (정의·명칭 중심 허용).",
    2: "개념의 의미를 설명·구분하게 한다 — 단순 명칭 맞히기보다 한 단계 깊게, "
       "유사 개념과의 차이를 묻는다.",
    3: "배운 개념을 새로운 상황·예시·코드에 적용해야 풀리게 한다 — "
       "'~란 무엇인가' 류 정의 회상 발문 금지.",
    4: "두 개념 비교, 코드/동작 추적, 엣지케이스·오류 원인 분석 중 하나를 반드시 요구한다 — "
       "정의 회상·단순 사실 확인 금지. 개념 식별 후 적용·비교까지 2단계 이상 추론해야 "
       "정답에 도달하도록 작성한다.",
    5: "설계 판단·트레이드오프 평가·반례 검토를 요구한다 — 출처의 여러 개념을 종합한 "
       "다단계 추론으로만 정답이 결정되게 하고, 자료 한 줄의 표면 인용만으로 풀리면 안 된다.",
}


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
    except Exception as exc:
        # 카탈로그 로드 실패는 치명적이지 않으므로 경고 후 폴백으로 진행한다
        _LOG.warning(
            "[concept-blueprint] 템플릿 카탈로그 로드 실패, 폴백 사용 — template_id=%s, error=%s",
            template_id,
            exc,
        )
    # 명시 집합으로 2차 폴백
    if template_id in _FIVE_OPTION_TEMPLATES:
        return 5
    return _DEFAULT_NUM_CHOICES


def _seed_from_key(seed_key: str) -> int:
    """파이썬 해시 랜덤화에 영향받지 않는 고정 seed를 만든다.

    app.core.planfirst.positions.seed_from_key에 위임 — 동작 무변경.
    """
    return _seed_from_key_impl(seed_key)


def _balanced_target_positions(
    count: int, num_choices: int = 4, seed: int = 0
) -> list[int]:
    """count개 문항에 목표 정답 위치를 균등하게 만들고 결정적으로 섞는다.

    ChapterStudio_V1.postprocess.quiz_balance.balanced_target_positions 와
    동일한 알고리즘이다. app.core.planfirst.positions.balanced_target_positions에
    위임해 단일 소스로 통합 — 동작 무변경.
    """
    return _balanced_target_positions_impl(count, num_choices=num_choices, seed=seed)


def build_question_blueprint(
    topics: list[dict],
    allocations: list[dict],
    exam_id: str = "",
) -> list[dict]:
    """계획된 문항 수만큼 강의·개념·난이도·정답위치 슬롯을 만든다.

    plan-first 보장:
    1. 개념 다양성 — 서로 다른 개념을 먼저 1회씩 소진한 뒤 재사용(coverage-first),
       개념당 슬롯 상한(per_concept_cap)으로 지엽 개념의 과점유 차단
    2. num_choices  — 카탈로그 spec에서 결정, AI 개입 0
    3. target_answer_position — 전체 슬롯에 걸쳐 균등 배정, AI 개입 0
    4. concept_key 고유성 — (chapter::topic::concept::diff::reasoning) 조합 유일화
    """
    concepts = _concept_pool(topics)
    tasks = _allocation_slots(allocations)
    if not tasks:
        return []
    if not concepts:
        concepts = [{"chapter": "일반", "topic": "일반", "concept": "핵심 개념"}]

    seed = _seed_from_key(exam_id)

    # 1단계: 각 슬롯에 개념을 다양성 우선(coverage-first)으로 배정한다.
    #   - 서로 다른 개념을 먼저 1회씩 모두 소진한 뒤에야 재사용한다.
    #   - 한 개념이 차지하는 슬롯 수에 상한(per_concept_cap)을 둬서
    #     지엽 개념이 핵심처럼 여러 문항을 점유하지 못하게 한다.
    #   - 개념 풀은 _concept_pool이 이미 구조적 중요도 내림차순으로 정렬했으므로,
    #     순회 순서가 곧 핵심 우선 배정이 된다.
    slot_concepts = _assign_concepts_with_chapter_quota(concepts, len(tasks))

    # 2단계: 각 슬롯에 개념/메타 배정 (중복 없는 concept_key 보장)
    pre_slots: list[dict] = []
    seen_keys: set[str] = set()
    for index, task in enumerate(tasks):
        concept = slot_concepts[index]
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
            # num_choices는 3단계에서 채운다
            "num_choices": 0,
        })

    # 3단계: template_id → num_choices 결정적 배정
    for slot in pre_slots:
        slot["num_choices"] = _num_choices_for_template(slot["template_id"])

    # 4단계: num_choices 그룹별로 균등 정답 위치 배정
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

    difficulty = int(slot.get("difficulty", 3) or 3)
    directive = _DIFFICULTY_DIRECTIVES.get(difficulty, _DIFFICULTY_DIRECTIVES[3])

    lines = [
        "\n\n[문항 blueprint 계약]",
        f"- 강의/챕터: {chapter}",
        f"- 핵심 개념: {concept}",
        f"- 난이도: {difficulty}/5",
        f"- 인지 수준: {slot.get('bloom_level', '이해')}",
        f"- 추론 방식: {reasoning}",
        f"- 난이도 요구사항: {directive}",
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


# 개념이 추출된 출처 필드별 가중치(과목 불문 구조적 신호).
# 핵심 주제(key_topics)에 가까울수록 높고, 말단 키워드(keywords)일수록 낮다.
# 특정 과목·도메인 단어가 아니라 "어느 필드에서 왔는가"라는 구조만 본다.
_FIELD_WEIGHT: dict[str, float] = {
    "key_topics": 1.0,
    "sub_concepts": 0.7,
    "keywords": 0.4,
}
# 한 리스트 안에서 말단으로 갈수록 우선순위를 깎는 감쇠 폭.
# 같은 리스트의 첫 항목 대비 마지막 항목이 이만큼까지 낮아질 수 있다.
# (지엽/저빈도 개념 가중치 하향 — 완전 배제는 아님)
_POSITION_DECAY = 0.5


def _concept_pool(topics: list[dict]) -> list[dict]:
    """주제 목록에서 중복 없는 개념 후보를 구조적 중요도 내림차순으로 펼친다.

    과목 불문(subject-agnostic) 구조적 신호만으로 핵심/지엽을 구분한다:
      - topic.importance     : 주제 단위 중요도(있으면 가산)
      - 출처 필드 tier        : key_topics > sub_concepts > keywords (_FIELD_WEIGHT)
      - 리스트 내 위치         : 앞쪽=핵심, 말단=지엽(_POSITION_DECAY로 감쇠)
      - 개념 출현 빈도         : 여러 주제/리스트에 반복 등장하면 핵심으로 가산

    특정 과목 단어를 하드코딩하지 않으며, 점수가 높은 개념이 슬롯 배정에서
    먼저 소진되도록 정렬만 한다(배제·삭제 없음 — 좁은 소스에서도 모두 쓰일 수 있음).
    """
    # 1차 패스: 후보 수집 + 출현 빈도 집계. concept 텍스트 기준으로 빈도를 센다.
    raw: list[dict] = []
    seen: set[str] = set()
    freq: dict[str, int] = {}
    for topic in topics:
        topic_name = str(topic.get("name") or topic.get("title") or "일반")
        chapter = str(topic.get("chapter") or topic_name)
        importance = float(topic.get("importance", 0.0) or 0.0)
        for concept, field_weight, position_weight in _topic_concepts(topic, topic_name):
            key = f"{chapter}::{topic_name}::{concept}"
            # 빈도는 중복 키 제거 전에 세어 같은 개념의 반복 등장을 핵심 신호로 본다
            freq[concept] = freq.get(concept, 0) + 1
            if key in seen:
                continue
            seen.add(key)
            raw.append({
                "chapter": chapter,
                "topic": topic_name,
                "concept": concept,
                "_importance": importance,
                "_field_weight": field_weight,
                "_position_weight": position_weight,
                "_order": len(raw),  # 원래 등장 순서 — 타이브레이커(안정 정렬)
            })

    # 2차 패스: 구조적 우선순위 점수 계산.
    #   importance(주제) + 필드 tier + 위치 + log 스케일 빈도 가산.
    #   빈도는 과하게 지배하지 않도록 log로 눌러 반영한다.
    for item in raw:
        frequency = freq.get(item["concept"], 1)
        item["_priority"] = (
            item["_importance"]
            + item["_field_weight"]
            * item["_position_weight"]
            + math.log1p(frequency - 1) * 0.3
        )

    # 점수 내림차순 정렬. 점수가 같으면 원래 등장 순서를 유지(결정적·안정적).
    ordered = sorted(raw, key=lambda it: (-it["_priority"], it["_order"]))

    # 내부 점수 필드는 제거하고 기존 인터페이스(chapter/topic/concept)만 노출한다.
    return [
        {"chapter": it["chapter"], "topic": it["topic"], "concept": it["concept"]}
        for it in ordered
    ]


def _topic_concepts(topic: dict, fallback: str) -> list[tuple[str, float, float]]:
    """key_topics/sub_concepts/keywords에서 (개념, 필드가중치, 위치가중치)를 추출한다.

    - 필드가중치: _FIELD_WEIGHT — 핵심 필드일수록 높다.
    - 위치가중치: 같은 리스트 안에서 앞쪽=1.0, 말단으로 갈수록 _POSITION_DECAY까지 감쇠.
      말단 키워드에만 등장하는 지엽 개념의 우선순위를 낮추기 위함이다.
    """
    candidates: list[tuple[str, float, float]] = []
    for field in ("key_topics", "sub_concepts", "keywords"):
        value = topic.get(field)
        if not isinstance(value, list):
            continue
        names = [str(item) for item in value if str(item).strip()]
        field_weight = _FIELD_WEIGHT.get(field, 0.4)
        count = len(names)
        for idx, name in enumerate(names):
            # 단일 항목 리스트는 감쇠 0(위치가중치 1.0). 여러 항목이면 선형 감쇠.
            if count <= 1:
                position_weight = 1.0
            else:
                position_weight = 1.0 - (_POSITION_DECAY * idx / (count - 1))
            candidates.append((name, field_weight, position_weight))
    if not candidates:
        # 개념이 하나도 없으면 주제명 자체를 단일 핵심 개념으로 본다
        return [(fallback, _FIELD_WEIGHT["key_topics"], 1.0)]
    return candidates


def _assign_concepts_with_chapter_quota(
    concepts: list[dict], slot_count: int
) -> list[dict]:
    """슬롯을 챕터별 쿼터로 먼저 나눈 뒤, 챕터 내부에서 개념 다양성을 배정한다.

    챕터 간 우선 분배 → 챕터 내 개념 다양성, subject-agnostic(chapter 메타로만).
    concepts는 _concept_pool이 이미 중요도 내림차순으로 정렬한 상태라고 가정한다.
    """
    if not concepts or slot_count <= 0:
        return []

    # 챕터 순서 = concepts에서 처음 등장한 위치(importance 랭킹, 결정적)
    chapter_order: list[str] = []
    chapter_groups: dict[str, list[dict]] = {}
    for concept in concepts:
        chapter = str(concept.get("chapter") or "일반")
        if chapter not in chapter_groups:
            chapter_order.append(chapter)
            chapter_groups[chapter] = []
        chapter_groups[chapter].append(concept)

    c = len(chapter_order)
    if c == 0:
        return []

    quotas: dict[str, int] = {ch: 0 for ch in chapter_order}
    if c <= slot_count:
        base = slot_count // c
        remainder = slot_count - base * c
        for chapter in chapter_order:
            quotas[chapter] = base
        for chapter in chapter_order[:remainder]:
            quotas[chapter] += 1
    else:
        for chapter in chapter_order[:slot_count]:
            quotas[chapter] = 1

    assigned: list[dict] = []
    for chapter in chapter_order:
        quota = quotas[chapter]
        if quota <= 0:
            continue
        chapter_concepts = chapter_groups[chapter]
        assigned.extend(_assign_concepts_to_slots(chapter_concepts, quota))

    return assigned


def _assign_concepts_to_slots(concepts: list[dict], slot_count: int) -> list[dict]:
    """슬롯에 개념을 다양성 우선(coverage-first)으로 배정한다.

    배정 규칙(subject-agnostic):
      1. 서로 다른 개념을 우선순위 순서로 1회씩 모두 소진한 뒤에야 재사용한다
         (한 라운드 = 전체 개념 1순회). 지엽 개념이 핵심처럼 연속 점유하지 못한다.
      2. 한 개념이 차지하는 슬롯 수에 상한(per_concept_cap)을 둔다:
             cap = max(1, ceil(slot_count / distinct_concepts))
         단 개념이 충분(distinct >= slot_count)하면 cap=1로 묶어 반복을 원천 차단한다.
      3. 개념이 정말 적으면(좁은 소스) cap 한도 내에서 균등 분산만 한다
         (source_capacity 캡과 정합 — 억지 반복 최소화).

    concepts는 _concept_pool이 이미 중요도 내림차순으로 정렬한 상태라고 가정한다.
    """
    if not concepts:
        return []
    distinct = len(concepts)
    if distinct >= slot_count:
        # 개념이 슬롯보다 많거나 같다 → 서로 다른 개념만으로 모두 채운다(반복 0).
        # 우선순위 상위 개념부터 slot_count개를 그대로 쓴다.
        return [concepts[i] for i in range(slot_count)]

    # 개념 < 슬롯 → 개념당 상한을 두고 라운드로빈으로 균등 분산한다.
    per_concept_cap = max(1, math.ceil(slot_count / distinct))
    assigned: list[dict] = []
    used_count = [0] * distinct
    # cap 한도 내에서 라운드를 돌며 한 개념씩 채운다. 한 라운드에 모든 개념이
    # 1회씩 배정되므로 같은 개념이 연속/과반 점유하는 일이 없다.
    while len(assigned) < slot_count:
        progressed = False
        for i in range(distinct):
            if len(assigned) >= slot_count:
                break
            if used_count[i] >= per_concept_cap:
                continue
            assigned.append(concepts[i])
            used_count[i] += 1
            progressed = True
        # 모든 개념이 cap에 도달했는데 슬롯이 남으면 cap을 1 올려 계속 채운다
        # (이론상 ceil 공식상 도달하지 않지만, 방어적으로 무한루프를 막는다).
        if not progressed:
            per_concept_cap += 1
    return assigned


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

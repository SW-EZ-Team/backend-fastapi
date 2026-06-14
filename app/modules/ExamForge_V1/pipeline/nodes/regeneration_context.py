"""재생성(보충) 시 중복을 직접 줄이기 위한 프롬프트 컨텍스트 빌더.

문제
----
좁은 소스에서 retry 보충 생성이 단순 재호출이면 모델이 직전과 동일한 발문을
다시 만들어 dedup이 또 드롭한다(비수렴). 핵심 해법은 프롬프트에 "이미 나온 것"을
직접 알려 다른 축으로 출제하도록 유도하는 것이다.

이 모듈은 기존 채택 문항에서 다음을 추출해 프롬프트 절(clause)로 만든다:
  (1) 이미 채택된 stem 요약 (앞부분 발췌)
  (2) 이미 다룬 개념(concept/_concept_key) 목록
  (3) 남은 coverage slot(이 보충 청크가 노려야 할 개념/난이도/추론축)

설계 원칙(SRP, 순수 함수)
-------------------------
- IN : existing_drafts(list[dict]), task(dict, 선택)
- OUT: 프롬프트에 덧붙일 문자열(str). 기존 문항이 없으면 빈 문자열(=기존 동작).
- 부수효과·AI·인프라 의존 없음.
"""
from __future__ import annotations

# 프롬프트 비대화를 막기 위한 상한.
_MAX_STEMS = 12  # 나열할 기존 stem 최대 개수
_MAX_STEM_CHARS = 80  # stem 1개당 표시 글자수
_MAX_CONCEPTS = 20  # 나열할 기존 개념 최대 개수


def _short_stem(stem: object) -> str:
    """stem을 한 줄 요약으로 자른다."""
    text = " ".join(str(stem or "").split())
    if len(text) > _MAX_STEM_CHARS:
        return text[:_MAX_STEM_CHARS] + "…"
    return text


def _existing_stems(drafts: list[dict]) -> list[str]:
    """기존 초안에서 비어있지 않은 stem 요약 목록을 만든다(중복 제거)."""
    seen: set[str] = set()
    stems: list[str] = []
    for d in drafts:
        if not isinstance(d, dict):
            continue
        short = _short_stem(d.get("stem", ""))
        if not short or short in seen:
            continue
        seen.add(short)
        stems.append(short)
        if len(stems) >= _MAX_STEMS:
            break
    return stems


def _existing_concepts(drafts: list[dict]) -> list[str]:
    """기존 초안에서 이미 다룬 개념 이름 목록을 만든다(중복 제거)."""
    seen: set[str] = set()
    concepts: list[str] = []
    for d in drafts:
        if not isinstance(d, dict):
            continue
        # concept → _concept_key 꼬리 → topic 순으로 개념 이름을 고른다
        concept = str(d.get("concept", "") or "").strip()
        if not concept:
            ck = str(d.get("_concept_key", "") or d.get("concept_key", "") or "")
            concept = ck.split("::")[-1].strip() if ck else ""
        if not concept:
            concept = str(d.get("topic", "") or "").strip()
        if not concept or concept in seen:
            continue
        seen.add(concept)
        concepts.append(concept)
        if len(concepts) >= _MAX_CONCEPTS:
            break
    return concepts


def build_avoidance_clause(
    existing_drafts: list[dict],
    task: dict | None = None,
) -> str:
    """이미 채택된 stem·개념과 이번 청크의 coverage slot을 알리는 프롬프트 절을 만든다.

    재생성 청크에 붙여 "이미 나온 것과 다른 축으로 새 문항만 생성"하도록 유도한다.
    기존 문항이 없으면(첫 생성) 빈 문자열을 반환해 기존 동작을 그대로 보존한다.
    """
    if not isinstance(existing_drafts, list) or not existing_drafts:
        return ""
    stems = _existing_stems(existing_drafts)
    concepts = _existing_concepts(existing_drafts)
    if not stems and not concepts:
        return ""

    lines = [
        "\n\n[중복 회피 — 이미 출제된 문항과 반드시 다른 문항을 생성하시오]",
        "아래는 이번 시험에 이미 채택된 문항/개념이다. 같은 발문 구조·같은 개념을 "
        "표현만 바꿔 반복하지 말고, 다른 개념·다른 적용 사례·다른 추론 축으로 출제하시오.",
    ]
    if stems:
        lines.append("- 이미 나온 발문(요약):")
        lines.extend(f"  · {s}" for s in stems)
    if concepts:
        joined = ", ".join(concepts)
        lines.append(f"- 이미 다룬 개념: {joined}")

    # 이번 보충 청크가 노릴 남은 coverage slot(개념/난이도/추론축)을 명시한다.
    if isinstance(task, dict):
        target_concept = str(
            task.get("concept", "")
            or str(task.get("_concept_key", "") or "").split("::")[-1]
        ).strip()
        reasoning = str(task.get("reasoning_type", "") or task.get("_reasoning_type", "")).strip()
        difficulty = task.get("difficulty")
        slot_parts: list[str] = []
        if target_concept:
            slot_parts.append(f"개념='{target_concept}'")
        if difficulty is not None:
            slot_parts.append(f"난이도={difficulty}")
        if reasoning:
            slot_parts.append(f"추론축='{reasoning}'")
        if slot_parts:
            lines.append(
                "- 이번 문항이 채울 빈 슬롯: " + ", ".join(slot_parts)
                + " — 위 '이미 나온' 목록과 겹치지 않는 새 각도로 출제하시오."
            )
    return "\n".join(lines)

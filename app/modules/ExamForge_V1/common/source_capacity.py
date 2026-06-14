"""소스 폭 기반 유효 목표 문항 수(effective target) 산정 모듈.

목적
----
사용자가 좁은 자료(예: 단일 챕터 12슬라이드)로 20문항 같은 큰 시험을 요청하면,
자료에서 뽑을 수 있는 고유 개념이 부족해 동일 발문이 반복 생성된다. dedup이
중복을 거의 전부 드롭하고 재생성도 같은 문항만 만들어 비수렴 → 0문항 FAILED.

이 모듈은 요청 문항 수(requested_count)와 별개로 **소스 폭으로 산정한 상한
(effective_target_count)** 을 계산한다. 계획 단계에서 effective target만큼만
슬롯/배분을 만들면 dedup 비수렴을 근본적으로 피한다.

설계 원칙(라이브러리형 모듈, SRP)
--------------------------------
- IN : requested_count(int), source_text(str), topics(list[dict])
- OUT: effective_target_count(int) — 1..requested_count 범위로 캡된 값
- 부수효과 없음(순수 함수). 인프라/AI 의존 없음.
- 넓은 소스(개념·길이 충분)면 capacity >= requested 라 캡이 requested 그대로 →
  기존 동작 무변경(회귀 0).

폴백/에러 정책
--------------
- topics/source_text가 비어도 예외를 던지지 않고 보수적 하한(_ABSOLUTE_FLOOR)로 수렴.
- 모든 입력 타입 방어(스칼라/None 혼입 시 0 또는 빈 컬렉션으로 정규화).
"""
from __future__ import annotations

from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# capacity 산정에 쓰는 상수 — 조정 시 narrow-source 캡의 강도가 바뀐다.
# 자료가 아무리 좁아도 최소 이만큼은 출제 시도한다(너무 작은 캡으로 인한 과잉 차단 방지).
_ABSOLUTE_FLOOR = 5
# 고유 개념 1개당 만들 수 있다고 보는 변별 가능한 문항 수.
# 같은 개념이라도 난이도/추론축(개념확인·적용·분석)을 달리하면 서로 다른 문항이
# 가능하므로 1개념 = 2문항으로 본다. (concept_blueprint의 reasoning_type 3종과 정합)
_QUESTIONS_PER_CONCEPT = 2
# 슬라이드/세그먼트 1개당 만들 수 있다고 보는 문항 수(개념 추출이 빈약할 때의 2차 신호).
_QUESTIONS_PER_SEGMENT = 1
# source_text 글자수 기반 상한 — 자료가 짧으면 개념 추출과 무관하게 물리적으로
# 출제 가능한 문항이 적다. 약 N자당 1문항으로 환산한다.
_CHARS_PER_QUESTION = 220


def _coerce_int(value: object, default: int = 0) -> int:
    """스칼라/None/문자열 혼입을 안전하게 정수로 변환한다."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return default


def count_distinct_concepts(topics: list[dict] | None) -> int:
    """topics에서 중복 없는 고유 개념 수를 센다.

    parse_source_node가 추출한 topics의 sub_concepts/key_topics/keywords와
    주제명 자체를 모두 모아 중복 제거한 집합 크기를 반환한다.
    concept_blueprint._concept_pool와 동일한 신호원을 쓰되, 여기서는 개수만 센다.
    """
    if not isinstance(topics, list):
        return 0
    seen: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        name = str(topic.get("name") or topic.get("title") or "").strip()
        chapter = str(topic.get("chapter") or name).strip()
        has_concept = False
        for key in ("key_topics", "sub_concepts", "keywords"):
            value = topic.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                concept = str(item).strip()
                if not concept:
                    continue
                seen.add(f"{chapter}::{name}::{concept}")
                has_concept = True
        # 하위 개념이 하나도 없으면 주제명 자체를 1개 개념으로 센다
        if not has_concept and (name or chapter):
            seen.add(f"{chapter}::{name}::__topic__")
    return len(seen)


def count_source_segments(topics: list[dict] | None) -> int:
    """topics에서 서로 다른 챕터/슬라이드(세그먼트) 수를 센다.

    chapter 필드가 있으면 그 고유 개수를, 없으면 주제 개수를 세그먼트 수로 본다.
    단일 챕터(좁은 소스)면 1에 가까운 값이 나온다.
    """
    if not isinstance(topics, list):
        return 0
    chapters: set[str] = set()
    topic_count = 0
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        topic_count += 1
        chapter = str(topic.get("chapter") or "").strip()
        if chapter:
            chapters.add(chapter)
    return len(chapters) if chapters else topic_count


def source_capacity(
    source_text: str,
    topics: list[dict] | None,
) -> int:
    """소스가 변별 가능한 고유 문항을 몇 개까지 지탱하는지 추정한다.

    세 신호의 최댓값을 capacity로 삼되 절대 하한(_ABSOLUTE_FLOOR)을 보장한다:
      1) 고유 개념 수 × _QUESTIONS_PER_CONCEPT
      2) 세그먼트(챕터/슬라이드) 수 × _QUESTIONS_PER_SEGMENT
      3) source_text 길이 ÷ _CHARS_PER_QUESTION — 세그먼트 ≥ 2 일 때만 max에 포함

    개념 폭을 1차 신호로 삼고, 글자수 신호는 **여러 세그먼트(넓은 소스)일 때만**
    보조로 인정한다. 단일 챕터의 장황한 내레이션이 글자수만으로 capacity를 부풀려
    좁은 소스인데도 캡이 안 걸리는 회귀를 막기 위함이다.
    (실측: BST 단일챕터 12슬라이드 본문이 len//220≈20으로 캡을 무력화한 사례.)
    """
    concept_capacity = count_distinct_concepts(topics) * _QUESTIONS_PER_CONCEPT
    segment_count = count_source_segments(topics)
    segment_capacity = segment_count * _QUESTIONS_PER_SEGMENT
    text = source_text if isinstance(source_text, str) else ""
    signals = [concept_capacity, segment_capacity]
    # parse가 개념을 빈약하게 뽑아도 여러 챕터면 넓은 소스로 인정해 캡을 풀어주되,
    # 단일 세그먼트면 길이가 길어도(장황한 한 주제) 개념 폭으로만 capacity를 본다.
    if segment_count >= 2:
        signals.append(len(text) // _CHARS_PER_QUESTION)
    capacity = max(signals)
    return max(_ABSOLUTE_FLOOR, capacity)


def effective_target_count(
    requested_count: int,
    source_text: str,
    topics: list[dict] | None,
) -> int:
    """요청 문항 수를 소스 폭 상한으로 캡한 유효 목표 문항 수를 반환한다.

    - 넓은 소스: capacity >= requested → requested 그대로 반환(기존 동작 무변경).
    - 좁은 소스: capacity < requested → capacity로 캡(중복 비수렴 회피).
    - 항상 1 이상, requested 이하.

    requested_count 자체는 호출자가 메타로 보존한다(사용자에게 "요청 20 / 생성 N" 표기).
    """
    requested = _coerce_int(requested_count, default=0)
    if requested <= 0:
        return 0
    capacity = source_capacity(source_text, topics)
    effective = min(requested, capacity)
    effective = max(1, effective)
    if effective < requested:
        logger.info(
            "effective_target_count: 소스 폭 캡 적용 — 요청 %d → 유효 %d "
            "(capacity=%d, 개념=%d, 세그먼트=%d, 길이=%d자)",
            requested,
            effective,
            capacity,
            count_distinct_concepts(topics),
            count_source_segments(topics),
            len(source_text) if isinstance(source_text, str) else 0,
        )
    return effective

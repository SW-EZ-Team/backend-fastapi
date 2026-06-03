"""커리큘럼 블루프린트 — AI가 개입하지 않는 결정적 슬롯 설계.

plan-first 원칙의 핵심 모듈이다. 입력(subject, difficulty, N, detected_topics)을
받아 길이 정확히 N인 ChapterSlot 리스트를 결정적으로 생성한다.

AI는 이 블루프린트가 확정한 슬롯 구조 안에서 텍스트(title/summary/learning_goal/
key_topics 문구)만 채운다. 챕터 개수·순서·단계역할·주제범위는 여기서만 결정된다.
동일 입력 → 동일 블루프린트(재현성 보장).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.modules.ChapterStudio_V1.app.curriculum_stages import STAGES
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_for

# 커리큘럼 허용 강의 수 — Spring 계약(1~30)과 일치, 운영·프리뷰 양 경로에서 사용
CURRICULUM_MIN_LESSONS: int = 1
CURRICULUM_MAX_LESSONS: int = 30

# 슬라이드 수·예상 시간 결정적 기본값
_DEFAULT_SLIDE_COUNT: int = 12
_DEFAULT_ESTIMATED_MINUTES: int = 30

# 역할 배분 기준: 전체 N강 중 위치 비율로 진행 역할을 결정적으로 배정한다
# (0.0 ~ 1.0 구간 경계, 우측 경계 포함)
_ROLE_BREAKPOINTS: tuple[tuple[float, str], ...] = (
    (0.10, "도입"),   # 앞 10%  — 전체 그림·맥락 소개
    (0.35, "탐구"),   # 10~35%  — 핵심 개념·원리 탐구
    (0.65, "심화"),   # 35~65%  — 적용·심화·비교
    (0.85, "적용"),   # 65~85%  — 실전·프로젝트·종합
    (1.00, "마무리"), # 85~100% — 평가·복습·정리
)


@dataclass(frozen=True)
class ChapterSlot:
    """AI가 채울 슬롯 한 칸의 설계 계약이다.

    AI는 이 슬롯의 topic_scope·stage·role을 바꿀 수 없다.
    허용 작업: title, summary, learning_goal, key_topics 문구 작성.
    """

    order: int              # 1-based 순번 (1..N 연속 보장)
    stage: str              # STAGES에서 선택된 학습 단계 이름
    topic_scope: str        # 이 슬롯이 다뤄야 할 주제 범위
    role: str               # 진행 역할 (도입/탐구/심화/적용/마무리)
    slide_count: int        # 슬라이드 수 기본값 (범위: 10~15)
    estimated_minutes: int  # 예상 소요 시간(분) 기본값 (범위: 20~60)
    key_topics: list[str] = field(default_factory=list)  # 3~5개 주제어 힌트


def build_curriculum_blueprint(
    *,
    subject: str,
    difficulty: str = "medium",
    lesson_count: int,
    detected_topics: list[str] | None = None,
    template_key: str = "foundation",
) -> list[ChapterSlot]:
    """결정적 커리큘럼 블루프린트를 생성한다.

    동일 입력은 항상 동일한 슬롯 리스트를 반환한다(AI 미관여, 랜덤 없음).
    반환 리스트의 길이는 정확히 lesson_count다.

    Args:
        subject: 과목명 (튜터 블루프린트 매핑·기본 주제 범위에 사용)
        difficulty: 난이도 레이블 ('easy'/'medium'/'hard')
        lesson_count: 생성할 강의 수 (CURRICULUM_MIN~MAX 범위)
        detected_topics: PDF/텍스트 분석으로 추출된 실제 주제 목록
        template_key: tutor_blueprints 매핑 키 (없으면 'foundation')

    Returns:
        길이 lesson_count인 ChapterSlot 리스트 (order 1..N 연속)
    """
    _validate_lesson_count(lesson_count)
    n = lesson_count
    topics = _resolve_topics(subject, detected_topics, n)
    bp = blueprint_for(template_key)

    slots: list[ChapterSlot] = []
    for i in range(n):
        order = i + 1
        stage = _pick_stage(i, n)
        role = _pick_role(i, n)
        topic_scope = _pick_topic_scope(i, n, topics, stage, bp.lens)
        key_hints = _build_key_hints(stage, topic_scope, bp.lens)
        slots.append(
            ChapterSlot(
                order=order,
                stage=stage,
                topic_scope=topic_scope,
                role=role,
                slide_count=_DEFAULT_SLIDE_COUNT,
                estimated_minutes=_DEFAULT_ESTIMATED_MINUTES,
                key_topics=key_hints,
            )
        )
    return slots


# ---------------------------------------------------------------------------
# 내부 결정적 헬퍼 함수들 — 모두 순수 함수(입력 고정 시 출력 고정)
# ---------------------------------------------------------------------------


def _validate_lesson_count(n: int) -> None:
    """허용 범위를 벗어난 강의 수를 즉시 차단한다."""
    if not (CURRICULUM_MIN_LESSONS <= n <= CURRICULUM_MAX_LESSONS):
        raise ValueError(
            f"lesson_count는 {CURRICULUM_MIN_LESSONS}~{CURRICULUM_MAX_LESSONS} 범위여야 한다. "
            f"받은 값: {n}"
        )


def _pick_stage(slot_index: int, n: int) -> str:
    """슬롯 인덱스를 15단계 STAGES에 결정적으로 매핑한다.

    N=15: 1:1 매핑
    N<15: 15단계를 균등 슬라이스로 N개 선택 (floor(index * 15 / N))
    N>15: 결정적 순환 — 15단계를 반복하되 stage_index = slot_index % 15
          (30강이면 각 단계가 정확히 2회, 28강이면 앞 13단계가 2회·뒤 2단계가 1회)
    """
    total_stages = len(STAGES)
    if n <= total_stages:
        # 균등 슬라이스: 슬롯을 0..n-1로 0..14 구간에 고르게 매핑
        stage_index = math.floor(slot_index * total_stages / n)
        stage_index = min(stage_index, total_stages - 1)
    else:
        # N>15: 순환 — 단계를 반복해 커버
        stage_index = slot_index % total_stages
    return STAGES[stage_index]


def _pick_role(slot_index: int, n: int) -> str:
    """전체 강의 수 대비 위치 비율로 진행 역할을 결정적으로 배정한다."""
    ratio = slot_index / max(n - 1, 1)
    for threshold, role_name in _ROLE_BREAKPOINTS:
        if ratio <= threshold:
            return role_name
    return "마무리"  # 방어적 폴백 (정상 경로에서는 도달하지 않음)


def _resolve_topics(
    subject: str,
    detected_topics: list[str] | None,
    n: int,
) -> list[str]:
    """슬롯 분배에 쓸 주제 풀을 확정한다.

    detected_topics가 있으면 그걸 사용하고, 없으면 subject 기반 기본 주제를
    생성해 반환한다. 반환 길이는 최소 1이다.
    """
    if detected_topics and len(detected_topics) >= 1:
        return list(detected_topics)
    # subject 기반 기본 주제 풀 — 학습 흐름을 반영한 4개 범주
    return [
        f"{subject} 기초",
        f"{subject} 핵심 원리",
        f"{subject} 실전 적용",
        f"{subject} 심화·정리",
    ]


def _pick_topic_scope(
    slot_index: int,
    n: int,
    topics: list[str],
    stage: str,
    lens: str,
) -> str:
    """슬롯에 배정할 주제 범위를 결정적으로 선택한다.

    topics 풀을 N개 슬롯에 균등 분배 — floor(slot_index * len(topics) / n).
    같은 주제 풀 항목이 여러 슬롯에 배정될 수 있다(N > len(topics)인 경우 정상).
    stage 정보를 덧붙여 '단계+주제' 범위를 명확히 한다.
    """
    pool_size = len(topics)
    topic_index = math.floor(slot_index * pool_size / n)
    topic_index = min(topic_index, pool_size - 1)
    base_topic = topics[topic_index]
    return f"{base_topic} · {stage}"


def _build_key_hints(stage: str, topic_scope: str, lens: str) -> list[str]:
    """슬롯의 key_topics 힌트를 결정적으로 생성한다 (3개 고정).

    AI에게 전달하는 가이드라인이지 AI가 최종 문구를 채울 힌트다.
    lens(관점)·stage·topic_scope에서 유도한다.
    """
    return [stage, lens.split("·")[0].strip(), topic_scope.split("·")[0].strip()]

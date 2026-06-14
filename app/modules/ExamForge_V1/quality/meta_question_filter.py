"""시험 메타 문항(시험 그 자체에 대한 문항) 결정론적 차단 필터.

프롬프트 금지 규칙만으로는 LLM이 "이 모의고사는 몇 문항으로 구성되어 있는가?" 같은
메타 문항을 간헐적으로 생성하는 문제를 막지 못한다. 생성 직후 stem을 정규식으로
검사해 메타 문항을 탈락시키고, 기존 보충 생성 경로(repair_missing_questions)가
탈락분을 과목 내용 문항으로 다시 채우게 한다.

IN : 문항 초안 dict 리스트 (stem 필드 검사)
OUT: (통과 문항 리스트, 탈락 문항 stem 요약 리스트)
"""
from __future__ import annotations

import re

from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# 자기 참조(이/본/해당 + 시험·모의고사·문제지) — 단어 경계를 강제해
# "다음과 같이 시험 데이터를…" 처럼 앞 단어 끝의 '이'가 오탐되는 것을 막는다.
# '본'은 동사 활용("어제 본 시험에서 평균 점수는?" 같은 통계 문항)과 충돌하므로
# stem 시작 위치에서만 자기 참조로 인정한다.
_SELF_REF = (
    r"(?:(?:^|[\s\(\[\{'\"「『])(?:이|해당)|^\s*['\"「『\(\[]?\s*본)"
    r"\s*(?:모의고사|시험지|문제지|시험)"
)

# 메타 문항 판정 정규식 — stem에 하나라도 걸리면 탈락.
#
# 정밀도 우선 원칙: 시험을 소재로 한 정당한 과목 문항(교육평가의 '문항 수와 신뢰도',
# 수능/자격시험 대비 강의의 '응시 시간·출제 범위', 수학의 '배점 계산',
# 프로그래밍의 "this test" 등)을 오탐하지 않도록, 넓은 단어(배점·응시·문항 수·합격 등)는
# 반드시 자기 참조(이/본/해당 + 시험·모의고사)와 결합해야만 메타로 판정한다.
# 오탐은 validate_node 거부 루프 + 보충 생성 비용으로 직결되므로 표준은 보수적 통과다.
_META_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # "이 모의고사는 총 몇 문항…", "이 시험의 합격 기준 점수는?", "본 문제지의 배점 방식은?"
        rf"{_SELF_REF}[^\n]*?(?:문항|배점|점수|구성|시간|합격|응시|난이도|유형|범위|과목|몇)",
        # "이 문제의 배점은?" — 자기 참조가 문항 단위인 경우
        r"(?:^|[\s\(\[\{'\"「『])(?:이|본|해당)\s*(?:문제|문항)의?\s*배점",
        # 영어 메타 — "this test"는 프로그래밍(단위 테스트) 오탐이 있어 exam/quiz만 잡는다
        r"this\s+(?:exam|quiz|mock\s+exam)\b",
        r"how\s+many\s+questions[^\n]*\b(?:exam|test|quiz|paper)\b",
        r"passing\s+score\s+(?:of|for)\s+this\b",
    )
)


def is_meta_question(stem: str) -> bool:
    """stem이 시험 메타 문항 패턴에 해당하는지 판정한다."""
    if not stem:
        return False
    return any(pattern.search(stem) for pattern in _META_PATTERNS)


def filter_meta_questions(drafts: list[dict]) -> tuple[list[dict], list[str]]:
    """메타 문항을 걸러내고 (통과 목록, 탈락 stem 요약)을 반환한다.

    탈락 문항은 호출 측에서 보충 생성(repair) 경로로 재충전해야 한다 —
    이 필터는 절대 조용히 문항 수를 줄이는 용도로 쓰여서는 안 된다.
    """
    kept: list[dict] = []
    removed: list[str] = []
    for draft in drafts:
        stem = str(draft.get("stem", ""))
        if is_meta_question(stem):
            removed.append(stem[:60])
            continue
        kept.append(draft)
    if removed:
        logger.warning(
            "메타 문항 %d건 차단 — 보충 생성으로 재충전 필요: %s",
            len(removed),
            "; ".join(removed),
        )
    return kept, removed

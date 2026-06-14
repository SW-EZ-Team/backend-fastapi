"""슬라이드 내 퀴즈 메타 문항(강의 구조 그 자체를 묻는 문항) 결정론적 판별 필터.

프롬프트 금지 규칙(parallel_prompt_text.py 퀴즈 섹션)만으로는 LLM이
"이 강의는 총 몇 개의 슬라이드로 구성되어 있는가?" 같은 메타 퀴즈를
간헐적으로 생성하는 것을 막지 못한다. 생성 직후 question을 정규식으로 검사해
메타 퀴즈를 찾아내고, 기존 self-repair 경로(quality.check_payload → repair_payload)가
해당 slide_idx 퀴즈를 슬라이드 내용 기반 문항으로 다시 쓰게 한다.

ExamForge_V1 quality/meta_question_filter.py 의 자기참조(self-reference) 정밀도 우선
철학을 슬라이드 강의 도메인에 맞게 옮긴 것이다. 모듈 간 직접 의존 금지 규칙
(backend-fastapi CLAUDE.md) 때문에 import 하지 않고 로컬로 미러링한다.

정밀도 우선 원칙: ChapterStudio 퀴즈는 슬라이드 단위로 귀속되므로
"이 슬라이드에서 설명한 X는?" 같은 내용 참조 발문은 정상이다. 따라서
자기참조(이/해당/본 + 강의·슬라이드·퀴즈)만으로는 메타로 판정하지 않고,
반드시 구조 질의 어휘(몇·개수·번째·순서·구성·목차·제목)와 결합해야 메타로 본다.
CSS 주제의 "슬라이드 레이아웃" 같은 정당한 과목 문항은 통과해야 한다.

IN : 퀴즈 question 문자열
OUT: 메타 여부(bool) / payload 단위 메타 slide_idx 목록
"""
from __future__ import annotations

import re

# 자기 참조(이/해당 + 강의·수업·챕터·슬라이드·퀴즈) — 단어 경계를 강제해
# "...같이 강의 자료를..." 처럼 앞 단어 끝의 '이'가 오탐되는 것을 막는다.
# '본'은 동사 활용("어제 본 강의에서...")과 충돌하므로 문장 시작 위치에서만 인정한다.
_SELF_REF = (
    r"(?:(?:^|[\s\(\[\{'\"「『])(?:이|해당)|^\s*['\"「『\(\[]?\s*본)"
    r"\s*(?:강의|수업|챕터|슬라이드|퀴즈)"
)

# 메타 퀴즈 판정 정규식 — question에 하나라도 걸리면 메타.
_META_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # 자기참조 + 구조물 명사 + 구조 질의: "이 강의는 총 몇 개의 슬라이드로 구성되어 있는가",
        # "이 챕터의 퀴즈는 모두 몇 문항인가" — 구조물 명사가 끼지 않으면
        # ("이 강의에서 배운 정렬 알고리즘은 몇 개인가?" 같은 내용 문항) 통과한다.
        rf"{_SELF_REF}[^\n]*?(?:슬라이드|퀴즈|챕터|문항|페이지)[^\n]*?(?:몇|개수|구성|순서|번째)",
        # 자기참조 + 순번/목차 질의: "이 슬라이드는 몇 번째인가", "이 강의의 목차 순서는"
        rf"{_SELF_REF}[^\n]*?(?:몇\s*번째|목차)",
        # 자기참조 + 제목 질의: "이 슬라이드의 제목은 무엇인가"
        rf"{_SELF_REF}의?\s*제목(?:은|이)",
        # 자기참조 없이도 본질적 메타: "재귀는 몇 번째 슬라이드에서 다루는가"
        r"몇\s*번째\s*슬라이드",
        # "슬라이드는 총 몇 개/장인가" — 발표 기법 강의의 "슬라이드를 몇 장..." 류는
        # 조사(를/은) 불일치로 통과한다(정밀도 우선, 드문 오탐은 repair가 재작성).
        r"슬라이드\s*(?:는|가)?\s*(?:총\s*)?몇\s*(?:개|장)",
        r"(?:총|모두)\s*몇\s*(?:개|장)의?\s*슬라이드",
        # "이 퀴즈" 자기참조 + 퀴즈 자체 질의: "이 퀴즈의 정답 번호는?"
        r"(?:^|[\s\(\[\{'\"「『])(?:이|해당)\s*퀴즈[^\n]*?(?:정답|문항|번호|몇)",
        # 영어 메타 — 강의 구조 질의만 잡는다("this slide shows..." 내용 발문은 통과)
        r"how\s+many\s+slides",
        r"this\s+(?:lecture|lesson)\b[^\n]*?\bhow\s+many\b",
    )
)


def is_meta_quiz_question(question: str) -> bool:
    """question이 강의 구조 메타 퀴즈 패턴에 해당하는지 판정한다."""
    if not question:
        return False
    return any(pattern.search(question) for pattern in _META_PATTERNS)


__all__ = ["is_meta_quiz_question"]

"""AI 총평 출력 정제 — LLM 사고/스크래치패드/영문 메타 발화를 제거한다.

실측 장애(2026-06-13): analyze 모델이 한국어 총평 본문 앞뒤로 자기 사고를 누출했다.
저장된 summary 예시:
    "Total is around 750 characters. Need to trim it slightly to fit the 350-700
     range precisely.\n\n5.  **Trimming the Draft:**\n    이번 모의고사에서..."
즉 (1) 글자수 계산·초안/Trimming 같은 메타 주석, (2) '**...:**' 류 마크다운 헤더,
(3) 'N. **Label:**' 류 영문 작성 단계 라벨이 본문에 섞여 들어왔다.

이 모듈은 그런 잡텍스트를 줄 단위 휴리스틱으로 제거하고 한국어 총평 본문만 남긴다.
어떤 인프라에도 종속되지 않는 순수 함수만 둔다(테스트·재사용 용이).

공개 API:
    - sanitize_analysis(text) -> str : think 블록 + 영문 메타 라인 제거 후 본문 반환

설계 원칙:
    - 보수적 제거: 한국어가 섞인 줄은 절대 지우지 않는다(본문 손실 방지).
    - '약점주제:' 줄은 절대 건드리지 않는다(split_weak_topics가 뒤에서 파싱하는 계약 줄).
    - 전부 제거돼 본문이 비면 빈 문자열을 반환한다(호출부가 폴백 문구로 대체).
"""
from __future__ import annotations

import re

# 루트 common/ 패키지 재사용 — <think> 블록/잘린 reasoning 절단을 한 곳에서 처리한다.
from common.llm_output import strip_thinking

# 한글 음절·자모 — 이 문자가 한 글자라도 있으면 '한국어 본문 줄'로 보고 보존한다.
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")

# 파싱 계약 줄(약점주제)은 메타로 오인해 지우면 안 되므로 화이트리스트로 통과시킨다.
_WEAK_TOPIC_PREFIXES = ("약점주제:", "약점 주제:")

# 글자수 계산/길이 조정 메타 주석. 영문 모델이 분량을 자가 점검하며 누출하는 발화다.
#   "Total is around 750 characters", "Need to trim it ... 350-700 range",
#   "This is about 600 chars", "Word count: 540" 등.
_META_LENGTH = re.compile(
    r"\b("
    r"total\s+is\s+around|"
    r"this\s+is\s+(?:about|around|roughly)|"
    r"need\s+to\s+(?:trim|cut|shorten|expand|add)|"
    r"(?:character|word|char)\s*count|"
    r"\d+\s*(?:characters|chars|words)\b|"
    r"\bfit(?:s|ting)?\s+the\s+\d+\s*[-–]\s*\d+\s*(?:range|character)"
    r")",
    re.IGNORECASE,
)

# 초안/다듬기/작성단계 메타 라벨.
#   "Trimming the Draft", "Final Draft", "Let me draft", "Revised version",
#   "Here is the analysis", "Drafting the response" 등.
_META_DRAFT = re.compile(
    r"\b("
    r"trimming|drafting|draft\b|revis(?:e|ing|ed|ion)|"
    r"let\s+me\s+(?:draft|write|trim|adjust|count|check)|"
    r"here\s+is\s+(?:the|my|a)\s+(?:analysis|response|summary|draft|feedback)|"
    r"final\s+(?:version|answer|draft|output)|"
    r"now\s+i(?:'ll| will)\s+"
    r")",
    re.IGNORECASE,
)

# 'N. **Label:**' 또는 '**Label: Sublabel**' 류 영문 작성 단계 헤더(마크다운 강조 라벨).
#   "5.  **Trimming the Draft:**", "**Step 1: Overall Assessment**" 등.
# 라벨 본문에 콜론이 중간에 와도(예: 'Step 1: Overall Assessment') 매칭되도록 콜론을 허용한다.
_META_STEP_HEADER = re.compile(
    r"^\s*(?:\d+[.)]\s*)?\*{1,2}\s*[A-Za-z][A-Za-z0-9 ,:'/&-]*\s*\*{0,2}\s*$"
)

# 순수 영문 문장(한글 0개)이면서 콜론/번호로 시작하는 메타성 줄 추가 차단용.
_LATIN_ONLY = re.compile(r"^[\x00-\x7F\s]*$")

# 영문 reasoning 서두 — gemini-3.x 가 <think> 태그 없이 인라인으로 사고를 흘릴 때
# '(미응답)' 같은 한글 토큰이 섞여 있어도 이런 서두로 시작하면 메타(사고 누출)로 본다.
_REASONING_LEAD = re.compile(
    r"^(wait|so|okay|ok|hmm|well|now|first|second|third|next|then|finally|"
    r"actually|let me|let's|i should|i need|i'll|i will|i'm|i am|i think|"
    r"we should|we need|we can|the user|the student|note that|note:|"
    r"looking at|given that|since the|based on the)\b",
    re.IGNORECASE,
)


def sanitize_analysis(text: str) -> str:
    """총평 모델 응답에서 사고/스크래치패드/영문 메타 발화를 제거한다.

    처리 순서:
        1) strip_thinking — <think>...</think> 및 잘린 reasoning 서문 절단.
        2) 줄 단위 필터 — 영문 메타(글자수/초안/작성단계 라벨) 라인을 제거하되,
           한국어가 한 글자라도 있는 줄과 '약점주제:' 계약 줄은 무조건 보존한다.
        3) 앞뒤 빈 줄을 정리해 반환. 전부 제거돼 비면 빈 문자열을 반환한다.

    Returns:
        정제된 한국어 총평 본문(약점주제 줄 포함 가능). 비면 "".
    """
    if not text:
        return ""

    cleaned = strip_thinking(text)
    kept: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            # 빈 줄은 단락 구분으로 일단 보존(연속 빈 줄은 뒤에서 압축).
            kept.append("")
            continue
        if _is_contract_line(stripped):
            kept.append(line)
            continue
        if _is_meta_line(stripped):
            # 메타 라인은 통째로 버린다(글자수 계산·초안 라벨·작성단계 헤더).
            continue
        kept.append(line)

    return _collapse_blank_lines(kept).strip()


def _is_contract_line(stripped: str) -> bool:
    """시스템이 파싱하는 계약 줄(약점주제)인지 판정한다 — 절대 제거 금지."""
    return any(stripped.startswith(prefix) for prefix in _WEAK_TOPIC_PREFIXES)


def _is_meta_line(stripped: str) -> bool:
    """이 줄이 LLM 메타 발화(사고/글자수/초안/작성단계 라벨)인지 판정한다.

    한국어가 한 글자라도 있으면 원칙적으로 본문으로 보고 False를 반환하되,
    영문 reasoning 서두로 시작하고 ASCII 비중이 높은 줄(인라인 사고 누출에 한글
    토큰만 섞인 경우)은 예외적으로 메타로 본다.
    """
    # 영문 reasoning 누출('Wait, ...', 'So I should ...' 등). '(미응답)' 같은 한글이
    # 일부 섞여도, reasoning 서두 + ASCII 비중 60% 이상이면 사고 누출로 판정한다.
    if _REASONING_LEAD.match(stripped):
        ascii_count = sum(1 for ch in stripped if ord(ch) < 128)
        if ascii_count / max(1, len(stripped)) >= 0.6:
            return True
    if _HANGUL.search(stripped):
        return False
    # 'N. **Label:**' / '**Label:**' 류 영문 작성단계 헤더.
    if _META_STEP_HEADER.match(stripped):
        return True
    # 글자수 계산·길이 조정 메타 주석.
    if _META_LENGTH.search(stripped):
        return True
    # 초안/다듬기/작성단계 서술 메타.
    if _META_DRAFT.search(stripped):
        return True
    # 콜론으로 끝나는 순수 영문 라벨('Trimming the Draft:', 'Overall Assessment:').
    if _LATIN_ONLY.match(stripped) and stripped.endswith(":") and len(stripped) <= 80:
        return True
    return False


def _collapse_blank_lines(lines: list[str]) -> str:
    """연속된 빈 줄을 하나로 압축해 문단 사이 간격을 정돈한다."""
    out: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        out.append(line)
        prev_blank = is_blank
    return "\n".join(out)

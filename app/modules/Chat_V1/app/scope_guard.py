"""Chat_V1 강의 범위·환각 방어 순수 함수 모듈.

약한 텍스트 모델(codex/Qwen 등)이 강의 자료 밖 일반지식을 끌어오거나, 존재하지
않는 슬라이드를 인용하는 것을 결정적 후처리로 막는다. 모든 함수는 부수효과 없는
순수 함수라 단위 테스트가 쉽고, service.py 의 오케스트레이션과 책임이 분리된다.

공개 API:
    - SCOPE_NOTICE                : 강의 범위 밖 답변 뒤에 붙이는 한 줄 안내문
    - OUT_OF_SCOPE_REPLY          : (레거시) 과거 거절문 상수 — 과거 대화 필터링용으로만 유지
    - extract_referenced_slides   : '[슬라이드 N]' 인용을 0-based 인덱스로(상한 검증 포함)
    - build_lecture_keywords      : 강의 컨텍스트에서 매칭용 키워드 집합 생성
    - apply_hallucination_guard   : 강의와 안 겹치는 답변에 범위 밖 안내문을 덧붙임(거절 아님)
"""
from __future__ import annotations

import re

from app.modules.Chat_V1.app.schemas import ChatRequest, VoiceChatRequest

# 강의 범위 밖 질문에 대한 한 줄 안내문 — 슬라이드는 참고 자료이지 감옥이 아니다.
# 일반 지식 답변을 막지 않고, 답변 끝에 이 안내문만 덧붙인다(거절 금지 정책).
SCOPE_NOTICE: str = "이 내용은 이번 강의 범위 밖이에요."

# (레거시) 과거 거절문 — 더 이상 새 답변에 쓰지 않는다. Spring recent_qa에 남아 있는
# 과거 거절 답변을 컨텍스트에서 걸러내는 식별용으로만 유지한다.
OUT_OF_SCOPE_REPLY: str = (
    "이 강의에서는 다루지 않는 내용이에요. 관련 슬라이드를 함께 확인해 보시겠어요?"
)

# 환각 경량 가드 파라미터
# _GUARD_MIN_ANSWER_LEN: 너무 짧은 답변은 매칭 신뢰도가 낮아 가드를 적용하지 않는다.
# _GUARD_MIN_KEYWORD_LEN: 한 글자 토큰(조사·기호)은 노이즈라 키워드에서 제외한다.
_GUARD_MIN_ANSWER_LEN: int = 12
_GUARD_MIN_KEYWORD_LEN: int = 2
# 답변이 이미 거절문 계열이면 가드를 면제하기 위한 판별용 핵심 어구.
_REFUSAL_MARKERS: tuple[str, ...] = ("다루지 않는", "강의에서는", "확인해 보시")

# 슬라이드 인용 패턴 — '[슬라이드 N]' 의 N(1-based)을 추출한다.
_SLIDE_CITE_RE = re.compile(r"\[슬라이드\s+(\d+)\]")
# 키워드 토큰 추출용 — 한글/영문/숫자 연속만 토큰으로 보고 조사·기호는 분리한다.
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

# 흔한 한국어 조사 접미사 — 토큰 끝에서 떼어내 내용 어간만 남긴다('벡터는'→'벡터',
# '수를'→'수'). 긴 접미사부터 시도해 과도한 절단을 막는다.
_PARTICLE_SUFFIXES: tuple[str, ...] = (
    "에서는", "으로는", "에게서", "이라는", "라는",
    "에서", "에게", "으로", "처럼", "보다", "까지", "부터", "마다", "이나",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "나",
)
# 어간 정규화 후에도 내용성이 낮은 일반 토큰 — 환각 판별 기준에서 제외한다.
# (수·것·때 등은 어떤 강의에도 흔히 나와 매칭 신뢰도가 낮다.)
_GENERIC_STEMS: frozenset[str] = frozenset(
    {"수", "것", "때", "등", "이것", "그것", "내용", "경우", "정도", "여기", "거기"}
)


def extract_referenced_slides(answer: str, slide_count: int | None = None) -> list[int]:
    """답변 텍스트에서 '[슬라이드 N]' 패턴의 슬라이드 인덱스를 추출한다.

    중복 제거 후 오름차순으로 반환한다. 인덱스는 0-based로 변환한다.

    slide_count 가 주어지면 상한도 검증한다 — 모델이 존재하지 않는 슬라이드를
    인용(예: 슬라이드가 3개인데 [슬라이드 7])하면 그 참조는 버린다. 잘못된 슬라이드
    참조가 Spring/프론트로 흘러가 엉뚱한 자료를 띄우는 것을 막는다. slide_count 가
    None 이면 하한(idx>=0)만 검사한다(기존 동작 유지).
    """
    matches = _SLIDE_CITE_RE.findall(answer)
    seen: set[int] = set()
    result: list[int] = []
    for m in matches:
        idx = int(m) - 1  # 1-based → 0-based
        if idx < 0 or idx in seen:
            continue
        if slide_count is not None and idx >= slide_count:
            # 실제 슬라이드 수를 벗어난 인용 — 환각 참조이므로 버린다.
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)


def _to_stem(token: str) -> str:
    """토큰 끝의 흔한 한국어 조사 접미사를 떼어 내용 어간만 남긴다.

    '벡터는'→'벡터', '수를'→'수' 처럼 조사를 제거해 답변·강의 토큰이 어간 기준으로
    일치하도록 한다. 어간이 너무 짧아지면(1글자 미만) 절단 전 토큰을 그대로 둔다.
    """
    for suffix in _PARTICLE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 1:
            return token[: -len(suffix)]
    return token


def _content_stems(text: str) -> set[str]:
    """텍스트를 토큰화해 조사 제거·일반어 제외한 내용 어간 집합을 만든다."""
    stems: set[str] = set()
    for token in _TOKEN_RE.findall(text.lower()):
        stem = _to_stem(token)
        if len(stem) >= _GUARD_MIN_KEYWORD_LEN and stem not in _GENERIC_STEMS:
            stems.add(stem)
    return stems


def build_lecture_keywords(request: ChatRequest | VoiceChatRequest) -> list[str]:
    """강의 컨텍스트(제목·슬라이드·음성대본·퀴즈)에서 키워드 어간 집합을 만든다.

    환각 경량 가드가 '답변이 강의 자료와 전혀 겹치지 않는지' 판단할 때 쓰는
    내용 어간 목록이다. 조사를 떼고 일반어를 제외해 '수를'·'것이다' 같은 저내용
    토큰이 우연히 매칭되어 환각을 놓치는 것을 줄인다.
    """
    ctx = request.lecture_context
    parts: list[str] = [ctx.chapter_title]
    for slide in ctx.slides:
        parts.append(slide.title)
        parts.append(slide.content)
    if ctx.voice_scripts:
        parts.extend(ctx.voice_scripts)
    if ctx.quiz_items:
        parts.extend(ctx.quiz_items)

    keywords: set[str] = set()
    for raw in parts:
        keywords |= _content_stems(raw)
    return sorted(keywords)


def _looks_like_refusal(answer: str) -> bool:
    """답변이 표준 거절문 계열인지 핵심 어구로 판별한다(거절이면 가드 면제)."""
    return any(marker in answer for marker in _REFUSAL_MARKERS)


def apply_hallucination_guard(
    answer: str, lecture_keywords: list[str]
) -> tuple[str, bool]:
    """강의 자료와 매칭되지 않는 답변에 범위 밖 안내문을 덧붙인다(답변 교체 금지).

    슬라이드는 참고 자료다 — 강의 밖 질문도 일반 지식으로 정확히 답하되,
    학생이 강의 범위를 인지하도록 답변 끝에 SCOPE_NOTICE 한 줄만 추가한다.
    진짜 질문에 대한 거절문 교체는 하지 않는다(NEVER refuse 정책).

    안내문을 덧붙이지 않는 경우(강의 근거 답변으로 간주):
      - 답변이 비었거나 너무 짧을 때(매칭 신뢰도 낮음)
      - 답변이 이미 거절문/안내문 계열일 때(중복 방지)
      - 강의 키워드가 없을 때(비교 기준 부재 — 보수적으로 통과)
      - 슬라이드 인용([슬라이드 N])이 하나라도 있을 때(강의 근거 표식)
      - 답변 어간이 강의 키워드와 하나라도 겹칠 때

    반환: (최종 답변, 안내문 추가 여부)
    """
    stripped = answer.strip()
    if len(stripped) < _GUARD_MIN_ANSWER_LEN:
        return answer, False
    if _looks_like_refusal(stripped) or SCOPE_NOTICE in stripped:
        return answer, False
    if not lecture_keywords:
        return answer, False
    if _SLIDE_CITE_RE.search(stripped):
        return answer, False

    # 답변도 같은 방식으로 어간화해 강의 키워드 어간 집합과 교집합을 본다.
    # substring 이 아닌 어간 단위 일치라 '수를'(→'수', 일반어 제외) 같은 우연 매칭을
    # 줄이고, 조사가 다른 활용형('벡터가' vs '벡터는')은 어간으로 묶어 정상 매칭한다.
    answer_stems = _content_stems(stripped)
    if answer_stems & set(lecture_keywords):
        return answer, False
    # 강의 키워드 어간이 안 겹침 → 일반 지식 답변으로 보고 답변은 유지한 채 안내문만 덧붙인다.
    return f"{stripped}\n\n{SCOPE_NOTICE}", True

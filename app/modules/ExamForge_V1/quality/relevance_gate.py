"""문항-출처 관련성 결정론 게이트.

프롬프트의 "출처 발췌 밖 일반 상식 문항 금지" 규칙만으로는 LLM이 주제와
동떨어진 일반 상식 문항을 간헐적으로 생성하는 것을 막지 못한다. 출처 발췌와
주제 키워드로 콘텐츠 어휘 집합을 만들고, 각 문항의 토큰 겹침을 검사해
출처 무관 문항을 결정론적으로 탈락시킨다. 탈락분은 기존 재시도 경로
(validate_node → retry_router → repair/재생성)가 과목 내용 문항으로 재충전한다.

오탐 방지 원칙:
- 출처 어휘가 빈약하면(스텁 source_text 등) 게이트를 생략한다 — 어휘 부족
  상태에서 강제하면 정상 문항까지 무한 재시도로 예산을 태운다.
- 문항 토큰은 stem + 보기 + 코드 스니펫을 모두 모아 비교한다 — 코드 중심
  문항은 stem이 짧아도 코드 토큰이 출처 코드와 겹쳐 통과한다.
- 시험 상투어(다음/것은/고르시오 등)는 콘텐츠 토큰에서 제외한다.

IN : 문항 dict 리스트(stem/options/code_snippet), source_text, topics(파싱 주제)
OUT: 문항별 관련성 결함 issue 리스트 (빈 리스트 = 통과)
"""
from __future__ import annotations

import re

from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# 게이트 활성 최소 어휘 크기 — 미만이면 출처가 빈약하다고 보고 게이트를 생략한다
MIN_VOCAB_SIZE = 30

# 통과 기준: 매칭 콘텐츠 토큰 수 또는 겹침 비율 중 하나만 충족하면 통과(보수적)
_MIN_MATCHED_TOKENS = 2
_MIN_OVERLAP_RATIO = 0.15

# 한국어+영어+숫자 토큰 (코드 식별자의 언더스코어 포함)
_TOKEN_RE = re.compile(r"[가-힣a-zA-Z0-9_]+")

# 시험 발문 상투어 — 콘텐츠 판단에서 제외 (deduplicator 불용어 + 발문 보강)
_BOILERPLATE_STOPWORDS: frozenset[str] = frozenset({
    "다음", "중", "가장", "적절한", "옳은", "옳지", "않은", "것은", "것을",
    "대한", "대해", "설명", "으로", "에서", "하고", "하는", "하여", "경우",
    "문제", "문항", "고르시오", "고르면", "쓰시오", "서술하시오", "선택하시오",
    "보기", "정답", "무엇인가", "무엇", "어떤", "어느", "이유", "결과",
    "올바른", "올바르게", "틀린", "잘못된", "아닌", "모두", "각각",
    "the", "is", "are", "what", "which", "of", "to", "in", "a", "an",
    "and", "or", "for", "following", "correct", "answer",
})

# 조사·어미 접미 제거 — deduplicator._normalize_token과 같은 규칙 유지
_JOSA_SUFFIXES: tuple[str, ...] = (
    "으로", "에서", "에게", "하고", "하는", "이다", "이며",
    "을", "를", "은", "는", "이", "가", "의", "에",
)


def _normalize_token(token: str) -> str:
    """한국어 조사·어미 차이를 줄여 같은 개념 표현을 맞춘다."""
    for suffix in _JOSA_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def _content_tokens(text: str) -> set[str]:
    """텍스트에서 상투어·1글자·순수 숫자를 제외한 콘텐츠 토큰 집합을 만든다."""
    tokens: set[str] = set()
    for raw in _TOKEN_RE.findall(text.lower()):
        normalized = _normalize_token(raw)
        if len(normalized) < 2 or normalized.isdigit():
            continue
        if normalized in _BOILERPLATE_STOPWORDS:
            continue
        tokens.add(normalized)
    return tokens


def build_source_vocabulary(source_text: str, topics: list[dict]) -> set[str]:
    """출처 발췌 + 주제 메타(name/sub_concepts/keywords)에서 어휘 집합을 만든다."""
    vocab = _content_tokens(source_text or "")
    for topic in topics or []:
        if not isinstance(topic, dict):
            continue
        vocab |= _content_tokens(str(topic.get("name", "")))
        vocab |= _content_tokens(str(topic.get("chapter", "")))
        for key in ("sub_concepts", "keywords", "key_topics"):
            value = topic.get(key)
            if isinstance(value, list):
                for item in value:
                    vocab |= _content_tokens(str(item))
    return vocab


def _question_tokens(question: dict) -> set[str]:
    """관련성 비교에 쓸 문항 텍스트(stem+보기+코드) 토큰을 모은다."""
    parts: list[str] = [str(question.get("stem", ""))]
    options = question.get("options")
    if isinstance(options, list):
        for opt in options:
            if isinstance(opt, dict):
                parts.append(str(opt.get("text", "")))
            else:
                parts.append(str(opt))
    code = question.get("code_snippet")
    if code:
        parts.append(str(code))
    return _content_tokens(" ".join(parts))


def check_question_relevance(question: dict, vocabulary: set[str]) -> list[str]:
    """문항이 출처 어휘와 충분히 겹치는지 검사한다.

    Returns:
        결함 issue 리스트 — 비어 있으면 통과.
    """
    q_tokens = _question_tokens(question)
    if not q_tokens:
        # 콘텐츠 토큰이 전혀 없으면 구조 검증(빈 stem 등)이 잡을 영역이므로 통과
        return []
    matched = q_tokens & vocabulary
    ratio = len(matched) / len(q_tokens)
    if len(matched) >= _MIN_MATCHED_TOKENS or ratio >= _MIN_OVERLAP_RATIO:
        return []
    return [
        f"출처 무관 문항 의심 — 출처 어휘와 겹치는 콘텐츠 토큰 {len(matched)}개"
        f"(비율 {ratio:.2f}). 학습 자료(출처 발췌)의 개념으로 재출제 필요"
    ]


def check_questions_relevance(
    questions: list[dict],
    source_text: str,
    topics: list[dict],
) -> dict[str, list[str]]:
    """전체 문항을 관련성 검사하고 {draft_id: issues} 매핑을 반환한다.

    출처 어휘가 MIN_VOCAB_SIZE 미만이면(스텁 소스 등) 빈 매핑을 반환해
    게이트를 생략한다 — 빈약한 출처로 정상 문항을 탈락시키지 않는다.
    """
    vocabulary = build_source_vocabulary(source_text, topics)
    if len(vocabulary) < MIN_VOCAB_SIZE:
        logger.info(
            "관련성 게이트 생략 — 출처 어휘 %d개(< %d), 스텁/빈약 소스로 판단",
            len(vocabulary), MIN_VOCAB_SIZE,
        )
        return {}
    flagged: dict[str, list[str]] = {}
    for index, q in enumerate(questions):
        issues = check_question_relevance(q, vocabulary)
        if issues:
            draft_id = str(q.get("draft_id") or q.get("question_id") or index)
            flagged[draft_id] = issues
    if flagged:
        logger.warning(
            "출처 무관 의심 문항 %d건 — 재시도 경로로 전달: %s",
            len(flagged), ", ".join(flagged.keys()),
        )
    return flagged

"""문제 중복 검사 - 핑거프린트 사전 필터 + 코사인 유사도 기반.

O(n^2) 비교 비용을 줄이기 위해 정렬된 토큰 핑거프린트로 정확/근사 중복을
먼저 걸러낸 뒤, 나머지 쌍에만 코사인 유사도를 적용한다.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

_STOPWORDS: frozenset[str] = frozenset({
    "다음", "중", "가장", "적절한", "옳은", "것은", "대한", "설명",
    "으로", "에서", "하고", "하는", "하여", "경우", "문제", "고르시오",
})

_BOILERPLATE_PATTERNS: tuple[str, ...] = (
    r"다음\s*중",
    r"가장\s*적절한\s*것은",
    r"옳은\s*것은",
    r"옳지\s*않은\s*것은",
    r"설명으로\s*옳은\s*것은",
)


def _tokenize(text: str) -> list[str]:
    """텍스트를 정규화된 토큰 목록으로 변환한다."""
    text = text.lower().strip()
    tokens = re.findall(r"[가-힣a-z0-9]+", text)
    return [
        normalized for token in tokens
        if (normalized := _normalize_token(token)) and normalized not in _STOPWORDS
    ]


def _normalize_token(token: str) -> str:
    """한국어 조사·어미 차이를 줄여 같은 개념 표현을 맞춘다."""
    for suffix in ("으로", "에서", "에게", "하고", "하는", "이다", "이며", "을", "를", "은", "는", "이", "가", "의", "에"):
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[:-len(suffix)]
    return token


def _question_id(question: dict, index: int) -> str:
    """검증/초안 어느 단계에서도 안정적인 문항 식별자를 반환한다."""
    return str(question.get("question_id") or question.get("draft_id") or index)


def _question_text(question: dict) -> str:
    """의미 중복 판단에 사용할 문항 핵심 텍스트를 만든다."""
    parts = [
        str(question.get("stem", "")),
        str(question.get("topic", "")),
        str(question.get("_concept_key", "")),
    ]
    return " ".join(part for part in parts if part)


def _normalize_core(text: str) -> str:
    """숫자·상투 발문을 제거해 같은 규칙 반복을 더 잘 잡는다."""
    core = text.lower()
    for pattern in _BOILERPLATE_PATTERNS:
        core = re.sub(pattern, " ", core)
    core = re.sub(r"\d+(\.\d+)?", "<n>", core)
    core = re.sub(r"[^가-힣a-z0-9<>]+", "", core)
    return core


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    """짧은 한국어 발문 유사도를 보기 위한 문자 n-gram 집합을 만든다."""
    core = _normalize_core(text)
    if len(core) <= n:
        return {core} if core else set()
    return {core[i:i + n] for i in range(len(core) - n + 1)}


def _fingerprint(tokens: list[str]) -> str:
    """토큰 집합의 해시 핑거프린트를 생성한다 (정확 중복 탐지용)."""
    sorted_unique = sorted(set(tokens))
    return hashlib.md5("".join(sorted_unique).encode()).hexdigest()


def _token_overlap_ratio(set_a: set[str], set_b: set[str]) -> float:
    """자카드 유사도로 빠른 사전 필터링을 수행한다."""
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _cosine_similarity(counter_a: Counter, counter_b: Counter) -> float:
    """두 카운터 간 코사인 유사도를 계산한다."""
    # 교집합 키만으로 내적 계산 (all_keys 순회 대비 빠름)
    if not counter_a or not counter_b:
        return 0.0
    # 작은 쪽 기준으로 순회해 내적 계산
    if len(counter_a) > len(counter_b):
        counter_a, counter_b = counter_b, counter_a
    dot_product = sum(v * counter_b[k] for k, v in counter_a.items() if k in counter_b)
    mag_a = sum(v * v for v in counter_a.values()) ** 0.5
    mag_b = sum(v * v for v in counter_b.values()) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot_product / (mag_a * mag_b)


# 자카드 유사도가 이 값 미만이면 코사인 비교를 건너뛴다 (조기 종료)
_JACCARD_SKIP_THRESHOLD = 0.18
_CHAR_DUP_THRESHOLD = 0.58
_CONCEPT_DUP_THRESHOLD = 0.45


def check_duplicates(
    questions: list[dict],
    threshold: float = 0.62,
) -> tuple[float, list[tuple[str, str]]]:
    """문제 간 중복을 검사하고 중복 쌍을 반환한다.

    최적화:
    1. 핑거프린트 해시로 정확 중복을 O(n)에 탐지
    2. 자카드 유사도 사전 필터로 명확히 다른 쌍은 코사인 비교 생략
    3. 코사인 내적 시 작은 카운터 기준 순회

    Returns:
        (dedup_score, duplicate_pairs)
        dedup_score: 1.0이면 중복 없음, 0.0이면 전부 중복
    """
    stems = [_question_text(q) for q in questions]
    tokens_list = [_tokenize(stem) for stem in stems]
    counters = [Counter(t) for t in tokens_list]
    token_sets = [set(t) for t in tokens_list]
    fingerprints = [_fingerprint(t) for t in tokens_list]
    ngrams = [_char_ngrams(stem) for stem in stems]
    n = len(questions)
    duplicate_pairs: list[tuple[str, str]] = []

    # 핑거프린트 기반 정확 중복 빠른 탐지 (O(n) 해시 그룹화)
    fp_groups: dict[str, list[int]] = {}
    for idx, fp in enumerate(fingerprints):
        fp_groups.setdefault(fp, []).append(idx)

    # 정확 중복 쌍 수집 + 이미 처리된 쌍 기록
    exact_pairs: set[tuple[int, int]] = set()
    for indices in fp_groups.values():
        if len(indices) > 1:
            for a in range(len(indices)):
                for b in range(a + 1, len(indices)):
                    i, j = indices[a], indices[b]
                    id_i = _question_id(questions[i], i)
                    id_j = _question_id(questions[j], j)
                    duplicate_pairs.append((id_i, id_j))
                    exact_pairs.add((i, j))

    # 나머지 쌍에 대해 자카드 사전 필터 + 코사인 비교
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in exact_pairs:
                continue
            # 조기 종료: 자카드 유사도가 낮으면 코사인도 낮을 것
            jaccard = _token_overlap_ratio(token_sets[i], token_sets[j])
            char_sim = _token_overlap_ratio(ngrams[i], ngrams[j])
            concept_sim = _concept_similarity(questions[i], questions[j], jaccard)
            if max(jaccard, char_sim, concept_sim) < _JACCARD_SKIP_THRESHOLD:
                continue
            sim = _cosine_similarity(counters[i], counters[j])
            if (
                sim >= threshold
                or char_sim >= _CHAR_DUP_THRESHOLD
                or concept_sim >= _CONCEPT_DUP_THRESHOLD
            ):
                id_i = _question_id(questions[i], i)
                id_j = _question_id(questions[j], j)
                duplicate_pairs.append((id_i, id_j))

    max_pairs = n * (n - 1) / 2 if n > 1 else 1
    affected = {qid for pair in duplicate_pairs for qid in pair}
    pair_score = 1.0 - (len(duplicate_pairs) / max_pairs)
    affected_score = 1.0 - (len(affected) / n) if n else 1.0
    dedup_score = min(pair_score, affected_score)
    return max(0.0, dedup_score), duplicate_pairs


def deduplicate_questions(questions: list[dict]) -> tuple[list[dict], list[str]]:
    """중복 쌍의 뒤쪽 문항을 제거하고 제거된 문항 ID를 반환한다."""
    _, pairs = check_duplicates(questions)
    rejected = {right for _, right in pairs}
    if not rejected:
        return questions, []
    unique: list[dict] = []
    removed: list[str] = []
    for index, question in enumerate(questions):
        qid = _question_id(question, index)
        if qid in rejected:
            removed.append(qid)
            continue
        unique.append(question)
    return unique, removed


def _concept_similarity(left: dict, right: dict, fallback: float) -> float:
    """같은 blueprint 개념이면 낮은 표현 유사도도 중복 후보로 올린다."""
    left_key = str(left.get("_concept_key", ""))
    right_key = str(right.get("_concept_key", ""))
    if left_key and left_key == right_key:
        return min(1.0, fallback + 0.15)
    return 0.0

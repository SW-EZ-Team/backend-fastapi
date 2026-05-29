"""문제 중복 검사 - 핑거프린트 사전 필터 + 코사인 유사도 기반.

O(n^2) 비교 비용을 줄이기 위해 정렬된 토큰 핑거프린트로 정확/근사 중복을
먼저 걸러낸 뒤, 나머지 쌍에만 코사인 유사도를 적용한다.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """텍스트를 정규화된 토큰 목록으로 변환한다."""
    text = text.lower().strip()
    tokens = re.findall(r"[가-힣a-z0-9]+", text)
    return tokens


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
_JACCARD_SKIP_THRESHOLD = 0.3


def check_duplicates(
    questions: list[dict],
    threshold: float = 0.7,
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
    stems = [q.get("stem", "") for q in questions]
    tokens_list = [_tokenize(s) for s in stems]
    counters = [Counter(t) for t in tokens_list]
    token_sets = [set(t) for t in tokens_list]
    fingerprints = [_fingerprint(t) for t in tokens_list]
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
                    id_i = questions[i].get("question_id", str(i))
                    id_j = questions[j].get("question_id", str(j))
                    duplicate_pairs.append((id_i, id_j))
                    exact_pairs.add((i, j))

    # 나머지 쌍에 대해 자카드 사전 필터 + 코사인 비교
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) in exact_pairs:
                continue
            # 조기 종료: 자카드 유사도가 낮으면 코사인도 낮을 것
            jaccard = _token_overlap_ratio(token_sets[i], token_sets[j])
            if jaccard < _JACCARD_SKIP_THRESHOLD:
                continue
            sim = _cosine_similarity(counters[i], counters[j])
            if sim >= threshold:
                id_i = questions[i].get("question_id", str(i))
                id_j = questions[j].get("question_id", str(j))
                duplicate_pairs.append((id_i, id_j))

    max_pairs = n * (n - 1) / 2 if n > 1 else 1
    dedup_score = 1.0 - (len(duplicate_pairs) / max_pairs)
    return max(0.0, dedup_score), duplicate_pairs

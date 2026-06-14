"""시나리오 중복·개념 과대표현 결정론 게이트 (subject-agnostic).

[배경]
생성 후 문항 세트에서 두 가지 품질 결함을 구조적 신호만으로 잡는다.
어떤 과목(파이썬·스프링·수학·자격증 등)에도 동작해야 하므로 특정 과목
개념·도메인 단어를 하드코딩하지 않는다. 오직 등장 숫자 시퀀스·정규화 토큰·
concept_key 같은 "구조 신호"로만 판단한다.

(1) 시나리오 중복(scenario duplicate)
    같은 삽입 수열/트리/예시 시나리오를 재활용한 문항을 잡는다. 발문 어휘가
    조금 달라도 stem 안의 "숫자 시퀀스 + 정규화 핵심 토큰"이 같으면 같은
    시나리오로 보고 두 번째 이후 문항을 교체 대상으로 표시한다.
    deduplicator(토큰/문자 n-gram 유사도)가 잡지 못하는, "수치 예시만 같은"
    구조적 재활용을 보완한다.

(1.5) 의미 중복(semantic duplicate)
    숫자열 서명이 못 잡는, 숫자 없이 "발문은 다르나 같은 지식을 묻는" 중복을 잡는다.
    stem(+correct_answer 핵심어)에서 상투어를 제거한 내용 토큰 집합의 Jaccard
    유사도가 임계 이상이면 의미적 중복으로 클러스터링하고, 한 클러스터에서 보존
    한도를 초과한 뒤쪽 문항을 교체 대상으로 표시한다. 영문 식별자
    (@SpringBootApplication, Starter 등)는 원형 보존해 강한 중복 신호로 쓴다.
    임베딩/LLM 없이 토큰 기반으로만 동작하며 과목 불문이다.

(2) 개념 과대표현(concept over-representation)
    같은 정규화 개념(concept_key 또는 stem 정규화 키)이 전체의 임계 비율을
    넘게 출제되면(예: 20% 초과 또는 2개 초과) 초과분을 교체 대상으로 표시한다.
    좁은 소스에서 같은/지엽 개념이 핵심처럼 반복 출제되는 것을 막는다.

[IN]  questions: 문항 dict 리스트 (stem, _concept_key/concept_key, draft_id/question_id)
[OUT] {draft_id: [issue 문자열...]} — 교체 대상 문항 매핑 (빈 매핑 = 통과)

[게이트 정합]
- 결과를 validate_node 가 기존 failed_ids 로 합류시킨다(중복 방지: 이미 있으면 skip).
- 교체는 기존 repair/재생성 경로(EXAMFORGE_TARGETED_REPAIR / question_repair)가 수행한다.
- 좁은 소스로 교체가 불가능하면 route_after_validation 의 기존 재시도 캡
  (max_retries / count_stuck_rounds / missing_retry_cap)이 1~2회 시도 후
  graceful 통과시킨다 — 이 게이트는 무한루프를 새로 만들지 않는다.

[폴백/오탐 방지]
- 문항이 1개 이하면 비교 대상이 없어 빈 매핑을 반환한다.
- 시그니처가 비면(숫자·토큰이 전혀 없는 빈 stem 등) 구조 검증 영역이므로 제외한다.
- 과대표현 임계는 "비율 OR 절대 개수" 중 하나만 넘으면 플래그하되, 전체 문항이
  적을 때(개념 종류 자체가 부족) 정상 세트를 오탐하지 않도록 절대 개수 하한을 둔다.
"""
from __future__ import annotations

import re

from app.modules.ExamForge_V1.common.logger import get_logger

logger = get_logger(__name__)

# ── 정규화 상수 ──────────────────────────────────────────────────────────────

# 한국어+영어+숫자 토큰. 숫자는 별도 추출하므로 토큰 추출 시에는 글자 위주로 본다.
_WORD_RE = re.compile(r"[가-힣a-z0-9_]+")

# stem 안의 정수/실수 시퀀스 — 같은 수치 예시 재활용을 잡는 핵심 구조 신호.
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# 시험 상투어·발문 보일러플레이트 — 시그니처 토큰에서 제외해
# "다음 중 옳은 것은" 류 공통 문구가 시그니처를 오염시키지 않게 한다.
# (relevance_gate / deduplicator 의 불용어와 정합되게 유지)
_BOILERPLATE_STOPWORDS: frozenset[str] = frozenset({
    "다음", "중", "가장", "적절한", "옳은", "옳지", "않은", "것은", "것을",
    "대한", "대해", "설명", "으로", "에서", "하고", "하는", "하여", "경우",
    "문제", "문항", "고르시오", "고르면", "쓰시오", "서술하시오", "선택하시오",
    "보기", "정답", "무엇인가", "무엇", "어떤", "어느", "이유", "결과",
    "올바른", "올바르게", "틀린", "잘못된", "아닌", "모두", "각각", "때",
    "the", "is", "are", "what", "which", "of", "to", "in", "a", "an",
    "and", "or", "for", "following", "correct", "answer",
})

# 한국어 조사·어미 접미 제거 — deduplicator/relevance_gate 와 동일 규칙 유지.
_JOSA_SUFFIXES: tuple[str, ...] = (
    "으로", "에서", "에게", "하고", "하는", "이다", "이며",
    "을", "를", "은", "는", "이", "가", "의", "에",
)

# 시그니처에 포함할 핵심 토큰 최대 개수 — 너무 길면 작은 표현 차이로 시그니처가
# 어긋나 중복을 놓친다. 정렬된 상위 N개만 써서 "핵심 명사구"만 비교한다.
_MAX_SIGNATURE_TOKENS = 8

# 숫자 시퀀스가 이 길이 이상이면 그 자체로 시나리오를 식별하는 지배적 신호로 본다.
# 같은 데이터 예시(삽입 수열·좌표·계수 등)는 어순/발문이 달라도 숫자열이 같다.
# 한국어 어미·조사 변형(삽입했/삽입한/삽입)에 토큰 비교가 취약하므로, 충분히 긴
# 숫자열이 있으면 토큰을 섞지 않고 숫자열만으로 서명해 중복 탐지를 견고하게 한다.
_DOMINANT_NUMBER_LEN = 2

# 핵심 토큰 시그니처를 신뢰할 최소 토큰 수 — 숫자 신호가 약할 때(짧은 숫자열)
# 토큰이 이 수 미만이면 식별력이 부족하다고 보고 서명을 비운다(오탐 방지).
_MIN_TOKEN_SIGNATURE = 3

# 핵심 토큰 시그니처에 쓸 토큰 접두 길이 — 어미/조사 변형에 견고하도록 토큰을
# 앞 N글자로 절단해 "삽입했/삽입한/삽입"을 같은 어간으로 묶는다(과목 불문 구조 정규화).
_TOKEN_STEM_LEN = 2

# ── 의미 중복(semantic duplicate) 임계 ───────────────────────────────────────
#
# 숫자열 서명은 "수치 예시만 같은" 재활용을 잡지만, 숫자 없는 의미 중복
# (예: @SpringBootApplication 자동설정 연결을 발문만 바꿔 4회 출제)은 못 잡는다.
# 이를 보완해 stem(+correct_answer 핵심어) 내용 토큰 집합의 Jaccard 유사도로
# "발문은 다르나 같은 지식을 묻는" 문항을 묶는다. 특정 과목 단어가 아니라
# 토큰 중복 비율(구조 신호)로만 판단하므로 과목 불문이다.

# 두 문항 토큰 집합의 Jaccard 유사도가 이 값 이상이면 의미적 중복으로 본다.
# 보수적으로(0.55) 잡아 정당하게 다른 문항(삽입 vs 삭제 등 토큰이 충분히 다른
# 경우)을 오탐하지 않게 한다. 너무 낮추면 정상 세트의 과반을 플래그한다.
_SEMANTIC_JACCARD_THRESHOLD = 0.55

# 의미 중복 클러스터당 보존할 문항 수 — 같은 지식을 묻더라도 변별 가치가 있는
# 소수(2개)는 남기고, 이를 초과한 뒤쪽 문항만 교체 대상으로 플래그한다.
# (시나리오 중복은 "동일 시나리오"라 1개만 보존하지만, 의미 중복은 더 느슨한
#  신호이므로 보존 한도를 2로 둬 오탐을 줄인다.)
_SEMANTIC_CLUSTER_KEEP = 2

# 의미 중복 비교를 신뢰할 최소 내용 토큰 수 — 토큰이 너무 적으면 작은 겹침도
# Jaccard 가 과대평가돼 오탐한다. 이 수 미만인 문항은 의미 중복 비교에서 제외한다.
_SEMANTIC_MIN_TOKENS = 3

# 영문 식별자(@SpringBootApplication, Starter 등) 판별 정규식 — 이런 토큰은
# 어간 절단 없이 원형 보존해 "강한 중복 신호"로 쓴다(한국어 어미 변형과 무관).
# 2글자 이상 영문 토큰을 식별자로 본다(순수 한국어 어간과 구분).
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]+$")

# 식별자 토큰 가중치 — Jaccard 계산 시 영문 식별자가 겹치면 일반 토큰보다
# 이 배수만큼 강하게 친다. 같은 식별자(@SpringBootApplication 등)를 공유하는
# 문항은 같은 지식을 묻는 신호가 크다는 요구사항을 반영한다(가중 Jaccard).
_IDENTIFIER_WEIGHT = 3.0

# ── 과대표현 임계 ────────────────────────────────────────────────────────────

# 같은 개념이 전체에서 이 비율을 초과하면 과대표현으로 본다.
_OVERREP_RATIO = 0.20
# 비율과 무관하게 같은 개념이 이 절대 개수를 초과하면 과대표현으로 본다.
_OVERREP_ABS_COUNT = 2
# 과대표현 게이트를 켜는 최소 문항 수 — 너무 적으면(예: 3문항) 개념 종류가
# 본래 적어 오탐하므로 이 미만이면 게이트를 생략한다.
_OVERREP_MIN_QUESTIONS = 5


def _normalize_word(token: str) -> str:
    """한국어 조사·어미 차이를 줄여 같은 개념 표현을 맞춘다."""
    for suffix in _JOSA_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def _content_tokens(text: str) -> list[str]:
    """상투어·1글자·순수 숫자를 제외한 콘텐츠 토큰 목록(중복 포함)을 만든다."""
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text.lower()):
        normalized = _normalize_word(raw)
        if len(normalized) < 2 or normalized.isdigit():
            continue
        if normalized in _BOILERPLATE_STOPWORDS:
            continue
        tokens.append(normalized)
    return tokens


def _number_sequence(text: str) -> list[str]:
    """stem 안의 등장 숫자 시퀀스를 등장 순서대로 추출한다.

    예: "12, 8, 18, 10 순서로 삽입" → ['12', '8', '18', '10']
    같은 수치 예시(삽입 수열·좌표·계수 등)를 재활용하면 이 시퀀스가 같다.
    소수점/음수도 그대로 보존해 미세한 차이를 구분한다.
    """
    return _NUMBER_RE.findall(text or "")


def _token_stems(tokens: list[str]) -> list[str]:
    """토큰을 앞 N글자로 절단해 어미/조사 변형을 같은 어간으로 묶는다.

    "삽입했/삽입한/삽입" → "삽입", "결과로/결과는" → "결과" 처럼 한국어 활용형
    차이를 흡수한다. 정렬+중복 제거 후 상위 N개만 남겨 어순·표현 차이에 견고하게 한다.
    특정 과목 단어가 아니라 글자 단위 구조만 보므로 과목 불문이다.
    """
    stems = {tok[:_TOKEN_STEM_LEN] for tok in tokens if tok}
    return sorted(stems)[:_MAX_SIGNATURE_TOKENS]


def scenario_signature(question: dict) -> str:
    """문항 stem에서 구조적 시나리오 서명을 정규화 추출한다 (subject-agnostic).

    서명 규칙(구조 신호만 사용 — 특정 과목 단어 하드코딩 금지):
      1. 등장 숫자 시퀀스가 _DOMINANT_NUMBER_LEN 이상이면 숫자열만으로 서명한다.
         같은 데이터 예시(삽입 수열·트리 값·좌표 등)는 어순/발문이 달라도 숫자열이
         같으므로, 한국어 활용형에 취약한 토큰을 섞지 않고 숫자열로 견고하게 잡는다.
         순서를 보존해 [12,8,18]과 [8,12,18]을 다른 시나리오로 본다.
      2. 숫자 신호가 약하면(짧은 숫자열) 핵심 토큰 어간(_token_stems)으로 서명한다.
         단 토큰이 _MIN_TOKEN_SIGNATURE 미만이면 식별력 부족으로 서명을 비운다.
    숫자·토큰이 모두 비면 빈 문자열을 반환한다(구조 검증 영역 → 게이트 제외).
    """
    stem = str(question.get("stem", ""))
    code = question.get("code_snippet")
    # 코드 스니펫이 있으면 코드 안의 수치/식별자도 시나리오 구성 요소로 포함한다.
    full_text = f"{stem}\n{code}" if code else stem

    numbers = _number_sequence(full_text)
    # 1) 충분히 긴 숫자열 → 숫자열이 곧 시나리오 식별자.
    if len(numbers) >= _DOMINANT_NUMBER_LEN:
        return f"N[{','.join(numbers)}]"

    # 2) 숫자 신호 약함 → 핵심 토큰 어간으로 서명.
    token_stems = _token_stems(_content_tokens(full_text))
    if len(token_stems) < _MIN_TOKEN_SIGNATURE:
        # 토큰이 너무 적으면(짧은 발문) 식별력 부족 — 서명 비워 게이트 제외(오탐 방지).
        # 단 짧은 숫자열이라도 토큰과 함께 있으면 토큰 서명에 숫자를 덧붙여 변별한다.
        return ""
    num_suffix = f"+n{len(numbers)}" if numbers else ""
    return f"T[{'|'.join(token_stems)}]{num_suffix}"


def _draft_id(question: dict, index: int) -> str:
    """검증/초안 어느 단계에서도 안정적인 문항 식별자를 반환한다."""
    return str(question.get("draft_id") or question.get("question_id") or index)


def find_duplicate_scenarios(questions: list[dict]) -> dict[str, list[str]]:
    """같은 시나리오 서명을 가진 문항의 2번째 이후를 교체 대상으로 표시한다.

    같은 서명이 2개 이상이면 중복으로 판정한다. 첫 번째 문항은 보존하고
    뒤쪽(중복) 문항만 플래그해 repair 경로로 보낸다(deduplicator 와 동일 정책).

    Returns:
        {draft_id: [issue]} — 빈 매핑이면 시나리오 중복 없음.
    """
    if len(questions) < 2:
        return {}

    seen_first: dict[str, str] = {}  # signature → 첫 번째 draft_id
    flagged: dict[str, list[str]] = {}
    for index, q in enumerate(questions):
        sig = scenario_signature(q)
        if not sig:
            continue
        draft_id = _draft_id(q, index)
        if sig in seen_first:
            flagged[draft_id] = [
                "시나리오 중복 — 동일한 수치 예시/핵심 구조를 재활용한 문항"
                f"(최초 문항 draft_id={seen_first[sig]}). 다른 시나리오·데이터로 재출제 필요"
            ]
        else:
            seen_first[sig] = draft_id

    if flagged:
        logger.warning(
            "시나리오 중복 의심 문항 %d건 — 재시도 경로로 전달: %s",
            len(flagged), ", ".join(flagged.keys()),
        )
    return flagged


# ── 의미 중복(semantic duplicate) 검출 ───────────────────────────────────────


def _semantic_token_set(question: dict) -> frozenset[str]:
    """stem(+correct_answer 핵심어)에서 의미 비교용 내용 토큰 집합을 만든다.

    숫자열 서명이 못 잡는 "발문은 다르나 같은 지식을 묻는" 의미 중복을 잡기 위해,
    상투어·불용어·순수 숫자를 제거한 내용 토큰의 *집합*(중복 무시)을 반환한다.

    토큰 정규화 규칙(subject-agnostic — 특정 과목 단어 하드코딩 없음):
      - 한국어 활용형: 앞 _TOKEN_STEM_LEN 글자 어간으로 절단해 "삽입했/삽입한/삽입"을
        같은 어간으로 흡수한다(_token_stems 와 동일 정규화).
      - 영문 식별자(@SpringBootApplication, Starter 등): 어간 절단 없이 원형 보존해
        강한 중복 신호로 쓴다. 이런 식별자가 겹치면 같은 지식을 묻는 신호가 크다.
    correct_answer 는 정답 핵심어(보통 짧은 명사구/식별자)라 같은 지식을 묻는
    문항을 묶는 신호가 강하므로 stem 과 함께 토큰화한다.
    """
    stem = str(question.get("stem", ""))
    answer = str(question.get("correct_answer", ""))
    code = question.get("code_snippet")
    parts = [stem, answer]
    if code:
        parts.append(str(code))
    text = "\n".join(parts)

    tokens: set[str] = set()
    for raw in _WORD_RE.findall(text.lower()):
        normalized = _normalize_word(raw)
        if len(normalized) < 2 or normalized.isdigit():
            continue
        if normalized in _BOILERPLATE_STOPWORDS:
            continue
        if _IDENTIFIER_RE.match(normalized):
            # 영문 식별자는 원형 보존 — 어간 절단 시 변별 신호가 사라진다.
            tokens.add(normalized)
        else:
            # 한국어/일반 토큰은 어간 절단으로 활용형 변형을 흡수한다.
            tokens.add(normalized[:_TOKEN_STEM_LEN])
    return frozenset(tokens)


def _token_weight(tokens: frozenset[str]) -> float:
    """토큰 집합의 가중 합 — 영문 식별자는 _IDENTIFIER_WEIGHT 배로 친다.

    같은 식별자(@SpringBootApplication, Starter 등)를 공유하면 같은 지식을 묻는
    강한 신호이므로, 일반 한국어 어간 토큰보다 무겁게 둬 Jaccard 에 더 기여하게 한다.
    """
    return sum(
        _IDENTIFIER_WEIGHT if _IDENTIFIER_RE.match(tok) else 1.0
        for tok in tokens
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """두 토큰 집합의 가중 Jaccard 유사도(가중 교집합/가중 합집합)를 반환한다.

    영문 식별자 토큰은 _token_weight 에서 가중되므로, 식별자가 겹치면 일반 토큰만
    겹칠 때보다 유사도가 높게 나온다(요구사항: 식별자를 강한 중복 신호로 사용).
    빈 합집합은 0 을 반환한다.
    """
    if not a or not b:
        return 0.0
    union = a | b
    union_weight = _token_weight(union)
    if union_weight == 0.0:
        return 0.0
    return _token_weight(a & b) / union_weight


def find_semantic_duplicates(
    questions: list[dict],
    *,
    threshold: float = _SEMANTIC_JACCARD_THRESHOLD,
    keep: int = _SEMANTIC_CLUSTER_KEEP,
) -> dict[str, list[str]]:
    """토큰 Jaccard 유사도로 의미적 중복 문항을 클러스터링해 초과분을 플래그한다.

    숫자열 시나리오 서명(find_duplicate_scenarios)은 "수치 예시만 같은" 재활용을
    잡지만, 숫자 없는 의미 중복(@SpringBootApplication 자동설정 연결을 발문만 바꿔
    여러 번 출제 등)은 통과시킨다. 이를 보완한다.

    알고리즘(단일 패스 단일연결(single-link) 그리디 클러스터링 — 무한루프 없음):
      0. 변별 숫자열(≥_DOMINANT_NUMBER_LEN)을 가진 문항은 제외한다 — 그런 문항은
         숫자열 시나리오 게이트의 영역이며, 서로 다른 수치 예시를 의미 중복으로
         오탐하지 않기 위함이다(역할 분담).
      1. 나머지 문항의 내용 토큰 집합(_semantic_token_set)을 만든다.
         토큰이 _SEMANTIC_MIN_TOKENS 미만이면 식별력 부족으로 클러스터링에서 제외한다.
      2. 등장 순서대로 보며, 기존 클러스터의 *어느 멤버*와든 가중 Jaccard 가
         threshold 이상이면 그 클러스터에 합류시킨다(single-link). 발문 변형이 누적돼
         대표와는 약간 멀어진 문항도 중간 멤버를 통해 같은 군집으로 묶을 수 있다.
         어디에도 못 들면 새 클러스터를 만든다(O(n·전체비교), 단일 패스라 종료 보장).
      3. 한 클러스터에서 keep 개를 초과한 뒤쪽 문항을 교체 대상으로 플래그한다.
         앞쪽 keep 개(첫 출제 + 변별 가치 있는 소수)는 보존한다.

    오탐 방지:
      - threshold 를 보수적으로(0.55) 둬 토큰이 충분히 다른 정당한 문항(삽입 vs 삭제
        등)은 묶이지 않게 한다.
      - 토큰 수가 적은 문항은 제외해 작은 겹침의 Jaccard 과대평가를 막는다.

    Returns:
        {draft_id: [issue]} — 빈 매핑이면 의미 중복 없음.
    """
    if len(questions) < keep + 1:
        # keep 개 이하면 초과분이 나올 수 없다 — 비교 자체를 생략(오탐·낭비 방지).
        return {}

    # 클러스터: 멤버 [(draft_id, 토큰 집합) ...] 목록. single-link 로 어느 멤버와든
    # threshold 이상이면 합류한다.
    clusters: list[list[tuple[str, frozenset[str]]]] = []
    for index, q in enumerate(questions):
        # 숫자열이 지배적인 문항(수치 예시로 변별되는 문항)은 숫자열 시나리오 게이트
        # (find_duplicate_scenarios)의 영역이다. 의미 중복은 "숫자 없이 같은 지식을
        # 묻는" 변형을 노리므로, 변별 숫자를 가진 문항은 여기서 제외해 서로 다른
        # 수치 예시 문항을 의미 중복으로 오탐하지 않게 한다(역할 분담 + 오탐 방지).
        stem = str(q.get("stem", ""))
        code = q.get("code_snippet")
        num_text = f"{stem}\n{code}" if code else stem
        if len(_number_sequence(num_text)) >= _DOMINANT_NUMBER_LEN:
            continue

        token_set = _semantic_token_set(q)
        if len(token_set) < _SEMANTIC_MIN_TOKENS:
            # 토큰이 너무 적으면(짧은 발문) 식별력 부족 — 클러스터링 제외(오탐 방지).
            continue
        draft_id = _draft_id(q, index)

        joined = False
        for members in clusters:
            if any(_jaccard(token_set, other) >= threshold for _id, other in members):
                members.append((draft_id, token_set))
                joined = True
                break
        if not joined:
            clusters.append([(draft_id, token_set)])

    flagged: dict[str, list[str]] = {}
    for members in clusters:
        if len(members) <= keep:
            continue
        first_id = members[0][0]
        # keep 개 초과분(뒤쪽 문항)만 교체 대상 — 앞쪽 keep 개는 보존.
        for dup_id, _ts in members[keep:]:
            flagged[dup_id] = [
                "의미 중복 — 발문은 다르나 같은 지식을 묻는 문항"
                f"(유사 클러스터 대표 draft_id={first_id}, 토큰 중복 ≥{threshold:.0%}). "
                "다른 핵심 지식으로 재출제 필요"
            ]

    if flagged:
        logger.warning(
            "의미 중복 의심 문항 %d건 — 재시도 경로로 전달: %s",
            len(flagged), ", ".join(flagged.keys()),
        )
    return flagged


def _concept_label(question: dict) -> str:
    """과대표현 집계에 쓸 정규화 개념 라벨을 만든다 (subject-agnostic).

    우선순위:
      1. _concept_key / concept_key — 블루프린트가 부여한 슬롯 개념(가장 신뢰도 높음)
      2. (1) 이 없으면 stem 상위 핵심 토큰을 정규화한 키로 폴백한다.
    concept_key 는 (chapter::topic::concept::diff::reasoning) 형태라 diff/reasoning
    suffix 가 달라도 같은 개념이면 묶이도록 앞 3토막(개념 식별부)만 사용한다.
    """
    raw_key = str(question.get("_concept_key") or question.get("concept_key") or "")
    if raw_key:
        parts = raw_key.split("::")
        # chapter::topic::concept 까지만 — d{diff}::reasoning::v{n} suffix 는 같은 개념의
        # 변주이므로 묶어서 과대표현을 본다(개념 다양성 기준).
        return "::".join(parts[:3]) if len(parts) >= 3 else raw_key

    # 폴백: stem 핵심 토큰 어간 키 (개념 메타가 없는 경로 호환).
    # scenario_signature 와 같은 어간 정규화를 써 한국어 활용형 차이를 흡수한다.
    return "|".join(_token_stems(_content_tokens(str(question.get("stem", "")))))


def find_overrepresented_concepts(
    questions: list[dict],
    *,
    ratio: float = _OVERREP_RATIO,
    abs_count: int = _OVERREP_ABS_COUNT,
    min_questions: int = _OVERREP_MIN_QUESTIONS,
) -> dict[str, list[str]]:
    """같은 개념이 임계를 초과해 출제됐는지 검사해 초과분을 교체 대상으로 표시한다.

    임계: (해당 개념 수 / 전체) > ratio  또는  해당 개념 수 > abs_count.
    초과분은 등장 순서상 뒤쪽 문항부터 플래그한다(앞쪽 = 첫 출제 보존).

    전체 문항이 min_questions 미만이면 개념 종류 자체가 적어 오탐하므로 생략한다.

    Returns:
        {draft_id: [issue]} — 빈 매핑이면 과대표현 없음.
    """
    total = len(questions)
    if total < min_questions:
        return {}

    # 개념별로 문항 인덱스를 등장 순서대로 모은다.
    by_concept: dict[str, list[int]] = {}
    for index, q in enumerate(questions):
        label = _concept_label(q)
        if not label:
            continue
        by_concept.setdefault(label, []).append(index)

    # 임계 한도 = max(abs_count, floor(total * ratio)). 한도를 초과하는 만큼 뒤쪽을 플래그.
    threshold_count = max(abs_count, int(total * ratio))
    flagged: dict[str, list[str]] = {}
    for label, indices in by_concept.items():
        if len(indices) <= threshold_count:
            continue
        share = len(indices) / total
        # 한도 초과분(뒤쪽 문항)만 교체 대상 — 앞쪽 threshold_count개는 보존.
        for index in indices[threshold_count:]:
            q = questions[index]
            draft_id = _draft_id(q, index)
            flagged[draft_id] = [
                f"개념 과대표현 — 동일 개념이 {len(indices)}문항({share:.0%}, 전체 {total}문항)"
                f"으로 임계(>{threshold_count}개)를 초과. 다른 핵심 개념으로 분산 출제 필요"
            ]

    if flagged:
        logger.warning(
            "개념 과대표현 의심 문항 %d건 — 재시도 경로로 전달: %s",
            len(flagged), ", ".join(flagged.keys()),
        )
    return flagged


def check_scenario_quality(questions: list[dict]) -> dict[str, list[str]]:
    """시나리오 중복 + 의미 중복 + 개념 과대표현을 한 번에 검사해 교체 대상을 반환한다.

    세 검사 결과를 draft_id 기준으로 병합한다(같은 문항이 여러 곳에 걸리면 issue 합침).
      1. find_duplicate_scenarios   — 숫자열 시나리오 서명(수치 예시 재활용) 중복
      2. find_semantic_duplicates   — 토큰 Jaccard 기반 의미 중복(숫자 없는 발문 변형)
      3. find_overrepresented_concepts — 같은 개념 과대표현(챕터 편중·반복 출제)
    세 신호는 모두 failed_ids 합류 시 중복 추가가 차단되므로 충돌 없이 함께 동작한다.

    Returns:
        {draft_id: [issue...]} — 빈 매핑이면 통과(교체 대상 없음).
    """
    merged: dict[str, list[str]] = {}
    for partial in (
        find_duplicate_scenarios(questions),
        find_semantic_duplicates(questions),
        find_overrepresented_concepts(questions),
    ):
        for draft_id, issues in partial.items():
            merged.setdefault(draft_id, []).extend(issues)
    return merged

"""저장된 모의고사 문항을 재생성 없이(LLM 호출 0) 품질 게이트로 검증하는 replay 도구.

[목적]
품질 로직(챕터 쿼터·의미 dedup·과대표현·해설)을 바꿀 때마다 새 시험을 생성(비쌈)하지
않고, 이미 DB에 저장된 문항을 게이트에 통과시켜 "무엇이 플래그되는지"를 LLM 호출 0으로
확인한다. 비싼 풀 재생성 반복이 비용의 대부분이었으므로, 저장 문항을 정적으로 재검증해
같은 신호를 얻는다.

[3계층 구성 — 라이브러리형, SRP]
  1. analyze_questions(questions) -> dict
       순수 함수. 인프라 의존 0. 입력 문항 리스트에 대해 LLM 없이
       (a) scenario_gate.check_scenario_quality (시나리오 중복·의미 중복·과대표현)
       (b) 챕터 분포 집계 (각 챕터 문항 수·0 챕터·편중)
       (c) concept 분포·다양성
       (d) 해설 길이 분포
       (e) 유형(template_id) 분포
       를 계산해 구조화 리포트(dict)로 반환한다.
  2. load_attempt_questions(attempt_id) -> list[dict]
       DB 어댑터. exam_attempt_question 행을 읽어 게이트가 먹는 dict로 변환한다.
       기존 asyncpg 패턴(TTS_V2 helpers_async)을 그대로 따른다.
  3. CLI (python -m app.modules.ExamForge_V1.quality.replay <attempt_id>)
       attempt_id로 문항을 로드해 사람이 읽는 텍스트 리포트를 출력한다.

[챕터/개념 메타 저장 한계 — 매우 중요]
Spring exam_attempt_question 스키마에는 chapter / concept_key 컬럼이 **없다**.
저장 시점에 살아남는 메타는 grading_metadata_json 안의 topic / difficulty / bloom_level
뿐이다(mock_generation_callback._to_spring_question 참조). 따라서:
  - 챕터 커버리지는 정확 집계가 불가능하다. topic(있으면) 또는 stem 기반 추정 키로
    "메타 미저장 — 추정" 표기와 함께 근사 집계한다.
  - concept_key 도 미저장이므로, scenario_gate._concept_label 폴백(stem 토큰 어간)으로
    추정한다. 이 한계는 리포트의 `meta` 섹션에 명시한다.
입력 dict 에 chapter / _concept_key 가 직접 들어오면(생성 직후 in-memory 검증) 그 값을
우선 사용한다 — replay 는 DB 경로와 in-memory 경로 양쪽을 모두 지원한다.

[비-목표 / 금지]
  - 라이브 AI 생성·임베딩 API 호출 절대 금지. 모든 계산은 결정론적 정적 분석이다.
  - 기존 생성 경로·게이트 동작을 바꾸지 않는다(읽기 전용 재검증 도구).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from app.modules.ExamForge_V1.common.logger import get_logger
from app.modules.ExamForge_V1.quality.scenario_gate import (
    _concept_label,
    check_scenario_quality,
)

logger = get_logger(__name__)


# ── 분석 상수 ────────────────────────────────────────────────────────────────

# 해설 길이 분포에서 "사실상 빈 스텁 해설"로 보는 하한(문자 수).
# explanation_checker._EXPLANATION_ABSOLUTE_MIN_CHARS(6)와 정합되게 둔다.
_EXPLANATION_STUB_MAX_CHARS = 6

# 해설 길이 분포에서 "짧음"으로 분류하는 상한(문자 수). 이 미만은 근거가 부족할
# 가능성이 높다는 약한 신호로만 쓴다(게이트가 아니라 리포트 표기용).
_EXPLANATION_SHORT_MAX_CHARS = 40

# 챕터 편중 판정 비율 — 한 챕터가 전체의 이 비율을 초과하면 편중으로 표기한다.
# scenario_gate._OVERREP_RATIO(0.20)보다 느슨한 챕터 단위 신호이므로 별도 상수로 둔다.
_CHAPTER_SKEW_RATIO = 0.40

# 챕터 편중 판정을 켜는 최소 문항 수 — 너무 적으면 챕터 종류가 본래 적어 오탐한다.
_CHAPTER_SKEW_MIN_QUESTIONS = 4

# stem 토큰 추정 시 사용하는 단어 정규식(scenario_gate 와 동일 계열).
_WORD_RE = re.compile(r"[가-힣a-z0-9_]+")


def _question_index_id(question: dict, index: int) -> str:
    """문항 식별자를 안정적으로 뽑는다(scenario_gate._draft_id 와 동일 규칙)."""
    return str(
        question.get("draft_id")
        or question.get("question_id")
        or index
    )


def _chapter_label(question: dict) -> tuple[str, bool]:
    """챕터 라벨과 "추정 여부"를 반환한다.

    우선순위:
      1. chapter (직접 저장/in-memory) — 가장 신뢰. is_estimated=False.
      2. _concept_key/concept_key 의 chapter 토막(:: 분리 앞 부분) — 신뢰. False.
      3. grading_metadata_json 에서 살아남은 topic — 챕터 근사. is_estimated=True.
      4. 폴백: stem 토큰 어간 추정 키. is_estimated=True.
    DB 저장 스키마에는 chapter/concept_key 가 없으므로 일반적으로 3~4번 경로를 탄다.

    Returns:
        (label, is_estimated) — label 이 빈 문자열이면 집계에서 제외.
    """
    chapter = str(question.get("chapter") or "").strip()
    if chapter:
        return chapter, False

    raw_key = str(question.get("_concept_key") or question.get("concept_key") or "")
    if raw_key:
        # concept_key 는 chapter::topic::concept::... 형태 — 앞 토막이 챕터.
        head = raw_key.split("::", 1)[0].strip()
        if head:
            return head, False

    topic = str(question.get("topic") or "").strip()
    if topic:
        # topic 은 grading_metadata_json 에 살아남는 유일한 챕터 근사 신호다.
        return topic, True

    # 최후 폴백: stem 핵심 토큰 어간으로 추정 키(개념 라벨과 동일 계열).
    fallback = _concept_label(question)
    return (fallback, True) if fallback else ("", True)


def _has_stored_chapter_meta(questions: list[dict]) -> bool:
    """입력 문항에 신뢰할 수 있는 챕터/개념 메타가 직접 저장돼 있는지 판정한다.

    chapter 또는 concept_key 가 하나라도 직접 들어오면 True(in-memory 검증 경로).
    DB 로드 경로는 이 메타가 없으므로 보통 False → 리포트에 "메타 미저장 — 추정" 표기.
    """
    for q in questions:
        if str(q.get("chapter") or "").strip():
            return True
        if str(q.get("_concept_key") or q.get("concept_key") or "").strip():
            return True
    return False


def _chapter_distribution(questions: list[dict]) -> dict[str, Any]:
    """챕터별 문항 수·0 챕터·편중을 집계한다.

    chapter/concept_key 미저장 시 topic·stem 추정으로 근사하므로, 반환 dict 에
    estimated 플래그를 실어 호출부(리포트)가 한계를 명시할 수 있게 한다.
    """
    total = len(questions)
    estimated = not _has_stored_chapter_meta(questions)

    counts: dict[str, int] = {}
    unlabeled = 0
    for q in questions:
        label, _is_est = _chapter_label(q)
        if not label:
            unlabeled += 1
            continue
        counts[label] = counts.get(label, 0) + 1

    # 편중: 충분한 문항이 있을 때만, 한 챕터가 임계 비율 초과 시 표기.
    skewed: list[dict[str, Any]] = []
    if total >= _CHAPTER_SKEW_MIN_QUESTIONS:
        for label, count in counts.items():
            share = count / total
            if share > _CHAPTER_SKEW_RATIO:
                skewed.append({"chapter": label, "count": count, "share": share})
    skewed.sort(key=lambda d: d["count"], reverse=True)

    return {
        "estimated": estimated,
        "total_questions": total,
        "distinct_chapters": len(counts),
        "counts": dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True)),
        "unlabeled_questions": unlabeled,
        "skewed_chapters": skewed,
    }


def _concept_distribution(questions: list[dict]) -> dict[str, Any]:
    """개념(concept_key 또는 stem 추정 키)별 문항 수·다양성을 집계한다.

    scenario_gate._concept_label 을 재사용해 과대표현 게이트와 같은 개념 키를 쓴다
    (concept_key 미저장 시 stem 토큰 어간 폴백). 다양성 지표:
      - distinct_concepts: 서로 다른 개념 수
      - diversity_ratio: distinct_concepts / total (1.0 에 가까울수록 다양)
    """
    total = len(questions)
    counts: dict[str, int] = {}
    unlabeled = 0
    for q in questions:
        label = _concept_label(q)
        if not label:
            unlabeled += 1
            continue
        counts[label] = counts.get(label, 0) + 1

    distinct = len(counts)
    diversity_ratio = (distinct / total) if total else 0.0
    # 가장 많이 출제된 개념 상위 몇 개(리포트 가독성용).
    top_concepts = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "total_questions": total,
        "distinct_concepts": distinct,
        "diversity_ratio": diversity_ratio,
        "unlabeled_questions": unlabeled,
        "top_concepts": [{"concept": k, "count": v} for k, v in top_concepts],
    }


def _explanation_stats(questions: list[dict]) -> dict[str, Any]:
    """해설 길이 분포(문자 수 기준)를 집계한다.

    분류:
      - missing: 해설이 비었거나 공백뿐
      - stub: 길이가 _EXPLANATION_STUB_MAX_CHARS 이하(사실상 빈 스텁)
      - short: stub 초과 ~ _EXPLANATION_SHORT_MAX_CHARS 미만(근거 부족 가능)
      - ok: short 이상
    통계: min/max/mean(비어있지 않은 해설 기준), 그리고 문제별 길이 리스트.
    """
    total = len(questions)
    lengths: list[int] = []
    missing = 0
    stub = 0
    short = 0
    ok = 0
    flagged_short: list[dict[str, Any]] = []  # stub/missing 문항 식별자(리포트용)

    for index, q in enumerate(questions):
        text = str(q.get("explanation") or "").strip()
        length = len(text)
        qid = _question_index_id(q, index)
        if length == 0:
            missing += 1
            flagged_short.append({"id": qid, "length": 0, "kind": "missing"})
            continue
        lengths.append(length)
        if length <= _EXPLANATION_STUB_MAX_CHARS:
            stub += 1
            flagged_short.append({"id": qid, "length": length, "kind": "stub"})
        elif length < _EXPLANATION_SHORT_MAX_CHARS:
            short += 1
        else:
            ok += 1

    nonempty = len(lengths)
    return {
        "total_questions": total,
        "missing": missing,
        "stub": stub,
        "short": short,
        "ok": ok,
        "min_length": min(lengths) if lengths else 0,
        "max_length": max(lengths) if lengths else 0,
        "mean_length": (sum(lengths) / nonempty) if nonempty else 0.0,
        "flagged": flagged_short,
    }


def _type_distribution(questions: list[dict]) -> dict[str, Any]:
    """문항 유형(template_id) 분포를 집계한다.

    template_id 는 DB 에 저장되는(저장 스키마에 컬럼 존재) 유형 신호다.
    비어있으면 'UNKNOWN' 으로 묶는다.
    """
    counts: dict[str, int] = {}
    for q in questions:
        template_id = str(q.get("template_id") or "").strip() or "UNKNOWN"
        counts[template_id] = counts.get(template_id, 0) + 1
    return {
        "distinct_types": len(counts),
        "counts": dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True)),
    }


def analyze_questions(questions: list[dict]) -> dict[str, Any]:
    """저장된 문항 리스트를 LLM 없이 품질 게이트로 검증해 구조화 리포트를 반환한다.

    순수 함수 — 인프라(DB·네트워크·LLM) 의존 0. 같은 입력에 항상 같은 출력.

    [IN]  questions: 문항 dict 리스트. 최소 stem 을 기대하며, 선택적으로
          correct_answer / explanation / template_id / options / topic /
          chapter / _concept_key / question_id|draft_id 등을 본다.
    [OUT] dict — 아래 키를 가진 구조화 리포트:
          {
            "question_count": int,
            "meta": {                       # 분석 한계·전제 명시
              "chapter_meta_stored": bool,  # 챕터/개념 메타가 직접 저장됐는지
              "chapter_basis": str,         # 챕터 집계 근거(stored|estimated)
              "llm_calls": 0,               # 항상 0 — 정적 분석임을 명시
              "notes": [str, ...],
            },
            "scenario_gate": {              # check_scenario_quality 결과 요약
              "flagged_count": int,
              "flagged": {id: [issue, ...]},
              "clusters": [...],            # 중복/과대표현 이슈 그룹
            },
            "chapter_coverage": {...},      # _chapter_distribution
            "concept_diversity": {...},     # _concept_distribution
            "explanation_lengths": {...},   # _explanation_stats
            "type_distribution": {...},     # _type_distribution
          }

    빈/단일 입력 안전:
      - 빈 리스트면 모든 분포가 0/빈 매핑으로 채워진 리포트를 반환한다(예외 없음).
      - 1문항이면 scenario_gate 가 빈 매핑을 반환하므로 flagged_count=0 이 된다.
    """
    count = len(questions)

    # (a) 시나리오/의미 중복·과대표현 게이트 — LLM 없이 구조 신호로만 판단.
    scenario_flagged = check_scenario_quality(questions)
    # 같은 이슈 문구로 묶어 클러스터 요약(리포트 가독성용 — 게이트 동작은 변경 없음).
    clusters = _summarize_scenario_clusters(scenario_flagged)

    # (b)~(e) 분포 집계.
    chapter_cov = _chapter_distribution(questions)
    concept_div = _concept_distribution(questions)
    explanation = _explanation_stats(questions)
    types = _type_distribution(questions)

    notes: list[str] = []
    if not chapter_cov["estimated"]:
        chapter_basis = "stored"
    else:
        chapter_basis = "estimated"
        notes.append(
            "exam_attempt_question 스키마에 chapter/concept_key 컬럼이 없어 챕터 커버리지는 "
            "topic(grading_metadata) 또는 stem 토큰으로 추정한 근사값이다."
        )
    if explanation["missing"] or explanation["stub"]:
        notes.append(
            f"해설 누락 {explanation['missing']}건 / 스텁(<={_EXPLANATION_STUB_MAX_CHARS}자) "
            f"{explanation['stub']}건 발견 — 해설 품질 점검 필요."
        )

    return {
        "question_count": count,
        "meta": {
            "chapter_meta_stored": not chapter_cov["estimated"],
            "chapter_basis": chapter_basis,
            "llm_calls": 0,
            "notes": notes,
        },
        "scenario_gate": {
            "flagged_count": len(scenario_flagged),
            "flagged": scenario_flagged,
            "clusters": clusters,
        },
        "chapter_coverage": chapter_cov,
        "concept_diversity": concept_div,
        "explanation_lengths": explanation,
        "type_distribution": types,
    }


def _summarize_scenario_clusters(flagged: dict[str, list[str]]) -> list[dict[str, Any]]:
    """게이트 플래그 결과를 이슈 종류별로 묶어 사람이 읽기 쉬운 클러스터로 만든다.

    issue 문자열 머리말("시나리오 중복"/"의미 중복"/"개념 과대표현")로 분류한다.
    게이트 자체 동작은 바꾸지 않고, 리포트 가독성을 위해 결과만 재구성한다.
    """
    kinds = {
        "시나리오 중복": "scenario_duplicate",
        "의미 중복": "semantic_duplicate",
        "개념 과대표현": "concept_overrepresentation",
    }
    buckets: dict[str, list[str]] = {}
    for draft_id, issues in flagged.items():
        for issue in issues:
            kind = next(
                (v for k, v in kinds.items() if issue.startswith(k)),
                "other",
            )
            buckets.setdefault(kind, []).append(draft_id)
    return [
        {"kind": kind, "question_ids": sorted(set(ids)), "count": len(set(ids))}
        for kind, ids in sorted(buckets.items())
    ]


# ── DB 어댑터 (asyncpg) ──────────────────────────────────────────────────────


def _row_to_question(row: Any) -> dict[str, Any]:
    """exam_attempt_question 한 행을 게이트가 먹는 문항 dict 로 변환한다(순수 함수).

    행은 dict 형태(또는 dict 변환 가능한 asyncpg Record)를 기대한다. 매핑:
      stem            → stem
      template_id     → template_id (유형 신호)
      correct_answer  → correct_answer (의미 중복 토큰화에 사용)
      explanation     → explanation (해설 길이 분포)
      options_json    → options (label/text/is_correct 리스트로 역직렬화)
      points          → points
      display_order   → display_order
      question_id     → question_id (식별자)
      grading_metadata_json → topic/difficulty/bloom_level 등 부가 메타를 평탄화해 포함
                              (챕터 커버리지 추정에 topic 사용)

    chapter/concept_key 는 스키마에 없으므로 매핑하지 않는다 — 분석 시 추정 처리된다.
    """
    data = dict(row)

    question: dict[str, Any] = {
        "question_id": data.get("question_id"),
        "template_id": data.get("template_id") or "",
        "stem": data.get("stem") or "",
        "correct_answer": data.get("correct_answer") or "",
        "explanation": data.get("explanation") or "",
        "points": data.get("points"),
        "display_order": data.get("display_order"),
        "source_reference": data.get("source_reference") or "",
        "options": _parse_options(data.get("options_json")),
    }

    # grading_metadata_json 안의 살아남은 메타(topic/difficulty/bloom_level 등)를
    # 최상위로 평탄화해 분석 함수가 topic 으로 챕터를 추정할 수 있게 한다.
    metadata = _parse_json_obj(data.get("grading_metadata_json"))
    for key in ("topic", "difficulty", "bloom_level", "code_snippet"):
        if key in metadata and metadata[key] is not None:
            question[key] = metadata[key]

    return question


def _parse_options(raw: Any) -> list[dict[str, Any]]:
    """options_json(JSONB) 을 label/text/is_correct 보기 리스트로 역직렬화한다.

    asyncpg JSONB 는 보통 str 로 오므로 json.loads 한다. 이미 list 면 그대로 쓴다.
    형식이 어긋나면 빈 리스트를 반환한다(분석은 stem 만으로도 가능).
    """
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(value, list):
        return []

    options: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            options.append(
                {
                    "label": item.get("label", ""),
                    "text": item.get("text", ""),
                    # Spring 저장 키는 is_correct(snake) 또는 isCorrect(camel) 둘 다 대응.
                    "is_correct": bool(
                        item.get("is_correct", item.get("isCorrect", False))
                    ),
                }
            )
    return options


def _parse_json_obj(raw: Any) -> dict[str, Any]:
    """JSONB 객체 컬럼을 dict 로 역직렬화한다. 실패·비객체면 빈 dict."""
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


# exam_attempt_question 조회 SQL — display_order 순서로 읽어 출제 순서를 보존한다.
# (시나리오/개념 게이트가 "앞쪽 보존, 뒤쪽 플래그" 정책이라 순서가 결과에 영향을 준다.)
_SELECT_ATTEMPT_QUESTIONS = (
    "SELECT question_id, template_id, display_order, stem, options_json, "
    "       points, correct_answer, explanation, source_reference, "
    "       grading_metadata_json "
    "FROM exam_attempt_question "
    "WHERE attempt_id = $1 "
    "ORDER BY display_order ASC, id ASC"
)


async def fetch_attempt_question_rows(conn: Any, attempt_id: str) -> list[dict[str, Any]]:
    """주입된 asyncpg 호환 커넥션으로 exam_attempt_question 행을 읽어 dict 리스트로 변환한다.

    DI 지향(직접 인프라 import 금지) — 커넥션을 인자로 받아 테스트에서 mock 으로 주입한다.
    SELECT 전용(쓰기 없음). 행이 없으면 빈 리스트.
    """
    rows = await conn.fetch(_SELECT_ATTEMPT_QUESTIONS, attempt_id)
    return [_row_to_question(r) for r in rows]


async def load_attempt_questions(attempt_id: str) -> list[dict[str, Any]]:
    """attempt_id 로 저장된 문항을 DB 에서 읽어 게이트가 먹는 dict 리스트로 반환한다.

    DATABASE_URL(asyncpg DSN)로 연결한다 — TTS_V2 helpers_async 와 동일 패턴.
    이 함수는 SELECT 만 수행하며 LLM·임베딩 호출이 전혀 없다.

    [IN]  attempt_id: exam_attempt.attempt_id (VARCHAR(80))
    [OUT] list[dict] — analyze_questions 가 바로 먹는 문항 dict 리스트
    [에러] DATABASE_URL 미설정 시 RuntimeError. 연결/조회 실패는 원예외를 전파한다.
    """
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았다 — replay DB 로드를 수행할 수 없다."
        )

    # asyncpg 는 함수 내부에서 지연 import 한다(인프라 의존을 모듈 로드 시점에 끌어오지
    # 않게 — analyze_questions 순수성·테스트 import 가벼움 보존).
    import asyncpg  # noqa: PLC0415  (지연 import 의도)

    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        return await fetch_attempt_question_rows(conn, attempt_id)
    finally:
        if conn is not None:
            await conn.close()


# ── CLI: 사람이 읽는 텍스트 리포트 ───────────────────────────────────────────


def format_report_text(attempt_id: str, report: dict[str, Any]) -> str:
    """analyze_questions 리포트를 사람이 읽는 텍스트로 렌더한다(순수 함수).

    챕터 커버리지·중복 클러스터·해설 길이 요약을 중심으로 정리한다.
    리더가 저장된 시험에 바로 돌려 결과를 눈으로 확인하는 용도.
    """
    lines: list[str] = []
    count = report["question_count"]
    meta = report["meta"]

    lines.append("=" * 64)
    lines.append(f"ExamForge replay 품질 리포트 — attempt_id={attempt_id}")
    lines.append(f"문항 수: {count}개   (LLM 호출: {meta['llm_calls']}회 — 정적 분석)")
    lines.append("=" * 64)

    # 분석 한계 / 전제
    if meta["notes"]:
        lines.append("")
        lines.append("[분석 전제·한계]")
        for note in meta["notes"]:
            lines.append(f"  - {note}")

    # 게이트 플래그 요약
    gate = report["scenario_gate"]
    lines.append("")
    lines.append(f"[품질 게이트] 플래그 문항: {gate['flagged_count']}개")
    if gate["clusters"]:
        kind_kr = {
            "scenario_duplicate": "시나리오 중복(수치 예시 재활용)",
            "semantic_duplicate": "의미 중복(발문만 다른 동일 지식)",
            "concept_overrepresentation": "개념 과대표현",
            "other": "기타",
        }
        for cluster in gate["clusters"]:
            label = kind_kr.get(cluster["kind"], cluster["kind"])
            ids = ", ".join(cluster["question_ids"][:12])
            more = " ..." if cluster["count"] > 12 else ""
            lines.append(f"  - {label}: {cluster['count']}건 [{ids}{more}]")
    else:
        lines.append("  - 플래그 없음 (통과)")

    # 챕터 커버리지
    chapter = report["chapter_coverage"]
    lines.append("")
    basis = "추정(메타 미저장)" if chapter["estimated"] else "저장된 메타"
    lines.append(f"[챕터 커버리지] 근거: {basis} / 서로 다른 챕터: {chapter['distinct_chapters']}개")
    if chapter["counts"]:
        for name, n in list(chapter["counts"].items())[:20]:
            lines.append(f"    {name}: {n}문항")
    if chapter["unlabeled_questions"]:
        lines.append(f"    (라벨 없음: {chapter['unlabeled_questions']}문항)")
    if chapter["skewed_chapters"]:
        for sk in chapter["skewed_chapters"]:
            lines.append(
                f"    ⚠ 편중: {sk['chapter']} {sk['count']}문항 "
                f"({sk['share']:.0%} > {_CHAPTER_SKEW_RATIO:.0%})"
            )

    # 개념 다양성
    concept = report["concept_diversity"]
    lines.append("")
    lines.append(
        f"[개념 다양성] 서로 다른 개념: {concept['distinct_concepts']}개 / "
        f"다양성 비율: {concept['diversity_ratio']:.2f} (1.00=모두 고유)"
    )
    if concept["top_concepts"]:
        lines.append("    최다 출제 개념:")
        for item in concept["top_concepts"][:8]:
            lines.append(f"      {item['concept']}: {item['count']}문항")

    # 해설 길이 분포
    exp = report["explanation_lengths"]
    lines.append("")
    lines.append("[해설 길이 분포]")
    lines.append(
        f"    누락 {exp['missing']} / 스텁(<={_EXPLANATION_STUB_MAX_CHARS}자) {exp['stub']} / "
        f"짧음(<{_EXPLANATION_SHORT_MAX_CHARS}자) {exp['short']} / 정상 {exp['ok']}"
    )
    lines.append(
        f"    길이(비어있지 않은 해설): min={exp['min_length']} "
        f"max={exp['max_length']} mean={exp['mean_length']:.1f}"
    )
    if exp["flagged"]:
        flagged_ids = ", ".join(
            f"{f['id']}({f['kind']},{f['length']}자)" for f in exp["flagged"][:12]
        )
        lines.append(f"    점검 대상: {flagged_ids}")

    # 유형 분포
    types = report["type_distribution"]
    lines.append("")
    lines.append(f"[유형 분포] 서로 다른 유형: {types['distinct_types']}개")
    for name, n in list(types["counts"].items())[:20]:
        lines.append(f"    {name}: {n}문항")

    lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


def _run_cli(attempt_id: str) -> int:
    """CLI 진입 본체 — attempt_id 로 로드·분석·텍스트 출력. 종료 코드를 반환한다.

    종료 코드: 0=성공(플래그 유무 무관), 1=로드/실행 실패.
    플래그가 있어도 0 으로 둔다 — replay 는 "무엇이 플래그되는지 확인"이 목적이고,
    CI 게이트로 쓰려면 호출부가 리포트의 flagged_count 를 직접 판정하면 된다.
    """
    import asyncio

    try:
        questions = asyncio.run(load_attempt_questions(attempt_id))
    except Exception as exc:  # noqa: BLE001  (CLI 경계 — 모든 오류를 사용자 메시지로)
        print(f"[replay] 로드 실패: {exc}")
        return 1

    if not questions:
        print(f"[replay] attempt_id={attempt_id} 에 저장된 문항이 없다.")
        # 빈 결과도 정상 분석으로 처리(예외 아님).

    report = analyze_questions(questions)
    print(format_report_text(attempt_id, report))
    return 0


def main(argv: list[str] | None = None) -> int:
    """python -m app.modules.ExamForge_V1.quality.replay <attempt_id> 진입점."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.modules.ExamForge_V1.quality.replay",
        description=(
            "저장된 모의고사 문항을 재생성 없이(LLM 0) 품질 게이트로 재검증한다. "
            "DATABASE_URL 로 exam_attempt_question 을 읽어 텍스트 리포트를 출력한다."
        ),
    )
    parser.add_argument("attempt_id", help="exam_attempt.attempt_id (검증할 응시 ID)")
    args = parser.parse_args(argv)
    return _run_cli(args.attempt_id)


if __name__ == "__main__":  # pragma: no cover  (CLI 진입 — 단위테스트는 main()을 직접 호출)
    raise SystemExit(main())

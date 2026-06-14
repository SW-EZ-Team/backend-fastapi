"""replay 도구 단위 테스트 — 저장된 문항 재검증(LLM 호출 0).

검증 범위:
(a) 의미 중복 클러스터가 리포트의 scenario_gate.clusters 에 잡힌다
(b) 챕터 편중이 chapter_coverage.skewed_chapters 에 잡힌다
(c) 해설 길이 통계(누락/스텁/짧음/정상, min/max/mean)가 정확하다
(d) 빈/단일 입력에서 예외 없이 안전한 리포트를 반환한다
+ DB 어댑터(_row_to_question / fetch_attempt_question_rows)를 mock 커넥션으로 검증
+ 챕터/개념 메타 미저장 시 estimated 표기, 직접 저장 시 stored 표기
+ format_report_text 가 예외 없이 텍스트를 만든다

전부 fixture/mock 기반 — Gemini 등 라이브 AI 생성·임베딩·DB 라이브 호출 없음.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.ExamForge_V1.quality import replay as replay_mod
from app.modules.ExamForge_V1.quality.replay import (
    _row_to_question,
    analyze_questions,
    fetch_attempt_question_rows,
    format_report_text,
    load_attempt_questions,
    main,
)


def _q(qid: str, stem: str, **extra: object) -> dict:
    """테스트용 문항 dict 헬퍼."""
    q: dict = {"question_id": qid, "stem": stem}
    q.update(extra)
    return q


# ── (a) 의미 중복 클러스터 리포트 ─────────────────────────────────────────────


class TestSemanticDuplicateReport:
    """발문만 다른 동일 지식 문항(숫자 없음)이 게이트 클러스터로 보고된다."""

    def test_semantic_duplicate_cluster_flagged(self) -> None:
        # @SpringBootApplication 자동설정을 발문만 바꿔 4회 — keep=2 초과분 2개가 플래그.
        questions = [
            _q("q1", "스프링부트 애플리케이션에서 자동설정을 활성화하는 애너테이션은 무엇인가",
               correct_answer="springbootapplication"),
            _q("q2", "자동설정을 켜는 스프링부트 애플리케이션 애너테이션을 고르시오",
               correct_answer="springbootapplication"),
            _q("q3", "스프링부트 자동설정 애너테이션 애플리케이션 활성화는 어느 것인가",
               correct_answer="springbootapplication"),
            _q("q4", "애플리케이션 자동설정 스프링부트 애너테이션으로 옳은 것은",
               correct_answer="springbootapplication"),
        ]
        report = analyze_questions(questions)

        assert report["question_count"] == 4
        assert report["meta"]["llm_calls"] == 0  # 정적 분석 — LLM 호출 0
        gate = report["scenario_gate"]
        assert gate["flagged_count"] >= 1, "의미 중복이 전혀 잡히지 않았다"
        kinds = {c["kind"] for c in gate["clusters"]}
        assert "semantic_duplicate" in kinds, f"의미 중복 클러스터 없음: {gate['clusters']}"


# ── (b) 챕터 편중 리포트 ─────────────────────────────────────────────────────


class TestChapterSkewReport:
    """한 챕터가 임계 비율을 초과하면 skewed_chapters 로 보고된다."""

    def test_chapter_skew_flagged_with_stored_meta(self) -> None:
        # chapter 직접 저장 — 8문항 중 6문항이 '정렬'(75% > 40%)이면 편중.
        questions = [_q(f"q{i}", f"정렬 알고리즘 문항 {i}", chapter="정렬") for i in range(6)]
        questions += [
            _q("qa", "트리 순회 문항", chapter="트리"),
            _q("qb", "그래프 탐색 문항", chapter="그래프"),
        ]
        report = analyze_questions(questions)

        cov = report["chapter_coverage"]
        assert cov["estimated"] is False, "직접 저장된 chapter 인데 추정으로 표기됨"
        assert report["meta"]["chapter_meta_stored"] is True
        assert cov["distinct_chapters"] == 3
        skewed_names = {s["chapter"] for s in cov["skewed_chapters"]}
        assert "정렬" in skewed_names, f"편중 챕터 미탐지: {cov['skewed_chapters']}"

    def test_chapter_estimated_when_meta_absent(self) -> None:
        # chapter/concept_key 없음 — topic 으로 추정 → estimated=True + 안내 노트.
        questions = [_q(f"q{i}", f"스택 자료구조 문항 {i}", topic="스택") for i in range(3)]
        report = analyze_questions(questions)

        assert report["chapter_coverage"]["estimated"] is True
        assert report["meta"]["chapter_meta_stored"] is False
        assert report["meta"]["chapter_basis"] == "estimated"
        assert any("chapter/concept_key" in n for n in report["meta"]["notes"])


# ── (c) 해설 길이 통계 ───────────────────────────────────────────────────────


class TestExplanationStats:
    """해설 길이 분류(누락/스텁/짧음/정상)와 min/max/mean 이 정확하다."""

    def test_length_buckets_and_stats(self) -> None:
        questions = [
            _q("q1", "문항1", explanation=""),                 # missing
            _q("q2", "문항2", explanation="정답."),            # stub (<=6자)
            _q("q3", "문항3", explanation="정답은 2번이다 짧다"),  # short (<40자)
            _q("q4", "문항4", explanation="가" * 80),          # ok (>=40자)
        ]
        report = analyze_questions(questions)
        exp = report["explanation_lengths"]

        assert exp["missing"] == 1
        assert exp["stub"] == 1
        assert exp["short"] == 1
        assert exp["ok"] == 1
        # 비어있지 않은 해설은 3개(q2,q3,q4) — min 은 q2(<=6), max 는 q4(80).
        assert exp["max_length"] == 80
        assert exp["min_length"] <= 6
        assert exp["mean_length"] > 0
        # 누락·스텁 문항이 점검 대상으로 식별된다.
        flagged_ids = {f["id"] for f in exp["flagged"]}
        assert {"q1", "q2"} <= flagged_ids


# ── (d) 빈/단일 입력 안전 ────────────────────────────────────────────────────


class TestEmptyAndSingleSafe:
    """빈 리스트·단일 문항에서 예외 없이 0/빈 매핑 리포트를 반환한다."""

    def test_empty_list_safe(self) -> None:
        report = analyze_questions([])
        assert report["question_count"] == 0
        assert report["scenario_gate"]["flagged_count"] == 0
        assert report["chapter_coverage"]["distinct_chapters"] == 0
        assert report["explanation_lengths"]["mean_length"] == 0.0
        assert report["type_distribution"]["distinct_types"] == 0
        # 텍스트 렌더도 예외 없이 동작한다.
        text = format_report_text("att_empty", report)
        assert "attempt_id=att_empty" in text

    def test_single_question_no_duplicate(self) -> None:
        report = analyze_questions([_q("only", "단일 문항", explanation="정답은 A이다.")])
        assert report["question_count"] == 1
        assert report["scenario_gate"]["flagged_count"] == 0  # 비교 대상 없음
        text = format_report_text("att_single", report)
        assert "문항 수: 1개" in text


# ── 유형 분포 ────────────────────────────────────────────────────────────────


class TestTypeDistribution:
    """template_id 유형 분포가 집계되고 빈 값은 UNKNOWN 으로 묶인다."""

    def test_type_counts_and_unknown_bucket(self) -> None:
        questions = [
            _q("q1", "a", template_id="mcq_single"),
            _q("q2", "b", template_id="mcq_single"),
            _q("q3", "c", template_id="short_answer"),
            _q("q4", "d"),  # template_id 없음 → UNKNOWN
        ]
        types = analyze_questions(questions)["type_distribution"]
        assert types["counts"]["mcq_single"] == 2
        assert types["counts"]["short_answer"] == 1
        assert types["counts"]["UNKNOWN"] == 1
        assert types["distinct_types"] == 3


# ── DB 어댑터 (mock 커넥션 — 라이브 호출 0) ──────────────────────────────────


class _FakeConn:
    """asyncpg 커넥션 흉내 — fetch 만 구현해 미리 준 행을 돌려준다(라이브 DB 없음)."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.last_query: str | None = None
        self.last_args: tuple = ()

    async def fetch(self, query: str, *args: object) -> list[dict]:
        self.last_query = query
        self.last_args = args
        return self._rows


class TestRowMapping:
    """exam_attempt_question 행 → 게이트 dict 변환을 검증한다."""

    def test_row_to_question_maps_columns(self) -> None:
        # options_json 은 JSONB → asyncpg 가 보통 str 로 준다. is_correct 키 복원 확인.
        row = {
            "question_id": "q_001",
            "template_id": "mcq_single",
            "display_order": 3,
            "stem": "다음 중 옳은 것은?",
            "options_json": json.dumps(
                [
                    {"label": "A", "text": "보기1", "is_correct": False},
                    {"label": "B", "text": "보기2", "is_correct": True},
                ],
                ensure_ascii=False,
            ),
            "points": 5,
            "correct_answer": "B",
            "explanation": "정답은 B이다.",
            "source_reference": "p.12",
            # grading_metadata_json 에 살아남는 메타 — topic 으로 챕터 추정.
            "grading_metadata_json": json.dumps(
                {"topic": "정렬", "difficulty": 3, "bloom_level": "apply"}
            ),
        }
        q = _row_to_question(row)

        assert q["question_id"] == "q_001"
        assert q["template_id"] == "mcq_single"
        assert q["stem"] == "다음 중 옳은 것은?"
        assert q["correct_answer"] == "B"
        assert q["explanation"] == "정답은 B이다."
        assert len(q["options"]) == 2
        assert q["options"][1]["is_correct"] is True
        # grading_metadata 평탄화 — 챕터 추정용 topic 이 최상위로 올라온다.
        assert q["topic"] == "정렬"
        assert q["difficulty"] == 3

    def test_row_to_question_tolerates_camelcase_options(self) -> None:
        # Spring 이 camelCase(isCorrect)로 저장한 경우도 복원한다.
        row = {
            "question_id": "q_002",
            "stem": "문항",
            "options_json": [{"label": "A", "text": "x", "isCorrect": True}],
        }
        q = _row_to_question(row)
        assert q["options"][0]["is_correct"] is True

    def test_row_to_question_bad_json_safe(self) -> None:
        # 깨진 JSON 은 빈 옵션/빈 메타로 안전 처리(분석은 stem 만으로 가능).
        row = {"question_id": "q_003", "stem": "문항", "options_json": "{not json"}
        q = _row_to_question(row)
        assert q["options"] == []

    def test_fetch_attempt_question_rows_uses_mock_conn(self) -> None:
        rows = [
            {"question_id": "q1", "stem": "문항1", "template_id": "mcq_single"},
            {"question_id": "q2", "stem": "문항2", "template_id": "mcq_single"},
        ]
        conn = _FakeConn(rows)
        result = asyncio.run(fetch_attempt_question_rows(conn, "att_123"))

        assert len(result) == 2
        assert result[0]["question_id"] == "q1"
        # attempt_id 가 파라미터로 바인딩됐는지(SQL 인젝션 방지 — 위치 인자) 확인.
        assert conn.last_args == ("att_123",)
        assert "exam_attempt_question" in (conn.last_query or "")


# ── 통합: 분포 + 게이트 + 텍스트 렌더가 함께 동작 ─────────────────────────────


class TestEndToEndReportRender:
    """mock 행 → 분석 → 텍스트 렌더가 예외 없이 한 번에 동작한다."""

    def test_full_pipeline_from_rows(self) -> None:
        rows = [
            {
                "question_id": f"q{i}",
                "stem": f"정렬 알고리즘에서 사용하는 비교 횟수를 묻는 문항 {i}",
                "template_id": "mcq_single",
                "explanation": "정답 근거 해설이 충분히 길게 작성된 정상 해설이다." * 2,
                "grading_metadata_json": json.dumps({"topic": "정렬"}),
            }
            for i in range(5)
        ]
        conn = _FakeConn(rows)
        questions = asyncio.run(fetch_attempt_question_rows(conn, "att_e2e"))
        report = analyze_questions(questions)
        text = format_report_text("att_e2e", report)

        assert report["question_count"] == 5
        assert report["meta"]["llm_calls"] == 0
        # 메타 미저장 경로 — 챕터는 topic 추정.
        assert report["chapter_coverage"]["estimated"] is True
        assert "ExamForge replay 품질 리포트" in text
        assert "att_e2e" in text


# ── DB 로드 가드 + CLI (라이브 DB 없음 — monkeypatch) ────────────────────────


class TestLoadGuardAndCli:
    """DATABASE_URL 미설정 가드와 CLI 경로를 라이브 DB 없이 검증한다."""

    def test_load_raises_without_dsn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # DATABASE_URL 미설정 → RuntimeError(연결 시도 전에 즉시 실패).
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            asyncio.run(load_attempt_questions("att_x"))

    def test_cli_renders_report_with_mocked_loader(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # load_attempt_questions 를 mock 해 DB·LLM 없이 CLI 전체 경로를 탄다.
        async def _fake_load(attempt_id: str) -> list[dict]:
            return [_q("q1", "정렬 문항", explanation="정답은 A이다.", topic="정렬")]

        monkeypatch.setattr(replay_mod, "load_attempt_questions", _fake_load)
        rc = main(["att_cli"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ExamForge replay 품질 리포트" in out
        assert "att_cli" in out

    def test_cli_returns_1_on_load_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        async def _boom(attempt_id: str) -> list[dict]:
            raise RuntimeError("DB 다운")

        monkeypatch.setattr(replay_mod, "load_attempt_questions", _boom)
        rc = main(["att_fail"])
        assert rc == 1
        assert "로드 실패" in capsys.readouterr().out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

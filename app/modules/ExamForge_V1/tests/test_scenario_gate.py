"""시나리오 중복·개념 과대표현 게이트 단위 테스트 (subject-agnostic, 라이브 호출 없음).

검증 범위:
(a) 같은 숫자열 시나리오 2문항 → 중복 플래그
(b) 서로 다른 시나리오 → 통과
(c) 같은 개념 3/10 → 과대표현 플래그
(d) 좁은 소스로 교체 불가 시 무한루프 없이 종료 (route_after_validation 캡과 정합)
+ subject-agnostic 보장(특정 과목 무관), 기존 게이트와의 충돌 없음, validate_node 배선

의미 중복(토큰 Jaccard) 검증 범위:
(s-a) @SpringBootApplication 류 4문항(숫자 없음, 토큰 겹침) → keep=2 초과분 2개 플래그
(s-b) Starter 유사쌍/트리오 → 초과분 플래그(영문 식별자 강한 신호)
(s-c) 삽입 vs 삭제 등 토큰이 충분히 다른 문항 → 통과(오탐 0)
(s-d) Jaccard 임계 경계 동작
(s-e) subject-agnostic(파이썬/수학 동일 구조 → 동일 처리)

전부 mock/fixture 기반 — Gemini 등 라이브 AI 생성·임베딩 API 호출 없음.
"""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.pipeline.nodes.validate_node import _apply_scenario_gate
from app.modules.ExamForge_V1.pipeline.nodes.retry_router_node import route_after_validation
from app.modules.ExamForge_V1.quality.scenario_gate import (
    _jaccard,
    _semantic_token_set,
    check_scenario_quality,
    find_duplicate_scenarios,
    find_overrepresented_concepts,
    find_semantic_duplicates,
    scenario_signature,
)


def _q(draft_id: str, stem: str, **extra: object) -> dict:
    """테스트용 문항 dict 헬퍼."""
    q: dict = {"draft_id": draft_id, "stem": stem}
    q.update(extra)
    return q


# ── (a) 같은 숫자열 시나리오 중복 ─────────────────────────────────────────────

class TestDuplicateScenario:
    """등장 숫자 시퀀스가 같은 시나리오 재활용을 잡는다."""

    def test_same_number_sequence_flagged(self) -> None:
        """같은 삽입 수열을 쓰는 두 문항 중 뒤쪽이 중복으로 플래그된다."""
        questions = [
            _q("d1", "12, 8, 18, 10 순서로 자료에 삽입했을 때 결과로 옳은 것은?"),
            _q("d2", "다음 중 12, 8, 18, 10 을 차례로 삽입한 뒤의 상태는?"),
        ]
        flagged = find_duplicate_scenarios(questions)
        assert "d2" in flagged, "같은 숫자열 재활용 문항이 플래그되지 않았다"
        assert "d1" not in flagged, "최초 문항이 잘못 플래그됐다"
        assert "시나리오 중복" in flagged["d2"][0]

    def test_signature_stable_across_wording(self) -> None:
        """발문 어휘가 달라도 숫자열+핵심 토큰이 같으면 서명이 같다."""
        a = scenario_signature(_q("d1", "12, 8, 18, 10 을 삽입한 트리의 결과는?"))
        b = scenario_signature(_q("d2", "트리에 12, 8, 18, 10 삽입 결과로 옳은 것은?"))
        assert a == b and a != ""

    def test_three_same_scenario_flags_two(self) -> None:
        """같은 시나리오 3문항이면 최초 1개만 보존하고 2개를 플래그한다."""
        questions = [
            _q("d1", "5 3 9 1 삽입 순서에서 트리 높이는?"),
            _q("d2", "5 3 9 1 을 삽입했을 때 트리 높이로 옳은 것은?"),
            _q("d3", "5 3 9 1 순으로 넣은 트리의 높이를 구하면?"),
        ]
        flagged = find_duplicate_scenarios(questions)
        assert set(flagged) == {"d2", "d3"}


# ── (b) 서로 다른 시나리오는 통과 ─────────────────────────────────────────────

class TestDistinctScenariosPass:
    """수치/구조가 다른 시나리오는 중복으로 잡지 않는다."""

    def test_different_numbers_pass(self) -> None:
        """다른 숫자열을 쓰는 문항들은 통과한다."""
        questions = [
            _q("d1", "12, 8, 18 삽입 결과는?"),
            _q("d2", "30, 25, 40 삽입 결과는?"),
            _q("d3", "7, 3, 11 삽입 결과는?"),
        ]
        assert find_duplicate_scenarios(questions) == {}

    def test_same_numbers_different_order_distinct(self) -> None:
        """같은 값이라도 등장 순서가 다르면 다른 시나리오로 본다."""
        a = scenario_signature(_q("d1", "12, 8, 18 순서로 삽입"))
        b = scenario_signature(_q("d2", "8, 12, 18 순서로 삽입"))
        assert a != b

    def test_no_numbers_distinct_concepts_pass(self) -> None:
        """숫자가 없어도 핵심 토큰이 충분히 다르면 통과한다."""
        questions = [
            _q("d1", "프로세스 스케줄링에서 선점형 방식의 특징으로 옳은 것은?"),
            _q("d2", "가상 메모리의 페이지 교체 알고리즘으로 옳은 것은?"),
        ]
        assert find_duplicate_scenarios(questions) == {}


# ── (c) 같은 개념 과대표현 ────────────────────────────────────────────────────

class TestOverRepresentation:
    """같은 정규화 개념이 임계를 초과하면 초과분을 플래그한다."""

    def _ten_with_repeat(self, repeat_count: int) -> list[dict]:
        """repeat_count 개는 같은 concept_key, 나머지는 서로 다른 10문항 세트."""
        questions: list[dict] = []
        for i in range(repeat_count):
            questions.append(_q(
                f"dup{i}", f"중복 개념 발문 {i}: 값 {i} 적용 결과는?",
                _concept_key="챕터A::주제A::중복개념::d3::2단계 적용 추론",
            ))
        for i in range(10 - repeat_count):
            questions.append(_q(
                f"uniq{i}", f"고유 개념 발문 {i}: 값 {i} 적용 결과는?",
                _concept_key=f"챕터{i}::주제{i}::개념{i}::d3::개념 확인",
            ))
        return questions

    def test_same_concept_three_of_ten_flagged(self) -> None:
        """같은 개념 3/10(30% > 20%, 절대 3 > 2)이면 초과분 1개가 플래그된다."""
        questions = self._ten_with_repeat(3)
        flagged = find_overrepresented_concepts(questions)
        # 임계 = max(2, int(10*0.2)=2) = 2 → 앞 2개 보존, 3번째(dup2)만 플래그
        assert "dup2" in flagged, "과대표현 초과분이 플래그되지 않았다"
        assert "dup0" not in flagged and "dup1" not in flagged, "보존분이 잘못 플래그됐다"
        assert "과대표현" in flagged["dup2"][0]

    def test_concept_key_suffix_variation_grouped(self) -> None:
        """diff/reasoning suffix 가 달라도 같은 개념(앞 3토막)이면 함께 묶인다."""
        questions = [
            _q("d1", "발문 1", _concept_key="C::T::동일개념::d3::2단계 적용 추론"),
            _q("d2", "발문 2", _concept_key="C::T::동일개념::d4::오류 원인 분석"),
            _q("d3", "발문 3", _concept_key="C::T::동일개념::d2::개념 확인"),
            _q("d4", "발문 4", _concept_key="C::T::동일개념::d5::트레이드오프"),
        ] + [
            _q(f"u{i}", f"고유 발문 {i}", _concept_key=f"C{i}::T{i}::개념{i}::d3::x")
            for i in range(6)
        ]
        flagged = find_overrepresented_concepts(questions)
        # 동일개념 4개 중 임계(2) 초과분 2개(d3, d4) 플래그
        assert set(flagged) == {"d3", "d4"}

    def test_balanced_set_passes(self) -> None:
        """개념이 고르게 분산된 10문항은 과대표현 없음."""
        questions = [
            _q(f"d{i}", f"발문 {i}", _concept_key=f"C{i}::T{i}::개념{i}::d3::x")
            for i in range(10)
        ]
        assert find_overrepresented_concepts(questions) == {}

    def test_small_set_skipped(self) -> None:
        """전체 문항이 적으면(< min) 개념 종류가 본래 적어 게이트 생략."""
        questions = [
            _q("d1", "발문1", _concept_key="C::T::개념X::d3::x"),
            _q("d2", "발문2", _concept_key="C::T::개념X::d3::x"),
            _q("d3", "발문3", _concept_key="C::T::개념X::d3::x"),
        ]
        # 3문항(< _OVERREP_MIN_QUESTIONS=5) → 생략
        assert find_overrepresented_concepts(questions) == {}

    def test_stem_fallback_concept_label(self) -> None:
        """concept_key 가 없으면 stem 핵심 토큰 어간으로 과대표현을 본다(메타 없는 경로).

        실제 개념 과대표현은 LLM 이 같은 핵심 명사구를 반복하는 형태로 나타난다 —
        같은 토큰 집합(어순만 다름)을 쓰는 발문 3개 + 서로 다른 발문 7개.
        """
        questions = [
            _q("s1", "이진탐색트리 노드 삭제 연산으로 옳은 것은?"),
            _q("s2", "다음 중 이진탐색트리 노드 삭제 연산은?"),
            _q("s3", "이진탐색트리 노드 삭제 연산을 고르시오."),
        ] + [
            _q(f"u{i}", f"서로 다른 핵심개념{i} 적용 비교 평가 결과 분석 항목{i}")
            for i in range(7)
        ]
        flagged = find_overrepresented_concepts(questions)
        assert "s3" in flagged, "stem 폴백 개념 집계가 동작하지 않았다"


# ── (d) 좁은 소스 교체 불가 — 무한루프 없이 종료 ──────────────────────────────

class TestNarrowSourceNoInfiniteLoop:
    """게이트가 잡은 문항을 교체하지 못해도 기존 재시도 캡으로 graceful 종료한다.

    이 게이트는 failed_ids 에만 합류하므로 새로운 루프를 만들지 않는다. 종료는
    route_after_validation 의 기존 캡(max_retries / count_stuck_rounds)이 담당한다.
    """

    def _flagged_questions(self) -> list[dict]:
        """시나리오 중복이 있는 5문항(좁은 소스 — 교체해도 같은 시나리오만 나옴)."""
        return [
            _q(f"d{i}", "12, 8, 18 삽입 결과는?", _concept_key="C::T::개념X::d3::x")
            for i in range(5)
        ]

    def test_gate_flags_but_route_exhausts_at_max_retries(self) -> None:
        """최대 재시도에 도달하면 게이트가 계속 플래그해도 exhausted 로 종료한다."""
        questions = self._flagged_questions()
        # validate 단계에서 게이트가 채운 failed_ids 를 흉내낸다(4건 중복).
        failed_ids = [f"d{i}" for i in range(1, 5)]
        state = {
            "verified_questions": questions,
            "failed_question_ids": failed_ids,
            "retry_count": 3,
            "max_retries": 3,
            "exam_plan": {},
            "validation_report": {
                "answer_accuracy_rate": 1.0,
                "dedup_score": 1.0,
                "missing_count": 0,
                "answer_position_mismatch": False,
            },
        }
        # 실패율(4/5=80% >= 10%)이 높지만 retry_count == max_retries → 재시도 없이 종료.
        assert route_after_validation(state) == "exhausted"

    def test_gate_idempotent_no_growth(self) -> None:
        """같은 입력에 게이트를 반복 적용해도 failed_ids 가 무한히 늘지 않는다."""
        questions = self._flagged_questions()
        failed_ids: list[str] = []
        issues: list[str] = []
        _apply_scenario_gate(questions, failed_ids, issues)
        first = sorted(failed_ids)
        # 두 번째 적용(같은 입력) — 중복 추가 방지로 동일해야 한다.
        _apply_scenario_gate(questions, failed_ids, issues)
        assert sorted(failed_ids) == first, "게이트 재적용이 failed_ids 를 증식시켰다"


# ── subject-agnostic 보장: 어떤 과목이든 동일 동작 ───────────────────────────

class TestSubjectAgnostic:
    """특정 과목 단어가 아니라 구조 신호로만 판단함을 확인한다."""

    def test_python_and_math_same_structure_both_flagged(self) -> None:
        """파이썬·수학 발문 모두 같은 숫자열이면 동일하게 중복 처리된다."""
        py = [
            _q("p1", "리스트 [3, 1, 4]를 정렬한 결과는?"),
            _q("p2", "[3, 1, 4]를 오름차순 정렬하면?"),
        ]
        math = [
            _q("m1", "수열 5, 2, 9의 중앙값은?"),
            _q("m2", "5, 2, 9 의 중앙값을 구하면?"),
        ]
        assert "p2" in find_duplicate_scenarios(py)
        assert "m2" in find_duplicate_scenarios(math)


# ── 기존 게이트와의 정합 + validate_node 배선 ────────────────────────────────

class TestWiringAndCompat:
    """check_scenario_quality 병합 + validate_node 배선 동작."""

    def test_check_scenario_quality_merges_both(self) -> None:
        """중복+과대표현이 동시에 걸린 문항의 issue 가 병합된다."""
        # 같은 개념 + 같은 시나리오를 함께 가진 6문항 세트
        questions = [
            _q(f"d{i}", "12, 8, 18 삽입 결과는?", _concept_key="C::T::개념X::d3::x")
            for i in range(6)
        ]
        merged = check_scenario_quality(questions)
        # d1..d5 는 시나리오 중복이며, 개념 과대표현 임계 초과분에도 걸린다.
        assert "d1" in merged
        # 한 문항에 두 게이트가 모두 걸리면 issue 가 2개 이상 합쳐진다.
        multi = [v for v in merged.values() if len(v) >= 2]
        assert multi, "중복+과대표현 issue 병합이 동작하지 않았다"

    def test_apply_scenario_gate_appends_failed_ids(self) -> None:
        """validate_node 헬퍼가 플래그 문항을 failed_ids·global_issues 에 반영한다."""
        questions = [
            _q("d_first", "12, 8, 18 삽입 결과는?"),
            _q("d_dup", "다음 중 12, 8, 18 삽입 결과로 옳은 것은?"),
        ]
        failed_ids: list[str] = []
        global_issues: list[str] = []
        _apply_scenario_gate(questions, failed_ids, global_issues)
        assert failed_ids == ["d_dup"]
        assert any("시나리오 중복" in issue or "과대표현" in issue for issue in global_issues)

    def test_apply_scenario_gate_no_duplicate_ids(self) -> None:
        """이미 failed_ids 에 있는 draft_id 는 중복 추가되지 않는다(기존 게이트 합류)."""
        questions = [
            _q("d_first", "12, 8, 18 삽입 결과는?"),
            _q("d_dup", "12, 8, 18 삽입 결과로 옳은 것은?"),
        ]
        failed_ids = ["d_dup"]  # 이미 다른 게이트가 넣은 상태
        global_issues: list[str] = []
        _apply_scenario_gate(questions, failed_ids, global_issues)
        assert failed_ids.count("d_dup") == 1, "중복 게이트가 같은 id 를 또 넣었다"

    def test_clean_set_no_flags(self) -> None:
        """중복·과대표현이 없는 정상 세트는 게이트가 아무것도 표시하지 않는다(회귀 방지)."""
        questions = [
            _q(f"d{i}", f"서로 다른 주제 {i}: 값 {i*7}, {i*3} 적용 결과 비교는?",
               _concept_key=f"C{i}::T{i}::개념{i}::d3::x")
            for i in range(10)
        ]
        failed_ids: list[str] = []
        global_issues: list[str] = []
        _apply_scenario_gate(questions, failed_ids, global_issues)
        assert failed_ids == []
        assert global_issues == []


# ── 경계 입력 ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """빈 입력·단일 문항·빈 stem 에서 크래시 없이 합리적 판정."""

    def test_empty_questions(self) -> None:
        assert find_duplicate_scenarios([]) == {}
        assert find_overrepresented_concepts([]) == {}
        assert check_scenario_quality([]) == {}

    def test_single_question(self) -> None:
        assert find_duplicate_scenarios([_q("d1", "12, 8 삽입 결과는?")]) == {}

    def test_empty_stem_no_signature(self) -> None:
        """빈 stem 은 시그니처가 비어 게이트에서 제외된다(구조 검증 영역)."""
        assert scenario_signature(_q("d1", "")) == ""
        questions = [_q("d1", ""), _q("d2", ""), _q("d3", "")]
        # 빈 시그니처끼리는 중복으로 묶지 않는다.
        assert find_duplicate_scenarios(questions) == {}

    def test_missing_stem_key_safe(self) -> None:
        """stem 키가 없어도 크래시하지 않는다."""
        assert scenario_signature({"draft_id": "d1"}) == ""


# ── (s-a~e) 의미 중복(토큰 Jaccard) 검출 ──────────────────────────────────────

class TestSemanticDuplicate:
    """발문은 다르나 같은 지식을 묻는 의미 중복을 토큰 Jaccard 로 잡는다.

    숫자열 서명이 못 잡는, 숫자 없는 의미 반복(@SpringBootApplication 자동설정
    연결을 발문만 바꿔 여러 번 출제 등)을 검출한다. 라이브/임베딩 호출 없음.
    """

    def test_springboot_four_questions_flags_two(self) -> None:
        """(s-a) 같은 지식(@SpringBootApplication 자동 구성 연결)을 묻는 4문항 →
        keep=2 초과분 2개(뒤쪽)가 플래그된다. 숫자 신호가 전혀 없어도 토큰 겹침으로 잡는다."""
        questions = [
            _q("q4", "@SpringBootApplication 애너테이션이 자동 구성과 연결되는 방식으로 옳은 것은?",
               correct_answer="자동 구성 연결"),
            _q("q8", "다음 중 @SpringBootApplication 이 자동 구성과 연결되는 설명으로 옳은 것은?",
               correct_answer="자동 구성 연결"),
            _q("q15", "@SpringBootApplication 의 자동 구성 연결 동작으로 가장 적절한 것은?",
               correct_answer="자동 구성 연결"),
            _q("q19", "@SpringBootApplication 구성이 자동 구성과 연결되는 원리로 옳은 것은?",
               correct_answer="자동 구성 연결"),
        ]
        flagged = find_semantic_duplicates(questions)
        # 앞 2개(q4,q8) 보존, 뒤 2개(q15,q19) 플래그
        assert set(flagged) == {"q15", "q19"}, f"기대=2개 초과분, 실제={sorted(flagged)}"
        assert "q4" not in flagged and "q8" not in flagged
        assert "의미 중복" in flagged["q15"][0]

    def test_starter_similar_trio_flags_overflow(self) -> None:
        """(s-b) Starter 의존성 묶음을 묻는 유사 3문항 → keep=2 초과분 1개 플래그.
        영문 식별자 'starter' 가 강한 중복 신호로 작동한다."""
        questions = [
            _q("q11", "starter 의존성이 관련 라이브러리를 한데 묶어 제공하는 방식으로 옳은 것은?",
               correct_answer="starter 의존성 묶음 제공"),
            _q("q18", "다음 중 starter 의존성이 라이브러리를 묶어 제공하는 설명으로 옳은 것은?",
               correct_answer="starter 의존성 묶음 제공"),
            _q("q20", "starter 의존성이 라이브러리 묶음을 제공하는 원리로 옳은 것은?",
               correct_answer="starter 의존성 묶음 제공"),
        ]
        flagged = find_semantic_duplicates(questions)
        assert "q20" in flagged, "Starter 유사 초과분이 플래그되지 않았다"
        assert "q11" not in flagged and "q18" not in flagged, "보존분이 잘못 플래그됐다"

    def test_starter_pair_with_distractors_not_flagged(self) -> None:
        """(s-b') Starter 유사쌍(2개)만 있고 keep=2 이하면 플래그하지 않는다 —
        변별 가치 있는 소수는 보존(보수적 정책)."""
        questions = [
            _q("q11", "starter 의존성이 관련 라이브러리를 한데 묶어 제공하는 방식으로 옳은 것은?",
               correct_answer="starter 의존성 묶음 제공"),
            _q("q18", "다음 중 starter 의존성이 라이브러리를 묶어 제공하는 설명으로 옳은 것은?",
               correct_answer="starter 의존성 묶음 제공"),
            _q("u1", "프로파일별 외부 설정을 분리해 적용하는 방식으로 옳은 것은?",
               correct_answer="프로파일 외부 설정 분리"),
            _q("u2", "액추에이터가 헬스 체크 엔드포인트를 노출하는 방식으로 옳은 것은?",
               correct_answer="액추에이터 헬스 엔드포인트"),
        ]
        # 유사쌍은 2개(=keep) 뿐 → 초과분 없음. 나머지는 토큰이 달라 안 묶임.
        assert find_semantic_duplicates(questions) == {}

    def test_insert_vs_delete_not_flagged(self) -> None:
        """(s-c) 같은 자료구조라도 삽입/삭제/탐색 등 연산이 다르면 토큰이 충분히
        달라 의미 중복으로 잡지 않는다(오탐 0)."""
        questions = [
            _q("i1", "이진탐색트리에 노드를 삽입하는 연산의 동작으로 옳은 것은?",
               correct_answer="삽입 후 균형 유지"),
            _q("d1", "이진탐색트리에서 노드를 삭제하는 연산의 동작으로 옳은 것은?",
               correct_answer="삭제 후 후계자 승격"),
            _q("s1", "이진탐색트리에서 노드를 탐색하는 연산의 시간복잡도로 옳은 것은?",
               correct_answer="평균 로그 시간"),
        ]
        assert find_semantic_duplicates(questions) == {}

    def test_distinct_concepts_not_flagged(self) -> None:
        """(s-c') 서로 다른 핵심 개념을 묻는 문항들은 토큰 겹침이 낮아 통과한다."""
        questions = [
            _q("c1", "프로세스 스케줄링에서 선점형 방식의 특징으로 옳은 것은?",
               correct_answer="선점형 우선순위 교체"),
            _q("c2", "가상 메모리의 페이지 교체 알고리즘으로 옳은 것은?",
               correct_answer="LRU 페이지 교체"),
            _q("c3", "교착 상태의 발생 조건으로 옳은 것은?",
               correct_answer="상호 배제 점유 대기"),
        ]
        assert find_semantic_duplicates(questions) == {}

    def test_jaccard_threshold_boundary(self) -> None:
        """(s-d) Jaccard 임계 경계 — 임계 미만이면 묶지 않고, 이상이면 묶는다."""
        a = _q("a", "스프링 빈 생명주기 초기화 콜백 동작으로 옳은 것은?",
               correct_answer="빈 초기화 콜백")
        b_high = _q("b", "다음 중 스프링 빈 생명주기 초기화 콜백 동작 설명으로 옳은 것은?",
                    correct_answer="빈 초기화 콜백")
        b_low = _q("b", "트랜잭션 전파 속성의 동작으로 옳은 것은?",
                   correct_answer="전파 속성 적용")
        ta, th, tl = (_semantic_token_set(a), _semantic_token_set(b_high),
                      _semantic_token_set(b_low))
        # 거의 같은 발문은 임계(0.55) 이상, 전혀 다른 발문은 임계 미만.
        assert _jaccard(ta, th) >= 0.55, "동일 지식 발문이 임계 미만으로 측정됐다"
        assert _jaccard(ta, tl) < 0.55, "다른 지식 발문이 임계 이상으로 측정됐다"
        # 클러스터링 결과: 3문항(a, b_high, b_low) 중 a·b_high 만 유사 → keep=2 → 초과 없음.
        assert find_semantic_duplicates([a, b_high, b_low]) == {}
        # 같은 유사군 3개면 1개 초과분 플래그.
        a2 = _q("a2", "스프링 빈 생명주기 초기화 콜백의 동작 원리로 옳은 것은?",
                correct_answer="빈 초기화 콜백")
        flagged = find_semantic_duplicates([a, b_high, a2])
        assert "a2" in flagged

    def test_subject_agnostic_python_and_math(self) -> None:
        """(s-e) 파이썬·수학 등 어떤 과목이든 같은 구조(토큰 겹침)면 동일하게 처리한다.
        특정 과목 단어 하드코딩 없이 토큰 겹침 비율만으로 판단함을 보장한다."""
        python = [
            _q("p1", "리스트 컴프리헨션이 반복문을 간결하게 표현하는 방식으로 옳은 것은?",
               correct_answer="리스트 컴프리헨션 간결 표현"),
            _q("p2", "다음 중 리스트 컴프리헨션이 반복문을 간결히 표현하는 설명으로 옳은 것은?",
               correct_answer="리스트 컴프리헨션 간결 표현"),
            _q("p3", "리스트 컴프리헨션으로 반복문을 간결하게 작성하는 원리로 옳은 것은?",
               correct_answer="리스트 컴프리헨션 간결 표현"),
        ]
        math = [
            _q("m1", "코사인 함수의 주기성이 그래프에 나타나는 성질로 옳은 것은?",
               correct_answer="코사인 주기성 성질"),
            _q("m2", "다음 중 코사인 함수의 주기성 성질 설명으로 옳은 것은?",
               correct_answer="코사인 주기성 성질"),
            _q("m3", "코사인 함수가 주기성을 갖는 성질로 가장 적절한 것은?",
               correct_answer="코사인 주기성 성질"),
        ]
        assert "p3" in find_semantic_duplicates(python), "파이썬 의미 중복 미검출"
        assert "m3" in find_semantic_duplicates(math), "수학 의미 중복 미검출"

    def test_numeric_questions_deferred_to_scenario_gate(self) -> None:
        """변별 숫자열을 가진 문항은 의미 중복에서 제외된다 — 숫자열 시나리오 게이트의
        영역이라 서로 다른 수치 예시를 의미 중복으로 오탐하지 않는다."""
        questions = [
            _q("n1", "서로 다른 주제 1: 값 7, 3 적용 결과 비교는?"),
            _q("n2", "서로 다른 주제 2: 값 14, 6 적용 결과 비교는?"),
            _q("n3", "서로 다른 주제 3: 값 21, 9 적용 결과 비교는?"),
        ]
        # 발문 골격은 같지만 변별 숫자가 있으므로 의미 중복에서 제외(scenario_gate 담당).
        assert find_semantic_duplicates(questions) == {}

    def test_short_questions_excluded(self) -> None:
        """내용 토큰이 _SEMANTIC_MIN_TOKENS 미만인 짧은 발문은 클러스터링 제외(오탐 방지)."""
        questions = [
            _q("s1", "옳은 것은?"),
            _q("s2", "옳은 것은?"),
            _q("s3", "옳은 것은?"),
        ]
        assert find_semantic_duplicates(questions) == {}

    def test_empty_and_single_safe(self) -> None:
        """빈 입력·단일 문항·keep 이하 문항에서 크래시 없이 빈 매핑."""
        assert find_semantic_duplicates([]) == {}
        assert find_semantic_duplicates([_q("d1", "스프링 빈 생명주기 초기화 동작은?")]) == {}
        # keep=2 이하 문항 수면 초과분이 나올 수 없어 즉시 빈 매핑.
        assert find_semantic_duplicates([
            _q("d1", "스프링 빈 생명주기 초기화 동작은?", correct_answer="초기화"),
            _q("d2", "스프링 빈 생명주기 초기화 동작 설명은?", correct_answer="초기화"),
        ]) == {}

    def test_merged_into_check_scenario_quality(self) -> None:
        """check_scenario_quality 가 의미 중복 결과를 합류시킨다(게이트 정합)."""
        questions = [
            _q("q1", "@SpringBootApplication 이 자동 구성과 연결되는 방식으로 옳은 것은?",
               correct_answer="자동 구성 연결"),
            _q("q2", "다음 중 @SpringBootApplication 자동 구성 연결 설명으로 옳은 것은?",
               correct_answer="자동 구성 연결"),
            _q("q3", "@SpringBootApplication 의 자동 구성 연결 동작으로 옳은 것은?",
               correct_answer="자동 구성 연결"),
        ]
        merged = check_scenario_quality(questions)
        assert "q3" in merged, "의미 중복이 check_scenario_quality 에 합류되지 않았다"

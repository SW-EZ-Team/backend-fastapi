"""출처 관련성 게이트 + 난이도 발현 게이트 테스트."""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.pipeline.nodes.concept_blueprint import blueprint_prompt
from app.modules.ExamForge_V1.pipeline.nodes.validate_node import _apply_relevance_gate
from app.modules.ExamForge_V1.quality.difficulty_scorer import check_difficulty_manifestation
from app.modules.ExamForge_V1.quality.relevance_gate import (
    MIN_VOCAB_SIZE,
    build_source_vocabulary,
    check_question_relevance,
    check_questions_relevance,
)

# Rust 학습 자료 샘플 — 관련성 게이트가 활성화될 만큼 어휘가 충분한 출처
_RUST_SOURCE = """
Rust의 소유권(ownership) 시스템은 메모리 안전성을 컴파일 타임에 보장한다.
모든 값은 단 하나의 소유자(owner)를 가지며, 소유자가 스코프를 벗어나면 값이 해제된다.
변수를 다른 변수에 대입하면 이동(move)이 발생하고, 원래 변수는 더 이상 사용할 수 없다.
차용(borrowing)은 참조(reference)를 통해 소유권을 넘기지 않고 값에 접근하는 방법이다.
불변 참조(&T)는 동시에 여러 개 존재할 수 있지만, 가변 참조(&mut T)는 한 번에 하나만 허용된다.
수명(lifetime)은 참조가 유효한 범위를 표시하며, 댕글링 포인터를 컴파일 단계에서 차단한다.
String 타입은 힙에 할당되고, fn main 함수에서 let 바인딩으로 생성할 수 있다.
클로저(closure)는 환경을 캡처하며 Fn, FnMut, FnOnce 트레이트로 구분된다.
"""

_RUST_TOPICS = [
    {
        "name": "소유권과 이동",
        "sub_concepts": ["move 의미론", "소유자 규칙"],
        "keywords": ["ownership", "move"],
    },
    {
        "name": "차용과 수명",
        "sub_concepts": ["불변 참조", "가변 참조", "lifetime"],
        "keywords": ["borrowing", "reference"],
    },
]


class TestRelevanceGate:
    """출처 관련성 게이트 테스트."""

    def test_vocabulary_includes_source_and_topic_terms(self) -> None:
        """출처 발췌와 주제 메타의 어휘가 모두 어휘 집합에 들어간다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        assert len(vocab) >= MIN_VOCAB_SIZE
        assert "ownership" in vocab
        assert "lifetime" in vocab
        # 한국어 조사 정규화 확인 — "소유권(ownership)" → 소유권 계열 토큰 존재
        assert any(token.startswith("소유") for token in vocab)

    def test_on_topic_question_passes(self) -> None:
        """출처 개념(소유권/이동)에 근거한 문항은 통과한다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        question = {
            "stem": "Rust에서 이동(move)이 발생한 뒤 원래 변수에 접근하면 어떻게 되는가?",
            "options": [
                {"text": "컴파일 오류가 발생한다"},
                {"text": "런타임에 값이 복사된다"},
            ],
        }
        assert check_question_relevance(question, vocab) == []

    def test_off_topic_question_flagged(self) -> None:
        """출처와 무관한 일반 상식 문항은 결함으로 보고된다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        question = {
            "stem": "조선 왕조를 건국한 인물과 건국 연도로 짝지어진 항목은?",
            "options": [
                {"text": "이성계, 1392년"},
                {"text": "왕건, 918년"},
            ],
        }
        issues = check_question_relevance(question, vocab)
        assert issues
        assert "출처 무관" in issues[0]

    def test_code_heavy_question_passes(self) -> None:
        """짧은 발문이라도 코드 토큰이 출처 코드 어휘와 겹치면 통과한다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        question = {
            "stem": "다음 코드의 실행 결과는?",
            "code_snippet": 'fn main() { let s = String::from("hi"); }',
            "options": [{"text": "컴파일 오류"}, {"text": "hi 출력"}],
        }
        assert check_question_relevance(question, vocab) == []

    def test_gate_skipped_for_stub_source(self) -> None:
        """스텁 source_text(어휘 빈약)에서는 게이트가 자체 생략된다."""
        stub_source = "과목: Rust. 주제: 소유권."
        questions = [{"stem": "조선 왕조를 건국한 인물은?", "draft_id": "d1"}]
        flagged = check_questions_relevance(questions, stub_source, [])
        assert flagged == {}

    def test_validate_node_wiring_appends_failed_ids(self) -> None:
        """validate_node 게이트 적용 시 출처 무관 문항이 failed_ids에 추가된다."""
        state = {
            "source_text": _RUST_SOURCE,
            "topics": _RUST_TOPICS,
        }
        questions = [
            {
                "stem": "가변 참조(&mut)가 동시에 두 개 존재할 때 컴파일러의 동작은?",
                "draft_id": "d_on",
                "options": [{"text": "컴파일 오류"}],
            },
            {
                "stem": "세계에서 가장 높은 산의 이름과 높이를 고르시오.",
                "draft_id": "d_off",
                "options": [{"text": "에베레스트, 8848m"}],
            },
        ]
        failed_ids: list[str] = []
        global_issues: list[str] = []
        _apply_relevance_gate(state, questions, failed_ids, global_issues)
        assert failed_ids == ["d_off"]
        assert any("출처 무관" in issue for issue in global_issues)


class TestDifficultyManifestation:
    """난이도 발현 게이트(상위 블룸 정의 회상 차단) 테스트."""

    def test_high_difficulty_recall_stem_flagged(self) -> None:
        """난이도 4 문항이 정의 회상형 발문이면 결함으로 보고된다."""
        question = {"difficulty": 4, "stem": "Rust의 소유권이란 무엇인가?"}
        issues = check_difficulty_manifestation(question)
        assert issues
        assert "정의 회상형" in issues[0]

    def test_high_difficulty_definition_pattern_flagged(self) -> None:
        """'정의로 가장 적절한 것은' 류 발문도 난이도 5에서 결함이다."""
        question = {"difficulty": 5, "stem": "차용(borrowing)의 정의로 가장 적절한 것은?"}
        assert check_difficulty_manifestation(question)

    def test_high_difficulty_analysis_stem_passes(self) -> None:
        """비교·분석을 요구하는 난이도 4 발문은 통과한다."""
        question = {
            "difficulty": 4,
            "stem": "불변 참조와 가변 참조의 동시 존재 규칙을 비교할 때, 컴파일 오류가 발생하는 경우는?",
        }
        assert check_difficulty_manifestation(question) == []

    def test_low_difficulty_recall_stem_passes(self) -> None:
        """난이도 2(이해) 문항은 정의 회상형이라도 정상이다."""
        question = {"difficulty": 2, "stem": "소유권이란 무엇인가?"}
        assert check_difficulty_manifestation(question) == []

    def test_code_snippet_question_skipped(self) -> None:
        """코드 스니펫 문항은 추적/분석 문항이므로 검사하지 않는다."""
        question = {
            "difficulty": 4,
            "stem": "다음 코드에서 x란 무엇을 가리키는가?",
            "code_snippet": "let x = &mut v;",
        }
        assert check_difficulty_manifestation(question) == []

    def test_code_trace_stem_not_false_positive(self) -> None:
        """'출력은 무엇인가' 류 코드 추적 발문은 회상형으로 오탐하지 않는다."""
        question = {"difficulty": 4, "stem": "위 함수 호출 후 벡터의 최종 출력은 무엇인가?"}
        assert check_difficulty_manifestation(question) == []


class TestBlueprintDifficultyDirective:
    """blueprint_prompt 난이도 요구사항 주입 테스트."""

    def test_level4_directive_present(self) -> None:
        """난이도 4 슬롯 프롬프트에 조작적 요구사항(비교/추적/엣지케이스)이 들어간다."""
        slot = {
            "chapter": "차용과 수명",
            "concept": "가변 참조 규칙",
            "difficulty": 4,
            "bloom_level": "분석",
            "reasoning_type": "오류 원인 분석",
            "num_choices": 5,
            "target_answer_position": 2,
        }
        prompt = blueprint_prompt(slot)
        assert "난이도 요구사항" in prompt
        assert "엣지케이스" in prompt
        assert "정의 회상" in prompt

    def test_level5_directive_requires_multistep(self) -> None:
        """난이도 5 슬롯은 다단계 추론 요구가 명시된다."""
        slot = {"concept": "수명 생략 규칙", "difficulty": 5, "num_choices": 4}
        prompt = blueprint_prompt(slot)
        assert "다단계 추론" in prompt


class TestGroundedSourceLoading:
    """mock_async_router의 DB 그라운딩 소스 로딩 테스트."""

    @pytest.mark.asyncio
    async def test_grounded_source_prepends_header(self, monkeypatch) -> None:
        """DB 본문이 충분하면 과목 헤더 + 본문으로 source_text를 구성한다."""
        from app.modules.ExamForge_V1.app.routers import mock_async_router

        chapter_text = "## 1장 소유권\n" + ("소유권과 차용의 핵심 규칙을 설명한다. " * 10)

        async def fake_build(conn: object, course_id: str, topic: str | None) -> str:
            assert course_id == "course_1"
            return chapter_text

        class _FakeConn:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *args: object) -> None:
                return None

        import common.db as common_db

        monkeypatch.setattr(common_db, "get_connection", lambda: _FakeConn())
        monkeypatch.setattr(mock_async_router, "build_db_source_text", fake_build)

        req = mock_async_router.MockGenerateAsyncRequest(
            attempt_id="eat_1",
            course_id="course_1",
            subject="Rust",
            topic="소유권",
        )
        source, degraded = await mock_async_router._load_grounded_source_text(req)
        assert source.startswith("과목: Rust. 주제: 소유권.")
        assert "소유권과 차용의 핵심 규칙" in source
        # 충분한 본문 → grounding 정상(degraded 아님)
        assert degraded is False

    @pytest.mark.asyncio
    async def test_db_failure_falls_back_to_stub(self, monkeypatch) -> None:
        """DB 조회가 실패하면 기존 subject/topic 스텁으로 폴백한다."""
        from app.modules.ExamForge_V1.app.routers import mock_async_router

        def boom() -> object:
            raise RuntimeError("DB 미설정")

        import common.db as common_db

        monkeypatch.setattr(common_db, "get_connection", boom)

        req = mock_async_router.MockGenerateAsyncRequest(
            attempt_id="eat_2",
            course_id="course_x",
            subject="Rust",
            topic=None,
        )
        source, degraded = await mock_async_router._load_grounded_source_text(req)
        assert source.startswith("과목: Rust.")
        assert len(source) >= 100
        # DB 조회 실패 → 스텁 폴백 → grounding degraded
        assert degraded is True

    @pytest.mark.asyncio
    async def test_empty_db_content_falls_back_to_stub(self, monkeypatch) -> None:
        """DB 본문이 최소 길이 미만이면 스텁으로 폴백한다."""
        from app.modules.ExamForge_V1.app.routers import mock_async_router

        async def fake_build(conn: object, course_id: str, topic: str | None) -> str:
            return "짧은 본문"

        class _FakeConn:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *args: object) -> None:
                return None

        import common.db as common_db

        monkeypatch.setattr(common_db, "get_connection", lambda: _FakeConn())
        monkeypatch.setattr(mock_async_router, "build_db_source_text", fake_build)

        req = mock_async_router.MockGenerateAsyncRequest(
            attempt_id="eat_3",
            course_id="course_y",
            subject="자료구조",
            topic="해시 테이블",
        )
        source, degraded = await mock_async_router._load_grounded_source_text(req)
        assert "자료구조" in source
        assert len(source) >= 100
        # DB 본문 부족(hard-gate 미달) → 스텁 폴백 → grounding degraded
        assert degraded is True


class TestGateEdgeCases:
    """경계 입력(빈 stem·None options·영어 전용·코드블록 전용)에서 크래시 없이 합리적 판정."""

    def test_empty_stem_passes_relevance_gate(self) -> None:
        """빈 stem은 콘텐츠 토큰이 없어 구조 검증 영역으로 보고 통과한다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        assert check_question_relevance({"stem": "", "options": None}, vocab) == []

    def test_none_options_do_not_crash(self) -> None:
        """options=None 이어도 stem 토큰만으로 판정한다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        question = {"stem": "Rust의 소유권과 차용 규칙으로 옳은 것은?", "options": None}
        assert check_question_relevance(question, vocab) == []

    def test_english_only_stem_matches_english_vocab(self) -> None:
        """영어 전용 stem도 출처의 영어 어휘(ownership/borrowing)와 매칭된다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        question = {
            "stem": "Which statement about ownership and borrowing is correct?",
            "options": None,
        }
        assert check_question_relevance(question, vocab) == []

    def test_code_block_only_stem_uses_code_tokens(self) -> None:
        """stem이 코드블록뿐이어도 코드 토큰이 출처 코드와 겹치면 통과한다."""
        vocab = build_source_vocabulary(_RUST_SOURCE, _RUST_TOPICS)
        question = {
            "stem": "```rust\nfn main() { let s = String::from(\"hi\"); }\n```",
            "options": None,
        }
        assert check_question_relevance(question, vocab) == []

    def test_check_questions_relevance_empty_list(self) -> None:
        """빈 문항 목록은 빈 매핑을 돌려준다(크래시 금지)."""
        assert check_questions_relevance([], _RUST_SOURCE, _RUST_TOPICS) == {}

    def test_check_questions_relevance_none_source_and_topics(self) -> None:
        """source_text=None·topics=None 이어도 게이트 생략으로 조용히 통과한다."""
        questions = [{"stem": "아무 질문", "options": None}]
        assert check_questions_relevance(questions, None, None) == {}

    def test_difficulty_scorer_empty_stem(self) -> None:
        """빈 stem은 회상형 판정 없이 통과한다."""
        assert check_difficulty_manifestation({"difficulty": 5, "stem": ""}) == []

    def test_difficulty_scorer_non_numeric_difficulty(self) -> None:
        """difficulty가 숫자가 아니면 판정을 생략한다(크래시 금지)."""
        assert check_difficulty_manifestation({"difficulty": "어려움", "stem": "소유권이란 무엇인가?"}) == []
        assert check_difficulty_manifestation({"difficulty": None, "stem": "소유권이란 무엇인가?"}) == []

    def test_difficulty_scorer_english_only_definition_stem(self) -> None:
        """영어 전용 정의 회상 stem(난이도 4 이상)도 잡는다."""
        question = {"difficulty": 4, "stem": "What is the definition of ownership in Rust?"}
        assert check_difficulty_manifestation(question) != []

    def test_difficulty_scorer_code_block_stem_skipped(self) -> None:
        """stem이 코드블록 위주면 추적 문항으로 보고 회상형 판정을 건너뛴다."""
        question = {
            "difficulty": 4,
            "stem": "```rust\nfn main() {}\n``` 이 코드의 정의로 가장 적절한 것은?",
        }
        assert check_difficulty_manifestation(question) == []


class TestMetaFilterEdgeCases:
    """메타 문항 필터 경계 입력(빈 stem·영어 전용·코드블록)."""

    def test_empty_stem_not_meta(self) -> None:
        from app.modules.ExamForge_V1.quality.meta_question_filter import is_meta_question

        assert is_meta_question("") is False

    def test_english_only_meta_detected(self) -> None:
        from app.modules.ExamForge_V1.quality.meta_question_filter import is_meta_question

        assert is_meta_question("How many questions are in this exam paper?") is True

    def test_code_block_stem_not_meta(self) -> None:
        """'this test'류 코드 문항(단위 테스트 주제)은 메타로 오탐하지 않는다."""
        from app.modules.ExamForge_V1.quality.meta_question_filter import is_meta_question

        stem = "```python\ndef test_add():\n    assert add(1, 2) == 3\n``` 이 테스트가 검증하는 것은?"
        assert is_meta_question(stem) is False

    def test_filter_handles_missing_stem_key(self) -> None:
        """stem 키가 없는 초안도 크래시 없이 통과시킨다."""
        from app.modules.ExamForge_V1.quality.meta_question_filter import filter_meta_questions

        kept, removed = filter_meta_questions([{"options": []}])
        assert len(kept) == 1
        assert removed == []

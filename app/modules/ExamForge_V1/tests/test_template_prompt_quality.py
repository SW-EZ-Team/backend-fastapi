"""
템플릿 프롬프트 품질·신뢰도 단위테스트.

검증 범위:
1. 유형별 생성 프롬프트에 few-shot 예시·스키마·제약이 포함되는지 단언
2. 유형별 모범 codex 응답을 파싱해 유효 QuestionDraft / Question 생성 확인
3. 정답 형식 검증: 정답키/blank_answers/correct_ordering/matching_pairs 등

모델 실호출 없음 — 프롬프트 구성·파싱·검증 로직만 테스트.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ExamForge_V1.templates.registry import get_template
from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption, MatchingPair


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------

SAMPLE_CONTEXT = (
    "운영체제(OS)는 하드웨어 자원을 관리하고 사용자·응용프로그램에게 서비스를 제공하는 시스템 소프트웨어이다. "
    "스케줄링, 메모리 관리, 입출력 관리, 프로세스 관리를 담당한다. "
    "교착상태(DeadLock)는 두 개 이상의 프로세스가 서로 상대방의 자원을 기다리며 무한히 블로킹되는 상태이다. "
    "페이지 교체 알고리즘에는 FIFO, LRU, OPT 등이 있다."
)


# ---------------------------------------------------------------------------
# 1. OX형(true_false) — 프롬프트 품질
# ---------------------------------------------------------------------------

class TestTrueFalsePromptQuality:
    """OX형 프롬프트에 필수 요소가 포함되는지 검증한다."""

    def test_generation_prompt_contains_fewshot_example(self) -> None:
        """생성 프롬프트에 모범 예시(기억, 이해 bloom_level)가 포함된다."""
        tmpl = get_template("ko_true_false")
        prompt = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=3, context=SAMPLE_CONTEXT, count=4,
        )
        # few-shot 예시 존재 확인
        assert "모범 예시" in prompt
        assert "bloom_level" in prompt

    def test_generation_prompt_contains_schema_constraint(self) -> None:
        """생성 프롬프트에 JSON 스키마 형식 제약이 명시된다."""
        tmpl = get_template("ko_true_false")
        prompt = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=2, context=SAMPLE_CONTEXT, count=2,
        )
        # 출력 형식 명시 확인
        assert "[출력 형식" in prompt
        assert "bloom_level" in prompt

    def test_generation_prompt_diff3_contains_trap_guide(self) -> None:
        """난이도 3 이상이면 함정 문장 지시가 포함된다."""
        tmpl = get_template("ko_true_false")
        prompt_high = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=3, context=SAMPLE_CONTEXT, count=2,
        )
        prompt_low = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=1, context=SAMPLE_CONTEXT, count=2,
        )
        assert "함정 문장" in prompt_high
        assert "함정 문장" not in prompt_low

    def test_answer_prompt_forces_uppercase_ox(self) -> None:
        """정답 생성 프롬프트가 대문자 O 또는 X를 명시한다."""
        tmpl = get_template("ko_true_false")
        draft = QuestionDraft(
            draft_id="d_tf_01",
            template_id="ko_true_false",
            topic="운영체제",
            difficulty=2,
            stem="운영체제는 하드웨어 자원을 관리한다.",
        )
        prompt = tmpl.build_answer_prompt(draft, SAMPLE_CONTEXT)
        assert '대문자 "O"' in prompt or "대문자 O" in prompt
        assert '대문자 "X"' in prompt or "대문자 X" in prompt

    def test_parse_valid_generation_response(self) -> None:
        """유효한 codex 응답 샘플을 파싱해 QuestionDraft 목록을 반환한다."""
        tmpl = get_template("ko_true_false")
        sample_response = json.dumps([
            {
                "stem": "운영체제에서 교착상태는 두 프로세스가 서로의 자원을 기다릴 때 발생한다.",
                "topic": "운영체제",
                "difficulty": 2,
                "bloom_level": "기억",
            },
            {
                "stem": "LRU 페이지 교체 알고리즘은 가장 오래 사용되지 않은 페이지를 교체한다.",
                "topic": "운영체제",
                "difficulty": 3,
                "bloom_level": "이해",
            },
        ], ensure_ascii=False)
        drafts = tmpl.parse_generation_response(sample_response)
        assert len(drafts) == 2
        assert all(d.template_id == "ko_true_false" for d in drafts)
        assert all(d.stem for d in drafts)

    def test_validate_structure_normalizes_ox(self) -> None:
        """validate_structure가 'O'/'X' 외 변형('참', 'true')을 정규화한다."""
        tmpl = get_template("ko_true_false")
        q_true = Question(
            question_id="q_tf_t",
            draft_id="d_tf_t",
            template_id="ko_true_false",
            topic="운영체제",
            difficulty=2,
            bloom_level="기억",
            stem="교착상태는 두 프로세스가 서로 기다릴 때 발생한다.",
            correct_answer="참",
            explanation="교착상태 정의에 부합하는 진술이다.",
        )
        issues = tmpl.validate_structure(q_true)
        # '참' → 'O'로 정규화되어 이슈 없어야 함
        assert not any("O/X" in i for i in issues), issues
        assert q_true.correct_answer == "O"

    def test_validate_structure_rejects_invalid_answer(self) -> None:
        """'참거짓' 같은 완전 무효 정답은 검증 실패 이슈를 반환한다."""
        tmpl = get_template("ko_true_false")
        q_bad = Question(
            question_id="q_tf_bad",
            draft_id="d_tf_bad",
            template_id="ko_true_false",
            topic="운영체제",
            difficulty=2,
            bloom_level="기억",
            stem="교착상태 진술문.",
            correct_answer="모름",
            explanation="설명.",
        )
        issues = tmpl.validate_structure(q_bad)
        assert any("O/X" in i for i in issues)


# ---------------------------------------------------------------------------
# 2. 단답형(short_answer) — 프롬프트 품질
# ---------------------------------------------------------------------------

class TestShortAnswerPromptQuality:
    """단답형 프롬프트에 필수 요소가 포함되는지 검증한다."""

    def test_generation_prompt_contains_fewshot(self) -> None:
        """생성 프롬프트에 모범 예시가 포함된다."""
        tmpl = get_template("ko_short_answer")
        prompt = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=2, context=SAMPLE_CONTEXT, count=3,
        )
        assert "모범 예시" in prompt
        assert "교착상태" in prompt or "LRU" in prompt

    def test_generation_prompt_contains_uniqueness_constraint(self) -> None:
        """답이 유일해야 한다는 제약이 포함된다."""
        tmpl = get_template("ko_short_answer")
        prompt = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=3, context=SAMPLE_CONTEXT, count=2,
        )
        assert "유일" in prompt or "모호한 문제 금지" in prompt

    def test_answer_prompt_enforces_short_answer(self) -> None:
        """정답 생성 프롬프트가 5어절 이하 핵심어를 명시한다."""
        tmpl = get_template("ko_short_answer")
        draft = QuestionDraft(
            draft_id="d_sa_01",
            template_id="ko_short_answer",
            topic="운영체제",
            difficulty=2,
            stem="운영체제에서 교착상태의 영어 용어는?",
        )
        prompt = tmpl.build_answer_prompt(draft, SAMPLE_CONTEXT)
        assert "5어절" in prompt or "핵심어" in prompt

    def test_parse_valid_generation_response(self) -> None:
        """유효한 codex 응답 샘플을 파싱해 QuestionDraft를 반환한다."""
        tmpl = get_template("ko_short_answer")
        sample_response = json.dumps([
            {
                "stem": "운영체제에서 두 프로세스가 서로의 자원을 기다리며 무한 블로킹되는 상태를 무엇이라 하는가?",
                "topic": "운영체제",
                "difficulty": 2,
                "bloom_level": "기억",
            }
        ], ensure_ascii=False)
        drafts = tmpl.parse_generation_response(sample_response)
        assert len(drafts) == 1
        assert drafts[0].template_id == "ko_short_answer"
        assert "교착" in drafts[0].stem or "블로킹" in drafts[0].stem

    def test_validate_structure_rejects_long_answer(self) -> None:
        """5단어 초과 정답은 검증 실패 이슈를 반환한다."""
        tmpl = get_template("ko_short_answer")
        q = Question(
            question_id="q_sa_long",
            draft_id="d_sa_long",
            template_id="ko_short_answer",
            topic="운영체제",
            difficulty=2,
            bloom_level="기억",
            stem="교착상태란?",
            correct_answer="교착상태는 두 프로세스가 서로의 자원을 기다리는 상태입니다 정말",
            explanation="설명.",
        )
        issues = tmpl.validate_structure(q)
        assert any("5단어" in i or "너무 김" in i for i in issues)

    def test_validate_structure_passes_short_answer(self) -> None:
        """짧은 정답(3어절 이하)은 검증을 통과한다."""
        tmpl = get_template("ko_short_answer")
        q = Question(
            question_id="q_sa_ok",
            draft_id="d_sa_ok",
            template_id="ko_short_answer",
            topic="운영체제",
            difficulty=2,
            bloom_level="기억",
            stem="교착상태의 영어 용어는?",
            correct_answer="DeadLock",
            explanation="교착상태를 영어로 DeadLock이라 한다.",
        )
        issues = tmpl.validate_structure(q)
        assert issues == []


# ---------------------------------------------------------------------------
# 3. 빈칸채우기(fill_blank) — 프롬프트 품질 + 불일치 방지
# ---------------------------------------------------------------------------

class TestFillBlankPromptQuality:
    """빈칸채우기 프롬프트의 blank_positions 불일치 방지 지시를 검증한다."""

    def test_generation_prompt_contains_match_constraint(self) -> None:
        """blank_positions 수와 빈칸 수 일치 제약이 포함된다."""
        tmpl = get_template("ko_fill_blank")
        prompt = tmpl.build_generation_prompt(
            topic="운영체제", difficulty=2, context=SAMPLE_CONTEXT, count=2,
        )
        assert "blank_positions" in prompt
        assert "일치" in prompt

    def test_generation_prompt_contains_fewshot(self) -> None:
        """생성 프롬프트에 모범 예시가 포함된다."""
        tmpl = get_template("ko_fill_blank")
        prompt = tmpl.build_generation_prompt(
            topic="자료구조", difficulty=2, context=SAMPLE_CONTEXT, count=1,
        )
        assert "모범 예시" in prompt

    def test_answer_prompt_specifies_blank_count(self) -> None:
        """정답 생성 프롬프트가 blank_answers 배열 크기를 명시한다."""
        tmpl = get_template("ko_fill_blank")
        draft = QuestionDraft(
            draft_id="d_fb_01",
            template_id="ko_fill_blank",
            topic="운영체제",
            difficulty=2,
            stem="___은 LIFO 구조이며, ___은 FIFO 구조이다.",
            blank_positions=[0, 5],
        )
        prompt = tmpl.build_answer_prompt(draft, SAMPLE_CONTEXT)
        # blank_count=2가 프롬프트에 반영되었는지 확인
        assert "2" in prompt
        assert "blank_answers" in prompt

    def test_parse_valid_generation_response(self) -> None:
        """유효한 codex 응답 샘플을 파싱해 blank_positions가 설정된 QuestionDraft를 반환한다."""
        tmpl = get_template("ko_fill_blank")
        sample_response = json.dumps([
            {
                "stem": "___은 데이터를 LIFO 방식으로 관리하는 자료구조이다.",
                "topic": "자료구조",
                "difficulty": 2,
                "bloom_level": "기억",
                "blank_positions": [0],
            }
        ], ensure_ascii=False)
        drafts = tmpl.parse_generation_response(sample_response)
        assert len(drafts) == 1
        assert drafts[0].blank_positions == [0]
        assert "___" in drafts[0].stem

    def test_validate_structure_detects_blank_count_mismatch(self) -> None:
        """blank_answers 개수 != blank_positions 개수면 검증 실패한다."""
        tmpl = get_template("ko_fill_blank")
        q = Question(
            question_id="q_fb_mismatch",
            draft_id="d_fb_mismatch",
            template_id="ko_fill_blank",
            topic="자료구조",
            difficulty=2,
            bloom_level="기억",
            stem="___은 LIFO 구조이며, ___은 FIFO 구조이다.",
            blank_positions=[0, 5],
            blank_answers=["스택"],  # 2개 위치에 1개 답 — 불일치
            correct_answer="스택",
            explanation="설명.",
        )
        issues = tmpl.validate_structure(q)
        assert any("불일치" in i for i in issues)

    def test_validate_structure_passes_matching_blanks(self) -> None:
        """blank_answers 개수 == blank_positions 개수면 검증을 통과한다."""
        tmpl = get_template("ko_fill_blank")
        q = Question(
            question_id="q_fb_ok",
            draft_id="d_fb_ok",
            template_id="ko_fill_blank",
            topic="자료구조",
            difficulty=2,
            bloom_level="기억",
            stem="___은 LIFO 구조이며, ___은 FIFO 구조이다.",
            blank_positions=[0, 5],
            blank_answers=["스택", "큐"],
            correct_answer="스택, 큐",
            explanation="스택은 LIFO, 큐는 FIFO 자료구조이다.",
        )
        issues = tmpl.validate_structure(q)
        assert "불일치" not in " ".join(issues)


# ---------------------------------------------------------------------------
# 4. 순서배열(ordering) — 프롬프트 품질 + 항목 집합 불일치 방지
# ---------------------------------------------------------------------------

class TestOrderingPromptQuality:
    """순서배열 프롬프트의 ordering_items 일치 제약을 검증한다."""

    def test_generation_prompt_contains_fewshot_and_constraint(self) -> None:
        """생성 프롬프트에 모범 예시와 항목 집합 일치 제약이 포함된다."""
        tmpl = get_template("ko_ordering")
        prompt = tmpl.build_generation_prompt(
            topic="소프트웨어공학", difficulty=2, context=SAMPLE_CONTEXT, count=1,
        )
        assert "모범 예시" in prompt
        assert "ordering_items" in prompt

    def test_answer_prompt_specifies_item_count(self) -> None:
        """정답 생성 프롬프트가 correct_ordering 항목 수를 명시한다."""
        tmpl = get_template("ko_ordering")
        draft = QuestionDraft(
            draft_id="d_ord_01",
            template_id="ko_ordering",
            topic="소프트웨어공학",
            difficulty=2,
            stem="다음 SDLC 단계를 올바른 순서로 나열하시오.",
            ordering_items=["구현", "요구사항 분석", "테스트", "설계", "유지보수"],
        )
        prompt = tmpl.build_answer_prompt(draft, SAMPLE_CONTEXT)
        # 항목 수 5가 포함되는지 확인
        assert "5" in prompt
        assert "correct_ordering" in prompt

    def test_parse_valid_generation_response(self) -> None:
        """유효한 codex 응답 샘플을 파싱해 ordering_items가 설정된 QuestionDraft를 반환한다."""
        tmpl = get_template("ko_ordering")
        sample_response = json.dumps([
            {
                "stem": "다음 소프트웨어 개발 생명주기 단계를 올바른 순서로 나열하시오.",
                "topic": "소프트웨어공학",
                "difficulty": 2,
                "bloom_level": "이해",
                "ordering_items": ["구현", "요구사항 분석", "테스트", "설계"],
            }
        ], ensure_ascii=False)
        drafts = tmpl.parse_generation_response(sample_response)
        assert len(drafts) == 1
        assert len(drafts[0].ordering_items) == 4

    def test_validate_structure_detects_ordering_mismatch(self) -> None:
        """ordering_items와 correct_ordering 항목 집합이 다르면 검증 실패한다."""
        tmpl = get_template("ko_ordering")
        q = Question(
            question_id="q_ord_mismatch",
            draft_id="d_ord_mismatch",
            template_id="ko_ordering",
            topic="소프트웨어공학",
            difficulty=2,
            bloom_level="이해",
            stem="다음 단계를 순서대로 나열하시오.",
            ordering_items=["A", "B", "C", "D"],
            correct_ordering=["A", "B", "C", "E"],  # D → E로 항목 다름
            correct_answer="A -> B -> C -> E",
            explanation="순서 설명.",
        )
        issues = tmpl.validate_structure(q)
        assert any("불일치" in i for i in issues)

    def test_validate_structure_passes_correct_ordering(self) -> None:
        """ordering_items와 correct_ordering이 일치하면 검증을 통과한다."""
        tmpl = get_template("ko_ordering")
        items = ["구현", "요구사항 분석", "테스트", "설계"]
        q = Question(
            question_id="q_ord_ok",
            draft_id="d_ord_ok",
            template_id="ko_ordering",
            topic="소프트웨어공학",
            difficulty=2,
            bloom_level="이해",
            stem="다음 SDLC 단계를 순서대로 나열하시오.",
            ordering_items=items,
            correct_ordering=["요구사항 분석", "설계", "구현", "테스트"],
            correct_answer="요구사항 분석 -> 설계 -> 구현 -> 테스트",
            explanation="개발은 요구사항 분석 후 설계, 구현, 테스트 순으로 진행한다.",
        )
        issues = tmpl.validate_structure(q)
        assert issues == []


# ---------------------------------------------------------------------------
# 5. 연결형(matching) — 프롬프트 품질 + 쌍 수 제약 + correct_answer 형식
# ---------------------------------------------------------------------------

class TestMatchingPromptQuality:
    """연결형 프롬프트의 매칭 쌍 수 제약과 correct_answer 형식 명시를 검증한다."""

    def test_generation_prompt_contains_fewshot_and_min_pairs(self) -> None:
        """생성 프롬프트에 모범 예시와 최소 3쌍 이상 제약이 포함된다."""
        tmpl = get_template("ko_matching")
        prompt = tmpl.build_generation_prompt(
            topic="자료구조", difficulty=2, context=SAMPLE_CONTEXT, count=1,
        )
        assert "모범 예시" in prompt
        assert "matching_pairs" in prompt
        # 최소 쌍 수 제약 확인
        assert "3개 미만" in prompt or "최소" in prompt

    def test_answer_prompt_specifies_correct_answer_format(self) -> None:
        """정답 생성 프롬프트가 'A-N, B-N, ...' 형식을 명시한다."""
        tmpl = get_template("ko_matching")
        pairs = [
            MatchingPair(left="스택", right="LIFO"),
            MatchingPair(left="큐", right="FIFO"),
            MatchingPair(left="덱", right="양방향"),
        ]
        draft = QuestionDraft(
            draft_id="d_match_01",
            template_id="ko_matching",
            topic="자료구조",
            difficulty=2,
            stem="다음 자료구조와 특성을 연결하시오.",
            matching_pairs=pairs,
        )
        prompt = tmpl.build_answer_prompt(draft, SAMPLE_CONTEXT)
        assert "A-" in prompt or "A-1" in prompt
        assert "correct_answer" in prompt

    def test_parse_valid_generation_response(self) -> None:
        """유효한 codex 응답 샘플을 파싱해 matching_pairs가 설정된 QuestionDraft를 반환한다."""
        tmpl = get_template("ko_matching")
        sample_response = json.dumps([
            {
                "stem": "다음 자료구조와 그 특성을 올바르게 연결하시오.",
                "topic": "자료구조",
                "difficulty": 2,
                "bloom_level": "기억",
                "matching_pairs": [
                    {"left": "스택(Stack)", "right": "LIFO — 마지막 삽입이 가장 먼저 삭제"},
                    {"left": "큐(Queue)", "right": "FIFO — 먼저 삽입된 것이 먼저 삭제"},
                    {"left": "덱(Deque)", "right": "양방향 삽입·삭제 가능한 선형 구조"},
                ],
            }
        ], ensure_ascii=False)
        drafts = tmpl.parse_generation_response(sample_response)
        assert len(drafts) == 1
        assert len(drafts[0].matching_pairs) == 3
        assert drafts[0].matching_pairs[0].left == "스택(Stack)"

    def test_validate_structure_rejects_fewer_than_3_pairs(self) -> None:
        """매칭 쌍이 3개 미만이면 검증 실패한다."""
        tmpl = get_template("ko_matching")
        q = Question(
            question_id="q_match_few",
            draft_id="d_match_few",
            template_id="ko_matching",
            topic="자료구조",
            difficulty=2,
            bloom_level="기억",
            stem="다음을 연결하시오.",
            matching_pairs=[
                MatchingPair(left="스택", right="LIFO"),
                MatchingPair(left="큐", right="FIFO"),
            ],
            correct_answer="A-1, B-2",
            explanation="설명.",
        )
        issues = tmpl.validate_structure(q)
        assert any("3개 미만" in i for i in issues)

    def test_validate_structure_passes_3_or_more_pairs(self) -> None:
        """매칭 쌍이 3개 이상이면 검증을 통과한다."""
        tmpl = get_template("ko_matching")
        q = Question(
            question_id="q_match_ok",
            draft_id="d_match_ok",
            template_id="ko_matching",
            topic="자료구조",
            difficulty=2,
            bloom_level="기억",
            stem="다음을 연결하시오.",
            matching_pairs=[
                MatchingPair(left="스택", right="LIFO"),
                MatchingPair(left="큐", right="FIFO"),
                MatchingPair(left="덱", right="양방향"),
            ],
            correct_answer="A-1, B-2, C-3",
            explanation="스택은 LIFO, 큐는 FIFO, 덱은 양방향이다.",
        )
        issues = tmpl.validate_structure(q)
        assert issues == []


# ---------------------------------------------------------------------------
# 6. 서술형(descriptive) — 프롬프트 품질 + 채점기준 포함 보장
# ---------------------------------------------------------------------------

class TestDescriptivePromptQuality:
    """서술형 프롬프트의 채점기준 포함 지시와 검증 로직을 확인한다."""

    def test_generation_prompt_contains_fewshot_and_scoring_requirement(self) -> None:
        """생성 프롬프트에 모범 예시와 채점 요소 명시 지시가 포함된다."""
        tmpl = get_template("ko_descriptive")
        prompt = tmpl.build_generation_prompt(
            topic="데이터베이스", difficulty=4, context=SAMPLE_CONTEXT, count=1,
        )
        assert "모범 예시" in prompt
        assert "채점 요소" in prompt

    def test_answer_prompt_contains_scoring_criteria_requirement(self) -> None:
        """정답 생성 프롬프트가 채점기준/배점 포함을 강제한다."""
        tmpl = get_template("ko_descriptive")
        draft = QuestionDraft(
            draft_id="d_desc_01",
            template_id="ko_descriptive",
            topic="데이터베이스",
            difficulty=4,
            stem="관계형 데이터베이스의 정규화 목적과 1NF~3NF 조건을 각각 설명하시오.",
        )
        prompt = tmpl.build_answer_prompt(draft, SAMPLE_CONTEXT)
        assert "채점기준" in prompt or "배점" in prompt
        assert "correct_answer" in prompt

    def test_parse_valid_generation_response(self) -> None:
        """유효한 codex 응답을 파싱해 QuestionDraft를 반환한다."""
        tmpl = get_template("ko_descriptive")
        sample_response = json.dumps([
            {
                "stem": "운영체제의 교착상태(DeadLock) 발생 조건 4가지를 서술하시오.",
                "topic": "운영체제",
                "difficulty": 4,
                "bloom_level": "분석",
            }
        ], ensure_ascii=False)
        drafts = tmpl.parse_generation_response(sample_response)
        assert len(drafts) == 1
        assert drafts[0].template_id == "ko_descriptive"
        assert "교착상태" in drafts[0].stem

    def test_validate_structure_rejects_short_answer(self) -> None:
        """모범답안이 50자 미만이면 검증 실패한다."""
        tmpl = get_template("ko_descriptive")
        q = Question(
            question_id="q_desc_short",
            draft_id="d_desc_short",
            template_id="ko_descriptive",
            topic="운영체제",
            difficulty=4,
            bloom_level="분석",
            stem="교착상태 조건을 서술하시오.",
            correct_answer="교착상태 조건은 4가지이다.",  # 50자 미만
            explanation="채점기준: 1. 상호배제 (25%)",
        )
        issues = tmpl.validate_structure(q)
        assert any("50자" in i or "너무 짧" in i for i in issues)

    def test_validate_structure_rejects_missing_scoring_criteria(self) -> None:
        """해설에 채점기준 키워드가 없으면 검증 실패한다."""
        tmpl = get_template("ko_descriptive")
        long_answer = "교착상태는 상호배제, 점유와 대기, 비선점, 순환대기 4가지 조건이 모두 성립할 때 발생한다. "
        q = Question(
            question_id="q_desc_nocrit",
            draft_id="d_desc_nocrit",
            template_id="ko_descriptive",
            topic="운영체제",
            difficulty=4,
            bloom_level="분석",
            stem="교착상태 조건을 서술하시오.",
            correct_answer=long_answer * 2,
            explanation="교착상태는 자원 경쟁으로 발생한다.",  # 채점 키워드 없음
        )
        issues = tmpl.validate_structure(q)
        assert any("채점" in i or "기준" in i for i in issues)

    def test_validate_structure_passes_with_scoring_criteria(self) -> None:
        """해설에 채점기준과 충분한 모범답안이 있으면 검증을 통과한다."""
        tmpl = get_template("ko_descriptive")
        long_answer = (
            "교착상태는 두 개 이상의 프로세스가 서로의 자원을 기다리며 무한히 블로킹되는 상태이다. "
            "발생 조건은 상호배제, 점유와 대기, 비선점, 순환대기 네 가지이며 모두 성립해야 발생한다. "
            "예방 방법으로는 네 조건 중 하나를 원천 차단하는 방식이 있다."
        )
        q = Question(
            question_id="q_desc_ok",
            draft_id="d_desc_ok",
            template_id="ko_descriptive",
            topic="운영체제",
            difficulty=4,
            bloom_level="분석",
            stem="교착상태 발생 조건 4가지를 서술하시오.",
            correct_answer=long_answer,
            explanation="채점기준:\n1. 상호배제 (25%)\n2. 점유와 대기 (25%)\n3. 비선점 (25%)\n4. 순환대기 (25%)",
        )
        issues = tmpl.validate_structure(q)
        assert issues == []


# ---------------------------------------------------------------------------
# 7. 템플릿 레지스트리 — 7유형 모두 등록 확인
# ---------------------------------------------------------------------------

class TestTemplateRegistryAllTypes:
    """7유형 한국어 템플릿이 레지스트리에 모두 등록되어 있는지 확인한다."""

    _REQUIRED_IDS = [
        "ko_multiple_choice_4",
        "ko_multiple_choice_5",
        "ko_true_false",
        "ko_short_answer",
        "ko_fill_blank",
        "ko_ordering",
        "ko_matching",
        "ko_descriptive",
    ]

    @pytest.mark.parametrize("template_id", _REQUIRED_IDS)
    def test_template_is_registered(self, template_id: str) -> None:
        """각 유형 템플릿이 레지스트리에서 반환된다."""
        tmpl = get_template(template_id)
        assert tmpl.template_id == template_id
        assert tmpl.locale == "ko"

    @pytest.mark.parametrize("template_id", _REQUIRED_IDS)
    def test_template_has_generation_prompt_builder(self, template_id: str) -> None:
        """각 템플릿의 build_generation_prompt가 호출 가능하고 비어있지 않다."""
        tmpl = get_template(template_id)
        prompt = tmpl.build_generation_prompt(
            topic="테스트", difficulty=2, context="테스트 자료.", count=1,
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    @pytest.mark.parametrize("template_id", _REQUIRED_IDS)
    def test_template_has_answer_prompt_builder(self, template_id: str) -> None:
        """각 템플릿의 build_answer_prompt가 호출 가능하고 비어있지 않다."""
        tmpl = get_template(template_id)
        draft = QuestionDraft(
            draft_id="d_test",
            template_id=template_id,
            topic="테스트",
            difficulty=2,
            stem="테스트 문제 지문.",
        )
        prompt = tmpl.build_answer_prompt(draft, "테스트 자료.")
        assert isinstance(prompt, str)
        # OX/단답/서술 등 일부는 비어있지 않아야 함
        # (distractor_prompt만 빈 문자열 허용)
        assert len(prompt) > 0

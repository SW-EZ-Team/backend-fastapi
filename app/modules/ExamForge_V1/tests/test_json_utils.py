"""json_utils 헬퍼 함수 테스트."""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.common.json_utils import (
    extract_json,
    normalize_question_fields,
    parse_llm_json,
    unwrap_json_array,
)


class TestUnwrapJsonArray:
    """unwrap_json_array 래퍼 객체 언래핑 테스트."""

    def test_plain_list_passthrough(self) -> None:
        """일반 리스트는 그대로 반환한다."""
        data = [{"stem": "Q1"}, {"stem": "Q2"}]
        assert unwrap_json_array(data) == data

    def test_wrapped_in_questions_key(self) -> None:
        """{"questions": [...]} 래핑을 언래핑한다."""
        inner = [{"stem": "Q1"}, {"stem": "Q2"}]
        wrapped = {"questions": inner}
        assert unwrap_json_array(wrapped) == inner


class TestRobustJsonExtraction:
    """LLM 응답 JSON 추출 안정성 테스트."""

    def test_fenced_json_with_trailing_text_trimmed(self) -> None:
        """코드블록 안 후행 설명이 있어도 첫 JSON만 추출한다."""
        raw = '```json\n[{"stem": "Q"}]\n\n설명 텍스트\n```'
        assert extract_json(raw) == '[{"stem": "Q"}]'

    def test_parse_llm_json_ignores_trailing_payload(self) -> None:
        """JSON 뒤에 다른 JSON이 붙어도 첫 값만 파싱한다."""
        raw = '[{"stem": "Q1"}]\n[{"stem": "Q2"}]'
        parsed = parse_llm_json(raw)
        assert parsed == [{"stem": "Q1"}]

    def test_parse_llm_json_handles_prefixed_code_block(self) -> None:
        """코드블록 안 라벨/설명이 섞여도 JSON 객체를 찾는다."""
        raw = '```json\n결과:\n{"topics": [{"name": "Rust"}]}\n```'
        parsed = parse_llm_json(raw)
        assert parsed["topics"][0]["name"] == "Rust"

    def test_parse_llm_json_handles_inline_json_fence(self) -> None:
        """줄바꿈 없는 json 코드펜스에서도 객체를 추출한다."""
        parsed = parse_llm_json('```json{"passed": true, "issues": []}```')
        assert parsed == {"passed": True, "issues": []}

    def test_parse_llm_json_skips_markdown_bracket_before_object(self) -> None:
        """설명용 대괄호가 JSON 배열로 오인돼도 뒤쪽 객체를 다시 찾는다."""
        raw = '[검증 결과]\n정답은 맞습니다.\n{"passed": true, "issues": []}'
        parsed = parse_llm_json(raw)
        assert parsed["passed"] is True

    def test_parse_llm_json_uses_yaml_for_jsonish_output(self) -> None:
        """따옴표 없는 키를 섞은 JSON 유사 출력도 마지막 수단으로 파싱한다."""
        parsed = parse_llm_json('[{stem: Rust move, difficulty: 3}]')
        assert parsed[0]["stem"] == "Rust move"

    def test_wrapped_in_items_key(self) -> None:
        """{"items": [...]} 래핑을 언래핑한다."""
        inner = [{"stem": "Q1"}]
        wrapped = {"items": inner}
        assert unwrap_json_array(wrapped) == inner

    def test_dict_with_multiple_keys_wraps(self) -> None:
        """키가 2개 이상인 dict는 리스트로 감싼다."""
        data = {"stem": "Q1", "topic": "OS"}
        result = unwrap_json_array(data)
        assert result == [data]

    def test_single_dict_wraps(self) -> None:
        """단일 dict(키 1개이지만 값이 list 아님)는 리스트로 감싼다."""
        data = {"stem": "Q1"}
        result = unwrap_json_array(data)
        assert result == [data]

    def test_empty_list(self) -> None:
        """빈 리스트는 빈 리스트로 반환한다."""
        assert unwrap_json_array([]) == []

    def test_string_wraps(self) -> None:
        """문자열 같은 비-dict/비-list 값은 리스트로 감싼다."""
        assert unwrap_json_array("hello") == ["hello"]

    def test_nested_wrapper(self) -> None:
        """단일 키 dict에 중첩 리스트가 있으면 해당 리스트를 반환한다."""
        inner = [{"stem": "Q1"}, {"stem": "Q2"}, {"stem": "Q3"}]
        wrapped = {"data": inner}
        assert unwrap_json_array(wrapped) == inner


class TestThinkStripping:
    """모델 스왑(Qwen <think>) 대비 reasoning 제거 후 JSON 추출 테스트."""

    def test_extract_json_drops_closed_think_block(self) -> None:
        """닫힌 <think> 블록 뒤의 본문 JSON을 정확히 추출한다."""
        raw = (
            "<think>\n5지선다. is_correct는 정확히 1개만 True여야 함.\n</think>\n"
            '[{"stem":"OS 정의?","options":'
            '[{"label":"1","text":"A","is_correct":true}]}]'
        )
        parsed = parse_llm_json(raw)
        assert parsed[0]["options"][0]["is_correct"] is True

    def test_extract_json_truncated_think_does_not_break(self) -> None:
        """본문 JSON 뒤에 닫히지 않은 <think>가 잘려 붙어도 JSON만 살린다."""
        raw = '[{"stem":"본문"}]\n<think>스트림이 여기서 끊김... 정답 추론 중'
        parsed = parse_llm_json(raw)
        assert parsed == [{"stem": "본문"}]

    def test_extract_json_no_think_is_noop(self) -> None:
        """think가 없는 codex류 출력은 회귀 없이 그대로 파싱된다."""
        raw = '[{"stem":"평이","label":"1"}]'
        assert parse_llm_json(raw) == [{"stem": "평이", "label": "1"}]


class TestNormalizeQuestionFields:
    """normalize_question_fields 필드명 정규화 테스트."""

    def test_standard_fields_unchanged(self) -> None:
        """표준 필드명은 변경 없이 통과한다."""
        item = {"stem": "문제", "options": [], "correct_answer": "1"}
        result = normalize_question_fields(item)
        assert result == item

    def test_question_to_stem(self) -> None:
        """'question' 키를 'stem'으로 정규화한다."""
        item = {"question": "OS란?", "topic": "OS"}
        result = normalize_question_fields(item)
        assert result["stem"] == "OS란?"
        assert "question" not in result

    def test_problem_to_stem(self) -> None:
        """'problem' 키를 'stem'으로 정규화한다."""
        item = {"problem": "계산하시오", "topic": "수학"}
        result = normalize_question_fields(item)
        assert result["stem"] == "계산하시오"

    def test_korean_문제_to_stem(self) -> None:
        """한국어 '문제' 키를 'stem'으로 정규화한다."""
        item = {"문제": "설명하시오", "topic": "과학"}
        result = normalize_question_fields(item)
        assert result["stem"] == "설명하시오"

    def test_choices_to_options(self) -> None:
        """'choices' 키를 'options'으로 정규화한다."""
        choices = [{"label": "A", "text": "보기"}]
        item = {"stem": "Q", "choices": choices}
        result = normalize_question_fields(item)
        assert result["options"] == choices
        assert "choices" not in result

    def test_answer_to_correct_answer(self) -> None:
        """'answer' 키를 'correct_answer'로 정규화한다."""
        item = {"stem": "Q", "answer": "2"}
        result = normalize_question_fields(item)
        assert result["correct_answer"] == "2"
        assert "answer" not in result

    def test_korean_정답_to_correct_answer(self) -> None:
        """한국어 '정답' 키를 'correct_answer'로 정규화한다."""
        item = {"stem": "Q", "정답": "3"}
        result = normalize_question_fields(item)
        assert result["correct_answer"] == "3"

    def test_does_not_overwrite_existing_stem(self) -> None:
        """이미 'stem'이 있으면 'question' 키를 무시한다."""
        item = {"stem": "원본", "question": "대체X"}
        result = normalize_question_fields(item)
        assert result["stem"] == "원본"
        # question은 원본에 그대로 남아있음 (pop되지 않음)
        assert result["question"] == "대체X"

    def test_preserves_other_fields(self) -> None:
        """정규화 대상 아닌 필드는 그대로 유지된다."""
        item = {"question": "Q", "topic": "T", "difficulty": 3, "extra": "X"}
        result = normalize_question_fields(item)
        assert result["topic"] == "T"
        assert result["difficulty"] == 3
        assert result["extra"] == "X"

    def test_object_answer_fields_become_text(self) -> None:
        """객체형 정답/해설은 응답 스키마에 맞게 문자열화한다."""
        item = {
            "stem": "Q",
            "correct_answer": {"blank": "&mut data"},
            "explanation": {"reason": "가변 참조"},
        }
        result = normalize_question_fields(item)
        assert '"blank": "&mut data"' in result["correct_answer"]
        assert '"reason": "가변 참조"' in result["explanation"]


class TestCrossValidation:
    """correct_answer와 is_correct 교차 검증 테스트."""

    def test_consistent_passes(self) -> None:
        """일관된 데이터는 이슈 없이 통과한다."""
        from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
        questions = [{
            "question_id": "q1",
            "correct_answer": "2",
            "options": [
                {"label": "1", "text": "A", "is_correct": False},
                {"label": "2", "text": "B", "is_correct": True},
            ],
            "explanation": "정답은 2번이다.",
        }]
        issues = check_consistency(questions)
        assert issues == []

    def test_mismatch_detected(self) -> None:
        """correct_answer와 is_correct 불일치를 감지한다."""
        from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
        questions = [{
            "question_id": "q1",
            "correct_answer": "1",
            "options": [
                {"label": "1", "text": "A", "is_correct": False},
                {"label": "2", "text": "B", "is_correct": True},
            ],
            "explanation": "정답은 1번이다.",
        }]
        issues = check_consistency(questions)
        assert len(issues) == 1
        assert any("불일치" in i for i in issues[0]["issues"])

    def test_no_is_correct_flag_detected(self) -> None:
        """is_correct가 하나도 없는데 correct_answer만 있는 경우를 감지한다."""
        from app.modules.ExamForge_V1.quality.consistency_checker import check_consistency
        questions = [{
            "question_id": "q1",
            "correct_answer": "1",
            "options": [
                {"label": "1", "text": "A", "is_correct": False},
                {"label": "2", "text": "B", "is_correct": False},
            ],
            "explanation": "정답은 1번이다.",
        }]
        issues = check_consistency(questions)
        assert len(issues) >= 1

"""템플릿 검증 테스트."""
from __future__ import annotations

import pytest

from app.modules.ExamForge_V1.templates.registry import get_template, list_templates
from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft


class TestTemplateRegistry:
    """템플릿 레지스트리 기본 동작 검증."""

    def test_get_korean_mc5(self) -> None:
        """한국어 5지선다 템플릿을 가져올 수 있다."""
        tmpl = get_template("ko_multiple_choice_5")
        assert tmpl.template_id == "ko_multiple_choice_5"
        assert tmpl.locale == "ko"

    def test_get_us_mc4(self) -> None:
        """US 4지선다 템플릿을 가져올 수 있다."""
        tmpl = get_template("us_multiple_choice_4")
        assert tmpl.locale == "en"

    def test_get_engineer_written(self) -> None:
        """정보처리기사 필기 템플릿을 가져올 수 있다."""
        tmpl = get_template("engineer_written")
        assert tmpl.category == "professional"

    def test_list_korean_templates(self) -> None:
        """한국어 템플릿 목록을 필터링할 수 있다."""
        templates = list_templates(locale="ko")
        assert len(templates) >= 9

    def test_list_us_templates(self) -> None:
        """US 템플릿 목록을 필터링할 수 있다."""
        templates = list_templates(category="us")
        assert len(templates) >= 8

    def test_not_found_raises(self) -> None:
        """존재하지 않는 ID는 예외를 발생시킨다."""
        from app.modules.ExamForge_V1.common.errors import TemplateNotFoundError
        with pytest.raises(TemplateNotFoundError):
            get_template("nonexistent_template")


class TestKoreanMC5Validation:
    """한국어 5지선다 구조 검증."""

    def test_valid_question_passes(self, sample_question_dict: dict) -> None:
        """유효한 문제는 검증을 통과한다."""
        tmpl = get_template("ko_multiple_choice_5")
        q = Question(**sample_question_dict)
        issues = tmpl.validate_structure(q)
        assert issues == []

    def test_wrong_option_count_fails(self, sample_question_dict: dict) -> None:
        """보기 수가 틀리면 검증 실패한다."""
        tmpl = get_template("ko_multiple_choice_5")
        sample_question_dict["options"] = sample_question_dict["options"][:3]
        q = Question(**sample_question_dict)
        issues = tmpl.validate_structure(q)
        assert any("보기 수" in i for i in issues)


class TestPromptGeneration:
    """프롬프트 생성 검증."""

    def test_mc5_prompt_contains_topic(self) -> None:
        """생성 프롬프트에 주제가 포함된다."""
        tmpl = get_template("ko_multiple_choice_5")
        prompt = tmpl.build_generation_prompt(
            topic="운영체제",
            difficulty=3,
            context="운영체제는 컴퓨터 하드웨어를 관리하는 소프트웨어이다.",
            count=5,
        )
        assert "운영체제" in prompt
        assert "5" in prompt

    def test_answer_prompt_includes_source(self) -> None:
        """정답 프롬프트에 원문이 포함된다."""
        tmpl = get_template("ko_multiple_choice_5")
        draft = QuestionDraft(
            draft_id="test",
            template_id="ko_multiple_choice_5",
            topic="테스트",
            difficulty=3,
            stem="테스트 문제",
            options=[],
        )
        prompt = tmpl.build_answer_prompt(draft, "원본 학습 자료 텍스트")
        assert "원본 학습 자료" in prompt

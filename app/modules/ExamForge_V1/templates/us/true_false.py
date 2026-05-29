"""미국식 참/거짓 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


# LLM 정답 변형을 표준 형태로 정규화하는 매핑
_TF_NORMALIZE: dict[str, str] = {
    "True": "True", "true": "True", "TRUE": "True",
    "T": "True", "t": "True",
    "False": "False", "false": "False", "FALSE": "False",
    "F": "False", "f": "False",
}


class USTrueFalseTemplate:
    """참/거짓 문제 - 학문적 서술 스타일."""

    template_id: str = "us_true_false"
    locale: str = "en"
    category: str = "us"
    display_name: str = "True/False"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """참/거짓 문제 생성 프롬프트."""
        return f"""Generate {count} True/False questions based on this material.

[Material] {context}
[Requirements]
- Topic: {topic}, Difficulty: {difficulty}/5
- Clear, unambiguous statements
- ~50/50 True/False ratio
- Higher difficulty: partially true statements with subtle errors

[Output - JSON Array]
[{{"stem": "Statement", "topic": "{topic}", "difficulty": {difficulty}, "bloom_level": "Remember|Understand|Analyze"}}]"""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """참/거짓은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """참/거짓 판별 프롬프트."""
        return f"""Determine if this statement is True or False.
[Source] {source_text[:4000]}
[Statement] {question_draft.stem}
Output JSON: {{"correct_answer": "True or False", "explanation": "...", "source_reference": "..."}}"""

    def parse_generation_response(self, raw_text: str) -> list[QuestionDraft]:
        """생성 응답 파싱."""
        try:
            data = json.loads(extract_json(raw_text))
        except json.JSONDecodeError as e:
            raise ParseError(f"JSON 파싱 실패: {e}") from e
        data = unwrap_json_array(data)
        drafts: list[QuestionDraft] = []
        for item in data:
            item = normalize_question_fields(item)
            drafts.append(QuestionDraft(
                draft_id=f"draft_{uuid.uuid4().hex[:8]}",
                template_id=self.template_id,
                topic=item.get("topic", ""),
                difficulty=item.get("difficulty", 3),
                bloom_level=item.get("bloom_level", ""),
                stem=item["stem"],
            ))
        return drafts

    def parse_answer_response(self, raw_text: str, draft: QuestionDraft) -> Question:
        """답안 응답 파싱."""
        try:
            data = json.loads(extract_json(raw_text))
        except json.JSONDecodeError as e:
            raise ParseError(f"정답 파싱 실패: {e}") from e
        data = normalize_question_fields(data)
        return Question(
            question_id=f"q_{uuid.uuid4().hex[:8]}",
            draft_id=draft.draft_id,
            template_id=self.template_id,
            topic=draft.topic,
            difficulty=draft.difficulty,
            bloom_level=draft.bloom_level,
            stem=draft.stem,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증 — LLM 변형 정답을 정규화 후 판정한다."""
        issues: list[str] = []
        # 정답 정규화: "true", "T", "FALSE" 등을 표준 True/False로 변환
        raw = question.correct_answer.strip()
        normalized = _TF_NORMALIZE.get(raw)
        if normalized:
            question.correct_answer = normalized
        else:
            issues.append(f"정답은 True 또는 False여야 함, 현재: {question.correct_answer}")
        return issues

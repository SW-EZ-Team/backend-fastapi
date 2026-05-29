"""미국식 순서 배열 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class USOrderingTemplate:
    """순서 배열 - 항목을 올바른 순서로 정렬."""

    template_id: str = "us_ordering"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Ordering"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """순서 배열 문제 생성 프롬프트."""
        return f"""Generate {count} ordering/sequencing questions.
[Material] {context}
[Requirements] Topic: {topic}, Difficulty: {difficulty}/5
- 4-8 items to arrange in correct order
- Items presented in shuffled order
- Process steps, chronological events, or logical sequences

[Output - JSON Array]
[{{"stem": "Arrange the following in correct order.", "topic": "{topic}", "difficulty": {difficulty}, "bloom_level": "Understand|Apply|Analyze", "ordering_items": ["Step C", "Step A", "Step D", "Step B"]}}]"""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """순서 배열은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """올바른 순서 판별 프롬프트."""
        items = json.dumps(question_draft.ordering_items, ensure_ascii=False)
        return f"""Determine the correct order.
[Source] {source_text[:4000]}
[Question] {question_draft.stem}
[Items to order] {items}
Output JSON: {{"correct_answer": "A -> B -> C -> D", "correct_ordering": ["Step A", "Step B", "Step C", "Step D"], "explanation": "...", "source_reference": "..."}}"""

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
                ordering_items=item.get("ordering_items", []),
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
            ordering_items=draft.ordering_items,
            correct_ordering=data.get("correct_ordering", []),
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증."""
        issues: list[str] = []
        if not question.ordering_items:
            issues.append("배열할 항목이 없음")
        if not question.correct_ordering:
            issues.append("정답 순서가 없음")
        elif question.ordering_items:
            if set(question.ordering_items) != set(question.correct_ordering):
                issues.append("문제 항목과 정답 항목이 불일치")
        return issues

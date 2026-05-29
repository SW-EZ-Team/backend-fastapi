"""미국식 5지선다 객관식 템플릿 (AP 스타일)."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.common.errors import ParseError


class USMC5Template:
    """5지선다 객관식 - AP 시험 스타일."""

    template_id: str = "us_multiple_choice_5"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Multiple Choice (5 options)"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """AP 스타일 5지선다 생성 프롬프트."""
        return f"""Generate {count} AP-style multiple-choice questions with 5 options.

[Study Material]
{context}

[Requirements]
- Topic: {topic}, Difficulty: {difficulty}/5, Count: {count}
- 5 options (A-E), exactly 1 correct
- AP exam conventions, formal academic language
- Bloom's taxonomy level required

[Output - JSON Array]
[
  {{
    "stem": "Question",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "Remember|Understand|Apply|Analyze|Evaluate|Create",
    "options": [
      {{"label": "A", "text": "...", "is_correct": false}},
      {{"label": "B", "text": "...", "is_correct": true}},
      {{"label": "C", "text": "...", "is_correct": false}},
      {{"label": "D", "text": "...", "is_correct": false}},
      {{"label": "E", "text": "...", "is_correct": false}}
    ]
  }}
]"""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """5지선다 오답 선택지 개선 프롬프트."""
        return f"""Improve distractors for this 5-option question.
[Question] {question_draft.stem}
[Options] {json.dumps([o.model_dump() for o in (question_draft.options or [])], ensure_ascii=False)}
Output JSON:
{{
  "options": [
    {{"label": "A", "text": "Option A", "is_correct": false}},
    {{"label": "B", "text": "Option B", "is_correct": true}},
    {{"label": "C", "text": "Option C", "is_correct": false}},
    {{"label": "D", "text": "Option D", "is_correct": false}},
    {{"label": "E", "text": "Option E", "is_correct": false}}
  ],
  "distractor_rationale": "Explanation"
}}"""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """연쇄 추론 방식으로 정답 생성."""
        opts = "\n".join(
            f"  {o.label}. {o.text}" for o in (question_draft.options or [])
        )
        return f"""Answer this question with reasoning.
[Source] {source_text[:4000]}
[Question] {question_draft.stem}
[Options]\n{opts}
Output JSON: {{"correct_answer": "letter", "explanation": "...", "source_reference": "..."}}"""

    def parse_generation_response(self, raw_text: str) -> list[QuestionDraft]:
        """AI 응답 파싱."""
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
                options=[QuestionOption(**o) for o in item.get("options", [])],
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
            options=draft.options,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """5지선다 구조 검증."""
        issues: list[str] = []
        if not question.options:
            issues.append("선택지가 없음")
            return issues
        if len(question.options) != 5:
            issues.append(f"선택지 5개 필요, 현재 {len(question.options)}개")
        correct = sum(1 for o in question.options if o.is_correct)
        if correct != 1:
            issues.append(f"정답 1개 필요, 현재 {correct}개")
        return issues

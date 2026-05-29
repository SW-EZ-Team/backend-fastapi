"""미국식 4지선다 객관식 템플릿 (AP/SAT 스타일)."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.common.errors import ParseError


class USMC4Template:
    """4지선다 객관식 - AP/SAT/GRE 시험 스타일."""

    template_id: str = "us_multiple_choice_4"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Multiple Choice (4 options)"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """AP/SAT 스타일 객관식 생성 프롬프트 구성."""
        return f"""Based on the following study material, generate {count} multiple-choice questions.

[Study Material]
{context}

[Requirements]
- Topic: {topic}
- Difficulty: {difficulty}/5
- Exactly 4 options per question (A, B, C, D)
- One correct answer per question
- Follow AP/SAT exam conventions
- Distractors should reflect common misconceptions
- Include Bloom's taxonomy level

[Output Format - JSON Array]
[
  {{
    "stem": "Question text",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "Remember|Understand|Apply|Analyze|Evaluate|Create",
    "options": [
      {{"label": "A", "text": "Option A", "is_correct": false}},
      {{"label": "B", "text": "Option B", "is_correct": true}},
      {{"label": "C", "text": "Option C", "is_correct": false}},
      {{"label": "D", "text": "Option D", "is_correct": false}}
    ]
  }}
]

Output exactly {count} questions as a JSON array."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """오답 선택지 개선 프롬프트."""
        return f"""Improve the distractors for this multiple-choice question.

[Question]
{question_draft.stem}

[Current Options]
{json.dumps([o.model_dump() for o in (question_draft.options or [])], ensure_ascii=False)}

[Requirements]
- Total options: {num_options}
- Distractors must target common student misconceptions
- All options should be similar in length and grammatical structure
- Provide rationale for each distractor

[Output Format - JSON]
{{
  "options": [
    {{"label": "A", "text": "Option A", "is_correct": false}},
    {{"label": "B", "text": "Option B", "is_correct": true}},
    {{"label": "C", "text": "Option C", "is_correct": false}},
    {{"label": "D", "text": "Option D", "is_correct": false}}
  ],
  "distractor_rationale": "Explanation of distractor design"
}}"""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 생성 프롬프트."""
        options_str = ""
        if question_draft.options:
            for opt in question_draft.options:
                options_str += f"  {opt.label}. {opt.text}\n"
        return f"""Determine the correct answer and provide explanation.

[Source Material]
{source_text[:4000]}

[Question]
{question_draft.stem}

[Options]
{options_str}

[Instructions]
1. Use chain-of-thought reasoning to identify the answer
2. Explain why the correct answer is right
3. Briefly explain why each distractor is wrong

[Output Format - JSON]
{{
  "correct_answer": "Letter of correct option",
  "explanation": "Full explanation",
  "source_reference": "Relevant quote from source"
}}"""

    def parse_generation_response(
        self, raw_text: str,
    ) -> list[QuestionDraft]:
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
                options=[QuestionOption(**o) for o in item.get("options", [])],
            ))
        return drafts

    def parse_answer_response(
        self, raw_text: str, draft: QuestionDraft,
    ) -> Question:
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
        """4지선다 구조 검증."""
        issues: list[str] = []
        if not question.options:
            issues.append("선택지가 없음")
            return issues
        if len(question.options) != 4:
            issues.append(f"선택지 4개 필요, 현재 {len(question.options)}개")
        correct = sum(1 for o in question.options if o.is_correct)
        if correct != 1:
            issues.append(f"정답 1개 필요, 현재 {correct}개")
        return issues

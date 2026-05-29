"""미국식 서술형 에세이 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class USEssayTemplate:
    """서술형 에세이 - 루브릭 포함 장문 답변."""

    template_id: str = "us_essay"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Essay"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """서술형 에세이 생성 프롬프트."""
        return f"""Generate {count} essay questions requiring extended responses.
[Material] {context}
[Requirements] Topic: {topic}, Difficulty: {difficulty}/5
- Questions should require analysis, synthesis, or evaluation
- Include clear parameters (word count, aspects to address)
- Suitable for timed exam conditions

[Output - JSON Array]
[{{"stem": "Essay prompt with instructions", "topic": "{topic}", "difficulty": {difficulty}, "bloom_level": "Analyze|Evaluate|Create"}}]"""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """에세이는 오답 선택지 없음."""
        return ""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """모범 답안 및 채점 루브릭 생성 프롬프트."""
        return f"""Provide a model answer and scoring rubric.
[Source] {source_text[:3000]}
[Question] {question_draft.stem}
Output JSON: {{
  "correct_answer": "Model answer (500+ words)",
  "explanation": "Rubric: Content (40%), Analysis (30%), Organization (20%), Language (10%)",
  "source_reference": "Key source passages"
}}"""

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
                difficulty=item.get("difficulty", 4),
                bloom_level=item.get("bloom_level", "Analyze"),
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
        """구조 검증."""
        issues: list[str] = []
        if len(question.correct_answer) < 200:
            issues.append("모범 답안이 너무 짧음 (200자 미만)")
        if not question.explanation:
            issues.append("루브릭이 없음")
        return issues

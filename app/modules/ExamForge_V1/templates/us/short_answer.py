"""미국식 단답형 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class USShortAnswerTemplate:
    """단답형 - 1~3단어 이내 짧은 답변."""

    template_id: str = "us_short_answer"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Short Answer"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """단답형 문제 생성 프롬프트."""
        return f"""Generate {count} short-answer questions (1-3 word answers).
[Material] {context}
[Requirements] Topic: {topic}, Difficulty: {difficulty}/5
- Answers must be specific terms, names, numbers, or concepts
- Avoid ambiguous questions with multiple valid answers

[Output - JSON Array]
[{{"stem": "Question?", "topic": "{topic}", "difficulty": {difficulty}, "bloom_level": "Remember|Understand|Apply"}}]"""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """단답형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """단답형 정답 생성 프롬프트."""
        return f"""Answer this short-answer question.
[Source] {source_text[:4000]}
[Question] {question_draft.stem}
Output JSON: {{"correct_answer": "1-3 words", "explanation": "...", "source_reference": "..."}}"""

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
        """구조 검증."""
        issues: list[str] = []
        if not question.correct_answer:
            issues.append("정답이 비어있음")
        if len(question.correct_answer.split()) > 5:
            issues.append("정답이 너무 김 (5단어 초과)")
        return issues

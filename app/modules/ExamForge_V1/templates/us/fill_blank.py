"""미국식 빈칸 채우기 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import re
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


# 빈칸 마커 패턴: 언더스코어 2개 이상, 괄호/대괄호 안 공백 등
_BLANK_PATTERN = re.compile(r'_{2,}|\(\s+\)|\[\s+\]')


class USFillBlankTemplate:
    """빈칸 채우기 - 용어·수식·코드 중심."""

    template_id: str = "us_fill_blank"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Fill in the Blank"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """빈칸 채우기 문제 생성 프롬프트."""
        return f"""Generate {count} fill-in-the-blank questions.
[Material] {context}
[Requirements] Topic: {topic}, Difficulty: {difficulty}/5
- Use ___ for blanks, 1-3 blanks per question
- Answers: key terms, code fragments, or formulas
- Include blank_positions (0-indexed word positions)

[Output - JSON Array]
[{{"stem": "The ___ pattern separates ___.", "topic": "{topic}", "difficulty": {difficulty}, "bloom_level": "Remember|Understand|Apply", "blank_positions": [1, 4]}}]"""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """빈칸 채우기는 오답 선택지 없음."""
        return ""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """빈칸 정답 생성 프롬프트."""
        code = f"\n[Code]\n{question_draft.code_snippet}" if question_draft.code_snippet else ""
        return f"""Fill in the blanks.
[Source] {source_text[:4000]}
[Question] {question_draft.stem}{code}
[Blank positions] {question_draft.blank_positions}
Output JSON: {{"correct_answer": "ans1, ans2", "blank_answers": ["ans1", "ans2"], "explanation": "...", "source_reference": "..."}}"""

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
                blank_positions=item.get("blank_positions", [0]),
                code_snippet=item.get("code_snippet"),
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
            blank_positions=draft.blank_positions,
            blank_answers=data.get("blank_answers", []),
            code_snippet=draft.code_snippet,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증."""
        issues: list[str] = []
        if not question.blank_positions:
            issues.append("빈칸 위치가 지정되지 않음")
        if not question.blank_answers:
            issues.append("빈칸 정답이 없음")
        if not _BLANK_PATTERN.search(question.stem):
            issues.append("문제 지문에 빈칸 마커(___)가 없음")
        return issues

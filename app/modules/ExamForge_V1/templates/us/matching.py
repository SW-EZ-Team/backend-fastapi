"""미국식 연결하기 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, MatchingPair
from app.modules.ExamForge_V1.common.errors import ParseError


class USMatchingTemplate:
    """연결하기 - 좌우 항목 매칭."""

    template_id: str = "us_matching"
    locale: str = "en"
    category: str = "us"
    display_name: str = "Matching"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """연결하기 문제 생성 프롬프트."""
        return f"""Generate {count} matching questions.
[Material] {context}
[Requirements] Topic: {topic}, Difficulty: {difficulty}/5
- 4-7 pairs per question, 1:1 mapping only
- Left: terms/concepts, Right: definitions/descriptions

[Output - JSON Array]
[{{"stem": "Match each item on the left with its correct pair on the right.", "topic": "{topic}", "difficulty": {difficulty}, "bloom_level": "Remember|Understand|Analyze", "matching_pairs": [{{"left": "Term", "right": "Definition"}}]}}]"""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """연결하기는 오답 선택지 없음."""
        return ""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """정답 매칭 검증 프롬프트."""
        pairs = json.dumps(
            [p.model_dump() for p in (question_draft.matching_pairs or [])],
            ensure_ascii=False,
        )
        return f"""Verify the correct matching.
[Source] {source_text[:4000]}
[Question] {question_draft.stem}
[Pairs] {pairs}
Output JSON: {{"correct_answer": "A-1, B-2, ...", "explanation": "...", "source_reference": "..."}}"""

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
                matching_pairs=[MatchingPair(**p) for p in item.get("matching_pairs", [])],
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
            matching_pairs=draft.matching_pairs,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증."""
        issues: list[str] = []
        if not question.matching_pairs:
            issues.append("매칭 쌍이 없음")
        elif len(question.matching_pairs) < 3:
            issues.append("매칭 쌍이 너무 적음 (3개 미만)")
        return issues

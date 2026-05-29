"""한국어 순서배열 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanOrderingTemplate:
    """순서배열 - 프로세스/알고리즘 단계."""

    template_id: str = "ko_ordering"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "순서배열"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """순서배열 문제 생성 프롬프트."""
        items_range = {1: "3~4", 2: "4~5", 3: "5~6", 4: "6~7", 5: "7~8"}
        return f"""다음 학습 자료를 기반으로 순서배열 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 배열 항목 수: {items_range.get(difficulty, "5~6")}개
- 프로세스 단계, 알고리즘 순서, 역사적 순서 등
- 항목은 무작위로 섞어서 제시
- 정답 순서가 명확히 하나만 존재해야 함

[출력 형식 - JSON 배열]
[
  {{
    "stem": "다음 항목을 올바른 순서로 배열하시오.",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "이해|적용|분석",
    "ordering_items": ["항목C", "항목A", "항목D", "항목B"]
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """순서배열은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 순서 생성."""
        items_str = json.dumps(
            question_draft.ordering_items, ensure_ascii=False
        )
        return f"""다음 순서배열 문제의 정답을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[배열할 항목]
{items_str}

[지시사항]
1. 올바른 순서대로 항목을 재배열
2. 각 단계가 왜 그 순서인지 설명
3. 순서가 바뀌면 안 되는 이유 언급

[출력 형식 - JSON]
{{
  "correct_answer": "A -> B -> C -> D",
  "correct_ordering": ["항목A", "항목B", "항목C", "항목D"],
  "explanation": "순서 근거 해설",
  "source_reference": "관련 원문 인용"
}}"""

    def parse_generation_response(
        self, raw_text: str,
    ) -> list[QuestionDraft]:
        """AI 응답 파싱."""
        try:
            data = parse_llm_json(raw_text)
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

    def parse_answer_response(
        self, raw_text: str, draft: QuestionDraft,
    ) -> Question:
        """정답 파싱."""
        try:
            data = parse_llm_json(raw_text)
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
            issues.append("배열 항목이 비어있음")
        if not question.correct_ordering:
            issues.append("정답 순서가 비어있음")
        elif question.ordering_items:
            if set(question.ordering_items) != set(question.correct_ordering):
                issues.append("배열 항목과 정답 순서의 항목이 불일치")
        return issues

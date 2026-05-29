"""자격시험 공통 베이스 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.common.errors import ParseError


class CertificationBaseTemplate:
    """자격시험 공통 - 5지선다 기본형."""

    template_id: str = "cert_base"
    locale: str = "ko"
    category: str = "professional"
    display_name: str = "자격시험 기본형"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """자격시험 기본 문제 생성."""
        return f"""다음 자료를 기반으로 자격시험 형식의 5지선다 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 5지선다, 정답 1개
- 자격시험 출제 스타일 (간결하고 정확한 표현)
- 실무 적용 능력을 평가하는 문제 위주

[출력 형식 - JSON 배열]
[
  {{
    "stem": "문제 지문",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석",
    "options": [
      {{"label": "1", "text": "정답 보기", "is_correct": true}},
      {{"label": "2", "text": "오답 보기", "is_correct": false}},
      ...
    ]
  }}
]"""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        return f"""자격시험 문제의 오답을 개선하시오.
[문제] {question_draft.stem}
[보기] {json.dumps([o.model_dump() for o in (question_draft.options or [])], ensure_ascii=False)}
출력 JSON:
{{
  "options": [
    {{"label": "1", "text": "보기1", "is_correct": false}},
    {{"label": "2", "text": "보기2", "is_correct": true}},
    {{"label": "3", "text": "보기3", "is_correct": false}},
    {{"label": "4", "text": "보기4", "is_correct": false}}
  ],
  "distractor_rationale": "오답 설계 근거"
}}"""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        opts = "\n".join(
            f"  {o.label}. {o.text}" for o in (question_draft.options or [])
        )
        return f"""자격시험 문제의 정답과 해설을 생성하시오.
[자료] {source_text[:4000]}
[문제] {question_draft.stem}
[보기]\n{opts}
출력 JSON: {{"correct_answer": "번호", "explanation": "해설", "source_reference": "출처"}}"""

    def parse_generation_response(self, raw_text: str) -> list[QuestionDraft]:
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
        issues: list[str] = []
        if not question.options:
            issues.append("보기가 없음")
            return issues
        if len(question.options) != 5:
            issues.append(f"보기 수: {len(question.options)} (5개 필요)")
        correct = sum(1 for o in question.options if o.is_correct)
        if correct != 1:
            issues.append(f"정답 수: {correct} (1개 필요)")
        return issues

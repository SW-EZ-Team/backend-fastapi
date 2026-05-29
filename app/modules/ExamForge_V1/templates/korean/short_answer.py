"""한국어 단답형 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanShortAnswerTemplate:
    """단답형 - 1~3단어 정답."""

    template_id: str = "ko_short_answer"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "단답형"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """단답형 문제 생성 프롬프트."""
        return f"""다음 학습 자료를 기반으로 단답형 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 정답은 1~3단어로 명확하게 답할 수 있는 문제
- 용어, 개념명, 숫자, 약어 등을 물어보는 형태
- 답이 여러 개 가능한 모호한 문제 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "문제 지문 (___에 들어갈 용어는?)",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석|평가|창조"
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """단답형은 오답 선택지가 없으므로 빈 프롬프트."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 및 해설 생성 프롬프트."""
        return f"""다음 단답형 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[지시사항]
1. 정답은 1~3단어로 작성
2. 유사 정답(동의어, 약어 등)도 함께 제시
3. 해설은 왜 그 답이 정확한지 근거 제시

[출력 형식 - JSON]
{{
  "correct_answer": "정답 (1~3단어)",
  "explanation": "해설",
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
        if not question.explanation:
            issues.append("해설이 비어있음")
        return issues

"""한국어 서술형 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanDescriptiveTemplate:
    """서술형 - 3~10문장 답변, 채점 기준 포함."""

    template_id: str = "ko_descriptive"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "서술형"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """서술형 문제 생성 프롬프트."""
        return f"""다음 학습 자료를 기반으로 서술형 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 답변 분량: 3~10문장
- "설명하시오", "비교하시오", "서술하시오" 형태의 문제
- 채점 요소가 명확히 구분되는 문제여야 함

[출력 형식 - JSON 배열]
[
  {{
    "stem": "서술형 문제 지문",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "이해|적용|분석|평가|창조"
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """서술형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """모범답안 및 채점기준 생성 프롬프트."""
        return f"""다음 서술형 문제의 모범답안과 채점기준을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[지시사항]
1. 3~10문장의 모범답안 작성
2. 채점 요소를 3~5개로 구분
3. 각 채점 요소별 배점 비율 제시
4. 부분점수 기준도 포함

[출력 형식 - JSON]
{{
  "correct_answer": "모범답안 전문",
  "explanation": "채점기준:\\n1. 요소1 (30%)\\n2. 요소2 (30%)\\n...",
  "source_reference": "관련 원문 인용"
}}"""

    def parse_generation_response(
        self, raw_text: str,
    ) -> list[QuestionDraft]:
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
            ))
        return drafts

    def parse_answer_response(
        self, raw_text: str, draft: QuestionDraft,
    ) -> Question:
        """정답 파싱."""
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
            issues.append("모범답안이 비어있음")
        if len(question.correct_answer) < 50:
            issues.append("모범답안이 너무 짧음 (50자 미만)")
        if not any(kw in question.explanation for kw in ("채점", "배점", "평가 기준", "점수", "기준")):
            issues.append("채점기준이 해설에 포함되지 않음")
        return issues

"""한국어 논술형 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanEssayTemplate:
    """논술형 - 논리 구조 + 근거 + 결론, 800자 이상."""

    template_id: str = "ko_essay"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "논술형"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """논술형 문제 생성 프롬프트."""
        return f"""다음 학습 자료를 기반으로 논술형 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 답변은 800자 이상의 논술 형태
- "~에 대해 논하시오", "~의 장단점을 분석하고 본인의 견해를 제시하시오"
- 서론-본론-결론 구조가 필요한 문제
- 복합적 사고력을 요구하는 문제

[출력 형식 - JSON 배열]
[
  {{
    "stem": "논술형 문제 지문 (조건/제약 포함)",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "분석|평가|창조"
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """논술형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """모범답안 및 채점기준 생성."""
        return f"""다음 논술형 문제의 모범답안과 채점기준을 생성하시오.

[원본 자료]
{source_text[:3000]}

[문제]
{question_draft.stem}

[지시사항]
1. 800자 이상의 모범답안 작성 (서론-본론-결론 구조)
2. 채점 영역: 논리성(30%), 근거 타당성(30%), 창의성(20%), 표현력(20%)
3. 각 영역별 세부 채점 기준 제시

[출력 형식 - JSON]
{{
  "correct_answer": "모범답안 전문 (800자 이상)",
  "explanation": "채점기준 상세",
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
                difficulty=item.get("difficulty", 4),
                bloom_level=item.get("bloom_level", "분석"),
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
        if len(question.correct_answer) < 400:
            issues.append("모범답안이 너무 짧음 (800자 미만 추정)")
        if not question.explanation:
            issues.append("채점기준이 비어있음")
        return issues

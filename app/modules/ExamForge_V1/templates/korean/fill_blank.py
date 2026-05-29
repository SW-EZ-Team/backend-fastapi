"""한국어 빈칸채우기 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, unwrap_json_array, normalize_question_fields

import json
import re
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


# 빈칸 마커 패턴: 언더스코어 2개 이상, 괄호/대괄호 안 공백 등
_BLANK_PATTERN = re.compile(r'_{2,}|\(\s+\)|\[\s+\]')


class KoreanFillBlankTemplate:
    """빈칸채우기 - 코드/수식/용어."""

    template_id: str = "ko_fill_blank"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "빈칸채우기"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """빈칸채우기 문제 생성 프롬프트."""
        return f"""다음 학습 자료를 기반으로 빈칸채우기 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 빈칸은 (   ) 또는 ___로 표시
- 빈칸에 들어갈 답은 핵심 용어, 코드 조각, 수식 중 하나
- 빈칸 위치는 blank_positions 배열로 0-indexed 단어 위치 표기
- 빈칸이 1~3개인 문제

[출력 형식 - JSON 배열]
[
  {{
    "stem": "___은/는 객체지향 프로그래밍에서 ___을/를 구현하는 기법이다.",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용",
    "blank_positions": [0, 5]
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """빈칸채우기는 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 생성 프롬프트."""
        code_section = ""
        if question_draft.code_snippet:
            code_section = f"\n[코드]\n{question_draft.code_snippet}\n"
        return f"""다음 빈칸채우기 문제의 정답을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}
{code_section}
[빈칸 위치 (0-indexed)]
{question_draft.blank_positions}

[지시사항]
1. 각 빈칸에 들어갈 정확한 답을 순서대로 제시
2. 동의어/약어가 있으면 함께 언급
3. 왜 그 답이 맞는지 해설

[출력 형식 - JSON]
{{
  "correct_answer": "답1, 답2",
  "blank_answers": ["답1", "답2"],
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
                blank_positions=item.get("blank_positions", [0]),
                code_snippet=item.get("code_snippet"),
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
            issues.append("빈칸 답이 비어있음")
        elif question.blank_positions:
            if len(question.blank_answers) != len(question.blank_positions):
                issues.append("빈칸 수와 답 수 불일치")
        if not _BLANK_PATTERN.search(question.stem):
            issues.append("지문에 빈칸 표시가 없음")
        return issues

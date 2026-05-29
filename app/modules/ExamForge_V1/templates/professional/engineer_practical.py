"""정보처리기사 실기 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class EngineerPracticalTemplate:
    """정보처리기사 실기 - 서술형 + 코딩문제(SQL, Python, Java, C)."""

    template_id: str = "engineer_practical"
    locale: str = "ko"
    category: str = "professional"
    display_name: str = "정보처리기사 실기"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """실기 문제 생성."""
        return f"""정보처리기사 실기시험 형식의 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 문제 유형 혼합:
  * 약술형 (2~3문장 답변)
  * 서술형 (5~10문장 답변)
  * 코딩문제는 학습 자료에 나온 언어/도구를 우선 사용
- 실기시험 기출 스타일:
  * 코드 출력 결과 작성
  * 빈칸에 들어갈 코드 작성
  * 개념을 약술하시오
- 코드 블록은 JSON 필드로 직접 쓰지 말고 문제 지문에는 코드 결과/오류/사용 위치만 묻기

[출력 형식 - JSON 배열]
[
  {{
    "stem": "문제 지문",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "적용|분석|평가"
  }}
]"""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """실기는 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 및 해설 생성."""
        code_section = ""
        if question_draft.code_snippet:
            code_section = f"\n[코드]\n```\n{question_draft.code_snippet}\n```\n"
        return f"""정보처리기사 실기 문제의 정답과 해설을 생성하시오.

[자료]
{source_text[:4000]}

[문제]
{question_draft.stem}
{code_section}
[조건]
1. 정확한 정답 작성 (코드 출력 결과 / 빈칸 답 / 서술 답안)
2. 풀이 과정을 단계별로 설명
3. 관련 핵심 이론 요약

출력 JSON: {{
  "correct_answer": "정답",
  "explanation": "풀이 과정 + 핵심 이론",
  "source_reference": "관련 개념"
}}"""

    def parse_generation_response(self, raw_text: str) -> list[QuestionDraft]:
        """파싱."""
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
                bloom_level=item.get("bloom_level", "적용"),
                stem=item["stem"],
                code_snippet=item.get("code_snippet"),
            ))
        return drafts

    def parse_answer_response(self, raw_text: str, draft: QuestionDraft) -> Question:
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
            code_snippet=draft.code_snippet,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증."""
        issues: list[str] = []
        if not question.correct_answer:
            issues.append("정답이 비어있음")
        if not question.explanation:
            issues.append("해설이 비어있음")
        if len(question.explanation) < 30:
            issues.append("해설이 너무 짧음 (풀이 과정 부족)")
        return issues

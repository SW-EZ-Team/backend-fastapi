"""한국어 OX형 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


# LLM 정답 변형을 표준 형태로 정규화하는 매핑
_OX_NORMALIZE: dict[str, str] = {
    "O": "O", "o": "O", "참": "O", "TRUE": "O", "True": "O",
    "true": "O", "T": "O", "t": "O",
    "X": "X", "x": "X", "거짓": "X", "FALSE": "X", "False": "X",
    "false": "X", "F": "X", "f": "X",
}


class KoreanTrueFalseTemplate:
    """OX형 - 함정 문장 포함 여부."""

    template_id: str = "ko_true_false"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "OX형 (참/거짓)"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """OX 문제 생성 프롬프트."""
        trap_guide = ""
        if difficulty >= 3:
            trap_guide = "- 고난도: 부분적으로 맞지만 핵심이 틀린 함정 문장 포함\n"
        return f"""다음 학습 자료를 기반으로 OX(참/거짓) 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 참(O)과 거짓(X) 비율을 약 50:50으로 유지
- 명확히 판별 가능한 진술문 형태
{trap_guide}
[출력 형식 - JSON 배열]
[
  {{
    "stem": "진술문 (O 또는 X로 판별)",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|분석"
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """OX형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 및 해설 생성."""
        return f"""다음 OX 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[진술문]
{question_draft.stem}

[지시사항]
1. O(참) 또는 X(거짓)으로 판정
2. 판정 근거를 원문에서 찾아 인용
3. X인 경우, 어느 부분이 왜 틀렸는지 명시

[출력 형식 - JSON]
{{
  "correct_answer": "O 또는 X",
  "explanation": "판정 근거 해설",
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
        """구조 검증 — LLM 변형 정답을 정규화 후 판정한다."""
        issues: list[str] = []
        # 정답 정규화: "참", "true", "T" 등을 표준 O/X로 변환
        raw = question.correct_answer.strip()
        normalized = _OX_NORMALIZE.get(raw)
        if normalized:
            question.correct_answer = normalized
        else:
            issues.append(f"정답이 O/X가 아님: {question.correct_answer}")
        if not question.explanation:
            issues.append("해설이 비어있음")
        return issues

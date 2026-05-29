"""한국어 연결형 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, MatchingPair
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanMatchingTemplate:
    """연결형 - 좌우 쌍 매칭."""

    template_id: str = "ko_matching"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "연결형"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """연결형 문제 생성 프롬프트."""
        pair_count = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7}
        return f"""다음 학습 자료를 기반으로 연결형(매칭) 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 좌우 쌍 수: {pair_count.get(difficulty, 5)}개
- 좌측: 용어/개념/코드, 우측: 설명/결과/정의
- 1:1 대응만 허용 (중복 매칭 금지)

[출력 형식 - JSON 배열]
[
  {{
    "stem": "다음 좌측 항목과 우측 항목을 올바르게 연결하시오.",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|분석",
    "matching_pairs": [
      {{"left": "용어A", "right": "설명A"}},
      {{"left": "용어B", "right": "설명B"}}
    ]
  }}
]

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """연결형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 매칭 검증."""
        pairs_str = json.dumps(
            [p.model_dump() for p in (question_draft.matching_pairs or [])],
            ensure_ascii=False,
        )
        return f"""다음 연결형 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[매칭 쌍]
{pairs_str}

[지시사항]
1. 각 좌-우 쌍의 연결이 올바른지 검증
2. 올바른 매칭을 "A-1, B-2, ..." 형태로 정리
3. 각 연결의 근거를 해설에 포함

[출력 형식 - JSON]
{{
  "correct_answer": "A-1, B-2, C-3, ...",
  "explanation": "각 매칭 근거 해설",
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
            pairs = [
                MatchingPair(**p) for p in item.get("matching_pairs", [])
            ]
            drafts.append(
                QuestionDraft(
                    draft_id=f"draft_{uuid.uuid4().hex[:8]}",
                    template_id=self.template_id,
                    topic=item.get("topic", ""),
                    difficulty=item.get("difficulty", 3),
                    bloom_level=item.get("bloom_level", ""),
                    stem=item["stem"],
                    matching_pairs=pairs,
                )
            )
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
            matching_pairs=draft.matching_pairs,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증."""
        issues: list[str] = []
        if not question.matching_pairs:
            issues.append("매칭 쌍이 비어있음")
        elif len(question.matching_pairs) < 3:
            issues.append("매칭 쌍이 3개 미만")
        if not question.correct_answer:
            issues.append("정답이 비어있음")
        return issues

"""한국어 4지선다 객관식 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanMC4Template:
    """4지선다 객관식 - 정답 1개, 난이도별 지문 길이 조절."""

    template_id: str = "ko_multiple_choice_4"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "4지선다 객관식"

    # 난이도별 지문 길이 안내 (build_generation_prompt에서 사용)
    _LENGTH_GUIDE: dict[int, str] = {
        1: "1~2문장의 간결한", 2: "2~3문장의", 3: "3~4문장의 중간 길이",
        4: "4~5문장의 복합적인", 5: "5문장 이상의 분석적 사고가 필요한",
    }

    def build_generation_prompt(
        self,
        topic: str,
        difficulty: int,
        context: str,
        count: int,
    ) -> str:
        """4지선다 문제 생성 프롬프트를 구축한다."""
        length_guide = self._LENGTH_GUIDE
        return f"""다음 학습 자료를 기반으로 4지선다 객관식 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 지문 길이: {length_guide.get(difficulty, "3~4문장의")} 지문
- 보기 수: 정확히 4개 (1개 정답 + 3개 오답)
- 오답은 그럴듯하지만 명확히 구별 가능해야 함
- 블룸 분류 단계를 함께 표기

[출력 형식 - JSON 배열]
[
  {{
    "stem": "문제 지문",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석|평가|창조",
    "options": [
      {{"label": "1", "text": "보기1", "is_correct": false}},
      {{"label": "2", "text": "보기2", "is_correct": true}},
      {{"label": "3", "text": "보기3", "is_correct": false}},
      {{"label": "4", "text": "보기4", "is_correct": false}}
    ]
  }}
]

정확히 {count}개의 문제를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """오답 선택지 개선 프롬프트를 구축한다."""
        return f"""다음 문제의 오답 선택지를 개선하시오.

[문제]
{question_draft.stem}

[현재 보기]
{json.dumps([o.model_dump() for o in (question_draft.options or [])], ensure_ascii=False)}

[개선 조건]
- 총 보기 수: {num_options}개
- 오답은 학생이 자주 범하는 오개념을 반영
- 정답과 길이/형식이 비슷해야 함
- 각 오답에 대한 설계 근거를 포함

[출력 형식 - JSON]
{{
  "options": [
    {{"label": "1", "text": "보기1", "is_correct": false}},
    {{"label": "2", "text": "보기2", "is_correct": true}},
    {{"label": "3", "text": "보기3", "is_correct": false}},
    {{"label": "4", "text": "보기4", "is_correct": false}}
  ],
  "distractor_rationale": "오답 설계 근거 설명"
}}"""

    def build_answer_prompt(self, question_draft: QuestionDraft, source_text: str) -> str:
        """정답 및 해설 생성 프롬프트를 구축한다."""
        options_str = ""
        if question_draft.options:
            for opt in question_draft.options:
                mark = " [정답]" if opt.is_correct else ""
                options_str += f"  {opt.label}. {opt.text}{mark}\n"
        return f"""다음 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[보기]
{options_str}

[지시사항]
1. 단계별로 사고하여 정답을 도출하시오 (Chain-of-Thought)
2. 정답이 맞는 이유를 명확히 설명하시오
3. 각 오답이 틀린 이유를 간략히 언급하시오

[출력 형식 - JSON]
{{
  "correct_answer": "정답 보기 번호",
  "explanation": "해설 전문",
  "source_reference": "관련 원문 부분 인용"
}}"""

    def parse_generation_response(self, raw_text: str) -> list[QuestionDraft]:
        """AI 응답에서 문제 초안 목록을 파싱한다."""
        try:
            data = json.loads(extract_json(raw_text))
        except json.JSONDecodeError as e:
            raise ParseError(f"JSON 파싱 실패: {e}") from e
        data = unwrap_json_array(data)
        drafts: list[QuestionDraft] = []
        for item in data:
            item = normalize_question_fields(item)
            options = [
                QuestionOption(**opt) for opt in item.get("options", [])
            ]
            drafts.append(
                QuestionDraft(
                    draft_id=f"draft_{uuid.uuid4().hex[:8]}",
                    template_id=self.template_id,
                    topic=item.get("topic", ""),
                    difficulty=item.get("difficulty", 3),
                    bloom_level=item.get("bloom_level", ""),
                    stem=item["stem"],
                    options=options,
                )
            )
        return drafts

    def parse_answer_response(
        self, raw_text: str, draft: QuestionDraft
    ) -> Question:
        """AI 응답에서 완성된 문제를 파싱한다."""
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
        """구조 검증 - 4지선다 규칙 확인."""
        issues: list[str] = []
        if not question.options:
            issues.append("보기가 없음")
            return issues
        if len(question.options) != 4:
            issues.append(f"보기 수 불일치: {len(question.options)}개")
        correct_count = sum(
            1 for o in question.options if o.is_correct
        )
        if correct_count != 1:
            issues.append(f"정답 수 불일치: {correct_count}개")
        if not question.correct_answer:
            issues.append("정답이 비어있음")
        if not question.explanation:
            issues.append("해설이 비어있음")
        return issues

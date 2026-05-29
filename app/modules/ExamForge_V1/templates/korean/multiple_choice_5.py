"""한국어 5지선다 객관식 템플릿 (정보처리기사 필기 형식 호환)."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanMC5Template:
    """5지선다 객관식 - 정보처리기사 필기 호환 형식."""

    template_id: str = "ko_multiple_choice_5"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "5지선다 객관식"

    def build_generation_prompt(
        self,
        topic: str,
        difficulty: int,
        context: str,
        count: int,
    ) -> str:
        """5지선다 문제 생성 프롬프트."""
        return f"""다음 학습 자료를 기반으로 5지선다 객관식 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 보기 수: 정확히 5개 (1개 정답 + 4개 오답)
- 정보처리기사 필기 출제 스타일 준수
- 전문 용어를 정확히 사용하고 모호한 표현 금지
- 블룸 분류 단계를 함께 표기
- 코드/프로그래밍 주제라면 코드의 결과, 오류 원인, 사용 위치를 묻는 문항 포함

[출력 형식 - JSON 배열]
[
  {{
    "stem": "문제 지문",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석|평가|창조",
    "options": [
      {{"label": "1", "text": "보기1", "is_correct": false}},
      {{"label": "2", "text": "보기2", "is_correct": false}},
      {{"label": "3", "text": "보기3", "is_correct": true}},
      {{"label": "4", "text": "보기4", "is_correct": false}},
      {{"label": "5", "text": "보기5", "is_correct": false}}
    ]
  }}
]

정확히 {count}개의 문제를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(self, question_draft: QuestionDraft, num_options: int) -> str:
        """오답 선택지 개선 프롬프트."""
        return f"""다음 5지선다 문제의 오답 선택지를 개선하시오.

[문제]
{question_draft.stem}

[현재 보기]
{json.dumps([o.model_dump() for o in (question_draft.options or [])], ensure_ascii=False)}

[개선 조건]
- 총 보기 수: {num_options}개
- 오답은 실제 시험에서 학생이 혼동하는 개념을 반영
- 보기 간 길이와 형식 균일성 유지
- "모두 맞다/틀리다" 같은 메타 선택지 금지

[출력 형식 - JSON]
{{
  "options": [
    {{"label": "1", "text": "보기1", "is_correct": false}},
    {{"label": "2", "text": "보기2", "is_correct": false}},
    {{"label": "3", "text": "보기3", "is_correct": true}},
    {{"label": "4", "text": "보기4", "is_correct": false}},
    {{"label": "5", "text": "보기5", "is_correct": false}}
  ],
  "distractor_rationale": "오답 설계 근거"
}}"""

    def build_answer_prompt(
        self,
        question_draft: QuestionDraft,
        source_text: str,
    ) -> str:
        """정답 및 해설 생성 프롬프트."""
        options_str = ""
        if question_draft.options:
            for opt in question_draft.options:
                mark = " [정답]" if opt.is_correct else ""
                options_str += f"  {opt.label}. {opt.text}{mark}\n"
        code = f"\n[코드]\n```\n{question_draft.code_snippet}\n```\n" if question_draft.code_snippet else ""
        return f"""다음 5지선다 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}
{code}

[보기]
{options_str}

[지시사항]
1. Chain-of-Thought로 정답을 도출하시오
2. 정답 근거를 원문에서 인용하시오
3. 주요 오답 2개에 대해 왜 틀렸는지 설명하시오

[출력 형식 - JSON]
{{
  "correct_answer": "정답 보기 번호",
  "explanation": "해설 전문",
  "source_reference": "관련 원문 인용"
}}"""

    def parse_generation_response(
        self, raw_text: str
    ) -> list[QuestionDraft]:
        """AI 응답에서 문제 초안 목록을 파싱한다."""
        try:
            data = parse_llm_json(raw_text)
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
                    code_snippet=item.get("code_snippet"),
                )
            )
        return drafts

    def parse_answer_response(
        self, raw_text: str, draft: QuestionDraft
    ) -> Question:
        """AI 응답에서 완성된 문제를 파싱한다."""
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
            options=draft.options,
            code_snippet=draft.code_snippet,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """5지선다 구조 검증."""
        issues: list[str] = []
        if not question.options:
            issues.append("보기가 없음")
            return issues
        if len(question.options) != 5:
            issues.append(f"보기 수 불일치: {len(question.options)}개 (5개 필요)")
        correct_count = sum(1 for o in question.options if o.is_correct)
        if correct_count != 1:
            issues.append(f"정답 수 불일치: {correct_count}개")
        if not question.correct_answer:
            issues.append("정답이 비어있음")
        if not question.explanation:
            issues.append("해설이 비어있음")
        return issues

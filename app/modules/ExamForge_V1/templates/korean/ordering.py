"""한국어 순서배열 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import parse_llm_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft
from app.modules.ExamForge_V1.common.errors import ParseError


class KoreanOrderingTemplate:
    """순서배열 - 프로세스/알고리즘 단계."""

    template_id: str = "ko_ordering"
    locale: str = "ko"
    category: str = "korean"
    display_name: str = "순서배열"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """순서배열 문제 생성 프롬프트.

        ordering_items와 정답 순서 항목 집합이 동일해야 하는 제약을 명시해
        '배열 항목과 정답 순서의 항목이 불일치' 검증 탈락을 사전 차단한다.
        few-shot 예시로 형식을 명확히 한다.
        """
        items_range = {1: "3~4", 2: "4~5", 3: "5~6", 4: "6~7", 5: "7~8"}
        return f"""다음 학습 자료를 기반으로 순서배열 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 배열 항목 수: {items_range.get(difficulty, "5~6")}개
- 대상: 프로세스 단계, 알고리즘 절차, 개발 생명주기 단계 등
- 정답 순서가 명확히 하나만 존재해야 함 (동점 순서 모호 금지)
- 항목은 섞인(무작위) 순서로 제시 (정답 순서대로 나열 금지)

[⚠️ 검증 통과를 위한 필수 규칙]
1. ordering_items 배열의 모든 항목이 정답 순서에도 반드시 포함 (항목 추가·제거 금지)
2. stem은 "다음 ~을 올바른 순서로 나열하시오" 형태의 완전한 질문 문장
3. bloom_level: 이해|적용|분석 중 하나
4. JSON 배열 외 추가 텍스트 출력 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "다음 [대상]을 올바른 순서로 나열하시오.",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "이해|적용|분석",
    "ordering_items": ["항목C", "항목A", "항목D", "항목B"]
  }}
]

[모범 예시 — 이 형식·수준으로 출력할 것 (내용은 학습 자료 기반으로 새로 작성)]
[
  {{
    "stem": "다음 소프트웨어 개발 생명주기(SDLC) 단계를 올바른 순서로 나열하시오.",
    "topic": "소프트웨어공학",
    "difficulty": 2,
    "bloom_level": "이해",
    "ordering_items": ["구현", "요구사항 분석", "테스트", "설계", "유지보수"]
  }}
]
- 위 예시의 정답 순서: 요구사항 분석 → 설계 → 구현 → 테스트 → 유지보수
- ordering_items에 제시된 5개 항목이 정답 순서에도 정확히 5개로 포함된다.
- ordering_items는 섞인 순서(정답과 다른 순서)로 배치한다.

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """순서배열은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 순서 생성.

        correct_ordering의 항목 집합 == ordering_items의 항목 집합을 강제해
        '배열 항목과 정답 순서의 항목이 불일치' 검증 탈락을 사전 차단한다.
        """
        items_str = json.dumps(
            question_draft.ordering_items, ensure_ascii=False
        )
        item_count = len(question_draft.ordering_items) if question_draft.ordering_items else 0
        return f"""다음 순서배열 문제의 정답을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[배열할 항목 — 정확히 이 항목들만 사용]
{items_str}

[지시사항]
1. correct_ordering: 위 항목을 올바른 순서로 재배열한 배열 (정확히 {item_count}개, 항목 추가·제거 절대 금지)
2. correct_answer: correct_ordering을 " -> "로 이어 붙인 문자열
3. explanation: 왜 이 순서인지 각 단계 근거를 포함한 40자 이상 해설

[⚠️ 출력 형식 — 반드시 준수]
- correct_ordering 배열: 위 배열할 항목 {item_count}개를 순서만 바꿔 담을 것 (새 항목 추가 금지)
- JSON 객체 하나만 출력

[출력 형식 - JSON]
{{
  "correct_answer": "항목A -> 항목B -> 항목C -> ...",
  "correct_ordering": ["항목A", "항목B", "항목C"],
  "explanation": "각 단계 순서 근거 해설 (40자 이상)",
  "source_reference": "관련 원문 인용 구절"
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
                ordering_items=item.get("ordering_items", []),
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
            ordering_items=draft.ordering_items,
            correct_ordering=data.get("correct_ordering", []),
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """구조 검증."""
        issues: list[str] = []
        if not question.ordering_items:
            issues.append("배열 항목이 비어있음")
        if not question.correct_ordering:
            issues.append("정답 순서가 비어있음")
        elif question.ordering_items:
            if set(question.ordering_items) != set(question.correct_ordering):
                issues.append("배열 항목과 정답 순서의 항목이 불일치")
        return issues

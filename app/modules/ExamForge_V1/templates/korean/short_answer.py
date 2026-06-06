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
        """단답형 문제 생성 프롬프트.

        few-shot 예시와 정답 키 형식 제약을 명시해 검증 탈락률을 낮춘다.
        단순 암기 편중을 막기 위해 다양한 질문 유형을 지시한다.
        """
        question_style = {
            1: "용어명·약어를 직접 묻는 형태 ('~를 부르는 용어는?')",
            2: "정의·특징을 1~2단어로 답하는 형태 ('~의 특성은?')",
            3: "적용 결과나 속성을 단답으로 답하는 형태 ('~를 수행하면 결과는?')",
            4: "비교·구분을 키워드 1~2개로 답하는 형태 ('A와 B의 차이점 핵심은?')",
            5: "원인·근거를 핵심 개념어 1~2개로 답하는 형태 ('~가 발생하는 이유는?')",
        }
        return f"""다음 학습 자료를 기반으로 단답형 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 정답은 1~3단어(최대 5어절)로 명확하게 답할 수 있는 문제
- 권장 질문 유형: {question_style.get(difficulty, question_style[3])}
- 답이 여러 개 가능한 모호한 문제 절대 금지 (정답이 유일하지 않으면 출제 불가)
- 학습 자료 외 외부 지식이 필요한 문항 금지

[⚠️ 검증 통과를 위한 필수 규칙]
1. "stem" 필드: 완전한 질문 문장 (명사구·미완성 문장 금지)
2. bloom_level: 기억|이해|적용|분석|평가|창조 중 반드시 하나
3. JSON 배열 외 추가 텍스트 출력 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "완전한 질문 문장",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석|평가|창조"
  }}
]

[모범 예시 — 이 형식·수준으로 출력할 것 (내용은 학습 자료 기반으로 새로 작성)]
[
  {{
    "stem": "운영체제에서 프로세스가 자원을 점유한 채 다른 프로세스의 자원을 무한히 기다리는 현상을 무엇이라 하는가?",
    "topic": "운영체제",
    "difficulty": 2,
    "bloom_level": "기억"
  }},
  {{
    "stem": "페이지 교체 알고리즘 중 가장 오래 사용되지 않은 페이지를 교체하는 알고리즘의 이름은?",
    "topic": "운영체제",
    "difficulty": 3,
    "bloom_level": "이해"
  }}
]
- 첫 예시 정답: '교착상태(데드락)', 두 번째 정답: 'LRU'
- stem은 의문형 완전 문장으로 작성한다.

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """단답형은 오답 선택지가 없으므로 빈 프롬프트."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 및 해설 생성 프롬프트.

        correct_answer는 1~5어절 내 핵심어만 포함한다.
        검증에서 '정답이 너무 김 (5단어 초과)' 오류를 사전 차단한다.
        """
        return f"""다음 단답형 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[지시사항]
1. 정답(correct_answer)은 1~5어절 이내 핵심어만 작성 (문장 아님, 반드시 짧게)
   예: "교착상태" / "LRU" / "LIFO" / "3" / "B-트리"
2. 괄호 안에 동의어·약어가 있으면 함께 포함 가능 (예: "교착상태(DeadLock)")
3. explanation은 학습 자료 근거를 포함하는 완결 문장으로 40~200자 작성
4. 유사 정답(동의어, 약어 등)은 explanation 첫 문장에서 언급

[⚠️ 출력 형식 — 반드시 준수]
- correct_answer: 5어절 이하 핵심어 (긴 서술 문장 절대 금지)
- JSON 객체 하나만 출력

[출력 형식 - JSON]
{{
  "correct_answer": "핵심어 (1~5어절)",
  "explanation": "정답 근거 해설 (40~200자 완결 문장)",
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

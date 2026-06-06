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
        """서술형 문제 생성 프롬프트.

        few-shot 예시와 채점기준 포함 지시를 명시해
        '채점기준이 해설에 포함되지 않음' 검증 탈락을 사전 차단한다.
        """
        question_type = {
            1: "'설명하시오' 형태 — 하나의 개념을 풀어 서술",
            2: "'비교하시오' 형태 — 두 개념의 공통점·차이점 서술",
            3: "'분석하시오' 형태 — 원인·결과·메커니즘 분석",
            4: "'설계하시오' 또는 '제안하시오' 형태 — 방법론 제시",
            5: "'평가하시오' 또는 '토론하시오' 형태 — 다각도 판단·비판",
        }
        return f"""다음 학습 자료를 기반으로 서술형 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 권장 유형: {question_type.get(difficulty, question_type[3])}
- 답변 분량: 3~10문장
- 채점 요소(핵심 키워드·논점)가 명확히 3~5개로 구분되는 문제
- 학습 자료에 근거한 문제 (외부 지식 불필요)

[⚠️ 검증 통과를 위한 필수 규칙]
1. stem: "~하시오" 또는 "~서술하시오" 형태의 완전한 지시 문장
2. bloom_level: 이해|적용|분석|평가|창조 중 하나
3. JSON 배열 외 추가 텍스트 출력 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "~하시오 형태의 완전한 지시 문장",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "이해|적용|분석|평가|창조"
  }}
]

[모범 예시 — 이 형식·수준으로 출력할 것 (내용은 학습 자료 기반으로 새로 작성)]
[
  {{
    "stem": "관계형 데이터베이스의 정규화(Normalization) 목적과 1NF~3NF의 조건을 각각 설명하시오.",
    "topic": "데이터베이스",
    "difficulty": 4,
    "bloom_level": "분석"
  }},
  {{
    "stem": "스택(Stack)과 큐(Queue)의 구조적 차이점과 각각의 대표적 활용 사례를 비교하여 서술하시오.",
    "topic": "자료구조",
    "difficulty": 3,
    "bloom_level": "분석"
  }}
]
- 위 예시처럼 채점 요소(정규화 목적, 1NF, 2NF, 3NF / 구조 차이, 활용사례)가 명확하다.

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """서술형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """모범답안 및 채점기준 생성 프롬프트.

        explanation에 '채점', '배점', '기준' 키워드 중 하나가 반드시 포함되도록 명시해
        '채점기준이 해설에 포함되지 않음' 검증 탈락을 사전 차단한다.
        """
        return f"""다음 서술형 문제의 모범답안과 채점기준을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[지시사항]
1. correct_answer: 3~10문장의 모범답안 전문 (50자 이상 완결 서술)
2. explanation: 반드시 아래 형식의 채점기준을 포함할 것
   [채점기준]
   1. 채점 요소1 (배점 XX%)
   2. 채점 요소2 (배점 XX%)
   3. 채점 요소3 (배점 XX%)
   ...
   — 채점 요소는 3~5개, 배점 합산 100%
   — 각 요소별 부분점수 기준도 포함

[⚠️ 출력 형식 — 반드시 준수]
- correct_answer: 50자 이상 완결 서술 문장
- explanation: "채점기준"·"배점"·"점수" 중 하나 이상 반드시 포함
- JSON 객체 하나만 출력

[출력 형식 - JSON]
{{
  "correct_answer": "모범답안 전문 (3~10문장, 50자 이상)",
  "explanation": "[채점기준]\\n1. 요소1 (30%)\\n2. 요소2 (30%)\\n3. 요소3 (40%)\\n...",
  "source_reference": "관련 원문 인용 구절"
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

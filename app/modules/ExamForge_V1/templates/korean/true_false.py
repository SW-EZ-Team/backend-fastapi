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
        """OX 문제 생성 프롬프트.

        few-shot 예시와 엄격한 JSON 스키마를 명시해 파싱 실패율을 낮춘다.
        """
        trap_guide = ""
        if difficulty >= 3:
            trap_guide = (
                "- 고난도: 부분적으로 맞지만 핵심 조건 하나가 틀린 '함정 문장' 반드시 포함\n"
                "  (예: '스택은 LIFO 구조이며 모든 삽입은 후단에서 이뤄진다' — LIFO는 맞지만\n"
                "   '모든 삽입이 후단'이라는 표현은 구현에 따라 다르므로 X)\n"
            )
        # 중복 방지 지시: 이미 제목·키워드 중심 암기 문항이 많으면 응용·비교 문항 요구
        diversity_guide = (
            "- 단순 정의 암기 문항에만 편중하지 말고 '조건-결과', '비교', '예외 탐지' 형태를 섞는다.\n"
        )
        return f"""다음 학습 자료를 기반으로 OX(참/거짓) 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 참(O)과 거짓(X) 비율을 정확히 50:50으로 유지 (홀수면 O가 1개 더)
- 진술문은 단 하나의 해석만 가능하도록 명확히 작성 (모호한 진술 금지)
- 학습 자료에 근거하지 않는 외부 지식 진술 금지
{trap_guide}{diversity_guide}
[⚠️ 검증 통과를 위한 필수 규칙]
1. "stem" 필드는 반드시 완전한 하나의 진술문 (의문문·명령문 금지)
2. bloom_level은 반드시 기억|이해|적용|분석 중 하나 (다른 값 금지)
3. JSON 배열 외의 텍스트(마크다운, 설명, 코드블록) 출력 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "완전한 진술문 (O 또는 X 중 하나로 명확히 판별)",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석"
  }}
]

[모범 예시 — 이 형식·수준으로 출력할 것 (내용은 학습 자료 기반으로 새로 작성)]
[
  {{
    "stem": "관계형 데이터베이스에서 기본키는 NULL 값을 가질 수 없다.",
    "topic": "데이터베이스",
    "difficulty": 2,
    "bloom_level": "기억"
  }},
  {{
    "stem": "SQL의 INNER JOIN은 두 테이블 중 한쪽에만 존재하는 레코드도 결과에 포함한다.",
    "topic": "데이터베이스",
    "difficulty": 3,
    "bloom_level": "이해"
  }}
]
- 첫 번째 예시는 O(참), 두 번째 예시는 X(거짓)이다.
- 위 예시처럼 stem은 명사 종결형 서술문으로 작성한다.
- topic, difficulty, bloom_level 필드를 모두 채운다.

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """OX형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 및 해설 생성.

        correct_answer는 반드시 대문자 O 또는 X만 허용한다.
        파싱 실패를 막기 위해 JSON 형식 제약을 명시한다.
        """
        return f"""다음 OX 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[진술문]
{question_draft.stem}

[지시사항]
1. O(참) 또는 X(거짓)으로 판정
2. 판정 근거를 원문에서 찾아 인용
3. X인 경우, 어느 부분이 왜 틀렸는지 구체적으로 명시 (어떤 단어/조건이 틀렸는지)
4. 해설은 50자 이상 완결 문장으로 작성 (단어 나열 금지)

[⚠️ 출력 형식 — 반드시 준수]
- correct_answer: 반드시 대문자 "O" 또는 대문자 "X" 중 하나만 (다른 값 금지)
- JSON 객체 하나만 출력 (배열·설명·마크다운 금지)

[출력 형식 - JSON]
{{
  "correct_answer": "O",
  "explanation": "판정 근거 해설 (50자 이상 완결 문장)",
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

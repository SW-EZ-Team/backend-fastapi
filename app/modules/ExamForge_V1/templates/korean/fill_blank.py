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
        """빈칸채우기 문제 생성 프롬프트.

        blank_positions 수와 실제 빈칸(___ 또는 (   )) 수의 불일치가
        검증 탈락의 주요 원인이므로 둘을 반드시 일치시키도록 명시한다.
        few-shot 예시로 형식을 명확히 한다.
        """
        blank_count_guide = {1: "1개", 2: "1~2개", 3: "2개", 4: "2~3개", 5: "3개"}
        return f"""다음 학습 자료를 기반으로 빈칸채우기 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 빈칸은 반드시 ___ (언더스코어 3개 이상) 기호로만 표시 (괄호 형식 금지)
- 빈칸 수: {blank_count_guide.get(difficulty, "2개")}
- 빈칸에 들어갈 답: 핵심 용어, 개념명, 숫자 중 하나 (코드 조각은 단순 키워드만)
- 학습 자료에서 직접 도출 가능한 답만 사용

[⚠️ 검증 통과를 위한 필수 규칙]
1. stem의 ___ 기호 개수 == blank_positions 배열의 원소 개수 (반드시 일치)
   예: stem에 ___ 2개 → blank_positions에 0-indexed 위치 2개
2. blank_positions 값은 stem을 공백으로 분리한 단어 목록에서의 0-indexed 위치
3. bloom_level: 기억|이해|적용 중 하나
4. JSON 배열 외 추가 텍스트 출력 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "___은/는 [주제어]에서 ___을/를 나타낸다.",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용",
    "blank_positions": [0, 6]
  }}
]

[모범 예시 — 이 형식·수준으로 출력할 것 (내용은 학습 자료 기반으로 새로 작성)]
[
  {{
    "stem": "___은 데이터를 후입선출(LIFO) 방식으로 관리하는 선형 자료구조이다.",
    "topic": "자료구조",
    "difficulty": 2,
    "bloom_level": "기억",
    "blank_positions": [0]
  }},
  {{
    "stem": "프로세스가 ___ 상태에 있을 때 CPU를 점유하고 있으며 ___ 큐에서 실행된다.",
    "topic": "운영체제",
    "difficulty": 3,
    "bloom_level": "이해",
    "blank_positions": [1, 10]
  }}
]
- 첫 예시: 빈칸 1개, blank_positions 원소 1개 (일치)
- 두 번째 예시: 빈칸 2개, blank_positions 원소 2개 (일치)
- stem 내 ___ 개수와 blank_positions 개수가 반드시 같아야 한다.

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """빈칸채우기는 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 생성 프롬프트.

        blank_answers 배열 길이 == blank_positions 배열 길이를 강제해
        '빈칸 수와 답 수 불일치' 검증 탈락을 사전 차단한다.
        """
        code_section = ""
        if question_draft.code_snippet:
            code_section = f"\n[코드]\n{question_draft.code_snippet}\n"
        blank_count = len(question_draft.blank_positions) if question_draft.blank_positions else 1
        return f"""다음 빈칸채우기 문제의 정답을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}
{code_section}
[빈칸 위치 (0-indexed)]
{question_draft.blank_positions}

[지시사항]
1. blank_answers 배열에 정확히 {blank_count}개의 답을 순서대로 작성 (빈칸 개수와 반드시 일치)
2. correct_answer는 blank_answers를 쉼표로 이어 붙인 문자열
   예: blank_answers=["스택", "LRU"] → correct_answer="스택, LRU"
3. 각 빈칸 답은 1~3단어 핵심어 (긴 문장 금지)
4. explanation은 각 빈칸 답의 근거를 학습 자료에서 찾아 40자 이상 서술

[⚠️ 출력 형식 — 반드시 준수]
- blank_answers: 길이 {blank_count}인 JSON 배열 (더 많거나 적으면 검증 실패)
- JSON 객체 하나만 출력

[출력 형식 - JSON]
{{
  "correct_answer": "답1, 답2, ...",
  "blank_answers": ["답1", "답2"],
  "explanation": "각 빈칸 근거 해설 (40자 이상)",
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

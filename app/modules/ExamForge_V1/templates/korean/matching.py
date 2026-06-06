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
        """연결형 문제 생성 프롬프트.

        matching_pairs 최소 3쌍 이상을 강제하고 few-shot 예시를 제공해
        '매칭 쌍이 3개 미만' 검증 탈락을 사전 차단한다.
        correct_answer 형식(A-1, B-2)도 명시해 정답 파싱 실패를 방지한다.
        """
        pair_count = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7}
        required_pairs = pair_count.get(difficulty, 5)
        return f"""다음 학습 자료를 기반으로 연결형(매칭) 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 좌우 쌍 수: 반드시 {required_pairs}개 (최소 3개 이상 필수)
- 좌측: 용어/개념/연산자, 우측: 설명/결과/정의
- 1:1 대응만 허용 (동일 우측 설명을 두 좌측 항목에 재사용 금지)
- 좌측 항목들이 서로 같은 주제 영역에서 자연스럽게 짝 지을 수 있는 쌍 구성

[⚠️ 검증 통과를 위한 필수 규칙]
1. matching_pairs 배열 길이: 반드시 {required_pairs}개 (3개 미만이면 검증 실패)
2. left/right 모두 비어있지 않은 문자열
3. bloom_level: 기억|이해|분석 중 하나
4. JSON 배열 외 추가 텍스트 출력 금지

[출력 형식 - JSON 배열]
[
  {{
    "stem": "다음 좌측 항목과 우측 항목을 올바르게 연결하시오.",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|분석",
    "matching_pairs": [
      {{"left": "용어A", "right": "설명A"}},
      {{"left": "용어B", "right": "설명B"}},
      {{"left": "용어C", "right": "설명C"}}
    ]
  }}
]

[모범 예시 — 이 형식·수준으로 출력할 것 (내용은 학습 자료 기반으로 새로 작성)]
[
  {{
    "stem": "다음 자료구조와 그 특성을 올바르게 연결하시오.",
    "topic": "자료구조",
    "difficulty": 2,
    "bloom_level": "기억",
    "matching_pairs": [
      {{"left": "스택(Stack)", "right": "LIFO — 마지막 삽입이 가장 먼저 삭제"}},
      {{"left": "큐(Queue)", "right": "FIFO — 먼저 삽입된 것이 먼저 삭제"}},
      {{"left": "덱(Deque)", "right": "양방향 삽입·삭제 가능한 선형 구조"}},
      {{"left": "힙(Heap)", "right": "우선순위 기준으로 삭제되는 트리 기반 구조"}}
    ]
  }}
]
- 위 예시는 난이도 2 기준 4쌍이다. 요청 난이도({difficulty})에 맞게 {required_pairs}쌍을 생성한다.
- matching_pairs가 {required_pairs}개 미만이면 반드시 추가해 {required_pairs}개를 맞춰라.

정확히 {count}개를 JSON 배열로 출력하시오."""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """연결형은 오답 선택지 없음."""
        return ""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 매칭 검증.

        correct_answer 형식("A-1, B-2, ...")을 명시해
        파싱 불가능한 자유 텍스트 응답을 방지한다.
        """
        pairs = question_draft.matching_pairs or []
        pairs_str = json.dumps(
            [p.model_dump() for p in pairs],
            ensure_ascii=False,
        )
        # 좌측 레이블 생성 (A, B, C, ...) — 정답 형식 예시 제공에 사용
        left_labels = [chr(65 + i) for i in range(len(pairs))]
        right_labels = [str(i + 1) for i in range(len(pairs))]
        answer_format_example = ", ".join(
            f"{l}-{r}" for l, r in zip(left_labels, right_labels)
        )
        return f"""다음 연결형 문제의 정답과 해설을 생성하시오.

[원본 자료]
{source_text[:4000]}

[문제]
{question_draft.stem}

[매칭 쌍 — 좌측은 A·B·C... 순, 우측은 1·2·3... 순으로 번호 부여]
{pairs_str}

[지시사항]
1. 각 좌측 항목(A, B, C...)이 연결되어야 할 우측 항목(1, 2, 3...)을 찾아라
2. correct_answer: 반드시 "A-N, B-N, C-N, ..." 형식으로 작성
   예: "{answer_format_example}" (이 예시는 좌측 순서 그대로 연결된 경우)
3. 실제로 틀린 매칭이 있으면 올바른 번호로 교정해 정확한 매칭을 출력
4. explanation: 각 매칭의 근거를 40자 이상 해설

[⚠️ 출력 형식 — 반드시 준수]
- correct_answer: "A-숫자, B-숫자, ..." 형식 (이 형식이 아니면 파싱 실패)
- JSON 객체 하나만 출력

[출력 형식 - JSON]
{{
  "correct_answer": "A-1, B-2, C-3, ...",
  "explanation": "각 매칭 근거 해설 (40자 이상)",
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

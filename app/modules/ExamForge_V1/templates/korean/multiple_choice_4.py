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
- 오답은 정답과 같은 주제 영역의 그럴듯한 오개념이되, 정답은 명확히 하나로 구별 가능해야 함
- 블룸 분류 단계를 함께 표기

[보기 균형 규칙 — 정답 단서 제거]
- 모든 보기는 길이·문체·구체성을 비슷하게 맞춘다.
- 정답만 교과서 문장과 똑같이 인용하거나, 정답/오답 한쪽만 유독 길거나 형식이 다르면 안 된다.
- 정답을 식별할 수 있는 표면적 단서(유독 긴 길이, 따옴표 유무, 전문용어 밀도 차이)를 제거한다.
- 모든 보기가 비슷한 문장 구조(명사구 또는 완전한 서술문)로 통일한다.

[인지 수준 다양화 — 암기/핵심어찾기 편중 금지]
- 단순 암기·재인에만 머물지 말고, 다음 고차원 유형을 골고루 섞어 출제하시오:
  · 적용(시나리오): "~상황에서 가장 적절한 것은?"
  · 비교: "A와 B의 차이로 옳은 것은?"
  · 오류찾기: "다음 설명/코드에서 잘못된 것은?"
  · 반례 판단 / 동작 추론: "~수행 후 결과로 옳은 것은?"
- 단, 어떤 유형이든 정답이 명확히 단 하나로 결정되는 객관식이어야 한다(정답 모호 금지).
- 난이도 3 이상은 개념을 떠올린 뒤 한 번 더 적용/계산/비교해야 풀리는 2단계 추론형으로 작성한다.
  예: 절댓값 계산 후 대소 비교, 사칙연산 순서 적용 후 결과 판단, 규칙 확인 후 예외 사례 선택.

[stem(발문) 작성 규칙]
- 실제 한국 시험처럼 발문을 자연스럽고 다양하게 작성하시오.
- "다음 물음에 가장 적절한 답을 고르시오" 같은 고정 보일러플레이트 접두사를
  모든 문항에 반복하지 마시오. 발문 자체가 무엇을 묻는지 드러나게 쓰시오.
- 문항 성격에 맞춰 다음 같은 다양한 형태를 활용하시오:
  "~로 가장 적절한 것은?", "~에 대한 설명으로 옳은 것은?",
  "다음 중 ~인 것은?", "~할 때의 결과로 옳은 것은?",
  "<보기>의 설명에 해당하는 것은?", "~에 대한 설명으로 옳지 않은 것은?".
- 단, 지문(맥락)이 필요하면 발문 앞에 맥락 문장을 두고 마지막에 발문을 두시오.

[출력 형식 - JSON 배열]
[
  {{
    "stem": "맥락(필요 시) + 다양한 실전형 발문",
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

[모범 예시 — 형식을 정확히 이 수준으로 채우시오(내용은 학습 자료에 맞게 새로 작성)]
[
  {{
    "stem": "관계형 데이터베이스에서 개체 무결성(entity integrity)에 대한 설명으로 옳은 것은?",
    "topic": "데이터베이스",
    "difficulty": 3,
    "bloom_level": "이해",
    "options": [
      {{"label": "1", "text": "기본키를 구성하는 속성은 NULL 값을 가질 수 없다", "is_correct": true}},
      {{"label": "2", "text": "외래키는 반드시 기본키와 이름이 같아야 한다", "is_correct": false}},
      {{"label": "3", "text": "모든 속성은 중복 값을 가질 수 없다", "is_correct": false}},
      {{"label": "4", "text": "테이블은 최소 두 개의 기본키를 가져야 한다", "is_correct": false}}
    ]
  }}
]
- 위 예시처럼 보기는 정확히 4개, label은 "1"~"4", is_correct는 정답 1개만 true이다.
- bloom_level은 반드시 한국어(기억|이해|적용|분석|평가|창조) 중 하나로 표기한다.

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
- 오답은 정답과 '같은 주제 영역' 안에서 학습자가 실제로 헷갈리는 인접 개념으로 만든다.
- 정답과 같은 카테고리·같은 추상수준 유지 (정답이 자료구조면 오답도 자료구조).
- 과목 밖이거나 무관한 보기 금지 — 학생이 단번에 제거하면 변별력이 죽는다.
- 보기 균형: 모든 보기(정답 포함)의 길이·문체·구체성을 비슷하게 맞춘다. 정답만 유독 길거나 짧거나 형식이 다르면 정답 단서가 되므로 금지.
- ⚠️ is_correct=true인 정답 보기의 '내용'은 그대로 보존한다. 오답(is_correct=false)만 개선한다.
- 각 오답이 노린 오개념/혼동 지점을 설계 근거에 포함.

[출력 형식 - JSON]
{{
  "options": [
    {{"label": "1", "text": "보기1", "is_correct": false}},
    {{"label": "2", "text": "보기2", "is_correct": true}},
    {{"label": "3", "text": "보기3", "is_correct": false}},
    {{"label": "4", "text": "보기4", "is_correct": false}}
  ],
  "distractor_rationale": "각 오답이 노린 오개념/혼동 지점을 짧게 설명"
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

[주제]
{question_draft.topic}

[지시사항]
1. 정답 판단 근거를 원본 자료와 보기의 관계로 도출하되, 최종 해설에는 필요한 근거만 간결히 쓰시오
2. 정답이 맞는 이유를 명확히 설명하시오 (정답 보기 번호를 해설에 반드시 포함)
3. 오답 보기 각각에 대해 왜 틀렸는지 1줄씩, 그 오답이 노리는 오개념 라벨을 괄호로 명시하시오
   예: "1번은 배열의 접근 속도를 연결 리스트로 혼동한 경우다(자료구조 속성 혼동)."
   예: "3번은 스택의 LIFO를 큐의 FIFO로 뒤바꾼 경우다(FIFO/LIFO 속성 혼동)."
4. 해설 끝에 이 개념이 다뤄진 단원/주제를 한 문장으로 가볍게 연결하시오
   (위 [주제]나 [원본 자료]의 단원/주제명을 활용. 예: "이 개념은 [{question_draft.topic}] 단원에서 다룬 내용이에요").
5. explanation은 "정답 근거: ... 오답 해설: ..." 구조의 완결 문장으로 쓰고, 마지막 문장이 중간에 끊기지 않게 하시오.

[출력 형식 - JSON]
{{
  "correct_answer": "정답 보기 번호",
  "explanation": "해설 전문 (정답 보기 번호 필수 포함, 오답별 오개념 라벨 포함, 끝에 단원/주제 근거 연결)",
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

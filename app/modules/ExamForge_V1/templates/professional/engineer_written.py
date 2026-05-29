"""정보처리기사 필기 템플릿."""
from __future__ import annotations
from app.modules.ExamForge_V1.common.json_utils import extract_json, unwrap_json_array, normalize_question_fields

import json
import uuid

from app.modules.ExamForge_V1.schemas.question import Question, QuestionDraft, QuestionOption
from app.modules.ExamForge_V1.common.errors import ParseError

# 정보처리기사 필기 5과목 (공백 없는 내부 표기)
SUBJECTS = [
    "소프트웨어설계",
    "소프트웨어개발",
    "데이터베이스구축",
    "프로그래밍언어활용",
    "정보시스템구축관리",
]
# 실제 시험 기준: 과목당 20문항
QUESTIONS_PER_SUBJECT = 20


class EngineerWrittenTemplate:
    """정보처리기사 필기 - 5과목, 과목당 20문항, 5지선다."""

    template_id: str = "engineer_written"
    locale: str = "ko"
    category: str = "professional"
    display_name: str = "정보처리기사 필기"

    def build_generation_prompt(
        self, topic: str, difficulty: int, context: str, count: int,
    ) -> str:
        """정보처리기사 필기 문제 생성."""
        return f"""정보처리기사 필기시험 형식의 5지선다 문제를 생성하시오.

[학습 자료]
{context}

[생성 조건]
- 과목/주제: {topic}
- 난이도: {difficulty}/5
- 문항 수: {count}개
- 보기: 5개 (1~5번), 정답 1개
- 정보처리기사 필기 기출문제 스타일 준수:
  * 간결하고 명확한 문장
  * 전문 IT 용어 정확 사용
  * "다음 중 ~에 해당하지 않는 것은?" 패턴 포함
  * "~에 대한 설명으로 옳은 것은?" 패턴 포함
- 과목 범위: {', '.join(SUBJECTS)}

[출력 형식 - JSON 배열]
[
  {{
    "stem": "문제 지문",
    "topic": "{topic}",
    "difficulty": {difficulty},
    "bloom_level": "기억|이해|적용|분석",
    "options": [
      {{"label": "1", "text": "보기1", "is_correct": false}},
      {{"label": "2", "text": "보기2", "is_correct": true}},
      {{"label": "3", "text": "보기3", "is_correct": false}},
      {{"label": "4", "text": "보기4", "is_correct": false}},
      {{"label": "5", "text": "보기5", "is_correct": false}}
    ]
  }}
]"""

    def build_distractor_prompt(
        self, question_draft: QuestionDraft, num_options: int,
    ) -> str:
        """기사시험 오답 개선."""
        return f"""정보처리기사 필기 문제의 오답을 기출 스타일로 개선하시오.
[문제] {question_draft.stem}
[보기] {json.dumps([o.model_dump() for o in (question_draft.options or [])], ensure_ascii=False)}
[조건]
- 실제 기출에서 자주 출현하는 혼동 개념 반영
- 비슷한 용어/약어를 활용한 함정
출력 JSON:
{{
  "options": [
    {{"label": "1", "text": "보기1", "is_correct": false}},
    {{"label": "2", "text": "보기2", "is_correct": true}},
    {{"label": "3", "text": "보기3", "is_correct": false}},
    {{"label": "4", "text": "보기4", "is_correct": false}}
  ],
  "distractor_rationale": "기출 패턴 분석 근거"
}}"""

    def build_answer_prompt(
        self, question_draft: QuestionDraft, source_text: str,
    ) -> str:
        """정답 및 해설."""
        opts = "\n".join(
            f"  {o.label}. {o.text}" for o in (question_draft.options or [])
        )
        return f"""정보처리기사 필기 문제의 정답과 해설을 생성하시오.
[자료] {source_text[:4000]}
[문제] {question_draft.stem}
[보기]\n{opts}
[조건]
1. 정답 번호 제시
2. 해설에 관련 이론/개념 요약
3. 오답 2개에 대한 간단한 부연
출력 JSON: {{"correct_answer": "번호", "explanation": "해설", "source_reference": "관련 개념"}}"""

    def parse_generation_response(self, raw_text: str) -> list[QuestionDraft]:
        """파싱."""
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
                options=[QuestionOption(**o) for o in item.get("options", [])],
            ))
        return drafts

    def parse_answer_response(self, raw_text: str, draft: QuestionDraft) -> Question:
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
            options=draft.options,
            correct_answer=data["correct_answer"],
            explanation=data["explanation"],
            source_reference=data.get("source_reference", ""),
        )

    def validate_structure(self, question: Question) -> list[str]:
        """5지선다 검증."""
        issues: list[str] = []
        if not question.options:
            issues.append("보기가 없음")
            return issues
        if len(question.options) != 5:
            issues.append(f"보기 수: {len(question.options)} (5개 필요)")
        correct = sum(1 for o in question.options if o.is_correct)
        if correct != 1:
            issues.append(f"정답 수: {correct} (1개 필요)")
        return issues

    def validate_subject_distribution(self, questions: list[Question]) -> list[str]:
        """100문항일 때 5과목 균등 분배를 검증한다. 부분 생성(미만)이면 건너뛴다."""
        issues: list[str] = []
        if len(questions) != 100:
            # 부분 생성 시 과목 분배 검증 생략
            return issues

        # 과목별 문항 수 집계
        subject_counts: dict[str, int] = {}
        missing_subject_field = 0
        for q in questions:
            subj = q.topic.strip() if q.topic else ""
            if not subj:
                missing_subject_field += 1
                continue
            # 공백 유무 모두 매칭 (예: "소프트웨어설계" == "소프트웨어 설계")
            normalized = subj.replace(" ", "")
            subject_counts[normalized] = subject_counts.get(normalized, 0) + 1

        if missing_subject_field > 0:
            issues.append(
                f"과목(subject/topic) 필드 누락: {missing_subject_field}개 문항"
            )

        # SUBJECTS 리스트 기준으로 검증 (공백 제거 비교)
        expected_normalized = [s.replace(" ", "") for s in SUBJECTS]
        for subj_norm in expected_normalized:
            count = subject_counts.get(subj_norm, 0)
            if count != QUESTIONS_PER_SUBJECT:
                issues.append(
                    f"과목 '{subj_norm}' 문항 수: {count} "
                    f"(기대: {QUESTIONS_PER_SUBJECT})"
                )

        return issues

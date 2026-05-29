"""난이도 보정 프롬프트."""
from __future__ import annotations

CALIBRATION_SYSTEM = """당신은 교육 측정 전문가입니다. 블룸 분류체계에 따라 문제의 인지 수준을 평가합니다.

[블룸 분류 단계]
1. 기억(Remember): 사실, 용어, 정의를 회상
2. 이해(Understand): 개념을 자기 말로 설명, 비교, 분류
3. 적용(Apply): 새로운 상황에 지식을 사용
4. 분석(Analyze): 구성요소 분해, 관계와 패턴 식별
5. 평가(Evaluate): 기준에 따른 판단, 비판적 사고
6. 창조(Create): 새로운 것을 종합/생성

[난이도-블룸 매핑]
- 난이도 1: 기억 위주
- 난이도 2: 이해 위주
- 난이도 3: 적용 + 일부 분석
- 난이도 4: 분석 + 평가
- 난이도 5: 평가 + 창조"""


def build_calibration_prompt(questions_json: str) -> str:
    """난이도 보정 프롬프트를 구축한다."""
    return f"""다음 문제들의 블룸 분류 수준과 난이도를 재평가하시오.

[문제 목록]
{questions_json}

[지시사항]
1. 각 문제의 인지 요구 수준을 분석
2. 현재 난이도/블룸 레벨이 적절한지 판단
3. 부적절한 경우 수정값 제시
4. 전체 분포가 목표 비율에 가까운지 확인

[출력 형식 - JSON]
{{
  "calibrations": [
    {{
      "question_id": "id",
      "current_difficulty": 3,
      "suggested_difficulty": 4,
      "current_bloom": "적용",
      "suggested_bloom": "분석",
      "reason": "보정 이유"
    }}
  ],
  "distribution_summary": {{
    "기억": 0.15,
    "이해": 0.25,
    "적용": 0.30,
    "분석": 0.20,
    "평가": 0.08,
    "창조": 0.02
  }}
}}"""

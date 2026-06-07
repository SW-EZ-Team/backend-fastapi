"""plan_exam_node에서 사용하는 프롬프트 상수."""
from __future__ import annotations

PLAN_PROMPT = """다음 주제 목록과 시험 설정을 기반으로 시험 계획을 수립하시오.

[주제 목록]
{topics_json}

[시험 설정]
{config_json}

[과목]
{subject}

[선택 템플릿 계약]
{template_contract}

[지시사항]
1. 주제별 중요도에 따라 문항 배분
2. 난이도 분포가 설정값에 맞도록 조정
3. 문제 유형별 배분은 선택 템플릿 계약의 template_id만 사용
4. type_allocations의 count 합계는 total_questions와 정확히 일치
5. 총점과 합격 기준 확정
6. 인지 수준이 암기(난이도 1~2)에만 쏠리지 않도록, difficulty_distribution에서
   적용(난이도 3)·분석(난이도 4)에 충분한 비중을 배정한다. 권장: 난이도 3+4의 합이
   전체의 40% 이상이 되도록 한다(설정값과 충돌하면 설정값을 우선한다).
7. 같은 하위 개념을 반복 출제하지 않도록 주제의 sub_concepts/key_topics/keywords를
   가능한 한 넓게 분산한다. 각 문항은 이후 내부 blueprint에서 강의·개념·난이도에
   매핑되므로 topic_weights는 특정 한 주제에 과도하게 쏠리지 않게 한다.

[절대 금지 - 시험 메타 문항 출제 금지]
이 설정 정보(total_questions, category, subject 과목명, 구성 원칙, 배점 방식,
합격 기준, 난이도 분포 비율, 평가 균형, 출제 의도 등)는 오직 문항 배분 계획
수립 목적으로만 사용한다. 이 메타데이터를 문제 stem의 소재로 삼아 "이 시험은
총 몇 문항인가?", "이 과목의 합격 기준 점수는?", "이론/실제적용 비율은?"
같은 시험 자체에 관한 문항을 절대 생성하지 않는다.

[출력 형식 - JSON]
{{
  "exam_title": "시험 제목",
  "subject": "{subject}",
  "total_questions": N,
  "total_points": N,
  "time_limit_minutes": N,
  "locale": "ko",
  "category": "korean",
  "type_allocations": [
    {{
      "template_id": "ko_multiple_choice_5",
      "count": 30,
      "difficulty_distribution": {{1: 6, 2: 9, 3: 9, 4: 4, 5: 2}},
      "points_per_question": 2.0
    }}
  ],
  "topic_weights": {{"주제1": 0.3, "주제2": 0.2}},
  "passing_score": 60.0,
  "bloom_distribution": {{"기억": 0.2, "이해": 0.3, "적용": 0.3, "분석": 0.15, "평가": 0.05}}
}}"""

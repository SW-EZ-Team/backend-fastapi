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

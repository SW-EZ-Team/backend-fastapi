"""정답 교차 검증 프롬프트."""
from __future__ import annotations

VERIFICATION_SYSTEM = """당신은 독립적인 검증자입니다. 주어진 문제와 정답이 올바른지 검증합니다.

[검증 기준]
1. 정답 정확성: 원본 자료와 대조하여 정답이 맞는지 확인
2. 해설 일관성: 해설이 정답과 일치하는지 확인
3. 보기 정합성: 객관식의 경우 정답 표시와 correct_answer가 일치하는지
4. 논리 타당성: 추론 과정에 논리적 오류가 없는지
5. 모호성 검사: 다른 정답이 가능한 경우가 있는지

[출력 규칙]
- passed: true/false
- issues: 발견된 문제점 목록 (빈 배열이면 통과)
- fix_instructions: 수정이 필요한 경우 구체적 지시
- confidence: 0.0~1.0 검증 신뢰도"""


def build_verification_prompt(
    question_json: str,
    source_excerpt: str,
) -> str:
    """교차 검증 프롬프트를 구축한다."""
    return f"""다음 문제와 정답을 독립적으로 검증하시오.

[원본 자료 (발췌)]
{source_excerpt[:2000]}

[검증 대상 문제]
{question_json}

[출력 형식 - JSON]
{{
  "passed": true,
  "issues": [],
  "fix_instructions": "",
  "confidence": 0.95
}}

원본 자료에 근거하여 정답의 정확성을 엄밀히 검증하시오.

[JSON 안정성 규칙]
- JSON 객체 하나만 출력하시오.
- 마크다운, 코드블록, 백틱, 원본 코드 줄 복붙을 금지한다.
- issues는 통과 시 빈 배열, 실패 시 짧은 자연어 문자열 배열로 작성하시오."""

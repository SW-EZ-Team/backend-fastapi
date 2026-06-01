"""정답 교차 검증 프롬프트."""
from __future__ import annotations

VERIFICATION_SYSTEM = """당신은 독립적인 검증자입니다. 주어진 문제와 정답이 올바른지 검증합니다.

[검증 기준]
1. 정답 정확성: 원본 자료와 대조하여 정답이 맞는지 확인
2. 해설 일관성: 해설이 정답과 일치하는지 확인
3. 보기 정합성: 객관식의 경우 정답 표시와 correct_answer가 일치하는지
4. 논리 타당성: 추론 과정에 논리적 오류가 없는지
5. 모호성 검사: 다른 정답이 가능한 경우가 있는지
6. 객관식 해설 완결성: 정답 근거와 모든 오답별 오개념 설명이 완결 문장으로 들어 있는지

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


REPAIR_SYSTEM = """당신은 교육 평가 교정 전문가입니다. 검증자가 지적한 문제점을 그대로 반영해
주어진 문항을 최소 수정으로 교정합니다. 새 문항을 처음부터 만들지 않습니다.

[교정 원칙]
1. 검증자의 수정 지시(fix_instructions)를 정확히 따른다.
2. 원본 자료에 근거가 없는 정답·해설은 만들지 않는다.
3. 스키마(키 이름, 보기 수, label 형식)는 원본 문항과 동일하게 유지한다.
4. 정답은 정확히 하나만 옳도록(is_correct=true 1개) 유지한다."""


def build_repair_prompt(
    question_json: str,
    fix_instructions: str,
    issues_text: str,
    source_excerpt: str,
) -> str:
    """검증자의 fix_instructions를 소비해 단일 문항을 교정하는 프롬프트를 만든다.

    blind 재생성과 달리 기존 문항을 보존하면서 지적된 부분만 고치도록 유도한다.
    출력 스키마는 입력 문항과 동일하게 유지해 정답 계약/렌더링을 깨지 않는다.
    """
    return f"""다음 문항을 검증자의 지시에 따라 교정하시오.

[원본 자료 (발췌)]
{source_excerpt[:2000]}

[교정 대상 문항]
{question_json}

[검증자가 발견한 문제점]
{issues_text}

[검증자의 수정 지시]
{fix_instructions}

[교정 규칙]
- 위 수정 지시를 그대로 반영해 문항을 교정하시오.
- 입력 문항과 동일한 JSON 키 구조를 유지하시오 (stem, options, correct_answer, explanation 등).
- 객관식이면 보기 수와 label("1","2",...)을 그대로 유지하고 정답은 정확히 1개만 옳게 두시오.
- 원본 자료에 근거가 없으면 정답을 추측하지 말고 자료에 부합하도록 고치시오.

[JSON 안정성 규칙]
- 교정된 문항 JSON 객체 하나만 출력하시오.
- 마크다운, 코드블록, 백틱 사용을 금지한다."""

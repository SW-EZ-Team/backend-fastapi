"""문항 생성 재호출 요청 보조 함수."""
from __future__ import annotations

from app.modules.ExamForge_V1.common.ai_bridge import ChapterAIRequest

# gemini-3.5-flash는 thinking 토큰(실측 0~20735 변동)이 max_output_tokens를 잠식한다.
# 4000/5000 토큰에서는 thinking이 크면 문항 JSON 본문이 절단(finish_reason=MAX_TOKENS)돼
# "Unterminated string"/"Expecting value" 파싱 오류가 다발했다(실측 3/10 유효).
# ChapterStudio 선례(24000→48000)에 따라 1차=16000, 2차=24000으로 상향한다.
# 문항 1개 단위 생성이므로 실제 출력 토큰은 1000~3000 수준이며,
# 여분 토큰은 thinking 헤드룸으로만 쓰인다(모델 한도 65536 이내).
_GEN_MAX_TOKENS_FIRST = 16000  # 1차 시도: thinking 헤드룸 확보
_GEN_MAX_TOKENS_RETRY = 24000  # 2차 시도: JSON 재출력 안정성 우선


def build_generation_request(system: str, prompt: str, attempt: int) -> ChapterAIRequest:
    """문항 생성 요청을 만든다. 2차 시도는 JSON 안정성을 우선한다."""
    return ChapterAIRequest(
        system=system,
        user=prompt,
        max_tokens=_GEN_MAX_TOKENS_RETRY if attempt else _GEN_MAX_TOKENS_FIRST,
        temperature=0.1 if attempt else 0.45,
    )


def strict_generation_prompt(prompt: str, task: dict) -> str:
    """깨진 JSON 후 재호출할 때 더 좁은 계약을 붙인다."""
    return (
        f"{prompt}\n\n[JSON 재출력 강제]\n"
        f"- JSON 배열 하나만 출력하시오. 정확히 {task.get('count', 0)}개여야 한다.\n"
        "- 설명문, 마크다운, 주석, trailing comma를 금지한다.\n"
        "- 문자열 안의 큰따옴표와 줄바꿈은 JSON 표준에 맞게 이스케이프하시오.\n"
        "- 코드 조각, 백틱, 원본 코드 줄은 JSON 문자열에 직접 넣지 말고 자연어로 지칭하시오."
    )

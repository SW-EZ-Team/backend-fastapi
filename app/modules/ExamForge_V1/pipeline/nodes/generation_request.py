"""문항 생성 재호출 요청 보조 함수."""
from __future__ import annotations

from app.modules.ExamForge_V1.common.ai_bridge import ChapterAIRequest


def build_generation_request(system: str, prompt: str, attempt: int) -> ChapterAIRequest:
    """문항 생성 요청을 만든다. 2차 시도는 JSON 안정성을 우선한다."""
    return ChapterAIRequest(
        system=system,
        user=prompt,
        max_tokens=5000 if attempt else 4000,
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

"""AI 총평(약점 진단) 프롬프트 조립 + 보기 텍스트 복원 헬퍼.

Spring과 합의된 공유 계약을 받아 codex에 넘길 system/user 프롬프트를 만든다.
- options: 보기 텍스트의 JSON 배열 문자열
- selectedOption / correctOption: 0-based 인덱스 문자열
이 둘을 안전하게 복원해(인덱스 범위·파싱 방어) 사람이 읽는 보기 텍스트로 바꾼다.
"""
from __future__ import annotations

import json

# 만점 여부 판정에 쓰는 시스템 프롬프트 — 친절한 과외쌤 해요체 강제
_SYSTEM_PROMPT = (
    "당신은 학생의 모의고사 결과를 분석하는 친절한 과외 선생님이에요. "
    "채점이 끝난 결과를 보고 개인 맞춤 학습 총평을 한국어로 작성해요. "
    "톤은 따뜻한 과외쌤 해요체(~해요, ~예요)를 일관되게 사용해요. "
    "마크다운 기호(#, *, - 등)는 쓰지 말고, 읽기 쉬운 자연스러운 단락으로 작성해요. "
    "전체 길이는 한국어 350~700자 내외로 핵심만 담아요. "
    "다른 설명이나 머리말 없이 총평 본문만 출력해요."
)

# 틀린 문항이 있는 경우의 작성 지침
# codex 재평가 지적: 틀린 문항마다 학생이 실제로 고른 보기 텍스트를 인용하고,
# 왜 그 선택이 그 오개념인지 근거를 연결한 뒤, 다음 연습 1개를 제시한다.
# 같은 오개념 묶음은 그룹으로 처리해 과외쌤답게 구조화한다.
_INSTRUCTION_WITH_WEAKNESS = (
    "다음 순서로 한 편의 글처럼 자연스럽게 이어 써요.\n"
    "1) 점수와 등급을 근거로 한두 문장 전체 평가.\n"
    "2) 틀린 문항을 반드시 '문항 번호'로 인용해요. "
    "각 틀린 문항마다: '채점 결과'에 있는 '내가 고른 보기' 텍스트를 짧게 인용하고, "
    "왜 그 선택이 어떤 오개념에서 비롯됐는지를 짧은 오개념 라벨(예: 'FIFO/LIFO 혼동')과 함께 설명해요. "
    "예: 'N번에서 \\'큐\\' 를 골랐는데, 이는 FIFO를 LIFO와 뒤바꾼 경우예요(FIFO/LIFO 혼동).'\n"
    "3) 같은 오개념 라벨이 붙은 문항은 그룹으로 묶어요"
    "(예: '3번·8번은 모두 FIFO/LIFO 혼동이에요'). "
    "맞은 문항이 보여주는 강점도 한 줄 언급해요.\n"
    "4) 오개념 그룹마다 다음 연습 1개씩만 제안해요(과하지 않게).\n"
    "5) 마지막에 격려 한 줄.\n"
    "규칙: 채점 결과에 실제로 있는 문항 번호·보기 텍스트만 인용하고, 없는 내용을 지어내지 마세요. "
    "길이는 700자를 넘지 않도록 핵심만 담아요."
)

# 만점인 경우의 작성 지침 — 약점 진단 대신 심화/응용 제안으로 전환
_INSTRUCTION_PERFECT = (
    "학생이 만점을 받았어요. 약점 진단 대신 다음을 담아요.\n"
    "1) 만점을 축하하는 전체 평가 한두 문장.\n"
    "2) 이 과목에서 다음 단계로 도전할 심화·응용 학습 제안 2~4개.\n"
    "3) 마지막에 격려 한 줄."
)


def restore_option_text(options_raw: str, index_raw: str) -> str:
    """보기 JSON 배열 문자열에서 인덱스 문자열에 해당하는 보기 텍스트를 복원한다.

    파싱 실패·인덱스 범위 초과·형식 오류는 조용히 삼키지 않고, 사람이 읽을 수 있는
    대체 문자열로 안전하게 폴백한다(프롬프트 품질만 약간 떨어질 뿐 흐름은 유지).
    """
    index = _parse_index(index_raw)
    if index is None:
        return f"(보기 인덱스 해석 불가: {index_raw!r})"
    options = _parse_options(options_raw)
    if options is None:
        return f"(보기 목록 파싱 불가, 선택 인덱스 {index})"
    if not 0 <= index < len(options):
        return f"(보기 인덱스 {index} 범위 초과, 보기 {len(options)}개)"
    return str(options[index])


def _parse_index(index_raw: str) -> int | None:
    """0-based 인덱스 문자열을 정수로 변환한다. 실패 시 None."""
    try:
        return int(str(index_raw).strip())
    except (ValueError, TypeError):
        return None


def _parse_options(options_raw: str) -> list[object] | None:
    """보기 JSON 배열 문자열을 리스트로 파싱한다. 배열이 아니면 None."""
    try:
        parsed = json.loads(options_raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def build_user_prompt(
    *,
    subject: str,
    score: int,
    total_points: int,
    grade: str,
    question_lines: list[str],
    is_perfect: bool,
) -> str:
    """codex에 넘길 사용자 프롬프트를 조립한다."""
    instruction = _INSTRUCTION_PERFECT if is_perfect else _INSTRUCTION_WITH_WEAKNESS
    header = (
        f"과목: {subject}\n"
        f"점수: {score}/{total_points} (등급 {grade})\n\n"
        f"문항별 채점 결과:\n"
    )
    body = "\n".join(question_lines) if question_lines else "(문항 정보 없음)"
    return f"{header}{body}\n\n{instruction}"


def system_prompt() -> str:
    """총평 작성용 시스템 프롬프트를 반환한다."""
    return _SYSTEM_PROMPT

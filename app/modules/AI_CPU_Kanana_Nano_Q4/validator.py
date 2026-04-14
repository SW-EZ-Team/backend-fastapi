"""Kanana 출력 검증. 규칙 위반 시 None 반환 → 폴백 트리거."""
import re

from .config import MAX_CHARS, MAX_EMOJIS, MIN_CHARS

# 이모지 유니코드 범위 — 주요 이모지 블록 포함
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]"
)


def sanitize(raw: str | None) -> str | None:
    """원시 출력 문자열을 검증하고 정제된 결과 또는 None을 반환한다.

    검증 실패 조건:
    - 빈 문자열 또는 None
    - 20자 미만 (너무 짧아 캡션 역할 불가)
    - 100자 초과 (텔레그램 표시 규격 초과)
    - 이모지 2개 이상 (v3 정책: 최대 1개)
    """
    if not raw:
        return None
    # 앞뒤 공백 제거 후 빈 문자열 체크 (공백 전용 입력 방어)
    stripped = raw.strip()
    if not stripped:
        return None
    # 첫 줄만 추출하고 다시 앞뒤 공백 제거
    text = stripped.splitlines()[0].strip()
    if not text:
        return None
    if len(text) < MIN_CHARS or len(text) > MAX_CHARS:
        return None
    if len(_EMOJI_RE.findall(text)) > MAX_EMOJIS:
        return None
    return text

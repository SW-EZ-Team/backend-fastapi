"""음성 합성 전용 대본 말투 후처리."""
from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"[^.?!]+[.?!]?")
_FORMAL_ENDINGS = ("입니다", "습니다")
_INFORMAL_ENDINGS = ("봐", "자", "야")


def apply_selective_tilde(text: str) -> str:
    """첫 문장과 마지막 문장의 부드러운 마침표만 물결표로 바꾼다."""
    matches = [match for match in _SENTENCE_RE.finditer(text) if match.group(0).strip()]
    if not matches:
        return text

    target_indexes = {0, len(matches) - 1}
    parts: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        parts.append(text[cursor : match.start()])
        sentence = match.group(0)
        parts.append(_apply_tilde_to_sentence(sentence) if index in target_indexes else sentence)
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts)


def _apply_tilde_to_sentence(sentence: str) -> str:
    """부드러운 마침표만 1개의 물결표로 대체한다."""
    stripped = sentence.rstrip()
    trailing_space = sentence[len(stripped) :]
    if not stripped.endswith("."):
        return sentence
    body = stripped[:-1].rstrip()
    if not _is_soft_sentence_ending(body):
        return sentence
    return f"{body.rstrip('~')}~{trailing_space}"


def _is_soft_sentence_ending(body: str) -> bool:
    """격식체는 제외하고 존댓말 요체와 짧은 반말 권유형만 허용한다."""
    normalized = body.rstrip("~").rstrip()
    if normalized.endswith(_FORMAL_ENDINGS):
        return False
    return normalized.endswith("요") or normalized.endswith(_INFORMAL_ENDINGS)

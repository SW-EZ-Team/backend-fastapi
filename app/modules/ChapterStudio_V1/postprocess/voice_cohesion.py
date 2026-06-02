"""슬라이드 음성대본 도입부 응집성 후처리."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

_GREETING_RE = re.compile(r"^\s*(?:안녕하세요|안녕\b|반갑습니다|반가워요|다들\s*안녕)")
_PUNCT_SPACE_RE = re.compile(r"[\s,.!?…。！？~'\"“”‘’()\[\]{}]+")
_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]?")

ScriptPair = tuple[int, str]
RewriteFn = Callable[[str], Awaitable[str]]


def detect_greeting_openings(scripts: list[ScriptPair]) -> list[int]:
    """첫 슬라이드 이후 문두 인사말로 시작하는 슬라이드 인덱스를 찾는다."""
    targets: list[int] = []
    for slide_idx, text in scripts:
        if slide_idx == 0:
            continue
        if _GREETING_RE.search(text[:12]):
            targets.append(slide_idx)
    return targets


def detect_duplicate_openings(scripts: list[ScriptPair], head_chars: int = 18) -> list[int]:
    """정규화한 앞부분이 같은 도입부에서 첫 항목을 제외한 인덱스를 찾는다."""
    seen: dict[str, int] = {}
    duplicates: list[int] = []
    for slide_idx, text in scripts:
        key = _opening_key(text, head_chars)
        if key == "":
            continue
        if key in seen:
            duplicates.append(slide_idx)
            continue
        seen[key] = slide_idx
    return duplicates


def needs_cohesion_fix(scripts: list[ScriptPair]) -> list[int]:
    """인사 반복과 동일 도입부 중복을 합쳐 교정 대상 인덱스를 반환한다."""
    targets = set(detect_greeting_openings(scripts))
    targets.update(detect_duplicate_openings(scripts))
    return sorted(targets)


async def rewrite_openings(
    scripts: list[ScriptPair],
    target_idxs: list[int],
    topic: str,
    rewrite_fn: RewriteFn,
) -> dict[int, str]:
    """대상 슬라이드의 첫 문장만 재작성해 나머지 본문은 그대로 보존한다."""
    by_idx = dict(scripts)
    rewritten: dict[int, str] = {}
    for slide_idx in target_idxs:
        source = by_idx[slide_idx]
        intro, body = _split_first_sentence(source)
        prompt = _rewrite_prompt(slide_idx, intro, scripts, topic)
        replacement = _clean_rewrite(await rewrite_fn(prompt))
        rewritten[slide_idx] = f"{replacement}{_join_body(body)}"
    return rewritten


async def apply_cohesion(
    scripts: list[ScriptPair],
    topic: str,
    rewrite_fn: RewriteFn,
) -> list[ScriptPair]:
    """필요한 경우 도입부만 재작성한 대본 목록을 원래 순서로 돌려준다."""
    targets = needs_cohesion_fix(scripts)
    if not targets:
        return scripts
    rewritten = await rewrite_openings(scripts, targets, topic, rewrite_fn)
    return [(slide_idx, rewritten.get(slide_idx, text)) for slide_idx, text in scripts]


def _opening_key(text: str, head_chars: int) -> str:
    # 도입부 반복은 첫 한두 호흡에서 드러나므로 앞 N자만 비교해 본문 유사도를 건드리지 않는다.
    head = text.strip()[:head_chars]
    return _PUNCT_SPACE_RE.sub("", head).casefold()


def _split_first_sentence(text: str) -> tuple[str, str]:
    match = _SENTENCE_RE.match(text.strip())
    if match is None:
        return text.strip(), ""
    intro = match.group(0).strip()
    return intro, text.strip()[len(intro):].lstrip()


def _join_body(body: str) -> str:
    return f" {body}" if body else ""


def _rewrite_prompt(slide_idx: int, intro: str, scripts: list[ScriptPair], topic: str) -> str:
    openings = "\n".join(f"- slide {idx}: {_split_first_sentence(text)[0]}" for idx, text in scripts)
    return (
        f"topic={topic}\n"
        f"대상 slide_idx={slide_idx}\n"
        f"현재 도입 문장: {intro}\n"
        f"다른 슬라이드 도입부:\n{openings}\n"
        "위 도입 문장을 인사말 없이 직전 흐름을 잇는 자연스러운 한 문장으로 바꿔라. "
        "다른 슬라이드와 겹치지 않게 하고 존댓말을 유지한다. "
        "따옴표·번호·설명 없이 결과 문장만 출력한다."
    )


def _clean_rewrite(text: str) -> str:
    cleaned = text.strip().strip("\"'“”‘’")
    if cleaned == "":
        raise ValueError("재작성 도입 문장이 비어 있다.")
    return cleaned


__all__ = [
    "apply_cohesion",
    "detect_duplicate_openings",
    "detect_greeting_openings",
    "needs_cohesion_fix",
    "rewrite_openings",
]

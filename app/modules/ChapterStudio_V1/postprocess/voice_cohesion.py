# -*- coding: utf-8 -*-
"""슬라이드 음성대본 도입부 응집성 후처리.

plan-first 섹션 구조 지원:
- sections가 있는 경우 intro 슬롯 text만 재작성하고 나머지 슬롯은 불변.
- sections가 없는 레거시 경우 기존 첫 문장만 교정 동작을 유지한다.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

_GREETING_RE = re.compile(r"^\s*(?:안녕하세요|안녕\b|반갑습니다|반가워요|다들\s*안녕)")
# 스마트쿼트(U+201C–U+201F)를 문자 클래스에 포함해 도입부 정규화 시 따옴표 차이를 흡수한다.
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
    semaphore: asyncio.Semaphore | None = None,
) -> dict[int, str]:
    """대상 슬라이드의 첫 문장만 재작성해 나머지 본문은 그대로 보존한다.

    이 함수는 평탄화된 script_text(섹션이 join된 단일 문자열) 수준에서만 동작한다.
    첫 문장(보통 intro 도입부)만 교체하고 그 뒤 본문 전체는 그대로 잇는다. plan-first
    섹션 구조를 슬롯 경계까지 정밀하게 재작성하지는 않는다(현 구현은 script_text 평탄화
    기준). 응집성 교정 후 voice_cohesion_pass가 sections=None으로 리셋해 script_text를
    정본으로 삼는다.

    semaphore: Gemini genai API rate limit 대응. None이면 제한 없이 병렬 실행.
    슬라이드 수는 통상 10~15개로 소규모라 기본 unbounded gather로도 안전하지만,
    외부에서 세마포어를 주입하면 동시성을 추가로 제어할 수 있다.
    """
    by_idx = dict(scripts)

    async def _rewrite_one(slide_idx: int) -> tuple[int, str]:
        """단일 슬라이드 도입부를 재작성해 (slide_idx, 새 텍스트)를 반환한다."""
        source = by_idx[slide_idx]
        intro, body = _split_first_sentence(source)
        prompt = _rewrite_prompt(slide_idx, intro, scripts, topic)
        if semaphore is not None:
            async with semaphore:
                replacement = _clean_rewrite(await rewrite_fn(prompt))
        else:
            replacement = _clean_rewrite(await rewrite_fn(prompt))
        return slide_idx, f"{replacement}{_join_body(body)}"

    # 슬라이드별 재작성을 병렬로 실행해 직렬 대비 슬라이드 수만큼 단축한다.
    pairs = await asyncio.gather(*[_rewrite_one(idx) for idx in target_idxs])
    return dict(pairs)


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
    # 직선 따옴표와 스마트쿼트를 모두 벗겨 TTS에 따옴표가 잔류하지 않게 한다.
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

from __future__ import annotations

import asyncio
from typing import Protocol

from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.common.config import kanana_polish_enabled, kanana_polish_max_concurrency
from app.modules.ChapterStudio_V1.common.logging import logger
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload, GeneratedSlide, GeneratedVoiceScript
from app.modules.ChapterStudio_V1.pipeline.quality_inspection import (
    CJK_RE,
    QualityInspectionReport,
    apply_spelling_fixes,
    inspect_lesson,
    strip_cjk,
)
from app.modules.ChapterStudio_V1.postprocess.visual_renderers import render_visual_slide


class PolishConnector(Protocol):
    async def polish(self, text: str, *, tone_hint: str = "") -> str:
        """교정 커넥터가 필요한 최소 비동기 인터페이스다."""
        ...


async def inspect_and_polish_payload(payload: GeneratedLessonPayload, *, tone_hint: str = "") -> GeneratedLessonPayload:
    """규칙 기반 문제를 기록한 뒤, 플래그가 켜진 경우에만 Kanana2 교정을 적용한다."""
    report = inspect_lesson(
        [script.script_text for script in payload.voice_scripts],
        [slide.narration for slide in payload.slides if slide.narration],
    )
    _log_report(report)
    payload = _apply_deterministic_spelling_payload(payload)
    if kanana_polish_enabled():
        connector = registry.get_polish_connector()
        semaphore = asyncio.Semaphore(kanana_polish_max_concurrency())
        slides, voices = await asyncio.gather(
            _polish_slides(payload.slides, connector, semaphore, tone_hint),
            _polish_voices(payload.voice_scripts, connector, semaphore, tone_hint),
        )
        payload = _apply_deterministic_spelling_payload(
            payload.model_copy(update={"slides": slides, "voice_scripts": voices})
        )
    _log_remaining_cjk(payload)
    return payload


async def _polish_slides(
    slides: list[GeneratedSlide],
    connector: PolishConnector,
    semaphore: asyncio.Semaphore,
    tone_hint: str,
) -> list[GeneratedSlide]:
    tasks = [_polish_slide(slide, connector, semaphore, tone_hint) for slide in slides]
    return await asyncio.gather(*tasks)


async def _polish_voices(
    scripts: list[GeneratedVoiceScript],
    connector: PolishConnector,
    semaphore: asyncio.Semaphore,
    tone_hint: str,
) -> list[GeneratedVoiceScript]:
    tasks = [_polish_voice(script, connector, semaphore, tone_hint) for script in scripts]
    return await asyncio.gather(*tasks)


async def _polish_slide(
    slide: GeneratedSlide,
    connector: PolishConnector,
    semaphore: asyncio.Semaphore,
    tone_hint: str,
) -> GeneratedSlide:
    if not slide.narration:
        return slide
    polished = await _polish_text(connector, slide.narration, semaphore, tone_hint, f"slide:{slide.slide_idx}")
    if polished == slide.narration:
        return slide
    update = {"narration": polished, "html": _rerender_slide_html(slide, polished)}
    if slide.focus == slide.narration:
        update["focus"] = polished
    return slide.model_copy(update=update)


async def _polish_voice(
    script: GeneratedVoiceScript,
    connector: PolishConnector,
    semaphore: asyncio.Semaphore,
    tone_hint: str,
) -> GeneratedVoiceScript:
    polished = await _polish_text(connector, script.script_text, semaphore, tone_hint, f"voice:{script.slide_idx}")
    if polished == script.script_text:
        return script
    return script.model_copy(update={"script_text": polished})


async def _polish_text(
    connector: PolishConnector,
    text: str,
    semaphore: asyncio.Semaphore,
    tone_hint: str,
    label: str,
) -> str:
    try:
        async with semaphore:
            return await connector.polish(text, tone_hint=tone_hint)
    except (RuntimeError, TypeError, ValueError, asyncio.TimeoutError) as exc:
        logger.warning("Kanana2 polish pass: {} 교정 실패로 원문 유지: {}", label, exc)
        return text


def _apply_deterministic_spelling_payload(payload: GeneratedLessonPayload) -> GeneratedLessonPayload:
    """Modal 호출 없이 슬라이드와 음성대본의 확정 표기·CJK 누출을 보정한다."""
    slides = [_apply_deterministic_spelling_slide(slide) for slide in payload.slides]
    voices = [_apply_deterministic_spelling_voice(script) for script in payload.voice_scripts]
    if slides == payload.slides and voices == payload.voice_scripts:
        return payload
    return payload.model_copy(update={"slides": slides, "voice_scripts": voices})


def _apply_deterministic_spelling_slide(slide: GeneratedSlide) -> GeneratedSlide:
    if not slide.narration:
        html = strip_cjk(slide.html)
        return slide if html == slide.html else slide.model_copy(update={"html": html})
    narration = _deterministic_text_fixes(slide.narration)
    html_source = _rerender_slide_html(slide, narration) if narration != slide.narration else slide.html
    html = strip_cjk(html_source)
    if narration == slide.narration and html == slide.html:
        return slide
    update = {"narration": narration, "html": html}
    if slide.focus == slide.narration:
        update["focus"] = narration
    return slide.model_copy(update=update)


def _apply_deterministic_spelling_voice(script: GeneratedVoiceScript) -> GeneratedVoiceScript:
    script_text = _deterministic_text_fixes(script.script_text)
    if script_text == script.script_text:
        return script
    return script.model_copy(update={"script_text": script_text})


def _deterministic_text_fixes(text: str) -> str:
    """확정 표기 치환 뒤 CJK 문자를 제거해 LLM 토글과 무관한 결과를 만든다."""
    return strip_cjk(apply_spelling_fixes(text))


def _rerender_slide_html(slide: GeneratedSlide, narration: str) -> str:
    visual_type = slide.visual.get("type")
    data = slide.visual.get("data")
    if isinstance(visual_type, str) and isinstance(data, dict):
        return render_visual_slide(slide.title, narration, visual_type, data)
    if slide.narration and slide.narration in slide.html:
        return slide.html.replace(slide.narration, narration)
    return slide.html


def _log_report(report: QualityInspectionReport) -> None:
    if report.total_issues == 0:
        logger.info("Kanana2 quality inspection: issue 없음")
        return
    summary = [
        f"{item.source}:{item.index}:{issue.kind}:{issue.fragment}"
        for item in report.items
        for issue in item.issues
    ]
    logger.warning(
        "Kanana2 quality inspection: issue {}건, duplicate_intro_group {}건 — {}",
        report.total_issues,
        len(report.duplicate_intro_groups),
        " | ".join(summary[:30]),
    )


def _log_remaining_cjk(payload: GeneratedLessonPayload) -> None:
    paths = _remaining_cjk_paths(payload.model_dump(), "payload")
    if paths:
        logger.warning(
            "Kanana2 quality inspection: CJK 잔존 {}건 — {}",
            len(paths),
            " | ".join(paths[:30]),
        )


def _remaining_cjk_paths(value: object, path: str) -> list[str]:
    if isinstance(value, str):
        match = CJK_RE.search(value)
        return [f"{path}:{match.group()}"] if match else []
    if isinstance(value, dict):
        return [
            found
            for key, nested in value.items()
            for found in _remaining_cjk_paths(nested, f"{path}.{key}")
        ]
    if isinstance(value, list):
        return [
            found
            for index, nested in enumerate(value)
            for found in _remaining_cjk_paths(nested, f"{path}[{index}]")
        ]
    return []


__all__ = ["inspect_and_polish_payload"]

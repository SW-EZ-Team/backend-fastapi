"""음성대본 도입부 응집성 패스를 payload 단계에 적용한다."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.common.config import voice_cohesion_enabled
from app.modules.ChapterStudio_V1.common.logging import logger
from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload, GeneratedVoiceScript
from app.modules.ChapterStudio_V1.postprocess.voice_cohesion import (
    apply_cohesion,
    needs_cohesion_fix,
)

_MAX_TOKENS = 220


async def apply_voice_cohesion_payload(
    payload: GeneratedLessonPayload,
    topic: str,
) -> GeneratedLessonPayload:
    """검증된 payload의 voice_scripts 도입부만 필요 시 재작성한다."""
    scripts = [(item.slide_idx, item.script_text) for item in payload.voice_scripts]
    target_idxs = needs_cohesion_fix(scripts)
    if not target_idxs:
        return payload
    logger.warning("voice_cohesion: 도입부 교정 대상 slide_idx={}", target_idxs)
    if not voice_cohesion_enabled():
        logger.info("voice_cohesion: VOICE_COHESION_ENABLED=false → 탐지만 수행하고 원본 유지")
        return payload
    return await _rewrite_payload(payload, scripts, target_idxs, topic)


async def _rewrite_payload(
    payload: GeneratedLessonPayload,
    scripts: list[tuple[int, str]],
    target_idxs: list[int],
    topic: str,
) -> GeneratedLessonPayload:
    connector = _load_connector()
    try:
        fixed_pairs = await apply_cohesion(scripts, topic, _rewrite_fn(connector))
    except (ConnectorError, RuntimeError, ValueError) as exc:
        logger.warning("voice_cohesion: 재작성 실패 → 원본 유지({})", exc)
        return payload
    return _replace_voice_scripts(payload, dict(fixed_pairs), set(target_idxs))


def _load_connector() -> AIConnector:
    try:
        return registry.get_text_connector()
    except (ConnectorError, RuntimeError, ImportError) as exc:
        logger.warning("voice_cohesion: 텍스트 커넥터 준비 실패 → 원본 유지({})", exc)
        raise RuntimeError("voice cohesion 커넥터를 준비하지 못했다.") from exc


def _rewrite_fn(connector: AIConnector) -> Callable[[str], Awaitable[str]]:
    async def rewrite(prompt: str) -> str:
        request = ChapterAIRequest(
            system="너는 한국어 강의 음성대본의 첫 문장만 고치는 편집자다. 결과 문장만 출력한다.",
            user=prompt,
            max_tokens=_MAX_TOKENS,
            temperature=0.2,
            extra={"schema": "voice_cohesion", "voice_cohesion": True},
        )
        response = await connector.generate(request)
        return response.text

    return rewrite


def _replace_voice_scripts(
    payload: GeneratedLessonPayload,
    fixed_by_idx: dict[int, str],
    target_idxs: set[int],
) -> GeneratedLessonPayload:
    voices = [
        _voice_with_text(item, fixed_by_idx[item.slide_idx]) if item.slide_idx in target_idxs else item
        for item in payload.voice_scripts
    ]
    return payload.model_copy(update={"voice_scripts": voices})


def _voice_with_text(item: GeneratedVoiceScript, script_text: str) -> GeneratedVoiceScript:
    # cohesion 재작성은 도입 첫 문장만 교체하므로 sections는 무효화해 script_text 우선으로 둔다.
    return GeneratedVoiceScript(slide_idx=item.slide_idx, script_text=script_text, sections=None)


__all__ = ["apply_voice_cohesion_payload"]

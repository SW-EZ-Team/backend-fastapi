"""커넥터 레지스트리 퍼사드.

각 도메인 서브레지스트리(_registry_*.py)에서 게터 함수를 재수출한다.
외부 코드는 이 파일만 import 하면 되고, 서브레지스트리 파일을 직접 참조하지 않는다.

도메인별 파일 구조:
  _registry_text.py    — 텍스트 생성 (CONNECTORS, get_connector, get_text_connector)
  _registry_asr.py     — ASR (ASR_CONNECTORS, get_asr_connector)
  _registry_denoise.py — 노이즈 제거 (DENOISE_CONNECTORS, get_denoise_connector)
  _registry_tts.py     — TTS (TTS_CONNECTORS, get_tts_connector)
  _registry_ocr.py     — OCR (OCR_CONNECTORS, get_ocr_connector)
  _registry_postproc.py — 후처리 (POSTPROC_CONNECTORS, get_postproc_connector)
  _registry_voice.py   — 음성 네이티브 (VOICE_CONNECTORS, get_voice_connector)
"""
from __future__ import annotations

import logging

from .base import PostprocConnector
from .errors import ModelNotFoundError
from ._registry_asr import get_asr_connector
from ._registry_denoise import get_denoise_connector
from ._registry_ocr import _resolve_ocr_name, get_ocr_connector
from ._registry_postproc import get_postproc_connector
from ._registry_text import get_connector, get_text_connector
from ._registry_tts import get_tts_connector
from ._registry_voice import get_voice_connector

_LOG = logging.getLogger(__name__)

# 후처리를 건너뛰는 OCR 모델 목록 — Nemotron-OCR-v2 는 글자 추출만 수행하고 정확도는
# 하위 LLM 이 커버하는 전략이라 후처리를 생략한다. 그 외 OCR 경로는 후처리를 유지한다.
_POSTPROC_BYPASS_OCR = frozenset({"nemotron-ocr-v2"})


def get_textbook_ocr_pipeline(
    ocr_key: str | None = None,
    postproc_key: str | None = None,
) -> "TextbookOCRPipeline":
    """교재 OCR 파이프라인 factory.

    ocr_key: OCR_CONNECTORS 키 (기본값: AI_MODEL_OCR/AI_OCR → 'gemini-ocr')
    postproc_key: POSTPROC_CONNECTORS 키 (기본값: AI_MODEL_POSTPROC → 'kanana2-modal')
    후처리 커넥터 미등록 시 None 으로 주입 — 파이프라인은 후처리 건너뛰고 동작한다.

    OCR 모델이 `_POSTPROC_BYPASS_OCR` 에 속하면(현재: nemotron-ocr-v2) 후처리는
    명시적으로 건너뛴다 — Nemotron 경로는 후처리 없이 LLM 단계로 바로 넘기는 설계라서다.
    그 외 OCR 모델은 Kanana-2 Modal 후처리 커넥터로 교정한다.
    """
    # 지연 import — 순환 참조 방지 (pipelines → registry → pipelines)
    from .pipelines.textbook_ocr_pipeline import TextbookOCRPipeline

    resolved_ocr_name = _resolve_ocr_name(ocr_key)
    ocr_connector = get_ocr_connector(resolved_ocr_name)

    postproc_connector: PostprocConnector | None
    if resolved_ocr_name in _POSTPROC_BYPASS_OCR:
        _LOG.info(
            "OCR 모델 %s 은 후처리 우회 대상 — 교재 파이프라인에 postproc 을 주입하지 않습니다.",
            resolved_ocr_name,
        )
        postproc_connector = None
    else:
        try:
            postproc_connector = get_postproc_connector(postproc_key)
        except ModelNotFoundError:
            _LOG.info("후처리 커넥터 미등록 — 교재 OCR 파이프라인이 후처리 없이 실행됩니다.")
            postproc_connector = None
    return TextbookOCRPipeline(
        ocr_connector=ocr_connector,
        postproc_connector=postproc_connector,
    )


__all__ = [
    "get_connector",
    "get_text_connector",
    "get_asr_connector",
    "get_denoise_connector",
    "get_tts_connector",
    "get_ocr_connector",
    "get_postproc_connector",
    "get_voice_connector",
    "get_textbook_ocr_pipeline",
]

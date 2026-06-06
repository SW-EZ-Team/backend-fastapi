"""후처리(Postproc) 커넥터 서브레지스트리.

POSTPROC_CONNECTORS dict 와 get_postproc_connector 팩토리를 담는다.
외부 코드는 이 파일을 직접 import 하지 않고 ai_connectors.registry 를 사용한다.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from .base import PostprocConnector
from .errors import ModelNotFoundError

_LOG = logging.getLogger(__name__)

# 후처리(postproc) 커넥터 팩토리 맵 (PostprocConnector 구현체)
POSTPROC_CONNECTORS: dict[str, Callable[[], PostprocConnector]] = {}

# 활성/배포 모두 클라우드 Kanana-2 Modal 후처리 커넥터를 사용한다.
# MLX 로컬 후처리(kanana2-mlx)는 프로덕션 전환으로 제거됐다.
try:
    from .postproc.kanana2_modal_connector import Kanana2ModalConnector
    POSTPROC_CONNECTORS["kanana2-modal"] = lambda: Kanana2ModalConnector()
except ImportError as _kanana_modal_import_err:
    _LOG.warning(
        "Kanana-2 Modal 후처리 커넥터 등록 건너뜀 (ImportError: %s).",
        _kanana_modal_import_err,
    )


def get_postproc_connector(model_name: str | None = None) -> PostprocConnector:
    """.env 의 AI_MODEL_POSTPROC 또는 명시된 model_name 으로 후처리 커넥터 반환."""
    name = model_name or os.getenv("AI_MODEL_POSTPROC", "kanana2-modal")
    if name not in POSTPROC_CONNECTORS:
        raise ModelNotFoundError(
            f"Unknown postproc model: {name}. "
            f"Registered: {list(POSTPROC_CONNECTORS.keys())}. "
            f"AI_MODEL_POSTPROC 환경변수와 venv 활성화 여부를 확인하세요.",
        )
    return POSTPROC_CONNECTORS[name]()

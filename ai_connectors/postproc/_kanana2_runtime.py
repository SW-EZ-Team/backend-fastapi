"""Kanana MLX 모델 로드 + 추론 런타임 아톰.

mlx_lm.load 는 1~2초가 걸리는 블로킹 호출이므로 프로세스당 1회만 수행한다.
ASR 싱글턴과 동일한 패턴(클래스 레벨 캐시 + asyncio.Lock) 을 쓰려 했으나,
이 모듈은 런타임 저장소(dict) 만 책임지고 락/async 는 상위 커넥터가 관리해
아톰 규약 (30 라인) 을 준수한다.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

# TYPE_CHECKING 가드 — `from __future__ import annotations` 덕분에 런타임엔 참조 없음.
# 덕분에 mlx_lm 이 Metal 을 초기화하지 않고도 정적 타입 체커에 정확한 타입을 제공한다.
if TYPE_CHECKING:
    from mlx.nn import Module as MlxModule
    from mlx_lm.tokenizer_utils import TokenizerWrapper

_LOG = logging.getLogger(__name__)


class _RuntimeState(TypedDict):
    """싱글턴 상태 — model/tokenizer 는 미로드 시 None."""

    model: MlxModule | None
    tok: TokenizerWrapper | None
    model_id: str | None


# 모듈 레벨 싱글턴 — 여러 인스턴스가 생성되어도 모델은 한 벌만 상주
_state: _RuntimeState = {"model": None, "tok": None, "model_id": None}


def is_loaded() -> bool:
    """모델·토크나이저가 로드되어 있는지 여부."""
    return _state["model"] is not None and _state["tok"] is not None


def get_loaded() -> tuple[MlxModule, TokenizerWrapper, str]:
    """로드된 (model, tokenizer, model_id) 를 반환한다. 미로드면 RuntimeError."""
    model = _state["model"]
    tok = _state["tok"]
    model_id = _state["model_id"]
    if model is None or tok is None or model_id is None:
        raise RuntimeError("Kanana MLX 런타임이 아직 로드되지 않음 — load() 선행 필요")
    return model, tok, model_id


def load(model_id: str) -> tuple[MlxModule, TokenizerWrapper]:
    """최초 1회 모델 로드. 이후 호출은 기존 싱글턴을 반환한다.

    mlx_lm lazy import — 상위 패키지 임포트만으로 Metal 디바이스가
    초기화되는 것을 막기 위해 여기서만 import 한다.
    """
    cached = _state["model"]
    cached_tok = _state["tok"]
    if cached is not None and cached_tok is not None and _state["model_id"] == model_id:
        return cached, cached_tok
    _LOG.info("Kanana MLX 모델 Cold Load 시작: %s", model_id)
    from mlx_lm import load as mlx_load  # lazy import

    model, tok = mlx_load(model_id)
    _state["model"] = model
    _state["tok"] = tok
    _state["model_id"] = model_id
    _LOG.info("Kanana MLX 모델 로드 완료: %s", model_id)
    return model, tok


def run_generate(
    prompt_text: str,
    max_tokens: int,
) -> str:
    """블로킹 mlx_lm.generate 호출 — 호출자가 asyncio.to_thread 로 래핑해야 한다."""
    model, tok, _model_id = get_loaded()
    from mlx_lm import generate  # lazy import

    # verbose=False, 온도 기본값(샘플러 조절 없이 greedy 에 가까운 기본값 사용)
    return generate(
        model,
        tok,
        prompt=prompt_text,
        max_tokens=max_tokens,
        verbose=False,
    )

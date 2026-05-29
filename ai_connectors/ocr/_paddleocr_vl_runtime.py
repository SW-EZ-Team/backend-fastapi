"""PaddleOCR-VL MLX 모델 로드 + 추론 런타임 아톰 모듈.

모델은 최초 1회만 로드하고 `functools.lru_cache` 로 싱글턴 재사용한다.
mlx_vlm.generate() 는 블로킹 호출이므로, 이 모듈을 asyncio.to_thread 로 감싸야 한다.
이미지 입력은 파일 경로(str)만 허용되므로, 바이트 입력은 호출자가 임시 파일로 변환해야 한다.

SRP 분리:
  - 상태 관리(_load_once): 모델/프로세서/설정 번들을 캐시
  - 경로 해석(_resolve_model_id): 환경변수 기반 repo id/경로 결정
  - 추론 실행(run_inference): 프롬프트 조립 + generate 호출
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any

from common.config import get_paddleocr_vl_mlx_model_path

from ..errors import ModelLoadError

_LOG = logging.getLogger(__name__)

# VLM 에 bbox 좌표를 포함하도록 유도하는 프롬프트.
# 한국어 프롬프트가 page_03 반복 붕괴를 방지하는 효과가 실험적으로 확인됨.
_OCR_PROMPT = "이미지에서 모든 텍스트를 정확히 추출해주세요."


# WORKAROUND: docs/workarounds.md#mlx_vlm-미타입-라이브러리 참조
# mlx_vlm 이 py.typed 를 제공하지 않아 model/processor/config 를
# 구조적으로 좁힐 방법이 없다. 번들 외부에선 속성 접근을 하지 않고
# mlx_vlm.generate() 에 positional 로만 전달하도록 캡슐화한다.
@dataclass(frozen=True)
class _MlxModelBundle:
    """mlx_vlm 로드 결과를 한 데 묶은 싱글턴 번들."""

    model: Any
    processor: Any
    config: dict[str, Any]


def _resolve_model_id() -> str:
    """환경변수(PADDLEOCR_VL_MLX_MODEL_PATH) 또는 기본 repo id 를 반환한다."""
    # .env 에 경로가 있으면 common/config 가 절대경로로 치환해서 반환한다.
    return get_paddleocr_vl_mlx_model_path()


@functools.lru_cache(maxsize=1)
def _load_once() -> _MlxModelBundle:
    """최초 1회 MLX 모델/프로세서/설정을 로드하고 캐시한다.

    lru_cache 덕분에 `global` 선언이나 None 체크가 필요 없다.
    재호출 시에는 동일 번들이 즉시 반환된다.
    로드 실패는 ModelLoadError 로 정규화해 커넥터 계층까지 전달한다.
    """
    model_id = _resolve_model_id()
    _LOG.info("PaddleOCR-VL MLX 모델 Cold Load 시작: %s", model_id)
    try:
        # 무거운 의존을 지연 임포트해 모듈 임포트 비용을 낮춘다.
        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        model, processor = load(model_id)
        config = load_config(model_id)
    except Exception as exc:  # mlx_vlm 로드 실패 — 공용 예외로 변환
        raise ModelLoadError(f"PaddleOCR-VL 로드 실패: {exc}") from exc

    _LOG.info("PaddleOCR-VL MLX 모델 로드 완료")
    return _MlxModelBundle(model=model, processor=processor, config=config)


def run_inference(image_path: str, max_tokens: int = 2048) -> str:
    """단일 이미지에 대해 VLM 추론을 실행하고 raw 텍스트를 반환한다.

    image_path: 로컬 파일 경로 (mlx_vlm.generate 는 파일 경로만 허용)
    max_tokens: 생성 최대 토큰 수 (기본 2048)
    반환값: 모델 raw 출력 문자열
    """
    bundle = _load_once()
    # 생성 관련 심볼도 지연 임포트 — 테스트 환경에서 mlx_vlm 미설치 시 임포트만으로 실패하지 않도록.
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    formatted = apply_chat_template(
        bundle.processor, bundle.config, _OCR_PROMPT, num_images=1
    )
    result = generate(
        model=bundle.model,
        processor=bundle.processor,
        prompt=formatted,
        image=[image_path],
        max_tokens=max_tokens,
        temperature=0.0,
        verbose=False,
    )
    return result.text

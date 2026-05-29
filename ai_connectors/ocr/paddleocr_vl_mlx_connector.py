"""PaddleOCR-VL-1.5-4bit MLX OCRConnector 구현.

OCRConnector Protocol을 준수하며, 이미지 바이트를 임시 파일로 브릿지한 후
mlx_vlm.generate()에 전달한다. 추론은 asyncio.to_thread로 감싸 이벤트 루프를 보호한다.
반복 붕괴 감지 + LOC 토큰 파서를 원자 모듈에서 가져와 조합한다.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path

from PIL import Image

from ..errors import AIConnectorError, InferenceError, ModelLoadError
from ..schemas import OCRDetection, OCRRequest, OCRResponse
from ._paddleocr_vl_loop_detect import is_loop_collapse
from ._paddleocr_vl_parse import parse_vl_output
from ._paddleocr_vl_runtime import run_inference

_LOG = logging.getLogger(__name__)

# 버전 식별자 — OCRResponse.model_version 에 사용
_MODEL_VERSION = "paddleocr-vl-mlx"


def _image_size_from_bytes(image_bytes: bytes) -> tuple[int, int]:
    """이미지 바이트에서 (width, height) 픽셀 크기를 읽는다."""
    import io
    with Image.open(io.BytesIO(image_bytes)) as im:
        return im.size  # (width, height)


def _write_temp_image(image_bytes: bytes) -> str:
    """이미지 바이트를 임시 PNG 파일로 저장하고 경로를 반환한다.

    mlx_vlm.generate()가 파일 경로만 허용하므로 브릿지 역할을 한다.
    호출자가 컨텍스트 관리자로 정리할 필요 없이 경로 반환 후 사용 완료 시 삭제한다.
    """
    suffix = ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(image_bytes)
        return f.name


def _sync_recognize(image_bytes: bytes) -> tuple[str, int, int]:
    """동기 추론 파이프라인 — asyncio.to_thread 내부에서 실행된다.

    반환: (raw_text, width, height)
    """
    tmp_path: str | None = None
    try:
        width, height = _image_size_from_bytes(image_bytes)
        tmp_path = _write_temp_image(image_bytes)
        raw_text = run_inference(tmp_path)
        return raw_text, width, height
    except Exception as exc:
        raise InferenceError(f"PaddleOCR-VL 추론 실패: {exc}") from exc
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


class PaddleOCRVLMlxConnector:
    """PaddleOCR-VL-1.5 MLX 4bit OCRConnector 구현체.

    싱글턴 모델(_paddleocr_vl_runtime)을 재사용하므로 인스턴스는 여러 번 생성해도 무방하다.
    """

    name: str = _MODEL_VERSION

    async def recognize(self, req: OCRRequest) -> OCRResponse:
        """이미지 바이트를 받아 VLM 기반 텍스트 인식 결과를 반환한다."""
        t0 = time.perf_counter()
        try:
            raw_text, width, height = await asyncio.to_thread(
                _sync_recognize, req.image_bytes
            )
        except InferenceError:
            raise
        except Exception as exc:
            raise AIConnectorError(f"PaddleOCR-VL recognize 실패: {exc}") from exc

        # 반복 붕괴 감지 — 붕괴 시 경고 로그 후 부분 결과를 반환한다.
        if is_loop_collapse(raw_text):
            _LOG.warning(
                "PaddleOCR-VL 반복 붕괴 감지. 출력 앞부분만 사용합니다. "
                "raw_text 길이=%d",
                len(raw_text),
            )
            # 붕괴 구간 이전 라인만 취한다 (연속 중복이 시작되기 전까지).
            raw_text = _truncate_before_loop(raw_text)

        detections: list[OCRDetection] = parse_vl_output(raw_text, width, height)
        full_text = "\n".join(d.text for d in detections)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return OCRResponse(
            detections=detections,
            text=full_text,
            model_version=_MODEL_VERSION,
            latency_ms=latency_ms,
            page_count=1,
        )

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그를 반환한다."""
        return feature in {"korean", "layout_analysis", "bbox", "mlx"}


def _truncate_before_loop(text: str, threshold: int = 6) -> str:
    """반복이 시작되기 직전까지의 텍스트만 반환한다."""
    lines = text.splitlines()
    run = 1
    for i in range(1, len(lines)):
        if lines[i].strip() == lines[i - 1].strip() and lines[i].strip():
            run += 1
            if run >= threshold:
                # 반복 시작 직전 인덱스를 구한다
                return "\n".join(lines[: i - threshold + 2])
        else:
            run = 1
    return text

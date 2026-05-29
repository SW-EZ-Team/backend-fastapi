"""교재 OCR 파이프라인 오케스트레이터.

체인: PDF 래스터화 → PaddleOCR-VL MLX OCR → Kanana-2 후처리 → 구조화 출력.
DI 기반 — OCR 커넥터와 후처리 커넥터를 외부에서 주입받는다.
오케스트레이터는 인프라를 직접 import 하지 않는다 (SRP).

OUT: OCRPipelineResult 단 하나.
"""
from __future__ import annotations

import time

from ai_connectors.ocr.pdf_rasterizer import rasterize_pdf
from ai_connectors.pipeline_schemas import OCRPipelineResult

from ._pipeline_helpers import aggregate_plain_text
from ._pipeline_runners import run_ocr_pages, run_postproc
from ._postproc_protocol import PostprocConnector


class TextbookOCRPipeline:
    """교재 OCR 파이프라인.

    ocr_connector: OCRConnector — PaddleOCR-VL MLX (registry에서 주입)
    postproc_connector: PostprocConnector | None — Kanana-2 (미완료 시 None)
    """

    def __init__(
        self,
        ocr_connector: object,
        postproc_connector: PostprocConnector | None = None,
    ) -> None:
        # DI: 외부에서 커넥터 인스턴스를 받아 저장한다
        self._ocr = ocr_connector
        self._postproc = postproc_connector

    async def run(self, pdf_bytes: bytes) -> OCRPipelineResult:
        """PDF 바이트를 받아 OCRPipelineResult 를 반환한다."""
        timings: dict[str, float] = {}

        t0 = time.perf_counter()
        png_pages, rasterizer_backend = rasterize_pdf(pdf_bytes, dpi=300)
        timings["raster_ms"] = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        page_results, ocr_model = await run_ocr_pages(self._ocr, png_pages)
        timings["ocr_ms"] = (time.perf_counter() - t1) * 1000.0

        raw_plain = aggregate_plain_text(page_results)

        t2 = time.perf_counter()
        plain_text, corrections, postproc_model = await run_postproc(
            self._postproc, raw_plain
        )
        timings["postproc_ms"] = (time.perf_counter() - t2) * 1000.0

        return OCRPipelineResult(
            plain_text=plain_text,
            pages=page_results,
            corrections=corrections,
            timings=timings,
            rasterizer_backend=rasterizer_backend,
            ocr_model=ocr_model,
            postproc_model=postproc_model,
        )

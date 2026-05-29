"""PDF 래스터화 모듈.

lib-rust/ 폴더는 CLAUDE.md Scope Boundary Rules 에 따라 LOCKED 임.
여기서는 Python-side 호출 skeleton 만 작성한다.

우선순위:
  1. lib_rust_rasterize 휠이 설치되어 있으면 Rust(PyO3) 경로로 처리한다.
     (pdfium 기반, 300 DPI, < 200ms/page — 성능 목표: paddleocr_onnx_sourcing.md §9)
  2. 설치되지 않은 경우(로컬 샌드박스 단계) pypdfium2 로 fallback 처리한다.
     (Apache 2.0 / BSD — PyMuPDF/AGPL-3.0 은 회피 결정, ocr_paddleocr_performance.md §라이선스)
"""
from __future__ import annotations

import io
import logging
from typing import Literal

# stdlib logging 사용 — 어떤 백엔드가 활성화됐는지 INFO 로 기록
_LOG = logging.getLogger(__name__)

# 래스터화 백엔드 리터럴 타입 — 라우터가 X-Rasterizer-Backend 헤더에 노출한다
RasterizerBackend = Literal["lib-rust", "pypdfium2"]


def _rasterize_with_rust(pdf_bytes: bytes, dpi: int) -> list[bytes]:
    """lib-rust PyO3 휠 경로로 PDF 래스터화.

    lib_rust_rasterize.rasterize_pdf() 는 bytes → list[bytes] 를 반환한다.
    각 원소는 PNG 바이트 (한 페이지 = 하나의 PNG).
    이 함수는 ImportError 가 전파되면 호출부에서 fallback 분기로 넘어간다.
    """
    # 런타임 조건부 임포트 — 휠 미설치 시 ImportError 를 호출부로 전파해 fallback 전환
    import lib_rust_rasterize as rust_raster

    # Rust 측 인터페이스: rasterize_pdf(pdf_bytes: bytes, dpi: int) -> list[bytes]
    return rust_raster.rasterize_pdf(pdf_bytes, dpi=dpi)


def _rasterize_with_pypdfium2(pdf_bytes: bytes, dpi: int) -> list[bytes]:
    """pypdfium2 Python fallback 경로로 PDF 래스터화.

    pypdfium2 는 Apache 2.0 / BSD 라이선스로 상업 이용 허용.
    lib-rust 휠이 없는 로컬 샌드박스 단계에서 동작을 보장한다.
    """
    # 런타임 조건부 임포트 — 샌드박스에서만 사용하는 fallback 라이브러리
    import pypdfium2 as pdfium

    scale = dpi / 72.0  # pypdfium2 는 72 DPI 기준 배율로 렌더링

    doc = pdfium.PdfDocument(pdf_bytes)
    result: list[bytes] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        bitmap = page.render(scale=scale, rotation=0)
        pil_image = bitmap.to_pil()
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        result.append(buf.getvalue())

    return result


def rasterize_pdf(pdf_bytes: bytes, dpi: int = 300) -> tuple[list[bytes], RasterizerBackend]:
    """PDF 바이트를 페이지별 PNG 바이트 목록으로 래스터화한다.

    반환값:
        (png_pages, backend)
        - png_pages: 페이지별 PNG 바이트 목록
        - backend: 실제로 사용된 백엔드 식별자 ('lib-rust' 또는 'pypdfium2')

    라우터가 backend 값을 X-Rasterizer-Backend 응답 헤더로 노출한다.
    """
    if not pdf_bytes:
        raise ValueError("PDF 바이트가 비어있습니다.")

    # lib-rust PyO3 휠 우선 시도 — 설치돼 있으면 이 경로가 빠르고 정확하다
    try:
        pages = _rasterize_with_rust(pdf_bytes, dpi)
        _LOG.info(
            "PDF 래스터화: lib-rust PyO3 경로 사용 (dpi=%d, pages=%d)",
            dpi,
            len(pages),
        )
        return pages, "lib-rust"
    except ImportError:
        # 샌드박스 단계에서는 lib-rust 휠 미설치 — pypdfium2 fallback 으로 전환
        _LOG.info(
            "lib_rust_rasterize 미설치 — pypdfium2 fallback 으로 전환 (dpi=%d)",
            dpi,
        )

    pages = _rasterize_with_pypdfium2(pdf_bytes, dpi)
    _LOG.info(
        "PDF 래스터화: pypdfium2 경로 사용 (dpi=%d, pages=%d)",
        dpi,
        len(pages),
    )
    return pages, "pypdfium2"

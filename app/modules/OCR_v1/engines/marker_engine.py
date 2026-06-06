"""Marker 기반 OCREngine 구현체.

marker-pdf 패키지의 동기 API를 asyncio.to_thread로 감싸
이벤트 루프 블로킹 없이 고품질 PDF 추출을 수행한다.
Born-Digital PDF와 스캔 PDF 모두 처리 가능하며,
use_llm 플래그로 LLM 사후 교정을 선택적으로 활성화할 수 있다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path

from ..config import marker_timeout_sec
from ..schemas import PageExtraction

_LOG = logging.getLogger(__name__)

# Marker 임포트 — 미설치 환경에서도 모듈 로드가 가능하도록 가용성만 사전 확인
# 실제 import는 _run_marker 내부에서 필요 시점에 수행한다
try:
    # marker-pdf 패키지는 공식 타입 스텁(.pyi)을 제공하지 않는 선택적 라이브러리다.
    # 스텁 부재는 pyproject.toml의 mypy.overrides(marker.*)에서 프로젝트 수준으로 허용한다.
    # 가용성 확인만이 목적이므로 실제 import는 _run_marker 내부에서 수행한다.
    import marker.converters.pdf
    _MARKER_AVAILABLE = True
except ImportError:
    try:
        import marker.convert
        _MARKER_AVAILABLE = True
    except ImportError:
        _MARKER_AVAILABLE = False
        _LOG.warning("marker-pdf 패키지가 설치되지 않았습니다. MarkerEngine 비활성화.")


def _tables_from_md(md: str) -> list[dict]:
    """마크다운에서 파이프 테이블 블록을 추출한다."""
    lines = md.splitlines()
    tables: list[dict] = []
    current: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            current.append(line)
        else:
            if len(current) >= 2:
                tables.append({"md": "\n".join(current), "json": {}})
            current = []
    if len(current) >= 2:
        tables.append({"md": "\n".join(current), "json": {}})
    return tables


def _formulas_from_md(md: str) -> list[str]:
    """마크다운에서 LaTeX 수식($$ ... $$ 및 $ ... $)을 추출한다."""
    out: list[str] = []
    for m in re.finditer(r"\$\$(.+?)\$\$", md, re.DOTALL):
        out.append(m.group(1).strip())
    for m in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", md):
        out.append(m.group(1).strip())
    return out


def _make_page(idx: int, md: str, llm_corrected: bool) -> PageExtraction:
    """단일 페이지 PageExtraction을 생성하는 헬퍼."""
    return PageExtraction(
        page_num=idx + 1,
        markdown=md,
        tables=_tables_from_md(md),
        formulas=_formulas_from_md(md),
        engine="marker",
        llm_corrected=llm_corrected,
    )


class MarkerEngine:
    """Marker PDF 변환기를 래핑한 OCREngine 구현체.

    싱글턴 모델 딕셔너리를 캐싱하여 첫 호출 이후 로드 오버헤드를 제거한다.
    """

    name: str = "marker"

    def __init__(self) -> None:
        self._model_dict: dict | None = None
        self._lock = asyncio.Lock()

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그를 반환한다."""
        return feature in {"pdf", "markdown", "ocr", "llm_correction", "tables", "formulas"}

    async def extract(
        self,
        pdf_bytes: bytes,
        pages: list[int] | None = None,
        force_ocr: bool = False,
        use_llm: bool = False,
    ) -> list[PageExtraction]:
        """PDF 바이트를 받아 페이지별 추출 결과를 반환한다."""
        if not _MARKER_AVAILABLE:
            raise RuntimeError("marker-pdf 패키지 미설치 — MarkerEngine 사용 불가.")
        timeout = marker_timeout_sec()
        return await asyncio.wait_for(
            asyncio.to_thread(self._extract_sync, pdf_bytes, pages, force_ocr, use_llm),
            timeout=timeout,
        )

    def _extract_sync(
        self,
        pdf_bytes: bytes,
        pages: list[int] | None,
        force_ocr: bool,
        use_llm: bool,
    ) -> list[PageExtraction]:
        """동기 래퍼 — Marker는 동기 API이므로 별도 스레드에서 실행된다."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(pdf_bytes)
            tmp_path = Path(f.name)
        try:
            return self._run_marker(tmp_path, use_llm)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _run_marker(self, pdf_path: Path, use_llm: bool) -> list[PageExtraction]:
        """Marker 변환을 실행하고 PageExtraction 리스트로 정규화한다."""
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict

            if self._model_dict is None:
                self._model_dict = create_model_dict()

            converter = PdfConverter(artifact_dict=self._model_dict)
            rendered = converter(str(pdf_path))
            return _parse_rendered(rendered, use_llm)

        except (ImportError, AttributeError):
            # 구버전 Marker API 폴백 — stubs 부재는 pyproject.toml mypy.overrides에서 허용한다.
            from marker.convert import convert_single_pdf
            full_text, _images, _meta = convert_single_pdf(
                str(pdf_path), self._model_dict, max_pages=None,
                langs=None, batch_multiplier=2,
            )
            return [_make_page(0, full_text or "", use_llm)]


def _parse_rendered(rendered: object, llm_corrected: bool) -> list[PageExtraction]:
    """신버전 Marker rendered 객체를 PageExtraction 리스트로 변환한다."""
    full_md: str = getattr(rendered, "markdown", "") or ""
    pages_data = getattr(rendered, "pages", None) or [None]
    return [
        _make_page(
            idx,
            getattr(page, "markdown", full_md) if page is not None else full_md,
            llm_corrected,
        )
        for idx, page in enumerate(pages_data)
    ]

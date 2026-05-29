"""MinerU(magic-pdf) 기반 OCREngine 구현체.

CJK 문서 처리에 강점을 가진 MinerU를 Marker의 폴백 엔진으로 활용한다.
동기 API를 asyncio.to_thread로 감싸 이벤트 루프 블로킹을 방지한다.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from ..schemas import PageExtraction

_LOG = logging.getLogger(__name__)

# MinerU 임포트 — 미설치 환경에서도 모듈 로드가 가능하도록 지연 임포트
try:
    from magic_pdf.data.data_reader_writer import (
        FileBasedDataReader,
        FileBasedDataWriter,
    )
    _MINERU_AVAILABLE = True
except ImportError:
    _MINERU_AVAILABLE = False
    _LOG.warning("magic-pdf 패키지가 설치되지 않았습니다. MinerUEngine 비활성화.")


class MinerUEngine:
    """MinerU(magic-pdf) PDF 변환기를 래핑한 OCREngine 구현체.

    CJK 문서, 특히 한국어·중국어·일본어 문서에서
    Marker보다 높은 인식률을 보이는 폴백 엔진이다.
    """

    name: str = "mineru"

    def supports(self, feature: str) -> bool:
        """지원 기능 플래그를 반환한다."""
        return feature in {"pdf", "markdown", "tables", "formulas", "cjk"}

    async def extract(
        self,
        pdf_bytes: bytes,
        pages: list[int] | None = None,
        force_ocr: bool = False,
        use_llm: bool = False,
    ) -> list[PageExtraction]:
        """PDF 바이트를 받아 페이지별 추출 결과를 반환한다.

        MinerU 동기 API를 asyncio.to_thread로 감싸 실행한다.
        """
        if not _MINERU_AVAILABLE:
            raise RuntimeError("magic-pdf 패키지가 설치되지 않아 MinerUEngine을 사용할 수 없습니다.")

        return await asyncio.to_thread(
            self._extract_sync, pdf_bytes, pages, force_ocr, use_llm
        )

    def _extract_sync(
        self,
        pdf_bytes: bytes,
        pages: list[int] | None,
        force_ocr: bool,
        use_llm: bool,
    ) -> list[PageExtraction]:
        """동기 래퍼 — MinerU는 동기 API이므로 별도 스레드에서 실행된다."""
        tmp_dir: Path | None = None
        try:
            # MinerU는 입출력 디렉터리를 필요로 하므로 임시 디렉터리 생성
            import tempfile as tf
            with tf.TemporaryDirectory() as tmp_str:
                tmp_dir = Path(tmp_str)
                pdf_path = tmp_dir / "input.pdf"
                pdf_path.write_bytes(pdf_bytes)
                return self._run_mineru(pdf_path, tmp_dir, force_ocr)
        except Exception as exc:
            _LOG.exception("MinerUEngine 추출 중 오류 발생")
            raise RuntimeError(f"MinerU 추출 실패: {exc}") from exc

    def _run_mineru(
        self,
        pdf_path: Path,
        out_dir: Path,
        force_ocr: bool,
    ) -> list[PageExtraction]:
        """MinerU API를 호출하고 PageExtraction 리스트로 정규화한다.

        magic-pdf 버전에 따라 UNIPipe 또는 OCRPipe를 사용한다.
        force_ocr=True이면 OCRPipe를 강제 선택한다.
        """
        try:
            if force_ocr:
                from magic_pdf.pipe.OCRPipe import OCRPipe  # type: ignore[import]
                pipe_cls = OCRPipe
            else:
                from magic_pdf.pipe.UNIPipe import UNIPipe  # type: ignore[import]
                pipe_cls = UNIPipe

            reader = FileBasedDataReader("")
            writer = FileBasedDataWriter(str(out_dir))
            pdf_bytes_data = pdf_path.read_bytes()

            pipe = pipe_cls(
                pdf_bytes_data,
                {"_pdf_type": "ocr" if force_ocr else "auto", "model_list": []},
                writer,
            )
            pipe.pipe_classify()
            pipe.pipe_analyze()
            pipe.pipe_parse()
            md_content = pipe.pipe_mk_markdown(str(out_dir), drop_mode="none")

        except (ImportError, Exception) as exc:
            _LOG.warning("MinerU 파이프 실행 실패, 빈 결과 반환: %s", exc)
            md_content = ""

        return _parse_mineru_output(md_content or "")


def _parse_mineru_output(md_content: str) -> list[PageExtraction]:
    """MinerU 마크다운 출력을 PageExtraction 리스트로 변환한다.

    MinerU는 단일 마크다운을 출력하므로 페이지 경계 마커(\\n\\n---\\n\\n)로
    페이지를 분리한다. 마커가 없으면 단일 페이지로 처리한다.
    """
    # MinerU 페이지 구분자: 수평선 패턴
    page_sections = md_content.split("\n\n---\n\n")
    results: list[PageExtraction] = []

    for idx, section in enumerate(page_sections):
        section = section.strip()
        tables = _extract_tables_from_md(section)
        formulas = _extract_formulas_from_md(section)
        results.append(
            PageExtraction(
                page_num=idx + 1,
                markdown=section,
                tables=tables,
                formulas=formulas,
                engine="mineru",
                llm_corrected=False,
            )
        )

    return results if results else [
        PageExtraction(
            page_num=1,
            markdown="",
            tables=[],
            formulas=[],
            engine="mineru",
            llm_corrected=False,
        )
    ]


def _extract_tables_from_md(md: str) -> list[dict]:
    """마크다운에서 파이프 테이블 블록을 추출한다."""
    lines = md.splitlines()
    tables: list[dict] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            current.append(line)
        else:
            if len(current) >= 2:
                tables.append({"md": "\n".join(current), "json": {}})
            current = []

    if len(current) >= 2:
        tables.append({"md": "\n".join(current), "json": {}})

    return tables


def _extract_formulas_from_md(md: str) -> list[str]:
    """마크다운에서 LaTeX 수식을 추출한다."""
    import re

    formulas: list[str] = []
    for match in re.finditer(r"\$\$(.+?)\$\$", md, re.DOTALL):
        formulas.append(match.group(1).strip())
    for match in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", md):
        formulas.append(match.group(1).strip())
    return formulas

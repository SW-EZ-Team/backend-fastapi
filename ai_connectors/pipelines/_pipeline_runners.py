"""파이프라인 비동기 실행 원자 함수.

각 함수는 파이프라인의 단일 단계(OCR / postproc)를 수행한다.
오케스트레이터에서 분리해 파일당 크기 제한을 지킨다.
"""
from __future__ import annotations

from ai_connectors.postproc_schemas import PostprocRequest, PostprocResponse
from ai_connectors.schemas import Correction, OCRRequest, OCRResponse

from ._pipeline_helpers import build_page_result, parse_corrections
from ._postproc_protocol import PostprocConnector


async def run_ocr_pages(
    ocr_connector: object, png_pages: list[bytes]
) -> tuple[list, str]:
    """페이지별 OCR 실행 후 (PageResult 목록, 모델명) 반환.

    반환 모델명은 마지막 페이지 응답의 model_version 을 기준으로 한다.
    """
    results = []
    ocr_model = ""
    for idx, page_png in enumerate(png_pages):
        resp: OCRResponse = await ocr_connector.recognize(
            OCRRequest(image_bytes=page_png)
        )
        ocr_model = resp.model_version
        results.append(build_page_result(page_num=idx + 1, ocr_resp=resp))
    return results, ocr_model


async def run_postproc(
    postproc_connector: PostprocConnector | None,
    raw_text: str,
    *,
    preserve_latex: bool = True,
) -> tuple[str, list[Correction], str]:
    """Kanana-2 후처리 실행. 커넥터 없으면 원문 그대로 반환.

    반환: (refined_text, corrections, postproc_model_name)
    커넥터 미주입 시 'postproc-not-available' 모델명으로 원문을 그대로 반환한다.
    """
    if postproc_connector is None:
        # ai-model-specialist 완료 전 임시 경로 — 후처리 건너뜀
        return raw_text, [], "postproc-not-available"
    request = PostprocRequest(ocr_text=raw_text, preserve_latex=preserve_latex)
    response: PostprocResponse = await postproc_connector.refine(request)
    refined_text: str = response.refined_text
    corrections: list[Correction] = parse_corrections(response.corrections)
    model_name: str = getattr(postproc_connector, "name", "kanana2-mlx")
    return refined_text, corrections, model_name

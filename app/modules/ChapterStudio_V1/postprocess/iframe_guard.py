"""저장 직전 슬라이드 iframe 계약 가드.

public.slide / chapter_studio.slide에 저장되는 html_content는 반드시
wrap_iframe 출력 형태(<iframe sandbox="allow-scripts" srcdoc=...)여야 한다.
어떤 생성 경로가 raw HTML을 흘려보내도 저장 단계에서 차단한다.

복구 순서:
  1) 이미 올바른 iframe이면 그대로 통과.
  2) 후처리 파이프라인(postprocess_slide)을 그 슬라이드에 한해 1회 재실행.
  3) 재실행 결과도 비정상이면 wrap_iframe으로 강제 감싼다 — raw HTML 저장 불가 보장.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from app.modules.ChapterStudio_V1.postprocess.iframe_sandboxer import wrap_iframe

_LOG = logging.getLogger(__name__)

SlideRecord = dict[str, object]

# wrap_iframe 출력과 구조까지 일치해야 통과 — srcdoc 값은 html.escape(quote=True)
# 결과라 raw 따옴표/꺾쇠가 없고, 추가 속성(onload 등)이 붙은 iframe은 거부된다.
_IFRAME_CONTRACT_RE = re.compile(
    r'<iframe sandbox="allow-scripts" srcdoc="[^"<>]*"'
    r' style="width:100%;border:none;"></iframe>\s*\Z'
)


def is_sandboxed_iframe(html: str) -> bool:
    """html이 wrap_iframe 출력 계약과 구조적으로 일치하는지 엄격 검사한다."""
    return _IFRAME_CONTRACT_RE.match(html.lstrip()) is not None


async def ensure_slides_iframe(records: list[SlideRecord]) -> list[SlideRecord]:
    """저장 직전 슬라이드 목록의 html_content를 iframe 계약으로 정규화한다.

    dict가 아닌 항목은 dict() 변환에서 죽지 않도록 그대로 통과시킨다 —
    가드는 저장 차단이 아니라 정규화가 목적이라, 형태가 깨진 행은 다운스트림
    저장 단계의 검증이 드러내게 둔다(여기서 예외로 전체 저장을 막지 않는다).
    """
    return [
        await _ensure_slide_iframe(dict(row)) if isinstance(row, Mapping) else row
        for row in records
    ]


async def _ensure_slide_iframe(row: SlideRecord) -> SlideRecord:
    html = row.get("html_content")
    if not isinstance(html, str) or html == "" or is_sandboxed_iframe(html):
        return row
    idx = row.get("slide_idx")
    slide_idx = idx if isinstance(idx, int) else 0
    category = row.get("category")
    category_text = category if isinstance(category, str) and category else "text"
    warnings = [item for item in row.get("warnings", []) if isinstance(item, str)] if isinstance(row.get("warnings"), list) else []

    candidate = await _re_postprocess(slide_idx, category_text, html)
    if candidate is not None and is_sandboxed_iframe(candidate):
        warnings.append("iframe-guard: raw HTML 감지 — 후처리 1회 재실행으로 복구")
        _LOG.warning("[iframe-guard] 후처리 재실행으로 복구 — slide_idx=%d", slide_idx)
    else:
        # 최후 방어선: 어떤 경우에도 raw HTML이 저장되지 않도록 강제 래핑한다.
        candidate = wrap_iframe(html)
        warnings.append("iframe-guard: 후처리 재실행 실패 — wrap_iframe 강제 적용")
        _LOG.warning("[iframe-guard] wrap_iframe 강제 적용 — slide_idx=%d", slide_idx)

    row["html_content"] = candidate
    row["warnings"] = warnings
    return row


async def _re_postprocess(slide_idx: int, category: str, raw_html: str) -> str | None:
    """단일 슬라이드 후처리 재실행. 실패 시 None을 반환해 강제 래핑 폴백으로 넘긴다."""
    # 지역 import — postprocess.pipeline은 무겁고(차트/머메이드 렌더러), 가드 단독 사용 시 불필요하다.
    from app.modules.ChapterStudio_V1.postprocess.pipeline import postprocess_slide

    try:
        result = await postprocess_slide(slide_idx, category, raw_html, "")
    except Exception as exc:
        _LOG.warning("[iframe-guard] 후처리 재실행 예외 — slide_idx=%d, error=%s", slide_idx, exc)
        return None
    iframe_html = result.get("iframe_html")
    return iframe_html if isinstance(iframe_html, str) else None


__all__ = ["ensure_slides_iframe", "is_sandboxed_iframe"]

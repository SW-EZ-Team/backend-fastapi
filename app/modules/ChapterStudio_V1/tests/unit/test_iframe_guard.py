# 저장 직전 iframe 계약 가드(postprocess/iframe_guard.py) 단위 테스트다.
# raw HTML 슬라이드가 절대 저장되지 않음(재후처리 → 강제 래핑 폴백)을 검증한다.
from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.postprocess import iframe_guard
from app.modules.ChapterStudio_V1.postprocess.iframe_guard import (
    ensure_slides_iframe,
    is_sandboxed_iframe,
)
from app.modules.ChapterStudio_V1.postprocess.iframe_sandboxer import wrap_iframe


class TestIsSandboxedIframe:
    def test_wrap_iframe_output_passes(self) -> None:
        assert is_sandboxed_iframe(wrap_iframe("<p>본문</p>")) is True

    def test_raw_html_fails(self) -> None:
        assert is_sandboxed_iframe("<div>raw 슬라이드</div>") is False

    def test_iframe_without_sandbox_fails(self) -> None:
        assert is_sandboxed_iframe('<iframe srcdoc="x"></iframe>') is False

    def test_iframe_without_srcdoc_fails(self) -> None:
        assert is_sandboxed_iframe('<iframe sandbox="allow-scripts" src="https://x"></iframe>') is False

    def test_iframe_with_extra_event_handler_fails(self) -> None:
        # iframe 요소 자체의 이벤트 핸들러는 부모 문서에서 실행되므로 구조 불일치로 거부해야 한다.
        assert (
            is_sandboxed_iframe(
                '<iframe sandbox="allow-scripts" srcdoc="x" onload="alert(1)"'
                ' style="width:100%;border:none;"></iframe>'
            )
            is False
        )

    def test_iframe_with_trailing_payload_fails(self) -> None:
        # 정상 iframe 뒤에 다른 마크업이 붙은 경우도 거부한다.
        assert is_sandboxed_iframe(wrap_iframe("<p>본문</p>") + "<script>alert(1)</script>") is False


@pytest.mark.anyio
async def test_valid_iframe_slide_passes_through_unchanged() -> None:
    html = wrap_iframe("<p>이미 올바른 슬라이드</p>")
    rows = [{"slide_idx": 0, "category": "text", "html_content": html, "warnings": []}]

    result = await ensure_slides_iframe(rows)

    assert result[0]["html_content"] == html
    assert result[0]["warnings"] == []


@pytest.mark.anyio
async def test_raw_html_slide_is_repostprocessed_into_iframe() -> None:
    rows = [
        {
            "slide_idx": 1,
            "category": "text",
            "html_content": "<h2>정수의 대소 비교</h2><p>수직선에서 오른쪽이 더 큽니다.</p>",
            "warnings": [],
        }
    ]

    result = await ensure_slides_iframe(rows)

    final = result[0]["html_content"]
    assert isinstance(final, str)
    assert is_sandboxed_iframe(final)
    assert any("iframe-guard" in w for w in result[0]["warnings"])


@pytest.mark.anyio
async def test_force_wrap_when_repostprocess_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_re_postprocess(slide_idx: int, category: str, raw_html: str) -> str | None:
        return None

    monkeypatch.setattr(iframe_guard, "_re_postprocess", fake_re_postprocess)
    raw = "<div>후처리 재실행도 실패한 raw 슬라이드</div>"
    rows = [{"slide_idx": 2, "category": "text", "html_content": raw, "warnings": ["기존 경고"]}]

    result = await ensure_slides_iframe(rows)

    final = result[0]["html_content"]
    assert isinstance(final, str)
    assert is_sandboxed_iframe(final)
    # 강제 래핑은 원본 body를 그대로 srcdoc에 보존한다(이중 escape된 형태)
    assert "후처리 재실행도 실패한" in final
    warnings = result[0]["warnings"]
    assert "기존 경고" in warnings
    assert any("wrap_iframe 강제 적용" in w for w in warnings)


@pytest.mark.anyio
async def test_record_without_html_content_key_passes_through() -> None:
    """html_content 키가 없는 레코드는 그대로 통과한다(크래시 금지)."""
    rows = [{"slide_idx": 0, "category": "text"}]

    result = await ensure_slides_iframe(rows)

    assert result[0] == {"slide_idx": 0, "category": "text"}


@pytest.mark.anyio
async def test_record_with_none_html_content_passes_through() -> None:
    """html_content=None 레코드는 문자열이 아니므로 손대지 않는다."""
    rows = [{"slide_idx": 0, "category": "text", "html_content": None}]

    result = await ensure_slides_iframe(rows)

    assert result[0]["html_content"] is None


@pytest.mark.anyio
async def test_non_dict_record_passes_through_unchanged() -> None:
    """dict가 아닌 항목은 dict() 변환에서 죽지 않고 그대로 통과한다."""
    rows = ["이상한 레코드", None, 42]

    result = await ensure_slides_iframe(rows)

    assert result == ["이상한 레코드", None, 42]

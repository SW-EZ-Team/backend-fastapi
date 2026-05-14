from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.validators.contrast import contrast_ratio, passes_aa_text


@pytest.mark.parametrize(
    ("foreground", "background"),
    [
        ("#1F2A30", "#F8F8F6"),
        ("#6F42C1", "#F6F8F4"),
        ("#8A5A00", "#F6F8F4"),
        ("#0B6EA8", "#F6F8F4"),
        ("#B42318", "#F6F8F4"),
        ("#067A7A", "#F6F8F4"),
        ("#5D6978", "#F6F8F4"),
        ("#1F2A30", "#E7F3E8"),
        ("#06120C", "#36A66A"),
        ("#1F2A30", "#F3F7FB"),
        ("#1F2A30", "#FFFDF7"),
        ("#FFFFFF", "#207B4C"),
        ("#1F2A30", "#EAF2F7"),
    ],
)
def test_theme_text_pairs_pass_wcag_aa(foreground: str, background: str) -> None:
    assert passes_aa_text(foreground, background), contrast_ratio(foreground, background)


def test_low_contrast_gray_on_white_fails() -> None:
    assert not passes_aa_text("#AEB4C4", "#FFFFFF")

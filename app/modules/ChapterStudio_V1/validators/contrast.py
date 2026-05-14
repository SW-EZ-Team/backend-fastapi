from __future__ import annotations


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 상대휘도 공식으로 두 색의 대비 비율을 계산한다."""
    fg = _relative_luminance(_hex_rgb(foreground))
    bg = _relative_luminance(_hex_rgb(background))
    light, dark = max(fg, bg), min(fg, bg)
    return (light + 0.05) / (dark + 0.05)


def passes_aa_text(foreground: str, background: str) -> bool:
    """일반 텍스트 기준 WCAG AA 4.5:1 이상인지 확인한다."""
    return contrast_ratio(foreground, background) >= 4.5


def _hex_rgb(value: str) -> tuple[float, float, float]:
    raw = value.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError("6자리 hex 색상만 지원한다.")
    return (
        int(raw[0:2], 16) / 255,
        int(raw[2:4], 16) / 255,
        int(raw[4:6], 16) / 255,
    )


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    red, green, blue = (_linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


__all__ = ["contrast_ratio", "passes_aa_text"]

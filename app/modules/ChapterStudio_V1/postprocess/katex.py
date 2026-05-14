from __future__ import annotations

import asyncio
import html
import json
import re
import subprocess

_BLOCK_RE = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)
_INLINE_RE = re.compile(r"\\\((.*?)\\\)", re.DOTALL)
_FORMULA_CACHE: dict[tuple[str, bool], tuple[str, str | None]] = {}


async def katex_render(source_html: str) -> tuple[str, list[str]]:
    """TeX 인라인/블록 표식을 KaTeX HTML로 변환한다."""
    block_html, block_warnings = await _replace(source_html, _BLOCK_RE, True)
    inline_html, inline_warnings = await _replace(block_html, _INLINE_RE, False)
    return inline_html, block_warnings + inline_warnings


async def _replace(
    source_html: str, pattern: re.Pattern[str], display_mode: bool
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    parts: list[str] = []
    last = 0
    for match in pattern.finditer(source_html):
        parts.append(source_html[last:match.start()])
        rendered, warning = await _render_formula(match.group(1).strip(), display_mode)
        parts.append(rendered)
        if warning is not None:
            warnings.append(warning)
        last = match.end()
    parts.append(source_html[last:])
    return "".join(parts), warnings


async def _render_formula(tex: str, display_mode: bool) -> tuple[str, str | None]:
    cache_key = (tex, display_mode)
    cached = _FORMULA_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result: tuple[str, str | None]
    try:
        rendered = await _run_external(_cmd(tex, display_mode), "", 10.0)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result = (_fallback(tex, display_mode), f"KaTeX: 원본 보존 {exc}")
    else:
        result = (rendered.strip(), None)
    _FORMULA_CACHE[cache_key] = result
    return result


async def _run_external(cmd: list[str], input_text: str, timeout_sec: float) -> str:
    """Node KaTeX 호출부를 단일 함수로 고정해 테스트 대체를 쉽게 한다."""
    loop = asyncio.get_running_loop()
    proc = await loop.run_in_executor(None, _run_sync, cmd, input_text, timeout_sec)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def _run_sync(
    cmd: list[str], input_text: str, timeout_sec: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=timeout_sec, check=False)


def _cmd(tex: str, display_mode: bool) -> list[str]:
    script = (
        "const katex = require('katex');"
        f"console.log(katex.renderToString({json.dumps(tex)}, "
        f"{{displayMode: {str(display_mode).lower()}, throwOnError: false}}));"
    )
    return ["node", "-e", script]


def _fallback(tex: str, display_mode: bool) -> str:
    escaped = html.escape(tex)
    if display_mode:
        return f"\\[{escaped}\\]"
    return f"\\({escaped}\\)"

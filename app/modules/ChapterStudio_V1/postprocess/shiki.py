from __future__ import annotations

import asyncio
import html
import re
import subprocess

SUPPORTED_LANGS = set("python javascript typescript java c cpp rust go sql html css bash json yaml markdown kotlin".split())
_CODE_RE = re.compile(
    r"<pre><code(?:\s+(?:data-lang=(?P<dq>['\"])(?P<data_lang>[^'\"]*)(?P=dq)"
    r"|class=(?P<cq>['\"])language-(?P<class_lang>[^'\"]*)(?P=cq)))?>(?P<code>.*?)</code></pre>",
    re.DOTALL,
)
_PY_KEYWORDS = set("from import class def return if else elif for while in async await try except with as".split())
_JS_TS_KEYWORDS = set("import from export class function return const let var if else for while async await interface type".split())
_SQL_KEYWORDS = set("select from where join left right inner group by order limit insert update delete create table as".split())
_BUILTINS = set("print len range str int float dict list set Promise Array Map console COUNT SUM AVG MAX MIN".split())
_HIGHLIGHT_CACHE: dict[tuple[str, str], tuple[str, str | None]] = {}


async def shiki_render(source_html: str) -> tuple[str, list[str]]:
    """코드 블록만 찾아 Shiki 하이라이팅을 적용한다."""
    warnings: list[str] = []
    parts: list[str] = []
    last = 0
    for match in _CODE_RE.finditer(source_html):
        parts.append(source_html[last:match.start()])
        lang = match.group("data_lang") or match.group("class_lang") or ""
        block, warning = await _highlight_block(lang, match.group("code"))
        parts.append(block)
        if warning is not None:
            warnings.append(warning)
        last = match.end()
    parts.append(source_html[last:])
    return "".join(parts), warnings


async def _highlight_block(lang: str, code: str) -> tuple[str, str | None]:
    if lang not in SUPPORTED_LANGS:
        return _plain_fallback(code), f"Shiki: 미지원 언어 {lang}"
    cache_key = (lang, code)
    cached = _HIGHLIGHT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        rendered = await _run_external(["npx", "shiki", "--lang", lang], code, 10.0)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        result: tuple[str, str | None] = (_language_fallback(lang, code), None)
    else:
        if _needs_class_fallback(rendered):
            result = (_language_fallback(lang, code), None)
        else:
            result = (f'<div class="shiki-dual-theme">{rendered}</div>', None)
    _HIGHLIGHT_CACHE[cache_key] = result
    return result


async def _run_external(cmd: list[str], input_text: str, timeout_sec: float) -> str:
    """서브프로세스 실행 지점을 하나로 모아 테스트에서 안전하게 대체한다."""
    loop = asyncio.get_running_loop()
    proc = await loop.run_in_executor(None, _run_sync, cmd, input_text, timeout_sec)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def _run_sync(
    cmd: list[str], input_text: str, timeout_sec: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def _needs_class_fallback(rendered: str) -> bool:
    """인라인 style 기반 결과는 sanitizer 후 색이 사라지므로 클래스 테마로 대체한다."""
    lowered = rendered.lower()
    return "style=" in lowered or "color:" in lowered


def _plain_fallback(code: str) -> str:
    """렌더 실패 시 코드 원문은 반드시 보존한다."""
    return f"<pre><code>{html.escape(code)}</code></pre>"


def _language_fallback(lang: str, code: str) -> str:
    if lang == "python":
        return _python_fallback(code)
    if lang in {"javascript", "typescript", "java", "go", "rust", "kotlin"}:
        return _generic_fallback(lang, code, _JS_TS_KEYWORDS)
    if lang == "sql":
        return _generic_fallback(lang, code, _SQL_KEYWORDS)
    return _plain_fallback(code)


def _python_fallback(code: str) -> str:
    escaped = html.escape(code)
    highlighted = "\n".join(_python_line(line) for line in escaped.splitlines())
    return _code_card("Python 구조 읽기", highlighted)


def _generic_fallback(lang: str, code: str, keywords: set[str]) -> str:
    escaped = html.escape(code)
    lines = [_generic_line(line, keywords) for line in escaped.splitlines()]
    return _code_card(f"{lang} 구조 읽기", "\n".join(lines))


def _code_card(title: str, highlighted: str) -> str:
    legend = (
        '<div class="code-legend"><span class="legend-keyword">keyword</span>'
        '<span class="legend-class">class</span><span class="legend-fn">function</span>'
        '<span class="legend-variable">variable</span><span class="legend-param">parameter</span>'
        '<span class="legend-property">property</span></div>'
    )
    return f'<div class="code-card"><div class="code-caption">{title}</div>{legend}<pre class="code-theme"><code>{highlighted}</code></pre></div>'


def _python_line(line: str) -> str:
    parts: list[str] = []
    expect: str | None = None
    pattern = r"#.*$|&quot;.*?&quot;|&#x27;.*?&#x27;|\b\d+\b|\b[A-Za-z_][A-Za-z0-9_]*\b|\s+|."
    for match in re.finditer(pattern, line):
        token = match.group(0)
        rendered, expect = _render_token(line, match.end(), token, expect)
        parts.append(rendered)
    return "".join(parts)


def _render_token(line: str, end: int, token: str, expect: str | None) -> tuple[str, str | None]:
    if token.startswith("#"):
        return f'<span class="tok-comment">{token}</span>', None
    if token.startswith(("&#x27;", "&quot;")):
        return f'<span class="tok-string">{token}</span>', None
    if token.isdigit():
        return f'<span class="tok-number">{token}</span>', expect
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
        return token, expect
    return _identifier_token(line, end, token, expect)


def _identifier_token(line: str, end: int, token: str, expect: str | None) -> tuple[str, str | None]:
    if token in _PY_KEYWORDS:
        next_expect = "class" if token == "class" else "fn" if token == "def" else None
        return f'<span class="tok-keyword">{token}</span>', next_expect
    if token in _BUILTINS:
        return f'<span class="tok-builtin">{token}</span>', None
    if _has_prefix(line, end, token, "@"):
        return f'<span class="tok-decorator">{token}</span>', None
    if expect == "class":
        return f'<span class="tok-class">{token}</span>', None
    if expect == "fn":
        return f'<span class="tok-fn">{token}</span>', None
    if _has_prefix(line, end, token, "."):
        return f'<span class="tok-property">{token}</span>', None
    if token in {"self", "cls"}:
        return f'<span class="tok-instance">{token}</span>', None
    if re.match(r"\s*=", line[end:]):
        return f'<span class="tok-variable">{token}</span>', None
    if re.match(r"\s*:", line[end:]):
        return f'<span class="tok-param">{token}</span>', None
    if token[:1].isupper():
        return f'<span class="tok-class">{token}</span>', None
    return token, None


def _generic_line(line: str, keywords: set[str]) -> str:
    pattern = r"//.*$|#.*$|&quot;.*?&quot;|&#x27;.*?&#x27;|`.*?`|\b\d+\b|\b[A-Za-z_][A-Za-z0-9_]*\b|\s+|."
    return "".join(_generic_token(line, match.end(), match.group(0), keywords) for match in re.finditer(pattern, line))

def _generic_token(line: str, end: int, token: str, keywords: set[str]) -> str:
    lowered = token.lower()
    if token.startswith(("//", "#")):
        return f'<span class="tok-comment">{token}</span>'
    if token.startswith(("&#x27;", "&quot;", "`")):
        return f'<span class="tok-string">{token}</span>'
    if token.isdigit():
        return f'<span class="tok-number">{token}</span>'
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
        return token
    if lowered in keywords:
        return f'<span class="tok-keyword">{token}</span>'
    if token in _BUILTINS:
        return f'<span class="tok-builtin">{token}</span>'
    if _has_prefix(line, end, token, "."):
        return f'<span class="tok-property">{token}</span>'
    if re.match(r"\s*[:=]", line[end:]):
        return f'<span class="tok-variable">{token}</span>'
    if re.match(r"\s*\(", line[end:]):
        return f'<span class="tok-fn">{token}</span>'
    if token[:1].isupper():
        return f'<span class="tok-class">{token}</span>'
    return token

def _has_prefix(line: str, end: int, token: str, prefix: str) -> bool:
    return line[: end - len(token)].rstrip().endswith(prefix)

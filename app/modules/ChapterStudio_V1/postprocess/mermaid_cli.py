from __future__ import annotations

import asyncio
import html
import re
import subprocess
import uuid
from pathlib import Path

_MERMAID_RE = re.compile(
    r"<pre\b[^>]*class=(?P<quote>['\"])(?P<class>[^'\"]*\bmermaid\b[^'\"]*)(?P=quote)[^>]*>"
    r"(?P<source>.*?)</pre>",
    re.DOTALL,
)
_EDGE_RE = re.compile(
    r"(?P<src>[A-Za-z0-9_]+)(?:\[(?P<src_label>[^\]]+)\]|\{(?P<src_brace>[^}]+)\})?\s*-+>"
    r"(?:\|[^|]*\|)?\s*(?P<dst>[A-Za-z0-9_]+)(?:\[(?P<dst_label>[^\]]+)\]|\{(?P<dst_brace>[^}]+)\})?"
)
_NODE_LABEL_START_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*\[")
_EDGE_LABEL_RE = re.compile(r"(?P<connector>(?:-\.+->|-\.+-|={2,}>?|-{2,}>?|~~~)\s*)\|(?P<label>[^\n|]*)\|")
_UNQUOTED_LABEL_SPECIAL_RE = re.compile(r"[:(){}]")
_EDGE_LABEL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("<=>", "⇔"),
    ("<->", "↔"),
    ("->", "→"),
    ("<-", "←"),
    ("=>", "⇒"),
)
_TIMEOUT_SEC = 10.0
_MERMAID_CACHE: dict[str, tuple[str, str | None]] = {}


async def mermaid_render(source_html: str) -> tuple[str, list[str]]:
    """Mermaid 원문 블록을 서버 렌더링 SVG로 치환한다."""
    warnings: list[str] = []
    parts: list[str] = []
    last = 0
    for match in _MERMAID_RE.finditer(source_html):
        parts.append(source_html[last:match.start()])
        svg, warning = await _render_mermaid_block(match.group("source"))
        parts.append(svg)
        if warning is not None:
            warnings.append(warning)
        last = match.end()
    parts.append(source_html[last:])
    return "".join(parts), warnings


async def _render_mermaid_block(source: str) -> tuple[str, str | None]:
    sanitized_source = _sanitize_mermaid_source(source)
    cached = _MERMAID_CACHE.get(sanitized_source)
    if cached is not None:
        return cached
    tmp_in = Path(f"/tmp/chapterstudio-mmd-{uuid.uuid4()}.mmd")
    tmp_out = Path(f"/tmp/chapterstudio-mmd-{uuid.uuid4()}.svg")
    result: tuple[str, str | None]
    try:
        tmp_in.write_text(sanitized_source, encoding="utf-8")
        await _run_external(_cmd(tmp_in, tmp_out), _TIMEOUT_SEC)
        if not tmp_out.exists():
            raise RuntimeError("SVG 출력 파일이 없다.")
        result = (tmp_out.read_text(encoding="utf-8"), None)
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError):
        result = (_mermaid_fallback(sanitized_source), None)
    finally:
        tmp_in.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)
    _MERMAID_CACHE[sanitized_source] = result
    return result


def _sanitize_mermaid_labels(source: str) -> str:
    """노드 라벨만 정제해 mermaid-cli 파싱 실패 가능성을 낮춘다."""
    parts: list[str] = []
    cursor = 0
    for match in _NODE_LABEL_START_RE.finditer(source):
        if match.start() < cursor or _is_inside_edge_label(source, match.start()):
            continue
        label_start = match.end()
        label_end = _find_node_label_end(source, label_start)
        if label_end is None:
            continue
        parts.append(source[cursor:label_start])
        parts.append(_sanitize_node_label(source[label_start:label_end]))
        parts.append("]")
        cursor = label_end + 1
    parts.append(source[cursor:])
    return "".join(parts)


def _sanitize_mermaid_source(source: str) -> str:
    """노드 라벨과 edge 라벨을 렌더링 전에 한 번에 정제한다."""
    return _sanitize_mermaid_edge_labels(_sanitize_mermaid_labels(source))


def _sanitize_mermaid_edge_labels(source: str) -> str:
    """edge 라벨 내부 예약 화살표만 바꾸고 edge 연결자는 그대로 둔다."""
    return _EDGE_LABEL_RE.sub(_sanitize_edge_label_match, source)


def _sanitize_edge_label_match(match: re.Match[str]) -> str:
    label = _sanitize_edge_label(match.group("label"))
    return f'{match.group("connector")}|{label}|'


def _sanitize_edge_label(label: str) -> str:
    safe_label = _collapse_label_line(label)
    for unsafe, replacement in _EDGE_LABEL_REPLACEMENTS:
        safe_label = safe_label.replace(unsafe, replacement)
    return safe_label


def _is_inside_edge_label(source: str, index: int) -> bool:
    line_start = source.rfind("\n", 0, index) + 1
    line_end = source.find("\n", index)
    if line_end == -1:
        line_end = len(source)
    return source[line_start:index].count("|") % 2 == 1 and "|" in source[index:line_end]


def _find_node_label_end(source: str, label_start: int) -> int | None:
    depth = 1
    for index in range(label_start, len(source)):
        char = source[index]
        if char == "\n":
            return None
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def _sanitize_node_label(label: str) -> str:
    if _is_quoted_label(label):
        return label
    one_line_label = _collapse_label_line(label)
    bracket_safe_label = one_line_label.replace("[", "(").replace("]", ")")
    if _UNQUOTED_LABEL_SPECIAL_RE.search(bracket_safe_label):
        return f'"{_escape_label_quotes(bracket_safe_label)}"'
    return bracket_safe_label


def _is_quoted_label(label: str) -> bool:
    stripped = label.strip()
    if len(stripped) < 2:
        return False
    return (stripped[0] == stripped[-1] == '"') or (stripped[0] == stripped[-1] == "'")


def _collapse_label_line(label: str) -> str:
    return " ".join(label.replace("\r", "\n").splitlines())


def _escape_label_quotes(label: str) -> str:
    return label.replace("\\", "\\\\").replace('"', '\\"')


async def _run_external(cmd: list[str], timeout_sec: float) -> str:
    """CLI 호출은 이 함수 하나에 모아 테스트에서 외부 실행을 차단한다."""
    loop = asyncio.get_running_loop()
    proc = await loop.run_in_executor(None, _run_sync, cmd, timeout_sec)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def _run_sync(cmd: list[str], timeout_sec: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, check=False)


def _cmd(tmp_in: Path, tmp_out: Path) -> list[str]:
    return ["npx", "-y", "@mermaid-js/mermaid-cli", "-i", str(tmp_in), "-o", str(tmp_out)]


def _mermaid_fallback(source: str) -> str:
    nodes, order = _parse_flowchart(source)
    if not order:
        return f'<pre class="mermaid-fallback">{html.escape(source)}</pre>'
    body = "".join(_node_html(node_id, nodes[node_id], idx) for idx, node_id in enumerate(order))
    return f'<div class="mermaid-fallback" role="img" aria-label="관계 다이어그램">{body}</div>'


def _parse_flowchart(source: str) -> tuple[dict[str, str], list[str]]:
    nodes: dict[str, str] = {}
    order: list[str] = []
    for line in source.splitlines():
        match = _EDGE_RE.search(line)
        if match is None:
            continue
        _add_node(nodes, order, match.group("src"), _label(match, "src"))
        _add_node(nodes, order, match.group("dst"), _label(match, "dst"))
    return nodes, order


def _label(match: re.Match[str], side: str) -> str | None:
    label = match.group(f"{side}_label") or match.group(f"{side}_brace")
    if label is None:
        return None
    return _display_label(label)


def _display_label(label: str) -> str:
    stripped = label.strip()
    if _is_quoted_label(stripped):
        return stripped[1:-1].replace('\\"', '"')
    return label


def _add_node(nodes: dict[str, str], order: list[str], node_id: str, label: str | None) -> None:
    if node_id not in nodes:
        order.append(node_id)
        nodes[node_id] = label or node_id
    elif label is not None:
        nodes[node_id] = label


def _node_html(node_id: str, label: str, idx: int) -> str:
    arrow = '<span class="mermaid-arrow">→</span>' if idx > 0 else ""
    safe_id = html.escape(node_id)
    safe_label = html.escape(label)
    return (
        f'{arrow}<div class="mermaid-node node-{idx % 4}">'
        f'<span class="node-id">{safe_id}</span><strong>{safe_label}</strong></div>'
    )

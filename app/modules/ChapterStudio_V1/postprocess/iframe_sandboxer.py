from __future__ import annotations

import html

_SRC_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:;">
  <style>{css}</style>
</head>
<body>{body}</body>
</html>"""
IFRAME_TEMPLATE = _SRC_TEMPLATE


def wrap_iframe(body_html: str, css: str = "") -> str:
    """sandbox token을 allow-scripts 하나로 고정해 부모 문서 접근을 막는다."""
    srcdoc = html.escape(_SRC_TEMPLATE.format(css=css, body=body_html), quote=True)
    return f'<iframe sandbox="allow-scripts" srcdoc="{srcdoc}" style="width:100%;border:none;"></iframe>'

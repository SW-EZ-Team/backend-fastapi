from __future__ import annotations


def code_theme_css() -> str:
    """라이트 기본값에서도 코드 의미 색상이 보이도록 고정하는 테마 계약이다."""
    return "".join((
        ":root{color-scheme:light dark;--lesson-bg:#F8F8F6;--lesson-paper:#FFFDF7;"
        "--lesson-ink:#1F2A30;--lesson-muted:#53636B;--lesson-line:#DED8CA;"
        "--code-bg:#F6F8F4;--code-head:#EAF0E6;--code-line:#E1E8DE;--code-border:#C9D5C4;"
        "--tok-keyword:#6F42C1;--tok-class:#8A5A00;--tok-fn:#0B6EA8;--tok-variable:#B42318;"
        "--tok-param:#9A5B13;--tok-property:#067A7A;--tok-string:#2D7D46;--tok-number:#A15C07;"
        "--tok-comment:#5D6978;--tok-builtin:#0B7285;--tok-decorator:#8A3FFC;--tok-operator:#475569}",
        "body{background:var(--lesson-bg);color:var(--lesson-ink)}"
        ".slide,section{background:transparent}.formula{background:#FFF3DA;color:#2A3B45;border-color:#E3C983}",
        ".shiki-dual-theme pre,pre.code-theme,.code-card pre{background:var(--code-bg);color:var(--lesson-ink);"
        "border:1px solid var(--code-border);border-radius:8px;padding:14px;overflow:auto;font-size:12px;line-height:1.6}"
        "code{font-family:'JetBrains Mono','D2Coding',ui-monospace,monospace}",
        ".mermaid-fallback{display:flex;align-items:stretch;gap:8px;flex-wrap:wrap;background:#FFFDF7;"
        "border:1px solid #B9C6B4;border-radius:8px;padding:12px;color:#1F2A30}.mermaid-node{min-width:122px;"
        "flex:1 1 122px;border:1px solid #B9C6B4;border-radius:8px;padding:10px 12px;background:#E7F3E8}"
        ".mermaid-node strong{display:block;margin-top:4px;color:#1F2A30;font-size:13px;line-height:1.45}"
        ".node-id{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:#207B4C;"
        "color:#FFFFFF;font-size:11px;font-weight:800}.node-1{background:#FFF3DA}.node-2{background:#F3F7FB}"
        ".node-3{background:#FDECEF}.mermaid-arrow{display:grid;place-items:center;color:#2A3B45;font-size:18px;font-weight:900}",
        ".code-card{background:var(--code-bg);border:1px solid var(--code-border);border-radius:8px;overflow:hidden;"
        "box-shadow:0 8px 22px -18px rgba(31,42,48,.38)}.code-card pre.code-theme{margin:0;border:0;"
        "border-radius:0;background:var(--code-bg);color:var(--lesson-ink)}",
        ".code-caption{padding:10px 14px;color:var(--lesson-ink);background:var(--code-head);"
        "font-size:12px;font-weight:760;border-bottom:1px solid var(--code-line)}"
        ".code-legend{display:flex;gap:6px;flex-wrap:wrap;padding:8px 14px;background:#FBFCF8;"
        "border-bottom:1px solid var(--code-line)}.code-legend span{font-size:10px;font-weight:800}",
        ".legend-keyword,.tok-keyword{color:var(--tok-keyword);font-weight:800}.legend-class,.tok-class{color:var(--tok-class);font-weight:800}"
        ".legend-fn,.tok-fn{color:var(--tok-fn);font-weight:800}.legend-variable,.tok-variable{color:var(--tok-variable);font-weight:720}"
        ".legend-param,.tok-param{color:var(--tok-param)}.legend-property,.tok-property{color:var(--tok-property);font-weight:700}",
        ".tok-string{color:var(--tok-string)}.tok-number{color:var(--tok-number);font-weight:720}"
        ".tok-comment{color:var(--tok-comment);font-style:italic}.tok-builtin{color:var(--tok-builtin);font-weight:720}"
        ".tok-decorator{color:var(--tok-decorator);font-style:italic}.tok-operator{color:var(--tok-operator)}"
        ".tok-instance{color:var(--tok-decorator);font-style:italic}",
        "@media(prefers-color-scheme:dark){:root{--lesson-bg:#141A1F;--lesson-paper:#1B2329;"
        "--lesson-ink:#EEF2F5;--lesson-muted:#B8C3C9;--lesson-line:#34424A;--code-bg:#172026;"
        "--code-head:#202C33;--code-line:#2D3B43;--code-border:#364850;--tok-keyword:#D6B4FF;"
        "--tok-class:#FFD27D;--tok-fn:#84CFFF;--tok-variable:#FF9A9A;--tok-param:#FFC078;"
        "--tok-property:#7CE0DF;--tok-string:#9BE09B;--tok-number:#FFD28A;--tok-comment:#9AA7B0;"
        "--tok-builtin:#8BE9FD;--tok-decorator:#D0B3FF;--tok-operator:#D8DEE9}"
        "body{background:var(--lesson-bg);color:var(--lesson-ink)}.code-legend{background:#1D282F}"
        ".formula{background:#3A301D;color:#FFF3DA;border-color:#6E5B2B}.mermaid-fallback{background:#192228;"
        "border-color:#40535C;color:#EEF2F5}.mermaid-node{background:#20322C;border-color:#40535C}"
        ".mermaid-node strong{color:#EEF2F5}.node-1{background:#3A301D}.node-2{background:#1C2D3A}"
        ".node-3{background:#3A2227}.node-id{background:#36A66A;color:#06120C}.mermaid-arrow{color:#B8C3C9}}",
    ))


__all__ = ["code_theme_css"]

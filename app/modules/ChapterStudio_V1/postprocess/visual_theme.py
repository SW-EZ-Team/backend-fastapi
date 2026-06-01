from __future__ import annotations


def visual_theme_css() -> str:
    """강의 시각 블록의 기본 대비와 구조를 보장한다."""
    return "".join((
        ":root{--lesson-bg:#F8F8F6;--lesson-offwhite:#FFFDF7;--visual-paper:#FFFDF7;--visual-wash:#F3F7FB;--visual-ink:#1F2A30;"
        "--visual-muted:#4F6068;--visual-line:#C9D5C4;--visual-accent:#207B4C;"
        "--visual-accent-soft:#DFF3E7;--visual-accent-2:#2A5C7A;--visual-warn:#7A6518;--visual-danger:#A33A3A}",
        "section{max-width:100%;min-height:100%;padding:36px 40px;background:var(--lesson-bg);"
        "color:var(--visual-ink);font-family:Pretendard,Inter,system-ui,-apple-system,sans-serif}",
        "h1,h2,h3{color:var(--visual-ink);letter-spacing:0;line-height:1.22}p,li,dd,dt{color:var(--visual-ink);line-height:1.72}",
        ".visual-slide{display:grid;gap:18px;background:var(--lesson-bg)}.visual-slide header{display:grid;gap:8px}"
        ".visual-slide h2{font-size:clamp(24px,3vw,34px);margin:0}.visual-slide header p{max-width:760px;margin:0;color:var(--visual-muted)}"
        ".visual-slide svg{display:block;width:100%;max-width:860px;height:auto;margin:0 auto}.visual-verdict,.visual-answer{font-weight:850;color:var(--visual-accent)}",
        ".comparison-visual,.step-flow-visual,.fraction-bar-visual,.example-box-visual{background:var(--visual-paper);"
        "border:1px solid var(--visual-line);border-radius:8px;padding:16px}.comparison-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}"
        ".comparison-card{background:#F8FBF5;border:1px solid var(--visual-line);border-radius:8px;padding:14px}.comparison-card h3{margin-top:0}"
        ".example-box-visual{display:grid;grid-template-columns:120px 1fr;gap:16px;align-items:start}",
        ".metric-card{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;"
        "background:var(--visual-paper);border:1px solid var(--visual-line);border-radius:8px;padding:16px}",
        ".metric-card>*{min-height:74px;border-left:5px solid var(--visual-accent);background:#F8FBF5;"
        "border-radius:8px;padding:12px;color:var(--visual-ink)}.metric-card strong,.metric-card b{color:var(--visual-accent)}",
        ".flow-strip,.step-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;align-items:stretch}",
        ".flow-strip>* ,.step-grid>*{position:relative;background:var(--visual-paper);border:1px solid var(--visual-line);"
        "border-radius:8px;padding:14px;color:var(--visual-ink);font-weight:760}",
        ".flow-strip>.arrow,.flow-strip>.connector,.flow-strip>.flow-arrow{display:none!important}"
        ".flow-strip>.arrow::after,.flow-strip>.connector::after,.flow-strip>.flow-arrow::after{content:none!important}",
        ".flow-strip>*:not(:last-child)::after{content:'→';position:absolute;right:-13px;top:50%;transform:translateY(-50%);"
        "color:var(--visual-accent);font-weight:900;background:var(--visual-wash);padding:0 3px}",
        ".comparison-table,table{width:100%;border-collapse:separate;border-spacing:0;background:var(--visual-paper);"
        "border:1px solid var(--visual-line);border-radius:8px;overflow:hidden;color:var(--visual-ink)}",
        "th{background:#EAF3ED;color:var(--visual-ink);font-weight:860}td,th{padding:12px;border-bottom:1px solid var(--visual-line);"
        "vertical-align:top}tr:last-child td{border-bottom:0}",
        ".timeline{display:grid;gap:12px;border-left:4px solid var(--visual-accent);padding-left:16px}"
        ".timeline>*{position:relative;background:var(--visual-paper);border:1px solid var(--visual-line);border-radius:8px;padding:12px}",
        ".timeline>*::before{content:'';position:absolute;left:-26px;top:18px;width:12px;height:12px;border-radius:50%;background:var(--visual-accent)}",
        "details{background:var(--visual-paper);border:1px solid var(--visual-line);border-radius:8px;padding:12px;color:var(--visual-ink)}"
        "summary{cursor:pointer;color:var(--visual-ink);font-weight:860}button{border:0;border-radius:8px;background:var(--visual-accent);"
        "color:#FFFFFF;padding:10px 14px;font-weight:860}",
        ".linked-list{display:flex;gap:26px;align-items:center;flex-wrap:wrap;list-style:none;padding:0;margin:16px 0}"
        ".linked-list li{position:relative;background:var(--visual-paper);border:2px solid var(--visual-accent);border-radius:8px;"
        "min-width:116px;padding:14px;text-align:center;font-weight:860;color:var(--visual-ink)}",
        ".linked-list li:not(:last-child)::after{content:'→';position:absolute;right:-26px;top:50%;transform:translateY(-50%);"
        "color:var(--visual-accent-2);font-size:24px;font-weight:900}",
        ".graph-map{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:16px;padding:16px;background:var(--visual-paper);"
        "border:1px solid var(--visual-line);border-radius:8px}.graph-node{display:grid;place-items:center;min-height:82px;"
        "border:2px solid var(--visual-accent-2);border-radius:50%;background:#EAF2F7;color:var(--visual-ink);font-weight:900}",
        ".node-link-visual{display:block;width:100%;max-width:720px;min-height:190px;margin:14px auto;background:var(--visual-paper);"
        "border:1px solid var(--visual-line);border-radius:8px}.node-link-visual text{fill:var(--visual-ink);font-weight:820}"
        ".node-link-visual circle{fill:#EAF2F7;stroke:var(--visual-accent-2);stroke-width:3;}"
        ".node-link-visual line,.node-link-visual path{stroke:var(--visual-accent-2);stroke-width:3}",
        "@media(prefers-color-scheme:dark){:root{--visual-paper:#1B2329;--visual-wash:#141A1F;--visual-ink:#EEF2F5;"
        "--visual-muted:#B8C3C9;--visual-line:#40535C;--visual-accent:#36A66A;--visual-accent-2:#84CFFF;--visual-warn:#FFD27D}"
        ".metric-card>*{background:#20322C}th{background:#20322C}.graph-node{background:#1C2D3A}}",
    ))


def accessibility_guard_css() -> str:
    """모델별 raw CSS 뒤에서 저대비 시각 블록을 다시 읽히게 만든다."""
    return "".join((
        "body section,body article,body .metric-card,body .flow-strip,body .step-grid,body .comparison-table,"
        "body .timeline,body details,body .graph-map{color:var(--visual-ink);}",
        "body .metric-card *,body .flow-strip *,body .step-grid *,body .comparison-table *,body .timeline *,"
        "body details *,body .graph-map *,body .linked-list *,body .node-link-visual text{color:var(--visual-ink);}",
        "body .metric-card{background:var(--visual-paper);border-color:var(--visual-line)}"
        "body .metric-card>*{color:var(--visual-ink);background:#F8FBF5}",
        "body .flow-strip>* ,body .step-grid>* ,body .timeline>* ,body .linked-list li{color:var(--visual-ink);"
        "background:var(--visual-paper);border-color:var(--visual-line)}",
        "body .flow-strip>.arrow,body .flow-strip>.connector,body .flow-strip>.flow-arrow{display:none!important}"
        "body .flow-strip>.arrow::after,body .flow-strip>.connector::after,body .flow-strip>.flow-arrow::after{content:none!important}",
        "body .node-link-visual circle{fill:#EAF2F7;stroke:var(--visual-accent-2);stroke-width:3;}"
        "body .node-link-visual text{fill:var(--visual-ink)}",
        "body button{background:var(--visual-accent);color:#FFFFFF}",
        "@media(prefers-color-scheme:dark){body .metric-card>*{background:#20322C}}",
    ))


__all__ = ["accessibility_guard_css", "visual_theme_css"]

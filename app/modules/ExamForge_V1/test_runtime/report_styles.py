"""프론트엔드 디자인 토큰 기반 보고서 CSS."""
from __future__ import annotations


def frontend_report_css() -> str:
    """frontend-web의 MockExam 화면 규칙을 정적 HTML용으로 변환한다."""
    return """
:root{
  --bg:#F9F8F3;--paper:#FFFDF7;--surface:#FFFFFF;--ink:#1F2A30;
  --ink-2:#55646C;--ink-3:#7B878B;--muted:#9FA8AA;--line:#DED8CA;
  --line-2:#ECE6D8;--grass-1:#207B4C;--grass-2:#36B36F;--grass-3:#ADD87B;
  --grass-wash:#E7F3E8;--coral:#FF7D87;--coral-wash:#FDECEF;
  --sand:#F4F0E5;--surface-muted:#F4F0E5;--shadow-md:0 4px 14px -8px rgba(28,32,20,.08),0 1px 2px rgba(28,32,20,.03);
  --shadow-lg:0 20px 40px -20px rgba(28,32,20,.14),0 2px 6px rgba(28,32,20,.04);
  --page-px:28px;--page-py:24px;--section-gap:20px;--page-max-w:1600px;
  --surface-page:var(--bg);--surface-card:var(--paper);--surface-subtle:var(--surface-muted);
  --text-primary:var(--ink);--text-secondary:var(--ink-2);--text-tertiary:var(--ink-3);
  --border-default:var(--line);--border-soft:var(--line-2);--accent-primary:var(--grass-1);
  --accent-strong:var(--grass-2);--accent-soft:var(--grass-wash);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);font-family:Pretendard,Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased}
body{min-height:100vh}
.page{padding:var(--page-py) var(--page-px);max-width:var(--page-max-w);margin:0 auto}
.intro{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:var(--section-gap)}
.eyebrow{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.14em;line-height:1.4;color:var(--text-tertiary)}
.title{margin-top:6px;font-size:32px;font-weight:850;letter-spacing:0;line-height:1.15;color:var(--text-primary)}
.script{font-family:cursive;color:var(--accent-primary);margin-right:6px}
.desc{margin-top:6px;font-size:13px;font-weight:500;line-height:1.6;color:var(--text-secondary)}
.layout{display:grid;grid-template-columns:1fr 300px;gap:var(--section-gap)}
.main{display:flex;flex-direction:column;gap:var(--section-gap)}
.aside{display:flex;flex-direction:column;gap:14px}
.section,.panel{background:var(--surface-card);border:1px solid var(--border-default);border-radius:16px;box-shadow:var(--shadow-md);overflow:hidden}
.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:16px 20px 12px;border-bottom:1px solid var(--border-soft)}
.section-title{font-size:14px;font-weight:800;line-height:1.45;color:var(--text-primary)}
.section-desc{font-size:12px;font-weight:500;line-height:1.6;color:var(--text-tertiary);margin-top:2px}
.body{padding:16px 20px}
.inspector{background:var(--surface-subtle);border:1px solid var(--border-soft);border-radius:14px;overflow:hidden}
.inspector-title{padding:12px 16px 10px;border-bottom:1px solid var(--border-soft);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text-tertiary)}
.inspector-body{padding:14px 16px}
.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.metric{padding:8px 10px;border-radius:8px;background:var(--surface-page);border:1px solid var(--border-soft);text-align:center}
.metric-k{font-size:10px;font-weight:700;color:var(--text-tertiary);letter-spacing:.04em}
.metric-v{font-size:15px;font-weight:800;color:var(--text-primary);margin-top:2px}
.badge{display:inline-flex;align-items:center;border-radius:999px;background:var(--accent-soft);color:var(--accent-primary);border:1px solid var(--border-soft);font-size:11px;font-weight:800;padding:4px 8px}
.raw{white-space:pre-wrap;word-break:break-word;margin:0;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;line-height:1.6;color:var(--text-primary)}
.frame{width:100%;min-height:640px;border:1px solid var(--border-soft);border-radius:12px;background:var(--surface);box-shadow:var(--shadow-md)}
.split{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.warn{padding:12px 14px;border-radius:10px;background:var(--coral-wash);border:1px solid var(--coral);font-size:12px;color:#C2425B;line-height:1.6}
.small{font-size:11px;color:var(--text-tertiary);line-height:1.6}
@media(max-width:1023px){.layout{grid-template-columns:1fr}.metric-grid,.split{grid-template-columns:1fr}.page{padding:22px}}
"""

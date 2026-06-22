#!/usr/bin/env python3
"""Inject a self-contained dark-mode toggle into static pages.

Each page embeds its own CSS with hardcoded light colors, so rather than refactor
every page to variables we layer `html[data-theme=dark]` overrides (higher
specificity than the bare element/class rules) covering every light-background
class used across the index and both post structures (agent posts put content
directly in <body>; generator posts wrap it in .container). A floating 🌙/☀️
button toggles and persists the choice; the default follows the OS via
prefers-color-scheme.

Some agent posts set no <body> background (transparent), which renders broken on
a dark-OS browser even in light mode — so when a page's body rule has no
background we also pin an explicit light one.

Idempotent: skips files already containing the marker. Run:
    python out/_dark.py index.html posts/*.html
"""
import re, sys, glob

MARKER = "id=dark-theme"

DARK_CSS = """
html[data-theme=dark] body{background:#0d1117;color:#c9d1d9}
html[data-theme=dark] .container{background:#161b22;box-shadow:0 1px 3px rgba(0,0,0,.5)}
html[data-theme=dark] h1,html[data-theme=dark] h2,html[data-theme=dark] h3,html[data-theme=dark] h4{color:#e6edf3}
html[data-theme=dark] a{color:#58a6ff}
html[data-theme=dark] hr{border-color:#30363d}
html[data-theme=dark] .lead,html[data-theme=dark] .cats,html[data-theme=dark] .sub,html[data-theme=dark] .footer,html[data-theme=dark] .conf-note,html[data-theme=dark] small,html[data-theme=dark] .entry .d,html[data-theme=dark] .entry .s,html[data-theme=dark] .br .nm,html[data-theme=dark] .bucket-bar .nm{color:#8b949e}
html[data-theme=dark] .entry,html[data-theme=dark] .entry .t{color:#e6edf3}
/* neutral light surfaces -> dark slate */
html[data-theme=dark] .meta,html[data-theme=dark] .home,html[data-theme=dark] .skim,html[data-theme=dark] .roi-item,html[data-theme=dark] .tc,html[data-theme=dark] blockquote,html[data-theme=dark] .thesis,html[data-theme=dark] th,html[data-theme=dark] table.cl th,html[data-theme=dark] .entry,html[data-theme=dark] pre,html[data-theme=dark] code{background:#1c2330;border-color:#30363d;color:#c9d1d9}
html[data-theme=dark] .home:hover,html[data-theme=dark] .entry:hover{background:#222b3a;border-color:#3d4759}
html[data-theme=dark] table,html[data-theme=dark] th,html[data-theme=dark] td{border-color:#30363d}
html[data-theme=dark] .br .bar,html[data-theme=dark] .bucket-bar .bar{background:#21304a}
/* semantic tinted boxes -> dark tint + readable accent text */
html[data-theme=dark] .ins,html[data-theme=dark] .action-card{background:#13241b;border-color:#1f3b2a}
html[data-theme=dark] .hot,html[data-theme=dark] .hot-box{background:#291719;border-color:#4a2327}
html[data-theme=dark] .cold,html[data-theme=dark] .cold-box,html[data-theme=dark] .pred-card{background:#15212f;border-color:#243a52}
html[data-theme=dark] .dd,html[data-theme=dark] .theme-card{background:#272110;border-color:#473c14}
html[data-theme=dark] .risk{background:#271d10;border-color:#473414}
html[data-theme=dark] .pill{background:#272110;color:#fcd34d;border-color:#473c14}
html[data-theme=dark] .tag{background:#272110;color:#fcd34d;border-color:#473c14}
html[data-theme=dark] .pill.a{background:#291719;color:#fca5a5;border-color:#4a2327}
html[data-theme=dark] .pill.b{background:#15212f;color:#93c5fd;border-color:#243a52}
html[data-theme=dark] .entry.wk{background:#272110;border-color:#5c4d1a}
/* floating toggle button */
#themeToggle{position:fixed;top:14px;right:14px;z-index:99;width:38px;height:38px;border-radius:50%;border:1px solid #d0d7de;background:#fff;cursor:pointer;font-size:17px;line-height:1;box-shadow:0 1px 3px rgba(0,0,0,.12);transition:transform .15s}
#themeToggle:hover{transform:scale(1.08)}
html[data-theme=dark] #themeToggle{background:#21262d;border-color:#30363d;color:#e6edf3}
@media print{#themeToggle{display:none}}
"""

LIGHT_BODY = "html[data-theme=light] body{background-color:#fff}\n"

INIT_SCRIPT = "<script>(function(){try{var k='theme',s=localStorage.getItem(k);if(!s)s=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';document.documentElement.dataset.theme=s;}catch(e){}})();</script>\n"

BODY_BLOCK = """<button id=themeToggle type=button aria-label="다크 모드 전환">🌙</button>
<script>(function(){var k='theme',r=document.documentElement,b=document.getElementById('themeToggle');function u(){b.textContent=r.dataset.theme==='dark'?'☀️':'🌙';}u();b.addEventListener('click',function(){r.dataset.theme=r.dataset.theme==='dark'?'light':'dark';try{localStorage.setItem(k,r.dataset.theme);}catch(e){}u();});})();</script>
"""


def body_has_background(html):
    m = re.search(r'(?:^|[{}\s,])body\s*\{([^{}]*)\}', html)
    return bool(m and re.search(r'background', m.group(1)))


def inject(html):
    if MARKER in html:
        return html, False
    head = "<style id=dark-theme>" + DARK_CSS
    if not body_has_background(html):
        head += LIGHT_BODY
    head += "</style>\n" + INIT_SCRIPT
    if "</head>" in html:
        html = html.replace("</head>", head + "</head>", 1)
    else:
        html = head + html
    if "</body>" in html:
        html = html.replace("</body>", BODY_BLOCK + "</body>", 1)
    else:
        html = html + BODY_BLOCK
    return html, True


def main(argv):
    files = []
    for a in argv:
        files.extend(glob.glob(a))
    for path in sorted(set(files)):
        h = open(path, encoding="utf-8").read()
        h2, changed = inject(h)
        if changed:
            open(path, "w", encoding="utf-8").write(h2)
            print(f"  injected {path}  (light-body fix: {not body_has_background(h)})")
        else:
            print(f"  already has toggle: {path}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["index.html"] + glob.glob("posts/*.html"))

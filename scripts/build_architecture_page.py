"""Generate docs/architecture-vN.html FROM uml/.

The page is never authored by hand and never replaces uml/ — it is the
send-to-someone-who-will-not-clone-the-repo view. If the two ever disagree,
uml/ is right: it is the one under review.

  python3 scripts/build_architecture_page.py

Contract honoured here:
  * §0 master diagram is inline SVG, hand-laid, no CDN and no JavaScript.
  * Every other diagram renders client-side but falls back to showing its own
    source text when the library cannot load.
"""
from html import escape
from pathlib import Path
import datetime
import re

ROOT = Path(__file__).resolve().parent.parent
UML = ROOT / "uml"
VERSION = "v1"
OUT = ROOT / "docs" / f"architecture-{VERSION}.html"

SECTIONS = [
    ("01-hld.md", "Zoom level 1 — High-level design"),
    ("02-lld.md", "Zoom level 2 — Low-level design"),
    ("03-data-model.md", "Zoom level 3 — Data model"),
    ("04-sequences.md", "Zoom level 4 — Sequences"),
    ("05-state-machines.md", "Zoom level 5 — State machines"),
    ("06-activity.md", "Zoom level 6 — Activity"),
]

# ── minimal markdown ────────────────────────────────────────────────────────
# Deliberately small: it handles exactly the constructs uml/ uses. Anything
# fancier belongs in the diagrams, not in the prose around them.

def inline(t):
    t = escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", t)
    t = t.replace("~str~", "&lt;str&gt;")
    return t


def convert(md, diagrams, slug):
    """Markdown -> HTML. Mermaid fences become fallback-first diagram blocks."""
    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]

        if ln.startswith("```"):
            lang = ln[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            src = "\n".join(buf)
            if lang == "mermaid":
                n = len(diagrams) + 1
                diagrams.append(src)
                out.append(
                    f'<figure class="diagram" data-mmd id="{slug}-d{n}">'
                    f'<pre class="mmd-src"><code>{escape(src)}</code></pre>'
                    f'<figcaption class="fallback-note">Diagram source &mdash; '
                    f'renders as a diagram when the Mermaid library loads.</figcaption>'
                    f"</figure>"
                )
            else:
                cls = f' class="lang-{lang}"' if lang else ""
                out.append(f"<pre{cls}><code>{escape(src)}</code></pre>")
            continue

        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            out.append(f"<h{min(lvl + 1, 6)}>{inline(ln[lvl:].strip())}</h{min(lvl + 1, 6)}>")
            i += 1
            continue

        if ln.strip() in ("---", "***"):
            out.append("<hr>")
            i += 1
            continue

        if ln.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].startswith("|"):
                tbl.append(lines[i])
                i += 1
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl]
            body = [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{inline(c)}</th>" for c in rows[0])
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                                 for r in body)
                       + "</tbody></table>")
            continue

        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(buf))}</p></blockquote>")
            continue

        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
        if m:
            ordered = not m.group(2) in ("-", "*")
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines):
                mm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
                if mm and (not mm.group(2) in ("-", "*")) == ordered and len(mm.group(1)) < 3:
                    items.append(mm.group(3))
                    i += 1
                    # fold indented continuation lines into the same item
                    while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() \
                            and not re.match(r"^\s*([-*]|\d+\.)\s", lines[i]):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                elif lines[i].strip() == "" and i + 1 < len(lines) and \
                        re.match(r"^(\s*)([-*]|\d+\.)\s+", lines[i + 1] or ""):
                    i += 1
                else:
                    break
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue

        if ln.strip() == "":
            i += 1
            continue

        buf = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", ">", "```")) \
                and not re.match(r"^(\s*)([-*]|\d+\.)\s+", lines[i]) and lines[i].strip() not in ("---", "***"):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append(f"<p>{inline(' '.join(buf))}</p>")
    return "\n".join(out)


# ── assemble ────────────────────────────────────────────────────────────────
master = (UML / "master.svg").read_text(encoding="utf-8")
master = re.sub(r"^<\?xml[^>]*\?>\s*", "", master)

readme = (UML / "README.md").read_text(encoding="utf-8")
all_diagrams = []
body = []

body.append('<section id="s0"><h2>&sect;0 &nbsp;Master diagram</h2>')
body.append(
    "<p>The whole system on one canvas. This one is hand-laid inline SVG with no "
    "library, no CDN and no JavaScript &mdash; it is the block that must survive a "
    "locked-down machine, an offline laptop or a projector with no network. "
    "Source: <code>uml/master.svg</code>.</p>"
)
body.append(f'<div class="master">{master}</div>')

# the one fact + problem IDs, lifted from uml/README.md
one_fact = re.search(r"## The one fact to read first\n(.*?)\n---", readme, re.S).group(1)
probs = re.search(r"## Problem IDs\n(.*?)\n---", readme, re.S).group(1)
body.append('<h3>The one fact to read first</h3>')
body.append(convert(one_fact, all_diagrams, "fact"))
body.append('<h3>Problem IDs</h3>')
body.append(convert(probs, all_diagrams, "prob"))
body.append("</section>")

toc = ['<li><a href="#s0">&sect;0 &nbsp;Master diagram</a></li>']
for n, (fn, title) in enumerate(SECTIONS, start=1):
    slug = f"s{n}"
    md = (UML / fn).read_text(encoding="utf-8")
    md = "\n".join(md.split("\n")[1:])  # drop the file's own H1
    before = len(all_diagrams)
    html = convert(md, all_diagrams, slug)
    count = len(all_diagrams) - before
    toc.append(f'<li><a href="#{slug}">&sect;{n} &nbsp;{escape(title)}</a> '
               f'<span class="dcount">{count} diagrams</span></li>')
    body.append(f'<section id="{slug}"><h2>&sect;{n} &nbsp;{escape(title)}</h2>'
                f'<p class="src-note">Generated from <code>uml/{fn}</code>.</p>{html}</section>')

changelog = Path(ROOT / "uml" / "CHANGELOG-v1.md")
changelog_md = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
n = len(SECTIONS) + 1
toc.append(f'<li><a href="#s{n}">&sect;{n} &nbsp;What changed</a></li>')
body.append(f'<section id="s{n}"><h2>&sect;{n} &nbsp;What changed since the previous version</h2>'
            f'{convert(changelog_md, all_diagrams, "chg")}</section>')

built = datetime.date.today().isoformat()
ndia = len(all_diagrams)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Citizen Legal Help &mdash; Architecture {VERSION}</title>
<style>
:root {{
  --bg:#ffffff; --panel:#f6f8fc; --ink:#161d2b; --muted:#5a6577; --line:#d7dde8;
  --accent:#1a73e8; --code-bg:#f2f4f9; --warn-bg:#fef7e0; --warn-line:#f9ab00;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:#12151c; --panel:#1a1f2b; --ink:#eef1f7; --muted:#9aa5b8; --line:#2e3646;
    --accent:#5b9bf8; --code-bg:#1c2230; --warn-bg:#2a2311; --warn-line:#b8860b;
  }}
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}}
header.page {{
  padding:36px 24px 28px; border-bottom:1px solid var(--line); background:var(--panel);
}}
header.page h1 {{ margin:0 0 6px; font-size:28px; letter-spacing:-.01em; }}
header.page .meta {{ color:var(--muted); font-size:14px; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:0 24px 80px; }}
nav.toc {{
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:18px 22px; margin:28px 0 36px;
}}
nav.toc h2 {{ margin:0 0 10px; font-size:14px; text-transform:uppercase;
  letter-spacing:.08em; color:var(--muted); border:0; padding:0; }}
nav.toc ol {{ margin:0; padding-left:20px; }}
nav.toc li {{ margin:4px 0; }}
nav.toc a {{ color:var(--accent); text-decoration:none; }}
nav.toc a:hover {{ text-decoration:underline; }}
.dcount {{ color:var(--muted); font-size:13px; }}
section {{ margin:0 0 56px; scroll-margin-top:20px; }}
h2 {{ font-size:23px; margin:48px 0 14px; padding-bottom:8px;
  border-bottom:2px solid var(--line); letter-spacing:-.01em; }}
h3 {{ font-size:18px; margin:32px 0 10px; }}
h4 {{ font-size:15px; margin:24px 0 8px; color:var(--muted);
  text-transform:uppercase; letter-spacing:.05em; }}
p, li {{ max-width:78ch; }}
a {{ color:var(--accent); }}
code {{
  background:var(--code-bg); padding:.12em .36em; border-radius:4px;
  font:13.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}}
pre {{
  background:var(--code-bg); border:1px solid var(--line); border-radius:8px;
  padding:14px 16px; overflow-x:auto;
}}
pre code {{ background:none; padding:0; font-size:12.5px; line-height:1.5; }}
blockquote {{
  margin:18px 0; padding:12px 18px; border-left:4px solid var(--accent);
  background:var(--panel); border-radius:0 8px 8px 0;
}}
blockquote p {{ margin:0; }}
table {{ border-collapse:collapse; margin:18px 0; font-size:14.5px; width:100%; }}
th, td {{ border:1px solid var(--line); padding:8px 11px; text-align:left;
  vertical-align:top; }}
td code, th code {{ overflow-wrap:anywhere; }}
@media (max-width:760px) {{
  .wrap {{ padding:0 16px 60px; }}
  table {{ display:block; overflow-x:auto; white-space:nowrap; }}
  table td, table th {{ white-space:normal; min-width:150px; }}
}}
th {{ background:var(--panel); font-weight:650; }}
hr {{ border:0; border-top:1px solid var(--line); margin:34px 0; }}
.src-note {{ color:var(--muted); font-size:13.5px; margin-top:-4px; }}
.master {{
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:14px; margin:20px 0; overflow-x:auto;
}}
.master svg {{ display:block; min-width:900px; }}
figure.diagram {{
  margin:22px 0; padding:14px; background:var(--panel);
  border:1px solid var(--line); border-radius:10px;
  max-width:100%; overflow:hidden;
}}
/* the inner wrapper is the scroll container, so a 3000px diagram never
   widens the page itself */
figure.diagram .mmd-out {{ overflow-x:auto; max-width:100%; }}
figure.diagram pre.mmd-src {{ margin:0; background:var(--code-bg); }}
figure.diagram .fallback-note {{
  margin-top:10px; font-size:12.5px; color:var(--muted);
}}
figure.diagram.rendered pre.mmd-src,
figure.diagram.rendered .fallback-note {{ display:none; }}
figure.diagram .mmd-out svg {{
  /* Render at true size and let the figure scroll. Fitting a 3000px
     sequence diagram into 1100px shrinks its text past legibility,
     which is the one thing a diagram cannot survive. */
  display:block; height:auto !important; max-width:none !important;
}}
figure.diagram .scroll-hint {{ font-size:12.5px; color:var(--muted); margin:0 0 8px; }}
footer.page {{
  border-top:1px solid var(--line); padding:26px 24px; color:var(--muted);
  font-size:13.5px; background:var(--panel);
}}
</style>
</head>
<body>
<header class="page">
  <h1>Citizen Legal Help &mdash; Architecture <span style="color:var(--muted)">{VERSION}</span></h1>
  <div class="meta">
    Generated from <code>uml/</code> on {built} &middot; {ndia} client-rendered diagrams
    plus one library-free master &middot; a fix belongs in both, in the same commit.
  </div>
</header>
<div class="wrap">
<nav class="toc">
  <h2>Contents</h2>
  <ol>{''.join(toc)}</ol>
</nav>
{''.join(body)}
</div>
<footer class="page">
  Diagrams are the source of truth in <code>uml/</code>; this page is generated from them.
  Every block below &sect;0 shows its own Mermaid source when the rendering library
  cannot load. &sect;0 needs no library at all.
</footer>
<script type="module">
// Progressive enhancement only. If this import fails - offline, blocked CDN,
// strict CSP - every figure keeps showing its own source text, which is why
// the <pre> starts visible and is hidden only after a successful render.
try {{
  const {{ default: mermaid }} = await import(
    'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'
  );
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  mermaid.initialize({{ startOnLoad:false, theme: dark ? 'dark' : 'default',
                       securityLevel:'strict', fontFamily:'system-ui, sans-serif' }});
  const figs = document.querySelectorAll('figure.diagram[data-mmd]');
  let n = 0;
  for (const fig of figs) {{
    const src = fig.querySelector('pre.mmd-src code').textContent;
    try {{
      const {{ svg }} = await mermaid.render('m' + (++n), src);
      const holder = document.createElement('div');
      holder.className = 'mmd-out';
      holder.innerHTML = svg;
      fig.prepend(holder);
      // Mermaid emits width="100%", which stretches or squashes the drawing to
      // the container. Pin it to the viewBox's own width so text renders at the
      // size it was laid out for; the figure scrolls when that exceeds the page.
      const el = holder.querySelector('svg');
      const vb = el && el.getAttribute('viewBox');
      if (vb) {{
        const w = Math.ceil(parseFloat(vb.split(/[ ,]+/)[2]));
        if (w > 0) {{
          el.removeAttribute('width');
          el.style.width = w + 'px';
          if (w > fig.clientWidth - 28) {{
            const hint = document.createElement('p');
            hint.className = 'scroll-hint';
            hint.textContent = 'Wide diagram \u2014 scroll sideways to follow it.';
            fig.prepend(hint);
          }}
        }}
      }}
      fig.classList.add('rendered');
    }} catch (e) {{
      // this one diagram stays as source; the rest still render
      console.warn('diagram failed to render', fig.id, e);
    }}
  }}
}} catch (e) {{
  console.warn('Mermaid unavailable - showing diagram sources instead', e);
}}
</script>
</body>
</html>
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size:,} bytes, {ndia} mermaid diagrams)")

"""Emit uml/master.svg — the whole system on one canvas.

Coordinates are explicit and hand-chosen: the master diagram must render with
no network, no JavaScript and no layout engine, so nothing here is computed by
a graph library. Styling lives in a <style> element inside the SVG so the file
is also correct when opened on its own, outside the architecture page.
"""
from pathlib import Path

W, H = 1280, 980
out = []
add = out.append


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def band(x, y, w, h, label, detail="", cls="band"):
    """Short name at top-left, detail right-aligned at top-right.

    The name is kept short on purpose: arrows enter these bands from above, and
    a long top-left label is the one thing they collide with.
    """
    add(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="10"/>')
    add(f'<text class="bandlabel" x="{x + 14}" y="{y + 20}">{esc(label)}</text>')
    if detail:
        add(f'<text class="bandlabel" style="font-weight:400" x="{x + w - 14}" '
            f'y="{y + 20}" text-anchor="end">{esc(detail)}</text>')


def box(x, y, w, h, title, lines=(), cls="box"):
    add(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')
    cx = x + w / 2
    add(f'<text class="title" x="{cx:g}" y="{y + 20}">{esc(title)}</text>')
    for i, ln in enumerate(lines):
        add(f'<text class="sub" x="{cx:g}" y="{y + 38 + i * 15}">{esc(ln)}</text>')


def actor(x, y, w, h, title, sub):
    add(f'<rect class="actor" x="{x}" y="{y}" width="{w}" height="{h}" rx="20"/>')
    cx = x + w / 2
    add(f'<text class="title" x="{cx:g}" y="{y + 22}">{esc(title)}</text>')
    add(f'<text class="sub" x="{cx:g}" y="{y + 38}">{esc(sub)}</text>')


def arrow(d, cls="edge", label=None, lx=0, ly=0, anchor="middle"):
    add(f'<path class="{cls}" d="{d}" marker-end="url(#ah)"/>')
    if label:
        add(f'<text class="elabel" x="{lx:g}" y="{ly:g}" text-anchor="{anchor}">{esc(label)}</text>')


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
    f'role="img" aria-label="Citizen Legal Help — whole-system master diagram">')
add('<title>Citizen Legal Help — master diagram</title>')
add("""<style>
  .bg{fill:#ffffff}
  .band{fill:#f6f8fc;stroke:#c3cad8;stroke-width:1.5}
  .bandext{fill:#fffaf2;stroke:#e0a760;stroke-width:1.5}
  .banddata{fill:#faf5ff;stroke:#b9a0e8;stroke-width:1.5}
  .bandlabel{font:600 12px system-ui,-apple-system,Segoe UI,sans-serif;fill:#5a6577;letter-spacing:.04em}
  .box{fill:#eef2fd;stroke:#7d93d6;stroke-width:1.4}
  .boxhot{fill:#d8e4fd;stroke:#1a73e8;stroke-width:2.2}
  .boxfree{fill:#e3f5e8;stroke:#1e8e3e;stroke-width:1.6}
  .boxpaid{fill:#fdeaea;stroke:#d93025;stroke-width:1.6}
  .boxext{fill:#fdefdc;stroke:#d9822b;stroke-width:1.6}
  .boxdata{fill:#f2e9fe;stroke:#8b5cf6;stroke-width:1.5}
  .actor{fill:#ffffff;stroke:#5a6577;stroke-width:1.6}
  .title{font:700 12.5px system-ui,-apple-system,Segoe UI,sans-serif;fill:#161d2b;text-anchor:middle}
  .sub{font:400 11px system-ui,-apple-system,Segoe UI,sans-serif;fill:#414b5c;text-anchor:middle}
  .elabel{font:600 10.5px system-ui,-apple-system,Segoe UI,sans-serif;fill:#2b3546}
  .edge{fill:none;stroke:#5a6577;stroke-width:1.5}
  .edgefree{fill:none;stroke:#1e8e3e;stroke-width:1.8}
  .edgepaid{fill:none;stroke:#d93025;stroke-width:1.8}
  .edgeplan{fill:none;stroke:#9aa0a6;stroke-width:1.5;stroke-dasharray:6 4}
  .note{font:400 10.5px system-ui,-apple-system,Segoe UI,sans-serif;fill:#5a6577}
  .key{font:600 11px system-ui,-apple-system,Segoe UI,sans-serif;fill:#2b3546}
  @media (prefers-color-scheme: dark){
    .bg{fill:#12151c}
    .band{fill:#1a1f2b;stroke:#3a4356}
    .bandext{fill:#241d13;stroke:#7a5426}
    .banddata{fill:#201a2e;stroke:#5c4899}
    .bandlabel{fill:#9aa5b8}
    .box{fill:#1e2740;stroke:#6b82c9}
    .boxhot{fill:#1e3358;stroke:#5b9bf8}
    .boxfree{fill:#14301e;stroke:#3ea55f}
    .boxpaid{fill:#331717;stroke:#e06055}
    .boxext{fill:#2c2112;stroke:#d9822b}
    .boxdata{fill:#251b38;stroke:#a483f0}
    .actor{fill:#1a1f2b;stroke:#9aa5b8}
    .title{fill:#eef1f7}
    .sub{fill:#b9c2d2}
    .elabel{fill:#cdd5e3}
    .edge{stroke:#8d99ad}
    .note{fill:#9aa5b8}
    .key{fill:#cdd5e3}
  }
</style>""")
add('<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
    'markerHeight="7" orient="auto-start-reverse">'
    '<path d="M0,0 L10,5 L0,10 z" fill="#5a6577"/></marker></defs>')
add(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')

# ── actors ────────────────────────────────────────────────────────────────
actor(40, 14, 210, 50, "Citizen", "asks in everyday language")
actor(380, 14, 210, 50, "Admin", "email listed in ADMIN_EMAILS")

# ── browser ───────────────────────────────────────────────────────────────
band(28, 84, 872, 118, "BROWSER", "React 19 · Vite :5173 · Context only, no state library")
box(46, 108, 168, 76, "Chat.jsx", ["messages · sessionId", "sessions · isLoading"])
box(228, 108, 150, 76, "Sidebar.jsx", ["list · search", "rename · delete"])
box(392, 108, 140, 76, "Admin.jsx", ["metrics table", "(P9)"])
box(546, 108, 150, 76, "LoginModal", ["email, then", "6-digit code"])
box(710, 108, 172, 76, "api/client.js", ["the ONLY fetch layer", "Bearer from localStorage"], cls="boxhot")

# ── backend ───────────────────────────────────────────────────────────────
band(28, 232, 872, 566, "BACKEND", "FastAPI :8000 · uvicorn · sync def on threadpool")
box(46, 256, 396, 56, "api.py", ["10 routes · Pydantic validation · CORS allow-list"])
box(460, 256, 422, 56, "auth.py — dependency ladder", ["optional  →  required  →  admin   (P6)"])

box(46, 336, 836, 46, "pipeline.answer_question", ["the only place the three branches meet"], cls="boxhot")
box(46, 406, 268, 50, "classify_intent", ["regex fast path, then Gemini"])

box(46, 486, 250, 74, "CHITCHAT", ["hardcoded reply", "0 Gemini · 0 IKanoon · ₹0"], cls="boxfree")
box(316, 486, 268, 74, "FOLLOW_UP", ["reuse session.last_context_text", "if the check returns True → ₹0"], cls="boxfree")
box(604, 486, 278, 74, "NEW_QUERY", ["rewrite_query  (P1)", "then look in the cache"])

box(604, 584, 278, 46, "query_cache lookup", ["hit → 0 IKanoon calls   (P7)"], cls="boxfree")
box(316, 656, 566, 62, "build_context — 1 search + 5 parallel doc fetches (P4)",
    ["extract Issue / Facts / Conclusion only, ~90% fewer tokens (P2)", "₹0.50–0.90 per question"], cls="boxpaid")
box(46, 742, 836, 42, "attach_disclaimer_and_attribution — every non-CHITCHAT path (P8)", [], cls="boxhot")

# ── external ──────────────────────────────────────────────────────────────
band(930, 232, 322, 330, "EXTERNAL", "we own none of this")
box(946, 258, 290, 86, "Indian Kanoon API",
    ["POST /search/ · POST /doc/{tid}/", "keyword only · PREPAID, no grace period", "the entire legal corpus"], cls="boxext")
box(946, 360, 290, 86, "Google Gemini API",
    ["gemini-2.5-flash", "4 call sites: route · rewrite ·", "context-check · explain"], cls="boxext")
box(946, 462, 290, 60, "SMTP", ["OTP delivery, or console log", "when unconfigured"], cls="boxext")

# ── data ──────────────────────────────────────────────────────────────────
band(930, 590, 322, 222, "DATA", "SQLite · legal.db", cls="banddata")
box(946, 616, 138, 44, "users", ["id · email"], cls="boxdata")
box(1096, 616, 140, 44, "otps", ["⚠ plaintext code"], cls="boxdata")
box(946, 672, 138, 44, "sessions", ["last_context_text"], cls="boxdata")
box(1096, 672, 140, 44, "messages", ["append-only"], cls="boxdata")
box(946, 728, 138, 60, "query_cache", ["key = rewritten", "⚠ no TTL"], cls="boxdata")
box(1096, 728, 140, 60, "query_logs", ["latency · intent", "no user_id"], cls="boxdata")

# ── edges ─────────────────────────────────────────────────────────────────
arrow("M 145 64 L 145 108", label="question", lx=150, ly=82, anchor="start")
arrow("M 485 64 L 462 108", label="/admin", lx=500, ly=86, anchor="start")
arrow("M 796 184 L 796 214 L 300 214 L 300 256", label="fetch · JSON · Bearer", lx=548, ly=228)
arrow("M 244 312 L 244 336")
arrow("M 671 312 L 671 326 L 640 326 L 640 336", label="user_id or None", lx=700, ly=330, anchor="start")
arrow("M 180 382 L 180 406")
arrow("M 140 456 L 140 486", cls="edgefree")
arrow("M 230 456 L 230 470 L 430 470 L 430 486", cls="edgefree", label="RouteIntent", lx=330, ly=466)
arrow("M 300 428 L 743 428 L 743 486", label="NEW_QUERY", lx=752, ly=452, anchor="start")
arrow("M 743 560 L 743 584")
arrow("M 743 630 L 743 644 L 620 644 L 620 656", cls="edgepaid", label="None → pay", lx=760, ly=648, anchor="start")
arrow("M 430 560 L 430 656", cls="edgepaid", label="False", lx=436, ly=600, anchor="start")
arrow("M 140 560 L 140 742", cls="edgefree")
arrow("M 380 560 L 380 600 L 250 600 L 250 730 L 300 742", cls="edgefree", label="True", lx=256, ly=596, anchor="start")
arrow("M 599 718 L 599 742")
arrow("M 882 687 L 906 687 L 906 301 L 946 301", cls="edgepaid")
arrow("M 882 359 L 914 359 L 914 403 L 946 403")
arrow("M 882 284 L 922 284 L 922 492 L 946 492")
arrow("M 882 763 L 890 763 L 890 700 L 930 700")

# ── key ───────────────────────────────────────────────────────────────────
add('<text class="key" x="40" y="838">Reading the colours</text>')
add('<rect class="boxfree" x="40" y="850" width="18" height="14" rx="3"/>')
add('<text class="note" x="66" y="861">₹0 in Indian Kanoon fees — three of five paths (P3)</text>')
add('<rect class="boxpaid" x="40" y="872" width="18" height="14" rx="3"/>')
add('<text class="note" x="66" y="883">₹0.50–0.90 per question — the paid retrieval path</text>')
add('<rect class="boxhot" x="40" y="894" width="18" height="14" rx="3"/>')
add('<text class="note" x="66" y="905">the seams everything else routes through</text>')
add('<text class="note" x="40" y="932">⚠ marks a known defect, drawn where it lives. P-numbers are problem IDs — see uml/README.md.</text>')
add('<text class="note" x="40" y="952">The system owns no legal corpus: every answer&#8217;s law is fetched from Indian Kanoon at request time.</text>')
add('<text class="note" x="40" y="968">That one constraint explains the router, the rewriter, the extractor and the cache.</text>')

add("</svg>")

p = Path("uml/master.svg")
p.write_text("\n".join(out), encoding="utf-8")
print(f"wrote {p} ({p.stat().st_size} bytes)")

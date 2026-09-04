"""Renders an OKF-format wiki/ directory (see repo-root AGENTS.md) as a set
of static, self-contained HTML files you open directly in a browser - no
server, no CI, no publish step. Same "just open the file" pattern as
engine/report.py and engine/bootstrap/report.py, applied to a whole wiki
instead of one run's output.

Deliberately decoupled from generate.py: this only reads whatever .md files
already exist under --wiki. No LLM calls, no API key, works on hand-written
pages just as well as generated ones.

One HTML file per wiki page (mirroring the summaries/entities/concepts/log
directory structure) plus one index.html with a client-side filter box -
chosen over a single giant page specifically so this doesn't fall over once
a real wiki grows into hundreds or thousands of pages, even though today's
wikis here are more like 20-50 pages.

Markdown->HTML is a small, deliberately narrow hand-rolled pass covering just
what this project's wiki pages actually contain (headers, bold, inline code,
links, bullet lists, pipe tables, footnote references) - not a general
CommonMark parser. Same philosophy as engine/report.py's render_prose and
engine/bootstrap/schema.py's narrow OpenAPI slice: match the real, bounded
shape of the input instead of adding a dependency for arbitrary input this
project never produces.

Images referenced from a page (`![alt](path)`) are resolved against the page's
own directory, then the wiki root, then the repo root, copied into
<out>/assets/, and the page rewritten to point at the copy - so a page keeps
working regardless of how deep --wiki and --out sit relative to each other or
to the images' real location.

An image a page only *cites* - a `sources:` entry whose resource is an image -
is copied in and shown too, above the body, unless the body already shows that
same file inline. That is how the game wiki carries its screenshots: those
pages were written from screenshots they then cite by a path into a gitignored
directory, so without this the site names evidence that nobody reading it can
see. Cited files of any kind get a link to the copy.

Run:
  python render_html.py --wiki sample-wiki --out results/site
  python render_html.py --wiki results/wiki --out results/site   # after generate.py
  python render_html.py --wiki results/game-wiki/wiki --out results/game-wiki/site
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


# --- frontmatter parsing ---------------------------------------------------
# Narrow, tailored to exactly the shapes generate.py's own renderer (and the
# repo-root AGENTS.md template) produce: flat scalars, `tags: [a, b]` /
# `tags: []` inline lists, `generated: { by: ..., at: "..." }` inline flow
# maps, and a `sources:` block list of flat maps. Not a general YAML parser.

def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _parse_inline_list(s: str) -> list[str]:
    inner = s.strip().strip("[]").strip()
    if not inner:
        return []
    return [_strip_quotes(x) for x in inner.split(",")]


def _parse_inline_map(s: str) -> dict:
    inner = s.strip().strip("{}").strip()
    if not inner:
        return {}
    out = {}
    for part in inner.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out[k.strip()] = _strip_quotes(v.strip())
    return out


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_text = text[3:end]
    body = text[end + 4:].lstrip("\n")

    meta: dict = {}
    lines = fm_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()

        if key == "sources" and rest == "":
            entries = []
            i += 1
            current = None
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                item = lines[i]
                if not item.strip():
                    i += 1
                    continue
                stripped = item.strip()
                if stripped.startswith("- "):
                    current = {}
                    entries.append(current)
                    stripped = stripped[2:]
                if current is not None and ":" in stripped:
                    k2, _, v2 = stripped.partition(":")
                    current[k2.strip()] = _strip_quotes(v2.strip())
                i += 1
            meta[key] = entries
            continue

        if rest.startswith("[") :
            meta[key] = _parse_inline_list(rest)
        elif rest.startswith("{"):
            meta[key] = _parse_inline_map(rest)
        elif rest == "":
            meta[key] = None
        else:
            meta[key] = _strip_quotes(rest)
        i += 1

    return meta, body


# --- narrow markdown -> HTML ------------------------------------------------

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+?)`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_FOOTNOTE_REF_RE = re.compile(r"\[\^([\w-]+)\]")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([\w-]+)\]:\s*(.*)$")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$")


@dataclass
class RenderContext:
    page_dir: Path      # directory the source .md file lives in
    wiki_dir: Path       # root of the wiki bundle being rendered
    out_dir: Path        # directory the output .html file will live in
    assets_dir: Path      # <out-root>/assets
    footnote_ids: list = field(default_factory=list)
    inlined_images: set = field(default_factory=set)   # resolved paths the body already shows


def _asset_dest_name(src: Path) -> str:
    digest = hashlib.sha1(str(src.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{digest}-{src.name}"


def _resolve_asset(raw_href: str, ctx: RenderContext) -> Path | None:
    """Where a referenced file actually is.

    Three bases, because two different kinds of reference arrive here. An inline
    `![](...)` is written relative to the page, while a `sources[].resource` is
    written relative to a root: the repo root for a wiki whose evidence lives
    elsewhere in the repo (the game wiki cites game-ontology's `out/`), or the
    wiki's own directory for one that carries its raw material inside it.
    Trying each in turn beats making the caller know which kind it holds.
    """
    for base in (ctx.page_dir, ctx.wiki_dir, REPO_ROOT):
        candidate = (base / raw_href).resolve()
        if candidate.exists():
            return candidate
    return None


def _copy_asset(src_path: Path, ctx: RenderContext) -> str:
    dest_name = _asset_dest_name(src_path)
    ctx.assets_dir.mkdir(parents=True, exist_ok=True)
    dest_path = ctx.assets_dir / dest_name
    if not dest_path.exists():
        shutil.copyfile(src_path, dest_path)
    rel = Path(_relpath(ctx.out_dir, ctx.assets_dir)) / dest_name
    return rel.as_posix()


def _resolve_and_copy_image(raw_href: str, ctx: RenderContext) -> str | None:
    if raw_href.startswith(("http://", "https://", "data:")):
        return raw_href
    src_path = _resolve_asset(raw_href, ctx)
    if src_path is None:
        return None
    # Remembered so a page that shows an image inline is not handed the same
    # image again from its `sources:` block. Compared as resolved paths, since
    # the two references reach the same file by different routes:
    # `../raw/funny.png` from the page against `raw/funny.png` from the root.
    ctx.inlined_images.add(src_path)
    return _copy_asset(src_path, ctx)


def _relpath(from_dir: Path, to_dir: Path) -> str:
    import os
    return Path(os.path.relpath(to_dir, from_dir)).as_posix()


def _rewrite_page_link(raw_href: str) -> str:
    if raw_href.startswith(("http://", "https://", "#")):
        return raw_href
    if raw_href.endswith(".md"):
        return raw_href[:-3] + ".html"
    return raw_href


def inline_markdown(text: str, ctx: RenderContext) -> str:
    def image_sub(m: re.Match) -> str:
        alt, href = m.group(1), m.group(2)
        resolved = _resolve_and_copy_image(href, ctx)
        if resolved is None:
            return f'<span class="broken-image" title="image not found: {html.escape(href)}">[missing image: {html.escape(alt or href)}]</span>'
        return f'<img src="{html.escape(resolved)}" alt="{html.escape(alt)}" loading="lazy">'

    def link_sub(m: re.Match) -> str:
        label, href = m.group(1), m.group(2)
        return f'<a href="{html.escape(_rewrite_page_link(href))}">{html.escape(label)}</a>'

    def footnote_sub(m: re.Match) -> str:
        fid = m.group(1)
        return f'<sup class="footnote-ref"><a href="#src-{html.escape(fid)}">[{html.escape(fid)}]</a></sup>'

    text = _IMAGE_RE.sub(image_sub, text)
    text = _LINK_RE.sub(link_sub, text)
    escaped_parts = []
    last = 0
    for m in re.finditer(r"<[^>]+>", text):
        escaped_parts.append(html.escape(text[last:m.start()]))
        escaped_parts.append(m.group(0))
        last = m.end()
    escaped_parts.append(html.escape(text[last:]))
    text = "".join(escaped_parts)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    text = _FOOTNOTE_REF_RE.sub(footnote_sub, text)
    return text


def render_markdown(body: str, ctx: RenderContext) -> str:
    lines = body.split("\n")
    out = []
    list_buf: list[str] = []
    para_buf: list[str] = []
    table_buf: list[str] = []

    def flush_list():
        if list_buf:
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_buf) + "</ul>")
            list_buf.clear()

    def flush_para():
        if para_buf:
            out.append(f"<p>{' '.join(para_buf)}</p>")
            para_buf.clear()

    def flush_table():
        if not table_buf:
            return
        rows = [r.strip().strip("|").split("|") for r in table_buf]
        rows = [[c.strip() for c in r] for r in rows]
        header, *body_rows = rows
        html_rows = ["<tr>" + "".join(f"<th>{inline_markdown(c, ctx)}</th>" for c in header) + "</tr>"]
        for r in body_rows:
            html_rows.append("<tr>" + "".join(f"<td>{inline_markdown(c, ctx)}</td>" for c in r) + "</tr>")
        out.append("<table>" + "".join(html_rows) + "</table>")
        table_buf.clear()

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.strip()

        if not line:
            flush_para(); flush_list(); flush_table()
            i += 1
            continue

        if _FOOTNOTE_DEF_RE.match(line):
            m = _FOOTNOTE_DEF_RE.match(line)
            ctx.footnote_ids.append((m.group(1), m.group(2)))
            i += 1
            continue

        if line.startswith("|"):
            flush_para(); flush_list()
            if _TABLE_SEP_RE.match(line):
                i += 1
                continue
            table_buf.append(line)
            i += 1
            continue
        else:
            flush_table()

        header_match = _HEADER_RE.match(line)
        if header_match:
            flush_para(); flush_list()
            level = min(len(header_match.group(1)) + 1, 6)
            out.append(f"<h{level}>{inline_markdown(header_match.group(2), ctx)}</h{level}>")
            i += 1
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            flush_para()
            list_buf.append(inline_markdown(bullet_match.group(1), ctx))
            i += 1
            continue

        # A plain line while a list is open is a soft-wrapped continuation of
        # the last bullet, not a new paragraph - this project's own generated
        # pages wrap long bullets across lines without a `-` on the wrap line.
        if list_buf:
            list_buf[-1] += " " + inline_markdown(line, ctx)
            i += 1
            continue

        para_buf.append(inline_markdown(line, ctx))
        i += 1

    flush_para(); flush_list(); flush_table()
    return "\n".join(out)


# --- page discovery + HTML shell -------------------------------------------

STYLE_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 860px; margin: 0 auto; padding: 2rem 1.25rem 4rem; line-height: 1.55; }
a { color: #2563eb; }
@media (prefers-color-scheme: dark) { a { color: #7db1ff; } }
nav.top { margin-bottom: 1.5rem; font-size: 0.9rem; }
nav.top a { text-decoration: none; }
.meta-box { border: 1px solid rgba(127,127,127,0.35); border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.5rem; font-size: 0.9rem; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; margin-right: 0.35rem; }
.badge.type { background: #dbeafe; color: #1e3a8a; }
.badge.status-draft { background: #fef3c7; color: #92400e; }
.badge.status-stable { background: #dcfce7; color: #166534; }
.badge.status-deprecated { background: #fee2e2; color: #991b1b; }
.badge.unverified { background: #fee2e2; color: #991b1b; }
@media (prefers-color-scheme: dark) {
  .badge.type { background: #1e3a5f; color: #bfdbfe; }
  .badge.status-draft { background: #4b3a0a; color: #fde68a; }
  .badge.status-stable { background: #0f3d24; color: #bbf7d0; }
  .badge.status-deprecated { background: #4a1414; color: #fecaca; }
  .badge.unverified { background: #4a1414; color: #fecaca; }
}
.tag { display: inline-block; background: rgba(127,127,127,0.15); border-radius: 4px; padding: 0.05rem 0.4rem; font-size: 0.75rem; margin-right: 0.3rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid rgba(127,127,127,0.35); padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }
img { max-width: 100%; border-radius: 4px; }
figure { margin: 0 0 1.5rem; }
figure img { border: 1px solid rgba(127,127,127,0.35); }
figcaption { color: rgba(127,127,127,0.9); font-size: 0.8rem; margin-top: 0.35rem; }
.sources-list { font-size: 0.85rem; }
.sources-list code { font-size: 0.8rem; }
.footnote-ref a { text-decoration: none; }
.broken-image { color: #b91c1c; font-size: 0.85rem; }
#filter-box { width: 100%; padding: 0.5rem 0.75rem; font-size: 1rem; margin-bottom: 1rem; box-sizing: border-box; }
ul.page-list { list-style: none; padding: 0; }
ul.page-list li { padding: 0.5rem 0; border-bottom: 1px solid rgba(127,127,127,0.2); }
ul.page-list .desc { color: rgba(127,127,127,0.9); font-size: 0.9rem; }
h2.group-heading { margin-top: 2rem; }
"""


def html_shell(title: str, body: str, css_href: str, extra_head: str = "") -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{html.escape(css_href)}">
{extra_head}
</head>
<body>
{body}
</body>
</html>
"""


def status_badge(status: str | None) -> str:
    status = status or "stable"
    return f'<span class="badge status-{html.escape(status)}">{html.escape(status)}</span>'


@dataclass
class Page:
    md_path: Path
    rel_out: Path   # relative to out root, e.g. summaries/foo.html
    meta: dict
    title: str
    description: str


def discover_pages(wiki_dir: Path) -> list[Page]:
    pages = []
    candidates = []
    overview = wiki_dir / "overview.md"
    if overview.exists():
        candidates.append(overview)
    for sub in ("summaries", "entities", "concepts", "log"):
        d = wiki_dir / sub
        if d.is_dir():
            candidates.extend(sorted(d.glob("*.md")))

    for md_path in candidates:
        text = md_path.read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(text)
        rel = md_path.relative_to(wiki_dir).with_suffix(".html")
        pages.append(Page(
            md_path=md_path, rel_out=rel, meta=meta,
            title=meta.get("title") or md_path.stem,
            description=meta.get("description") or "",
        ))
    return pages


def render_page(page: Page, wiki_dir: Path, out_dir: Path) -> None:
    text = page.md_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    out_path = out_dir / page.rel_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ctx = RenderContext(page_dir=page.md_path.parent, wiki_dir=wiki_dir,
                        out_dir=out_path.parent, assets_dir=out_dir / "assets")

    body_html = render_markdown(body, ctx)

    meta_bits = []
    if meta.get("type"):
        meta_bits.append(f'<span class="badge type">{html.escape(meta["type"])}</span>')
    meta_bits.append(status_badge(meta.get("status")))
    # Per AGENTS.md a page is verified only if it says so, so the absence of the
    # field is the claim. An absence is easy to read past, and these pages are
    # written by a model from an automated exploration, so it is said out loud.
    if not meta.get("verified"):
        meta_bits.append('<span class="badge unverified">unverified</span>')
    for tag in meta.get("tags") or []:
        meta_bits.append(f'<span class="tag">{html.escape(tag)}</span>')
    meta_box = f'<div class="meta-box">{"".join(meta_bits)}</div>' if meta_bits else ""

    # A cited image is shown, not just named. The game wiki's pages are written
    # from screenshots that the page then cites and nobody can see: the paths
    # point into a gitignored output directory, so on any other machine every
    # one of them is dead. Copying the file in and putting it on the page is
    # what makes the site carry its own evidence.
    #
    # Only from `sources:`. A page that already writes `![](...)` inline has said
    # where it wants the image, and showing it twice would be worse than not
    # showing it at all.
    sources_html, figures = "", []
    sources = meta.get("sources") or []
    if sources:
        items = []
        for s in sources:
            sid = s.get("id", "")
            resource = s.get("resource", "")
            label = s.get("title") or resource
            src_path = (_resolve_asset(resource, ctx)
                        if Path(resource).suffix.lower() in IMAGE_EXTENSIONS else None)
            already_shown = src_path is not None and src_path in ctx.inlined_images
            copied = _copy_asset(src_path, ctx) if src_path else None
            if copied and not already_shown:
                figures.append(f'<figure><img src="{html.escape(copied)}" alt="{html.escape(label)}" '
                               f'loading="lazy"><figcaption>{html.escape(label)}</figcaption></figure>')
            shown = (f'<a href="{html.escape(copied)}"><code>{html.escape(resource)}</code></a>'
                     if copied else f"<code>{html.escape(resource)}</code>")
            items.append(f'<li id="src-{html.escape(sid)}">{shown} — {html.escape(label)}</li>')
        sources_html = f'<h2>Sources</h2><ul class="sources-list">{"".join(items)}</ul>'

    css_href = _relpath(out_path.parent, out_dir / "assets" / "style.css")
    index_href = _relpath(out_path.parent, out_dir / "index.html")

    body_out = (
        f'<nav class="top"><a href="{html.escape(index_href)}">&larr; wiki index</a></nav>'
        f"<h1>{html.escape(page.title)}</h1>"
        f"{meta_box}"
        f"{''.join(figures)}"
        f"{body_html}"
        f"{sources_html}"
    )
    out_path.write_text(html_shell(page.title, body_out, css_href), encoding="utf-8")


def render_index(pages: list[Page], out_dir: Path) -> None:
    groups = {"overview": [], "summaries": [], "entities": [], "concepts": [], "log": []}
    for p in pages:
        top = p.rel_out.parts[0] if len(p.rel_out.parts) > 1 else "overview"
        groups.setdefault(top, []).append(p)

    group_titles = {
        "overview": "Overview", "summaries": "Summaries", "entities": "Entities",
        "concepts": "Concepts", "log": "Log",
    }

    sections = []
    for key in ("overview", "summaries", "entities", "concepts", "log"):
        items = groups.get(key) or []
        if not items:
            continue
        lis = []
        for p in items:
            href = p.rel_out.as_posix()
            tags = " ".join(p.meta.get("tags") or [])
            search_blob = html.escape(f"{p.title} {p.description} {tags}".lower())
            lis.append(
                f'<li data-search="{search_blob}">'
                f'<a href="{html.escape(href)}">{html.escape(p.title)}</a>'
                f'{status_badge(p.meta.get("status"))}'
                f'<div class="desc">{html.escape(p.description)}</div>'
                f"</li>"
            )
        sections.append(f'<h2 class="group-heading">{group_titles[key]} ({len(items)})</h2><ul class="page-list">{"".join(lis)}</ul>')

    filter_js = """
<script>
document.getElementById('filter-box').addEventListener('input', function (e) {
  var q = e.target.value.toLowerCase();
  document.querySelectorAll('ul.page-list li').forEach(function (li) {
    li.style.display = li.dataset.search.indexOf(q) === -1 ? 'none' : '';
  });
});
</script>
"""

    body = (
        '<h1>Wiki</h1>'
        '<input id="filter-box" type="text" placeholder="Filter pages…">'
        + "".join(sections)
        + filter_js
    )
    (out_dir / "index.html").write_text(html_shell("Wiki", body, "assets/style.css"), encoding="utf-8")


def build(wiki_dir: Path, out_dir: Path) -> list[Page]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")

    pages = discover_pages(wiki_dir)
    for page in pages:
        render_page(page, wiki_dir, out_dir)
    render_index(pages, out_dir)
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki", default="results/wiki", help="Path to an OKF wiki/ directory (default: results/wiki)")
    parser.add_argument("--out", default="results/site", help="Output directory for the static HTML site (default: results/site)")
    args = parser.parse_args()

    wiki_dir = (HERE / args.wiki).resolve()
    out_dir = (HERE / args.out).resolve()
    if not wiki_dir.is_dir():
        raise SystemExit(f"--wiki '{wiki_dir}' is not a directory")

    pages = build(wiki_dir, out_dir)
    print(f"Rendered {len(pages)} page(s) -> {out_dir / 'index.html'}")


if __name__ == "__main__":
    main()

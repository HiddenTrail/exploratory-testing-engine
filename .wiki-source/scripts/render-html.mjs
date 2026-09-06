#!/usr/bin/env node
// Quality Playbook Factory — render a wiki bundle to HTML.
//
// Two modes, one markdown implementation:
//
//   multi  (default)  <workspace>/wiki/**.md -> <workspace>/wiki-html/**.html + style.css
//                     Mirrors the source tree, so relative links (including images that
//                     point outside the bundle) keep resolving at the same depth.
//   single (--single) every page concatenated into one self-contained .html: CSS inlined,
//                     images embedded as base64 data URIs, in-bundle links turned into
//                     in-page anchors. Portable — one file, no sidecars.
//
// Dependency-free on purpose: this repo has no package.json. The markdown subset covered is
// the one OKF pages actually use — headings, paragraphs, emphasis, code spans, fenced code,
// pipe tables, blockquotes, nested lists, images, links, footnotes, HTML comments.
//
// Usage: node render-html.mjs [--dir <workspace>] [--out <dir>] [--single [file]] [--no-images]

import { readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync, statSync } from 'node:fs';
import { join, dirname, resolve, relative, basename, extname, sep } from 'node:path';

import { parseYaml } from './lib/yaml.mjs';

const argv = process.argv.slice(2);
const arg = (name) => {
  const i = argv.indexOf(name);
  if (i < 0) return undefined;
  const next = argv[i + 1];
  return next && !next.startsWith('--') ? next : true;
};
const WS = resolve(typeof arg('--dir') === 'string' ? arg('--dir') : process.cwd());
const SRC = join(WS, 'wiki');
const OUT = join(WS, typeof arg('--out') === 'string' ? arg('--out') : 'wiki-html');
const SINGLE = arg('--single');
const EMBED = !argv.includes('--no-images');

const cfgPath = join(WS, 'qpf.config.yml');
if (!existsSync(cfgPath)) {
  console.error(`✗ ${cfgPath} not found — is ${WS} a QPF workspace?`);
  process.exit(1);
}
if (!existsSync(SRC)) {
  console.error(`✗ ${SRC} not found — nothing to render.`);
  process.exit(1);
}
const cfg = parseYaml(readFileSync(cfgPath, 'utf8'));
const customer = cfg.qpf?.customer || basename(WS);
const lang = cfg.qpf?.language || 'en';

const SINGLE_FILE = SINGLE
  ? resolve(WS, typeof SINGLE === 'string' ? SINGLE : `${customer}-wiki.html`)
  : null;

// The repo root, so `sources[].resource` (repo-relative) can be linked from a page.
const REPO = (() => {
  let d = WS;
  for (;;) {
    if (existsSync(join(d, '.git'))) return d;
    const up = dirname(d);
    if (up === d) return null;
    d = up;
  }
})();

// --- frontmatter ----------------------------------------------------------------
// lib/yaml.mjs deliberately doesn't do flow collections with contents, and the page
// templates use them (`generated: { by: …, at: … }`, `tags: [a, b]`), so those arrive as
// opaque strings. Unpack just those two shapes here rather than widen the shared parser.
function unflow(v) {
  if (typeof v !== 'string') return v;
  const s = v.trim();
  const unq = (x) => x.trim().replace(/^["'](.*)["']$/, '$1');
  if (s.startsWith('[') && s.endsWith(']')) return s.slice(1, -1).split(',').map(unq).filter(Boolean);
  if (s.startsWith('{') && s.endsWith('}')) {
    const obj = {};
    for (const part of s.slice(1, -1).split(',')) {
      const k = part.indexOf(':');
      if (k >= 0) obj[unq(part.slice(0, k))] = unq(part.slice(k + 1));
    }
    return obj;
  }
  return v;
}

function splitFm(md) {
  if (!md.startsWith('---')) return { fm: {}, body: md };
  const end = md.indexOf('\n---', 3);
  if (end < 0) return { fm: {}, body: md };
  return { fm: parseYaml(md.slice(3, end)) || {}, body: md.slice(md.indexOf('\n', end + 1) + 1) };
}

// --- inline markdown ------------------------------------------------------------
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const attr = (s) => esc(s).replace(/"/g, '&quot;');
const slug = (s) => s.toLowerCase().replace(/<[^>]+>/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const pageId = (rel) => `page-${slug(rel.replace(/\.md$/, ''))}`;

const MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml' };
const dataUris = new Map();   // absolute path -> data: URI, so a file used twice is embedded once
let embedded = 0, embeddedBytes = 0;

function dataUri(abs) {
  if (dataUris.has(abs)) return dataUris.get(abs);
  const mime = MIME[extname(abs).toLowerCase()];
  if (!mime || !existsSync(abs)) return null;
  const buf = readFileSync(abs);
  const uri = `data:${mime};base64,${buf.toString('base64')}`;
  dataUris.set(abs, uri);
  embedded++; embeddedBytes += buf.length;
  return uri;
}

// Rewrite a link target. In multi mode the output tree mirrors the source, so only in-bundle
// `.md` targets change. In single mode every page is one document, so in-bundle links become
// anchors and everything else is re-based onto the single file's directory.
function href(h, ctx) {
  if (/^(https?:|mailto:|#|data:|\/)/.test(h)) return h;
  const [path, hash] = h.split('#');
  let abs;
  try { abs = resolve(ctx.srcDir, decodeURIComponent(path)); } catch { abs = resolve(ctx.srcDir, path); }
  const inBundle = path.endsWith('.md') && (abs === SRC || abs.startsWith(SRC + sep));
  if (!SINGLE_FILE) {
    return inBundle ? path.replace(/\.md$/, '.html') + (hash ? `#${hash}` : '') : h;
  }
  if (inBundle) {
    const target = pageId(relative(SRC, abs).split('\\').join('/'));
    return `#${hash ? `${target}--${hash}` : target}`;
  }
  const rel = relative(dirname(SINGLE_FILE), abs).split('\\').join('/');
  return rel.split('/').map(encodeURIComponent).join('/') + (hash ? `#${hash}` : '');
}

function inline(text, ctx) {
  const codes = [];
  let s = String(text).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s);
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => {
    if (SINGLE_FILE && EMBED) {
      let abs;
      try { abs = resolve(ctx.srcDir, decodeURIComponent(src)); } catch { abs = resolve(ctx.srcDir, src); }
      const uri = dataUri(abs);
      // No self-link here: repeating a data URI in href would put the whole payload in the
      // file twice, and clicking it would only open the image already on screen.
      if (uri) return `<img class="shot" src="${attr(uri)}" alt="${attr(alt)}" loading="lazy">`;
    }
    const link = href(src, ctx);
    return `<a class="shot" href="${attr(link)}"><img src="${attr(link)}" alt="${attr(alt)}" loading="lazy"></a>`;
  });
  s = s.replace(/\[\^([^\]\s]+)\]/g, (m, id) => {
    if (!ctx.footnotes[id]) return m;
    const n = ctx.order.indexOf(id) + 1;
    // A page cites the same source many times; only the first citation carries the id the
    // footnote's back-arrow returns to, or the document would repeat one id N times.
    const first = !ctx.refs.has(id);
    ctx.refs.add(id);
    const anchor = first ? ` id="${attr(ctx.ids)}ref-${attr(id)}"` : '';
    return `<sup class="fnref"><a${anchor} href="#${attr(ctx.ids)}fn-${attr(id)}" title="source">${n}</a></sup>`;
  });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, h) => `<a href="${attr(href(h, ctx))}">${t}</a>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[\s(—])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[i])}</code>`);
}

// --- block markdown -------------------------------------------------------------
function cells(row) {
  return row.trim().replace(/^\|/, '').replace(/\|$/, '')
    .replace(/\\\|/g, '\u0001').split('|').map((c) => c.replace(/\u0001/g, '|').trim());
}

function render(body, ctx) {
  // Footnote definitions come out first; they're rendered as a block at the end.
  const lines = [];
  for (const l of body.split('\n')) {
    const m = /^\[\^([^\]\s]+)\]:\s*(.*)$/.exec(l);
    if (m) { ctx.footnotes[m[1]] = m[2]; ctx.order.push(m[1]); } else lines.push(l);
  }

  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '') { i++; continue; }

    if (/^\s*<!--/.test(line)) {                                    // HTML comment
      while (i < lines.length && !lines[i].includes('-->')) i++;
      i++; continue;
    }

    if (/^\s*```/.test(line)) {                                     // fenced code
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }

    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {                                                        // heading
      // The shell already prints the page title as an h1, so an opening h1 that repeats it is
      // dropped rather than rendered twice. Ids are page-scoped so they stay unique when every
      // page shares one document.
      if (h[1].length === 1 && slug(h[2]) === slug(ctx.title)) { i++; continue; }
      // Any other body h1 (the index's group headings) is demoted, so each page keeps exactly
      // one h1 and the visual hierarchy matches the outline.
      const n = Math.max(h[1].length, 2);
      out.push(`<h${n} id="${attr(ctx.ids + slug(h[2]))}">${inline(h[2], ctx)}</h${n}>`);
      i++; continue;
    }

    if (/^\s*\|/.test(line)) {                                      // pipe table
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const head = cells(rows[0]);
      const hasSep = rows[1] && /^[\s|:-]+$/.test(rows[1]);
      const align = hasSep ? cells(rows[1]).map((c) =>
        c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : '') : [];
      const cell = (tag) => (c, k) => `<${tag}${align[k] ? ` style="text-align:${align[k]}"` : ''}>${inline(c, ctx)}</${tag}>`;
      const trs = rows.slice(hasSep ? 2 : 1).map((r) => `<tr>${cells(r).map(cell('td')).join('')}</tr>`);
      out.push(`<table><thead><tr>${head.map(cell('th')).join('')}</tr></thead><tbody>${trs.join('')}</tbody></table>`);
      continue;
    }

    if (/^\s*>/.test(line)) {                                       // blockquote
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote><p>${inline(buf.join(' ').trim(), ctx)}</p></blockquote>`);
      continue;
    }

    if (/^(\s*)([-*]|\d+\.)\s+/.test(line)) {                       // list, with nesting
      const items = [];
      while (i < lines.length && lines[i].trim() !== '') {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (m) { items.push({ indent: m[1].length, ordered: /\d/.test(m[2]), text: m[3] }); i++; }
        else if (/^\s+\S/.test(lines[i]) && items.length) { items[items.length - 1].text += ` ${lines[i].trim()}`; i++; }
        else break;
      }
      const stack = [];
      let html = '';
      for (const it of items) {
        while (stack.length && it.indent < stack[stack.length - 1].indent) html += `</li></${stack.pop().tag}>`;
        if (!stack.length || it.indent > stack[stack.length - 1].indent) {
          const tag = it.ordered ? 'ol' : 'ul';
          html += `<${tag}>`;
          stack.push({ indent: it.indent, tag });
        } else html += '</li>';
        html += `<li>${inline(it.text, ctx)}`;
      }
      while (stack.length) html += `</li></${stack.pop().tag}>`;
      out.push(html);
      continue;
    }

    const buf = [];                                                 // paragraph
    while (i < lines.length && lines[i].trim() !== ''
           && !/^\s*(#{1,6}\s|\||>|```|<!--)/.test(lines[i])
           && !/^(\s*)([-*]|\d+\.)\s+/.test(lines[i])) buf.push(lines[i++]);
    if (buf.length) out.push(`<p>${inline(buf.join(' ').trim(), ctx)}</p>`);
    else i++;
  }

  if (ctx.refs.size) {
    const fns = ctx.order.filter((id) => ctx.refs.has(id)).map((id) =>
      `<li id="${attr(ctx.ids)}fn-${attr(id)}">${inline(ctx.footnotes[id], ctx)} <a class="backref" href="#${attr(ctx.ids)}ref-${attr(id)}">↩</a></li>`);
    out.push(`<section class="footnotes"><h2 id="${attr(ctx.ids)}sources">Sources</h2><ol>${fns.join('')}</ol></section>`);
  }
  return out.join('\n');
}

// --- collect pages --------------------------------------------------------------
function walk(dir) {
  const files = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) files.push(...walk(p));
    else if (name.endsWith('.md')) files.push(p);
  }
  return files;
}

const all = walk(SRC).map((abs) => {
  const rel = relative(SRC, abs).split('\\').join('/');
  const { fm, body } = splitFm(readFileSync(abs, 'utf8'));
  return {
    abs, rel, fm, body,
    outRel: rel.replace(/\.md$/, '.html'),
    id: pageId(rel),
    group: rel.includes('/') ? rel.split('/')[0] : (rel === 'index.md' ? 'index' : 'root'),
    title: fm.title || (rel === 'index.md' ? `${customer} — wiki index` : basename(rel, '.md')),
  };
});

const GROUPS = [
  ['Contents', (p) => p.rel === 'index.md'],
  ['Overview', (p) => p.rel === 'overview.md'],
  ['Summaries', (p) => p.group === 'summaries'],
  ['Entities', (p) => p.group === 'entities'],
  ['Concepts', (p) => p.group === 'concepts'],
  ['Log', (p) => p.group === 'log'],
];
const grouped = GROUPS.map(([heading, pred]) => [heading, all.filter(pred).sort((a, b) =>
  heading === 'Log' ? b.rel.localeCompare(a.rel) : a.title.localeCompare(b.title))]).filter(([, g]) => g.length);

// In multi mode the index is its own page and isn't listed in the sidebar (the brand links to
// it); in single mode it leads the document as a table of contents.
function sidebar(current) {
  const up = current ? '../'.repeat(current.outRel.split('/').length - 1) : '';
  const link = (p) => (SINGLE_FILE ? `#${p.id}` : up + p.outRel);
  const parts = [`<a class="brand" href="${SINGLE_FILE ? '#top' : `${up}index.html`}">${esc(customer)}<span>wiki</span></a>`];
  for (const [heading, group] of grouped) {
    if (!SINGLE_FILE && heading === 'Contents') continue;
    parts.push(`<h3>${heading}</h3><ul>`);
    for (const p of group) {
      const here = current && p.rel === current.rel ? ' class="here"' : '';
      parts.push(`<li${here}><a href="${attr(link(p))}">${esc(p.title)}</a></li>`);
    }
    parts.push('</ul>');
  }
  return parts.join('\n');
}

function metaPanel(p, outDir) {
  const fm = p.fm;
  const chips = [];
  if (fm.type) chips.push(`<span class="chip type">${esc(fm.type)}</span>`);
  if (fm.entity_kind) chips.push(`<span class="chip kind">${esc(fm.entity_kind)}</span>`);
  if (fm.status) chips.push(`<span class="chip status-${attr(String(fm.status))}">${esc(fm.status)}</span>`);
  chips.push(fm.verified
    ? `<span class="chip ok">verified: ${esc(typeof fm.verified === 'object' ? fm.verified.by : fm.verified)}</span>`
    : `<span class="chip warn" title="no verified: key in frontmatter — nobody has confirmed this page against the source">unverified</span>`);
  for (const t of (unflow(fm.tags) || [])) chips.push(`<span class="chip tag">${esc(t)}</span>`);

  const rows = [];
  const gen = unflow(fm.generated);
  if (gen && typeof gen === 'object') {
    rows.push(`<div><dt>generated</dt><dd>${esc(gen.by || '?')} <span class="dim">at ${esc(gen.at || '?')}</span></dd></div>`);
  }
  if (Array.isArray(fm.sources) && fm.sources.length) {
    const items = fm.sources.map((s) => {
      const res = String(s.resource || '');
      let link = `<code>${esc(res)}</code>`;
      if (REPO && res && existsSync(join(REPO, res))) {
        const rel = relative(outDir, join(REPO, res)).split('\\').join('/');
        link = `<a href="${attr(rel.split('/').map(encodeURIComponent).join('/'))}"><code>${esc(res)}</code></a>`;
      }
      return `<li><span class="fnid">${esc(s.id || '')}</span> ${esc(s.title || '')}<br>${link}</li>`;
    });
    rows.push(`<div><dt>sources</dt><dd><ul class="srcs">${items.join('')}</ul></dd></div>`);
  }
  return `<aside class="meta"><div class="chips">${chips.join('')}</div>${rows.length ? `<dl>${rows.join('')}</dl>` : ''}</aside>`;
}

const DERIVED_NOTE = '<p class="note">This page is derived — regenerated by <code>rebuild-index.mjs</code> from the frontmatter of every other page.</p>';

function article(p, outDir) {
  const ctx = { srcDir: dirname(p.abs), title: p.title, footnotes: {}, order: [], refs: new Set(),
                ids: SINGLE_FILE ? `${p.id}--` : '' };
  const bodyHtml = render(p.body, ctx);
  const lede = p.fm.description ? `<p class="lede">${inline(p.fm.description, ctx)}</p>` : '';
  const head = `<header><h1>${esc(p.title)}</h1>${lede}</header>`;
  const meta = p.rel === 'index.md' ? DERIVED_NOTE : metaPanel(p, outDir);
  const foot = SINGLE_FILE
    ? `<footer class="pagefoot">From <code>wiki/${esc(p.rel)}</code> · <a href="#top">↑ contents</a></footer>`
    : `<footer>Rendered from <code>wiki/${esc(p.rel)}</code> by <code>render-html.mjs</code>. Generated view — edit the markdown, not this file.</footer>`;
  return { html: `${head}\n${meta}\n${bodyHtml}\n${foot}`, ctx };
}

const CSS = `:root{
  --bg:#fbfaf8; --panel:#fff; --ink:#1e1d1b; --dim:#6b6864; --line:#e3e0da;
  --accent:#8a4b2a; --accent-soft:#f4ece6; --warn:#8a6d1f; --ok:#2c6b4a; --code:#f3f1ec;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#17171a; --panel:#1e1e22; --ink:#e8e6e1; --dim:#a09c95; --line:#33323a;
  --accent:#e0a077; --accent-soft:#2a2320; --warn:#d9bc6a; --ok:#7fc3a0; --code:#26262c;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  display:grid;grid-template-columns:19rem 1fr}
a{color:var(--accent)}
a:hover{text-decoration-thickness:2px}

nav{position:sticky;top:0;height:100vh;overflow-y:auto;padding:1.5rem 1rem 3rem;
  background:var(--panel);border-right:1px solid var(--line);font-size:.875rem}
.brand{display:block;margin:0 .5rem 1.25rem;font-weight:700;font-size:1.05rem;
  text-decoration:none;color:var(--ink)}
.brand span{display:block;font-weight:400;font-size:.75rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim)}
nav h3{margin:1.25rem .5rem .35rem;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
nav ul{list-style:none;margin:0;padding:0}
nav li a{display:block;padding:.3rem .5rem;border-radius:5px;text-decoration:none;color:var(--ink)}
nav li a:hover{background:var(--accent-soft)}
nav li.here a,nav li a.here{background:var(--accent-soft);color:var(--accent);font-weight:600;
  box-shadow:inset 3px 0 0 var(--accent)}
#navtoggle,#navtoggle+label{display:none}

main{padding:2.5rem clamp(1rem,4vw,3.5rem) 5rem;min-width:0}
article{max-width:52rem}
header h1{margin:0 0 .3rem;font-size:1.9rem;line-height:1.2;letter-spacing:-.01em}
.lede{margin:0 0 1.5rem;font-size:1.05rem;color:var(--dim)}
h2{margin:2.5rem 0 .75rem;padding-bottom:.3rem;border-bottom:1px solid var(--line);font-size:1.3rem}
h3{margin:1.75rem 0 .5rem;font-size:1.05rem}
h4{margin:1.25rem 0 .4rem;font-size:.95rem}
p,ul,ol{margin:0 0 1rem}
li{margin:.2rem 0}
li>ul,li>ol{margin:.25rem 0}
strong{font-weight:650}
code{background:var(--code);padding:.1em .35em;border-radius:4px;
  font:.85em/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-word}
pre{background:var(--code);border:1px solid var(--line);border-radius:8px;
  padding:1rem;overflow-x:auto;margin:0 0 1.25rem}
pre code{background:none;padding:0;font-size:.8rem;line-height:1.45;white-space:pre}
blockquote{margin:0 0 1.25rem;padding:.6rem 1rem;background:var(--panel);
  border-left:3px solid var(--accent);border-radius:0 6px 6px 0;color:var(--dim)}
blockquote p{margin:0}
table{border-collapse:collapse;width:100%;margin:0 0 1.5rem;font-size:.9rem;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.45rem .6rem;text-align:left;vertical-align:top}
th{background:var(--panel);font-size:.8rem;letter-spacing:.03em;text-transform:uppercase;color:var(--dim)}
tbody tr:nth-child(odd) td{background:var(--panel)}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;display:block}
a.shot,img.shot{display:inline-block;max-width:22rem;margin:0 .5rem 1rem 0}

.meta{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:.9rem 1rem;margin:0 0 2rem;font-size:.85rem}
.chips{display:flex;flex-wrap:wrap;gap:.35rem}
.chip{padding:.12rem .5rem;border-radius:999px;border:1px solid var(--line);
  background:var(--bg);font-size:.75rem;color:var(--dim);white-space:nowrap}
.chip.type{border-color:var(--accent);color:var(--accent);font-weight:600}
.chip.kind{font-weight:600}
.chip.warn{border-color:var(--warn);color:var(--warn)}
.chip.ok{border-color:var(--ok);color:var(--ok)}
.meta dl{margin:.9rem 0 0;display:grid;gap:.5rem}
.meta dt{font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.meta dd{margin:.15rem 0 0}
.dim{color:var(--dim)}
ul.srcs{list-style:none;margin:0;padding:0}
ul.srcs li{margin:.35rem 0}
.fnid{display:inline-block;padding:0 .35rem;border-radius:4px;background:var(--accent-soft);
  color:var(--accent);font:.75rem ui-monospace,monospace}
.note{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--warn);
  border-radius:0 6px 6px 0;padding:.6rem 1rem;font-size:.9rem;color:var(--dim)}

sup.fnref a{text-decoration:none;padding:0 .15rem;font-size:.7rem}
.footnotes{margin-top:3rem;border-top:1px solid var(--line);font-size:.85rem;color:var(--dim)}
.footnotes h2{border:0;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;margin:1.25rem 0 .5rem}
.backref{text-decoration:none}
footer{max-width:52rem;margin-top:4rem;padding-top:1rem;border-top:1px solid var(--line);
  font-size:.78rem;color:var(--dim)}

/* single-file mode: one document, one section per page */
article.page{padding-top:1rem;scroll-margin-top:1rem}
article.page+article.page{margin-top:5rem;border-top:4px double var(--line);padding-top:3rem}
.pagefoot{margin-top:2.5rem}
.kicker{margin:0 0 .35rem;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}

@media (max-width:900px){
  body{grid-template-columns:1fr}
  #navtoggle+label{display:block;position:fixed;top:.6rem;right:.6rem;z-index:3;
    background:var(--panel);border:1px solid var(--line);border-radius:6px;
    padding:.25rem .55rem;cursor:pointer;font-size:1.1rem}
  nav{display:none}
  #navtoggle:checked~nav{display:block;position:static;height:auto}
  main{padding-top:3.5rem}
}
@media print{
  body{display:block}
  nav,#navtoggle+label{display:none}
  a{color:inherit}
  article.page{break-before:page}
}
`;

const shell = (title, head, bodyInner) => `<!DOCTYPE html>
<html lang="${esc(lang)}">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
${head}
<body id="top">
<input type="checkbox" id="navtoggle"><label for="navtoggle" title="menu">☰</label>
${bodyInner}
</body>
</html>
`;

// --- write ----------------------------------------------------------------------
if (SINGLE_FILE) {
  const outDir = dirname(SINGLE_FILE);
  const sections = [];
  for (const [heading, group] of grouped) {
    for (const p of group) {
      const { html } = article(p, outDir);
      sections.push(`<article class="page" id="${attr(p.id)}"><p class="kicker">${esc(heading)}</p>\n${html}\n</article>`);
    }
  }
  const at = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const banner = `<article class="page" id="about-this-file"><header><h1>${esc(customer)} — wiki, single file</h1>`
    + `<p class="lede">${all.length} pages from the <code>wiki/</code> markdown bundle, in one self-contained HTML file.</p></header>`
    + `<p class="note">Generated ${esc(at)} by <code>render-html.mjs --single</code>. `
    + `${EMBED ? `${embedded} screenshot${embedded === 1 ? '' : 's'} (${(embeddedBytes / 1048576).toFixed(1)} MB of PNG) are embedded as data URIs, so this file needs nothing alongside it` : 'Images are linked, not embedded, so they resolve only next to the repo'}. `
    + `Links between pages are in-page anchors; links to source material under <code>out/</code> or elsewhere in the repo are relative and resolve only while this file sits in <code>${esc(relative(REPO || WS, outDir).split('\\').join('/') || '.')}</code>. `
    + `Derived view — edit the markdown and re-run, don't edit this file.</p></article>`;
  const html = shell(`${customer} — wiki`, `<style>\n${CSS}</style>`,
    `<nav>${sidebar(null)}</nav>\n<main>\n${banner}\n${sections.join('\n')}\n</main>`);
  writeFileSync(SINGLE_FILE, html, 'utf8');
  const kb = Buffer.byteLength(html) / 1048576;
  console.log(`✓ ${relative(WS, SINGLE_FILE)}: ${all.length} pages, ${embedded} images embedded, ${kb.toFixed(1)} MB`);
} else {
  mkdirSync(OUT, { recursive: true });
  for (const p of all) {
    const dest = join(OUT, p.outRel);
    const up = '../'.repeat(p.outRel.split('/').length - 1);
    const { html } = article(p, dirname(dest));
    mkdirSync(dirname(dest), { recursive: true });
    writeFileSync(dest, shell(`${p.title} — ${customer}`,
      `<link rel="stylesheet" href="${attr(`${up}style.css`)}">`,
      `<nav>${sidebar(p)}</nav>\n<main>\n<article>\n${html}\n</article>\n</main>`), 'utf8');
  }
  writeFileSync(join(OUT, 'style.css'), CSS, 'utf8');
  console.log(`✓ ${relative(WS, OUT) || OUT}: ${all.length} pages + style.css`);
}

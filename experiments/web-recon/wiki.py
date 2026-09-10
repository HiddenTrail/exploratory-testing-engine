"""An ontology.json -> a browsable HTML wiki, by arithmetic. No model.

The Clash Royale kit's "the wiki is measurement, the model only synthesizes" creed,
applied to a web crawl. Everything here is a rearrangement of what the crawl already
recorded: the states and transitions become a navigation graph, and the evidence becomes
the one page a game wiki never had - **Functional findings**, every 500 / failed request
/ console error / exception with the state it fired in. `build_wiki` is a pure function
of the Ontology, so it is unit-tested with no browser and no model.

    python wiki.py <ontology.json> [--out wiki.html]
"""

from __future__ import annotations

import argparse
import html
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema import Ontology

# Finding kind -> (label, colour). Network/HTTP faults are the loud ones.
_FINDING_STYLE = {
    "http_error": ("HTTP error", "#dc2626"),
    "request_failed": ("Request failed", "#dc2626"),
    "exception": ("Uncaught exception", "#ea580c"),
    "console_error": ("Console error", "#d97706"),
    "state_unstable": ("Unstable state", "#9333ea"),
}
_NODE_BLUE, _NODE_RED = "#2563eb", "#dc2626"


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _short_state_label(state) -> str:
    """A node label: state id plus its first heading, or a control hint."""
    if state.name:
        head = state.name
    else:
        # signature is "route|controls|landmarks"; prefer a landmark, else the route.
        parts = state.signature.split("|")
        head = parts[2] if len(parts) > 2 and parts[2] else (parts[0] or "/")
    return f"{state.id}: {head[:22]}"


def _layout(onto: Ontology) -> dict:
    """BFS-depth layout: entry (a state nothing navigates into) at top, rows by depth.
    Self-loops are ignored for layout."""
    ids = [s.id for s in onto.states]
    adj = defaultdict(list)
    indeg = {i: 0 for i in ids}
    for t in onto.transitions:
        if t.dest != t.source and t.dest in indeg:
            adj[t.source].append(t.dest)
            indeg[t.dest] += 1
    if not ids:
        return {}
    entry = next((i for i in ids if indeg[i] == 0), ids[0])
    level = {entry: 0}
    queue = [entry]
    while queue:
        node = queue.pop(0)
        for nxt in adj[node]:
            if nxt not in level:
                level[nxt] = level[node] + 1
                queue.append(nxt)
    deepest = max(level.values(), default=0)
    for i in ids:
        level.setdefault(i, deepest + 1)
    rows = defaultdict(list)
    for i in ids:
        rows[level[i]].append(i)
    pos = {}
    for lvl in sorted(rows):
        for j, i in enumerate(sorted(rows[lvl])):
            pos[i] = (110 + j * 200, 70 + lvl * 130)
    return pos


def _svg_graph(onto: Ontology) -> str:
    pos = _layout(onto)
    if not pos:
        return "<p>(no states)</p>"
    states_with_findings = {f.state_id for f in onto.findings}
    by_id = {s.id: s for s in onto.states}
    width = max((x for x, _ in pos.values()), default=200) + 220
    height = max((y for _, y in pos.values()), default=200) + 120

    edges, self_loops = [], defaultdict(list)
    seen = set()
    for t in onto.transitions:
        if t.source == t.dest:
            self_loops[t.source].append(f"{t.action.element_key} ({t.effect})")
            continue
        key = (t.source, t.dest)
        if key in seen or t.source not in pos or t.dest not in pos:
            continue
        seen.add(key)
        x1, y1 = pos[t.source]
        x2, y2 = pos[t.dest]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        edges.append(
            f'<path d="M {x1} {y1} Q {mx} {my - 20} {x2} {y2}" class="edge"/>'
            f'<text x="{mx}" y="{my - 24}" class="edge-label">{_esc(t.action.element_key)[:24]}</text>')

    nodes = []
    for sid, (x, y) in pos.items():
        colour = _NODE_RED if sid in states_with_findings else _NODE_BLUE
        loop = " ⟲" if sid in self_loops else ""
        label = _esc(_short_state_label(by_id[sid])) + loop
        nodes.append(
            f'<g><circle cx="{x}" cy="{y}" r="30" fill="{colour}"/>'
            f'<text x="{x}" y="{y + 48}" class="node-label">{label}</text>'
            f'<text x="{x}" y="{y + 5}" class="node-id">{_esc(sid)}</text></g>')

    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" '
            f'orient="auto"><polygon points="0 0, 10 3, 0 6" fill="#94a3b8"/></marker></defs>'
            f'<g>{"".join(edges)}</g><g>{"".join(nodes)}</g></svg>')


def _findings_html(onto: Ontology) -> str:
    if not onto.findings:
        return '<p class="ok">No functional findings — no HTTP errors, failed requests, or console errors observed.</p>'
    by_kind = defaultdict(list)
    for f in onto.findings:
        by_kind[f.kind].append(f)
    blocks = []
    for kind, items in sorted(by_kind.items(), key=lambda kv: kv[0]):
        label, colour = _FINDING_STYLE.get(kind, (kind, "#64748b"))
        rows = "".join(
            f'<tr><td>{_esc(f.state_id)}</td><td>{_esc(f.summary)}</td>'
            f'<td class="seq">{_esc(f.seq)}</td></tr>' for f in items)
        blocks.append(
            f'<h3><span class="badge" style="background:{colour}">{_esc(label)}</span> '
            f'&times;{len(items)}</h3>'
            f'<table class="findings"><thead><tr><th>state</th><th>detail</th><th>action#</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')
    return "".join(blocks)


def _states_html(onto: Ontology) -> str:
    out_edges = defaultdict(list)
    in_edges = defaultdict(list)
    for t in onto.transitions:
        out_edges[t.source].append(t)
        in_edges[t.dest].append(t)
    findings_by_state = defaultdict(list)
    for f in onto.findings:
        findings_by_state[f.state_id].append(f)

    cards = []
    for s in onto.states:
        els = "".join(
            f'<tr><td>{_esc(e.role)}</td><td>{_esc(e.name)}</td>'
            f'<td>{"committing" if e.committing else "safe"}</td>'
            f'<td class="loc">{_esc(e.locator)}</td></tr>' for e in s.elements)
        outs = "".join(
            f'<li>{_esc(t.action.element_key)} <span class="eff">({_esc(t.effect)})</span> &rarr; '
            f'<a href="#{_esc(t.dest)}">{_esc(t.dest)}</a></li>' for t in out_edges[s.id])
        ins = ", ".join(sorted({_esc(t.source) for t in in_edges[s.id]})) or "—"
        finds = "".join(f'<li>{_esc(f.kind)}: {_esc(f.summary)[:120]}</li>'
                        for f in findings_by_state[s.id])
        shot = (f'<img class="state-shot" src="{_esc(s.image)}" alt="{_esc(s.id)} screenshot" '
                f'loading="lazy">') if s.image else ""
        cards.append(f"""
        <section class="state" id="{_esc(s.id)}">
          <h3>{_esc(s.id)} <span class="sig">{_esc(s.signature)}</span></h3>
          <p class="url">{_esc(s.url)}{' — ' + _esc(s.title) if s.title else ''}</p>
          {shot}
          <p class="meta">reached from: {ins}</p>
          {'<p class="meta">leaves via:</p><ul class="outs">' + outs + '</ul>' if outs else '<p class="meta">no recorded exits</p>'}
          {'<p class="meta findings-here">findings here:</p><ul class="finds">' + finds + '</ul>' if finds else ''}
          <details><summary>{len(s.elements)} interactive element(s)</summary>
            <table class="els"><thead><tr><th>role</th><th>name</th><th>gate</th><th>locator</th></tr></thead>
            <tbody>{els}</tbody></table></details>
        </section>""")
    return "".join(cards)


def build_wiki(onto: Ontology) -> str:
    """The whole wiki as one self-contained HTML string. Pure - no I/O, no browser."""
    target = onto.target.get("url", "?")
    n_states, n_trans, n_find = len(onto.states), len(onto.transitions), len(onto.findings)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>web-recon wiki — {_esc(target)}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 0; color: #1e293b; background: #f8fafc; }}
  header {{ background: #0f172a; color: #fff; padding: 20px 28px; }}
  header h1 {{ margin: 0 0 4px; font-size: 20px; }}
  header .stats {{ color: #94a3b8; font-size: 14px; }}
  main {{ padding: 24px 28px; max-width: 1100px; }}
  h2 {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; margin-top: 34px; }}
  .badge {{ color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0 16px; }}
  th, td {{ border-bottom: 1px solid #e2e8f0; padding: 5px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #f1f5f9; }}
  .findings td.seq {{ text-align: right; color: #64748b; }}
  .loc, .sig {{ font-family: ui-monospace, monospace; font-size: 11px; color: #475569; }}
  .ok {{ color: #16a34a; font-weight: 600; }}
  svg {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; max-width: 100%; }}
  .edge {{ stroke: #94a3b8; stroke-width: 1.5; fill: none; marker-end: url(#arrow); }}
  .edge-label {{ font-size: 10px; fill: #64748b; text-anchor: middle; }}
  .node-label {{ font-size: 11px; fill: #334155; text-anchor: middle; }}
  .node-id {{ font-size: 11px; font-weight: 700; fill: #fff; text-anchor: middle; }}
  .state {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px 16px; margin: 12px 0; }}
  .state h3 {{ margin: 0 0 4px; }} .state .url {{ color: #475569; font-size: 13px; margin: 2px 0; }}
  .meta {{ font-size: 13px; color: #334155; margin: 6px 0 2px; }} .eff {{ color: #64748b; }}
  .finds li {{ color: #b91c1c; }} details summary {{ cursor: pointer; color: #2563eb; font-size: 13px; }}
  .state-shot {{ display: block; max-width: 480px; width: 100%; border: 1px solid #cbd5e1; border-radius: 4px; margin: 8px 0; }}
</style></head><body>
<header>
  <h1>web-recon wiki</h1>
  <div class="stats">{_esc(target)} &middot; {n_states} states &middot; {n_trans} transitions &middot;
    <strong style="color:{'#f87171' if n_find else '#4ade80'}">{n_find} functional finding(s)</strong>
    &middot; {_esc(onto.session.get('actions', 0))} actions &middot; read-only, no model</div>
</header>
<main>
  <h2>Functional findings</h2>
  {_findings_html(onto)}
  <h2>Navigation map</h2>
  <p class="meta">Red = a state with findings. &#10226; on a node = a control that stayed on the same state.</p>
  {_svg_graph(onto)}
  <h2>States</h2>
  {_states_html(onto)}
</main></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ontology")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    onto = Ontology.load(args.ontology)
    out = Path(args.out) if args.out else Path(args.ontology).with_name("wiki.html")
    out.write_text(build_wiki(onto), encoding="utf-8")
    print(f"wrote {out}  ({len(onto.states)} states, {len(onto.transitions)} transitions, "
          f"{len(onto.findings)} findings)")


if __name__ == "__main__":
    main()

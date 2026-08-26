"""Renders the full 4-layer ontology stack as one static HTML page:
heuristics (top) -> business/domain -> context -> oracle prioritized (bottom).
Each layer shows a summary count with a <details> drill-down into full content.
No linking across layers is drawn (Phase 0: stacked view only).

Run: python -m engine.ontology.website --sut token_purchase
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.ontology.oracle_creator import ONTOLOGY_DIR, build_ranked_ideas, load_context, load_heuristics
from engine.report import badge, esc, inline_markdown

CSS = """
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; margin: 2rem auto; max-width: 1100px; color: #1a1a1a; background: #fafafa; }
h1 { font-size: 1.5rem; }
h2 { font-size: 1.15rem; margin: 0; }
section.layer { border: 1px solid #ddd; border-radius: 0.5rem; margin-bottom: 1.25rem; background: #fff; }
section.layer > .layer-header { padding: 0.9rem 1.1rem; display: flex; align-items: center; justify-content: space-between; background: #f0f0f0; border-radius: 0.5rem 0.5rem 0 0; }
section.layer .layer-count { color: #555; font-size: 0.85rem; }
details { padding: 0 1.1rem; }
details summary { cursor: pointer; padding: 0.6rem 0; font-weight: 600; color: #333; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1rem; }
th, td { border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; font-size: 0.85rem; }
th { background: #f7f7f7; }
tr:nth-child(even) { background: #fafafa; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.75rem; font-weight: 600; }
.badge-good { background: #d4f4dd; color: #1b6b34; }
.badge-bad { background: #fbdada; color: #8a1f1f; }
.badge-warn { background: #fdf0c8; color: #8a6d1f; }
.badge-neutral { background: #e2e2e2; color: #444; }
.rationale { color: #555; font-size: 0.85rem; }
.arrow { text-align: center; color: #999; font-size: 1.3rem; margin: -0.5rem 0 0.5rem; }
.meta { color: #666; font-size: 0.85rem; padding: 0 1.1rem 0.8rem; }
"""

_TIER_KIND = {"grounded": "good", "generic": "neutral"}
_STATUS_KIND = {"untested": "warn", "confirmed": "neutral", "refuted": "bad", "n/a": "neutral"}


def _status_kind(status: str) -> str:
    return _STATUS_KIND.get(status.split("+")[0], "warn")


def _layer(title: str, count_label: str, body: str) -> str:
    return f"""
<section class="layer">
  <div class="layer-header"><h2>{esc(title)}</h2><span class="layer-count">{esc(count_label)}</span></div>
  <details>
    <summary>Show details</summary>
    {body}
  </details>
</section>
<div class="arrow">&#8595;</div>"""


def _render_heuristics(heuristics: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{esc(h['id'])}</td><td>{esc(h['category'])}</td><td>{esc(h['description'])}</td><td>{h['base_weight']}</td></tr>"
        for h in heuristics
    )
    return f"""<table>
<thead><tr><th>Id</th><th>Category</th><th>Description</th><th>Base weight</th></tr></thead>
<tbody>{rows}</tbody></table>"""


def _render_domain(domain: dict) -> str:
    req_rows = "".join(
        f"<tr><td>{esc(f['name'])}</td><td>{esc(f['type'])}</td><td>{esc(f['description'])}</td></tr>"
        for f in domain.get("request_fields", [])
    )
    resp_rows = "".join(
        f"<tr><td>{esc(f['name'])}</td><td>{esc(f['type'])}</td><td>{esc(f['description'])}</td></tr>"
        for f in domain.get("response_fields", [])
    )
    rules = "".join(f"<li>{inline_markdown(r)}</li>" for r in domain.get("business_rules", []))
    decline_reasons = ", ".join(domain.get("known_decline_reasons", []))
    return f"""
<p><strong>{esc(domain.get('endpoint', {}).get('method', ''))} {esc(domain.get('endpoint', {}).get('path', ''))}</strong> - {esc(domain.get('description', ''))}</p>
<p><strong>Request fields</strong></p>
<table><thead><tr><th>Field</th><th>Type</th><th>Description</th></tr></thead><tbody>{req_rows}</tbody></table>
<p><strong>Response fields</strong></p>
<table><thead><tr><th>Field</th><th>Type</th><th>Description</th></tr></thead><tbody>{resp_rows}</tbody></table>
<p><strong>Known decline reasons:</strong> {esc(decline_reasons)}</p>
<p><strong>Business rules</strong></p>
<ul>{rules}</ul>"""


def _render_context(context: dict) -> str:
    results_rows = "".join(
        f"<tr><td>{esc(r.get('claim_id', ''))}</td><td>{bool_badge_text(r.get('verified'))}</td><td>{esc(r.get('timestamp', ''))}</td></tr>"
        for r in context.get("test_results", [])
    )
    jira_rows = "".join(
        f"<tr><td>{esc(j.get('title', ''))}</td><td>{esc(j.get('description', ''))}</td></tr>"
        for j in context.get("jira_entries", [])
    )
    risk_rows = "".join(f"<li>{esc(str(r))}</li>" for r in context.get("risk_assessments", []))
    return f"""
<p><strong>Test results ({len(context.get('test_results', []))})</strong></p>
<table><thead><tr><th>Claim id</th><th>Verified</th><th>Timestamp</th></tr></thead><tbody>{results_rows or '<tr><td colspan="3"><em>none yet</em></td></tr>'}</tbody></table>
<p><strong>JIRA entries ({len(context.get('jira_entries', []))})</strong></p>
<table><thead><tr><th>Title</th><th>Description</th></tr></thead><tbody>{jira_rows or '<tr><td colspan="2"><em>none yet</em></td></tr>'}</tbody></table>
<p><strong>Risk assessments ({len(context.get('risk_assessments', []))})</strong></p>
<ul>{risk_rows or '<li><em>none yet</em></li>'}</ul>"""


def bool_badge_text(value) -> str:
    if value is True:
        return badge("verified", "good")
    if value is False:
        return badge("refuted", "bad")
    return badge("unknown", "warn")


def _render_oracle(ranked: dict, top_n: int = 25) -> str:
    ideas = ranked["ranked_ideas"]
    rows = "".join(f"""
        <tr>
          <td>{idea['rank']}</td>
          <td>{esc(idea['id'])}</td>
          <td>{idea['score']:.1f}</td>
          <td>{badge(idea['tier'], _TIER_KIND.get(idea['tier'], 'neutral'))}</td>
          <td>{badge(idea['status'], _status_kind(idea['status']))}</td>
          <td>{esc(idea['category'])}</td>
          <td>{inline_markdown(idea['claim'])}</td>
        </tr>""" for idea in ideas[:top_n])
    return f"""
<p>Showing top {min(top_n, len(ideas))} of {len(ideas)} ranked test ideas (grounded claims + generic heuristic probes, combined and sorted).</p>
<table>
<thead><tr><th>Rank</th><th>Id</th><th>Score</th><th>Tier</th><th>Status</th><th>Category</th><th>Claim</th></tr></thead>
<tbody>{rows}</tbody></table>"""


def render_html(sut: str, heuristics: list[dict], domain: dict, context: dict, ranked: dict) -> str:
    grounded_count = sum(1 for i in ranked["ranked_ideas"] if i["tier"] == "grounded")
    generic_count = sum(1 for i in ranked["ranked_ideas"] if i["tier"] == "generic")

    body = "".join([
        _layer("1. Heuristic library (generic ontology)", f"{len(heuristics)} heuristics", _render_heuristics(heuristics)),
        _layer("2. Business / domain layer", f"{len(domain.get('request_fields', []))} request fields, {len(domain.get('known_accounts', []))} known accounts", _render_domain(domain)),
        _layer("3. Context / source layer", f"{len(context.get('test_results', []))} results, {len(context.get('jira_entries', []))} jira, {len(context.get('risk_assessments', []))} risk", _render_context(context)),
        _layer("4. Oracle (prioritized test ideas)", f"{grounded_count} grounded + {generic_count} generic = {len(ranked['ranked_ideas'])} total", _render_oracle(ranked)),
    ]).rsplit('<div class="arrow">&#8595;</div>', 1)[0]  # no trailing arrow after last layer

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ontology stack - {esc(sut)}</title>
<style>{CSS}</style>
</head>
<body>
<h1>Ontology stack - {esc(sut)}</h1>
<p class="meta">Generated {esc(ranked['generated_at'])}</p>
{body}
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the full ontology stack (4 layers) as one HTML page.")
    parser.add_argument("--sut", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    heuristics = load_heuristics()
    domain_path = ONTOLOGY_DIR / f"domain_{args.sut}.json"
    domain = json.loads(domain_path.read_text(encoding="utf-8")) if domain_path.exists() else {}
    context = load_context(args.sut)
    ranked = build_ranked_ideas(args.sut)

    out_path = Path(args.out) if args.out else Path("runs/ontology") / args.sut / "ontology_website.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(args.sut, heuristics, domain, context, ranked), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

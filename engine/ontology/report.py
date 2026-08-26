"""Renders a layer-4 ranked-oracle output (oracle_ranked.json) as a single
self-contained HTML page - one row per test idea, ordered by rank, with tier
(grounded vs generic) and status visible at a glance. Reuses the small
CSS/badge/escaping helpers already shared across engine.report.

Run: python -m engine.ontology.report --sut token_purchase
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.report import badge, esc, inline_markdown

CSS = """
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; margin: 2rem; color: #1a1a1a; background: #fafafa; }
h1 { font-size: 1.4rem; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top; font-size: 0.9rem; }
th { background: #f0f0f0; position: sticky; top: 0; }
tr:nth-child(even) { background: #f7f7f7; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.75rem; font-weight: 600; }
.badge-good { background: #d4f4dd; color: #1b6b34; }
.badge-bad { background: #fbdada; color: #8a1f1f; }
.badge-warn { background: #fdf0c8; color: #8a6d1f; }
.badge-neutral { background: #e2e2e2; color: #444; }
.rationale { color: #555; font-size: 0.85rem; }
.meta { color: #666; font-size: 0.85rem; margin-bottom: 1rem; }
"""

_TIER_KIND = {"grounded": "good", "generic": "neutral"}
_STATUS_KIND = {
    "untested": "warn",
    "confirmed": "neutral",
    "refuted": "bad",
    "n/a": "neutral",
}


def _status_kind(status: str) -> str:
    base = status.split("+")[0]
    return _STATUS_KIND.get(base, "warn")


def render_html(ranked: dict) -> str:
    rows = []
    for idea in ranked["ranked_ideas"]:
        rows.append(f"""
        <tr>
          <td>{idea['rank']}</td>
          <td>{idea['score']:.1f}</td>
          <td>{badge(idea['tier'], _TIER_KIND.get(idea['tier'], 'neutral'))}</td>
          <td>{badge(idea['status'], _status_kind(idea['status']))}</td>
          <td>{esc(idea['category'])}</td>
          <td>{inline_markdown(idea['claim'])}</td>
          <td class="rationale">{inline_markdown(idea['rationale'])}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ranked oracle - {esc(ranked['sut'])}</title>
<style>{CSS}</style>
</head>
<body>
<h1>Ranked oracle test ideas - {esc(ranked['sut'])}</h1>
<div class="meta">Generated {esc(ranked['generated_at'])} - {len(ranked['ranked_ideas'])} ideas</div>
<table>
<thead><tr><th>Rank</th><th>Score</th><th>Tier</th><th>Status</th><th>Category</th><th>Claim</th><th>Rationale</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a ranked oracle JSON file as HTML.")
    parser.add_argument("--sut", required=True)
    parser.add_argument("--in", dest="in_path", default=None, help="Input path (default: runs/ontology/<sut>/oracle_ranked.json)")
    parser.add_argument("--out", default=None, help="Output path (default: runs/ontology/<sut>/oracle_ranked.html)")
    args = parser.parse_args()

    in_path = Path(args.in_path) if args.in_path else Path("runs/ontology") / args.sut / "oracle_ranked.json"
    ranked = json.loads(in_path.read_text(encoding="utf-8"))

    out_path = Path(args.out) if args.out else Path("runs/ontology") / args.sut / "oracle_ranked.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(ranked), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

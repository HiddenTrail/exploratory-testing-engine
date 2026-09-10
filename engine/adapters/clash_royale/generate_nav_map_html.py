"""Generate an interactive HTML navigation map from a recon pass or wiki.

Usage (from recon pass):
    python -m engine.adapters.clash_royale.generate_nav_map_html \\
        "experiments/android-bot/out/Clash Royale-20260903-153913"

Usage (from wiki):
    python -m engine.adapters.clash_royale.generate_nav_map_html \\
        "experiments/android-bot/wiki"

Produces: navigation_map.html in the specified directory.

This creates an interactive browser-viewable page showing:
- Screen nodes with real names, images, and descriptions
- Navigation edges with action details (drag/click coordinates)
- Clickable nodes that display screen details, element positions, and clickable targets
- Legend showing screen status (hub, dead end, unreachable, sink)
- Structural problems and gaps identified in the map
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path


def _display_name(screen: dict) -> str:
    """Human-readable screen name, with any leading 'scNN - ' prefix stripped.

    Falls back to 'unnamed' when the screen has no name.
    """
    name = (screen.get("name") or "").strip()
    if not name:
        return "unnamed"
    # Names sometimes embed the id, e.g. "sc01 - main menu"; drop that prefix.
    name = re.sub(r"^sc\d+\s*[-–—:]\s*", "", name).strip()
    return name or "unnamed"


def generate_html(source_dir: Path) -> str:
    """Generate HTML from a recon pass directory or wiki directory."""

    # Detect source type
    ontology_path = source_dir / "ontology.json"
    wiki_path = source_dir / "entities"

    if ontology_path.exists():
        ontology = _load_from_recon_pass(source_dir)
    elif wiki_path.exists():
        ontology = _load_from_wiki(source_dir)
    else:
        raise SystemExit(
            f"No ontology.json or wiki/entities/ found in {source_dir}\n"
            "Expected either a recon pass directory or a wiki directory"
        )

    # Continue with HTML generation
    return _generate_html_from_ontology(source_dir, ontology)


def _load_from_recon_pass(pass_dir: Path) -> dict:
    """Load ontology from a recon pass."""
    ontology_path = pass_dir / "ontology.json"
    return json.loads(ontology_path.read_text(encoding="utf-8"))


def _load_from_wiki(wiki_dir: Path) -> dict:
    """Load ontology from wiki markdown files."""

    screens = []
    transitions = []

    # Load screen entities
    entities_dir = wiki_dir / "entities"
    concepts_dir = wiki_dir / "concepts"

    for entity_file in sorted(entities_dir.glob("clash-royale-sc*.md")):
        screen_data = _parse_screen_entity(entity_file)
        if screen_data:
            screens.append(screen_data)

    # Load transitions from navigation map concept
    nav_map_file = concepts_dir / "clash-royale-navigation-map.md"
    if nav_map_file.exists():
        transitions = _parse_navigation_map(nav_map_file, screens)

    return {
        "screens": screens,
        "transitions": transitions,
        "session": {"grid": [32, 18], "seconds": 0, "actions": 0},
    }


def _parse_screen_entity(file_path: Path) -> dict | None:
    """Extract screen data from a markdown entity file."""
    content = file_path.read_text(encoding="utf-8")

    # Extract frontmatter
    if not content.startswith("---"):
        return None

    end_marker = content.find("---", 3)
    if end_marker == -1:
        return None

    frontmatter = content[3:end_marker]
    body = content[end_marker + 3:].strip()

    # Extract screen ID from filename
    match = re.search(r"clash-royale-(sc\d+)", file_path.name)
    screen_id = match.group(1) if match else None

    if not screen_id:
        return None

    # Extract title and description from frontmatter
    title_match = re.search(r'title:\s*"([^"]+)"', frontmatter)
    description_match = re.search(r'description:\s*"([^"]+)"', frontmatter)

    title = title_match.group(1) if title_match else "Unknown"
    description = description_match.group(1) if description_match else "Unknown"

    # Parse body for details section
    observations = 0
    if "Seen **" in body:
        obs_match = re.search(r"Seen \*\*(\d+) times\*\*", body)
        if obs_match:
            observations = int(obs_match.group(1))

    return {
        "id": screen_id,
        "name": title,
        "purpose": description,
        "observations": observations,
        "identity_is_weak": False,
        "animated_cells": 0,
        "variants": [],
    }


def _parse_navigation_map(file_path: Path, screens: list) -> list:
    """Extract transitions from the navigation map concept file."""

    content = file_path.read_text(encoding="utf-8")
    transitions = []

    # Parse the ASCII graph section
    graph_start = content.find("```")
    if graph_start == -1:
        return transitions

    graph_end = content.find("```", graph_start + 3)
    if graph_end == -1:
        return transitions

    graph = content[graph_start + 3:graph_end]

    # Extract transitions from graph lines
    # Pattern: "sc01 <────── sc02" or "sc01 ─────> sc02"
    transition_patterns = [
        (r"(\w+)\s+<+[\w\s]+?(\w+)", lambda m: (m.group(2), m.group(1))),  # backwards arrow
        (r"(\w+)\s+─+>+\s+(\w+)", lambda m: (m.group(1), m.group(2))),  # forward arrow
        (r"(\w+)\s+═+>+\s+(\w+)", lambda m: (m.group(1), m.group(2))),  # double forward
    ]

    for line in graph.split("\n"):
        for pattern, extractor in transition_patterns:
            for match in re.finditer(pattern, line):
                from_id, to_id = extractor(match)
                if from_id and to_id:
                    # Check if not already added
                    if not any(
                        t["from"] == from_id and t["to"] == to_id for t in transitions
                    ):
                        transitions.append(
                            {
                                "from": from_id,
                                "to": to_id,
                                "at": {"kind": "drag", "at": (0.5, 0.5)},
                                "effect": "navigation",
                                "settle_ms": 0,
                                "changed_cells": 0,
                                "times_taken": 1,
                            }
                        )

    return transitions


def _generate_html_from_ontology(source_dir: Path, ontology: dict) -> str:
    """Generate HTML from ontology data."""

    # Map screen IDs to their data
    screens_by_id = {s["id"]: s for s in ontology["screens"]}

    # Build node positions (layout the graph)
    node_positions = _calculate_positions(ontology["screens"], ontology["transitions"])

    # Classify screens by structural role (drives node colors).
    categories = _classify_screens(ontology["screens"], ontology["transitions"])

    # Canvas extent from the computed layout, plus room for node radius + labels.
    max_x = max((x for x, _ in node_positions.values()), default=0) + _MARGIN
    max_y = max((y for _, y in node_positions.values()), default=0) + _MARGIN
    view_w, view_h = max_x + _MARGIN, max_y + _MARGIN

    # Build SVG nodes
    svg_nodes = _build_svg_nodes(screens_by_id, node_positions, categories)

    # Build SVG edges
    svg_edges = _build_svg_edges(ontology["transitions"], node_positions, screens_by_id)

    # Detect screens whose screenshots are near-identical (recon over-split).
    similar_groups = _find_similar_groups(screens_by_id, source_dir)

    # Build interactive panels
    detail_panels = _build_detail_panels(
        screens_by_id, ontology.get("transitions", []), similar_groups
    )

    html = f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Clash Royale Navigation Map</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}

                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background: #f5f5f5;
                    color: #333;
                }}

                .header {{
                    background: white;
                    border-bottom: 1px solid #ddd;
                    padding: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }}

                .header h1 {{
                    font-size: 24px;
                    margin-bottom: 5px;
                }}

                .header p {{
                    color: #666;
                    font-size: 14px;
                }}

                .container {{
                    display: flex;
                    height: calc(100vh - 150px);
                }}

                .canvas {{
                    flex: 1;
                    background: white;
                    overflow: auto;
                    border-right: 1px solid #ddd;
                    padding: 20px;
                }}

                .sidebar {{
                    width: 350px;
                    background: white;
                    overflow-y: auto;
                    border-left: 1px solid #ddd;
                    display: flex;
                    flex-direction: column;
                }}

                .panel {{
                    padding: 16px;
                    border-bottom: 1px solid #ddd;
                }}

                .panel h3 {{
                    font-size: 16px;
                    margin-bottom: 12px;
                    color: #000;
                }}

                .panel p {{
                    font-size: 13px;
                    line-height: 1.5;
                    color: #555;
                    margin-bottom: 8px;
                }}

                .dup-note {{
                    font-size: 12px;
                    line-height: 1.4;
                    color: #92400e;
                    background: #fef3c7;
                    border: 1px solid #fcd34d;
                    border-radius: 4px;
                    padding: 8px 10px;
                    margin: 8px 0;
                }}

                .surface-note {{
                    font-size: 12px;
                    line-height: 1.4;
                    color: #075985;
                    background: #e0f2fe;
                    border: 1px solid #7dd3fc;
                    border-radius: 4px;
                    padding: 8px 10px;
                    margin: 8px 0;
                }}

                .surface-panorama {{
                    display: block;
                    width: 100%;
                    max-width: 300px;
                    border: 1px solid #7dd3fc;
                    border-radius: 4px;
                    margin: 8px 0;
                }}

                .screen-image {{
                    width: 100%;
                    max-width: 300px;
                    border-radius: 4px;
                    margin: 12px 0;
                    border: 1px solid #ddd;
                }}

                .elements-table {{
                    width: 100%;
                    font-size: 12px;
                    margin-top: 12px;
                    border-collapse: collapse;
                }}

                .elements-table th {{
                    background: #f0f0f0;
                    padding: 6px;
                    text-align: left;
                    font-weight: 600;
                    border-bottom: 1px solid #ddd;
                }}

                .elements-table td {{
                    padding: 6px;
                    border-bottom: 1px solid #eee;
                }}

                .element-clickable {{
                    color: #0066cc;
                    font-weight: 500;
                }}

                .legend {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 20px;
                    padding: 14px 20px;
                    background: #f9f9f9;
                    border-top: 1px solid #ddd;
                }}

                .legend-item {{
                    display: flex;
                    align-items: center;
                    font-size: 12px;
                }}

                .legend-dot {{
                    width: 12px;
                    height: 12px;
                    border-radius: 50%;
                    margin-right: 8px;
                }}

                svg {{
                    display: block;
                }}

                .node {{
                    cursor: pointer;
                    transition: all 0.2s;
                }}

                .node:hover circle {{
                    filter: drop-shadow(0 0 8px rgba(0, 102, 204, 0.5));
                }}

                .node text {{
                    pointer-events: none;
                }}

                .edge {{
                    stroke: #ccc;
                    stroke-width: 2;
                    fill: none;
                    marker-end: url(#arrowhead);
                }}

                .edge-label {{
                    font-size: 11px;
                    fill: #999;
                    pointer-events: none;
                }}

                .node-label {{
                    font-size: 13px;
                    font-weight: 600;
                    fill: white;
                    text-anchor: middle;
                    pointer-events: none;
                }}

                .node-caption {{
                    font-size: 12px;
                    fill: #333;
                    text-anchor: middle;
                    pointer-events: none;
                }}

                .hidden {{
                    display: none;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Clash Royale Navigation Map</h1>
                <p>Interactive visualization of {len(ontology["screens"])} screens and {len(ontology["transitions"])} transitions. Click any screen for details.</p>
            </div>

            <div class="container">
                <div class="canvas">
                    <svg width="{view_w}" height="{view_h}" viewBox="0 0 {view_w} {view_h}">
                        <defs>
                            <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                                <polygon points="0 0, 10 3, 0 6" fill="#ccc"/>
                            </marker>
                        </defs>

                        <g id="edges">
                            {svg_edges}
                        </g>

                        <g id="nodes">
                            {svg_nodes}
                        </g>
                    </svg>
                </div>

                <div class="sidebar">
                    <div id="detail-panels" class="detail-panels">
                        <div id="detail-placeholder" class="panel" style="color: #999; text-align: center; padding: 40px 16px;">
                            <p>Click a screen to see its screenshot, details, and navigation.</p>
                        </div>
                        {detail_panels}
                    </div>
                </div>
            </div>

            <div class="legend">
                <div class="legend-item">
                    <div class="legend-dot" style="background: #2563eb;"></div>
                    <span>Navigation Hub</span>
                </div>
                <div class="legend-item">
                    <div class="legend-dot" style="background: #0891b2;"></div>
                    <span>Navigation Node</span>
                </div>
                <div class="legend-item">
                    <div class="legend-dot" style="background: #dc2626;"></div>
                    <span>Dead End</span>
                </div>
                <div class="legend-item">
                    <div class="legend-dot" style="background: #9333ea;"></div>
                    <span>Unreachable</span>
                </div>
                <div class="legend-item">
                    <div class="legend-dot" style="background: #ea580c;"></div>
                    <span>Inescapable Sink</span>
                </div>
            </div>

            <script>
                function showScreen(screenId) {{
                    const placeholder = document.getElementById('detail-placeholder');
                    if (placeholder) placeholder.classList.add('hidden');

                    const allPanels = document.querySelectorAll('.screen-detail-panel');
                    allPanels.forEach(p => p.classList.add('hidden'));

                    const targetPanel = document.getElementById('panel-' + screenId);
                    if (targetPanel) {{
                        targetPanel.classList.remove('hidden');
                        // Scroll the sidebar (not the page) back to the top of the detail.
                        targetPanel.scrollIntoView({{ block: 'nearest' }});
                    }}
                }}

                // Add click handlers to nodes
                document.querySelectorAll('.node').forEach(node => {{
                    node.addEventListener('click', function() {{
                        showScreen(this.dataset.screenId);
                    }});
                }});
            </script>
        </body>
        </html>
    """

    return html


# Layout constants (SVG user units).
_H_SPACING = 170
_V_SPACING = 150
_MARGIN = 80


def _calculate_positions(screens: list, transitions: list) -> dict:
    """Compute a BFS-layered layout so the map scales to any number of screens.

    Screens are placed in rows by their BFS depth from an entry node (the flow
    of navigation reads top-to-bottom). Screens never reached by BFS
    (unreachable islands) are laid out in extra rows below.
    """
    ids = [s["id"] for s in screens]
    id_set = set(ids)

    # Build adjacency and degree maps from transitions.
    adjacency: dict[str, list[str]] = {sid: [] for sid in ids}
    in_degree: dict[str, int] = {sid: 0 for sid in ids}
    for trans in transitions:
        frm, to = trans["from"], trans["to"]
        if frm in id_set and to in id_set:
            if to not in adjacency[frm]:
                adjacency[frm].append(to)
            in_degree[to] += 1

    # Pick an entry node: prefer sc01, else the most-observed node with no
    # incoming edges, else the most-observed node overall.
    obs = {s["id"]: s.get("observations", 0) for s in screens}
    roots = [sid for sid in ids if in_degree[sid] == 0]
    if "sc01" in id_set:
        entry = "sc01"
    elif roots:
        entry = max(roots, key=lambda sid: obs.get(sid, 0))
    else:
        entry = max(ids, key=lambda sid: obs.get(sid, 0)) if ids else None

    # BFS to assign each reachable node a depth level.
    level_of: dict[str, int] = {}
    if entry is not None:
        level_of[entry] = 0
        queue = [entry]
        while queue:
            node = queue.pop(0)
            for nxt in adjacency[node]:
                if nxt not in level_of:
                    level_of[nxt] = level_of[node] + 1
                    queue.append(nxt)

    # Unreachable screens go into rows below the deepest BFS level.
    max_level = max(level_of.values(), default=-1)
    unreached = [sid for sid in ids if sid not in level_of]
    for offset, sid in enumerate(unreached):
        level_of[sid] = max_level + 1 + (offset // 6)

    # Group by level, then place each row spread horizontally.
    rows: dict[int, list[str]] = {}
    for sid in ids:
        rows.setdefault(level_of[sid], []).append(sid)

    positions: dict[str, tuple[int, int]] = {}
    max_row_width = max((len(row) for row in rows.values()), default=1)
    for level in sorted(rows):
        row = sorted(rows[level])
        y = _MARGIN + level * _V_SPACING
        # Center each row within the widest row's span.
        row_span = (len(row) - 1) * _H_SPACING
        full_span = (max_row_width - 1) * _H_SPACING
        x_start = _MARGIN + (full_span - row_span) / 2
        for i, sid in enumerate(row):
            positions[sid] = (int(x_start + i * _H_SPACING), y)

    return positions


def _build_svg_nodes(screens_by_id: dict, positions: dict, categories: dict) -> str:
    """Build SVG circle nodes for each screen."""

    svg = ""

    for screen_id, (x, y) in positions.items():
        screen = screens_by_id[screen_id]

        # Color reflects the screen's structural role in the graph.
        color = _get_node_color(categories.get(screen_id, "isolated"))

        name = _display_name(screen)
        # The full name goes in the tooltip; the on-canvas caption is truncated
        # so long names don't collide with neighbouring bubbles.
        caption = name if len(name) <= 24 else name[:23] + "…"

        svg += f"""
        <g class="node" data-screen-id="{screen_id}" onclick="showScreen('{screen_id}')">
            <circle cx="{x}" cy="{y}" r="35" fill="{color}"/>
            <text class="node-label" x="{x}" y="{y + 5}">{screen_id}</text>
            <text class="node-caption" x="{x}" y="{y + 55}">{html.escape(caption)}</text>
            <title>{html.escape(name)}</title>
        </g>
        """

    return svg


def _build_svg_edges(transitions: list, positions: dict, screens_by_id: dict) -> str:
    """Build SVG paths for transitions between screens."""

    svg = ""

    # Group transitions by (from, to) to avoid duplicate edges
    edges_seen = set()

    for trans in transitions:
        from_id = trans["from"]
        to_id = trans["to"]

        # Self-loops (a scroll or variant that stays on the same screen) carry no
        # navigation and would draw a degenerate zero-length path. A scrolled surface
        # is one node by design; its scrollability shows in the detail panel instead.
        if from_id == to_id:
            continue

        edge_key = (from_id, to_id)
        if edge_key in edges_seen:
            continue
        edges_seen.add(edge_key)

        if from_id not in positions or to_id not in positions:
            continue

        x1, y1 = positions[from_id]
        x2, y2 = positions[to_id]

        # Curve path
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        svg += f'<path class="edge" d="M {x1} {y1} Q {cx} {cy} {x2} {y2}"/>\n'

    return svg


def _build_detail_panels(
    screens_by_id: dict, transitions: list, similar_groups: dict | None = None
) -> str:
    """Build HTML panels for screen details (hidden until clicked)."""

    similar_groups = similar_groups or {}
    panels = ""

    for screen_id, screen in screens_by_id.items():
        name = _display_name(screen)
        purpose = (screen.get("purpose") or "").strip() or "Unknown"
        observations = screen.get("observations", 0)

        # A scrollable surface is one node, not a chain of per-offset look-alikes; the
        # recon records that it scrolls in a "surface" block. Surface it here so a
        # reader knows there is more content past the visible frame.
        surface = screen.get("surface")
        surface_note = ""
        if surface and surface.get("axes"):
            axes = " and ".join(surface["axes"])
            surface_note = (
                f'<p class="surface-note">↕ Scrollable surface ({axes}). '
                f'{surface.get("scroll_steps", 0)} scroll(s) observed; '
                f'at least {surface.get("revealed_cells_floor", 0)} cells of content '
                f'sit past the visible frame.</p>'
            )
            # The whole page stitched from the scroll frames, when one was built - this
            # is the payoff of treating the surface as one node rather than a chain.
            panorama = surface.get("panorama")
            if panorama:
                surface_note += (
                    f'<img class="surface-panorama" src="{html.escape(panorama)}" '
                    f'alt="{html.escape(name)} - whole page" loading="lazy">'
                )

        # Flag near-identical screenshots (likely a recon over-split).
        duplicate_note = ""
        siblings = similar_groups.get(screen_id)
        if siblings:
            sib_list = ", ".join(siblings)
            duplicate_note = (
                '<p class="dup-note">⚠ Screenshot is near-identical to '
                f"{sib_list} — the recon tool likely over-split one screen "
                "(e.g. an animated background changed the fingerprint).</p>"
            )

        # Embed the screen capture. The image path is relative to the recon
        # directory, which is also where this HTML is written, so it resolves
        # directly when the page is opened from there.
        image_path = screen.get("image")
        image_html = ""
        if image_path:
            image_html = (
                f'<img class="screen-image" src="{html.escape(image_path)}" '
                f'alt="{html.escape(name)}" loading="lazy">'
            )

        # Find transitions from this screen. Self-loops (a scroll that stays on the
        # same surface) are not ways to "navigate away", so they are excluded here and
        # summarised by the surface note instead.
        outgoing = [t for t in transitions
                    if t["from"] == screen_id and t["to"] != screen_id]
        incoming = [t for t in transitions
                    if t["to"] == screen_id and t["from"] != screen_id]

        # Build transition details
        transition_details = ""
        if outgoing:
            transition_details += "<p><strong>Actions that navigate away:</strong></p><ul>"
            for trans in outgoing:
                action = trans.get("at", {})
                kind = action.get("kind", "unknown")
                coord = action.get("at", ())
                effect = trans.get("effect", "unknown")
                transition_details += f"<li>→ {trans['to']}: {kind} at {coord} ({effect})</li>"
            transition_details += "</ul>"

        if incoming:
            transition_details += f"<p><strong>{len(incoming)} action(s) lead here</strong></p>"

        panels += f"""
        <div id="panel-{screen_id}" class="screen-detail-panel hidden">
            <div class="panel">
                <h3>{screen_id} — {html.escape(name)}</h3>
                {duplicate_note}
                {surface_note}
                {image_html}
                <p>{html.escape(purpose)}</p>
                <p style="font-size: 12px; color: #999;">Observed {observations} times</p>
                {transition_details}
            </div>
        </div>
        """

    return panels


# Category -> color, mirroring the on-page legend.
_CATEGORY_COLORS = {
    "hub": "#2563eb",
    "navigation": "#0891b2",
    "dead_end": "#dc2626",
    "unreachable": "#9333ea",
    "sink": "#ea580c",
    "isolated": "#666666",
}


def _classify_screens(screens: list, transitions: list) -> dict:
    """Assign each screen a structural category derived from the real graph.

    - unreachable: nothing navigates into it (in-degree 0), and it isn't the entry.
    - dead_end:    it navigates nowhere (out-degree 0) but is reachable.
    - hub:         high out-degree (routes to many screens).
    - navigation:  everything else that both takes and gives edges.
    """
    ids = [s["id"] for s in screens]
    id_set = set(ids)

    out_degree = {sid: 0 for sid in ids}
    in_degree = {sid: 0 for sid in ids}
    out_targets = {sid: set() for sid in ids}
    for trans in transitions:
        frm, to = trans["from"], trans["to"]
        if frm in id_set and to in id_set:
            out_targets[frm].add(to)
            in_degree[to] += 1
    for sid in ids:
        out_degree[sid] = len(out_targets[sid])

    entry = "sc01" if "sc01" in id_set else (ids[0] if ids else None)
    hub_threshold = 4  # routes to 4+ distinct screens

    categories = {}
    for sid in ids:
        if in_degree[sid] == 0 and out_degree[sid] == 0:
            categories[sid] = "isolated"
        elif in_degree[sid] == 0 and sid != entry:
            categories[sid] = "unreachable"
        elif out_degree[sid] == 0:
            categories[sid] = "dead_end"
        elif out_degree[sid] >= hub_threshold:
            categories[sid] = "hub"
        else:
            categories[sid] = "navigation"
    return categories


def _get_node_color(category: str) -> str:
    """Map a structural category to its legend color."""
    return _CATEGORY_COLORS.get(category, _CATEGORY_COLORS["isolated"])


# Max average-hash Hamming distance (of 256 bits) for two screenshots to be
# treated as the same screen. Calibrated against the Social-screen over-split.
_SIMILARITY_THRESHOLD = 22


def _find_similar_groups(screens_by_id: dict, source_dir: Path) -> dict:
    """Group screens whose screenshots are near-identical.

    The recon tool can over-split one logical screen into several IDs when an
    animated background changes the fingerprint. This flags those so the map
    doesn't silently show the same picture under different names.

    Returns {screen_id: [sibling ids...]}. Requires Pillow; if it's missing the
    detection is skipped (returns {}), so the map still renders.
    """
    try:
        from PIL import Image
    except ImportError:
        return {}

    def average_hash(path: Path) -> list[int] | None:
        try:
            img = Image.open(path).convert("L").resize((16, 16))
        except (FileNotFoundError, OSError):
            return None
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        return [1 if p > avg else 0 for p in pixels]

    hashes: dict[str, list[int]] = {}
    for sid, screen in screens_by_id.items():
        image_rel = screen.get("image")
        if not image_rel:
            continue
        h = average_hash(source_dir / image_rel)
        if h is not None:
            hashes[sid] = h

    ids = list(hashes)

    # Union-find over near-identical pairs (single-linkage clustering).
    parent = {sid: sid for sid in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            hamming = sum(x != y for x, y in zip(hashes[a], hashes[b]))
            if hamming <= _SIMILARITY_THRESHOLD:
                parent[find(a)] = find(b)

    clusters: dict[str, list[str]] = {}
    for sid in ids:
        clusters.setdefault(find(sid), []).append(sid)

    similar: dict[str, list[str]] = {}
    for members in clusters.values():
        if len(members) > 1:
            members = sorted(members)
            for sid in members:
                similar[sid] = [m for m in members if m != sid]
    return similar


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)

    source_dir = Path(sys.argv[1])
    if not source_dir.exists():
        raise SystemExit(f"directory not found: {source_dir}")

    html = generate_html(source_dir)

    output_path = source_dir / "navigation_map.html"
    output_path.write_text(html, encoding="utf-8")

    print(f"Generated {output_path} ({output_path.stat().st_size // 1024}KB)")
    print(f"Open in browser: {output_path.resolve().as_uri()}")


if __name__ == "__main__":
    main()

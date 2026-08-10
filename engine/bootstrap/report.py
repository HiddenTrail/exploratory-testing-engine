"""Renders a DiscoveredSchema (Phase 1/2 of the adapter-bootstrap roadmap) as
a self-contained HTML page - the --discover-only counterpart to
engine.report's full checkpoint-loop report. Reuses engine.report's public
CSS/esc/badge helpers so both report styles look like one consistent tool,
not two unrelated ones.
"""

from engine.bootstrap.discovery import DiscoveredEndpoint, DiscoveredField, DiscoveredSchema
from engine.report import CSS, badge, bool_badge, esc, render_prose


def _render_field(field: DiscoveredField) -> str:
    enum_note = f" &middot; one of {esc(field.enum)}" if field.enum else ""
    default_note = f" &middot; default {esc(field.default)}" if field.has_default else ""
    description = f'<p class="prose-muted">{esc(field.description)}</p>' if field.description else ""
    return f"""
    <div class="test">
      <div class="test-hypothesis">
        <span class="test-number">{esc(field.name)}</span>
        <code>{esc(field.type)}</code>{enum_note}{default_note}
        {bool_badge(field.required, "required", "optional")}
      </div>
      {description}
    </div>
    """


def _render_endpoint(endpoint: DiscoveredEndpoint) -> str:
    fields_html = "".join(_render_field(f) for f in endpoint.request_fields) or (
        '<p class="prose-muted">No request fields discovered.</p>'
    )
    return f"""
    <div class="exhibit">
      <h3>{esc(endpoint.method)} {esc(endpoint.path)}</h3>
      <p class="eyebrow">Request fields ({len(endpoint.request_fields)})</p>
      <div class="test-grid">{fields_html}</div>
    </div>
    """


def _stat(value, label) -> str:
    return f'<div class="stat"><span class="num">{esc(value)}</span><span class="label">{esc(label)}</span></div>'


def render_discovery_report(schema: DiscoveredSchema, base_url: str) -> str:
    status_kind = "good" if schema.status == "found" else ("warn" if schema.status == "not_found" else "bad")
    stats = [
        _stat(schema.source, "source"),
        _stat("yes" if schema.confirmed else "no", "confirmed"),
        _stat(len(schema.endpoints), "endpoints found"),
    ]

    error_html = ""
    if schema.error:
        error_html = f"""
        <section id="error">
          <p class="eyebrow">Malformed document</p>
          <h2>Error</h2>
          <div class="exhibit"><p class="prose-muted">{esc(schema.error)}</p></div>
        </section>
        """

    notes_html = ""
    if schema.notes:
        notes_html = f"""
        <section id="notes">
          <p class="eyebrow">Notes</p>
          <h2>Commentary</h2>
          <div class="exhibit"><div class="prose">{render_prose(schema.notes)}</div></div>
        </section>
        """

    endpoints_html = "".join(_render_endpoint(e) for e in schema.endpoints) or (
        '<p class="prose-muted">No endpoints discovered.</p>'
    )

    nav_items = [("#endpoints", "Endpoints")]
    if schema.error:
        nav_items.append(("#error", "Error"))
    if schema.notes:
        nav_items.append(("#notes", "Notes"))
    nav_html = "".join(f'<li><a href="{href}">{label}</a></li>' for href, label in nav_items)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Discovered schema: {esc(base_url)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <span class="topbar-title">Discovered Schema</span>
    <ul class="topbar-nav">{nav_html}</ul>
  </div>
</div>

<div class="wrap">
  <div class="hero">
    <p class="eyebrow">Adapter-bootstrap Phase 1/2 {badge(schema.status, status_kind)}</p>
    <h1>{esc(base_url)}</h1>
    <div class="stat-row">{''.join(stats)}</div>
  </div>

  {error_html}

  <section id="endpoints">
    <p class="eyebrow">{esc(schema.fetched_from) if schema.fetched_from else "Discovery"}</p>
    <h2>Endpoints</h2>
    {endpoints_html}
  </section>

  {notes_html}
</div>
</body>
</html>
"""

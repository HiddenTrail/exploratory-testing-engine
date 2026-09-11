"""Turn a live browser page into one normalised, serialisable Observation.

This is the only module that touches Playwright. Everything downstream (identity,
oracles, the wiki) works on the Observation/ontology dataclasses, so it is all testable
against recorded fixtures with no browser attached.

An Observation is deliberately richer than a game frame: besides the visible structure
(the interactive elements and visible headings read straight off the page), it carries
the console messages and network responses/failures seen since the last one - the hard
evidence a deterministic oracle turns into a functional finding, with no model in the
loop. (The accessibility tree was tried and dropped: it is empty for a canvas app like
EcoEstate, so identity uses the DOM-read control set instead - see identity.py.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

# Interactive controls, read from the DOM rather than invented. Each gets a stable-ish
# CSS selector (id when present, else a positional path), an accessible name, and a
# role family - enough to identify it across visits and to act on it deterministically.
_ELEMENTS_JS = r"""
() => {
  const sel = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node.tagName.toLowerCase() !== 'html') {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const sibs = [...parent.children].filter(c => c.tagName === node.tagName);
        if (sibs.length > 1) part += `:nth-of-type(${sibs.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const name = (el) => {
    const explicit = el.getAttribute('aria-label')
      || el.getAttribute('title')
      || (el.tagName === 'INPUT' && el.labels && el.labels[0] && el.labels[0].textContent)
      || el.getAttribute('placeholder');
    if (explicit) return clean(explicit);
    // A button-like control's value IS its label; a text/search/number/checkbox value
    // is *user content* and must not become the control's identity, or typing into a
    // field would mint a new state (over-split) and "on" would collapse toggles.
    if (el.tagName === 'INPUT') {
      return ['submit', 'button', 'reset'].includes(el.type) ? clean(el.value) : '';
    }
    return clean(el.textContent);
  };
  const roleOf = (el) => {
    if (el.getAttribute('role')) return el.getAttribute('role');
    const t = el.tagName.toLowerCase();
    if (t === 'a') return 'link';
    if (t === 'button') return 'button';
    if (t === 'select') return 'combobox';
    if (t === 'textarea') return 'textbox';
    if (t === 'input') return (['button','submit','reset'].includes(el.type)) ? 'button'
      : (el.type === 'checkbox') ? 'checkbox'
      : (el.type === 'radio') ? 'radio' : 'textbox';
    return 'generic';
  };
  const q = 'a[href], button, input, select, textarea, [role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem], [onclick], [tabindex]';
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(q)) {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const s = sel(el);
    if (seen.has(s)) continue;
    seen.add(s);
    out.push({
      role: roleOf(el),
      name: name(el),
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      locator: s,
      href: el.getAttribute('href') || '',
      disabled: !!el.disabled,
    });
  }
  return out;
}
"""

# Visible headings, in order. These are the landmark text identity uses to tell apart
# views that share a control set but differ in content (a "You said yes" page and a
# "You said no" page both have only a Back button). Hidden headings - e.g. an SPA's
# inactive sections - are excluded, or every view would carry every other view's title.
_HEADINGS_JS = r"""
() => {
  const vis = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  };
  return [...document.querySelectorAll('h1, h2, h3, [role=heading]')]
    .filter(vis)
    .map((h) => (h.textContent || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .slice(0, 5);
}
"""


@dataclass
class Observation:
    url: str
    title: str
    headings: list[str] = field(default_factory=list)  # visible landmark text, in order
    elements: list[dict] = field(default_factory=list)
    console: list[dict] = field(default_factory=list)  # {type, text, location}
    network: list[dict] = field(default_factory=list)  # {method, url, status, failure?}
    text: str = ""                                     # visible body text sample

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Observation":
        # Tolerate extra keys (e.g. an older fixture's dropped `a11y` field) and missing
        # ones (defaults apply), so the corpus keeps loading as the shape evolves.
        allowed = {f.name for f in fields(Observation)}
        return Observation(**{k: v for k, v in d.items() if k in allowed})

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> "Observation":
        return Observation.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class Collector:
    """Accumulates console + network for a page across actions; drained per Observation."""

    def __init__(self) -> None:
        self.console: list[dict] = []
        self.network: list[dict] = []

    def attach(self, page) -> "Collector":
        page.on("console", lambda m: self.console.append(
            {"type": m.type, "text": m.text[:500], "location": str(getattr(m, "location", ""))[:300]}))
        page.on("pageerror", lambda e: self.console.append(
            {"type": "pageerror", "text": str(e)[:500], "location": ""}))
        page.on("response", lambda r: self.network.append(
            {"method": r.request.method, "url": r.url[:300], "status": r.status}))
        # A request that never gets a response (backend down, DNS/connection failure,
        # aborted fetch) fires this, not `response`. Recorded as status 0 with the
        # failure text so an oracle can flag a dead endpoint - a real functional defect.
        # The requestfailed event passes a Request (not a Response): it has .method /
        # .url / .failure directly - r.request would raise and lose the finding.
        page.on("requestfailed", lambda r: self.network.append(
            {"method": r.method, "url": r.url[:300], "status": 0,
             "failure": (r.failure or "")[:200]}))
        return self

    def drain(self) -> tuple[list[dict], list[dict]]:
        console, network = self.console[:], self.network[:]
        self.console.clear()
        self.network.clear()
        return console, network


def capture(page, collector: Collector) -> Observation:
    """One Observation of the page as it stands now. Assumes the caller already waited
    for whatever settle it wants - capture reads, it does not decide when."""
    console, network = collector.drain()
    elements = page.evaluate(_ELEMENTS_JS)
    headings = page.evaluate(_HEADINGS_JS)
    text = (page.inner_text("body")[:4000] if page.query_selector("body") else "")
    return Observation(
        url=page.url,
        title=page.title(),
        headings=headings,
        elements=elements,
        console=console,
        network=network,
        text=text,
    )


def visual_diff(before: bytes | None, after: bytes | None, cell_delta: int = 20):
    """Fraction of a downscaled grayscale frame that changed between two PNG screenshots,
    or None if it cannot be computed (Pillow absent / bad capture). Lets a canvas or map
    change the DOM signature and text cannot see still register as an effect - which is
    what keeps a pixel-only pan/zoom from being mistaken for a dead control. Shared by the
    deterministic crawler and the engine web-GUI adapter so both judge "did nothing" the
    same way.

    Each frame is autocontrast-stretched (histogram to full 0-255, ignoring the 1% extremes)
    before comparison. On a pale, low-contrast surface - a light choropleth map, a mostly
    white page - a genuine change lives in near-white values whose raw delta sits under
    cell_delta and would be missed; stretching spreads those values across the range so the
    change registers, while a true no-op stays at 0 (measured: it ~doubles the signal on a
    real pan/zoom and leaves an unchanged frame at 0.0)."""
    if not (before and after):
        return None
    try:
        import io
        from PIL import Image, ImageOps

        def _prep(png):
            im = Image.open(io.BytesIO(png)).convert("L")
            return ImageOps.autocontrast(im, cutoff=1).resize((64, 64)).tobytes()

        a, b = _prep(before), _prep(after)
    except Exception:
        return None
    if not a or len(a) != len(b):
        return None
    return sum(1 for x, y in zip(a, b) if abs(x - y) > cell_delta) / len(a)

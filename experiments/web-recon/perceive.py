"""Turn a live browser page into one normalised, serialisable Observation.

This is the only module that touches Playwright. Everything downstream (identity,
oracles, the wiki) works on the Observation/ontology dataclasses, so it is all testable
against recorded fixtures with no browser attached.

An Observation is deliberately richer than a game frame: besides the visible structure
(the accessibility tree and the interactive elements read straight off the page), it
carries the console messages and network responses seen since the last one - the hard
evidence a deterministic oracle turns into a functional finding, with no model in the
loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
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
  const name = (el) => (
    el.getAttribute('aria-label') ||
    el.getAttribute('title') ||
    el.getAttribute('placeholder') ||
    (el.tagName === 'INPUT' && el.labels && el.labels[0] && el.labels[0].textContent) ||
    (el.value && el.type !== 'text' ? el.value : '') ||
    (el.textContent || '').trim()
  ).replace(/\s+/g, ' ').trim().slice(0, 120);
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

# A structural outline of the accessibility tree: role[:name] per node, indented. This
# is the semantic skeleton identity is built from - stable across a data refresh, and
# far more meaningful than raw HTML.
_A11Y_ROLES_TO_KEEP_NAME = {"heading", "button", "link", "tab", "menuitem", "textbox", "combobox"}


@dataclass
class Observation:
    url: str
    title: str
    a11y: dict = field(default_factory=dict)          # page.accessibility.snapshot()
    elements: list[dict] = field(default_factory=list)
    console: list[dict] = field(default_factory=list)  # {type, text, location}
    network: list[dict] = field(default_factory=list)  # {method, url, status}
    text: str = ""                                     # visible body text sample

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Observation":
        return Observation(**d)

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
    try:
        a11y = page.accessibility.snapshot() or {}
    except Exception:
        a11y = {}
    elements = page.evaluate(_ELEMENTS_JS)
    text = (page.inner_text("body")[:4000] if page.query_selector("body") else "")
    return Observation(
        url=page.url,
        title=page.title(),
        a11y=a11y,
        elements=elements,
        console=console,
        network=network,
        text=text,
    )

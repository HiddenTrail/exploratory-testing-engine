"""The product layer of the oracle (issue #138): what the product wiki says about one
product, read from its pages' frontmatter. No model calls.

A product is named by a slug (`juice-shop`). Its overview page carries `product` and
`surfaces` (e.g. [gui]), and each entity page about it carries:

    product: juice-shop
    features: [login, form]          # tags from engine/ontology/heuristics/vocabulary.json
    facts:
      - id: F1                       # unique on the page; the global id adds product and page
        kind: shown                  # a fact kind from the vocabulary
        text: Apple Juice (1000ml) costs 1.99¤ in the list.
        source: screens              # one of the page's sources[].id

A fact's global id is `<product>.<page>.<id>`, e.g. `juice-shop.product-list.F1`, where
<page> is the file name without the product prefix. See AGENTS.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
WIKI_DIR = REPO / "wiki"
VOCABULARY = Path(__file__).parent / "heuristics" / "vocabulary.json"


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def _page_slug(path: Path, product: str) -> str:
    stem = path.stem
    return stem[len(product) + 1:] if stem.startswith(product + "-") else stem


def load_product(product: str, wiki_dir: Path = WIKI_DIR) -> dict[str, Any] | None:
    """The product's surfaces and its entities (features and facts), or None if the
    wiki has no overview for it."""
    pages = sorted(wiki_dir.rglob("*.md"))
    overview = next((p for p in pages if _frontmatter(p).get("type") == "Product Overview"
                     and _frontmatter(p).get("product") == product), None)
    if overview is None:
        return None
    entities = []
    for path in pages:
        meta = _frontmatter(path)
        if meta.get("type") != "Entity" or meta.get("product") != product:
            continue
        slug = _page_slug(path, product)
        sources = {s["id"]: s["resource"] for s in meta.get("sources", []) if "id" in s}
        entities.append({
            "slug": slug,
            "title": meta.get("title", slug),
            "page": path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else str(path),
            "features": list(meta.get("features", [])),
            "facts": [{
                "local_id": (local_id := fact.get("id")),
                "id": f"{product}.{slug}.{local_id}" if local_id else None,
                "kind": fact.get("kind"),
                "text": fact.get("text", ""),
                "source": sources.get(fact.get("source"), ""),
            } for fact in meta.get("facts", [])],
        })
    return {"product": product, "surfaces": list(_frontmatter(overview).get("surfaces", [])), "entities": entities}


def product_errors(product: str, wiki_dir: Path = WIKI_DIR) -> list[str]:
    """What's wrong with a product's pages: unknown features or fact kinds, facts
    without text or with a source the page doesn't list, duplicate fact ids."""
    vocabulary = json.loads(VOCABULARY.read_text(encoding="utf-8"))
    features = set(vocabulary["tags"]["feature"]) | set(vocabulary["tags"]["surface"])
    kinds = set(vocabulary["fact_kinds"])
    loaded = load_product(product, wiki_dir)
    if loaded is None:
        return [f"no Product Overview page with product: {product}"]
    errors = [f"surface '{s}' isn't in the vocabulary" for s in loaded["surfaces"]
              if s not in vocabulary["tags"]["surface"]]
    seen = set()
    for entity in loaded["entities"]:
        where = entity["page"]
        errors += [f"{where}: feature '{f}' isn't in the vocabulary" for f in entity["features"] if f not in features]
        for fact in entity["facts"]:
            if not fact["local_id"]:
                errors.append(f"{where}: fact has no id")
                continue
            if fact["kind"] not in kinds:
                errors.append(f"{where}: {fact['id']} has kind '{fact['kind']}', not one of {sorted(kinds)}")
            if not str(fact["text"]).strip():
                errors.append(f"{where}: {fact['id']} has no text")
            if not fact["source"]:
                errors.append(f"{where}: {fact['id']} cites a source the page doesn't list")
            if fact["id"] in seen:
                errors.append(f"{where}: {fact['id']} is used twice")
            seen.add(fact["id"])
    return errors

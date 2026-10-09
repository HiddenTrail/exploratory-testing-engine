"""The oracle seeder (issue #138): builds one product's oracle by running the heuristic
library (layer 1) and the product's facts from the wiki (layer 2) through the oracle
seeds in trailhound/ontology/seeds/ (FEW HICCUPPS). No model calls, so it's free to
rebuild whenever the wiki or the library changes.

Each seed says what it draws on:
- fact_kinds: each product fact of these kinds becomes an expectation ("fact" tier)
- heuristic_ids / heuristic_tags / heuristic_kinds: these library heuristics are applied.
  One with feature tags goes on every screen sharing a feature ("heuristic" tier,
  ranked higher); one without goes on the product as a whole.
- standing: one expectation for the whole product ("standing" tier)

The output is plain data with stable ids and sources, so it can become what a separate
Oracle service hands the Driver. Run: python -m trailhound.ontology.seeder --product juice-shop
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from trailhound.ontology import product as product_layer
from trailhound.ontology.oracle_creator import (FEATURE_MATCH_BONUS, GROUNDED_BASE_SCORE, SURFACE_MATCH_BONUS,
                                            load_heuristics, load_vocabulary)

SEEDS_DIR = Path(__file__).parent / "seeds"
GENERATED_FACT_PENALTY = 2.0


def load_seeds() -> list[dict[str, Any]]:
    seeds = []
    for path in sorted(SEEDS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        seeds.extend({**s, "source": data["source"]} for s in data["seeds"])
    return seeds


def _owner(seeds: list[dict], heuristic: dict) -> dict | None:
    """The one seed a heuristic goes under. A seed that names it by id gets it before
    one that only matches its tags or kind: World names monetary_precision, and
    without this the broader 'consistency' tag handed it to Product instead."""
    for seed in seeds:
        if heuristic["id"] in seed.get("draws_on", {}).get("heuristic_ids", ()):
            return seed
    for seed in seeds:
        on = seed.get("draws_on", {})
        if set(heuristic["tags"]) & set(on.get("heuristic_tags", ())) or heuristic["kind"] in on.get("heuristic_kinds", ()):
            return seed
    return None


def build_oracle(product: str, wiki_dir: Path | None = None) -> dict[str, Any]:
    """{"product", "seeds", "expectations": [...]}, every expectation with an id, its
    seed, tier, entity, claim, how to check it, its sources and a score."""
    # The screens Spoor's map showed, from the product's context (#311), next to what the
    # wiki says. A product nobody has written about yet still gets an oracle from them.
    screens = product_layer.context_screens(product)
    errors = [e for e in product_layer.product_errors(product, wiki_dir)
              if not (screens and e.startswith("no Product Overview"))]
    if errors:
        raise ValueError("invalid product layer:\n" + "\n".join(errors))
    prod = product_layer.load_product(product, wiki_dir)
    if prod is None and screens:
        prod = {"product": product, "surfaces": ["gui"], "entities": []}
    if prod is None:
        raise ValueError(f"the wiki has no Product Overview for '{product}', and its context has no screens")
    prod = {**prod, "entities": prod["entities"] + screens}
    vocabulary = load_vocabulary()
    surface_tags, feature_tags = set(vocabulary["tags"]["surface"]), set(vocabulary["tags"]["feature"])
    surfaces = set(prod["surfaces"])

    def fits(h):
        own = surface_tags & set(h["tags"])
        return not own or bool(own & surfaces)

    heuristics = [h for h in load_heuristics() if fits(h)]
    seeds = load_seeds()
    owner = {h["id"]: _owner(seeds, h) for h in heuristics}
    expectations = []
    for seed in seeds:
        if seed.get("standing"):
            expectations.append({
                "id": f"oracle:{seed['id']}:product", "seed": seed["id"], "seed_name": seed["name"],
                "tier": "standing", "entity": "product", "claim": seed["standing"], "check": seed["question"],
                "sources": [f"seed:{seed['id']}"], "score": GROUNDED_BASE_SCORE,
            })
        for entity in prod["entities"]:
            for fact in entity["facts"]:
                if fact["kind"] not in seed.get("draws_on", {}).get("fact_kinds", ()):
                    continue
                expectations.append({
                    "id": f"oracle:{seed['id']}:{fact['id']}", "seed": seed["id"], "seed_name": seed["name"],
                    "tier": "fact", "entity": entity["slug"],
                    "claim": seed["fact_template"].format(fact=fact["text"].rstrip("."), entity=entity["title"]),
                    "check": f"Compare what the product does with fact {fact['id']}.",
                    "sources": [fact["id"], fact["source"], entity["page"]],
                    # A fact generated from Spoor's map only describes a screen (#311): it
                    # shouldn't outrank the heuristics aimed at what that screen has.
                    "score": GROUNDED_BASE_SCORE - (GENERATED_FACT_PENALTY if entity.get("generated") else 0.0),
                })
        for h in heuristics:
            if owner[h["id"]] is not seed:
                continue
            bonus = SURFACE_MATCH_BONUS if surface_tags & set(h["tags"]) & surfaces else 0.0
            wanted = set(h["tags"]) & feature_tags
            targets = ([e for e in prod["entities"] if wanted & set(e["features"])] if wanted
                       else [{"slug": "product", "title": "the product", "page": ""}])
            for entity in targets:
                expectations.append({
                    "id": f"oracle:{seed['id']}:{entity['slug']}:{h['id']}", "seed": seed["id"],
                    "seed_name": seed["name"], "tier": "heuristic", "entity": entity["slug"],
                    "claim": seed["heuristic_template"].format(entity=entity["title"],
                                                               description=h["description"].rstrip(".")),
                    "check": h["apply"],
                    "sources": [f"heuristic:{h['id']}"] + ([entity["page"]] if entity["page"] else []),
                    "score": float(h["base_weight"]) + bonus + (FEATURE_MATCH_BONUS if wanted else 0.0),
                })
    # Said out loud, not dropped quietly: 40 of 118 heuristics, console_and_network_errors
    # among them, once fell through every seed without anyone noticing (issue #246).
    not_drawn_on = sorted(h["id"] for h in heuristics if owner[h["id"]] is None)
    return {"product": product, "seeds": [s["id"] for s in seeds], "expectations": expectations,
            "not_drawn_on": not_drawn_on}


def pick_across_seeds(ideas: list[dict], limit: int) -> list[dict]:
    """The best `limit` ideas, taking turns across seeds so that every seed is
    represented: a product's facts all outrank every heuristic, and a plain top-N
    would hand the Driver nothing but self-consistency checks."""
    # Within a seed, equal scores alternate between screens: otherwise a seed's first
    # picks were all from the alphabetically first page (the login page's facts, not
    # the product list's prices).
    nth: dict[tuple, int] = {}
    keyed = []
    for idea in ideas:
        key = (idea["category"], idea.get("entity"))
        keyed.append((-idea["score"], nth.get(key, 0), idea))
        nth[key] = nth.get(key, 0) + 1
    by_seed: dict[str, list[dict]] = {}
    for _, _, idea in sorted(keyed, key=lambda k: (k[0], k[1])):
        by_seed.setdefault(idea["category"], []).append(idea)
    order = sorted(by_seed, key=lambda s: by_seed[s][0]["score"], reverse=True)
    picked = []
    while len(picked) < limit and any(by_seed.values()):
        for seed in order:
            if by_seed[seed] and len(picked) < limit:
                picked.append(by_seed[seed].pop(0))
    return sorted(picked, key=lambda i: i["score"], reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a product's oracle from the heuristic library and its wiki.")
    parser.add_argument("--product", required=True, help="product slug, e.g. juice-shop")
    parser.add_argument("--out", default=None, help="write the oracle here as JSON (default: print a summary)")
    args = parser.parse_args()
    oracle = build_oracle(args.product)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(oracle, indent=2, ensure_ascii=False), encoding="utf-8")
    counts: dict[str, int] = {}
    for e in oracle["expectations"]:
        counts[e["seed"]] = counts.get(e["seed"], 0) + 1
    print(f"{len(oracle['expectations'])} expectations for {args.product}: "
          + ", ".join(f"{seed} {n}" for seed, n in counts.items()))
    if oracle["not_drawn_on"]:
        print(f"{len(oracle['not_drawn_on'])} heuristics no seed draws on (techniques and product models, "
              f"by design so far): {', '.join(oracle['not_drawn_on'])}")


if __name__ == "__main__":
    main()

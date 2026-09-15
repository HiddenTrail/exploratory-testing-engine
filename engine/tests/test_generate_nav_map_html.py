from engine.adapters.clash_royale.generate_nav_map_html import generate_html


def test_generate_html_from_wiki_carries_surface_panorama(tmp_path):
    entities = tmp_path / "entities"
    entities.mkdir()
    (entities / "clash-royale-sc01-main-screen.md").write_text(
        """---
type: Entity
title: "sc01 — Clash Royale Main screen"
description: "The home screen."
---

# sc01 — Clash Royale Main screen

## Details

Seen **3 times**

## The whole page

This screen scrolls (vertical); the recon recognised 2 scroll(s) on it as the same surface rather than new screens, and at least 7 cells of content sit past the visible frame.

![sc01 - whole page](images/surface-sc01.png)
""",
        encoding="utf-8",
    )

    html = generate_html(tmp_path)

    assert "Scrollable surface (vertical)" in html
    assert 'src="images/surface-sc01.png"' in html

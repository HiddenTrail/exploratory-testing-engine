# Clash Royale Adapter

Adapter for testing the Clash Royale game client. Includes screen recognition, navigation mapping, and test orchestration.

## Scripts

### `extract_reference.py`
Extracts a committable screen reference from a completed recon pass. Run this after a recon pass has produced screens worth carrying.

```bash
python -m engine.adapters.clash_royale.extract_reference \
    "experiments/android-bot/out/Clash Royale-YYYYMMDD-HHMMSS"
```

**Why this exists:** `out/` is gitignored, so extracted data goes into `known_screens.json` (committed) instead, preventing silent failures on different checkouts.

**Output:** `known_screens.json` with screen fingerprints, variants, and click-only transitions.

### `generate_nav_map_html.py`
Generates an interactive HTML navigation map from either a **recon pass** or **wiki directory**. Creates a browsable visualization of all screens and transitions that persists as a standalone HTML file.

**From a fresh recon pass:**
```bash
python -m engine.adapters.clash_royale.generate_nav_map_html \
    "experiments/android-bot/out/Clash Royale-YYYYMMDD-HHMMSS"
```

**From the existing wiki (anytime, no recon pass needed):**
```bash
python -m engine.adapters.clash_royale.generate_nav_map_html \
    "experiments/android-bot/wiki"
```

**What it shows:**
- Every screen in the source, laid out by BFS depth from the entry, labelled with its real name (or "unnamed")
- Navigation edges with action details (drag/click coordinates)
- Click a screen to open its screenshot and navigation details in the side panel
- Node colors derived from graph structure — hub, navigation node, dead end, unreachable — with a legend in the footer
- Scrollable surfaces shown as one node: the "↕ Scrollable surface" note plus, when the recon captured the frames, the stitched **whole-page panorama**; scroll self-loops are not drawn
- Near-duplicate screenshots flagged (a warning when the recon tool appears to have over-split one screen into several); needs Pillow, skipped if it's not installed

**Output:** `navigation_map.html` in the source directory. Open in any browser.

**Why two sources?** The recon pass contains raw fingerprints and is gitignored. The wiki is permanent and committed, so you can regenerate the visualization anytime without the original recon data.

## Module Structure

- `adapter.py` — Main adapter class integrating with the qes-exploration engine
- `actions.py` — Action space definition for Clash Royale
- `reference.py` — Screen reference data and matching
- `session.py` — Test session state management
- `preview.py` — Screen preview rendering
- `known_screens.json` — Extracted screen database (committed)
- `rubric.md` — Adapter rubric and quality standards

# Wiki Generator PoC

Proves the "wiki-ingest" mechanics described in the repo-root
[`AGENTS.md`](../../AGENTS.md) as real, testable code, instead of only an
interactive Claude Code slash command
([`.claude/commands/wiki-ingest.md`](../../.claude/commands/wiki-ingest.md)).
If this holds up, it graduates to `engine/wiki/` the way `token-purchase-poc`
became `engine/adapters/token_purchase` and `oracle-agent-poc` became
`engine/ontology` - proven here first, hardened there.

**This is a wiki about the product under test, not about this repo's own
testing machinery.** `raw/` holds only product-facing material a tester with
no prior knowledge would be handed: a spec, a ticket. Both files here are
transcribed verbatim from what's already known and validated elsewhere in
this project (`engine/adapters/token_purchase/adapter.py`'s
`API_SCHEMA_DOC`/`KNOWN_ACCOUNTS`, and `engine/bootstrap/jira_mock.py`'s
`PROJ-101`) - not rediscovered, not fabricated, and deliberately real files
on disk rather than string constants, so the generator has an actual
directory to point at.

## What it does

Two tool-forced LLM calls per run (same call→validate→retry shape every
experiment's `run_live.py` uses):

1. **Summarize** - one call per file under `--source`, producing a faithful
   `Source Summary` page.
2. **Synthesize** - one call across all the summaries just produced,
   producing a `Quality Concept` "product model" page - the point where
   combining sources tells you something neither told you alone.

Both calls return structured tool output; the actual markdown+frontmatter is
rendered deterministically in Python from that structure (same
"structured-call, deterministic-render" split as `engine/report.py`), not
generated as free-text markdown by the model.

## Running it

```
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
python generate.py
```

Defaults: `--source raw --dest results/wiki --product` (inferred from
`results`'s parent dir name, i.e. `wiki-generator-poc` unless overridden). To
point it at a different source/destination pair entirely:

```
python generate.py --source /path/to/raw/material --dest /path/to/wiki --product my-product
```

If `node` and this repo's `.wiki-source/scripts/rebuild-index.mjs` are
reachable, the run also regenerates `<dest>/index.md`; otherwise that step is
skipped with a warning, and the summary/concept pages are still written and
usable.

## Writing a wiki about a game

`generate_game_wiki.py` points the same mechanics at
[`game-ontology`](../game-ontology/)'s output - the map one exploration session
built of a real game - and writes a wiki about *the game*.

```
py generate_game_wiki.py --pass-dir "../game-ontology/out/<run>/pass6" --dry-run
py generate_game_wiki.py --pass-dir "../game-ontology/out/<run>/pass6"
py render_html.py --wiki results/game-wiki/wiki --out results/game-wiki/site
```

Pass `--out`. Its default is `results/site`, which is `sample-wiki`'s committed
render.

`--dry-run` prints exactly what each call would be given and writes nothing, so
what the model is about to be told can be read before anything is spent.

Point it at the **last** pass of a sweep. Each pass carries forward everything
the ones before it found, so `pass6` of a six-pass sweep is the whole map while
`pass1` is only what was known early on.

The output is not committed (see `.gitignore` for why), so a fresh clone re-runs
the generator. A run rewrites the pages it owns and leaves `log/` alone, so
re-running is safe: it will not leave the last run's pages beside this run's,
where six pages about one screen read as six screens.

The whole difference from `generate.py` is **what counts as one source**. Not a
file: a *place in the game*. Pointing `--source` at a pass directory would not
work at all - the first `.png` would raise `UnicodeDecodeError` on
`read_text` - and even if it did, one file per page would make 271 pages, one of
them titled `sc02-click-0-438-0-500-pressed`. `ontology_source.py` regroups the
map into a source per place instead, which is what the map already is
underneath.

Three passes, 8 calls on the Tile Tale map:

1. One per place → `wiki/entities/<place>.md`, an Entity page with
   `entity_kind: screen`. Entity is the right type because a place is exactly
   what AGENTS.md describes: a concrete thing the rest of the wiki refers to
   repeatedly.
2. One over the navigation graph → one `wiki/concepts/<rule>.md` per rule. A
   rule ("Escape backs out", "nothing observed ever returned from settings")
   only exists *across* places, so no per-place pass can find one.
3. One over the results of both → `wiki/overview.md`.

### Two things it decides, and why

**The harness gets no voice.** Cell counts, settle times, match thresholds,
screen ids and coordinates never reach a page - they are facts about how the
game was looked at, not about the game. `ontology_source.py` is where that line
is held, and `selftest_game_wiki.py` fails the build if any of that vocabulary
turns up in a page body. This is also why the map's actions are renamed on the
way through: the map says `click:0.438,0.700`, a page says "clicking SETTINGS",
and resolving the one into the other (nearest control, within the median spacing
of the controls on that screen) is what turns a click-by-click log into a
description of a game.

Seven of Tile Tale's safety-refusal reasons are dropped for this - they explain
themselves in coordinates ("at approximately y=0.90 and leftward x..."), so they
say nothing to a reader of the wiki. The count is printed rather than swallowed:
each one is a known unknown the wiki can no longer mention.

**Six screens named "settings menu" are written as one place.** The harness
identifies a screen by its pixels, so turning dark mode on makes the settings
screen a *new* screen to it. Their controls say so: the same seven rows in the
same order, differing in the values they hold - `MUSIC: OFF` against
`MUSIC: 5%`, `SCREEN: FULLSCREEN` against `SCREEN: WINDOWED`. So the grouping
rule is that evidence and not a guess: **the same name, and a control the two
screens can be shown to have in common.** Two screens that share a name over
nothing in common stay apart.

One shared control rather than an identical set, which is what an earlier
version asked for. It turned out that no two of the six visits produced matching
control lists, because each visit is described from scratch by a vision call:
one row came back as `Music volume setting`, `Music menu item`, `MUSIC: OFF` and
`Music: OFF menu item`, and some visits noticed the decorative banner while
others did not. Demanding an exact match therefore let the *describer's*
inconsistency decide how many screens the game has, and produced six settings
pages. Normalising the wording away (`ROLE_WORDS` in `ontology_source.py` -
generic interface vocabulary, not this game's) and then asking for one shared
control asks for the least evidence that is still evidence. That direction is
deliberate: over-merging shows up on the page as a place with contradictory
controls, which a reader catches, while under-merging quietly produces several
confident pages about one screen, which reads as a larger game.

The same normalisation decides what the page *calls* a control, so one act is
described once. Without it the same click read as "clicking SCREEN: FULLSCREEN",
"clicking Screen mode setting" and "clicking Screen: Fullscreen menu item".
Values get the same treatment: `FULLSCREEN` and `Fullscreen` are one state, not
two, and reporting two would report the wiki's own inconsistency as behaviour of
the game.

Leaving the screens split would also render a settings change as travel between
screens - "clicking BACK opens the settings menu". Grouped, the differing values
become what they are: the states this one screen was seen in, which is a fact
about the game no single screenshot contains.

Elements the describer gave no position to are dropped from what's on a screen.
They are notes about the keyboard (`Menu focus - key:down`, `key:up (global)`),
present on some visits and not others, and a player looking at the screen sees no
such object. What they say about the keys is not lost - it arrives through the
observed transitions instead, as what pressing the key actually did.

### Reading it as HTML

```
py render_html.py --wiki results/game-wiki/wiki --out results/game-wiki/site
```

`render_html.py` was already here, taking any OKF wiki directory; the game wiki
is just another one to point it at. No model and no network involved - the
markdown bundle stays the source of truth and this only presents it, so it can be
re-run any time without regenerating a page. One HTML file per markdown file at
the same relative path, so anything wrong with the wiki's shape stays visible
instead of being smoothed over by the renderer.

What pointing it at a *game* wiki needed adding, and why:

- **The screenshots are on the page.** The wiki was written from them and a
  reader could not see any of them. A screenshot arrives as a `sources:` entry
  rather than an inline `![](...)`, because the generator knows which shot a page
  was written from and the model writing the prose does not. So an image that is
  only cited is now shown as well - unless the body already shows that same file
  inline, in which case showing it twice would be worse than not showing it.
- **The citations open.** `sources[].resource` points into game-ontology's
  gitignored `out/`, so on any other machine every citation is a dead path. Each
  cited file is copied into `assets/` and its list entry links to the copy, so
  the site travels with its own evidence.
- **A cited path is not written relative to the page.** It is written relative to
  a root - the repo root for the game wiki, whose evidence lives elsewhere in the
  repo, and the wiki's own directory for `sample-wiki`, which carries its raw
  material inside it. All three bases are tried, and the file that resolves is the
  one both the figure and the inline-duplicate check use, so the same image
  reached by two different spellings is recognised as one image.
- **It says what has not been checked.** No page carries a `verified:` field; in
  markdown that is an absence, and an absence is easy to read past. Here it is a
  badge on every page.

Unresolved images are marked in place rather than failing the run - the site
still builds and says which image is missing.

### What it does not do yet

- **Screenshots are shown, but not read.** The calls are text-only, so the model
  writes about each place without seeing it. Not blind, though: every screen
  name, purpose and control description in the map was already bought with a
  vision call during the exploration, so the pages inherit real observation.
  Adding image blocks to the place call is the natural next step.
- **One screenshot per place, even where the page describes several states.**
  The settings page says the screen was seen with `MUSIC: OFF` and with
  `MUSIC: 5%`, but cites one of the six shots, so the evidence for the other
  states is not on the page. The reader picks a representative image per place;
  citing every variant is the fix, and it needs a regeneration to write the new
  frontmatter.
- **The site directory is not cleared before rendering.** Pages the wiki no
  longer has stay behind as orphan HTML - reachable by URL, absent from the
  index. Deleting `--out` first is the workaround; the markdown side solved the
  same problem by owning what it deletes.
- **Three descriptions of the settings background survive as three controls.**
  Wording normalisation merges the rows and the banner; `Background /
  non-interactive area` and `Settings menu background / surface` share no word
  once the role words are gone, so they stay apart and the model is left to group
  them in prose.
- **Nothing is verified.** No page carries a `verified:` field, because nobody
  has checked any of it against the game, and per AGENTS.md the absence of that
  field is what says so. The map holds observations too thin to trust - a single
  click on `SCREEN` inside Settings appearing to open a screen nobody could
  identify - and the wiki reports them as seen once rather than silently
  repairing or dropping them.

### Checking it without spending anything

```
py selftest_game_wiki.py --pass-dir "../game-ontology/out/<run>/pass6"
py selftest_game_wiki.py --pass-dir <same> --dest results/game-wiki/wiki --check-only
```

The first stubs the model's prose and exercises everything else - the regrouping,
the phrasing, the rendering, the slugs, the citations, the index rebuild. It
asserts that every place got exactly one page and no two share a filename, that
no harness vocabulary reaches a page, that every cited path exists on disk, and
that no page claims to be verified.

The second runs only the page checks, over a real run's output, where the prose
is the model's and a leak is likeliest. The stub run can only catch leaks from
the reader and the renderer.

Titles and one-line descriptions are checked along with the body, and they matter
more: they are what the derived index and the overview quote, so a leak there is
repeated on pages that never made the claim. Checking only bodies let a rule
page's description through reading "the most reliably observed route into the
settings menu, having been seen three times" - a measurement of how hard the
explorer looked, printed as though it were a fact about the game.

## Scope rule this inherits

Same as the repo-root `AGENTS.md`: in scope = specs, tickets, screenshots,
design docs, user-facing instructions - what a tester would actually be
handed. Out of scope = this repo's own engine/adapter code, oracle/heuristic
config, and past test-run results. This PoC doesn't classify files itself -
the caller is trusted to only point `--source` at a directory that's already
in-scope raw material (the interactive `/wiki-ingest` command does that
classification; this script assumes it already happened).

A game-ontology map sits close to that line, since it is literally something a
test run produced. `generate_game_wiki.py` treats it as **in scope**, on the
grounds that what the exploration produced is a model of the product discovered
by testing it, not a record of what passed - there are no verdicts in it, only
observations of the game. That reading only holds if the harness's own voice is
stripped out, which is why it is stripped out rather than summarized: a page
that reported cell counts and settle times would be a page about the test run,
and would belong out of scope.

## What's not built here

- Recursive source directories (one flat level of files only).
- Entity pages from *text* sources - `generate.py` still writes only Source
  Summary and one Quality Concept page. `generate_game_wiki.py` does write
  Entity pages, one per place in the game.
- The in-scope/out-of-scope file classification `/wiki-ingest` does - see
  above.
- Non-text raw sources. Neither entry point sends an image to the model:
  `generate.py`'s `raw/` is text-only and would crash on a `.png`, and
  `generate_game_wiki.py` cites screenshots without reading them (see above).
- HTML for `generate.py`'s own wiki. `render_html.py` takes any wiki directory of
  OKF pages, so `--wiki results/wiki --out results/site` works once `generate.py`
  has been run, but the only sites rendered and looked at are the game wiki's and
  `sample-wiki`'s (committed at `results/site` as a fixture, so a change to the
  renderer shows up as a diff).

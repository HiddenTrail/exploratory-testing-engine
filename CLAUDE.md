# CLAUDE.md: how coding agents work in this repo

This file is for any coding agent (Claude Code, Copilot, Codex and so on) that
changes code here. It covers **how to work**. For **what the repo is**, read
[README.md](README.md) first, then the README of the area you're touching.

> [AGENTS.md](AGENTS.md) is **not** a general coding guide. It is the schema for
> the product wiki under `wiki/`. Follow it when you create or edit wiki pages,
> and ignore it otherwise.

## The repo in one paragraph

This is an LLM-based **disconfirmation engine** for exploratory testing. A Driver
runs real tests against a live system under test (SUT) and forms one claim about
how it behaves. Then a separate Skeptic tries to knock that claim down.
`engine/` is the product: the checkpoint loop, one adapter per SUT, the pipeline
that drafts new adapters, and the ontology layer that prioritizes test ideas.
`clash-royale-kit/` packages the game-client exploration. `.experiments/` is
mostly an archive of the prototypes that `engine/` grew out of.

## Backlog and workflow

1. **The backlog is GitHub Issues** on `HiddenTrail/exploratory-testing-engine`.
   Check `gh issue list` before you start. Open an issue for new work, and for
   anything you notice but aren't fixing right now. A TODO comment nobody reads
   is not a backlog.
2. **Every issue gets its own branch.** Before you change anything for an
   issue, create a branch for it from an up-to-date `master`. Start the name
   with the issue number, then a few words in kebab-case, for example
   `39-oracle-claims-from-domain`. Keep one issue per branch. If you find
   something else along the way, open a new issue for it and don't fold it into
   the current branch. Never commit straight to `master`.
3. **Commit and push only when the user asks.** Opening a PR makes the work
   public, so check first.
4. **Every change reaches `master` through a PR**, and CI
   ([engine-tests.yml](.github/workflows/engine-tests.yml)) has to pass. PRs are
   squash-merged, so the PR title becomes the commit subject. Put `Closes #N` in
   the PR body when it fixes an issue.
5. **Read your whole diff before you open a PR.** Go through `git diff master...`
   from start to finish, the way you'd review a colleague's work. Look for
   leftover debug code, dead branches, naming that doesn't match, and clumsy
   logic. Green tests don't replace reading the diff, and reading the diff
   doesn't replace tests. Do both.

### Commit messages

Write the subject as a plain instruction that says what behaviour changes, not
which file you touched. Two from the history: *"Stop a health check from closing
the client it is checking"* and *"Retry the 529 that was propagating on the
first attempt"*. In the body, explain **why**: what was wrong, how you found out,
and how you checked the fix ("Ran live on Bedrock: both scenarios matched their
predictions.").

## Writing style for everything you write

This covers docs, READMEs, comments, commit messages, PR descriptions, issues
and wiki pages.

- **Write the way a person talks.** Imagine explaining it to a colleague at the
  next desk. If you wouldn't say a sentence out loud, rewrite it.
- **Use short, plain sentences.** One idea per sentence. Use the ordinary word:
  "use", not "leverage"; "check", not "validate the integrity of"; "fix", not
  "remediate".
- **Say the concrete thing.** Name the file, the command, the number, what
  actually happened. "The retry list missed the 529 error, so the first
  overload crashed the run" beats "improved error-handling robustness".
- **Skip AI-flavoured filler.** No "It's worth noting that", "This ensures a
  seamless", "robust", "comprehensive", "delve", "key insight", "In summary".
  Don't write "Not X, but Y" setups or tidy groups of three for the sake of
  rhythm. Don't pile adjectives on or promise more than the code does.
- **Don't use long dashes.** Never use the em dash (—) or en dash (–) in text.
  Use a full stop, a comma, a colon or brackets instead. Regular hyphens in
  words like `kebab-case` or `read-only` are fine.
- **Keep it short.** Say it once, where it belongs. Only use a bullet list when
  the items really are a list.

## Architecture rules (don't break these)

- **Imports go one way.** `engine/*` never imports from `engine/adapters/*`.
  Adapters import from `engine`, never the other way round. The one exception is
  `engine/adapters/registry.py`, which loads adapters lazily through
  `importlib`. `engine/bootstrap/` also depends only on `engine/`, never on a
  specific adapter.
- **`engine/tools.py` is shared.** The hypothesis, Skeptic and bug-report
  schemas are the same for every SUT, and adapters can't override them.
  Anything SUT-specific goes in the adapter.
- **The engine only reads adapter results through `engine/outcome.py`.** Generic
  code must never parse an adapter's prose.
- **A person registers adapters, not the code.** The bootstrap pipeline prints
  the line to add to `registry.py`. Never register or run a generated adapter
  automatically.
- **`validate_adapter()`** in `engine/adapter.py` checks up front that an adapter
  has every field it needs. If you add a required field, keep that check
  complete.
- **The Oracle and the Driver will become separate services.** That's decided;
  only the timing is open. Don't tie them closer together. Keep what passes
  between them a clean data format that could become an API later.

## `.experiments/`: an archive, with two live exceptions

Treat `.experiments/*` as history. Don't refactor it and don't copy fixes back
into it. **The exceptions are `.experiments/game-ontology/` and
`.experiments/android-bot/`.** `engine/adapters/clash_royale/session.py` imports
them at run time, so renaming or moving something in them can break the engine
without CI noticing. Their tests only run on Windows and CI doesn't run them, so
run them yourself (see below) before you merge a change to them.

New prototypes go in their own `.experiments/<name>/` folder with a README and a
`requirements.txt`. When code moves into `engine/`, port it and harden it. Never
import it from `.experiments/`.

## Safety: the game harness drives a real account

`.experiments/android-bot/`, `.experiments/game-ontology/`,
`engine/adapters/clash_royale/` and `clash-royale-kit/` send real taps and drags
to a real game client on someone's real account. Two things have already gone
wrong: input landed in the wrong window (someone's editor), and the game got
closed with no way to reopen it.

- Before you change any of these, read the safety parts of their READMEs,
  `adapters/clash_royale/actions.py`, and the "Things that bit" section of the
  game-ontology README.
- Never weaken a safety layer, a denylist, a window-identity check or the
  `--allow-battle` gate just to make something work. If a guard is in your way,
  stop and ask.
- In `clash-royale-kit/`, keep Win32 imports inside functions so its tests keep
  running on Linux CI.
- `known_screens.json` holds measurements, not settings. Don't edit it by hand.

## Testing

```
pip install -r engine/requirements.txt
python -m pytest engine/tests            # runs in CI
python -m pytest clash-royale-kit        # runs in CI
python -m pytest .experiments/game-ontology .experiments/android-bot   # Windows only, run by hand
```

- **Tests never call a real LLM** and never need an API key. Stub the client.
  Tests must give the same result every time.
- New behaviour gets a test. A bug fix gets a test that fails without the fix.
- CI also runs `python -m compileall -q engine`.
- Tests only prove what they check. If your change affects live behaviour (a
  real SUT, a real browser, the real game client), try it live when you can and
  say what you ran. If you couldn't, say that too.

## Scraping and mapping websites: use Spoor

When a task needs a website scraped, crawled or mapped, use **Spoor**
(`ht-spoor`). It's a separate project, checked out next to this repo in
`../ht-spoor`. Only use this repo's own crawlers (`.experiments/web-scraper-poc/`
on the `scraper` branch, and `.experiments/web-recon/`) when the user asks for
them by name.

- Spoor has its own virtualenv in `../ht-spoor/.venv`. Run its CLI from there
  as a separate process, and don't install it into this repo's environment.
  To set it up on a new machine:
  ```
  py -3.13 -m venv ../ht-spoor/.venv
  ../ht-spoor/.venv/Scripts/python -m pip install -e "../ht-spoor[serve]"
  ../ht-spoor/.venv/Scripts/python -m playwright install chromium
  ```
- Map a site: `../ht-spoor/.venv/Scripts/spoor explore <url> --wiki <dir>`.
  Always cap the run (`--max-depth`, `--max-states`, `--max-seconds`).
  `spoor run config.yaml -o out.json` extracts data with a config. The
  [Spoor README](../ht-spoor/README.md) has the rest.
- **Local test targets** are in `test-targets/`: Juice Shop (port 3000), Sauce
  Demo (3001) and PrestaShop (8080). Start them with
  `docker compose -f test-targets/docker-compose.yml up -d`. Spoor has the same
  set in its own `fixtures/`. They use the same ports, so run only one of them.
- Only use `--sandbox` against those local targets or another throwaway system
  you control. Without it, Spoor skips destructive actions like buy, delete
  and log out. Keep it that way.
- Spoor writes a `.spoor-cache/` in the folder you run it from. That cache holds
  raw captures with secrets left in, so it is gitignored. Never commit it.
- If Spoor can't do something a task needs, don't patch around it here. Tell
  the user, and open an issue in Spoor's repo if they agree. Spoor has its own
  rules (see its `CLAUDE.md`); the main one is that it never adds code for
  one specific site.

## Dependencies, config and secrets

- **When you install a package, add it to the right manifest in the same
  change**: `engine/requirements.txt`, the experiment's `requirements.txt`, or
  `package.json`. Give it a sensible minimum version. If the version or an
  optional dependency needs explaining, add a comment the way
  `engine/requirements.txt` does.
- Secrets go in `.env` or `.claude/settings.local.json`, and git ignores both.
  Only `.env.example` gets committed. Never put keys in code,
  `.claude/settings.json`, tests or commit messages.
- Create the LLM client with `engine.client.build_client()` and
  `default_model()`. They handle both the direct API and Bedrock
  (`ENGINE_USE_BEDROCK=1`). Don't call `Anthropic(...)` directly anywhere else.
  Bedrock model IDs aren't the ones `list-inference-profiles` shows; see
  [engine/README.md](engine/README.md).

## Don't commit generated output

`runs/`, screenshots, recon `out/` folders, rendered wiki HTML,
`.playwright-mcp/` and caches can all be regenerated, and git ignores most of
them. Only commit them when the change is meant to add a curated example, like
`docs/examples/bootstrap_demo/`. Check `git status` for stray files before
every commit.

## Code style

- Python 3.13 with 4-space indents. `.editorconfig` sets UTF-8, LF line endings,
  a final newline, and 2-space indents for everything that isn't Python.
- Match the code around you: its naming, its habits and how much it comments.
- Comments explain **why**: a constraint, something that broke before, a
  trade-off made on purpose. This codebase writes accepted limitations down
  where they live (like the rounding caveat in `engine/tools.py`). Keep those
  comments true when you change nearby code, and don't quietly "fix" a
  limitation someone chose to accept.
- Be honest in the code too. A result that wasn't confirmed is `inconclusive`,
  never `corroborated`. Don't hide uncertainty.

## Standing practices

- **Heuristics catalog:** whenever you come up with or spot a new testing
  heuristic, add it to `.experiments/oracle-agent-poc/heuristics/catalog.json`
  using the existing template. Mark it `status: "cataloged"` until something
  actually uses it.
- **Keep the docs true.** If your change makes the README, an area README or
  `docs/ontology-todo.md` wrong (roadmap checkmarks included), fix them in the
  same PR.
- **The product wiki (`wiki/`)** describes the product being tested, not this
  engine. Follow [AGENTS.md](AGENTS.md). `wiki/index.md` is generated, so rebuild
  it with `node .wiki-source/scripts/rebuild-index.mjs --dir .` instead of
  editing it.

## Windows notes

- The main shell is PowerShell 5.1, which has no `&&`. Use
  `; if ($?) { ... }`. Git Bash is also available.
- `> nul` in the wrong shell creates a real file called `nul` that git can't
  delete. Use `$null` in PowerShell and `/dev/null` in bash.
- Warnings like `LF will be replaced by CRLF` are expected and harmless.
  `.editorconfig` keeps the files you write on LF.

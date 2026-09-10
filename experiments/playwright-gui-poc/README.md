# Playwright-MCP GUI PoC

Validating a genuinely different SUT shape for the Driver+Skeptic
disconfirmation engine: a browser GUI, driven via Playwright MCP tools,
instead of a REST API driven via plain HTTP. Short version of the reasoning:
the existing checkpoint loop's "propose a batch of tests, execute them
mechanically, then reason about results" shape works because an HTTP
request is fully specified in advance and free to execute. A browser action
isn't - what you can click next depends on what actually rendered after the
last click - so "executing" a GUI test means an LLM has to perceive-decide-
act in a loop, not fire a pre-built request. This PoC exists to prove that
mechanism works at all before deciding whether/how to harden it into
`engine/`.

**Phase 1** built just the mock GUI itself - no Driver, no Playwright MCP
wiring. The app's own logic is deliberately trivial (there's no interesting
backend logic to bug-hunt) - the point was giving a future
Playwright-MCP-driven agent something real to navigate, click, and observe
a result from.

**Phase 2 (this increment)** wires up that Driver - `run_live.py` proposes
2 test scenarios from a real page snapshot, then actually carries each one
out in a real browser via Playwright MCP tools, and reports what it found.
**Deliberately excludes hypothesis formation and the Skeptic** - both
already work fine elsewhere in this project with different evidence shapes,
so they weren't at risk; the one thing genuinely worth proving was whether
an LLM can meaningfully perceive-decide-act its way through a browser via
MCP tools at all. It can: verified live, both scenarios resolved themselves
correctly in 5 turns each (well under the 10-turn safety cap), correctly
observed the actual response text, and matched it against their own
predictions - see `results/output.json` after running it.

## The app

One page, one question: "Is this a test?", two buttons ("Yes"/"No"), one
response line. Clicking a button calls the backend and renders whatever
text comes back - `"This is a test."` or `"This isn't a test."`.

- `sut.py` - a minimal FastAPI backend, one endpoint (`POST /answer`).
- `frontend/` - a bare Vite + vanilla JS scaffold (no framework - two
  buttons and a text response don't need one). `frontend/src/main.js`
  calls the backend directly via `fetch()`.

## Running it

```
# terminal 1 - backend
pip install -r requirements.txt
uvicorn sut:app --port 8010

# terminal 2 - frontend
cd frontend
npm install
npm run dev

# terminal 3 - the Driver
pip install -r requirements.txt
python run_live.py
```

The Driver authenticates through `engine/client.py`, the same as the rest of the repo:
by default it uses **Amazon Bedrock**, configured in the **repo-root `.env`**
(`ENGINE_USE_BEDROCK=1`, `AWS_REGION`, `AWS_PROFILE`; `aws sso login` before a run) -
`run_live.py` loads that file itself and picks the right model for the provider
(`anthropic.claude-sonnet-5` on Bedrock). To use the direct Anthropic API instead, leave
`ENGINE_USE_BEDROCK` unset and put a funded `ANTHROPIC_API_KEY` in this directory's `.env`
(see `.env.example`).

`run_live.py` spawns `npx @playwright/mcp@latest` itself (Node/npx must be
on PATH - on Windows this means the `.cmd` shim is used explicitly, since
bare `npx` isn't directly spawnable as a subprocess there) - no separate
terminal needed for it. Writes `results/output.json` with both scenarios'
predicted/observed outcomes.

You can also just open the printed Vite URL (default `http://localhost:5173`)
yourself and click either button by hand, to confirm the app works before
involving the Driver at all.

## Next steps (not built yet)

Hypothesis formation (synthesizing both scenario results into one claim)
and a Skeptic review of it - both already proven elsewhere in this project
with different evidence shapes, so they're lower-risk additions than
anything built so far. Also worth exploring: a test budget larger than 2
scenarios per run, and a mock GUI with an actual bug an API-only test
couldn't see (this one has no interesting logic to find).

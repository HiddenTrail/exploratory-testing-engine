# Playwright-MCP GUI PoC

Phase 1 of validating a genuinely different SUT shape for the Driver+Skeptic
disconfirmation engine: a browser GUI, driven via Playwright MCP tools,
instead of a REST API driven via plain HTTP. See the session discussion for
the full reasoning; short version: the existing checkpoint loop's "propose a
batch of tests, execute them mechanically, then reason about results" shape
works because an HTTP request is fully specified in advance and free to
execute. A browser action isn't - what you can click next depends on what
actually rendered after the last click - so "executing" a GUI test means an
LLM has to perceive-decide-act in a loop, not fire a pre-built request. This
PoC exists to prove that mechanism works at all before deciding whether/how
to harden it into `engine/`.

**This increment is just the mock GUI itself** - no Driver, no Playwright
MCP wiring yet. The point of the app is deliberately trivial (there's no
interesting backend logic to bug-hunt) - the point is giving a future
Playwright-MCP-driven agent something real to navigate, click, and observe
a result from.

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
```

Open the printed Vite URL (default `http://localhost:5173`), click either
button, confirm the response line updates correctly. Verified working via a
real browser session during this PoC's setup - both buttons render the
correct text with no console errors.

## Next steps (not built yet)

Wire up a Driver that uses Playwright MCP tools to navigate to the page,
read the question, click a button, and report a structured result -
proving the perceive-decide-act mechanism works, before adding hypothesis
formation or a Skeptic review on top.

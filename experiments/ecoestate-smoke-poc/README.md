# EcoEstate Smoke PoC

The smallest possible live check before going deeper on EcoEstate: does the Driver agent work at
all against this real, running server? One checkpoint, one test, no hypothesis-forming, no
Skeptic, no oracle library - none of the engine's full checkpoint-loop machinery.

Targets `GET /api/notes/:postalCode` - read-only, local (in-memory, no external API dependency),
and directly relevant to the notes CRUD target chosen for deeper testing next.

Owns the EcoEstate server's lifecycle end to end - starts it (`npm run dev`), waits for
readiness, runs the one Claude-proposed test, then shuts it down. Finds the real PID bound to
the port (not the npm launcher's own PID) to shut down cleanly, since `npm run dev` spawns
`ts-node-dev` as a child process.

## Running it

```
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
python run_live.py
```

Starts and stops the EcoEstate server itself - nothing needs to be running first, and port 3001
must be free before you run it. Writes `results/output.json`.

## Result

Live-verified: Claude proposed a genuinely informative boundary test (a 4-digit postal code,
not a lazy happy-path call) to check whether the `^\d{5}$` validation is actually enforced,
predicted a 400 with an error body, and the real server matched exactly. Confirms the agent, the
tool-forced call, and the start/verify/shutdown lifecycle all work end to end before building the
full `notes` adapter.

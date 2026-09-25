# Token-Purchase Oracle Value

A measurement experiment: does the oracle library wired into the real
`engine/adapters/token_purchase` adapter change real Driver+Skeptic checkpoint-loop outcomes?
Unlike `pattern-detection-oracle-poc`, this drives the actual production pipeline
(`engine.runner.run()`) against the real adapter - not a hand-rolled reimplementation - since
the full checkpoint loop already exists for `token_purchase`.

`token_purchase`'s mock SUT has no known/seeded bug, so this can only measure proxy signals
(Skeptic satisfaction rate, hypothesis-theme coverage, bug yield) - not recall against a known
answer. See [REPORT.md](REPORT.md) for the findings.

## Running it

```
python run_comparison.py
```

Requires the repo root `.env` (`ANTHROPIC_API_KEY`) - no separate env file here, since this
imports `engine/` directly rather than being a self-contained experiment. Starts and restarts
the mock SUT itself between trials; nothing else needs to be running first. Writes 12 full run
directories plus `results/comparison_summary.json` under `results/` (gitignored).

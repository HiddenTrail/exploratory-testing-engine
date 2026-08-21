# Pattern-Detection Oracle PoC

A measurement experiment, not a feature: does injecting an oracle library into the Driver's
evidence change outcomes on `pattern-detection-poc`'s scenario - the one PoC in this project with
real, known `ground_truth` (withheld from every model call), making it possible to score for
actual correctness rather than just "did behavior change."

Deliberately does **not** reuse the 5 heuristics already chosen for `token_purchase` (a different
SUT) or its oracle library - a clean slate: `run_oracle_pass.py` judges all 22 "model"-type
entries in [the heuristics catalog](../oracle-agent-poc/heuristics/catalog.json) fresh, against a
new `spec/spec.md` describing only this scenario's API, letting each heuristic's own "does this
apply" judgment decide, not a hand-picked subset assumed to fit.

## Running it

```
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
python run_oracle_pass.py    # writes results/oracle_library.json
python run_comparison.py     # writes results/comparison.json (6 paired trials)
```

See [REPORT.md](REPORT.md) for the findings.

"""Measures whether the oracle library wired into engine/adapters/token_purchase
changes real Driver+Skeptic checkpoint-loop outcomes - the same paired-trial idea
as pattern-detection-oracle-poc, but against the real, live-SUT adapter via the
actual engine (not a hand-rolled single-shot script), since token_purchase's full
checkpoint loop already exists in engine/runner.py.

Unlike pattern-detection-oracle-poc, token_purchase's mock SUT has NO known/seeded
bug - "whether a real bug exists at all... is genuinely unknown" (sut.py's own
docstring). So this can only measure proxy signals (anomaly yield, hypothesis-theme
coverage, efficiency), not recall against ground truth. See REPORT.md for why that
distinction matters.

The mock SUT holds in-memory state (balances, transaction counter) that persists
across calls within one process - restarted fresh before every individual trial so
all 12 runs start from the same clean slate, not compounding state from prior trials.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from engine.adapters.token_purchase.adapter import ADAPTER, KNOWN_ACCOUNTS  # noqa: E402
from engine.config import RunConfig  # noqa: E402
from engine.runner import run as run_engine  # noqa: E402

N_TRIALS = 6
TESTS_PER_CHECKPOINT = 8
SUT_MODULE = "engine.adapters.token_purchase.sut:app"
SUT_PORT = 8000
DOCS_URL = f"http://127.0.0.1:{SUT_PORT}/docs"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(__file__).parent / "results"

WITHOUT_ORACLE_ADAPTER = replace(ADAPTER, onboarding_extra={"known_accounts": KNOWN_ACCOUNTS})
WITH_ORACLE_ADAPTER = ADAPTER  # already carries oracle_library, unchanged


def start_sut() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", SUT_MODULE, "--port", str(SUT_PORT)],
        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            httpx.get(DOCS_URL, timeout=1.0)
            return proc
        except httpx.TransportError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("SUT did not become ready in time")


def stop_sut(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_one(arm: str, trial: int) -> dict:
    adapter = WITH_ORACLE_ADAPTER if arm == "with_oracle" else WITHOUT_ORACLE_ADAPTER
    out_dir = RESULTS_DIR / f"trial_{trial}_{arm}"
    run_config = RunConfig.for_adapter(
        adapter, first_round_test_budget=TESTS_PER_CHECKPOINT, default_test_budget=TESTS_PER_CHECKPOINT, out_dir=out_dir,
    )

    sut = start_sut()
    try:
        output = run_engine(adapter, run_config)
    finally:
        stop_sut(sut)

    tests_run = len(output.get("casting_log", []))
    checkpoints_used = len(output.get("checkpoints", []))
    final_verdict = output["checkpoints"][-1]["skeptic_review"]["verdict"] if output.get("checkpoints") else None
    hypotheses = [t["linked_hypothesis"] for t in output.get("casting_log", []) if t.get("linked_hypothesis")]

    bugs_path = out_dir / "bugs.json"
    bugs = json.loads(bugs_path.read_text(encoding="utf-8")) if bugs_path.exists() else []

    return {
        "trial": trial, "arm": arm, "stopped_reason": output.get("stopped_reason"),
        "checkpoints_used": checkpoints_used, "tests_run": tests_run, "final_skeptic_verdict": final_verdict,
        "anomaly_found": output.get("anomaly_found", False), "bug_count": len(bugs),
        "bug_severities": [b.get("severity") for b in bugs], "bug_statuses": [b.get("status") for b in bugs],
        "linked_hypotheses": hypotheses,
    }


def main():
    summary = []
    for trial in range(1, N_TRIALS + 1):
        for arm in ("without_oracle", "with_oracle"):
            print(f"\n=== trial {trial}/{N_TRIALS} [{arm}] ===")
            result = run_one(arm, trial)
            print(f"  {result['checkpoints_used']} checkpoints, {result['tests_run']} tests, "
                  f"verdict={result['final_skeptic_verdict']}, anomaly_found={result['anomaly_found']}, "
                  f"bugs={result['bug_count']} {result['bug_severities']}")
            summary.append(result)

    out_path = RESULTS_DIR / "comparison_summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote summary of {len(summary)} runs to {out_path}")


if __name__ == "__main__":
    main()

"""Signal-trust audit (#143, #146): run web_gui's real act() many times against one target
and look for weak spots in signal handling. No model calls, so it's free; run it after
any change to how signals are captured or trusted, on more than one kind of site.

For each of N fresh sessions, every chosen (state, control) pair is acted R times.
Then, per pair, across all sessions and repeats where the state was reached:
- a trusted signal that shows up in some runs but not all is FLAKY: the weak spot
  this audit exists to find (it was trusted, but it isn't reproducible)
- screen_was that varies is flaky classification
- weak signals are listed with the likely reason (third-party, seen idle, unsettled)
Also: unsettled reads, unreached states, and whether each state's idle noise
baseline is the same from session to session.

    python -m trailhound.adapters.web_gui.signal_audit --ontology <web-recon ontology.json> \
        --url <base url> --name juice-shop [--sessions 4 --repeats 2 --max-pairs 15 --out audit.json]
"""
import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from trailhound.adapters.web_gui import reference as ref_mod
from trailhound.adapters.web_gui import session as live_session


def pick_pairs(ref, limit):
    """Round-robin across states, so a big state doesn't take the whole budget."""
    by_state = defaultdict(list)
    for state_id, control in sorted(ref.pairs()):
        by_state[state_id].append(control)
    picked = []
    while len(picked) < limit and any(by_state.values()):
        for state_id in sorted(by_state):
            if by_state[state_id] and len(picked) < limit:
                picked.append((state_id, by_state[state_id].pop(0)))
    return picked


def items(signals):
    out = set()
    for key, value in (signals or {}).items():
        if key.startswith("settled_") or key.endswith("_more"):
            continue
        for v in value:
            out.add(f"{key}: {v}")
    return out


def analyse(runs: list[dict], noise: dict, origin: str) -> dict:
    """The audit's findings from the recorded acts (pure, so it's tested without a browser)."""
    report = {}
    by_pair = defaultdict(list)
    for run in runs:
        by_pair[(run["state"], run["control"])].append(run)
    flaky_trusted, flaky_screen, weak_seen, unreached, demoted = [], [], Counter(), 0, 0
    unsettled = sum(1 for r in runs if r["signals"] and not (r["signals"]["settled_before"] and r["signals"]["settled_after"]))
    for (state_id, control), rs in sorted(by_pair.items()):
        reached = [r for r in rs if r["reached_target_state"]]
        unreached += len(rs) - len(reached)
        if not reached:
            continue
        # Flaky means a trusted signal that's simply missing from some runs. One that a
        # run moved to weak (an unsettled read, say) wasn't contradicted, only demoted.
        trusted = Counter(i for r in reached for i in items(r["signals"]))
        seen = Counter(i for r in reached for i in items(r["signals"]) | items(r["signals_weak"]))
        for item, n in trusted.items():
            if seen[item] < len(reached):
                flaky_trusted.append(f"{state_id} :: {control} | {item} | in {seen[item]} of {len(reached)}")
            elif n < len(reached):
                demoted += 1
        screens = Counter(r["screen_was"] for r in reached)
        if len(screens) > 1:
            flaky_screen.append(f"{state_id} :: {control} | {dict(screens)}")
        for r in reached:
            for item in items(r["signals_weak"]):
                url = item.split(" ", 2)[-1].split(" -> ")[0] if item.startswith("failed_requests") else ""
                why = ("weak by kind" if item.startswith("console_warnings")
                       else "not sent" if r["verdict"] != "sent"
                       else "unsettled" if not (r["signals"]["settled_before"] and r["signals"]["settled_after"])
                       else "third-party" if url and not live_session._own_request({"url": url}, origin)
                       else "seen idle")
                weak_seen[f"{why} | {item}"] += 1
    noise_unstable = {s: v for s, v in noise.items() if any(x != v[0] for x in v)}
    report.update({
        "unsettled_reads": unsettled, "unreached": unreached,
        "trusted_signal_items": sum(len(items(r["signals"])) for r in runs),
        "flaky_trusted": flaky_trusted, "demoted_to_weak_sometimes": demoted, "flaky_screen": flaky_screen,
        "weak": dict(weak_seen.most_common(15)), "noise_unstable": noise_unstable,
        "noise_example": {s: v[0] for s, v in list(noise.items())[:3]},
        "covered_by": dict(Counter(r["covered_by"] for r in runs if r["covered_by"])),
        "wall_per_act": round(sum(r["wall"] for r in runs) / max(len(runs), 1), 1),
    })
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ontology", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--max-pairs", type=int, default=15)
    ap.add_argument("--out", default=None)
    ap.add_argument("--session", default=None, help="a saved session file every test starts from (#154)")
    args = ap.parse_args()

    ref = ref_mod.Reference(json.loads(Path(args.ontology).read_text(encoding="utf-8")))
    pairs = pick_pairs(ref, args.max_pairs)
    runs, noise, errors = [], defaultdict(list), []
    t_start = time.time()
    for s in range(args.sessions):
        sess = live_session.Session(ref, args.url, False,
                                    live_session.load_session_file(args.session) if args.session else None)
        try:
            sess.baseline()
            for state_id, control in pairs:
                for r in range(args.repeats):
                    t = time.time()
                    try:
                        res = sess.act(state_id, control)
                    except Exception as ex:
                        errors.append(f"s{s} {state_id} {control}: {type(ex).__name__}: {str(ex)[:120]}")
                        continue
                    runs.append({"session": s, "repeat": r, "state": state_id, "control": control,
                                 "wall": round(time.time() - t, 1), **{k: res.get(k) for k in (
                                     "reached_target_state", "verdict", "screen_was", "same_appearance",
                                     "signals", "signals_weak", "covered_by", "click", "settle")}})
            for state_id, n in sess._noise.items():
                noise[state_id].append({k: sorted(v) for k, v in n.items()})
        finally:
            sess.close()
        print(f"session {s + 1}/{args.sessions} done, {len(runs)} acts, {time.time() - t_start:.0f}s", flush=True)

    origin = "{0.scheme}://{0.netloc}".format(urlsplit(args.url))
    report = {"target": args.name, "pairs": len(pairs), "acts": len(runs), "errors": errors,
              "minutes": round((time.time() - t_start) / 60, 1), **analyse(runs, noise, origin)}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        # The file also keeps every act's raw result, so a finding can be traced back.
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({**report, "runs": runs}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

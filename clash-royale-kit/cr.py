"""One command: check the machine, explore Clash Royale for N minutes, build a wiki from it.

    python clash-royale-kit/cr.py --doctor            # check, touch nothing, say what is wrong
    python clash-royale-kit/cr.py --minutes 10        # explore, then build the wiki
    python clash-royale-kit/cr.py --minutes 10 --synthesize   # and add three analysis pages

What this replaces
------------------
The wiki this produces used to be built by a person sitting with an agent, which worked and is
not something anybody else can run. Going back over what those interventions actually were, they
were not code bugs. They were the same handful of environmental problems every time - a stale
threshold, a client on the wrong screen, a window that was really an editor, a frozen guest -
each with a ten-second fix that nobody could apply because the symptom never named the cause.

So this file is a sequence, not a loop. Preflight turns each of those into a sentence. Recon is
the pass that already existed. The wiki build is arithmetic. The only model calls are the recon
pass's own vetting call, which is a safety layer, and the three optional synthesis pages. Nothing
here writes or edits code, and nothing decides to do a fourth thing.

The order, and why it is this order
-----------------------------------
Preflight before anything, because everything after it measures the wrong thing otherwise, and
because the checks it fails are the ones a person can fix in seconds. Recon as a **subprocess**
rather than an import: a pass that crashes the interpreter should cost the pass, not the wiki
build, and `run_recon.py` is a working program with its own argument surface that this has no
business reaching inside. Teardown before the wiki, because the client is somebody's real account
and leaving it on a random screen is a cost paid by the next person, not by this run. The wiki
last, because it is the only part that can be re-run from files on disk.

What it will not do
-------------------
It will not open the client - `Target.exe` is empty on purpose and opening the game is a person's
job. It will not pass `--allow-battle`, so no battle is fought, Training Camp included. It cannot
disable either safety layer; the coordinate denylist and the vetting call are both verified in
preflight and a run that has lost one refuses to start. And every observation it makes itself is
taken with `verify=False`, because a verified grab of a hidden window is a driving call that ends
in the client being closed.

Windows-only. `controller` calls `ctypes.WinDLL` at import time; the decision logic that CI runs
lives in `checks.py` and `wikibuild.py`, which import nothing of the kind.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "game-ontology"))
sys.path.insert(0, str(ROOT / "experiments" / "android-bot"))
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import wikibuild  # noqa: E402

RECON = ROOT / "experiments" / "android-bot" / "run_recon.py"
WIKI_SCRIPTS = ROOT / ".wiki-source" / "scripts"
GAME = "Clash Royale"

# One retry by default. A pass that dies twice is not having bad luck: the usual cause is the
# client having stopped rendering, which no amount of retrying fixes because relaunching it is a
# person's job here. `checks.restart_verdict` holds the reasoning and the messages.
MAX_RESTARTS = 1


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _version() -> str:
    """A build actor precise enough to blame, with no comma in it.

    No comma because the renderer's frontmatter unpacker splits `{ by: x, at: y }` on commas,
    so an actor containing one silently truncates the timestamp beside it.
    """
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:                                                     # noqa: BLE001
        sha = ""
    return f"process:cr-kit@{sha or 'unknown'}"


def recon(run_dir: Path, minutes: float, threshold: float, resume: Path | None) -> int:
    """Run one recon pass as a child process. Returns its exit code.

    A subprocess rather than an import, for two reasons that are both about blast radius. A pass
    that takes the interpreter down with it - a Win32 call into a dying window, a C-level fault
    in the capture path - would otherwise take the wiki build with it, and the wiki build is the
    thing the operator came for. And `run_recon.py` is a program with its own argument surface
    and its own defaults; reaching inside it to call `session.run()` directly would mean quietly
    owning every one of those defaults here.

    The derived threshold is passed on the command line rather than written into the calibration
    file. `run_recon.py --screen-match` exists for exactly this and says in its own help that a
    value given this way is "asked for on the command line, not measured" - which is the honest
    description of a per-session derivation, and keeps the file on disk as the record of what a
    calibration pass actually measured.
    """
    command = [sys.executable, str(RECON), "--game", GAME, "--minutes", f"{minutes}",
               "--out", str(run_dir), "--screen-match", f"{threshold}"]
    if resume is not None:
        command += ["--resume", str(resume)]
    print(f"\n$ {' '.join(command)}\n", flush=True)
    return subprocess.run(command, cwd=str(ROOT / "experiments" / "android-bot")).returncode


def explore(out: Path, minutes: float, threshold: float, limit: int) -> Path | None:
    """Recon, retried by resuming rather than restarting. Returns the run that has a map.

    Resumed, always. A fresh pass would spend the remaining budget re-exploring the screens the
    dead one already mapped, and recon supports `--resume` from an `ontology.json` precisely so
    it does not have to. A pass that died before writing one is reported as a failure instead of
    retried, because there is nothing to resume from and the client just killed a pass.
    """
    attempt, previous = 0, None
    while True:
        attempt += 1
        run_dir = out / f"recon-{attempt}"
        code = recon(run_dir, minutes, threshold, previous)
        has_map = (run_dir / "ontology.json").exists()
        if code == 0 and has_map:
            return run_dir
        print(f"\nthe recon pass exited {code}"
              + ("" if has_map else " without writing a map"), flush=True)
        # `attempt` is also the number of failures so far, which is what the limit counts.
        again, why = checks.restart_verdict(attempt, limit, has_map)
        print(f"  {why}", flush=True)
        if not again:
            return run_dir if has_map else None
        previous = run_dir


def teardown(game: str) -> str:
    """Put the client back on the main screen, using the adapter's own vetted recovery action.

    Worth doing and worth being explicit about, because it is the one place this sends input the
    operator did not ask for. `Recon exits wherever it finished` is a known trap in the bot's own
    README, and the cost lands on whoever runs next: `battle.py` photographs whatever is on
    screen at startup as its lobby reference, so a pass left on a profile screen makes the next
    run bind that as "the lobby" and invert its own navigation test while every log line still
    reads plausible.

    One recovery action, not a search. It is the tap the reference already carries as the way
    back, it goes through `controller.click` and so past the coordinate denylist like any other
    tap, and if it does not land the failure is reported rather than followed by improvisation -
    a run that guesses its way home is a run sending taps at a screen nobody has modelled.

    Everything is caught, including `Unsafe`, because this runs after the pass is over. The map
    is already on disk and the wiki is still to be built; a client that cannot be recovered is
    worth a loud sentence, not the loss of the run's output.
    """
    from attach import apply_calibration, attach                          # noqa: E402
    from engine.adapters.clash_royale.session import Session              # noqa: E402
    try:
        controller = attach(game, verbose=False)
        apply_calibration(controller, game)
        return f"teardown: back on {Session(controller=controller).recover()}"
    except Exception as error:                                            # noqa: BLE001
        return (f"teardown FAILED ({type(error).__name__}: {error}). The client is wherever the "
                f"pass left it - put it back on the main screen by hand before running anything "
                f"else against this account.")


def check_model() -> str:
    """Prove the model the pass depends on can actually be reached. Refuses if not.

    Refuses rather than warns, because the recon pass's model call is not a nicety: it is the
    second of the two safety layers. The coordinate denylist stops a tap by where it lands, and
    the vetting call stops one by what it *is* - a control the boxes do not cover but whose
    description reads irreversible. `run_recon.py` can be told `--no-model`, and this kit never
    tells it that, so a pass with no reachable model is a pass with one guard instead of two.

    Checked with a one-token call rather than by constructing the client, because construction
    proves almost nothing. `build_client` validates that a region and a profile are configured;
    it does not talk to anything. The failure this is really here for is an expired SSO token,
    which looks perfectly configured and fails on first use - i.e. five minutes into the pass,
    on the first screen worth vetting. A one-token call costs a fraction of a cent and moves
    that discovery to before anything has been touched.
    """
    from engine.client import build_client, default_model                 # noqa: E402
    model = default_model()
    try:
        client = build_client()
        client.messages.create(model=model, max_tokens=1,
                               messages=[{"role": "user", "content": "ok"}])
    except SystemExit as unconfigured:
        # A BaseException, so it would otherwise sail past an `except Exception` and take the
        # process down with a message that reads like a crash rather than like a refusal.
        raise checks.Refuse(
            f"{unconfigured}\n"
            f"  Nothing was tapped, and this is a configuration problem rather than a game "
            f"one.") from unconfigured
    except Exception as unreachable:                                      # noqa: BLE001
        raise checks.Refuse(
            f"the model {model!r} could not be reached: "
            f"{type(unreachable).__name__}: {unreachable}\n"
            f"  This is refused rather than warned about because that call is one of the two "
            f"safety layers - the denylist stops a tap by where it lands, the model stops one "
            f"by what it is. On Bedrock the usual cause is an expired SSO token, which looks "
            f"configured and fails on first use: run `aws sso login` and try again. Nothing was "
            f"tapped.") from unreachable
    return f"model: {model} answered a one-token call, so the vetting layer is live"


def render(workspace: Path) -> list[str]:
    """Rebuild the index and the HTML, or say why not. Never fatal.

    Both are node scripts that live in `.wiki-source/`, and node is not something this kit
    installs. The markdown bundle is the deliverable and it is already complete and readable in
    any editor by the time this runs, so a machine without node loses the browsable HTML and
    nothing else - which is worth saying out loud rather than failing over.
    """
    node = shutil.which("node")
    if node is None:
        # `--wiki-only` is what makes this recoverable without touching the game again.
        return ["node is not on PATH, so wiki/index.md was not rebuilt and no HTML was "
                "rendered. The markdown pages under wiki/ are complete and readable as they "
                "are; install Node.js and re-run with --wiki-only <run dir> to add the "
                "browsable copy."]
    notes = []
    for script, extra in (("rebuild-index.mjs", []),
                          ("render-html.mjs", ["--single", "wiki.html"])):
        result = subprocess.run([node, str(WIKI_SCRIPTS / script), "--dir", str(workspace)]
                                + extra, capture_output=True, text=True)
        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                notes.append(line.strip())
        if result.returncode != 0:
            notes.append(f"{script} exited {result.returncode}")
    return notes


def build_wiki(workspace: Path, run_dir: Path, note: str, synthesize_too: bool) -> None:
    """The deterministic bundle first, then optionally the three analysis pages, then HTML.

    This ordering is the whole reason synthesis can fail softly: by the time a model is asked
    anything, the wiki is complete and correct. The pages a model adds are commentary on it.
    """
    built = wikibuild.build(run_dir, workspace, generated_by=_version(), threshold_note=note)
    print(f"\nwrote {len(built.pages)} pages to {workspace / 'wiki'}", flush=True)
    facts = built.facts
    print(f"  {len(facts.screens)} screens, {facts.graph['distinct_edges']} routes, "
          f"{facts.reach['activated']} of {facts.reach['named']} named controls pressed, "
          f"{facts.refusals['blocked_total']} inputs declined", flush=True)
    if facts.frames["identical_crops_nonzero_count"]:
        print(f"  {len(facts.frames['identical_crops_nonzero_count'])} transitions report a "
              f"change between byte-identical crops - see concepts/frames-vs-counts.md",
              flush=True)

    if synthesize_too:
        import synthesize                                                 # noqa: E402
        try:
            run_rel = run_dir.resolve().relative_to(workspace.resolve()).as_posix()
        except ValueError:
            run_rel = run_dir.resolve().as_posix()
        print(f"\nasking a model for {len(synthesize.PAGES)} analysis pages", flush=True)
        result = synthesize.run(facts, workspace, run_rel, generated_by=_version(),
                                threshold_note=note)
        for path in result.pages:
            print(f"  wrote {path.relative_to(workspace)}", flush=True)
        for note_line in result.skipped:
            print(f"  SKIPPED {note_line}", flush=True)

    for line in render(workspace):
        print(f"  {line}", flush=True)


def main() -> int:
    from controller import readable_output, set_dpi_aware                 # noqa: E402
    # First, and in this order. `readable_output` because a cp1252 console raises
    # UnicodeEncodeError on the first non-ASCII character a report contains, killing a finished
    # pass at the print statement. `set_dpi_aware` before anything measures the window, because
    # a scaled rect makes every fractional coordinate resolve against geometry the game is not
    # using - and that failure does not error, it just lands taps somewhere else.
    readable_output()
    set_dpi_aware()

    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The client must already be open on the main screen. Opening it is a person's "
               "job: this cannot launch it, by design.")
    parser.add_argument("--minutes", type=float, default=5.0,
                        help="how long the exploration pass runs (default 5)")
    parser.add_argument("--doctor", action="store_true",
                        help="run the checks, touch nothing, and say what is wrong")
    parser.add_argument("--synthesize", action="store_true",
                        help="add three analysis pages written by a model from the run's own "
                             "measurements. Needs Bedrock or an API key; skipped with a note "
                             "if neither is configured")
    parser.add_argument("--out", default="",
                        help="workspace directory (default clash-royale-kit/out/<stamp>)")
    parser.add_argument("--wiki-only", default="",
                        help="skip the game entirely and rebuild the wiki from an existing run "
                             "directory. Useful after installing node, or after editing the "
                             "builder")
    parser.add_argument("--max-restarts", type=int, default=MAX_RESTARTS,
                        help=f"how many times a crashed pass may be resumed "
                             f"(default {MAX_RESTARTS})")
    parser.add_argument("--drift-samples", type=int, default=0,
                        help="one-second samples of the idle window used to derive this "
                             "session's screen-match threshold")
    parser.add_argument("--no-teardown", action="store_true",
                        help="leave the client wherever the pass finished instead of pressing "
                             "the vetted recovery action to return to the main screen")
    args = parser.parse_args()

    if args.wiki_only:
        run_dir = Path(args.wiki_only).resolve()
        workspace = run_dir.parent
        print(f"rebuilding the wiki from {run_dir} - the game is not touched")
        note = ""
        measured = workspace / "preflight.json"
        if measured.exists():
            note = json.loads(measured.read_text(encoding="utf-8")).get("wiki_note", "")
        build_wiki(workspace, run_dir, note, args.synthesize)
        return 0

    import preflight                                                      # noqa: E402
    samples = args.drift_samples or preflight.DRIFT_SAMPLES
    try:
        report = preflight.run(GAME, samples=samples)
    except checks.Refuse as refused:
        print(f"\nWILL NOT RUN: {refused}")
        return 2
    print()
    for line in report.lines:
        print(f"  {line}")

    # After the findings are printed, not before, so a credentials failure does not throw away
    # the six seconds of measurement that were already made and might be wanted anyway.
    try:
        print(f"  {check_model()}")
    except checks.Refuse as refused:
        print(f"\nWILL NOT RUN: {refused}")
        return 2

    if args.doctor:
        print("\nready. Nothing was tapped - re-run without --doctor to explore.")
        return 0

    workspace = Path(args.out).resolve() if args.out else HERE / "out" / stamp()
    workspace.mkdir(parents=True, exist_ok=True)
    payload = report.to_json()
    payload["wiki_note"] = report.wiki_note()
    (workspace / "preflight.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_dir = explore(workspace, args.minutes, report.threshold.value, args.max_restarts)
    if not args.no_teardown:
        print(f"\n{teardown(GAME)}", flush=True)
    if run_dir is None:
        print("\nno map was written, so there is nothing to build a wiki from. The preflight "
              "output above and the recon log are what to read; the usual cause is the client "
              "having stopped rendering, which only a relaunch fixes.")
        return 1

    build_wiki(workspace, run_dir, report.wiki_note(), args.synthesize)
    print(f"\ndone. {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

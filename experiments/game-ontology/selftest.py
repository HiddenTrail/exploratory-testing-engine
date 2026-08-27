"""Drive a session against a synthetic game, to check the close-ups without launching one.

    py selftest.py

Nothing here is a fact about a real game - `FakeGame` is a menu invented to have the
behaviours the imaging code reasons about, and it belongs to this file only. What it
checks is the part of `recon.py` that is hardest to check against a real game, because a
real game gives no second opinion about what its own buttons look like:

  1. that a close-up is taken at all, for every kind of action that can take one;
  2. that it is aimed at the cells that took part, not at a guess;
  3. that a before/after pair is two different pictures - the bug this exists to catch is
     a pair filmed across two occurrences, where the `before` is the state the previous
     occurrence already left behind and is therefore its own `after`;
  4. that a map with pictures in it round-trips through save and resume, keeping both the
     files and the aim, so a later pass films what an earlier one could not.

**Not a CI test, and cannot become one.** `controller.py` imports `probe.py`, which calls
`ctypes.WinDLL` at module scope, so importing `recon` needs Windows; the workflow in
`.github/workflows/` runs on ubuntu. This is a check to run by hand on the machine the
experiment runs on, before trusting a change to `Recon.take`, `_film_resting` or the crop
geometry. It takes about a second and a half and costs nothing: there is no model call in
it, because `fake_vetter` clears everything and records only what it was sent.

Read the output rather than an exit code. It prints what was filmed and where it was
aimed; a regression shows up as a slot that stopped being filled, a box that stopped
matching the cells that moved, or a pair whose two files have one checksum.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import describe  # noqa: E402
import recon  # noqa: E402
from probe import write_png  # noqa: E402  (importable because controller.py added its path)
from recon import Action, Recon  # noqa: E402

COLS, ROWS = 32, 18
CLIENT = (3840, 2160)

# Three buttons in a column, a logo that animates, a back button on a second screen.
BUTTONS = [((10, 19), (5, 6), "play"), ((10, 19), (8, 9), "settings"),
           ((10, 19), (11, 12), "quit")]
BACK = ((2, 6), (15, 16))


class FakeGame:
    """A menu whose buttons light under the cursor, keep a selection, and go somewhere.

    Every behaviour here is one the imaging code has to handle: a hover reaction that
    ends when the cursor leaves (so a resting picture exists and differs), a pressed
    state visible only while the button is down, a selection that survives navigation,
    movement with no input at all, and a click that changes screen."""

    def __init__(self) -> None:
        self.screen = "menu"
        self.selected = 0
        self.hovered: int | None = None
        self.pressed = False
        self.frame = 0

    def cell(self, col: int, row: int) -> tuple[int, int, int]:
        if self.screen == "settings":
            if BACK[0][0] <= col <= BACK[0][1] and BACK[1][0] <= row <= BACK[1][1]:
                return (90, 90, 90)
            return (60, 20, 20)
        if 1 <= col <= 5 and row <= 1:                  # the animating logo
            shade = 100 + 50 * (self.frame % 3)
            return (shade, shade // 2, 40)
        for index, ((c0, c1), (r0, r1), _) in enumerate(BUTTONS):
            if c0 <= col <= c1 and r0 <= row <= r1:
                if self.pressed and self.hovered == index:
                    return (220, 220, 220)
                if self.hovered == index:
                    return (140, 140, 140)
                if self.selected == index:
                    return (70, 120, 70)
                return (70, 70, 70)
        return (20, 20, 20)

    def hit(self, fx: float, fy: float) -> int | None:
        col, row = int(fx * COLS), int(fy * ROWS)
        if self.screen == "settings":
            return 99 if (BACK[0][0] <= col <= BACK[0][1]
                          and BACK[1][0] <= row <= BACK[1][1]) else None
        for index, ((c0, c1), (r0, r1), _) in enumerate(BUTTONS):
            if c0 <= col <= c1 and r0 <= row <= r1:
                return index
        return None

    def render(self, width: int, height: int, region) -> bytes:
        """BGRA of a sub-rectangle of the client, at whatever size is asked for."""
        self.frame += 1
        fx, fy, fw, fh = region
        out = bytearray()
        for y in range(height):
            for x in range(width):
                col = int((fx + fw * (x + 0.5) / width) * COLS)
                row = int((fy + fh * (y + 0.5) / height) * ROWS)
                b, g, r = self.cell(min(col, COLS - 1), min(row, ROWS - 1))
                out += bytes((b, g, r, 255))
        return bytes(out)


class FakeTarget:
    name = "fakegame"
    window_title = "Fake"
    screen_match = 0.94
    cell_delta = 10

    @staticmethod
    def forbids(fx: float, fy: float) -> str:
        return ""


class FakeController:
    """Everything `Recon` asks of a controller, and nothing else.

    Deliberately not a subclass: what this checks is that the session only reaches for
    the small surface it is supposed to, and inheriting would hide the day a new call
    into the real controller appears."""

    def __init__(self, game: FakeGame) -> None:
        self.game = game
        self.target = FakeTarget()
        self.notes: list[str] = []
        self.handovers = 0
        self.restarts = 0
        self.last_good_rect = (0, 0, *CLIENT)
        self.crops: list[tuple[tuple, bool]] = []

    def note(self, message: str) -> None:
        self.notes.append(message)

    def ensure_readable(self, allow_restart: bool = True) -> str:
        return "ok"

    def grab(self, cols: int, rows: int, region=(0.0, 0.0, 1.0, 1.0)) -> bytes:
        return self.game.render(cols, rows, region)

    def capture(self, region=(0.0, 0.0, 1.0, 1.0), longest: int = 1400):
        fw, fh = region[2] * CLIENT[0], region[3] * CLIENT[1]
        scale = min(1.0, longest / max(fw, fh))
        ow, oh = max(1, int(fw * scale)), max(1, int(fh * scale))
        # A tenth of the pixels the real thing would return, so a full run stays under
        # two seconds. The aim and the contents are what this checks, not the resolution.
        w, h = max(1, ow // 10), max(1, oh // 10)
        self.crops.append((tuple(round(v, 3) for v in region), self.game.pressed))
        return self.game.render(w, h, region), w, h

    @staticmethod
    def write_capture(path: Path, frame):
        pixels, width, height = frame
        path.parent.mkdir(parents=True, exist_ok=True)
        write_png(str(path), pixels, width, height)
        return width, height

    def save_png(self, path: Path, region=(0.0, 0.0, 1.0, 1.0), longest: int = 1400):
        return self.write_capture(path, self.capture(region, longest))

    def hover(self, fx: float, fy: float, settle: float = 0.0) -> None:
        self.game.hovered = self.game.hit(fx, fy)

    def click(self, fx: float, fy: float, button: str = "left",
              hover: float = 0.0, hold: float = 0.0, during=None) -> None:
        self.game.hovered = self.game.hit(fx, fy)
        self.game.pressed = True
        if during is not None:
            during()
        self.game.pressed = False
        hit = self.game.hit(fx, fy)
        if hit == 1:
            self.game.screen = "settings"
        elif hit == 99:
            self.game.screen = "menu"

    def press(self, key: str) -> None:
        if key == "down":
            self.game.selected = (self.game.selected + 1) % len(BUTTONS)
        elif key == "up":
            self.game.selected = (self.game.selected - 1) % len(BUTTONS)
        elif key == "enter" and self.game.selected == 1:
            self.game.screen = "settings"
        elif key == "esc":
            self.game.screen = "menu"

    def wait_stable(self, *a, **k) -> float:
        return 0.05

    def close(self) -> str:
        return "fake"


def fake_vetter(seen: list[dict]):
    """Clears everything, and records the labels it was sent.

    The labels are half the point: a picture the model is given under the wrong
    description is worse than no picture, so what arrives at the call is checked and not
    just what was written to disk."""
    def vet(image_path, screen, variant, candidates, crops=()):
        seen.append({"screen": screen.id, "variant": variant.id,
                     "crops": [c["label"] for c in crops]})
        return {"name": f"{screen.id} menu", "purpose": "a fake screen",
                "highlighted": "", "elements": [],
                "actions": {a.id: {"safe": True, "why": "fake"} for a in candidates}}
    return vet


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()[:8]


def main() -> None:
    # The measured settles are the run's whole cost and none of its substance. Cut here
    # rather than made configurable in `recon`, so no real pass can pick these up.
    recon.HOVER_SETTLE = 0.01
    recon.HOVER_GROWTH = 0.01
    recon.HOVER_REACTION = 0.05
    recon.ANIMATION_GAP = 0.01

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "out" / "selftest"
    controller = FakeController(FakeGame())
    seen: list[dict] = []
    session = Recon(controller, out, vetter=fake_vetter(seen))
    for _ in range(40):
        if session.step() == "exhausted":
            break
    data = session.to_json()
    session.save()
    recon.write_report(data, out)

    print(f"\n{len(controller.crops)} crops taken, {len(session.screens)} screens, "
          f"{len(session.transitions)} transitions")
    for screen in data["screens"]:
        print(f"\n{screen['id']}: {len(screen['animation'])} animation frames, "
              f"{len(screen['hover'].get('sticky_points') or [])} sticky points")
        print(f"  crop_boxes: {json.dumps(screen['hover']['crop_boxes'])[:200]}")

    print("\ntransitions with close-ups, and whether their pictures differ:")
    for t in data["transitions"]:
        if not t["crops"]:
            continue
        marks = {slot: digest(out / path) for slot, path in t["crops"].items()}
        verdict = ("all differ" if len(set(marks.values())) == len(marks)
                   else "SAME PICTURE FILED TWICE")
        print(f"  {t['id']} {t['action']['id']:<28} box={[round(v, 3) for v in t['crop_box']]} "
              f"{ {s: marks[s] for s in recon.CROP_SLOTS if s in marks} } {verdict}")

    print("\nwhat the vetter was sent:")
    for call in seen:
        print(f"  {call['screen']}/{call['variant']}: {call['crops']}")

    blocks = describe._crop_blocks(out, [t for t in data["transitions"]
                                         if t["from"] == data["screens"][0]["id"]])
    print(f"\nannotate would attach "
          f"{sum(1 for b in blocks if b['type'] == 'image')} close-ups for "
          f"{data['screens'][0]['id']}")

    # The mission path: a verdict bought for a point nobody swept, which has to arrive
    # with the picture it was bought with.
    screen, variant, _ = session.look()
    unmapped = Action("click", at=(0.9, 0.9))
    session.ask_about(screen, variant, [unmapped])
    print(f"ask_about verdict: {json.dumps(screen.vetting['actions'][unmapped.id])}")

    # A second pass inheriting the first must keep the pictures and the aim, or it refilms
    # what it cannot film honestly any more.
    second = Path(str(out) + "-resumed")
    again = Recon(FakeController(FakeGame()), second, vetter=fake_vetter([]))
    print("\n" + again.resume(json.loads((out / "ontology.json").read_text("utf-8")), out))
    kept = again.to_json()
    lost = [t["id"] for t in kept["transitions"]
            if t["crops"] and not all((second / p).exists() for p in t["crops"].values())]
    print(f"crops after resume: {sum(len(t['crops']) for t in kept['transitions'])} paths, "
          f"{len(lost)} missing files, "
          f"{sum(1 for t in kept['transitions'] if t['crop_box'])} aims restored")
    print(f"animation after resume: {[len(s['animation']) for s in kept['screens']]}")

    # Re-read the map, because `ask_about` above added both a verdict and the picture it
    # was bought with, and the orphan check is only worth anything against the final one.
    orphans = sorted({p.name for p in (out / "images").glob("*.png")}
                     - {Path(ref).name for ref in _referenced(session.to_json())})
    print(f"pictures on disk that the map does not reference: {orphans}")


def _referenced(data: dict) -> set[str]:
    """Every picture the map points at. An unreferenced file is a picture nobody can find."""
    refs: set[str] = set()
    for screen in data["screens"]:
        refs.update(screen["animation"])
        for variant in screen["variants"]:
            refs.add(variant["image"])
            refs.add(variant.get("differs_image") or "")
        for entry in (screen.get("click_verdicts") or {}).values():
            if isinstance(entry, dict) and entry.get("image"):
                refs.add(entry["image"])
    for transition in data["transitions"]:
        refs.update((transition.get("crops") or {}).values())
    return refs - {""}


if __name__ == "__main__":
    started = time.monotonic()
    main()
    print(f"\n{time.monotonic() - started:.1f}s")

"""Wait until the Clash Royale client is actually rendering again, then say so.

Written for the case in `clash-royale-client-freezes-silently`: the guest stops
rendering, every Win32 health check still reports a healthy window, and the only
signal that tells a live client from a dead one is whether the picture moves.

Two things this does that a single `--dry` cannot:

- **it re-attaches every cycle.** A relaunch is not guaranteed to come back on the
  same hwnd, so a handle captured before the relaunch may be stale or dead. Cheap
  enough to just resolve it again each time.
- **it takes the maximum of several samples instead of one.** The lobby animates on
  a cycle longer than a second, so a single one-second window on a *healthy* lobby
  reads zero movement about four times in five. Measured live: 5, 0, 0, 0, 0, 5.
  Concluding "dead" from one zero is a false-alarm generator; concluding "alive"
  from one non-zero is fine, because a stale frame cannot move at all.
- **it cannot touch the game.** Every grab is unverified and the whole cycle is inside
  the guard. On 2026-09-07 neither was true: a verified grab of a *hidden* window sent
  `ensure_readable` looking for a fix, and the fix was `_restart`, which closed the
  client this script had been asked to watch. A liveness check that can shut the thing
  it is checking reports on a state it created.

Exit 0 the moment it sees real movement, 1 on timeout.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import changed_cells, readable_output, set_dpi_aware  # noqa: E402
from recon import GRID_COLS, GRID_ROWS, fingerprint  # noqa: E402

from attach import apply_calibration, attach  # noqa: E402

# A lobby's slow water/flag cycle measured 4-5 cells of 576. Anything at or under
# that is indistinguishable from a stale frame plus capture noise, so the bar is set
# above it: this is "the picture is genuinely moving", not "something twitched".
ALIVE_CELLS = 12
GAME = "Clash Royale"


def sample(controller, seconds: int = 4) -> int:
    """The largest one-second movement over `seconds`, in cells.

    Every grab here is `verify=False`, which is the whole difference between watching a
    window and driving one. A verified grab that finds the game is not the foreground
    calls `ensure_readable`, and that is allowed to relaunch - which for this target
    means closing a client it cannot reopen. A liveness check that can shut the thing it
    is checking is not a liveness check, and on 2026-09-07 this one did exactly that to a
    hidden window.
    """
    prev = fingerprint(controller, verify=False)
    worst = 0
    for _ in range(seconds):
        time.sleep(1.0)
        current = fingerprint(controller, verify=False)
        worst = max(worst, changed_cells(prev, current, controller.target.cell_delta))
        prev = current
    return worst


def main() -> int:
    """Wait for the window to exist; report movement rather than gating on it.

    `--moving` restores the stricter gate, which is the right one when the question is
    "did a frozen client come back". It is the wrong one when the question is "is the
    game open yet": measured on this target a live, logged-in lobby sat at a steady
    1 cell of 576 for ninety seconds - below any sane movement bar - while genuinely
    rendering, which the *content* proved (a countdown appeared on the Battle button)
    and the cell count denied. So existence is the default gate and the movement number
    is printed as evidence for a person to weigh, not a verdict.
    """
    readable_output()
    set_dpi_aware()
    argv = [a for a in sys.argv[1:] if a != "--moving"]
    need_movement = "--moving" in sys.argv
    budget = float(argv[0]) if argv else 300.0
    deadline = time.monotonic() + budget
    cells = GRID_COLS * GRID_ROWS
    cycle = 0

    while time.monotonic() < deadline:
        cycle += 1
        # The sampling is inside the guard, not just the attach. Losing the window
        # part-way through four seconds of watching is this loop's *ordinary* case - the
        # game is being opened or closed while it looks - and it used to escape as a
        # traceback because only `attach` was wrapped.
        try:
            controller = attach(GAME, verbose=cycle == 1)
            apply_calibration(controller, GAME)
            moved = sample(controller)
        except Exception as error:                          # noqa: BLE001
            # Expected while the window is gone: closed, or not opened yet.
            print(f"[{cycle}] no readable Play Games window yet ({error})", flush=True)
            time.sleep(3.0)
            continue
        print(f"[{cycle}] hwnd {controller.hwnd} max movement {moved} of {cells}",
              flush=True)
        if not need_movement or moved >= ALIVE_CELLS:
            print(f"open: hwnd {controller.hwnd}, movement {moved} of {cells}")
            return 0

    print(f"gave up after {budget:.0f}s"
          + (" without seeing the picture move" if need_movement else " with no window"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

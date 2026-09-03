"""One live vetting call against a PNG already on disk, to prove the provider works.

Worth its own script because of how the failure looks from inside a pass. A vetting
call that fails does not stop the session: it logs the reason, leaves committing
actions locked on that screen, and carries on exploring with nothing it is allowed to
press. The measured version of that was a one-minute pass that mapped two screens,
took no clicks, and reported `Your credit balance is too low` on a line among twenty
others. So the provider is checked *before* a pass rather than discovered during one -
and checked through `make_vetter` itself, so what is exercised is the real path,
including the image block and the forced tool call, not a bare hello.

Costs one call on one image. Sends no input to the game and does not need it running.

Run:  python experiments/android-bot/check_vetter.py [image.png]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "game-ontology"))

from controller import readable_output  # noqa: E402
from recon import Action, Screen, Variant  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"


def newest_image() -> Path:
    """The most recent screen capture any pass wrote, or raise."""
    shots = sorted(OUT.glob("*/images/*.png"), key=lambda p: p.stat().st_mtime)
    if not shots:
        raise SystemExit(f"no captures under {OUT} to test with - pass one as an argument")
    return shots[-1]


def main() -> None:
    readable_output()
    image = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_image()

    import describe
    from engine.client import default_model, use_bedrock  # noqa: E402
    where = (f"Bedrock ({os.environ.get('AWS_REGION')}, profile "
             f"{os.environ.get('AWS_PROFILE')})" if use_bedrock() else "the Anthropic API")
    print(f"provider: {where}\nmodel:    {default_model()}\nimage:    {image}\n")

    vetter = describe.make_vetter()
    # A real Screen and Variant rather than stand-ins, so the prompt this builds is
    # byte-for-byte the shape a pass builds. The fingerprints are never read by the
    # vetter - only the id, the hotspots and the image are.
    screen = Screen(id="probe", representative=b"", first_seen=0)
    variant = Variant(id="probe-v1", key="", fp=b"", image=str(image))
    screen.variants[variant.id] = variant
    candidates = [Action("click", at=(0.50, 0.95)), Action("click", at=(0.03, 0.50))]

    verdict = vetter(image, screen, variant, candidates)
    print(f"\nnamed it: {verdict['name']} - {verdict['purpose']}")
    print(f"elements located: {len(verdict['elements'])}")
    for action_id, ruling in verdict["actions"].items():
        print(f"  {'safe  ' if ruling['safe'] else 'unsafe'} {action_id}: {ruling['why']}")
    print("\nvetting works; a pass will be allowed to commit actions")


if __name__ == "__main__":
    main()

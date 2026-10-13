"""web_gui loads web-recon's identity, perceive and safety without putting the archive on
sys.path, so web-recon's bare module names can't shadow anyone else's (#420).

Each check runs in a fresh Python process, because the bug was about what one import does
to the whole process, and this test process has already imported half the engine."""

import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run(code: str, extra_path: Path | None = None) -> str:
    paths = [str(REPO)] + ([str(extra_path)] if extra_path else [])
    env_code = f"import sys; sys.path[:0] = {paths!r}\n" + textwrap.dedent(code)
    done = subprocess.run([sys.executable, "-c", env_code], capture_output=True, text=True, cwd=REPO)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_another_module_called_safety_is_not_shadowed(tmp_path):
    (tmp_path / "safety.py").write_text("WHOSE = 'mine'\n")
    out = _run("""
        from trailhound.adapters.web_gui import session
        import safety
        print(safety.WHOSE, session.gate_plan.__module__)
    """, extra_path=tmp_path)
    assert out == "mine trailhound.adapters.web_gui.recon.safety"


def test_web_recon_is_not_on_the_import_path():
    out = _run("""
        import importlib.util, sys
        from trailhound.adapters.web_gui import from_spoor, session
        from trailhound.adapters.web_gui.recon import WEB_RECON
        print(str(WEB_RECON) in sys.path, importlib.util.find_spec("schema") is None,
              "identity" in sys.modules, "perceive" in sys.modules)
    """)
    assert out == "False True False False"


def test_the_adapter_and_the_converter_share_one_copy_of_each_module():
    out = _run("""
        from trailhound.adapters.web_gui import from_spoor, session
        print(from_spoor.signature is session.signature, from_spoor.capture is session.capture,
              from_spoor.safety.plan is session.gate_plan)
    """)
    assert out == "True True True"

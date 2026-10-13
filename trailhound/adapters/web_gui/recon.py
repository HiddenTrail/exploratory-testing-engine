"""web-recon's perception, identity and safety gate, loaded without touching sys.path.

web_gui reuses three modules from the archived recon (.experiments/web-recon): `identity`
(a state's signature), `perceive` (a live page -> one Observation) and `safety` (the
read-only gate). The crawler that writes the carried map uses the same files, so the
adapter recognises a page exactly as the map does. Copying them here would let the two
drift apart.

They used to be imported by bare name after putting the folder at the front of sys.path.
That made web-recon's `schema`, `safety`, `wiki` and the rest win over any other module of
the same name, in the whole process (#420). Here each file is loaded under a name inside
this package instead, and nothing else in web-recon becomes importable.

The three files only import the standard library, so each loads on its own. If one of them
starts importing a sibling by bare name, loading fails here with ModuleNotFoundError rather
than quietly picking up another module.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

WEB_RECON = Path(__file__).resolve().parents[3] / ".experiments" / "web-recon"


def _load(name: str) -> ModuleType:
    qualified = f"{__name__}.{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, WEB_RECON / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"web_gui needs {WEB_RECON / f'{name}.py'}, which is missing")
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: dataclasses look their module up in sys.modules.
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[qualified]
        raise
    return module


identity = _load("identity")
perceive = _load("perceive")
safety = _load("safety")

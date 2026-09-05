"""Make the pure-logic modules importable without Home Assistant installed.

`parser`, `body` and `assign` deliberately import nothing from Home Assistant
so they can be tested as plain Python. But `ble_scales/__init__.py` does import
it, and a normal `from ble_scales.parser import ...` would execute that first.

Registering a stand-in package with the right __path__ lets the submodules
resolve by file while the real __init__ never runs. The alternative -- pulling
the whole homeassistant dependency tree into CI to test three pure functions --
costs minutes per run and buys nothing.
"""

import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ble_scales"

if "ble_scales" not in sys.modules:
    _pkg = types.ModuleType("ble_scales")
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["ble_scales"] = _pkg

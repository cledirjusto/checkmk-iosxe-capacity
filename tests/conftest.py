"""Minimal stub of the Checkmk plugin API.

Lets the plugin module be imported, and its pure logic tested, on a machine
with no Checkmk installation. Only what module import touches is stubbed;
extend it if the plugin starts using more of the API.
"""

import sys
import types
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(
    0, str(_REPO_ROOT / "cmk_addons" / "plugins" / "iosxe_capacity" / "agent_based")
)


class _Recorder:
    """Stands in for the API's constructors, keeping kwargs for inspection."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return types.SimpleNamespace(_kind=self._name, args=args, **kwargs)


class _State:
    OK = 0
    WARN = 1
    CRIT = 2
    UNKNOWN = 3


def _install_stub() -> None:
    cmk = sys.modules.setdefault("cmk", types.ModuleType("cmk"))
    agent_based = types.ModuleType("cmk.agent_based")
    v2 = types.ModuleType("cmk.agent_based.v2")

    for name in (
        "CheckPlugin",
        "Metric",
        "OIDEnd",
        "Result",
        "Service",
        "SNMPSection",
        "SNMPTree",
        "check_levels",
        "contains",
    ):
        setattr(v2, name, _Recorder(name))

    v2.State = _State
    v2.StringTable = list
    v2.CheckResult = Any
    v2.DiscoveryResult = Any

    agent_based.v2 = v2
    cmk.agent_based = agent_based
    sys.modules["cmk.agent_based"] = agent_based
    sys.modules["cmk.agent_based.v2"] = v2


_install_stub()

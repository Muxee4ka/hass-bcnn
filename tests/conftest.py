"""Shared pytest setup.

We unit-test the pure parts of the integration (HTML parsing, helpers) without
spinning up Home Assistant. The bcnn package's __init__.py imports `homeassistant`
on the top level, so we stub those modules in sys.modules before any test
imports `custom_components.bcnn.*`.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _install_fake_package(name: str) -> types.ModuleType:
    """Register an empty module that Python will treat as a package."""
    module = types.ModuleType(name)
    module.__path__ = []  # marks the module as a package, allowing submodule import
    sys.modules[name] = module
    return module


def _install_fake_submodule(parent: str, child: str) -> MagicMock:
    full = f"{parent}.{child}"
    mock = MagicMock()
    sys.modules[full] = mock
    setattr(sys.modules[parent], child, mock)
    return mock


_install_fake_package("homeassistant")
_install_fake_package("homeassistant.components")
_install_fake_package("homeassistant.helpers")
_install_fake_package("homeassistant.util")

for _sub in ("config_entries", "const", "core", "exceptions"):
    _install_fake_submodule("homeassistant", _sub)
for _sub in ("button", "number", "sensor", "diagnostics"):
    _install_fake_submodule("homeassistant.components", _sub)
for _sub in (
    "config_validation",
    "debounce",
    "device_registry",
    "entity",
    "entity_platform",
    "entity_registry",
    "typing",
    "update_coordinator",
):
    _install_fake_submodule("homeassistant.helpers", _sub)
for _sub in ("dt",):
    _install_fake_submodule("homeassistant.util", _sub)

# Expose `Platform` as a string-like attribute since const.Platform.<NAME>
# is referenced at module import time.
sys.modules["homeassistant.const"].Platform = MagicMock(
    SENSOR="sensor", BUTTON="button", NUMBER="number"
)

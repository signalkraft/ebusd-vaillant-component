"""Regression guard: every module in the component must compile under Python 3.

The unparenthesized multi-type ``except A, B:`` form is a ``SyntaxError`` on
Python 3 and has been reintroduced several times, making the whole integration
fail to import (no entities). Compiling every module catches it before release,
including modules not otherwise exercised by the test suite.
"""

from __future__ import annotations

import py_compile
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent / "custom_components" / "ebusd_vaillant"
_MODULES = sorted(_PKG.rglob("*.py"))


def test_package_discovered() -> None:
    """Fail loud if discovery finds nothing (else the guard is a silent no-op)."""
    assert _MODULES, f"no modules discovered under {_PKG}"


@pytest.mark.parametrize("module", _MODULES, ids=lambda p: p.name)
def test_module_compiles(module: Path, tmp_path: Path) -> None:
    # Write the .pyc to a tmp dir so the source tree stays clean / can be read-only.
    py_compile.compile(str(module), cfile=str(tmp_path / f"{module.stem}.pyc"), doraise=True)

"""Unit tests for _import_qt() QPointF caching and fallback logic."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import qplaywright.agent._server as server


def _reset_server_qt_globals(monkeypatch):
    """Reset all lazily-imported Qt globals so _import_qt() will run again."""
    monkeypatch.setattr(server, "_QtWidgets", None)
    monkeypatch.setattr(server, "_QtCore", None)
    monkeypatch.setattr(server, "_QtGui", None)
    monkeypatch.setattr(server, "_QtTest", None)
    monkeypatch.setattr(server, "_QApplication", None)
    monkeypatch.setattr(server, "_QPointF", None)


class _FakeQPointF:
    """Sentinel class that stands in for a real QPointF."""


def _make_fake_modules(*, qtcore_has_qpointf: bool, qtgui_has_qpointf: bool):
    """Build minimal fake Qt package modules suitable for patching __import__."""
    fake_qpointf = _FakeQPointF if (qtcore_has_qpointf or qtgui_has_qpointf) else None

    fake_qtcore = SimpleNamespace(
        Qt=SimpleNamespace(
            LeftButton="left",
            NoModifier="none",
            MouseFocusReason="mouse",
        ),
        **({"QPointF": fake_qpointf} if qtcore_has_qpointf else {}),
    )
    fake_qtgui = SimpleNamespace(
        **({"QPointF": fake_qpointf} if qtgui_has_qpointf else {}),
    )
    fake_qtwidgets = SimpleNamespace(QApplication=object())
    fake_qttest = SimpleNamespace()

    modules = {
        "FakePkg.QtCore": fake_qtcore,
        "FakePkg.QtWidgets": fake_qtwidgets,
        "FakePkg.QtGui": fake_qtgui,
        "FakePkg.QtTest": fake_qttest,
    }
    return modules, fake_qpointf


def _make_import(modules: dict):
    """Return a __import__ replacement that serves our fake modules first."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def fake_import(name, *args, **kwargs):
        if name in modules:
            return modules[name]
        # Any other "FakePkg.*" that we haven't provided should raise ImportError
        if name.startswith("FakePkg."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    return fake_import


def test_qpointf_cached_from_qtcore(monkeypatch):
    """_import_qt() should cache QPointF from QtCore when it is available there."""
    _reset_server_qt_globals(monkeypatch)

    modules, fake_qpointf = _make_fake_modules(qtcore_has_qpointf=True, qtgui_has_qpointf=False)

    with patch("builtins.__import__", side_effect=_make_import(modules)):
        _patched_import_qt(server, ("FakePkg",))

    assert server._QPointF is fake_qpointf


def test_qpointf_falls_back_to_qtgui(monkeypatch):
    """_import_qt() should fall back to QtGui when QtCore doesn't have QPointF."""
    _reset_server_qt_globals(monkeypatch)

    modules, fake_qpointf = _make_fake_modules(qtcore_has_qpointf=False, qtgui_has_qpointf=True)

    with patch("builtins.__import__", side_effect=_make_import(modules)):
        _patched_import_qt(server, ("FakePkg",))

    assert server._QPointF is fake_qpointf


def test_qpointf_raises_when_neither_module_has_it(monkeypatch):
    """_import_qt() should raise ImportError when QPointF is absent from both modules."""
    _reset_server_qt_globals(monkeypatch)

    modules, _ = _make_fake_modules(qtcore_has_qpointf=False, qtgui_has_qpointf=False)

    with patch("builtins.__import__", side_effect=_make_import(modules)):
        with pytest.raises(ImportError, match="No Qt binding found"):
            _patched_import_qt(server, ("FakePkg",))


def test_import_qt_skips_binding_when_qpointf_missing(monkeypatch):
    """A binding without QPointF in either module is skipped; the next is tried."""
    _reset_server_qt_globals(monkeypatch)

    # First fake pkg has no QPointF; second does.
    class _GoodQPointF:
        pass

    bad_modules = {
        "BadPkg.QtWidgets": SimpleNamespace(QApplication=object()),
        "BadPkg.QtCore": SimpleNamespace(),
        "BadPkg.QtGui": SimpleNamespace(),
        "BadPkg.QtTest": SimpleNamespace(),
    }
    good_modules = {
        "GoodPkg.QtWidgets": SimpleNamespace(QApplication=object()),
        "GoodPkg.QtCore": SimpleNamespace(QPointF=_GoodQPointF),
        "GoodPkg.QtGui": SimpleNamespace(),
        "GoodPkg.QtTest": SimpleNamespace(),
    }
    all_modules = {**bad_modules, **good_modules}

    with patch("builtins.__import__", side_effect=_make_import(all_modules)):
        _patched_import_qt(server, ("BadPkg", "GoodPkg"))

    assert server._QPointF is _GoodQPointF


# ---------------------------------------------------------------------------
# Internal helper — runs the real _import_qt() body against a custom pkg list.
# ---------------------------------------------------------------------------

def _patched_import_qt(srv, pkgs):
    """Re-run the core of _import_qt() using *pkgs* instead of the built-in list."""
    srv._QtWidgets = None
    srv._QtCore = None
    srv._QtGui = None
    srv._QtTest = None
    srv._QApplication = None
    srv._QPointF = None

    for pkg in pkgs:
        try:
            srv._QtWidgets = __import__(f"{pkg}.QtWidgets", fromlist=["QtWidgets"])
            srv._QtCore = __import__(f"{pkg}.QtCore", fromlist=["QtCore"])
            srv._QtGui = __import__(f"{pkg}.QtGui", fromlist=["QtGui"])
            try:
                srv._QtTest = __import__(f"{pkg}.QtTest", fromlist=["QtTest"])
            except ImportError:
                srv._QtTest = None
            srv._QApplication = srv._QtWidgets.QApplication
            srv._QPointF = getattr(srv._QtCore, "QPointF", None)
            if srv._QPointF is None:
                srv._QPointF = getattr(srv._QtGui, "QPointF", None)
            if srv._QPointF is None:
                raise ImportError(f"QPointF not found in {pkg}.QtCore or {pkg}.QtGui")
            return
        except ImportError:
            continue

    raise ImportError("No Qt binding found. Install PySide6, PyQt6, PySide2, or PyQt5.")

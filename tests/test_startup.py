"""Tests for the Windows startup-shortcut helper (section 13). Only
covers the not-frozen (running from source) path, which is what the
test suite always runs under - the frozen path needs a real Windows
Startup folder and pywin32 and is exercised manually when packaging."""

from __future__ import annotations

import pytest

from app.core import startup


def test_not_supported_when_running_from_source():
    assert startup.is_supported() is False


def test_not_enabled_when_not_supported():
    assert startup.is_enabled() is False


def test_set_enabled_raises_clear_error_when_unsupported():
    with pytest.raises(RuntimeError, match="installed application"):
        startup.set_enabled(True)

"""Smoke tests for console-script entry points."""

from __future__ import annotations

import importlib


def test_gateway_importable() -> None:
    mod = importlib.import_module("src.app.gateway")
    assert callable(getattr(mod, "main"))


def test_worker_importable() -> None:
    mod = importlib.import_module("src.app.worker")
    assert callable(getattr(mod, "main"))

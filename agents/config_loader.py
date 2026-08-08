"""Minimal YAML config loader for Hermes agents."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


_config_cache: dict[str, dict] = {}


def _load_config() -> dict:
    """Load all YAML configs from config/ directory."""
    config_dir = Path(__file__).resolve().parent.parent / "config"
    merged: dict[str, dict] = {}
    for yf in sorted(config_dir.glob("*.yaml")):
        try:
            with open(yf, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                merged.update(data)
        except Exception:
            pass
    return merged


def get(section: str, default: dict | None = None) -> dict:
    """Return a config section by its top-level YAML key."""
    if not _config_cache:
        _config_cache.update(_load_config())
    return _config_cache.get(section, default or {})


def reload() -> None:
    """Force reload of all config files."""
    _config_cache.clear()

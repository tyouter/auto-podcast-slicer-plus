"""Configuration loading. Dataclasses only — no module-level mutable globals.

Fixes legacy bug #9: config was carried in module-level dicts
(``_DEFAULT_ERRATA_CONFIG``, ``ERRATA_AUTHORS``, …) which leaked across
concurrent projects in the watcher. Here everything is a value passed explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from garden_core.stage_proofread import ErrataConfig
from garden_core.stage_segment import SegmentOptions

log = logging.getLogger(__name__)

__all__ = ["load_yaml", "build_errata_config", "ConfigError"]


class ConfigError(ValueError):
    """Raised on malformed config."""


def load_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def build_errata_config(errata_yaml_path: str | Path) -> ErrataConfig:
    """Build an ErrataConfig from a project errata.yaml.

    Merges the legacy categorical sub-dicts (authors/works/idioms/common/
    asr_phonetic/asr_noise/variants) into the flat map and loads regex
    patterns. Returns an empty config if the file is missing.
    """
    data = load_yaml(errata_yaml_path)
    if not data:
        return ErrataConfig.empty()

    flat: dict[str, str] = {}
    for key in ("authors", "works", "idioms", "common", "asr_phonetic", "asr_noise"):
        section = data.get(key, {}) or {}
        if isinstance(section, dict):
            flat.update({str(k): str(v) for k, v in section.items()})

    patterns: list[tuple] = []
    for pat in data.get("asr_phonetic_patterns", []) or []:
        if isinstance(pat, dict) and pat.get("pattern"):
            import re
            patterns.append((re.compile(pat["pattern"]), pat.get("replacement", "")))

    return ErrataConfig(flat=flat, patterns=tuple(patterns))

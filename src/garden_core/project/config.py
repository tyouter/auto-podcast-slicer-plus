"""ProjectConfig: the top-level project.yaml data model + validation.

``ProjectConfig`` is the single frozen dataclass that holds every field in
``project.yaml``.  It provides:

* ``from_dict(d)`` / ``to_dict()`` — dict round-trip
* ``from_yaml(path)`` / ``to_yaml(path)`` — file round-trip
* ``validate(cfg) -> None`` — structural/referential consistency check
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from garden_core.config import ConfigError, load_yaml
from garden_core.project.schema import (
    CutPointSpec,
    ProjectMeta,
    ProofOptsSpec,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
)

__all__ = ["ProjectConfig", "validate"]


# --------------------------------------------------------------------------- #
# Styles directory — same resolution as stage_style/molds.py
# --------------------------------------------------------------------------- #
_DEFAULT_STYLES_DIR = Path(__file__).parent.parent / "stage_style" / "styles"


def _known_style_names() -> set[str]:
    """Return the set of style names that have a YAML config in the default dir."""
    if not _DEFAULT_STYLES_DIR.is_dir():
        return set()
    return {
        p.stem for p in _DEFAULT_STYLES_DIR.glob("*.yaml")
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# ProjectConfig
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProjectConfig:
    """Top-level project.yaml data model.

    Every field that has a default value is optional in the YAML.
    ``sources`` and ``cut_points`` are tuples (immutable), consistent with
    the frozen style of ``types.py``.
    """

    meta: ProjectMeta
    sources: tuple[SourceSpec, ...]
    transcript: TranscriptSpec
    errata_path: str = "corrections.yaml"
    proof_opts: ProofOptsSpec = field(default_factory=ProofOptsSpec)
    cut_points: tuple[CutPointSpec, ...] = ()
    style_name: str = "default"
    render_opts: RenderOptsSpec = field(
        default_factory=lambda: RenderOptsSpec(output_dir="output/clips")
    )
    output_dir: str = "output"

    # ------------------------------------------------------------------ #
    # Dict round-trip
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConfig":
        """Build a ProjectConfig from a raw dict (as loaded from YAML)."""
        meta_d = d.get("meta", {}) or {}
        proof_d = d.get("proof_opts", {}) or {}
        render_d = d.get("render_opts", {}) or {}
        transcript_d = d.get("transcript", {}) or {}

        sources_raw = d.get("sources", []) or []
        cut_points_raw = d.get("cut_points", []) or []

        return cls(
            meta=ProjectMeta.from_dict(meta_d),
            sources=tuple(SourceSpec.from_dict(s) for s in sources_raw),
            transcript=TranscriptSpec.from_dict(transcript_d),
            errata_path=str(d.get("errata_path", "corrections.yaml")),
            proof_opts=ProofOptsSpec.from_dict(proof_d),
            cut_points=tuple(CutPointSpec.from_dict(cp) for cp in cut_points_raw),
            style_name=str(d.get("style_name", "default")),
            render_opts=RenderOptsSpec.from_dict(render_d),
            output_dir=str(d.get("output_dir", "output")),
        )

    def to_dict(self) -> dict:
        """Serialise to a plain dict (ready for ``yaml.safe_dump``)."""
        d: dict = {
            "meta": self.meta.to_dict(),
            "sources": [s.to_dict() for s in self.sources],
            "transcript": self.transcript.to_dict(),
        }
        if self.errata_path != "corrections.yaml":
            d["errata_path"] = self.errata_path
        proof_d = self.proof_opts.to_dict()
        if proof_d:
            d["proof_opts"] = proof_d
        if self.cut_points:
            d["cut_points"] = [cp.to_dict() for cp in self.cut_points]
        if self.style_name != "default":
            d["style_name"] = self.style_name
        render_d = self.render_opts.to_dict()
        if render_d:
            d["render_opts"] = render_d
        if self.output_dir != "output":
            d["output_dir"] = self.output_dir
        return d

    # ------------------------------------------------------------------ #
    # YAML file round-trip
    # ------------------------------------------------------------------ #
    @classmethod
    def from_yaml(cls, path: str | Path) -> "ProjectConfig":
        """Load a project.yaml file and return a validated ProjectConfig."""
        data = load_yaml(path)
        if not data:
            raise ConfigError(f"project.yaml is empty or missing: {path}")
        return cls.from_dict(data)

    def to_yaml(self, path: str | Path) -> None:
        """Write this config to a project.yaml file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                self.to_dict(),
                fh,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def validate(cfg: ProjectConfig) -> None:
    """Check structural / referential consistency of a ProjectConfig.

    Raises ``ConfigError`` on the first violation found.  Does **not** check
    file-system existence (that is the caller's responsibility, e.g. T9's
    ``load_project(strict=…)``).

    Checks (in order):
    1. ``sources`` non-empty; every ``id`` unique.
    2. Every ``cut_point.source`` references a known ``sources[].id``.
    3. Every ``cut_point`` lies within its source's timeline bounds.
    4. ``style_name`` has a corresponding YAML in ``stage_style/styles/``.
    5. ``cut_points`` have unique ``clip_id``.
    6. Every ``cut_point`` has ``start_s < end_s``.
    """
    # --- 1. sources -------------------------------------------------------
    if not cfg.sources:
        raise ConfigError("project.yaml: 'sources' must contain at least one entry")

    seen_source_ids: set[str] = set()
    for src in cfg.sources:
        if src.id in seen_source_ids:
            raise ConfigError(
                f"project.yaml: duplicate source id '{src.id}' — "
                f"every source.id must be unique"
            )
        seen_source_ids.add(src.id)

    # Build a lookup for timeline bounds
    source_map: dict[str, SourceSpec] = {s.id: s for s in cfg.sources}

    # --- 2. cut_point source references -----------------------------------
    for cp in cfg.cut_points:
        if cp.source not in source_map:
            raise ConfigError(
                f"project.yaml: cut_point '{cp.clip_id}' references source "
                f"'{cp.source}' which is not defined in 'sources'; "
                f"known source ids: {sorted(seen_source_ids)}"
            )

    # --- 3. timeline bounds -----------------------------------------------
    for cp in cfg.cut_points:
        src = source_map[cp.source]
        if cp.start_s < src.timeline_start_s:
            raise ConfigError(
                f"project.yaml: cut_point '{cp.clip_id}' start_s={cp.start_s} "
                f"is before its source '{cp.source}' timeline_start_s="
                f"{src.timeline_start_s}"
            )
        if src.timeline_end_s is not None and cp.end_s > src.timeline_end_s:
            raise ConfigError(
                f"project.yaml: cut_point '{cp.clip_id}' end_s={cp.end_s} "
                f"exceeds its source '{cp.source}' timeline_end_s="
                f"{src.timeline_end_s}"
            )

    # --- 4. style_name ----------------------------------------------------
    known_styles = _known_style_names()
    if known_styles and cfg.style_name not in known_styles:
        raise ConfigError(
            f"project.yaml: style_name '{cfg.style_name}' not found in "
            f"stage_style/styles/; known styles: {sorted(known_styles)}"
        )

    # --- 5. unique clip_id ------------------------------------------------
    seen_clip_ids: set[str] = set()
    for cp in cfg.cut_points:
        if cp.clip_id in seen_clip_ids:
            raise ConfigError(
                f"project.yaml: duplicate clip_id '{cp.clip_id}' — "
                f"every cut_point.clip_id must be unique"
            )
        seen_clip_ids.add(cp.clip_id)

    # --- 6. start_s < end_s -----------------------------------------------
    for cp in cfg.cut_points:
        if cp.start_s >= cp.end_s:
            raise ConfigError(
                f"project.yaml: cut_point '{cp.clip_id}' has start_s={cp.start_s} "
                f">= end_s={cp.end_s}; start_s must be < end_s"
            )

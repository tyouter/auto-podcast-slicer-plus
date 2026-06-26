"""Spec dataclasses for project.yaml configuration.

Every spec is ``@dataclass(frozen=True)`` — they are immutable value objects.
Each provides ``from_dict`` / ``to_dict`` for YAML round-trip.

Time unit iron law (inherited from ``types.py``): all ``_s`` fields are **seconds (float)**.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# ProjectMeta
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProjectMeta:
    """Project identity and root directory.

    ``root`` is the project root (absolute path, or relative to cwd at load time).
    """

    name: str
    root: str

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectMeta":
        return cls(
            name=str(d.get("name", "")),
            root=str(d.get("root", "")),
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "root": self.root}


# --------------------------------------------------------------------------- #
# SourceSpec — multi-source first-class citizen
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SourceSpec:
    """A source media entry in project.yaml.

    ``timeline_start_s`` / ``timeline_end_s`` define the span this source
    occupies on the **global (original) timeline** for multi-source projects.

    ``source_offset_s`` translates from global-time cut windows into the source
    media's local timeline (e.g. for multi-source concatenation).  It has the
    same semantics as ``types.CutPoint.source_offset_s`` — at T11 runtime it is
    forwarded to that field.
    """

    id: str
    path: str
    timeline_start_s: float = 0.0
    timeline_end_s: Optional[float] = None
    source_offset_s: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "SourceSpec":
        return cls(
            id=str(d["id"]),
            path=str(d["path"]),
            timeline_start_s=float(d.get("timeline_start_s", 0.0)),
            timeline_end_s=float(d["timeline_end_s"]) if d.get("timeline_end_s") is not None else None,
            source_offset_s=float(d.get("source_offset_s", 0.0)),
        )

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"id": self.id, "path": self.path}
        if self.timeline_start_s != 0.0:
            d["timeline_start_s"] = self.timeline_start_s
        if self.timeline_end_s is not None:
            d["timeline_end_s"] = self.timeline_end_s
        if self.source_offset_s != 0.0:
            d["source_offset_s"] = self.source_offset_s
        return d


# --------------------------------------------------------------------------- #
# CutPointSpec — clip definition on the original timeline
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CutPointSpec:
    """A clip boundary definition on the **global (original) timeline**.

    ``source`` references a ``SourceSpec.id``.  T11's multi-source translator
    resolves ``CutPointSpec → types.CutPoint`` by translating global-time
    windows into per-source local times via ``SourceSpec.source_offset_s``.

    This is the **config layer** type; ``types.CutPoint`` is the **runtime**
    type (already carrying a resolved ``source_media`` absolute path +
    ``source_offset_s``).
    """

    clip_id: str
    source: str          # references sources[].id  (YAML key is "source")
    start_s: float
    end_s: float
    style_name: str = "default"
    title: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CutPointSpec":
        return cls(
            clip_id=str(d["clip_id"]),
            source=str(d["source"]),
            start_s=float(d["start_s"]),
            end_s=float(d["end_s"]),
            style_name=str(d.get("style_name", "default")),
            title=str(d.get("title", "")),
        )

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "clip_id": self.clip_id,
            "source": self.source,
            "start_s": self.start_s,
            "end_s": self.end_s,
        }
        if self.style_name != "default":
            d["style_name"] = self.style_name
        if self.title:
            d["title"] = self.title
        return d


# --------------------------------------------------------------------------- #
# RenderOptsSpec — config-layer mirror of stage_render.RenderOptions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RenderOptsSpec:
    """Config-layer render options (frozen mirror of ``RenderOptions``).

    At T11 runtime this is converted to the mutable ``RenderOptions`` that
    ``stage_render.render()`` expects.
    """

    output_dir: str = "output/clips"
    horizontal_width: int = 1920
    horizontal_height: int = 1080
    vertical_width: int = 1080
    vertical_height: int = 1920
    crf: int = 18
    render_horizontal: bool = True
    render_vertical: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "RenderOptsSpec":
        return cls(
            output_dir=str(d.get("output_dir", "output/clips")),
            horizontal_width=int(d.get("horizontal_width", 1920)),
            horizontal_height=int(d.get("horizontal_height", 1080)),
            vertical_width=int(d.get("vertical_width", 1080)),
            vertical_height=int(d.get("vertical_height", 1920)),
            crf=int(d.get("crf", 18)),
            render_horizontal=bool(d.get("render_horizontal", True)),
            render_vertical=bool(d.get("render_vertical", True)),
        )

    def to_dict(self) -> dict:
        d: dict[str, Any] = {}
        if self.output_dir != "output/clips":
            d["output_dir"] = self.output_dir
        if self.horizontal_width != 1920:
            d["horizontal_width"] = self.horizontal_width
        if self.horizontal_height != 1080:
            d["horizontal_height"] = self.horizontal_height
        if self.vertical_width != 1080:
            d["vertical_width"] = self.vertical_width
        if self.vertical_height != 1920:
            d["vertical_height"] = self.vertical_height
        if self.crf != 18:
            d["crf"] = self.crf
        if not self.render_horizontal:
            d["render_horizontal"] = self.render_horizontal
        if not self.render_vertical:
            d["render_vertical"] = self.render_vertical
        return d


# --------------------------------------------------------------------------- #
# ProofOptsSpec — config-layer mirror of stage_proofread.ProofOptions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProofOptsSpec:
    """Config-layer proofread options (frozen mirror of ``ProofOptions``).

    At T11 runtime this is converted to ``ProofOptions`` (which is also frozen,
    but the separation keeps config-layer and runtime-layer types distinct).
    """

    enable_normalize: bool = True
    enable_errata: bool = True
    enable_phonetic: bool = True
    enable_llm: bool = False
    enable_dual_channel: bool = True
    llm_temperature: float = 0.1

    @classmethod
    def from_dict(cls, d: dict) -> "ProofOptsSpec":
        return cls(
            enable_normalize=bool(d.get("enable_normalize", True)),
            enable_errata=bool(d.get("enable_errata", True)),
            enable_phonetic=bool(d.get("enable_phonetic", True)),
            enable_llm=bool(d.get("enable_llm", False)),
            enable_dual_channel=bool(d.get("enable_dual_channel", True)),
            llm_temperature=float(d.get("llm_temperature", 0.1)),
        )

    def to_dict(self) -> dict:
        d: dict[str, Any] = {}
        if not self.enable_normalize:
            d["enable_normalize"] = self.enable_normalize
        if not self.enable_errata:
            d["enable_errata"] = self.enable_errata
        if not self.enable_phonetic:
            d["enable_phonetic"] = self.enable_phonetic
        if self.enable_llm:
            d["enable_llm"] = self.enable_llm
        if not self.enable_dual_channel:
            d["enable_dual_channel"] = self.enable_dual_channel
        if self.llm_temperature != 0.1:
            d["llm_temperature"] = self.llm_temperature
        return d


# --------------------------------------------------------------------------- #
# TranscriptSpec
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TranscriptSpec:
    """Transcript paths: source audio for ASR + transcript.json location."""

    audio_path: str
    path: str

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptSpec":
        return cls(
            audio_path=str(d["audio_path"]),
            path=str(d["path"]),
        )

    def to_dict(self) -> dict:
        return {"audio_path": self.audio_path, "path": self.path}

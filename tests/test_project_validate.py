"""T7: validate(cfg) tests — structural / referential consistency checks."""

from __future__ import annotations

import pytest

from garden_core.config import ConfigError
from garden_core.project import (
    CutPointSpec,
    ProjectConfig,
    ProjectMeta,
    ProofOptsSpec,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
    validate,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_SENTINEL = object()

def _valid_cfg(
    *,
    sources: tuple[SourceSpec, ...] | object = _SENTINEL,
    cut_points: tuple[CutPointSpec, ...] | object = _SENTINEL,
    style_name: str = "default",
) -> ProjectConfig:
    """Build a minimal valid ProjectConfig with optional overrides."""
    if sources is _SENTINEL:
        sources = (SourceSpec(id="SRC1", path="v1.mp4", timeline_start_s=0.0, timeline_end_s=1000.0),)
    if cut_points is _SENTINEL:
        cut_points = ()
    return ProjectConfig(
        meta=ProjectMeta(name="test", root="/tmp/test"),
        sources=sources,
        transcript=TranscriptSpec(audio_path="a.wav", path="t.json"),
        errata_path="corrections.yaml",
        proof_opts=ProofOptsSpec(),
        cut_points=cut_points,
        style_name=style_name,
        render_opts=RenderOptsSpec(),
        output_dir="output",
    )


# --------------------------------------------------------------------------- #
# valid config passes
# --------------------------------------------------------------------------- #
def test_validate_valid_minimal():
    validate(_valid_cfg())


def test_validate_valid_with_cut_points():
    cfg = _valid_cfg(cut_points=(
        CutPointSpec(clip_id="t01", source="SRC1", start_s=10.0, end_s=30.0),
        CutPointSpec(clip_id="t02", source="SRC1", start_s=50.0, end_s=80.0),
    ))
    validate(cfg)


def test_validate_valid_style_fresh():
    cfg = _valid_cfg(style_name="fresh")
    validate(cfg)


def test_validate_valid_timeline_end_none():
    """When timeline_end_s is None, only lower bound is checked."""
    cfg = _valid_cfg(
        sources=(
            SourceSpec(id="SRC1", path="v1.mp4", timeline_start_s=0.0, timeline_end_s=None),
        ),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=500.0, end_s=9999.0),
        ),
    )
    validate(cfg)


def test_validate_valid_multi_source():
    cfg = _valid_cfg(
        sources=(
            SourceSpec(id="SRC1", path="v1.mp4", timeline_start_s=0.0, timeline_end_s=850.0),
            SourceSpec(id="SRC2", path="v2.mp4", timeline_start_s=850.0, timeline_end_s=1294.0, source_offset_s=850.0),
        ),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=10.0, end_s=30.0),
            CutPointSpec(clip_id="t02", source="SRC2", start_s=860.0, end_s=900.0),
        ),
    )
    validate(cfg)


# --------------------------------------------------------------------------- #
# 1. sources non-empty + unique id
# --------------------------------------------------------------------------- #
def test_validate_empty_sources_raises():
    cfg = _valid_cfg(sources=())
    with pytest.raises(ConfigError, match="at least one entry"):
        validate(cfg)


def test_validate_duplicate_source_id_raises():
    cfg = _valid_cfg(
        sources=(
            SourceSpec(id="SRC1", path="v1.mp4"),
            SourceSpec(id="SRC1", path="v2.mp4"),  # duplicate id
        ),
    )
    with pytest.raises(ConfigError, match="duplicate source id.*SRC1"):
        validate(cfg)


# --------------------------------------------------------------------------- #
# 2. cut_point.source references
# --------------------------------------------------------------------------- #
def test_validate_bad_source_ref_raises():
    cfg = _valid_cfg(
        sources=(SourceSpec(id="SRC1", path="v1.mp4"),),
        cut_points=(
            CutPointSpec(clip_id="t01", source="NOPE", start_s=10.0, end_s=30.0),
        ),
    )
    with pytest.raises(ConfigError, match="t01.*references source.*NOPE"):
        validate(cfg)


# --------------------------------------------------------------------------- #
# 3. timeline bounds
# --------------------------------------------------------------------------- #
def test_validate_start_before_timeline_raises():
    cfg = _valid_cfg(
        sources=(SourceSpec(id="SRC1", path="v1.mp4", timeline_start_s=100.0, timeline_end_s=1000.0),),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=50.0, end_s=150.0),
        ),
    )
    with pytest.raises(ConfigError, match="t01.*start_s=50.*before.*timeline_start_s=100"):
        validate(cfg)


def test_validate_end_past_timeline_raises():
    cfg = _valid_cfg(
        sources=(SourceSpec(id="SRC1", path="v1.mp4", timeline_start_s=0.0, timeline_end_s=100.0),),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=10.0, end_s=150.0),
        ),
    )
    with pytest.raises(ConfigError, match="t01.*end_s=150.*exceeds.*timeline_end_s=100"):
        validate(cfg)


# --------------------------------------------------------------------------- #
# 4. style_name
# --------------------------------------------------------------------------- #
def test_validate_unknown_style_raises():
    cfg = _valid_cfg(style_name="nonexistent_style_xyz")
    with pytest.raises(ConfigError, match="style_name.*nonexistent_style_xyz.*not found"):
        validate(cfg)


# --------------------------------------------------------------------------- #
# 5. duplicate clip_id
# --------------------------------------------------------------------------- #
def test_validate_duplicate_clip_id_raises():
    cfg = _valid_cfg(
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=10.0, end_s=20.0),
            CutPointSpec(clip_id="t01", source="SRC1", start_s=30.0, end_s=40.0),
        ),
    )
    with pytest.raises(ConfigError, match="duplicate clip_id.*t01"):
        validate(cfg)


# --------------------------------------------------------------------------- #
# 6. start_s < end_s
# --------------------------------------------------------------------------- #
def test_validate_start_not_less_than_end_raises():
    cfg = _valid_cfg(
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=50.0, end_s=50.0),
        ),
    )
    with pytest.raises(ConfigError, match="t01.*start_s=50.*>=.*end_s=50"):
        validate(cfg)


def test_validate_start_greater_than_end_raises():
    cfg = _valid_cfg(
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=100.0, end_s=50.0),
        ),
    )
    with pytest.raises(ConfigError, match="t01.*start_s.*>=.*end_s"):
        validate(cfg)


# --------------------------------------------------------------------------- #
# edge: validate does NOT check file existence
# --------------------------------------------------------------------------- #
def test_validate_does_not_check_file_existence():
    """Validate should pass even when paths don't exist on disk (Q1 default A)."""
    cfg = ProjectConfig(
        meta=ProjectMeta(name="test", root="/nonexistent/root"),
        sources=(
            SourceSpec(id="S1", path="nonexistent_video.mp4"),
        ),
        transcript=TranscriptSpec(audio_path="nonexistent.wav", path="nonexistent.json"),
        errata_path="nonexistent_errata.yaml",
    )
    validate(cfg)  # must not raise

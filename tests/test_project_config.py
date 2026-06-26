"""T7: ProjectConfig from_dict/to_dict/from_yaml/to_yaml round-trip tests."""

from __future__ import annotations

import dataclasses
import os
import tempfile

import pytest

from garden_core.project import (
    CutPointSpec,
    ProjectConfig,
    ProjectMeta,
    ProofOptsSpec,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _tesla_shape_dict() -> dict:
    """A dict matching the tesla_stage04 multi-source shape (values are
    representative but NOT real tesla data — hygiene)."""
    return {
        "meta": {"name": "example-project", "root": "<project-root>"},
        "sources": [
            {
                "id": "SRC1",
                "path": "<source-part1>.mp4",
                "timeline_start_s": 0.0,
                "timeline_end_s": 850.0,
            },
            {
                "id": "SRC2",
                "path": "<source-part2>.mp4",
                "timeline_start_s": 850.0,
                "timeline_end_s": 1294.0,
                "source_offset_s": 850.0,
            },
        ],
        "transcript": {
            "audio_path": "<audio>.wav",
            "path": "transcript.json",
        },
        "errata_path": "corrections.yaml",
        "proof_opts": {"enable_llm": True},
        "cut_points": [
            {"clip_id": f"t{i:02d}", "source": "SRC1", "start_s": s, "end_s": s + 35}
            for i, s in enumerate(
                [0, 75, 140, 215, 295, 375, 455, 535, 615, 695, 775], start=1
            )
        ]
        + [
            {"clip_id": f"t{i:02d}", "source": "SRC2", "start_s": s, "end_s": s + 55}
            for i, s in enumerate(
                [860, 925, 1005, 1085, 1165, 1240], start=12
            )
        ],
        "style_name": "default",
        "render_opts": {
            "horizontal_width": 1920,
            "horizontal_height": 1080,
            "crf": 20,
        },
        "output_dir": "output",
    }


# --------------------------------------------------------------------------- #
# frozen
# --------------------------------------------------------------------------- #
def test_project_config_is_frozen():
    cfg = ProjectConfig.from_dict(_tesla_shape_dict())
    assert dataclasses.is_dataclass(cfg) and cfg.__dataclass_params__.frozen

    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.output_dir = "hacked"  # type: ignore[misc]


def test_spec_types_are_frozen():
    for cls in [
        ProjectMeta, SourceSpec, CutPointSpec,
        RenderOptsSpec, ProofOptsSpec, TranscriptSpec,
    ]:
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen, \
            f"{cls.__name__} not frozen"


# --------------------------------------------------------------------------- #
# from_dict → to_dict round-trip
# --------------------------------------------------------------------------- #
def test_from_dict_to_dict_roundtrip_tesla_shape():
    d = _tesla_shape_dict()
    cfg = ProjectConfig.from_dict(d)
    # Basic field checks
    assert cfg.meta.name == "example-project"
    assert len(cfg.sources) == 2
    assert cfg.sources[0].id == "SRC1"
    assert cfg.sources[1].source_offset_s == 850.0
    assert len(cfg.cut_points) == 17
    assert cfg.proof_opts.enable_llm is True
    assert cfg.render_opts.horizontal_width == 1920
    assert cfg.render_opts.crf == 20

    # Round-trip
    d2 = cfg.to_dict()
    # Semantic equivalence: reconstruct from d2 and compare fields
    cfg2 = ProjectConfig.from_dict(d2)
    assert cfg2.meta == cfg.meta
    assert cfg2.sources == cfg.sources
    assert cfg2.transcript == cfg.transcript
    assert cfg2.errata_path == cfg.errata_path
    assert cfg2.proof_opts == cfg.proof_opts
    assert cfg2.cut_points == cfg.cut_points
    assert cfg2.style_name == cfg.style_name
    assert cfg2.render_opts == cfg.render_opts
    assert cfg2.output_dir == cfg.output_dir

    # Full equality
    assert cfg2 == cfg


def test_from_dict_minimal():
    """Minimal valid project: only required fields."""
    d = {
        "meta": {"name": "min", "root": "/tmp/min"},
        "sources": [{"id": "S1", "path": "v.mp4"}],
        "transcript": {"audio_path": "a.wav", "path": "t.json"},
    }
    cfg = ProjectConfig.from_dict(d)
    assert cfg.meta.name == "min"
    assert len(cfg.sources) == 1
    assert cfg.cut_points == ()
    assert cfg.style_name == "default"
    assert cfg.errata_path == "corrections.yaml"
    assert cfg.output_dir == "output"
    assert cfg.render_opts.output_dir == "output/clips"


def test_to_dict_omits_defaults():
    """to_dict() should omit fields whose values equal their defaults."""
    d = {
        "meta": {"name": "x", "root": "/x"},
        "sources": [{"id": "S1", "path": "v.mp4"}],
        "transcript": {"audio_path": "a.wav", "path": "t.json"},
    }
    cfg = ProjectConfig.from_dict(d)
    out = cfg.to_dict()
    # Defaults that should be absent
    assert "proof_opts" not in out  # all defaults
    assert "render_opts" not in out  # all defaults (output_dir='output/clips')
    assert "errata_path" not in out  # default "corrections.yaml"
    assert "style_name" not in out   # default "default"
    assert "output_dir" not in out   # default "output"
    assert "cut_points" not in out   # empty tuple


def test_to_dict_includes_overrides():
    """Non-default values must appear in to_dict()."""
    cfg = ProjectConfig(
        meta=ProjectMeta(name="x", root="/x"),
        sources=(SourceSpec(id="S1", path="v.mp4"),),
        transcript=TranscriptSpec(audio_path="a.wav", path="t.json"),
        style_name="fresh",
        render_opts=RenderOptsSpec(crf=20, horizontal_width=3840, horizontal_height=2160),
        proof_opts=ProofOptsSpec(enable_llm=True),
    )
    out = cfg.to_dict()
    assert out.get("style_name") == "fresh"
    ro = out.get("render_opts", {})
    assert ro.get("crf") == 20
    assert ro.get("horizontal_width") == 3840
    assert ro.get("horizontal_height") == 2160
    # output_dir default "output/clips" → omitted
    assert "output_dir" not in ro
    po = out.get("proof_opts", {})
    assert po.get("enable_llm") is True
    # Normalize default → omitted
    assert "enable_normalize" not in po


# --------------------------------------------------------------------------- #
# YAML round-trip
# --------------------------------------------------------------------------- #
def test_yaml_round_trip():
    d = _tesla_shape_dict()
    cfg = ProjectConfig.from_dict(d)
    with tempfile.TemporaryDirectory() as td:
        yaml_path = os.path.join(td, "project.yaml")
        cfg.to_yaml(yaml_path)
        assert os.path.isfile(yaml_path)

        cfg2 = ProjectConfig.from_yaml(yaml_path)
        assert cfg2 == cfg


def test_from_yaml_empty_file_raises():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "empty.yaml")
        # Write an empty file
        with open(p, "w") as fh:
            fh.write("")
        from garden_core.config import ConfigError
        with pytest.raises(ConfigError, match="empty or missing"):
            ProjectConfig.from_yaml(p)


def test_from_yaml_missing_file_returns_empty_dict_but_config_raises():
    """load_yaml returns {} for missing files, but ProjectConfig.from_yaml
    should detect that and raise ConfigError."""
    from garden_core.config import ConfigError
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "nonexistent.yaml")
        with pytest.raises(ConfigError, match="empty or missing"):
            ProjectConfig.from_yaml(p)

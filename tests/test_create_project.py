"""T8: create_project tests — directory scaffolding + project.yaml + defaults."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from garden_core.config import ConfigError, load_yaml
from garden_core.project import (
    ProjectConfig,
    RenderOptsSpec,
    SourceSpec,
    create_project,
    validate,
)
from garden_core.project.schema import ProofOptsSpec, ProjectMeta, TranscriptSpec


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _simple_sources() -> list[SourceSpec]:
    return [SourceSpec(id="SRC1", path="source/ep01.mp4")]


def _assert_dir_tree_minimal(root: Path) -> None:
    """Assert the minimal skeleton directories and files exist."""
    assert (root / "source").is_dir()
    assert (root / "output" / "clips").is_dir()
    assert (root / "output" / "fullcut").is_dir()
    assert (root / "output" / "release").is_dir()
    assert (root / "corrections.yaml").is_file()
    assert (root / "AGENTS.md").is_file()
    assert (root / "README.md").is_file()
    assert (root / "project.yaml").is_file()


# --------------------------------------------------------------------------- #
# basic scaffolding
# --------------------------------------------------------------------------- #

def test_create_project_creates_directory_tree(tmp_path: Path):
    """create_project builds the full minimal skeleton."""
    root = tmp_path / "myproj"
    create_project("demo", root, sources=_simple_sources())
    _assert_dir_tree_minimal(root)


def test_create_project_returns_validated_config(tmp_path: Path):
    """Returned ProjectConfig is already validated."""
    root = tmp_path / "myproj"
    cfg = create_project("demo", root, sources=_simple_sources())
    assert isinstance(cfg, ProjectConfig)
    # Must not raise (already validated internally)
    validate(cfg)


# --------------------------------------------------------------------------- #
# project.yaml round-trip
# --------------------------------------------------------------------------- #

def test_project_yaml_round_trip(tmp_path: Path):
    """Written project.yaml can be read back and matches the create return."""
    root = tmp_path / "myproj"
    sources = [
        SourceSpec(id="SRC1", path="source/ep01.mp4", timeline_start_s=0.0, timeline_end_s=850.0),
        SourceSpec(id="SRC2", path="source/ep02.mp4", timeline_start_s=850.0, timeline_end_s=1294.0, source_offset_s=850.0),
    ]
    cfg = create_project("demo", root, sources=sources)

    # Read back
    cfg2 = ProjectConfig.from_yaml(root / "project.yaml")

    # Field-level assertions
    assert cfg2.meta == ProjectMeta(name="demo", root=str(root.resolve()))
    assert cfg2.sources == tuple(sources)
    assert cfg2.style_name == "fresh"
    assert cfg2.cut_points == ()
    assert cfg2.output_dir == "output"

    # Transcript placeholders
    assert cfg2.transcript.audio_path == "source/demo.wav"
    assert cfg2.transcript.path == "output/transcript.json"

    # errata_path
    assert cfg2.errata_path == "corrections.yaml"

    # Full equality
    assert cfg2 == cfg


def test_project_yaml_fields_match_params(tmp_path: Path):
    """Every field from create params is reflected in the yaml."""
    root = tmp_path / "myproj"
    cfg = create_project("testproj", root, sources=_simple_sources())

    # From yaml (not the returned object) to verify file is correct
    data = load_yaml(root / "project.yaml")
    assert data["meta"]["name"] == "testproj"
    assert data["meta"]["root"] == str(root.resolve())
    assert len(data["sources"]) == 1
    assert data["sources"][0]["id"] == "SRC1"
    assert data["transcript"]["audio_path"] == "source/testproj.wav"
    assert data["transcript"]["path"] == "output/transcript.json"
    assert data.get("style_name") == "fresh"  # non-default → written


def test_project_yaml_4k_render_opts(tmp_path: Path):
    """Default render_opts write 4K values to yaml — only non-schema-default fields."""
    root = tmp_path / "myproj"
    create_project("demo", root, sources=_simple_sources())
    data = load_yaml(root / "project.yaml")
    ro = data.get("render_opts", {})
    # horizontal 3840×2160 differs from schema default 1920×1080 → written
    assert ro.get("horizontal_width") == 3840
    assert ro.get("horizontal_height") == 2160
    # vertical 1080×1920 matches schema default → NOT written
    assert "vertical_width" not in ro
    assert "vertical_height" not in ro
    # crf 18 matches schema default → NOT written
    assert "crf" not in ro


def test_project_yaml_custom_render_opts(tmp_path: Path):
    """Custom render_opts override the 4K defaults — only non-schema-default fields."""
    root = tmp_path / "myproj"
    custom = RenderOptsSpec(
        output_dir="output/clips",
        horizontal_width=1920,
        horizontal_height=1080,
        crf=20,
    )
    cfg = create_project("demo", root, sources=_simple_sources(), render_opts=custom)
    data = load_yaml(root / "project.yaml")
    ro = data.get("render_opts", {})
    # horizontal_width=1920 matches schema default → NOT written
    assert "horizontal_width" not in ro
    # horizontal_height=1080 matches schema default → NOT written
    assert "horizontal_height" not in ro
    # crf=20 differs from schema default 18 → written
    assert ro.get("crf") == 20
    # Only crf differs
    assert list(ro.keys()) == ["crf"]


# --------------------------------------------------------------------------- #
# audio_path / transcript
# --------------------------------------------------------------------------- #

def test_audio_path_placeholder_default(tmp_path: Path):
    """When audio_path is None, the placeholder source/<name>.wav is used."""
    root = tmp_path / "myproj"
    cfg = create_project("hello", root, sources=_simple_sources())
    assert cfg.transcript.audio_path == "source/hello.wav"


def test_audio_path_explicit(tmp_path: Path):
    """Explicit audio_path is used as-is."""
    root = tmp_path / "myproj"
    cfg = create_project("demo", root, sources=_simple_sources(), audio_path="/abs/path/audio.wav")
    assert cfg.transcript.audio_path == "/abs/path/audio.wav"


# --------------------------------------------------------------------------- #
# style
# --------------------------------------------------------------------------- #

def test_style_default_fresh(tmp_path: Path):
    """Default style is 'fresh' (Plan T8 spec)."""
    root = tmp_path / "myproj"
    cfg = create_project("demo", root, sources=_simple_sources())
    assert cfg.style_name == "fresh"


def test_style_explicit(tmp_path: Path):
    """Explicit style is used, and validated."""
    root = tmp_path / "myproj"
    cfg = create_project("demo", root, sources=_simple_sources(), style="default")
    assert cfg.style_name == "default"


def test_style_bad_raises_config_error(tmp_path: Path):
    """Unknown style name → ConfigError (create = validate)."""
    root = tmp_path / "myproj"
    with pytest.raises(ConfigError, match="nonexistent_style"):
        create_project("demo", root, sources=_simple_sources(), style="nonexistent_style")
    # No half-created directory should be left behind
    assert not root.exists()


# --------------------------------------------------------------------------- #
# corrections.yaml
# --------------------------------------------------------------------------- #

def test_corrections_none_writes_empty_dict(tmp_path: Path):
    """corrections=None writes {}."""
    root = tmp_path / "myproj"
    create_project("demo", root, sources=_simple_sources())
    data = load_yaml(root / "corrections.yaml")
    assert data == {}


def test_corrections_dict_is_written(tmp_path: Path):
    """corrections=<dict> writes that dict."""
    root = tmp_path / "myproj"
    create_project("demo", root, sources=_simple_sources(), corrections={"foo": "bar", "key": "val"})
    data = load_yaml(root / "corrections.yaml")
    assert data == {"foo": "bar", "key": "val"}


# --------------------------------------------------------------------------- #
# overwrite guard
# --------------------------------------------------------------------------- #

def test_overwrite_false_on_nonempty_raises(tmp_path: Path):
    """overwrite=False with non-empty root → ConfigError."""
    root = tmp_path / "existing"
    root.mkdir(parents=True)
    (root / "some_file.txt").write_text("hi")
    with pytest.raises(ConfigError, match="already exists.*not empty"):
        create_project("demo", root, sources=_simple_sources())


def test_overwrite_false_on_empty_dir_is_ok(tmp_path: Path):
    """overwrite=False on empty directory is allowed."""
    root = tmp_path / "empty"
    root.mkdir(parents=True)
    cfg = create_project("demo", root, sources=_simple_sources())
    assert cfg.meta.name == "demo"


def test_overwrite_true_allows_rebuild(tmp_path: Path):
    """overwrite=True allows re-creating in a non-empty dir."""
    root = tmp_path / "rebuild"
    root.mkdir(parents=True)
    (root / "old_file.txt").write_text("existing")
    cfg = create_project("demo", root, sources=_simple_sources(), overwrite=True)
    assert cfg.meta.name == "demo"
    # old file should still exist (rebuild doesn't wipe unrelated files)
    assert (root / "old_file.txt").is_file()


def test_overwrite_true_does_not_delete_source_dir(tmp_path: Path):
    """overwrite=True never deletes source/ content (template iron law)."""
    root = tmp_path / "rebuild"
    # First create
    create_project("demo", root, sources=_simple_sources())
    marker = root / "source" / "marker.txt"
    marker.write_text("precious source content")

    # Rebuild with overwrite=True
    create_project("demo", root, sources=_simple_sources(), overwrite=True)

    # Marker must still exist
    assert marker.is_file()
    assert marker.read_text() == "precious source content"


def test_overwrite_false_on_nonexistent_is_ok(tmp_path: Path):
    """overwrite=False on a path that doesn't exist is fine."""
    root = tmp_path / "newdir"
    cfg = create_project("demo", root, sources=_simple_sources())
    assert cfg.meta.name == "demo"


# --------------------------------------------------------------------------- #
# wiki
# --------------------------------------------------------------------------- #

def test_wiki_false_no_wiki_dir(tmp_path: Path):
    """wiki=False (default) does NOT create Wiki/."""
    root = tmp_path / "nowiki"
    create_project("demo", root, sources=_simple_sources())
    assert not (root / "Wiki").exists()


def test_wiki_true_creates_full_wiki_tree(tmp_path: Path):
    """wiki=True creates Wiki/<name>/{A..M} sub-directories."""
    root = tmp_path / "withwiki"
    create_project("demo", root, sources=_simple_sources(), wiki=True)

    wiki_root = root / "Wiki" / "demo"
    assert wiki_root.is_dir()

    expected_dirs = [
        "A_花园地图", "B_创作宣言", "C_〈原著参考〉", "D_花园对话",
        "E_人类创作", "F_AI 创作", "G_发布管线", "H_发布渠道",
        "I_发布日志", "J_长期反馈", "K_行者社群", "L_开源说明", "M_概念花园",
    ]
    for d in expected_dirs:
        assert (wiki_root / d).is_dir(), f"Missing Wiki sub-dir: {d}"


# --------------------------------------------------------------------------- #
# AGENTS.md / README.md
# --------------------------------------------------------------------------- #

def test_agents_md_exists_and_contains_keywords(tmp_path: Path):
    """AGENTS.md is written with garden spirit + boundary content."""
    root = tmp_path / "proj"
    create_project("demo", root, sources=_simple_sources())
    content = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "花园精神" in content
    assert "权限边界" in content
    assert "create_project" in content
    assert "project.yaml" in content


def test_readme_md_exists_and_contains_project_name(tmp_path: Path):
    """README.md is written with project name."""
    root = tmp_path / "proj"
    create_project("my-awesome-project", root, sources=_simple_sources())
    content = (root / "README.md").read_text(encoding="utf-8")
    assert "# my-awesome-project" in content
    assert "load_project" in content


# --------------------------------------------------------------------------- #
# validation: create = validate
# --------------------------------------------------------------------------- #

def test_create_rejects_empty_sources(tmp_path: Path):
    """Empty sources → ConfigError (validate rejects)."""
    root = tmp_path / "bad"
    with pytest.raises(ConfigError, match="at least one entry"):
        create_project("demo", root, sources=[])
    # No partial directory left behind
    assert not root.exists()


def test_create_rejects_duplicate_source_ids(tmp_path: Path):
    """Duplicate source.id → ConfigError."""
    root = tmp_path / "bad"
    with pytest.raises(ConfigError, match="duplicate source id"):
        create_project(
            "demo", root,
            sources=[
                SourceSpec(id="S1", path="a.mp4"),
                SourceSpec(id="S1", path="b.mp4"),
            ],
        )
    assert not root.exists()


# --------------------------------------------------------------------------- #
# edge cases
# --------------------------------------------------------------------------- #

def test_root_resolves_to_absolute(tmp_path: Path):
    """root_dir is resolved to absolute path before use."""
    # Use a relative path
    rel = tmp_path / "relproj"
    create_project("demo", rel, sources=_simple_sources())
    cfg_read = ProjectConfig.from_yaml(rel / "project.yaml")
    assert Path(cfg_read.meta.root).is_absolute()


def test_create_preserves_proof_opts_defaults(tmp_path: Path):
    """Default proof_opts are used."""
    root = tmp_path / "proj"
    cfg = create_project("demo", root, sources=_simple_sources())
    assert cfg.proof_opts == ProofOptsSpec()
    # Default proof_opts are NOT written to yaml (all defaults)
    data = load_yaml(root / "project.yaml")
    assert "proof_opts" not in data


def test_parent_dirs_created(tmp_path: Path):
    """Intermediate parent directories are created automatically."""
    root = tmp_path / "deep" / "nested" / "proj"
    create_project("demo", root, sources=_simple_sources())
    _assert_dir_tree_minimal(root)


# --------------------------------------------------------------------------- #
# hygiene: no real data leak
# --------------------------------------------------------------------------- #

def test_no_real_tesla_data_in_templates():
    """AGENTS.md / README templates must not contain real tesla paths."""
    from garden_core.project.create import _AGENTS_MD_TEMPLATE, _README_MD_TEMPLATE

    for text in [_AGENTS_MD_TEMPLATE, _README_MD_TEMPLATE]:
        assert "20260611" not in text
        assert "DJI_20260611" not in text
        assert "N:\\\\20260611" not in text


def test_no_real_tesla_data_in_create_module():
    """create.py source must not contain real tesla paths."""
    src = (Path(__file__).parent.parent / "src" / "garden_core" / "project" / "create.py").read_text(encoding="utf-8")
    assert "20260611" not in src
    assert "DJI_20260611" not in src
    assert "N:\\\\" not in src

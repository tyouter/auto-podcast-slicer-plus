"""T9: load_project tests — load + validate + strict file-existence checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from garden_core.config import ConfigError
from garden_core.project import (
    CutPointSpec,
    ProjectConfig,
    ProjectMeta,
    SourceSpec,
    TranscriptSpec,
    create_project,
    load_project,
    validate,
)
from garden_core.project.schema import RenderOptsSpec


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _simple_sources() -> list[SourceSpec]:
    return [SourceSpec(id="SRC1", path="source/ep01.mp4")]


def _write_project_yaml(root: Path, data: dict) -> None:
    """Write a project.yaml to *root*."""
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "project.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


# --------------------------------------------------------------------------- #
# acceptance 1: reachability
# --------------------------------------------------------------------------- #

def test_load_project_is_importable():
    """load_project is reachable from garden_core.project."""
    from garden_core.project import load_project as lp
    assert callable(lp)


# --------------------------------------------------------------------------- #
# acceptance 2: create → load 闭环 (strict=False)
# --------------------------------------------------------------------------- #

def test_create_then_load_semantic_equivalence(tmp_path: Path):
    """After create_project, load_project(strict=False) returns a config
    whose path fields are resolved to absolute (relative to root)."""
    root = tmp_path / "myproj"
    cfg_create = create_project("demo", root, sources=_simple_sources())

    cfg_load = load_project(root, strict=False)

    # meta
    assert cfg_load.meta.name == cfg_create.meta.name
    assert cfg_load.meta.root == str(root.resolve())  # always absolute

    # sources: id/timeline/offset equal; path resolved to absolute
    assert len(cfg_load.sources) == len(cfg_create.sources)
    for s_load, s_create in zip(cfg_load.sources, cfg_create.sources):
        assert s_load.id == s_create.id
        assert s_load.timeline_start_s == s_create.timeline_start_s
        assert s_load.timeline_end_s == s_create.timeline_end_s
        assert s_load.source_offset_s == s_create.source_offset_s
        # create wrote relative; load resolves to absolute
        resolved = (root.resolve() / s_create.path).resolve()
        assert s_load.path == str(resolved)

    # transcript
    assert cfg_load.transcript.audio_path == str(
        (root.resolve() / cfg_create.transcript.audio_path).resolve()
    )
    assert cfg_load.transcript.path == str(
        (root.resolve() / cfg_create.transcript.path).resolve()
    )

    # errata_path
    assert cfg_load.errata_path == str(
        (root.resolve() / cfg_create.errata_path).resolve()
    )

    # style_name / render_opts.output_dir / output_dir
    assert cfg_load.style_name == cfg_create.style_name
    assert cfg_load.render_opts.output_dir == str(
        (root.resolve() / cfg_create.render_opts.output_dir).resolve()
    )
    assert cfg_load.output_dir == str(
        (root.resolve() / cfg_create.output_dir).resolve()
    )

    # cut_points empty
    assert cfg_load.cut_points == ()


# --------------------------------------------------------------------------- #
# acceptance 3: 传文件路径 == 传根目录
# --------------------------------------------------------------------------- #

def test_file_path_equals_directory_path(tmp_path: Path):
    """load_project(yaml_file) and load_project(root_dir) return equal configs."""
    root = tmp_path / "myproj"
    create_project("demo", root, sources=_simple_sources())

    cfg_from_dir = load_project(root, strict=False)
    cfg_from_file = load_project(root / "project.yaml", strict=False)

    assert cfg_from_file == cfg_from_dir


# --------------------------------------------------------------------------- #
# acceptance 4: 手写 tesla 形状 yaml 能 load
# --------------------------------------------------------------------------- #

def test_handwritten_multi_source_yaml_loads(tmp_path: Path):
    """A hand-written multi-source + cut_points + style yaml loads correctly."""
    data = {
        "meta": {"name": "handwritten", "root": str(tmp_path.resolve())},
        "sources": [
            {"id": "SRC1", "path": "source/part1.mp4",
             "timeline_start_s": 0.0, "timeline_end_s": 850.0},
            {"id": "SRC2", "path": "source/part2.mp4",
             "timeline_start_s": 850.0, "timeline_end_s": 1294.0,
             "source_offset_s": 850.0},
        ],
        "transcript": {"audio_path": "source/audio.wav", "path": "output/transcript.json"},
        "errata_path": "corrections.yaml",
        "cut_points": [
            {"clip_id": "t01", "source": "SRC1", "start_s": 0.0, "end_s": 35.0},
            {"clip_id": "t02", "source": "SRC1", "start_s": 75.0, "end_s": 110.0},
            {"clip_id": "t03", "source": "SRC2", "start_s": 860.0, "end_s": 915.0},
        ],
        "style_name": "default",
        "output_dir": "output",
    }
    _write_project_yaml(tmp_path, data)

    cfg = load_project(tmp_path, strict=False)

    assert cfg.meta.name == "handwritten"
    assert len(cfg.sources) == 2
    assert cfg.sources[0].id == "SRC1"
    assert cfg.sources[0].path == str(tmp_path.resolve() / "source" / "part1.mp4")
    assert cfg.sources[1].id == "SRC2"
    assert cfg.sources[1].source_offset_s == 850.0
    assert cfg.sources[1].path == str(tmp_path.resolve() / "source" / "part2.mp4")

    assert len(cfg.cut_points) == 3
    assert cfg.cut_points[0].clip_id == "t01"
    assert cfg.cut_points[0].source == "SRC1"
    assert cfg.cut_points[2].source == "SRC2"

    assert cfg.style_name == "default"
    assert cfg.output_dir == str(tmp_path.resolve() / "output")


# --------------------------------------------------------------------------- #
# acceptance 5: strict=False 不查文件
# --------------------------------------------------------------------------- #

def test_strict_false_does_not_check_files(tmp_path: Path):
    """strict=False succeeds even when no file exists on disk (except yaml)."""
    root = tmp_path / "nofiles"
    create_project("demo", root, sources=_simple_sources())
    # source media / transcript / audio don't exist — only corrections.yaml does
    cfg = load_project(root, strict=False)
    assert cfg.meta.name == "demo"


# --------------------------------------------------------------------------- #
# acceptance 6: strict=True 缺文件聚合报错
# --------------------------------------------------------------------------- #

def test_strict_true_missing_files_aggregated(tmp_path: Path):
    """strict=True reports ALL missing files in one ConfigError."""
    root = tmp_path / "missingfiles"
    create_project("demo", root, sources=_simple_sources())
    # source/ep01.mp4, source/demo.wav, output/transcript.json are missing
    # corrections.yaml exists (created by create_project)

    with pytest.raises(ConfigError) as exc_info:
        load_project(root, strict=True)

    msg = str(exc_info.value)
    assert "strict=True" in msg
    # Should mention missing source
    assert "SRC1" in msg
    assert "source.path" in msg
    # Should mention missing transcript paths
    assert "transcript.audio_path" in msg
    assert "transcript.path" in msg
    # corrections.yaml exists → NOT in the error
    assert "errata_path" not in msg


def test_strict_true_passes_when_all_files_exist(tmp_path: Path):
    """strict=True succeeds after all required files are touched."""
    root = tmp_path / "allfiles"
    create_project("demo", root, sources=_simple_sources())

    # Touch all required files
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "source" / "ep01.mp4").write_text("fake media")
    (root / "source" / "demo.wav").write_text("fake audio")
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "output" / "transcript.json").write_text("{}")

    cfg = load_project(root, strict=True)
    assert cfg.meta.name == "demo"


# --------------------------------------------------------------------------- #
# acceptance 7: strict=True 缺什么报什么（单项缺失）
# --------------------------------------------------------------------------- #

def test_strict_true_reports_only_missing_item(tmp_path: Path):
    """When only one file is missing, only that file is listed."""
    root = tmp_path / "onemissing"
    create_project("demo", root, sources=_simple_sources())

    # Touch all except transcript.path
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "source" / "ep01.mp4").write_text("fake media")
    (root / "source" / "demo.wav").write_text("fake audio")
    (root / "output").mkdir(parents=True, exist_ok=True)
    # transcript.json NOT created

    with pytest.raises(ConfigError) as exc_info:
        load_project(root, strict=True)

    msg = str(exc_info.value)
    assert "transcript.path" in msg
    # None of the other files should be mentioned
    assert "source.path" not in msg
    assert "transcript.audio_path" not in msg
    assert "errata_path" not in msg


# --------------------------------------------------------------------------- #
# acceptance 8: 非法 yaml 报 ConfigError (bad source reference)
# --------------------------------------------------------------------------- #

def test_bad_source_reference_in_cut_points_raises(tmp_path: Path):
    """A cut_point referencing a non-existent source → ConfigError."""
    data = {
        "meta": {"name": "badref", "root": str(tmp_path.resolve())},
        "sources": [{"id": "SRC1", "path": "source/v.mp4"}],
        "transcript": {"audio_path": "source/a.wav", "path": "output/t.json"},
        "cut_points": [
            {"clip_id": "t01", "source": "NOPE", "start_s": 0, "end_s": 10},
        ],
    }
    _write_project_yaml(tmp_path, data)

    with pytest.raises(ConfigError) as exc_info:
        load_project(tmp_path, strict=False)

    assert "NOPE" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# acceptance 9: 缺必填字段报 ConfigError
# --------------------------------------------------------------------------- #

def test_missing_transcript_block_raises_config_error(tmp_path: Path):
    """YAML without 'transcript' key → ConfigError (wrapped KeyError)."""
    data = {
        "meta": {"name": "notrans", "root": str(tmp_path.resolve())},
        "sources": [{"id": "SRC1", "path": "source/v.mp4"}],
        # no 'transcript' key
    }
    _write_project_yaml(tmp_path, data)

    with pytest.raises(ConfigError):
        load_project(tmp_path, strict=False)


def test_missing_source_id_raises_config_error(tmp_path: Path):
    """A source entry missing 'id' → ConfigError (wrapped KeyError)."""
    data = {
        "meta": {"name": "nosrcid", "root": str(tmp_path.resolve())},
        "sources": [{"path": "source/v.mp4"}],  # no 'id'
        "transcript": {"audio_path": "a.wav", "path": "t.json"},
    }
    _write_project_yaml(tmp_path, data)

    with pytest.raises(ConfigError):
        load_project(tmp_path, strict=False)


# --------------------------------------------------------------------------- #
# acceptance 10: 路径不存在报 ConfigError
# --------------------------------------------------------------------------- #

def test_nonexistent_path_raises(tmp_path: Path):
    """A path that doesn't exist → ConfigError."""
    with pytest.raises(ConfigError, match="does not exist"):
        load_project(tmp_path / "nonexistent", strict=False)


def test_file_that_is_not_yaml_or_directory(tmp_path: Path):
    """A regular file that is not valid yaml mapping → ConfigError."""
    f = tmp_path / "README.md"
    f.write_text("just a readme")
    with pytest.raises(ConfigError, match="not a mapping"):
        load_project(f, strict=False)


def test_directory_without_project_yaml_raises(tmp_path: Path):
    """A directory without project.yaml → ConfigError."""
    d = tmp_path / "emptydir"
    d.mkdir()
    with pytest.raises(ConfigError, match="does not contain.*project.yaml"):
        load_project(d, strict=False)


# --------------------------------------------------------------------------- #
# acceptance 11: diff 范围检查（在此文件中做白盒验证）
# --------------------------------------------------------------------------- #

def test_load_py_does_not_import_create_or_modify_schema():
    """load.py should only import config/schema symbols, not modify them."""
    import garden_core.project.load as load_mod
    src = (Path(__file__).parent.parent / "src" / "garden_core" / "project" / "load.py").read_text(encoding="utf-8")
    # Should not define any dataclass or type that duplicates schema.py
    assert "class ProjectConfig" not in src
    assert "class SourceSpec" not in src
    assert "class TranscriptSpec" not in src
    # Should not import create_project
    assert "create_project" not in src
    # Should import from config and schema
    assert "from garden_core.project.config import" in src
    assert "from garden_core.project.schema import" in src


# --------------------------------------------------------------------------- #
# additional tests
# --------------------------------------------------------------------------- #

def test_empty_yaml_file_raises(tmp_path: Path):
    """An empty project.yaml → ConfigError."""
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_project(p, strict=False)


def test_yaml_with_only_comments_raises(tmp_path: Path):
    """A yaml file with only comments → effectively empty → ConfigError."""
    p = tmp_path / "comments.yaml"
    p.write_text("# just a comment\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_project(p, strict=False)


def test_relative_meta_root_resolved_to_absolute(tmp_path: Path, monkeypatch):
    """When meta.root is relative, it is resolved against cwd."""
    data = {
        "meta": {"name": "relroot", "root": "."},
        "sources": [{"id": "SRC1", "path": "source/v.mp4"}],
        "transcript": {"audio_path": "a.wav", "path": "t.json"},
    }
    _write_project_yaml(tmp_path, data)

    # Change cwd to tmp_path so "." resolves to tmp_path
    monkeypatch.chdir(tmp_path)

    cfg = load_project(tmp_path, strict=False)
    assert cfg.meta.root == str(tmp_path.resolve())
    assert cfg.sources[0].path == str((tmp_path.resolve() / "source" / "v.mp4").resolve())


def test_already_absolute_paths_kept_as_is(tmp_path: Path):
    """Paths that are already absolute in the yaml stay absolute."""
    abs_source = str(tmp_path.resolve() / "media" / "vid.mp4")
    abs_audio = str(tmp_path.resolve() / "media" / "aud.wav")
    abs_transcript = str(tmp_path.resolve() / "out" / "t.json")

    data = {
        "meta": {"name": "abspaths", "root": str(tmp_path.resolve())},
        "sources": [{"id": "SRC1", "path": abs_source}],
        "transcript": {"audio_path": abs_audio, "path": abs_transcript},
    }
    _write_project_yaml(tmp_path, data)

    cfg = load_project(tmp_path, strict=False)
    assert cfg.sources[0].path == str(Path(abs_source).resolve())
    assert cfg.transcript.audio_path == str(Path(abs_audio).resolve())
    assert cfg.transcript.path == str(Path(abs_transcript).resolve())


def test_strict_true_errata_missing_reported(tmp_path: Path):
    """When errata file is missing and strict=True, it is reported."""
    data = {
        "meta": {"name": "noerrata", "root": str(tmp_path.resolve())},
        "sources": [{"id": "SRC1", "path": "source/v.mp4"}],
        "transcript": {"audio_path": "source/a.wav", "path": "output/t.json"},
        "errata_path": "nonexistent_errata.yaml",
    }
    _write_project_yaml(tmp_path, data)

    # Touch other files so only errata is missing
    (tmp_path / "source").mkdir(parents=True, exist_ok=True)
    (tmp_path / "source" / "v.mp4").write_text("fake")
    (tmp_path / "source" / "a.wav").write_text("fake")
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output" / "t.json").write_text("{}")

    with pytest.raises(ConfigError) as exc_info:
        load_project(tmp_path, strict=True)

    assert "errata_path" in str(exc_info.value)


def test_strict_false_skips_validate_on_bad_structure(tmp_path: Path):
    """strict=False still runs validate — bad structure is caught regardless."""
    data = {
        "meta": {"name": "badstruct", "root": str(tmp_path.resolve())},
        "sources": [],  # empty sources → validate error
        "transcript": {"audio_path": "a.wav", "path": "t.json"},
    }
    _write_project_yaml(tmp_path, data)

    with pytest.raises(ConfigError, match="at least one entry"):
        load_project(tmp_path, strict=False)


def test_load_preserves_non_path_fields(tmp_path: Path):
    """Non-path fields like proof_opts, render_opts dimensions round-trip correctly."""
    data = {
        "meta": {"name": "full", "root": str(tmp_path.resolve())},
        "sources": [{"id": "SRC1", "path": "source/v.mp4"}],
        "transcript": {"audio_path": "source/a.wav", "path": "output/t.json"},
        "proof_opts": {"enable_llm": True, "llm_temperature": 0.5},
        "style_name": "fresh",
        "render_opts": {
            "horizontal_width": 1920,
            "horizontal_height": 1080,
            "crf": 20,
        },
        "output_dir": "my_output",
    }
    _write_project_yaml(tmp_path, data)

    cfg = load_project(tmp_path, strict=False)
    assert cfg.proof_opts.enable_llm is True
    assert cfg.proof_opts.llm_temperature == 0.5
    assert cfg.style_name == "fresh"
    assert cfg.render_opts.horizontal_width == 1920
    assert cfg.render_opts.horizontal_height == 1080
    assert cfg.render_opts.crf == 20
    assert cfg.output_dir == str(tmp_path.resolve() / "my_output")


# --------------------------------------------------------------------------- #
# hygiene: no real tesla data
# --------------------------------------------------------------------------- #

def test_no_real_tesla_data_in_load_module():
    """load.py source must not contain real tesla paths."""
    src = (Path(__file__).parent.parent / "src" / "garden_core" / "project" / "load.py").read_text(encoding="utf-8")
    assert "20260611" not in src
    assert "DJI_20260611" not in src
    assert "N:\\\\" not in src

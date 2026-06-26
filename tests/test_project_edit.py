"""T10: edit_project tests — modify project.yaml + re-validate + persist.

Covers all 14 acceptance criteria from the T10 brief.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from garden_core.config import ConfigError, load_yaml
from garden_core.project import (
    CutPointSpec,
    ProjectConfig,
    ProofOptsSpec,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
    create_project,
    edit_project,
    load_project,
)
from garden_core.project.schema import ProjectMeta


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _simple_sources() -> list[SourceSpec]:
    return [SourceSpec(id="SRC1", path="source/ep01.mp4")]


def _create_demo_project(root: Path) -> ProjectConfig:
    """Scaffold a demo project and return its config."""
    return create_project("demo", root, sources=_simple_sources())


# --------------------------------------------------------------------------- #
# acceptance 1: reachability
# --------------------------------------------------------------------------- #

def test_edit_project_is_importable():
    """edit_project is reachable from garden_core.project."""
    from garden_core.project import edit_project as ep
    assert callable(ep)


# --------------------------------------------------------------------------- #
# acceptance 2: top-level scalar overrides
# --------------------------------------------------------------------------- #

def test_edit_scalar_style_name(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    cfg = edit_project(root, style_name="fresh")
    assert cfg.style_name == "fresh"

    # Disk check
    data = load_yaml(root / "project.yaml")
    assert data.get("style_name") == "fresh"

    # load_project sees it too
    cfg_load = load_project(root, strict=False)
    assert cfg_load.style_name == "fresh"


def test_edit_scalar_errata_path(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    cfg = edit_project(root, errata_path="other.yaml")
    assert cfg.errata_path == "other.yaml"

    data = load_yaml(root / "project.yaml")
    assert data.get("errata_path") == "other.yaml"


def test_edit_scalar_output_dir(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    cfg = edit_project(root, output_dir="out")
    assert cfg.output_dir == "out"

    data = load_yaml(root / "project.yaml")
    assert data.get("output_dir") == "out"


def test_edit_multiple_scalars_at_once(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    cfg = edit_project(
        root,
        style_name="default",
        errata_path="custom_errata.yaml",
        output_dir="build",
    )
    assert cfg.style_name == "default"
    assert cfg.errata_path == "custom_errata.yaml"
    assert cfg.output_dir == "build"


# --------------------------------------------------------------------------- #
# acceptance 3: nested spec partial merge
# --------------------------------------------------------------------------- #

def test_edit_nested_partial_merge_render_opts(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg = edit_project(root, render_opts={"crf": 20, "render_vertical": False})

    assert cfg.render_opts.crf == 20
    assert cfg.render_opts.render_vertical is False
    # Other fields stay at their create defaults
    assert cfg.render_opts.horizontal_width == 3840  # 4K default from create
    assert cfg.render_opts.horizontal_height == 2160
    assert cfg.render_opts.render_horizontal is True

    # Disk yaml reflects changes
    data = load_yaml(root / "project.yaml")
    ro = data.get("render_opts", {})
    assert ro.get("crf") == 20
    assert ro.get("render_vertical") is False


def test_edit_nested_partial_merge_proof_opts(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg = edit_project(root, proof_opts={"enable_llm": True, "llm_temperature": 0.5})

    assert cfg.proof_opts.enable_llm is True
    assert cfg.proof_opts.llm_temperature == 0.5
    assert cfg.proof_opts.enable_normalize is True  # unchanged from default


def test_edit_nested_partial_merge_meta(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg = edit_project(root, meta={"name": "renamed-project"})

    assert cfg.meta.name == "renamed-project"
    # root stays as-is
    assert cfg.meta.root == str(root.resolve())


# --------------------------------------------------------------------------- #
# acceptance 4: nested spec full replace (instance)
# --------------------------------------------------------------------------- #

def test_edit_nested_full_replace_proof_opts(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    new_po = ProofOptsSpec(enable_llm=True, enable_normalize=False)
    cfg = edit_project(root, proof_opts=new_po)

    assert cfg.proof_opts == new_po
    assert cfg.proof_opts.enable_llm is True
    assert cfg.proof_opts.enable_normalize is False
    # Other fields at ProofOptsSpec defaults
    assert cfg.proof_opts.enable_errata is True
    assert cfg.proof_opts.llm_temperature == 0.1


def test_edit_nested_full_replace_render_opts(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    new_ro = RenderOptsSpec(crf=30, horizontal_width=1280, horizontal_height=720)
    cfg = edit_project(root, render_opts=new_ro)

    assert cfg.render_opts == new_ro
    assert cfg.render_opts.crf == 30


# --------------------------------------------------------------------------- #
# acceptance 5: collection full replace (tuple/list, elements instance or dict)
# --------------------------------------------------------------------------- #

def test_edit_collection_sources_full_replace(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    new_sources = (
        SourceSpec(id="SRC2", path="source/b.mp4"),
    )
    cfg = edit_project(root, sources=new_sources, cut_points=())

    assert len(cfg.sources) == 1
    assert cfg.sources[0].id == "SRC2"
    assert cfg.cut_points == ()


def test_edit_collection_cut_points_dict_elements(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg = edit_project(
        root,
        cut_points=[
            {"clip_id": "t01", "source": "SRC1", "start_s": 0.0, "end_s": 10.0},
        ],
    )

    assert len(cfg.cut_points) == 1
    cp = cfg.cut_points[0]
    assert cp.clip_id == "t01"
    assert cp.source == "SRC1"
    assert cp.start_s == 0.0
    assert cp.end_s == 10.0
    assert cp.style_name == "default"
    assert cp.title == ""

    # Disk yaml
    data = load_yaml(root / "project.yaml")
    cps = data.get("cut_points", [])
    assert len(cps) == 1


def test_edit_collection_sources_from_dict_elements(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg = edit_project(
        root,
        sources=[{"id": "SRC_NEW", "path": "source/new.mp4"}],
        cut_points=(),
    )

    assert len(cfg.sources) == 1
    assert cfg.sources[0].id == "SRC_NEW"


def test_edit_collection_full_replace_is_not_append(tmp_path: Path):
    """edit_project collections are full-replace, not append."""
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Original has 1 source. Pass 2 — they replace fully.
    cfg = edit_project(
        root,
        sources=[
            SourceSpec(id="A", path="source/a.mp4"),
            SourceSpec(id="B", path="source/b.mp4"),
        ],
        cut_points=(),
    )

    assert len(cfg.sources) == 2
    assert {s.id for s in cfg.sources} == {"A", "B"}


# --------------------------------------------------------------------------- #
# acceptance 6: validate-before-write (disk untouched on error)
# --------------------------------------------------------------------------- #

def test_edit_bad_source_ref_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Record original project.yaml content
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="NOPE"):
        edit_project(
            root,
            cut_points=[
                {"clip_id": "t01", "source": "NOPE", "start_s": 0.0, "end_s": 10.0},
            ],
        )

    # Disk unchanged
    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_out_of_bounds_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # First, add a source with explicit timeline_end_s and a cut_point within bounds
    cfg0 = edit_project(
        root,
        sources=(
            SourceSpec(id="SRC1", path="source/ep01.mp4", timeline_start_s=0.0, timeline_end_s=100.0),
        ),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=10.0, end_s=50.0),
        ),
    )
    assert cfg0.sources[0].timeline_end_s == 100.0

    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="exceeds"):
        edit_project(
            root,
            cut_points=[
                {"clip_id": "t01", "source": "SRC1", "start_s": 0.0, "end_s": 200.0},
            ],
        )

    # Disk unchanged
    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_start_not_less_than_end_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="start_s.*>=.*end_s"):
        edit_project(
            root,
            cut_points=[
                {"clip_id": "t01", "source": "SRC1", "start_s": 50.0, "end_s": 50.0},
            ],
        )

    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_start_greater_than_end_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="start_s.*>=.*end_s"):
        edit_project(
            root,
            cut_points=[
                {"clip_id": "t01", "source": "SRC1", "start_s": 100.0, "end_s": 50.0},
            ],
        )

    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_duplicate_clip_id_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="duplicate clip_id"):
        edit_project(
            root,
            cut_points=[
                {"clip_id": "dup", "source": "SRC1", "start_s": 0.0, "end_s": 5.0},
                {"clip_id": "dup", "source": "SRC1", "start_s": 5.0, "end_s": 10.0},
            ],
        )

    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_unknown_style_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="style_name.*not found"):
        edit_project(root, style_name="not_a_style_xyz")

    assert (root / "project.yaml").read_bytes() == original_bytes


# --------------------------------------------------------------------------- #
# acceptance 7: remove source referenced by cut_point → validate catches it
# --------------------------------------------------------------------------- #

def test_edit_remove_referenced_source_blocked_by_validate(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Add a second source and a cut_point referencing it
    cfg = edit_project(
        root,
        sources=(
            SourceSpec(id="SRC1", path="source/a.mp4"),
            SourceSpec(id="SRC2", path="source/b.mp4"),
        ),
        cut_points=[
            {"clip_id": "t01", "source": "SRC2", "start_s": 0.0, "end_s": 5.0},
        ],
    )
    assert len(cfg.sources) == 2

    # Now try to remove SRC2 while keeping the cut_point → validate should block
    with pytest.raises(ConfigError, match="t01.*references source.*SRC2"):
        edit_project(
            root,
            sources=(
                SourceSpec(id="SRC1", path="source/a.mp4"),
            ),
        )

    # Disk still has the 2-source version
    data = load_yaml(root / "project.yaml")
    assert len(data["sources"]) == 2


# --------------------------------------------------------------------------- #
# acceptance 8: typo guard — unknown override key
# --------------------------------------------------------------------------- #

def test_edit_unknown_override_key_raises(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    with pytest.raises(ConfigError, match="Unknown override key.*stlye_name"):
        edit_project(root, stlye_name="fresh")


def test_edit_unknown_override_key_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError, match="Unknown override key"):
        edit_project(root, not_a_field=123)

    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_valid_keys_list_in_error_message(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    with pytest.raises(ConfigError, match="valid keys"):
        edit_project(root, foo="bar")


# --------------------------------------------------------------------------- #
# acceptance 9: protect data files — edit only touches project.yaml
# --------------------------------------------------------------------------- #

def test_edit_protects_data_files(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Create extra data files
    (root / "source").mkdir(exist_ok=True)
    source_file = root / "source" / "ep01.mp4"
    source_file.write_bytes(b"fake media content")

    output_marker = root / "output" / "marker.txt"
    output_marker.parent.mkdir(parents=True, exist_ok=True)
    output_marker.write_text("keep me")

    agends_content = (root / "AGENTS.md").read_text()
    readme_content = (root / "README.md").read_text()
    corrections_content = (root / "corrections.yaml").read_text()
    # project.yaml exists from create

    # Run several edits
    edit_project(root, style_name="fresh")
    edit_project(root, errata_path="renamed.yaml")
    edit_project(root, output_dir="out")

    # All data files still there and unchanged
    assert source_file.read_bytes() == b"fake media content"
    assert output_marker.read_text() == "keep me"
    assert (root / "AGENTS.md").read_text() == agends_content
    assert (root / "README.md").read_text() == readme_content
    assert (root / "corrections.yaml").read_text() == corrections_content

    # project.yaml was changed (style_name, errata_path, output_dir)
    data = load_yaml(root / "project.yaml")
    assert data.get("style_name") == "fresh"
    assert data.get("errata_path") == "renamed.yaml"
    assert data.get("output_dir") == "out"


# --------------------------------------------------------------------------- #
# acceptance 10: edit does NOT check file existence
# --------------------------------------------------------------------------- #

def test_edit_succeeds_without_media_files(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # No source media, no transcript.json — edit should still work
    cfg = edit_project(root, style_name="default")
    assert cfg.style_name == "default"


def test_edit_succeeds_when_source_path_does_not_exist(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Change to a non-existent source path
    cfg = edit_project(
        root,
        sources=(SourceSpec(id="SRC1", path="source/nonexistent.mp4"),),
        cut_points=(),
    )
    assert cfg.sources[0].path == "source/nonexistent.mp4"


# --------------------------------------------------------------------------- #
# acceptance 11: project.yaml does not exist → ConfigError
# --------------------------------------------------------------------------- #

def test_edit_nonexistent_directory_raises(tmp_path: Path):
    nonexistent = tmp_path / "nope"

    with pytest.raises(ConfigError, match="does not exist.*create_project"):
        edit_project(nonexistent)


def test_edit_directory_without_project_yaml_raises(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(ConfigError, match="does not contain.*project.yaml"):
        edit_project(empty_dir)


def test_edit_project_yaml_deleted_after_create_raises(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    (root / "project.yaml").unlink()

    with pytest.raises(ConfigError, match="does not contain.*project.yaml"):
        edit_project(root)


def test_edit_can_accept_yaml_file_path_directly(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Pass the yaml file directly (not the directory)
    cfg = edit_project(root / "project.yaml", style_name="fresh")
    assert cfg.style_name == "fresh"


# --------------------------------------------------------------------------- #
# acceptance 12: atomic write — no leftover tmp file
# --------------------------------------------------------------------------- #

def test_edit_no_leftover_tmp_file(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    edit_project(root, style_name="fresh")

    assert not (root / "project.yaml.tmp").exists()
    assert (root / "project.yaml").exists()

    # Verify it's valid yaml
    data = load_yaml(root / "project.yaml")
    assert isinstance(data, dict)
    assert data.get("style_name") == "fresh"


def test_edit_tmp_cleaned_up_on_write_error(tmp_path: Path):
    """If _atomic_write encounters an error after writing tmp, the tmp file
    is cleaned up on a best-effort basis."""
    root = tmp_path / "proj"
    _create_demo_project(root)

    from garden_core.project.edit import _atomic_write

    yaml_path = root / "project.yaml"
    cfg = ProjectConfig.from_dict(load_yaml(yaml_path))

    # Simulate write error by using a read-only directory for the tmp location
    # Actually, just test that _atomic_write cleans up its own tmp on error
    # by patching os.replace to fail after tmp is written.
    import garden_core.project.edit as edit_mod

    original_replace = os.replace

    def failing_replace(src, dst):
        raise OSError("simulated disk full")

    # Patch os.replace to fail, so _atomic_write will attempt cleanup
    # Note: this is a narrow test of _atomic_write's error path
    try:
        os.replace = failing_replace  # type: ignore[assignment]
        with pytest.raises(OSError, match="simulated disk full"):
            _atomic_write(cfg, yaml_path)
    finally:
        os.replace = original_replace  # type: ignore[assignment]

    # tmp should be cleaned up (best-effort in _atomic_write)
    assert not (root / "project.yaml.tmp").exists()

    # Original project.yaml still intact
    data = load_yaml(root / "project.yaml")
    assert isinstance(data, dict)


# --------------------------------------------------------------------------- #
# acceptance 13: round-trip equivalence (config view vs runtime view)
# --------------------------------------------------------------------------- #

def test_edit_then_load_semantic_equivalence(tmp_path: Path):
    """After edit_project, load_project(strict=False) returns a config whose
    path fields are absolute, but all non-path fields match the edit result."""
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg_edit = edit_project(
        root,
        style_name="default",
        errata_path="my_errata.yaml",
        render_opts={"crf": 22},
        cut_points=[
            {"clip_id": "t01", "source": "SRC1", "start_s": 5.0, "end_s": 15.0},
        ],
    )

    cfg_load = load_project(root, strict=False)

    # meta
    assert cfg_load.meta.name == cfg_edit.meta.name
    assert cfg_load.meta.root == str(root.resolve())

    # sources: id/timeline/offset equal; path resolved to absolute in load view
    assert len(cfg_load.sources) == len(cfg_edit.sources)
    for s_load, s_edit in zip(cfg_load.sources, cfg_edit.sources):
        assert s_load.id == s_edit.id
        assert s_load.timeline_start_s == s_edit.timeline_start_s
        assert s_load.timeline_end_s == s_edit.timeline_end_s
        assert s_load.source_offset_s == s_edit.source_offset_s
        # load resolves to absolute; edit keeps as written
        resolved = (root.resolve() / s_edit.path).resolve()
        assert s_load.path == str(resolved)

    # transcript
    assert cfg_load.transcript.audio_path == str(
        (root.resolve() / cfg_edit.transcript.audio_path).resolve()
    )
    assert cfg_load.transcript.path == str(
        (root.resolve() / cfg_edit.transcript.path).resolve()
    )

    # errata_path
    assert cfg_load.errata_path == str(
        (root.resolve() / cfg_edit.errata_path).resolve()
    )

    # style_name matches
    assert cfg_load.style_name == cfg_edit.style_name

    # render_opts (non-path fields match; output_dir is path in load view)
    assert cfg_load.render_opts.crf == cfg_edit.render_opts.crf  # 22
    assert cfg_load.render_opts.horizontal_width == cfg_edit.render_opts.horizontal_width
    assert cfg_load.render_opts.output_dir == str(
        (root.resolve() / cfg_edit.render_opts.output_dir).resolve()
    )

    # output_dir
    assert cfg_load.output_dir == str(
        (root.resolve() / cfg_edit.output_dir).resolve()
    )

    # cut_points match (no path fields)
    assert cfg_load.cut_points == cfg_edit.cut_points

    # proof_opts match (no path fields)
    assert cfg_load.proof_opts == cfg_edit.proof_opts


# --------------------------------------------------------------------------- #
# acceptance 14: no regression — existing tests still green
# (tested separately via pytest tests/ -v)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# edge cases
# --------------------------------------------------------------------------- #

def test_edit_empty_overrides_is_noop(tmp_path: Path):
    """edit_project with no overrides returns a config equal to the original
    and does not change project.yaml content."""
    root = tmp_path / "proj"
    _create_demo_project(root)

    original_bytes = (root / "project.yaml").read_bytes()

    cfg = edit_project(root)
    # Should be semantically equivalent to re-reading
    cfg2 = ProjectConfig.from_dict(load_yaml(root / "project.yaml"))
    assert cfg == cfg2

    # Disk unchanged
    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_overwrite_and_reread_roundtrip(tmp_path: Path):
    """edit then re-read via edit_project yields identical config."""
    root = tmp_path / "proj"
    _create_demo_project(root)

    cfg1 = edit_project(
        root,
        style_name="fresh",
        errata_path="e.yaml",
        output_dir="out",
        render_opts={"crf": 25},
        proof_opts={"enable_llm": True},
    )
    cfg2 = edit_project(root)

    assert cfg1 == cfg2


def test_edit_nested_spec_dict_invalid_field_raises(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    with pytest.raises(ConfigError, match="Cannot apply override.*render_opts"):
        edit_project(root, render_opts={"not_a_field": 123})


def test_edit_nested_spec_dict_invalid_field_preserves_disk(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)
    original_bytes = (root / "project.yaml").read_bytes()

    with pytest.raises(ConfigError):
        edit_project(root, proof_opts={"bad_key": True})

    assert (root / "project.yaml").read_bytes() == original_bytes


def test_edit_collection_element_wrong_type_raises(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    with pytest.raises(ConfigError, match="Collection element must be"):
        edit_project(root, sources=["not_a_dict_or_spec", 123])


def test_edit_collection_override_not_tuple_or_list_raises(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    with pytest.raises(ConfigError, match="must be a tuple or list"):
        edit_project(root, sources="not_a_collection")


def test_edit_nested_override_not_spec_or_dict_raises(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    with pytest.raises(ConfigError, match="must be a ProofOptsSpec instance or a dict"):
        edit_project(root, proof_opts=42)


def test_edit_preserves_relative_paths_on_disk(tmp_path: Path):
    """After edit, paths written to project.yaml should remain relative
    (when originally relative)."""
    root = tmp_path / "proj"
    _create_demo_project(root)

    edit_project(root, style_name="fresh")

    data = load_yaml(root / "project.yaml")
    # Sources path was written as relative by create_project
    assert data["sources"][0]["path"] == "source/ep01.mp4"
    # Transcript paths
    assert data["transcript"]["audio_path"].startswith("source/")
    # errata_path
    assert data.get("errata_path", "corrections.yaml") == "corrections.yaml"
    # meta.root should be absolute (create_project resolves it)
    assert Path(data["meta"]["root"]).is_absolute()


def test_edit_does_not_alter_mtime_of_other_files(tmp_path: Path):
    root = tmp_path / "proj"
    _create_demo_project(root)

    # Record mtimes of non-project.yaml files
    mtimes = {}
    for p in root.rglob("*"):
        if p.is_file() and p.name != "project.yaml":
            mtimes[p] = p.stat().st_mtime

    # Slight delay to ensure any mtime change would be detectable
    time.sleep(0.1)

    edit_project(root, style_name="fresh")

    for p, old_mtime in mtimes.items():
        assert p.stat().st_mtime == old_mtime, f"{p.name} mtime changed!"


# --------------------------------------------------------------------------- #
# sanity: edit_project does NOT import load_project (Q2/A)
# --------------------------------------------------------------------------- #

def test_edit_module_does_not_import_load_project():
    """edit.py must not import load_project to avoid path resolution (Q2/A).
    It may mention 'load_project' in prose (docstrings, comments) but must not
    have a functional import of the load module."""
    src = (Path(__file__).parent.parent / "src" / "garden_core" / "project" / "edit.py").read_text()
    # Check that there is no import of the load module
    assert "from garden_core.project.load" not in src
    assert "import garden_core.project.load" not in src

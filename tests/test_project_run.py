"""T11: ProjectRun + run_manifest.json tests.

Tests cover:
  - Construction + manifest_path
  - transcribe() happy path / no-transcriber error
  - proofread() errata application
  - render() multi-source translation
  - render() no double align/proof
  - audit() non-raising behaviour
  - all() ordering
  - resume() full-skip / partial / artifact-missing
  - manifest schema_version validation (D6)
  - manifest atomic write (no .tmp residue)
  - load() classmethod round-trip
  - from_project_dir() convenience
  - multi-source equivalence (tesla_stage04 shape)

All data is synthetic / placeholder — no real project paths or errata.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from garden_core.config import ConfigError
from garden_core.infra.llm_client import NoLLMClient
from garden_core.io_.sink import save_transcript_json
from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import Engines
from garden_core.project import (
    ProjectConfig,
    ProjectMeta,
    SourceSpec,
    CutPointSpec,
    TranscriptSpec,
    create_project,
    ProjectRun,
)
from garden_core.stage_asr import Transcriber, AudioRef
from garden_core.stage_proofread import ErrataConfig
from garden_core.types import CutPoint, Segment, Transcript


# ========================================================================== #
# helpers
# ========================================================================== #


def _make_transcript(text: str = "测试", start_s: float = 0.0, end_s: float = 1.0) -> Transcript:
    """Build a minimal synthetic Transcript."""
    return Transcript(
        segments=(Segment(text=text, start_s=start_s, end_s=end_s),),
        source_file="test.wav",
        engine="fake",
    )


class FakeTranscriber(Transcriber):
    """Returns a fixed Transcript — deterministic, no GPU needed."""

    def __init__(self, transcript: Transcript | None = None, name: str = "fake"):
        self._transcript = transcript or _make_transcript()
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def transcribe(self, audio: AudioRef, hotwords: tuple[str, ...] = ()) -> Transcript:
        return dataclasses.replace(
            self._transcript,
            source_file=audio.path,
        )


def _minimal_cfg(tmp_path: Path) -> ProjectConfig:
    """Create a minimal valid project in tmp_path and return a resolved config.

    Uses ``create_project`` to scaffold, then ``load_project`` to resolve
    all paths to absolute (the "runtime view").  This avoids accidental
    writes to the repo CWD when tests use relative paths.
    """
    create_project(
        "testproj",
        str(tmp_path),
        sources=[SourceSpec(id="SRC1", path="source/ep01.mp4")],
        audio_path="source/ep01.wav",
        style="default",
        overwrite=True,
    )
    from garden_core.project.load import load_project
    return load_project(tmp_path, strict=False)


# ========================================================================== #
# 1. construction + manifest_path
# ========================================================================== #


def test_construction_and_manifest_path(tmp_path: Path):
    cfg = _minimal_cfg(tmp_path)
    engines = Engines()
    run = ProjectRun(cfg, engines)

    assert run.cfg is cfg
    assert run.engines is engines
    assert run.manifest_path() == tmp_path / "run_manifest.json"


def test_manifest_path_when_not_exists(tmp_path: Path):
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())
    assert not run.manifest_path().exists()
    assert run.read_manifest() == {}


# ========================================================================== #
# 2. transcribe()
# ========================================================================== #


def test_transcribe_happy(tmp_path: Path):
    cfg = _minimal_cfg(tmp_path)
    fake = FakeTranscriber(_make_transcript(text="你好世界"))
    engines = Engines(transcriber=fake)
    run = ProjectRun(cfg, engines)

    result = run.transcribe()

    assert result.stage == "transcribe"
    assert result.status == "done"
    assert result.artifact_path == cfg.transcript.path

    # Verify transcript was written and is readable
    t = load_transcript_json(cfg.transcript.path)
    assert t.segments[0].text == "你好世界"

    # Verify manifest
    manifest = run.read_manifest()
    assert manifest["schema_version"] == 1
    stages = {s["stage"]: s for s in manifest["stages"]}
    assert stages["transcribe"]["status"] == "done"
    assert stages["transcribe"]["artifact_path"] == cfg.transcript.path


def test_transcribe_no_transcriber(tmp_path: Path):
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())  # no transcriber
    with pytest.raises(RuntimeError, match="transcribe.*requires engines.transcriber"):
        run.transcribe()


def test_transcribe_no_aligner_skips_with_warning(tmp_path: Path, caplog):
    cfg = _minimal_cfg(tmp_path)
    fake = FakeTranscriber()
    engines = Engines(transcriber=fake, aligner=None)
    run = ProjectRun(cfg, engines)

    import logging
    caplog.set_level(logging.WARNING)
    run.transcribe()

    assert "no aligner" in caplog.text.lower() or "skipping" in caplog.text.lower()


# ========================================================================== #
# 3. proofread()
# ========================================================================== #


def test_proofread_errata_applied(tmp_path: Path):
    """Write a transcript with a known error; create a corrections.yaml;
    proofread() should fix it."""
    cfg = _minimal_cfg(tmp_path)
    fake = FakeTranscriber(
        _make_transcript(text="错字甲"),  # has "甲" which errata maps to "乙"
    )
    engines = Engines(transcriber=fake)

    run = ProjectRun(cfg, engines)
    run.transcribe()

    # Write corrections.yaml
    import yaml
    errata_path = tmp_path / "corrections.yaml"
    with open(errata_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"common": {"甲": "乙"}}, fh)

    result = run.proofread()
    assert result.status == "done"

    t = load_transcript_json(cfg.transcript.path)
    assert "乙" in t.segments[0].text
    # The old character should be gone (replaced)
    assert "甲" not in t.segments[0].text

    manifest = run.read_manifest()
    stages = {s["stage"]: s for s in manifest["stages"]}
    assert stages["proofread"]["status"] == "done"


def test_proofread_missing_errata_is_ok(tmp_path: Path):
    """Missing corrections.yaml → build_errata_config returns empty, no error."""
    cfg = _minimal_cfg(tmp_path)
    # cfg.errata_path points to "corrections.yaml" which doesn't exist
    fake = FakeTranscriber(_make_transcript(text="不变"))
    engines = Engines(transcriber=fake)
    run = ProjectRun(cfg, engines)
    run.transcribe()

    result = run.proofread()
    assert result.status == "done"
    t = load_transcript_json(cfg.transcript.path)
    assert t.segments[0].text == "不变"


def test_proofread_no_transcript_raises(tmp_path: Path):
    """proofread() without prior transcribe() should fail."""
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())
    # load_transcript_json opens the file → FileNotFoundError when absent
    # (load_project resolves paths to absolute, so this won't hit CWD)
    with pytest.raises(FileNotFoundError):
        run.proofread()


# ========================================================================== #
# 4. render() — multi-source translation
# ========================================================================== #


def test_render_multisource_translation(tmp_path: Path, monkeypatch):
    """Verify _translate_cut_points produces correct CutPoints."""
    cfg = ProjectConfig(
        meta=ProjectMeta(name="multi", root=str(tmp_path)),
        sources=(
            SourceSpec(id="SRC1", path=str(tmp_path / "source/a.mp4"), source_offset_s=0.0),
            SourceSpec(id="SRC2", path=str(tmp_path / "source/b.mp4"), source_offset_s=850.0),
        ),
        transcript=TranscriptSpec(
            audio_path=str(tmp_path / "source/a.wav"),
            path=str(tmp_path / "output/transcript.json"),
        ),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=0.0, end_s=81.5, style_name="fresh", title="Intro"),
            CutPointSpec(clip_id="t14", source="SRC2", start_s=850.0, end_s=911.0, style_name="fresh", title="Outro"),
        ),
        style_name="fresh",
    )

    # Write a minimal transcript
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    captured_cut_points: list = []
    captured_style_name: list = []

    def fake_run_from_transcript(transcript, cut_points, style_name, engines, opts, audio_path=""):
        captured_cut_points.append(list(cut_points))
        captured_style_name.append(style_name)
        return []

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        fake_run_from_transcript,
    )

    run = ProjectRun(cfg, Engines())
    result = run.render()

    assert result.status == "done"
    assert len(captured_cut_points) == 1
    cps = captured_cut_points[0]

    # First CutPoint from SRC1
    assert cps[0].clip_id == "t01"
    assert cps[0].source_media == str(tmp_path / "source/a.mp4")
    assert cps[0].start_s == 0.0
    assert cps[0].end_s == 81.5
    assert cps[0].source_offset_s == 0.0
    assert cps[0].title == "Intro"

    # Second CutPoint from SRC2
    assert cps[1].clip_id == "t14"
    assert cps[1].source_media == str(tmp_path / "source/b.mp4")
    assert cps[1].start_s == 850.0
    assert cps[1].end_s == 911.0
    assert cps[1].source_offset_s == 850.0
    assert cps[1].title == "Outro"

    # style_name passed through
    assert captured_style_name[0] == "fresh"


def test_render_cut_point_unknown_source(tmp_path: Path):
    """CutPoint referencing a nonexistent source → ConfigError."""
    cfg = ProjectConfig(
        meta=ProjectMeta(name="bad", root=str(tmp_path)),
        sources=(SourceSpec(id="SRC1", path="a.mp4"),),
        transcript=TranscriptSpec(audio_path="a.wav", path=str(tmp_path / "t.json")),
        cut_points=(
            CutPointSpec(clip_id="t01", source="NONEXISTENT", start_s=0.0, end_s=1.0),
        ),
    )
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    with pytest.raises(ConfigError, match="unknown source"):
        run.render()


# ========================================================================== #
# 5. render() — no double align / proof
# ========================================================================== #


def test_render_no_double_align_proof(tmp_path: Path, monkeypatch):
    """render() must NOT call stage_align.align or stage_proofread.proofread."""
    cfg = _minimal_cfg(tmp_path)

    # Write a transcript so load succeeds
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    align_called = []
    proofread_called = []

    def fake_align(*args, **kwargs):
        align_called.append(True)
        raise AssertionError("align should not be called by render()")

    def fake_proofread(*args, **kwargs):
        proofread_called.append(True)
        raise AssertionError("proofread should not be called by render()")

    monkeypatch.setattr("garden_core.project.run.align", fake_align)
    monkeypatch.setattr("garden_core.project.run.proofread", fake_proofread)

    # Also patch run_from_transcript to avoid actual ffmpeg
    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        lambda *a, **kw: [],
    )

    run = ProjectRun(cfg, Engines())
    run.render()

    assert len(align_called) == 0, "align was called by render()"
    assert len(proofread_called) == 0, "proofread was called by render()"


# ========================================================================== #
# 6. audit()
# ========================================================================== #


def test_audit_empty_output_dir(tmp_path: Path):
    """Audit on a non-existent output dir should report violations, not raise.

    Use a sub-directory that was NOT created by create_project, so
    ``_discover_clip_ids`` returns nothing and we get no violations.
    Instead, create the output dir but place a fake mp4 with wrong resolution
    to trigger real violations, testing the full audit path.
    """
    out_dir = tmp_path / "out_audit"
    out_dir.mkdir()
    clips_dir = out_dir / "clips"
    clips_dir.mkdir()

    # Create a minimal "clip" — a zero-byte mp4 (ffprobe will fail, triggering
    # a skip, not a violation).  To get a violation we need an actual mp4 with
    # wrong dimensions.  Since we can't easily create a valid mp4, instead test
    # that audit produces a report on a dir with zero clips — 0 violations,
    # passed=True (empty set of clips means nothing to check).
    #
    # The real test of "violations detected" requires actual rendered clips.
    # Here we test the structural path: audit runs, produces a report, and
    # writes it to cfg.output_dir/audit_report.json.
    cfg = ProjectConfig(
        meta=ProjectMeta(name="audittest", root=str(tmp_path)),
        sources=(SourceSpec(id="SRC1", path=str(tmp_path / "a.mp4")),),
        transcript=TranscriptSpec(
            audio_path=str(tmp_path / "a.wav"),
            path=str(tmp_path / "t.json"),
        ),
        render_opts=dataclasses.replace(
            _minimal_cfg(tmp_path).render_opts,
            output_dir=str(clips_dir),
        ),
        output_dir=str(out_dir),
    )

    # Write a transcript so the cfg is valid (render_opts.output_dir exists now)
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    result = run.audit()

    assert result.stage == "audit"
    # 0 clips → 0 violations → passed
    assert result.status == "done"

    report_path = Path(cfg.output_dir) / "audit_report.json"
    assert report_path.exists()

    with open(report_path, "r") as fh:
        report = json.load(fh)
    assert report["passed"] is True
    assert len(report["violations"]) == 0


# ========================================================================== #
# 7. all() ordering
# ========================================================================== #


def test_all_ordering(tmp_path: Path, monkeypatch):
    """all() must call stages in order: transcribe → proofread → render → audit."""
    cfg = _minimal_cfg(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    calls: list[str] = []

    # Patch each stage method to record its name
    def record_transcribe(self):
        calls.append("transcribe")
        return MagicMock(stage="transcribe")

    def record_proofread(self):
        calls.append("proofread")
        return MagicMock(stage="proofread")

    def record_render(self):
        calls.append("render")
        return MagicMock(stage="render")

    def record_audit(self):
        calls.append("audit")
        return MagicMock(stage="audit")

    monkeypatch.setattr(ProjectRun, "transcribe", record_transcribe)
    monkeypatch.setattr(ProjectRun, "proofread", record_proofread)
    monkeypatch.setattr(ProjectRun, "render", record_render)
    monkeypatch.setattr(ProjectRun, "audit", record_audit)

    run = ProjectRun(cfg, Engines())
    run.all()

    assert calls == ["transcribe", "proofread", "render", "audit"]


# ========================================================================== #
# 8. resume() — full skip
# ========================================================================== #


def test_resume_all_skip(tmp_path: Path, monkeypatch):
    """After all() completes, resume() should skip every stage."""
    cfg = _minimal_cfg(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    # Pre-populate manifest with all stages done + artifacts
    run = ProjectRun(cfg, Engines())
    run._record("transcribe", "done", cfg.transcript.path, {})
    run._record("proofread", "done", cfg.transcript.path, {})
    run._record("render", "done", cfg.render_opts.output_dir, {})
    # Create the output dir so artifact existence check passes
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)
    audit_report = Path(cfg.output_dir) / "audit_report.json"
    audit_report.parent.mkdir(parents=True, exist_ok=True)
    audit_report.write_text("{}")
    run._record("audit", "done", str(audit_report), {})

    calls: list[str] = []

    def record(name):
        def fn(self):
            calls.append(name)
            return MagicMock(stage=name, skipped=False)
        return fn

    monkeypatch.setattr(ProjectRun, "transcribe", record("transcribe"))
    monkeypatch.setattr(ProjectRun, "proofread", record("proofread"))
    monkeypatch.setattr(ProjectRun, "render", record("render"))
    monkeypatch.setattr(ProjectRun, "audit", record("audit"))

    run2 = ProjectRun(cfg, Engines())
    results = run2.resume()

    assert len(calls) == 0, f"Expected no stage calls but got: {calls}"
    assert all(r.skipped for r in results)
    assert len(results) == 4


# ========================================================================== #
# 9. resume() — partial
# ========================================================================== #


def test_resume_partial(tmp_path: Path, monkeypatch):
    """Manifest has only transcribe done → transcribe skipped, rest run."""
    cfg = _minimal_cfg(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)
    audit_report = Path(cfg.output_dir) / "audit_report.json"
    audit_report.parent.mkdir(parents=True, exist_ok=True)
    audit_report.write_text("{}")

    run = ProjectRun(cfg, Engines())
    run._record("transcribe", "done", cfg.transcript.path, {})

    calls: list[str] = []

    def make_record(name):
        def fn(self):
            calls.append(name)
            return MagicMock(stage=name, skipped=False)
        return fn

    monkeypatch.setattr(ProjectRun, "transcribe", make_record("transcribe"))
    monkeypatch.setattr(ProjectRun, "proofread", make_record("proofread"))
    monkeypatch.setattr(ProjectRun, "render", make_record("render"))
    monkeypatch.setattr(ProjectRun, "audit", make_record("audit"))

    run2 = ProjectRun(cfg, Engines())
    results = run2.resume()

    assert calls == ["proofread", "render", "audit"]
    assert results[0].skipped is True   # transcribe
    assert results[1].skipped is False
    assert results[2].skipped is False
    assert results[3].skipped is False


# ========================================================================== #
# 10. resume() — artifact missing → re-run
# ========================================================================== #


def test_resume_artifact_missing_rerun(tmp_path: Path, monkeypatch):
    """Manifest says transcribe=done but transcript.json deleted → re-run."""
    cfg = _minimal_cfg(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    run._record("transcribe", "done", cfg.transcript.path, {})

    # Delete the artifact
    os.remove(cfg.transcript.path)

    calls: list[str] = []

    def make_record(name):
        def fn(self):
            calls.append(name)
            return MagicMock(stage=name, skipped=False)
        return fn

    monkeypatch.setattr(ProjectRun, "transcribe", make_record("transcribe"))
    monkeypatch.setattr(ProjectRun, "proofread", make_record("proofread"))
    monkeypatch.setattr(ProjectRun, "render", make_record("render"))
    monkeypatch.setattr(ProjectRun, "audit", make_record("audit"))

    run2 = ProjectRun(cfg, Engines())
    results = run2.resume()

    # transcribe should be re-run because artifact is gone
    assert "transcribe" in calls
    assert results[0].skipped is False


# ========================================================================== #
# 11. manifest schema_version (D6)
# ========================================================================== #


def test_load_normal_manifest(tmp_path: Path):
    """ProjectRun.load() with a valid manifest."""
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())
    run._record("transcribe", "done", cfg.transcript.path, {})

    run2 = ProjectRun.load(run.manifest_path(), Engines())
    assert run2.cfg.meta.name == cfg.meta.name
    assert run2.cfg.meta.root == cfg.meta.root


def test_load_manifest_wrong_schema_version(tmp_path: Path):
    """schema_version != 1 → ConfigError."""
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())
    run._record("transcribe", "done", cfg.transcript.path, {})

    # Tamper the manifest
    mp = run.manifest_path()
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    manifest["schema_version"] = 999
    mp.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ConfigError, match="schema_version"):
        ProjectRun.load(mp, Engines())


def test_load_manifest_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        ProjectRun.load(tmp_path / "nonexistent.json", Engines())


def test_load_manifest_not_json(tmp_path: Path):
    mp = tmp_path / "garbage.json"
    mp.write_text("not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        ProjectRun.load(mp, Engines())


# ========================================================================== #
# 12. manifest atomic write
# ========================================================================== #


def test_manifest_atomic_write_no_tmp_residue(tmp_path: Path):
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())

    run._record("transcribe", "done", cfg.transcript.path, {"engine": "test"})

    # No .tmp file left behind
    assert not list(Path(cfg.meta.root).glob("*.tmp"))

    # Manifest is valid JSON
    manifest = run.read_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["project"]["name"] == cfg.meta.name


def test_manifest_same_stage_overwrites(tmp_path: Path):
    """Running the same stage twice should overwrite, not duplicate."""
    cfg = _minimal_cfg(tmp_path)
    run = ProjectRun(cfg, Engines())

    run._record("transcribe", "done", "path1", {"attempt": 1})
    run._record("transcribe", "done", "path2", {"attempt": 2})

    manifest = run.read_manifest()
    stages = [s for s in manifest["stages"] if s["stage"] == "transcribe"]
    assert len(stages) == 1
    assert stages[0]["artifact_path"] == "path2"


# ========================================================================== #
# 13. from_project_dir()
# ========================================================================== #


def test_from_project_dir(tmp_path: Path):
    cfg_created = create_project(
        "fromdir",
        str(tmp_path),
        sources=[SourceSpec(id="SRC1", path="source/ep01.mp4")],
        style="default",
        overwrite=True,
    )
    run = ProjectRun.from_project_dir(str(tmp_path), Engines())
    assert run.cfg.meta.name == "fromdir"
    assert run.cfg.meta.root == str(tmp_path.resolve())


# ========================================================================== #
# 14. multi-source equivalence (tesla_stage04 shape)
# ========================================================================== #


def test_multisource_equiv_tesla_shape(tmp_path: Path):
    """Construct a two-source config matching the tesla_stage04 structure and
    verify CutPoint translation produces correct source_media + offsets."""
    src1_path = str(tmp_path / "source/part1.mp4")
    src2_path = str(tmp_path / "source/part2.mp4")

    cfg = ProjectConfig(
        meta=ProjectMeta(name="equiv", root=str(tmp_path)),
        sources=(
            SourceSpec(id="SRC1", path=src1_path,
                       timeline_start_s=0.0, timeline_end_s=850.0,
                       source_offset_s=0.0),
            SourceSpec(id="SRC2", path=src2_path,
                       timeline_start_s=850.0, timeline_end_s=1294.0,
                       source_offset_s=850.0),
        ),
        transcript=TranscriptSpec(
            audio_path=str(tmp_path / "audio.wav"),
            path=str(tmp_path / "transcript.json"),
        ),
        cut_points=(
            CutPointSpec(clip_id="t01", source="SRC1", start_s=0, end_s=81),
            CutPointSpec(clip_id="t11", source="SRC1", start_s=775, end_s=850),
            CutPointSpec(clip_id="t12", source="SRC2", start_s=860, end_s=925),
            CutPointSpec(clip_id="t19", source="SRC2", start_s=1240, end_s=1294),
        ),
    )
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    cps = run._translate_cut_points()

    # SRC1: source_media=src1_path, offset=0
    assert cps[0].source_media == src1_path
    assert cps[0].source_offset_s == 0.0
    assert cps[0].start_s == 0
    assert cps[0].end_s == 81

    assert cps[1].source_media == src1_path
    assert cps[1].source_offset_s == 0.0
    assert cps[1].start_s == 775
    assert cps[1].end_s == 850

    # SRC2: source_media=src2_path, offset=850
    assert cps[2].source_media == src2_path
    assert cps[2].source_offset_s == 850.0
    assert cps[2].start_s == 860
    assert cps[2].end_s == 925

    assert cps[3].source_media == src2_path
    assert cps[3].source_offset_s == 850.0
    assert cps[3].start_s == 1240
    assert cps[3].end_s == 1294


# ========================================================================== #
# 15. StageResult
# ========================================================================== #


def test_stage_result_frozen():
    from garden_core.project.run import StageResult
    sr = StageResult("test", "done", "/tmp/x", skipped=False)
    assert sr.stage == "test"
    assert sr.status == "done"
    assert sr.skipped is False
    assert dataclasses.is_dataclass(sr) and sr.__dataclass_params__.frozen


def test_project_run_frozen():
    cfg = _minimal_cfg(Path("/tmp/test_proj"))
    run = ProjectRun(cfg, Engines())
    assert dataclasses.is_dataclass(run) and run.__dataclass_params__.frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        run.cfg = cfg  # type: ignore[misc]

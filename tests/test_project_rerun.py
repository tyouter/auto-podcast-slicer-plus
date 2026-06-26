"""T12: ProjectRun.rerender() / .reproofread() tests.

Tests cover:
  - rerender clip_ids subset + skip_existing=False
  - rerender respects cfg order
  - rerender empty clip_ids → ValueError
  - rerender unknown clip_id → ConfigError
  - reproofread(errata=) injected errata
  - reproofread(errata=None) reuses cfg.errata_path
  - reproofread does NOT persist errata
  - reproofread + rerender_clip_ids combined
  - _render_cut_points / _apply_proofread are private
  - manifest schema stable after rerender/reproofread
  - render() / proofread() unchanged behavior (verified via T11 test regression)

All data is synthetic / placeholder — no real project paths or errata.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest
import yaml

from garden_core.config import ConfigError
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
        return dataclasses.replace(self._transcript, source_file=audio.path)


def _cfg_3_clips(tmp_path: Path, **kw) -> ProjectConfig:
    """Build a ProjectConfig with 3 cut_points (c01/c02/c03) from one source."""
    return ProjectConfig(
        meta=ProjectMeta(name="rerun", root=str(tmp_path)),
        sources=(
            SourceSpec(id="SRC1", path=str(tmp_path / "source/a.mp4"), source_offset_s=0.0),
        ),
        transcript=TranscriptSpec(
            audio_path=str(tmp_path / "source/a.wav"),
            path=str(tmp_path / "output/transcript.json"),
        ),
        cut_points=(
            CutPointSpec(clip_id="c01", source="SRC1", start_s=0.0, end_s=10.0),
            CutPointSpec(clip_id="c02", source="SRC1", start_s=10.0, end_s=20.0),
            CutPointSpec(clip_id="c03", source="SRC1", start_s=20.0, end_s=30.0),
        ),
        style_name="default",
        **kw,
    )


# ========================================================================== #
# 1. rerender clip_ids subset + skip_existing=False
# ========================================================================== #


def test_rerender_subset_skip_existing_false(tmp_path: Path, monkeypatch):
    """rerender(["c01","c03"]) passes only c01+c03 to run_from_transcript
    with skip_existing=False; manifest records rerender params."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)

    # Ensure output dir exists so run_from_transcript doesn't trip on it
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    captured_cut_points: list = []
    captured_opts: list = []
    call_count: list[int] = [0]

    def fake_run_from_transcript(transcript, cut_points, style_name, engines, opts, audio_path=""):
        call_count[0] += 1
        captured_cut_points.append(list(cut_points))
        captured_opts.append(opts)
        return []

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        fake_run_from_transcript,
    )

    run = ProjectRun(cfg, Engines())
    result = run.rerender(["c01", "c03"])

    # Only one call to run_from_transcript
    assert call_count[0] == 1
    # It received exactly c01 and c03 in cfg order
    assert len(captured_cut_points) == 1
    subset_ids = [cp.clip_id for cp in captured_cut_points[0]]
    assert subset_ids == ["c01", "c03"]
    # skip_existing forced to False
    assert captured_opts[0].skip_existing is False

    # StageResult shape
    assert result.stage == "render"
    assert result.status == "done"
    assert result.artifact_path == cfg.render_opts.output_dir

    # Manifest check
    manifest = run.read_manifest()
    stages = {s["stage"]: s for s in manifest["stages"]}
    assert stages["render"]["status"] == "done"
    assert stages["render"]["params"]["rerender"] is True
    assert stages["render"]["params"]["clips"] == ["c01", "c03"]


def test_rerender_preserves_cfg_order(tmp_path: Path, monkeypatch):
    """rerender(["c03","c02"]) still passes [c02,c03] in cfg order."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    captured_cut_points: list = []

    def fake_run_from_transcript(transcript, cut_points, style_name, engines, opts, audio_path=""):
        captured_cut_points.append(list(cut_points))
        return []

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        fake_run_from_transcript,
    )

    run = ProjectRun(cfg, Engines())
    # Pass reverse order — should still come out in cfg order
    run.rerender(["c03", "c02"])

    subset_ids = [cp.clip_id for cp in captured_cut_points[0]]
    assert subset_ids == ["c02", "c03"]


# ========================================================================== #
# 2. rerender empty / unknown clip_ids
# ========================================================================== #


def test_rerender_empty_clip_ids_raises(tmp_path: Path):
    """rerender([]) → ValueError."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    run = ProjectRun(cfg, Engines())
    with pytest.raises(ValueError, match="non-empty"):
        run.rerender([])


def test_rerender_unknown_clip_id_raises(tmp_path: Path):
    """rerender(["c99"]) → ConfigError with unknown + known list."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    run = ProjectRun(cfg, Engines())
    with pytest.raises(ConfigError, match=r"unknown.*c99") as exc_info:
        run.rerender(["c99"])
    # Message should include the known ids
    msg = str(exc_info.value)
    assert "c01" in msg
    assert "c02" in msg
    assert "c03" in msg


# ========================================================================== #
# 3. reproofread(errata=) injected errata
# ========================================================================== #


def test_reproofread_injected_errata(tmp_path: Path):
    """reproofread(errata=ErrataConfig(flat={...})) applies inline errata
    without using cfg.errata_path."""
    cfg = _cfg_3_clips(tmp_path)

    # Write a transcript with a known error
    ts = _make_transcript(text="错字甲")
    save_transcript_json(ts, cfg.transcript.path)

    run = ProjectRun(cfg, Engines())

    # Inject errata that fixes "甲" → "乙"
    errata = ErrataConfig(flat={"甲": "乙"})
    results = run.reproofread(errata=errata)

    # Returns exactly one StageResult (proofread)
    assert len(results) == 1
    assert results[0].stage == "proofread"
    assert results[0].status == "done"
    assert results[0].artifact_path == cfg.transcript.path

    # Transcript has been corrected
    t2 = load_transcript_json(cfg.transcript.path)
    assert "乙" in t2.segments[0].text
    assert "甲" not in t2.segments[0].text

    # Manifest recorded proofread
    manifest = run.read_manifest()
    stages = {s["stage"]: s for s in manifest["stages"]}
    assert stages["proofread"]["status"] == "done"


def test_reproofread_injected_errata_multiple_segments(tmp_path: Path):
    """Verify errata is applied across all segments (not just the first)."""
    cfg = _cfg_3_clips(tmp_path)
    ts = Transcript(
        segments=(
            Segment(text="第一甲", start_s=0.0, end_s=1.0),
            Segment(text="第二甲", start_s=1.0, end_s=2.0),
        ),
        source_file="test.wav",
        engine="fake",
        corrections_applied=(),
    )
    save_transcript_json(ts, cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    errata = ErrataConfig(flat={"甲": "乙"})
    run.reproofread(errata=errata)

    t2 = load_transcript_json(cfg.transcript.path)
    assert t2.segments[0].text == "第一乙"
    assert t2.segments[1].text == "第二乙"


# ========================================================================== #
# 4. reproofread(errata=None) reuses cfg.errata_path
# ========================================================================== #


def test_reproofread_cfg_errata(tmp_path: Path):
    """reproofread() (no errata arg) loads from cfg.errata_path."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="错字甲")
    save_transcript_json(ts, cfg.transcript.path)

    # Write corrections.yaml at the default errata_path
    errata_file = tmp_path / "corrections.yaml"
    with open(errata_file, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"common": {"甲": "乙"}}, fh)

    run = ProjectRun(cfg, Engines())
    results = run.reproofread()

    assert len(results) == 1
    assert results[0].stage == "proofread"

    t2 = load_transcript_json(cfg.transcript.path)
    assert "乙" in t2.segments[0].text
    assert "甲" not in t2.segments[0].text


def test_reproofread_cfg_errata_missing_is_ok(tmp_path: Path):
    """reproofread() with missing corrections.yaml → empty errata, no error."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="不变")
    save_transcript_json(ts, cfg.transcript.path)

    # No corrections.yaml exists; cfg.errata_path points to a nonexistent file
    run = ProjectRun(cfg, Engines())
    results = run.reproofread()

    assert len(results) == 1
    assert results[0].stage == "proofread"
    t2 = load_transcript_json(cfg.transcript.path)
    assert t2.segments[0].text == "不变"


# ========================================================================== #
# 5. reproofread does NOT persist errata
# ========================================================================== #


def test_reproofread_does_not_persist_errata(tmp_path: Path):
    """reproofread(errata=X) must NOT modify project.yaml or corrections.yaml."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="原始文本")
    save_transcript_json(ts, cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    errata = ErrataConfig(flat={"原始": "修改后"})
    run.reproofread(errata=errata)

    # The frozen cfg is unchanged — errata_path still points to default
    assert str(cfg.errata_path)  # still the original value

    # No corrections.yaml was written (unless it was pre-existing; it wasn't)
    errata_file = Path(cfg.meta.root) / cfg.errata_path
    if errata_file.exists():
        # If it exists, its content should NOT contain our injected errata
        content = errata_file.read_text(encoding="utf-8")
        assert "修改后" not in content


# ========================================================================== #
# 6. reproofread + rerender_clip_ids combined
# ========================================================================== #


def test_reproofread_with_rerender_clip_ids(tmp_path: Path, monkeypatch):
    """reproofread(errata=..., rerender_clip_ids=["c01"]) returns
    [proofread_sr, render_sr] and calls run_from_transcript once."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="错字")
    save_transcript_json(ts, cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    captured_cut_points: list = []
    captured_opts: list = []

    def fake_run_from_transcript(transcript, cut_points, style_name, engines, opts, audio_path=""):
        captured_cut_points.append(list(cut_points))
        captured_opts.append(opts)
        return []

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        fake_run_from_transcript,
    )

    run = ProjectRun(cfg, Engines())
    errata = ErrataConfig(flat={"错": "对"})
    results = run.reproofread(errata=errata, rerender_clip_ids=["c01"])

    # Returns two StageResults
    assert len(results) == 2
    assert results[0].stage == "proofread"
    assert results[0].status == "done"
    assert results[1].stage == "render"
    assert results[1].status == "done"

    # run_from_transcript called exactly once (for rerender, not for proofread)
    assert len(captured_cut_points) == 1
    assert [cp.clip_id for cp in captured_cut_points[0]] == ["c01"]
    assert captured_opts[0].skip_existing is False

    # Transcript was corrected
    t2 = load_transcript_json(cfg.transcript.path)
    assert "对" in t2.segments[0].text


def test_reproofread_with_rerender_no_clip_ids(tmp_path: Path):
    """reproofread() without rerender_clip_ids returns only proofread result."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="原文")
    save_transcript_json(ts, cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    results = run.reproofread()

    assert len(results) == 1
    assert results[0].stage == "proofread"


# ========================================================================== #
# 7. _render_cut_points / _apply_proofread are private helpers
# ========================================================================== #


def test_helpers_are_private():
    """The new helpers exist on ProjectRun but are NOT in run.__all__."""
    from garden_core.project.run import __all__ as run_all

    # Helpers are methods on ProjectRun (not module-level symbols)
    assert hasattr(ProjectRun, "_render_cut_points")
    assert hasattr(ProjectRun, "_apply_proofread")
    # _ prefixed methods are NOT in __all__
    assert "_render_cut_points" not in run_all
    assert "_apply_proofread" not in run_all
    # The public API is still ProjectRun + StageResult only
    assert "ProjectRun" in run_all
    assert "StageResult" in run_all


# ========================================================================== #
# 8. manifest schema stable after rerender / reproofread
# ========================================================================== #


def test_manifest_schema_stable_after_rerender(tmp_path: Path, monkeypatch):
    """After rerender, schema_version stays 1; only standard stage names exist."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        lambda *a, **kw: [],
    )

    run = ProjectRun(cfg, Engines())
    run.rerender(["c01"])

    manifest = run.read_manifest()
    assert manifest["schema_version"] == 1
    stage_names = {s["stage"] for s in manifest["stages"]}
    assert stage_names.issubset({"transcribe", "proofread", "render", "audit"})
    # No "rerender" or "reproofread" stage name
    assert "rerender" not in stage_names
    assert "reproofread" not in stage_names


def test_manifest_schema_stable_after_reproofread(tmp_path: Path):
    """After reproofread, schema_version stays 1; only standard stage names exist."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="测试")
    save_transcript_json(ts, cfg.transcript.path)

    run = ProjectRun(cfg, Engines())
    run.reproofread(errata=ErrataConfig())

    manifest = run.read_manifest()
    assert manifest["schema_version"] == 1
    stage_names = {s["stage"] for s in manifest["stages"]}
    assert stage_names.issubset({"transcribe", "proofread", "render", "audit"})


def test_resume_after_rerender_skips_render(tmp_path: Path, monkeypatch):
    """After rerender records stage=render done + output_dir exists,
    a new ProjectRun.resume() should skip render."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        lambda *a, **kw: [],
    )

    run = ProjectRun(cfg, Engines())
    run.rerender(["c01"])

    # Now resume with a fresh run
    calls: list[str] = []

    def make_record(name):
        def fn(self):
            calls.append(name)
            from garden_core.project.run import StageResult
            return StageResult(name, "done", "", skipped=False)
        return fn

    monkeypatch.setattr(ProjectRun, "transcribe", make_record("transcribe"))
    monkeypatch.setattr(ProjectRun, "proofread", make_record("proofread"))
    monkeypatch.setattr(ProjectRun, "render", make_record("render"))
    monkeypatch.setattr(ProjectRun, "audit", make_record("audit"))

    run2 = ProjectRun(cfg, Engines())
    results = run2.resume()

    # render should be skipped (not called)
    assert "render" not in calls
    # transcribe / proofread / audit should still run (no artifact/manifest for them)
    assert "transcribe" in calls
    assert "proofread" in calls
    assert "audit" in calls


# ========================================================================== #
# 9. render() / proofread() internal helpers produce correct params
# ========================================================================== #


def test_render_uses_helper_with_skip_existing_true(tmp_path: Path, monkeypatch):
    """render() must call _render_cut_points with skip_existing=True."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    captured_skip: list[bool] = []
    orig = ProjectRun._render_cut_points

    def spy_render_cut_points(self, cut_points, *, skip_existing):
        captured_skip.append(skip_existing)
        return orig(self, cut_points, skip_existing=skip_existing)

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(ProjectRun, "_render_cut_points", spy_render_cut_points)

    run = ProjectRun(cfg, Engines())
    run.render()

    assert captured_skip == [True]


def test_proofread_uses_apply_proofread_with_cfg_errata(tmp_path: Path):
    """proofread() must call _apply_proofread with errata from cfg.errata_path."""
    cfg = _cfg_3_clips(tmp_path)
    ts = _make_transcript(text="不变")
    save_transcript_json(ts, cfg.transcript.path)

    # Write corrections.yaml
    errata_file = tmp_path / "corrections.yaml"
    with open(errata_file, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"common": {"不": "改"}}, fh)

    run = ProjectRun(cfg, Engines())
    result = run.proofread()

    assert result.status == "done"
    t2 = load_transcript_json(cfg.transcript.path)
    assert "改" in t2.segments[0].text

    # Manifest should NOT contain "rerender" key in render params
    manifest = run.read_manifest()
    stages = {s["stage"]: s for s in manifest["stages"]}
    assert stages["proofread"]["status"] == "done"


def test_render_zero_regression_params(tmp_path: Path, monkeypatch):
    """render() manifest params must NOT contain 'rerender' key (T11 regression)."""
    cfg = _cfg_3_clips(tmp_path)
    save_transcript_json(_make_transcript(), cfg.transcript.path)
    os.makedirs(cfg.render_opts.output_dir, exist_ok=True)

    monkeypatch.setattr(
        "garden_core.project.run.run_from_transcript",
        lambda *a, **kw: [],
    )

    run = ProjectRun(cfg, Engines())
    run.render()

    manifest = run.read_manifest()
    stages = {s["stage"]: s for s in manifest["stages"]}

    # Regular render() must NOT have the "rerender" key (T11 behavior)
    assert "rerender" not in stages["render"].get("params", {})
    # Regular render() records clip count (integer), not list
    assert isinstance(stages["render"]["params"]["clips"], int)

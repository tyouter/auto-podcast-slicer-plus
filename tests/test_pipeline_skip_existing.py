"""T5 (D5): skip_existing — naive skip of already-rendered clips.

Tests the ``_maybe_skip`` helper and the ``_render_plans`` integration through
``PipelineOptions.skip_existing``.  No real ffmpeg — ``garden_core.pipeline.render``
is mocked so we assert whether the heavy render path was reached.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from garden_core.pipeline import (
    PipelineOptions,
    _maybe_skip,
    _render_plans,
)
from garden_core.stage_render import RenderOptions
from garden_core.types import ClipPlan, Cue, RenderResult


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _plan(clip_id: str = "c1", cues: tuple[Cue, ...] = ()) -> ClipPlan:
    if not cues:
        cues = (Cue(index=0, text="测试", start_s=0.0, end_s=2.0),)
    return ClipPlan(
        clip_id=clip_id,
        source_ref="v.mp4",
        start_s=0.0,
        end_s=10.0,
        cues=cues,
    )


def _render_opts(tmp_path, **kw) -> RenderOptions:
    return RenderOptions(output_dir=str(tmp_path), **kw)


def _touch(path: str) -> str:
    """Create an empty file (and its parent dirs) — returns *path* for chaining."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pass
    return path


# =========================================================================== #
# _maybe_skip (unit — no mock needed)
# =========================================================================== #

class TestMaybeSkip:
    def test_hit_both_orientations(self, tmp_path):
        plan = _plan("t01")
        ro = _render_opts(tmp_path)
        _touch(os.path.join(tmp_path, "t01_horizontal.mp4"))
        _touch(os.path.join(tmp_path, "t01_vertical.mp4"))

        result = _maybe_skip(plan, ro, "cinematic")
        assert result is not None
        assert result.clip_id == "t01"
        assert result.horizontal_mp4 == os.path.join(tmp_path, "t01_horizontal.mp4")
        assert result.vertical_mp4 == os.path.join(tmp_path, "t01_vertical.mp4")
        assert result.metadata["skipped"] is True
        assert result.metadata["style"] == "cinematic"
        assert result.metadata["cues"] == 1

    def test_miss_no_mp4(self, tmp_path):
        plan = _plan("t02")
        ro = _render_opts(tmp_path)
        assert _maybe_skip(plan, ro, "cinematic") is None

    def test_horizontal_only_enabled(self, tmp_path):
        plan = _plan("t03")
        ro = _render_opts(tmp_path, render_vertical=False)
        _touch(os.path.join(tmp_path, "t03_horizontal.mp4"))

        result = _maybe_skip(plan, ro, "cinematic")
        assert result is not None
        assert result.horizontal_mp4 == os.path.join(tmp_path, "t03_horizontal.mp4")
        assert result.vertical_mp4 == ""

    def test_vertical_missing_blocks_skip(self, tmp_path):
        plan = _plan("t04")
        ro = _render_opts(tmp_path)  # both enabled
        _touch(os.path.join(tmp_path, "t04_horizontal.mp4"))
        # no vertical mp4

        assert _maybe_skip(plan, ro, "cinematic") is None

    def test_wrong_naming_no_skip(self, tmp_path):
        """If the file is named t05.mp4 (not t05_horizontal.mp4), we must NOT skip."""
        plan = _plan("t05")
        ro = _render_opts(tmp_path)
        _touch(os.path.join(tmp_path, "t05.mp4"))  # wrong convention
        _touch(os.path.join(tmp_path, "t05_vertical.mp4"))

        # horizontal mp4 missing → no skip
        assert _maybe_skip(plan, ro, "cinematic") is None

    def test_srt_ass_filled_when_present(self, tmp_path):
        plan = _plan("t06")
        ro = _render_opts(tmp_path, render_vertical=False)
        _touch(os.path.join(tmp_path, "t06_horizontal.mp4"))
        _touch(os.path.join(tmp_path, "t06.srt"))
        _touch(os.path.join(tmp_path, "t06.ass"))

        result = _maybe_skip(plan, ro, "cinematic")
        assert result is not None
        assert result.srt_path == os.path.join(tmp_path, "t06.srt")
        assert result.ass_path == os.path.join(tmp_path, "t06.ass")

    def test_srt_ass_empty_when_missing(self, tmp_path):
        plan = _plan("t07")
        ro = _render_opts(tmp_path, render_vertical=False)
        _touch(os.path.join(tmp_path, "t07_horizontal.mp4"))
        # no srt/ass

        result = _maybe_skip(plan, ro, "cinematic")
        assert result is not None
        assert result.srt_path == ""
        assert result.ass_path == ""


# =========================================================================== #
# _render_plans integration (mock garden_core.pipeline.render)
# =========================================================================== #

class TestRenderPlansSkipExisting:
    def test_skip_hit_does_not_call_render(self, tmp_path):
        plan = _plan("t10")
        ro = _render_opts(tmp_path)
        _touch(os.path.join(tmp_path, "t10_horizontal.mp4"))
        _touch(os.path.join(tmp_path, "t10_vertical.mp4"))

        opts = PipelineOptions(render=ro, skip_existing=True)

        with patch("garden_core.pipeline.render") as mock_render:
            results = _render_plans((plan,), "cinematic", MagicMock(), opts)

        mock_render.assert_not_called()
        assert len(results) == 1
        assert results[0].metadata["skipped"] is True
        assert results[0].horizontal_mp4 == os.path.join(tmp_path, "t10_horizontal.mp4")

    def test_skip_miss_calls_render(self, tmp_path):
        plan = _plan("t11")
        ro = _render_opts(tmp_path)  # empty dir
        opts = PipelineOptions(render=ro, skip_existing=True)

        fake_result = RenderResult(
            clip_id="t11",
            horizontal_mp4=os.path.join(tmp_path, "t11_horizontal.mp4"),
            vertical_mp4=os.path.join(tmp_path, "t11_vertical.mp4"),
            srt_path=os.path.join(tmp_path, "t11.srt"),
            ass_path=os.path.join(tmp_path, "t11.ass"),
            metadata={"style": "cinematic", "cues": 1},
        )

        with patch("garden_core.pipeline.render", return_value=fake_result) as mock_render:
            results = _render_plans((plan,), "cinematic", MagicMock(), opts)

        mock_render.assert_called_once()
        assert len(results) == 1
        assert "skipped" not in results[0].metadata

    def test_explicit_false_never_skips(self, tmp_path):
        plan = _plan("t12")
        ro = _render_opts(tmp_path)
        _touch(os.path.join(tmp_path, "t12_horizontal.mp4"))
        _touch(os.path.join(tmp_path, "t12_vertical.mp4"))

        opts = PipelineOptions(render=ro, skip_existing=False)

        fake_result = RenderResult(
            clip_id="t12",
            horizontal_mp4=os.path.join(tmp_path, "t12_horizontal.mp4"),
            vertical_mp4=os.path.join(tmp_path, "t12_vertical.mp4"),
            srt_path="",
            ass_path="",
            metadata={"style": "cinematic", "cues": 1},
        )

        with patch("garden_core.pipeline.render", return_value=fake_result) as mock_render:
            results = _render_plans((plan,), "cinematic", MagicMock(), opts)

        mock_render.assert_called_once()
        assert len(results) == 1
        # even though files existed, we did NOT skip
        assert "skipped" not in results[0].metadata

    def test_default_is_true(self):
        opts = PipelineOptions()
        assert opts.skip_existing is True

    def test_no_render_options_skips_silently(self, tmp_path):
        """When opts.render is None, _render_plans skips the plan entirely
        (pre-existing behavior) — skip_existing is never reached."""
        plan = _plan("t13")
        opts = PipelineOptions(render=None, skip_existing=True)

        with patch("garden_core.pipeline.render") as mock_render:
            results = _render_plans((plan,), "cinematic", MagicMock(), opts)

        mock_render.assert_not_called()
        assert results == []

    def test_skip_does_not_throw(self, tmp_path):
        """Skipped clip returns a well-formed RenderResult, no exception."""
        plan = _plan("t14")
        ro = _render_opts(tmp_path)
        _touch(os.path.join(tmp_path, "t14_horizontal.mp4"))
        _touch(os.path.join(tmp_path, "t14_vertical.mp4"))

        opts = PipelineOptions(render=ro, skip_existing=True)

        with patch("garden_core.pipeline.render") as mock_render:
            results = _render_plans((plan,), "cinematic", MagicMock(), opts)

        mock_render.assert_not_called()
        r = results[0]
        # All fields present
        assert r.clip_id == "t14"
        assert r.horizontal_mp4  # non-empty
        assert r.vertical_mp4    # non-empty
        assert isinstance(r.srt_path, str)
        assert isinstance(r.ass_path, str)
        assert isinstance(r.metadata, dict)

    def test_mixed_skip_and_render(self, tmp_path):
        """First clip is pre-rendered, second is not — one skipped, one rendered."""
        p1 = _plan("t20")
        p2 = _plan("t21")
        ro = _render_opts(tmp_path)
        # Pre-render only t20
        _touch(os.path.join(tmp_path, "t20_horizontal.mp4"))
        _touch(os.path.join(tmp_path, "t20_vertical.mp4"))

        opts = PipelineOptions(render=ro, skip_existing=True)

        fake_r2 = RenderResult(
            clip_id="t21",
            horizontal_mp4=os.path.join(tmp_path, "t21_horizontal.mp4"),
            vertical_mp4=os.path.join(tmp_path, "t21_vertical.mp4"),
            srt_path="",
            ass_path="",
            metadata={"style": "cinematic", "cues": 1},
        )

        with patch("garden_core.pipeline.render", return_value=fake_r2) as mock_render:
            results = _render_plans((p1, p2), "cinematic", MagicMock(), opts)

        # render called exactly once (for t21)
        assert mock_render.call_count == 1
        assert len(results) == 2
        assert results[0].metadata["skipped"] is True
        assert "skipped" not in results[1].metadata

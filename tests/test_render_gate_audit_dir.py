r"""Tests for render_gate.audit_dir() — directory-level mechanical audit.

Covers all four check categories + skipped handling + clip_id discovery +
equivalence with check_ass_pair + regression safety.
"""

from __future__ import annotations

import json
import os
import re
from unittest.mock import patch

import pytest

from garden_core.infra.media_probe import MediaInfo
from garden_core.stage_render.ass_writer import build_ass
from garden_core.stage_render.render_gate import (
    AuditReport,
    GateViolation,
    RenderGateError,
    audit_dir,
    check_ass_pair,
)
from garden_core.stage_style.molds import YamlStyleResolver
from garden_core.types import ClipPlan, Cue


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _style():
    return YamlStyleResolver().resolve("cinematic", 1080)


def _clip(clip_id: str = "c1", text: str = "主体性是关键") -> ClipPlan:
    return ClipPlan(
        clip_id=clip_id,
        source_ref="v.mp4",
        start_s=0.0,
        end_s=10.0,
        cues=(Cue(index=0, text=text, start_s=0.0, end_s=2.0),),
    )


def _ass_pair(style, clip):
    h = build_ass(clip, style, video_height=1080)
    v = build_ass(clip, style, video_height=1920, video_width=1080)
    return h, v


def _inject_fontsize(ass: str, new_size: int) -> str:
    return re.sub(r"(Style: Default,[^,]*,)\d+", r"\g<1>" + str(new_size), ass, count=1)


def _write_files(tmp_path, cid: str, h_mp4: bool = True, v_mp4: bool = True,
                 h_ass: str | None = None, v_ass: str | None = None):
    """Write clip artifacts into tmp_path.  Returns (h_ass_text, v_ass_text) if given."""
    if h_mp4:
        (tmp_path / f"{cid}_horizontal.mp4").write_text("fake mp4")
    if v_mp4:
        (tmp_path / f"{cid}_vertical.mp4").write_text("fake mp4")
    if h_ass is not None:
        (tmp_path / f"{cid}.ass").write_text(h_ass, encoding="utf-8")
    if v_ass is not None:
        (tmp_path / f"{cid}_vertical.ass").write_text(v_ass, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. Empty dir — passes
# --------------------------------------------------------------------------- #

def test_empty_dir_passes():
    """Empty directory → no violations, report.passed == True, no raise."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = audit_dir(d, raise_on_fail=False)
        assert r.passed
        assert r.violations == []
        assert r.skipped == []


# --------------------------------------------------------------------------- #
# 2. Missing file violations
# --------------------------------------------------------------------------- #

def test_missing_file_horizontal_mp4(tmp_path):
    _write_files(tmp_path, "c1", h_mp4=False, v_mp4=True,
                 h_ass="fake", v_ass="fake")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    dims = {v.dimension for v in r.violations}
    assert "missing_file" in dims
    h_violations = [v for v in r.violations
                    if v.dimension == "missing_file" and v.orientation == "horizontal"]
    assert len(h_violations) >= 1
    assert any("H_MP4" in v.detail for v in h_violations)


def test_missing_file_vertical_mp4(tmp_path):
    _write_files(tmp_path, "c1", h_mp4=True, v_mp4=False,
                 h_ass="fake", v_ass="fake")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    v_violations = [v for v in r.violations
                    if v.dimension == "missing_file" and v.orientation == "vertical"]
    assert len(v_violations) >= 1
    assert any("V_MP4" in v.detail for v in v_violations)


def test_missing_file_horizontal_ass(tmp_path):
    _write_files(tmp_path, "c1", h_mp4=True, v_mp4=True,
                 h_ass=None, v_ass="fake")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    h_violations = [v for v in r.violations
                    if v.dimension == "missing_file" and v.orientation == "horizontal"]
    assert any("H_ASS" in v.detail for v in h_violations)


def test_missing_file_not_flagged_when_orientation_disabled(tmp_path):
    """When render_vertical=False, missing vertical files are not violations."""
    _write_files(tmp_path, "c1", h_mp4=True, v_mp4=False, h_ass="fake")
    r = audit_dir(str(tmp_path), render_vertical=False, raise_on_fail=False)
    # No missing_file for vertical
    v_violations = [v for v in r.violations
                    if v.dimension == "missing_file" and v.orientation == "vertical"]
    assert v_violations == []


# --------------------------------------------------------------------------- #
# 3. zero_cues violations
# --------------------------------------------------------------------------- #

def test_zero_cues(tmp_path):
    """An ASS file with zero Dialogue: lines → zero_cues violation."""
    ass_no_cues = (
        "[Script Info]\n"
        "PlayResX: 1920\nPlayResY: 1080\n"
        "Style: Default,Arial,84,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n"
        "[Events]\n"
    )
    _write_files(tmp_path, "c1", h_mp4=True, v_mp4=True,
                 h_ass=ass_no_cues, v_ass=ass_no_cues)
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    zero_violations = [v for v in r.violations if v.dimension == "zero_cues"]
    # Should have at least horizontal zero_cues
    assert len(zero_violations) >= 1
    assert any(v.orientation == "horizontal" for v in zero_violations)


def test_zero_cues_only_on_existing_files(tmp_path):
    """Missing ASS files don't produce zero_cues (they're missing_file instead)."""
    _write_files(tmp_path, "c1", h_mp4=True, v_mp4=True,
                 h_ass=None, v_ass="[Script Info]\nPlayResX: 1080\nPlayResY: 1920\nStyle: Default,Arial,84,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n[Events]\n")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    # Horizontal ASS missing → missing_file, not zero_cues
    zero_h = [v for v in r.violations
              if v.dimension == "zero_cues" and v.orientation == "horizontal"]
    assert zero_h == []
    # Vertical ASS exists but has no cues → zero_cues
    zero_v = [v for v in r.violations
              if v.dimension == "zero_cues" and v.orientation == "vertical"]
    assert len(zero_v) == 1


# --------------------------------------------------------------------------- #
# 4. ASS gate (font_ratio / safe_area) — reuses check_ass_pair
# --------------------------------------------------------------------------- #

def test_ass_gate_font_ratio_bug(tmp_path):
    """The old vertical-font-too-big bug is caught by audit_dir's ASS gate."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    bug_fs = round(style.font_size_ratio * 1920)
    v_bug = _inject_fontsize(v, bug_fs)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v_bug)
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    ass_violations = [v for v in r.violations if v.dimension in ("font_ratio", "safe_area")]
    assert len(ass_violations) >= 1
    assert any(v.dimension == "font_ratio" for v in ass_violations)


def test_ass_gate_safe_area_bug(tmp_path):
    """margin_v=0 on vertical canvas → safe_area violation caught."""
    style, clip = _style(), _clip("c1")
    _, v = _ass_pair(style, clip)
    line = next(l for l in v.splitlines() if l.startswith("Style: Default,"))
    parts = line.split(",")
    parts[-2] = "0"
    v_bad = v.replace(line, ",".join(parts))
    _write_files(tmp_path, "c1", h_ass=v_bad, v_ass=v_bad)  # both get margin_v=0
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    ass_violations = [v for v in r.violations if v.dimension in ("font_ratio", "safe_area")]
    assert any(v.dimension == "safe_area" for v in ass_violations)


def test_ass_gate_happy_path_passes(tmp_path):
    """Correct ASS files → no ASS gate violations."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    ass_violations = [v for v in r.violations if v.dimension in ("font_ratio", "safe_area")]
    assert ass_violations == []


# --------------------------------------------------------------------------- #
# 5. Resolution violations (mocked probe_media)
# --------------------------------------------------------------------------- #

def test_resolution_mismatch_horizontal(tmp_path):
    """Horizontal mp4 with wrong resolution → resolution violation."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    bad_info = MediaInfo(width=1920, height=1080, duration_s=10.0,
                         fps=30.0, has_audio=True)

    with patch("garden_core.stage_render.render_gate.probe_media",
               return_value=bad_info), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), raise_on_fail=False, ffprobe_bin="ffprobe")
    res_violations = [v for v in r.violations if v.dimension == "resolution"]
    assert len(res_violations) >= 1
    h_res = [v for v in res_violations if v.orientation == "horizontal"]
    assert len(h_res) == 1
    assert h_res[0].expected == "3840x2160"
    assert h_res[0].actual == "1920x1080"


def test_resolution_mismatch_vertical(tmp_path):
    """Vertical mp4 with wrong resolution → resolution violation."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    good_h = MediaInfo(width=3840, height=2160, duration_s=10.0,
                       fps=30.0, has_audio=True)
    bad_v = MediaInfo(width=1080, height=1080, duration_s=10.0,
                      fps=30.0, has_audio=True)

    # We need to return different values for different calls.
    call_count = [0]

    def side_effect(path, ffprobe_bin="ffprobe"):
        call_count[0] += 1
        if "vertical" in path:
            return bad_v
        return good_h

    with patch("garden_core.stage_render.render_gate.probe_media",
               side_effect=side_effect), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), raise_on_fail=False)
    res_violations = [v for v in r.violations if v.dimension == "resolution"]
    v_res = [v for v in res_violations if v.orientation == "vertical"]
    assert len(v_res) == 1
    assert v_res[0].expected == "1080x1920"
    assert v_res[0].actual == "1080x1080"


def test_resolution_happy_path(tmp_path):
    """Correct resolutions → no resolution violations."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    good_h = MediaInfo(width=3840, height=2160, duration_s=10.0,
                       fps=30.0, has_audio=True)
    good_v = MediaInfo(width=1080, height=1920, duration_s=10.0,
                       fps=30.0, has_audio=True)

    def side_effect(path, ffprobe_bin="ffprobe"):
        if "vertical" in path:
            return good_v
        return good_h

    with patch("garden_core.stage_render.render_gate.probe_media",
               side_effect=side_effect), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), raise_on_fail=False)
    res_violations = [v for v in r.violations if v.dimension == "resolution"]
    assert res_violations == []


# --------------------------------------------------------------------------- #
# 6. Codec violations (mocked _probe_codec)
# --------------------------------------------------------------------------- #

def test_codec_mismatch(tmp_path):
    """Wrong codec → codec violation."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    good_h = MediaInfo(width=3840, height=2160, duration_s=10.0,
                       fps=30.0, has_audio=True)
    good_v = MediaInfo(width=1080, height=1920, duration_s=10.0,
                       fps=30.0, has_audio=True)

    def probe_side(path, ffprobe_bin="ffprobe"):
        if "vertical" in path:
            return good_v
        return good_h

    def codec_side(path, ffprobe_bin="ffprobe"):
        if "vertical" in path:
            return "hevc"
        return "h264"

    with patch("garden_core.stage_render.render_gate.probe_media",
               side_effect=probe_side), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               side_effect=codec_side):
        r = audit_dir(str(tmp_path), raise_on_fail=False)
    codec_violations = [v for v in r.violations if v.dimension == "codec"]
    v_codec = [v for v in codec_violations if v.orientation == "vertical"]
    assert len(v_codec) == 1
    assert v_codec[0].expected == "h264"
    assert v_codec[0].actual == "hevc"


def test_codec_happy_path(tmp_path):
    """Correct codec → no codec violations."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    good_h = MediaInfo(width=3840, height=2160, duration_s=10.0,
                       fps=30.0, has_audio=True)
    good_v = MediaInfo(width=1080, height=1920, duration_s=10.0,
                       fps=30.0, has_audio=True)

    def probe_side(path, ffprobe_bin="ffprobe"):
        if "vertical" in path:
            return good_v
        return good_h

    with patch("garden_core.stage_render.render_gate.probe_media",
               side_effect=probe_side), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), raise_on_fail=False)
    codec_violations = [v for v in r.violations if v.dimension == "codec"]
    assert codec_violations == []


# --------------------------------------------------------------------------- #
# 7. ffprobe unavailable → skipped, not BLOCK
# --------------------------------------------------------------------------- #

def test_ffprobe_missing_marks_skipped_not_blocking(tmp_path):
    """When probe_media returns None and codec probe returns None,
    mechanical items are skipped but ASS gate still runs."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    v_bug = _inject_fontsize(v, round(style.font_size_ratio * 1920))
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v_bug)

    with patch("garden_core.stage_render.render_gate.probe_media",
               return_value=None), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value=None):
        r = audit_dir(str(tmp_path), raise_on_fail=False)
    # Skipped items exist
    assert len(r.skipped) >= 1
    assert all(v.dimension == "skipped" for v in r.skipped)
    # ASS gate still caught the font_ratio bug
    ass_violations = [v for v in r.violations if v.dimension == "font_ratio"]
    assert len(ass_violations) >= 1
    # ffprobe missing does NOT add blocking violations for resolution/codec
    res_violations = [v for v in r.violations if v.dimension == "resolution"]
    assert res_violations == []
    codec_violations = [v for v in r.violations if v.dimension == "codec"]
    assert codec_violations == []


def test_ffprobe_missing_no_raise_when_only_ass_gate_passes(tmp_path):
    """Skipped items never cause raise_on_fail to trigger."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    with patch("garden_core.stage_render.render_gate.probe_media",
               return_value=None), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value=None):
        # raise_on_fail=True (default) — should NOT raise because skipped is non-blocking
        r = audit_dir(str(tmp_path), raise_on_fail=True)
    assert r.passed
    assert len(r.skipped) >= 1


def test_ffprobe_missing_but_ass_gate_blocks(tmp_path):
    """Skipped + ASS gate violation → raise_on_fail still raises on ASS gate."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    v_bug = _inject_fontsize(v, round(style.font_size_ratio * 1920))
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v_bug)

    with patch("garden_core.stage_render.render_gate.probe_media",
               return_value=None), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value=None):
        with pytest.raises(RenderGateError) as ei:
            audit_dir(str(tmp_path), raise_on_fail=True)
        assert "font_ratio" in str(ei.value)


# --------------------------------------------------------------------------- #
# 8. raise_on_fail behavior
# --------------------------------------------------------------------------- #

def test_raise_on_fail_true_with_violations(tmp_path):
    """raise_on_fail=True (default) + violations → RenderGateError."""
    _write_files(tmp_path, "c1", h_mp4=False, v_mp4=True,
                 h_ass="fake", v_ass="fake")
    with pytest.raises(RenderGateError) as ei:
        audit_dir(str(tmp_path))
    assert "missing_file" in str(ei.value)


def test_raise_on_fail_false_with_violations(tmp_path):
    """raise_on_fail=False + violations → returns report, no raise."""
    _write_files(tmp_path, "c1", h_mp4=False, v_mp4=True,
                 h_ass="fake", v_ass="fake")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    assert not r.passed
    assert len(r.violations) >= 1


def test_raise_on_fail_true_no_violations(tmp_path):
    """raise_on_fail=True + no violations → returns report, no raise."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    good_h = MediaInfo(width=3840, height=2160, duration_s=10.0,
                       fps=30.0, has_audio=True)
    good_v = MediaInfo(width=1080, height=1920, duration_s=10.0,
                       fps=30.0, has_audio=True)

    def probe_side(path, ffprobe_bin="ffprobe"):
        if "vertical" in path:
            return good_v
        return good_h

    with patch("garden_core.stage_render.render_gate.probe_media",
               side_effect=probe_side), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), raise_on_fail=True)
    assert r.passed


# --------------------------------------------------------------------------- #
# 9. clip_id discovery (no duplicate from _vertical.ass)
# --------------------------------------------------------------------------- #

def test_clip_id_discovery_dedup(tmp_path):
    """_vertical.ass files do not create spurious clip_ids."""
    style, clip1 = _style(), _clip("c1")
    style2, clip2 = _style(), _clip("c2")
    h1, v1 = _ass_pair(style, clip1)
    h2, v2 = _ass_pair(style2, clip2)
    _write_files(tmp_path, "c1", h_ass=h1, v_ass=v1)
    _write_files(tmp_path, "c2", h_ass=h2, v_ass=v2)

    r = audit_dir(str(tmp_path), raise_on_fail=False)
    # Should have exactly 2 clips, not 4 (no duplicates from _vertical.ass)
    clip_ids_in_violations = {v.clip_id for v in r.violations}
    # With happy path, no violations — just check discovery worked
    assert r.passed


def test_discovery_from_mp4_only(tmp_path):
    """Clip discovered via _horizontal.mp4 when no ASS files exist."""
    (tmp_path / "c3_horizontal.mp4").write_text("fake")
    (tmp_path / "c3_vertical.mp4").write_text("fake")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    # Missing ASS files → missing_file violations for clip c3
    violations_c3 = [v for v in r.violations if v.clip_id == "c3"]
    assert len(violations_c3) >= 2  # H_ASS + V_ASS missing
    assert any("H_ASS" in v.detail for v in violations_c3)


# --------------------------------------------------------------------------- #
# 10. Equivalence: audit_dir ASS gate == check_ass_pair for same files
# --------------------------------------------------------------------------- #

def test_ass_gate_equivalence(tmp_path):
    """audit_dir's ASS gate violations match direct check_ass_pair calls."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    v_bug = _inject_fontsize(v, round(style.font_size_ratio * 1920))
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v_bug)

    r = audit_dir(str(tmp_path), raise_on_fail=False)
    audit_ass = [v for v in r.violations if v.dimension in ("font_ratio", "safe_area")]

    direct = check_ass_pair("c1", h, v_bug)

    # Same count of violations
    assert len(audit_ass) == len(direct)
    # Same dimensions
    audit_dims = {v.dimension for v in audit_ass}
    direct_dims = {v.dimension for v in direct}
    assert audit_dims == direct_dims


# --------------------------------------------------------------------------- #
# 11. AuditReport serialization
# --------------------------------------------------------------------------- #

def test_audit_report_to_dict_and_save(tmp_path):
    """to_dict() is serialisable; save() writes valid JSON readable back."""
    _write_files(tmp_path, "c1", h_mp4=False, v_mp4=True,
                 h_ass="fake", v_ass="fake")
    r = audit_dir(str(tmp_path), raise_on_fail=False)
    d = r.to_dict()
    assert d["output_dir"] == str(tmp_path)
    assert d["passed"] == (len(r.violations) == 0)
    assert isinstance(d["violations"], list)
    assert isinstance(d["skipped"], list)
    # Every violation has required keys
    for vd in d["violations"]:
        for k in ("clip_id", "dimension", "orientation", "detail", "expected", "actual"):
            assert k in vd
    # save -> read back
    path = str(tmp_path / "audit_report.json")
    r.save(path)
    with open(path, "r", encoding="utf-8") as f:
        back = json.load(f)
    assert back == d


# --------------------------------------------------------------------------- #
# 12. Regression: existing gate functions are NOT touched
# --------------------------------------------------------------------------- #

def test_regression_gate_results_still_works():
    """gate_results still accepts RenderResult list and raises RenderGateError."""
    from garden_core.types import RenderResult
    # gate_results expects RenderResult with ass_path — without valid ASS it warns
    # and returns without raising (it skips missing files gracefully).
    rr = RenderResult(
        clip_id="reg", horizontal_mp4="", vertical_mp4="",
        srt_path="", ass_path="/nonexistent/test.ass",
    )
    # Should not raise — missing ASS file → log warning, return empty list internally
    from garden_core.stage_render.render_gate import gate_results
    gate_results([rr])  # no raise


def test_regression_check_ass_pair_still_works():
    """check_ass_pair still accepts ASS text and returns violations."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    v_bug = _inject_fontsize(v, round(style.font_size_ratio * 1920))
    violations = check_ass_pair("c1", h, v_bug)
    assert any(v.dimension == "font_ratio" for v in violations)


def test_custom_expected_resolution(tmp_path):
    """Custom expected resolution is checked correctly."""
    style, clip = _style(), _clip("c1")
    h, v = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_ass=h, v_ass=v)

    info_1080p = MediaInfo(width=1920, height=1080, duration_s=10.0,
                           fps=30.0, has_audio=True)

    with patch("garden_core.stage_render.render_gate.probe_media",
               return_value=info_1080p), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), raise_on_fail=False,
                      expected_horizontal=(1920, 1080),
                      expected_vertical=(1920, 1080))
    # 1920x1080 matches both expected → no resolution violation
    res_violations = [v for v in r.violations if v.dimension == "resolution"]
    assert res_violations == []


def test_render_orientation_flags_control_checks(tmp_path):
    """render_horizontal=False skips all horizontal checks."""
    # Build a proper vertical ASS via build_ass (same as _ass_pair does) so the
    # safe_area check passes for the vertical orientation.
    style, clip = _style(), _clip("c1")
    _, v_ass = _ass_pair(style, clip)
    _write_files(tmp_path, "c1", h_mp4=False, v_mp4=True,
                 h_ass=None, v_ass=v_ass)
    # Mock ffprobe so resolution/codec checks pass for vertical
    good_v = MediaInfo(width=1080, height=1920, duration_s=10.0,
                       fps=30.0, has_audio=True)
    with patch("garden_core.stage_render.render_gate.probe_media",
               return_value=good_v), \
         patch("garden_core.stage_render.render_gate._probe_codec",
               return_value="h264"):
        r = audit_dir(str(tmp_path), render_horizontal=False, raise_on_fail=False)
    # No horizontal violations at all
    h_violations = [v for v in r.violations if v.orientation == "horizontal"]
    assert h_violations == []
    # Vertical should still be checked and pass with valid data
    v_violations = [v for v in r.violations if v.orientation == "vertical"]
    assert v_violations == []

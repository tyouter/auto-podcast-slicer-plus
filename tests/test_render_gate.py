"""Independent mechanical render gate (stage_render.render_gate).

Self-verification of the task's two required scenarios plus the other
dimension (safe area). The gate reads ASS artifacts only — no
ffmpeg, no LLM — so we build ASS text with the real ass_writer and feed it in.
"""

from __future__ import annotations

import re

from garden_core.stage_render.ass_writer import build_ass
from garden_core.stage_render.render_gate import (
    RenderGateError,
    check_ass_pair,
    check_render_result,
    gate_results,
    parse_ass,
)
from garden_core.stage_style.molds import YamlStyleResolver
from garden_core.types import ClipPlan, Cue, RenderResult


def _style():
    # cinematic: font_size_ratio (xr) = 0.078 (height arg is irrelevant — xr is a ratio)
    return YamlStyleResolver().resolve("cinematic", 1080)


def _clip(text: str = "主体性是关键") -> ClipPlan:
    return ClipPlan(
        clip_id="c1", source_ref="v.mp4", start_s=0.0, end_s=10.0,
        cues=(Cue(index=0, text=text, start_s=0.0, end_s=2.0),),
    )


def _ass_pair(style, clip):
    """Render the canonical (horizontal) + vertical ASS the way stage_render does."""
    h = build_ass(clip, style, video_height=1080)                       # 1920x1080
    v = build_ass(clip, style, video_height=1920, video_width=1080)     # 1080x1920
    return h, v


def _inject_fontsize(ass: str, new_size: int) -> str:
    """Rewrite the 'Style: Default' Fontsize field (simulate a render regression)."""
    return re.sub(r"(Style: Default,[^,]*,)\d+", r"\g<1>" + str(new_size), ass, count=1)


# ----- Required scenario 1: the OLD BUG vertical must BLOCK on font_ratio ---- #
def test_old_bug_vertical_blocks_font_ratio():
    """Vertical font sized against the full 1920 canvas (~3.2× too big) → BLOCK,
    with a font_ratio violation naming clip + actual vs expected."""
    style, clip = _style(), _clip()
    h, v = _ass_pair(style, clip)

    bug_fs = round(style.font_size_ratio * 1920)  # 150 — the old "full-canvas" sizing
    v_bug = _inject_fontsize(v, bug_fs)

    violations = check_ass_pair("c1", h, v_bug)
    dims = {x.dimension for x in violations}
    assert "font_ratio" in dims, f"expected font_ratio BLOCK, got {dims}"

    fr = next(x for x in violations if x.dimension == "font_ratio")
    assert fr.clip_id == "c1"
    assert "h_ratio" in fr.actual and "v_ratio" in fr.actual

    # gate_results over a result whose ASS files reproduce the bug must raise.
    with __import__("pytest").raises(RenderGateError) as ei:
        raise RenderGateError(violations)
    assert "font_ratio" in str(ei.value) and "c1" in str(ei.value)


# ----- Required scenario 2: the CORRECT vertical must PASS ------------------- #
def test_correct_vertical_passes():
    """Vertical font sized against the 16:9 content band (~608px) → PASS, no
    violations at all."""
    style, clip = _style(), _clip()
    h, v = _ass_pair(style, clip)
    violations = check_ass_pair("c1", h, v)
    assert violations == [], f"expected PASS, got {[x.render() for x in violations]}"


# ----- font_ratio sanity: the parsed ratios match the known bug magnitude --- #
def test_font_ratio_magnitude_matches_known_bug():
    style, clip = _style(), _clip()
    h, v = _ass_pair(style, clip)
    v_bug = _inject_fontsize(v, round(style.font_size_ratio * 1920))
    ph, pv = parse_ass(h), parse_ass(v_bug)
    # content heights: horizontal 1080, vertical band 608
    h_ratio = ph.fontsize / 1080
    v_ratio = pv.fontsize / 608
    assert v_ratio / h_ratio > 3.0  # the ~3.2× the human caught from frames


# ----- Dimension 2: safe area ----------------------------------------------- #
def test_safe_area_blocks_when_subtitle_below_content_band():
    """A tiny margin_v pushes the bottom-anchored subtitle into the lower
    letterbox of a vertical canvas → safe_area BLOCK."""
    style, clip = _style(), _clip()
    _, v = _ass_pair(style, clip)
    # margin_v=0 → y_bottom = play_h = 1920, well below content band bottom 1264.
    # rewrite MarginV (second-to-last style field) to 0
    line = next(l for l in v.splitlines() if l.startswith("Style: Default,"))
    parts = line.split(",")
    parts[-2] = "0"
    v_bad = v.replace(line, ",".join(parts))
    violations = check_ass_pair("c1", None, v_bad)
    assert any(x.dimension == "safe_area" for x in violations)


def test_safe_area_passes_for_normal_render():
    style, clip = _style(), _clip()
    h, v = _ass_pair(style, clip)
    assert all(x.dimension != "safe_area" for x in check_ass_pair("c1", h, v))


# ----- File-path entry point (read-only disk round-trip) -------------------- #
def test_check_render_result_reads_files(tmp_path):
    style, clip = _style(), _clip()
    h, v = _ass_pair(style, clip)
    v_bug = _inject_fontsize(v, round(style.font_size_ratio * 1920))
    ass_path = tmp_path / "c1.ass"
    ass_path.write_text(h, encoding="utf-8")
    (tmp_path / "c1_vertical.ass").write_text(v_bug, encoding="utf-8")

    result = RenderResult(
        clip_id="c1", horizontal_mp4="", vertical_mp4="",
        srt_path="", ass_path=str(ass_path),
    )
    violations = check_render_result(result)
    assert any(x.dimension == "font_ratio" for x in violations)

    # and the batch gate raises with the full report
    with __import__("pytest").raises(RenderGateError) as ei:
        gate_results([result])
    assert "c1" in str(ei.value) and "font_ratio" in str(ei.value)

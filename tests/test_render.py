"""Stage 6 (style) + Stage 7 (render: ASS/SRT writers, text_measure, ffmpeg escape)."""

from __future__ import annotations

import re

from garden_core.stage_render.ass_writer import build_ass, rounded_rect_drawing
from garden_core.stage_render.ffmpeg_render import escape_ass_path
from garden_core.stage_render.srt_writer import build_srt
from garden_core.stage_render.text_measure import measure_text_width, resolve_font_file
from garden_core.stage_style import DEFAULT_STYLE
from garden_core.stage_style.molds import MOLDS, YamlStyleResolver, mold_to_style
from garden_core.types import BgStyle, ClipPlan, Cue, StyleDef


def _clip(*cues: Cue) -> ClipPlan:
    return ClipPlan(
        clip_id="c1", source_ref="v.mp4", start_s=0.0, end_s=10.0, cues=cues,
    )


# ---------------------------- ASS writer ----------------------------------- #
def test_ass_has_well_formed_header_and_events():
    clip = _clip(Cue(index=0, text="你好世界", start_s=0.0, end_s=2.0))
    ass = build_ass(clip, DEFAULT_STYLE, video_height=1080)
    assert "[Script Info]" in ass
    assert "PlayResX: 1920" in ass  # 16:9 of 1080
    assert "PlayResY: 1080" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue:" in ass
    # one dialogue line per cue (no background)
    assert ass.count("Dialogue:") == 1


def test_ass_time_format_is_h_mm_ss_cc():
    clip = _clip(Cue(index=0, text="x", start_s=65.25, end_s=66.5))
    ass = build_ass(clip, DEFAULT_STYLE, video_height=1080)
    # 65.25s → 0:01:05.25
    assert "0:01:05.25" in ass


def test_ass_with_background_emits_two_dialogue_layers():
    style = StyleDef(
        name="bg", font_family="Noto Sans SC", font_size_ratio=0.05,
        primary_color="&H00FFFFFF", outline_color="&H00000000",
        outline_width=0.02, shadow_color="&H96000000", shadow_depth=0.01,
        background=BgStyle(kind="rounded", corner_radius=0.08, padding=0.15, alpha=180),
    )
    clip = _clip(Cue(index=0, text="测试", start_s=0.0, end_s=1.0))
    ass = build_ass(clip, style, video_height=1080)
    # background box (layer 0) + text (layer 1)
    assert ass.count("Dialogue:") == 2
    assert "\\p1" in ass  # vector drawing for the box


def test_ass_uses_explicit_canvas_for_vertical():
    """Vertical ASS must be authored at the vertical canvas, not 16:9-derived."""
    clip = _clip(Cue(index=0, text="竖屏测试", start_s=0.0, end_s=1.0))
    ass_v = build_ass(clip, DEFAULT_STYLE, video_height=1920, video_width=1080)
    assert "PlayResX: 1080" in ass_v
    assert "PlayResY: 1920" in ass_v
    # and horizontal defaults to 16:9
    ass_h = build_ass(clip, DEFAULT_STYLE, video_height=1080)
    assert "PlayResX: 1920" in ass_h
    assert "PlayResY: 1080" in ass_h


def _parse_style_line(ass: str) -> dict:
    """Pull Fontsize / MarginL,R,V out of the V4+ 'Style: Default,...' line."""
    line = next(l for l in ass.splitlines() if l.startswith("Style: Default,"))
    f = line[len("Style: "):].split(",")
    # Format: Name,Fontname,Fontsize,...,Alignment,MarginL,MarginR,MarginV,Encoding
    return {
        "fontsize": int(f[2]),
        "margin_l": int(f[-4]),
        "margin_r": int(f[-3]),
        "margin_v": int(f[-2]),
    }


def test_horizontal_4k_style_line_unchanged_by_content_region_fix():
    """Regression: the vertical content-region fix must NOT touch horizontal.

    Values match _verify/baseline_before.txt (cinematic @4K): a 16:9 canvas has
    content_height == video_height and zero bottom offset, so font + margins are
    byte-for-byte what they were before the fix.
    """
    resolver = YamlStyleResolver()
    style = resolver.resolve("cinematic", 2160)
    clip = _clip(Cue(index=0, text="主体性", start_s=0.0, end_s=1.0))
    ass = build_ass(clip, style, video_height=2160)  # default width → 3840 (16:9)
    assert "PlayResX: 3840" in ass and "PlayResY: 2160" in ass
    s = _parse_style_line(ass)
    assert s["fontsize"] == 168           # 0.078 * 2160
    assert s["margin_v"] == 129           # int(0.06 * 2160), no vertical offset
    assert s["margin_l"] == 307 and s["margin_r"] == 307


def test_vertical_subtitles_use_content_region_not_full_canvas():
    """The 16:9 content occupies only the centred 608px band of the 1920 canvas.

    Font + vertical margin must scale to that band (not the full 1920), and the
    subtitle must land at the bottom of the band — never in the letterbox below.
    """
    resolver = YamlStyleResolver()
    style = resolver.resolve("cinematic", 1080)  # xr is a ratio; height arg irrelevant
    clip = _clip(Cue(index=0, text="主体性", start_s=0.0, end_s=1.0))
    ass = build_ass(clip, style, video_height=1920, video_width=1080)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    s = _parse_style_line(ass)

    content_h = 608                       # centred 16:9 band of a 1080-wide canvas
    content_bottom_offset = 1920 - (1920 + content_h) // 2  # 656

    # font scales to the band, far below the buggy full-canvas size (0.078*1920≈150)
    assert s["fontsize"] == 47            # round(0.078 * 608)
    # margin places the subtitle at the band bottom, not the canvas bottom
    assert s["margin_v"] == int(0.06 * content_h) + content_bottom_offset  # 692
    baseline_y = 1920 - s["margin_v"]
    assert 656 < baseline_y < 1264        # inside the content band [656, 1264]
    # visual proportion matches horizontal (font / content_height ≈ xr = 0.078)
    assert abs(s["fontsize"] / content_h - 168 / 2160) < 0.002


def test_ass_skips_empty_text_cues():
    clip = _clip(
        Cue(index=0, text="", start_s=0.0, end_s=1.0),
        Cue(index=1, text="实际内容", start_s=1.0, end_s=2.0),
    )
    ass = build_ass(clip, DEFAULT_STYLE, video_height=1080)
    assert ass.count("Dialogue:") == 1


def test_rounded_rect_drawing_nonzero():
    d = rounded_rect_drawing(100, 40, 8)
    assert d.startswith("m 8 0")
    assert "b " in d  # has bezier corners


# ---------------------------- SRT writer ----------------------------------- #
def test_srt_format_and_indexing():
    clip = _clip(
        Cue(index=0, text="第一句", start_s=0.0, end_s=1.5),
        Cue(index=1, text="第二句", start_s=2.0, end_s=3.0),
    )
    srt = build_srt(clip)
    assert "1\n" in srt
    assert "00:00:00,000 --> 00:00:01,500" in srt
    assert "00:00:02,000 --> 00:00:03,000" in srt
    assert "第一句" in srt and "第二句" in srt


# ---------------------------- text_measure (bold fix) ---------------------- #
def test_text_measure_returns_positive_width():
    w = measure_text_width("你好世界", 54, "Noto Sans SC", bold=False)
    assert w > 0


def test_text_measure_bold_differs_or_falls_back_gracefully():
    """Fix #14: bold must be honoured (different file) or at least not crash."""
    w_reg = measure_text_width("Test", 54, "Noto Sans SC", bold=False)
    w_bold = measure_text_width("Test", 54, "Noto Sans SC", bold=True)
    # both succeed; bold may equal regular if no bold file, but must not error
    assert w_reg > 0 and w_bold > 0


def test_resolve_font_file_finds_something():
    """On a Windows box with fonts, we should resolve SOME file (or None gracefully)."""
    f = resolve_font_file("Arial", bold=False)
    # Arial should exist on Windows; if not, None is acceptable (no crash)
    assert f is None or f.exists()


# ---------------------------- style resolution ----------------------------- #
def test_builtin_molds_resolve():
    resolver = YamlStyleResolver()
    for name in ("default", "cinematic", "frosted_glass"):
        s = resolver.resolve(name, 1080)
        assert s.name == name
        assert s.font_size_px(1080) > 0


def test_frosted_glass_mold_has_background():
    s = mold_to_style(MOLDS["frosted_glass"])
    assert s.background is not None
    assert s.background.kind == "frosted_glass"


def test_unknown_style_raises_without_config():
    # New contract: xr (font_size_ratio) is required from config with no code
    # default. An unknown style has no config, so it raises instead of silently
    # falling back to a built-in number.
    import pytest
    from garden_core.config import ConfigError
    resolver = YamlStyleResolver()
    with pytest.raises(ConfigError):
        resolver.resolve("does_not_exist", 1080)


def test_missing_xr_in_config_raises():
    # A known mold with no xr in any config layer must error (xr is mandatory,
    # never silently 0.052). A non-existent default_dir => no packaged xr.
    import pytest
    from garden_core.config import ConfigError
    resolver = YamlStyleResolver(default_dir="__no_such_styles_dir__")
    with pytest.raises(ConfigError):
        resolver.resolve("cinematic", 2160)


def test_yaml_override(tmp_path):
    (tmp_path / "custom.yaml").write_text(
        "mold: cinematic\nfont_size_ratio: 0.08\n", encoding="utf-8"
    )
    resolver = YamlStyleResolver(config_dir=tmp_path)
    s = resolver.resolve("custom", 1080)
    assert s.font_size_ratio == 0.08
    assert s.name == "custom"


# ---------------------------- ffmpeg escape -------------------------------- #
def test_escape_ass_path_windows_drive():
    assert escape_ass_path("C:\\subs\\x.ass") == "C\\:/subs/x.ass"


def test_escape_ass_path_unix():
    assert escape_ass_path("/home/u/x.ass") == "/home/u/x.ass"

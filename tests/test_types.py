"""Milestone 0 verification: the core data model invariants hold.

If these pass, the foundation is sound before any stage logic is written.
"""

from __future__ import annotations

import dataclasses

import pytest

from garden_core.types import (
    BgStyle,
    ClipPlan,
    Cue,
    CutPoint,
    RenderResult,
    Segment,
    StyleDef,
    Transcript,
    Word,
)


# --------------------------------------------------------------------------- #
# immutability
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cls,kwargs", [
    (Word, {"text": "你", "start_s": 0.0, "end_s": 0.3}),
    (Segment, {"text": "你好", "start_s": 0.0, "end_s": 1.0}),
    (Cue, {"index": 0, "text": "你好", "start_s": 0.0, "end_s": 1.0}),
    (StyleDef, {
        "name": "x", "font_family": "f", "font_size_ratio": 0.05,
        "primary_color": "&H00FFFFFF", "outline_color": "&H00000000",
        "outline_width": 2.0, "shadow_color": "&H96000000", "shadow_depth": 1.0,
    }),
])
def test_frozen_dataclasses_are_immutable(cls, kwargs):
    obj = cls(**kwargs)
    first_field = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        # Regular setattr on a frozen dataclass must raise.
        setattr(obj, first_field, getattr(obj, first_field))


def test_cue_is_the_single_subtitle_shape():
    """Cue is the ONE type flowing segment→cut→render — fields are stable."""
    cue = Cue(index=3, text="测试", start_s=1.5, end_s=3.0, text_en="test")
    assert cue.duration_s == pytest.approx(1.5)
    fields = {f.name for f in dataclasses.fields(Cue)}
    assert fields == {"index", "text", "start_s", "end_s", "text_en"}


def test_words_are_first_class_on_segment():
    """Word timing lives on Segment, not dropped (fixes legacy loss)."""
    seg = Segment(
        text="你好", start_s=0.0, end_s=1.0,
        words=(Word("你", 0.0, 0.5), Word("好", 0.5, 1.0)),
    )
    assert len(seg.words) == 2
    assert seg.words[-1].end_s == 1.0


def test_transcript_replace_yields_new_instance():
    """Stages evolve data via replace(), not mutation."""
    seg = Segment(text="a", start_s=0.0, end_s=1.0)
    t1 = Transcript(segments=(seg,), source_file="x", engine="e")
    t2 = dataclasses.replace(t1, corrections_applied=("errata:3",))
    assert t1.corrections_applied == ()
    assert t2.corrections_applied == ("errata:3",)
    assert t1 is not t2


def test_clipplan_is_parametric_reference():
    """ClipPlan carries source-ref + in/out, not bytes (LTX idea)."""
    cue = Cue(index=0, text="x", start_s=0.0, end_s=1.0)
    plan = ClipPlan(
        clip_id="c1", source_ref="video.mp4",
        start_s=10.0, end_s=20.0, cues=(cue,),
    )
    assert plan.duration_s == pytest.approx(10.0)
    assert plan.source_ref.endswith(".mp4")


def test_styledef_font_size_scales_to_video():
    style = StyleDef(
        name="x", font_family="f", font_size_ratio=0.05,
        primary_color="&H00FFFFFF", outline_color="&H00000000",
        outline_width=2.0, shadow_color="&H00000000", shadow_depth=1.0,
    )
    assert style.font_size_px(1080) == pytest.approx(54.0)
    assert style.font_size_px(1920) == pytest.approx(96.0)


def test_bgstyle_optional_on_styledef():
    style = StyleDef(
        name="frosted", font_family="f", font_size_ratio=0.05,
        primary_color="&H00FFFFFF", outline_color="&H00000000",
        outline_width=2.0, shadow_color="&H00000000", shadow_depth=1.0,
        background=BgStyle(kind="frosted_glass", corner_radius=12, padding=8, alpha=180),
    )
    assert style.background.kind == "frosted_glass"

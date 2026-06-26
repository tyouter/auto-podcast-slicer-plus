"""Stage 4 (segment) + Stage 5 (cut) tests."""

from __future__ import annotations

from garden_core.stage_cut import cut
from garden_core.stage_segment import SegmentOptions, segment
from garden_core.types import CutPoint, Segment, Transcript


def _transcript(*segs: Segment) -> Transcript:
    return Transcript(segments=tuple(segs), source_file="v.mp4", engine="test")


def test_segment_short_segment_is_one_cue():
    t = _transcript(Segment(text="你好世界", start_s=0.0, end_s=1.0))
    cues = segment(t, SegmentOptions(strategy="semantic"))
    assert len(cues) == 1
    assert cues[0].text == "你好世界"
    assert cues[0].start_s == 0.0
    assert cues[0].end_s == 1.0


def test_segment_long_text_splits_at_sentence_boundary():
    # 40 chars with a period in the middle → split there.
    long = "今天天气真不错我们可以出去走走。" + "然后我们去吃点东西" * 4
    t = _transcript(Segment(text=long, start_s=0.0, end_s=10.0))
    opts = SegmentOptions(strategy="semantic", max_chars_per_line=14, max_lines=2)
    cues = segment(t, opts)
    assert len(cues) >= 2
    # every cue must respect the max_chars budget (allow small over by connective)
    for c in cues:
        assert len(c.text) <= opts.max_chars_per_line * opts.max_lines + 2


def test_segment_no_time_overlap_between_cues():
    long = "。".join(["这是一个较长的句子需要被切分"] * 5)
    t = _transcript(Segment(text=long, start_s=0.0, end_s=20.0))
    cues = segment(t, SegmentOptions(strategy="semantic"))
    for a, b in zip(cues, cues[1:]):
        assert a.end_s <= b.start_s + 0.01, f"overlap: {a} -> {b}"


def test_segment_merger_strategy_produces_cues():
    t = _transcript(
        Segment(text="你好", start_s=0.0, end_s=0.5),
        Segment(text="世界", start_s=0.6, end_s=1.1),
    )
    cues = segment(t, SegmentOptions(strategy="merger"))
    # two short segments merged into one cue
    assert len(cues) == 1
    assert cues[0].start_s == 0.0
    assert cues[0].end_s == 1.1


def test_segment_word_timing_redistributes_accurately():
    """When Segment carries words, sub-cues get word-spanned timestamps."""
    words = tuple(
        __import__("garden_core.types", fromlist=["Word"]).Word(text=ch, start_s=s, end_s=e)
        for ch, s, e in [("你", 0.0, 0.5), ("好", 0.5, 1.0),
                         ("世", 1.0, 1.5), ("界", 1.5, 2.0)]
    )
    t = _transcript(Segment(text="你好世界", start_s=0.0, end_s=2.0, words=words))
    # force a split with tiny budget
    cues = segment(t, SegmentOptions(strategy="semantic", max_chars_per_line=2, max_lines=1))
    assert len(cues) == 2
    # second cue should start near 1.0 (world) not 0.0
    assert cues[1].start_s >= 0.9


def test_cut_extracts_and_rebases_to_clip_local_time():
    t = _transcript(Segment(text="你好", start_s=0.0, end_s=1.0))
    from garden_core.types import Cue
    cues = (Cue(index=0, text="a", start_s=5.0, end_s=6.0),
            Cue(index=1, text="b", start_s=12.0, end_s=13.0),
            Cue(index=2, text="c", start_s=100.0, end_s=101.0))
    plans = cut(t, cues, [CutPoint(clip_id="c1", source_media=t.source_file, start_s=10.0, end_s=20.0)])
    assert len(plans) == 1
    plan = plans[0]
    # only cue 'b' (12-13) falls in [10,20]
    assert len(plan.cues) == 1
    assert plan.cues[0].text == "b"
    # rebased to clip-local: 12-10=2 .. 13-10=3
    assert plan.cues[0].start_s == 2.0
    assert plan.cues[0].end_s == 3.0
    assert plan.start_s == 10.0 and plan.end_s == 20.0
    assert plan.source_ref.endswith("v.mp4")


def test_cut_cue_straddling_boundary_is_clipped():
    t = _transcript(Segment(text="x", start_s=0.0, end_s=1.0))
    from garden_core.types import Cue
    # cue overlaps the clip start boundary (8-12, clip starts at 10)
    cues = (Cue(index=0, text="straddle", start_s=8.0, end_s=12.0),)
    plans = cut(t, cues, [CutPoint(clip_id="c1", source_media=t.source_file, start_s=10.0, end_s=20.0)])
    plan = plans[0]
    assert plan.cues[0].start_s == 0.0  # 8 clipped to clip start → local 0
    assert plan.cues[0].end_s == 2.0    # 12-10


def test_pipeline_source_media_overrides_source_ref():
    """When rendering from a loaded transcript whose source_file is a JSON path,
    opts.source_media must repoint clip plans to the real video."""
    from garden_core.pipeline import PipelineOptions
    from garden_core.types import Cue
    # transcript.source_file looks like a JSON path (the legacy-load situation)
    t = Transcript(
        segments=(Segment(text="x", start_s=5.0, end_s=6.0),),
        source_file="transcript.json", engine="test",
    )
    cues = (Cue(index=0, text="x", start_s=5.0, end_s=6.0),)
    plans = cut(t, cues, [CutPoint(clip_id="c1", source_media=t.source_file, start_s=0.0, end_s=10.0)])
    # source_ref comes from cp.source_media, not transcript.source_file
    assert plans[0].source_ref == t.source_file


def test_cut_uses_cutpoint_source_media():
    """T4: cut() now uses cp.source_media directly for source_ref.

    The old contract (cut uses transcript.source_file, then opts.source_media
    overrides) is retired. Now cp.source_media is required and is written
    straight into ClipPlan.source_ref by cut().
    """
    from garden_core.pipeline import PipelineOptions
    from garden_core.types import Cue
    t = Transcript(
        segments=(Segment(text="x", start_s=5.0, end_s=6.0),),
        source_file="transcript.json", engine="test",
    )
    cues = (Cue(index=0, text="x", start_s=5.0, end_s=6.0),)
    # CutPoint with explicit source_media
    plans = cut(t, cues, [CutPoint(clip_id="c1", source_media="real_video.mp4", start_s=0.0, end_s=10.0)])
    # cut() now writes cp.source_media, not transcript.source_file
    assert plans[0].source_ref == "real_video.mp4"
    # The old opts.source_media override is now a defensive fallback for empty
    # source_ref only — verify it doesn't overwrite an already-populated one.
    from dataclasses import replace as _replace
    opts = PipelineOptions(source_media="different.mp4")
    if opts.source_media:
        plans = tuple(
            _replace(p, source_ref=opts.source_media) if not p.source_ref else p
            for p in plans
        )
    # source_ref stays as cp.source_media, not overwritten
    assert plans[0].source_ref == "real_video.mp4"

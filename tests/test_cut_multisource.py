"""T4: multi-source CutPoint with source_media + source_offset_s."""

from garden_core.stage_cut import cut
from garden_core.types import CutPoint, Cue, Segment, Transcript

SRC1 = "video_part1.mp4"
SRC2 = "video_part2.mp4"


def test_multisource_cut_respects_source_media_and_offset():
    """Two CutPoints with different source_media; second has source_offset_s."""
    t = Transcript(
        segments=(Segment(text="x", start_s=0.0, end_s=1000.0),),
        source_file="transcript.json", engine="test",
    )
    # Cues that overlap the two clip windows
    cues = (
        Cue(index=0, text="a", start_s=15.0, end_s=18.0),
        Cue(index=1, text="b", start_s=865.0, end_s=870.0),
    )
    cp1 = CutPoint("a", SRC1, 10.0, 20.0)
    cp2 = CutPoint("b", SRC2, 860.0, 911.0, source_offset_s=850.0)

    plans = cut(t, cues, [cp1, cp2])
    assert len(plans) == 2

    # Plan 1: SRC1, no offset
    assert plans[0].source_ref == SRC1
    assert plans[0].start_s == 10.0
    assert plans[0].end_s == 20.0
    assert len(plans[0].cues) == 1
    # cue 'a' rebased: 15-10=5 .. 18-10=8
    assert plans[0].cues[0].start_s == 5.0
    assert plans[0].cues[0].end_s == 8.0

    # Plan 2: SRC2, offset 850
    assert plans[1].source_ref == SRC2
    assert plans[1].start_s == 10.0  # 860-850
    assert plans[1].end_s == 61.0    # 911-850
    assert len(plans[1].cues) == 1
    # cue 'b' rebase is still relative to cp.start_s (860), not offset-adjusted
    assert plans[1].cues[0].start_s == 5.0   # 865-860
    assert plans[1].cues[0].end_s == 10.0    # 870-860


def test_multisource_single_source_no_offset():
    """Single-source CutPoint: source_offset_s=0.0 → behavior unchanged."""
    t = Transcript(
        segments=(Segment(text="x", start_s=0.0, end_s=100.0),),
        source_file="unused.json", engine="test",
    )
    cues = (Cue(index=0, text="single", start_s=30.0, end_s=40.0),)
    cp = CutPoint("s1", "single_source.mp4", 25.0, 45.0)

    plans = cut(t, cues, [cp])
    assert plans[0].source_ref == "single_source.mp4"
    assert plans[0].start_s == 25.0  # no offset
    assert plans[0].end_s == 45.0
    assert plans[0].cues[0].start_s == 5.0   # 30-25
    assert plans[0].cues[0].end_s == 15.0    # 40-25

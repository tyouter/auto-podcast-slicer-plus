"""Pipeline-wide invariants: the overlap guarantee + gap-heal wiring."""

from __future__ import annotations

from garden_core.pipeline import PipelineOptions, _flatten_overlaps
from garden_core.stage_segment.gap_heal import has_overlaps
from garden_core.types import Cue


def test_flatten_overlaps_resolves_conflicts():
    """If segmentation produced overlapping cues, _flatten_overlaps trims them."""
    cues = (
        Cue(index=0, text="a", start_s=0.0, end_s=3.0),
        Cue(index=1, text="b", start_s=2.5, end_s=5.0),  # overlaps a by 0.5
    )
    flat = _flatten_overlaps(cues)
    # rebuild a transcript view to check the invariant
    from garden_core.types import Segment, Transcript
    t = Transcript(
        segments=tuple(Segment(text=c.text, start_s=c.start_s, end_s=c.end_s) for c in flat),
        source_file="", engine="",
    )
    assert not has_overlaps(t)


def test_pipeline_options_has_heal_fields():
    opts = PipelineOptions()
    assert opts.heal_gaps is False
    assert opts.heal_max_rounds == 5
    opts2 = PipelineOptions(heal_gaps=True, heal_max_rounds=3)
    assert opts2.heal_gaps is True and opts2.heal_max_rounds == 3


def test_full_pipeline_segmentation_produces_no_overlaps():
    """End-to-end invariant: segment() output must never overlap (defensive guard)."""
    from garden_core.stage_segment import SegmentOptions, segment
    from garden_core.types import Segment, Transcript

    # segments that would overlap if naive — segmenter must flatten
    t = Transcript(
        segments=(
            Segment(text="第一段较长内容需要切分", start_s=0.0, end_s=5.0),
            Segment(text="第二段也很长", start_s=4.5, end_s=8.0),  # overlaps first
        ),
        source_file="x", engine="t",
    )
    cues = segment(t, SegmentOptions(strategy="semantic"))
    from garden_core.types import Segment as S, Transcript as T
    view = T(
        segments=tuple(S(text=c.text, start_s=c.start_s, end_s=c.end_s) for c in cues),
        source_file="", engine="",
    )
    # segmenter + _enforce_timing should already prevent overlap; verify
    assert not has_overlaps(view)

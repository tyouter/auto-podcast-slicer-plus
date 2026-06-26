"""Milestone 3: gap_heal dedup (bug #5) + overlap invariant tests."""

from __future__ import annotations

from garden_core.stage_segment.gap_heal import (
    Gap,
    has_overlaps,
    insert_segments,
)
from garden_core.types import Segment, Transcript


def _t(*segs: Segment) -> Transcript:
    return Transcript(segments=tuple(segs), source_file="x", engine="test")


def test_has_overlaps_detects_true():
    t = _t(
        Segment(text="a", start_s=0.0, end_s=2.0),
        Segment(text="b", start_s=1.5, end_s=3.0),  # overlaps a by 0.5s
    )
    assert has_overlaps(t)


def test_has_overlaps_clean_is_false():
    t = _t(
        Segment(text="a", start_s=0.0, end_s=2.0),
        Segment(text="b", start_s=2.05, end_s=3.0),
    )
    assert not has_overlaps(t)


def test_insert_segments_dedups_overlapping_new():
    """Bug #5 fix: a new segment overlapping an existing one is dropped."""
    existing = _t(Segment(text="existing", start_s=5.0, end_s=8.0))
    # this candidate overlaps the existing segment heavily
    dup = Segment(text="dup", start_s=6.0, end_s=9.0)
    out = insert_segments(existing, [dup])
    assert len(out.segments) == 1
    assert out.segments[0].text == "existing"


def test_insert_segments_dedups_near_duplicate_text():
    """Near-duplicate (same text, close time) is collapsed."""
    existing = _t(Segment(text="你好世界", start_s=10.0, end_s=12.0))
    dup = Segment(text="你好世界", start_s=10.2, end_s=12.1)
    out = insert_segments(existing, [dup])
    assert len(out.segments) == 1


def test_insert_segments_accepts_non_overlapping_new():
    """A genuinely new gap segment is inserted, sorted into place."""
    existing = _t(Segment(text="a", start_s=0.0, end_s=2.0),
                  Segment(text="c", start_s=5.0, end_s=7.0))
    new = Segment(text="b", start_s=2.5, end_s=4.5)  # fills the gap, no overlap
    out = insert_segments(existing, [new])
    assert len(out.segments) == 3
    assert [s.text for s in out.segments] == ["a", "b", "c"]


def test_insert_segments_repeated_round_never_creates_overlap():
    """Multiple heal rounds inserting the same region must not pile up."""
    existing = _t(Segment(text="a", start_s=0.0, end_s=2.0))
    same_new = Segment(text="recovered", start_s=3.0, end_s=5.0)
    out = existing
    for _ in range(5):  # simulate 5 heal rounds all "finding" the same gap
        out = insert_segments(out, [same_new])
    assert len(out.segments) == 2  # a + recovered, never duplicated
    assert not has_overlaps(out)


def test_insert_segments_fail_safe_on_would_be_overlap():
    """If merging would somehow create overlap, original is returned unchanged."""
    existing = _t(Segment(text="a", start_s=0.0, end_s=10.0))
    # two new segs that individually don't overlap existing but overlap each other
    # (both start inside the gap after a). Construct so the merge guard trips.
    # Actually both are accepted vs existing; they overlap each other → guard.
    new1 = Segment(text="b", start_s=11.0, end_s=15.0)
    new2 = Segment(text="c", start_s=12.0, end_s=14.0)  # overlaps new1
    out = insert_segments(existing, [new1, new2])
    # new1 accepted; new2 overlaps new1 → dropped by _overlaps_any during merge
    assert not has_overlaps(out)
    assert len(out.segments) == 2  # a + b only


def test_gap_dataclass_duration():
    g = Gap(start_s=5.0, end_s=8.5)
    assert g.duration_s == 3.5


def test_detect_gaps_no_audio_returns_empty():
    """Detection without audio fails safe (no invented gaps)."""
    from garden_core.stage_segment.gap_heal import detect_gaps
    t = _t(Segment(text="a", start_s=0.0, end_s=1.0))
    assert detect_gaps(t, "") == []
    assert detect_gaps(t, "nonexistent.wav") == []


def test_heal_gaps_detection_only_mode():
    """With no transcriber, heal_gaps runs detection only — no text invented."""
    from garden_core.stage_segment.gap_heal import heal_gaps
    t = _t(Segment(text="a", start_s=0.0, end_s=1.0))
    out, unfilled = heal_gaps(t, "", transcriber=None, max_rounds=1)
    assert out == t  # unchanged

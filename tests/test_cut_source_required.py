"""T4 breaking change: CutPoint.source_media is now required (no default)."""

import pytest
from garden_core.types import CutPoint


def test_cutpoint_source_media_required():
    """Old-style CutPoint without source_media must raise TypeError."""
    with pytest.raises(TypeError):
        CutPoint(clip_id="x", start_s=0, end_s=10)  # missing source_media


def test_cutpoint_with_source_media():
    """CutPoint with source_media as positional arg works."""
    cp = CutPoint("x", "src.mp4", 0, 10)
    assert cp.source_media == "src.mp4"
    assert cp.source_offset_s == 0.0


def test_cutpoint_with_source_offset():
    """source_offset_s defaults to 0.0 and can be set via keyword."""
    cp = CutPoint("x", "src2.mp4", 100, 200, source_offset_s=50.0)
    assert cp.source_media == "src2.mp4"
    assert cp.source_offset_s == 50.0
    assert cp.start_s == 100
    assert cp.end_s == 200

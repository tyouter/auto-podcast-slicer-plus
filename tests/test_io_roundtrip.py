"""I/O symmetry: save_transcript_json → load_transcript_json round-trips.

Counterpart to test_io_source.py (the load-only direction). Asserts that a
Transcript written by ``save_transcript_json`` is read back field-for-field by
``load_transcript_json`` (segments / words / start/end / duration /
corrections_applied), and that saving overwrites an existing file.
"""

from __future__ import annotations

from garden_core.io_.sink import save_transcript_json
from garden_core.io_.source import load_transcript_json
from garden_core.types import Segment, Transcript, Word


def _sample_transcript() -> Transcript:
    return Transcript(
        segments=(
            Segment(
                text="你好",
                start_s=0.0,
                end_s=1.0,
                speaker="0",
                words=(
                    Word(text="你", start_s=0.0, end_s=0.5, confidence=1.0),
                    Word(text="好", start_s=0.5, end_s=1.0, confidence=0.9),
                ),
                confidence=0.95,
            ),
            Segment(
                text="世界",
                start_s=1.0,
                end_s=2.5,
                speaker=None,
                words=(),
                confidence=1.0,
            ),
        ),
        source_file="orig.json",
        engine="funasr_mixed",
        language="zh",
        # Non-zero so load keeps it as-is (a 0.0 duration would be re-derived).
        duration_s=12.34,
        corrections_applied=("特斯拉→Tesla", "fixed typo"),
    )


def test_save_load_roundtrip_fields_equal(tmp_path):
    """save → load preserves segments, words, timings, duration, corrections."""
    t = _sample_transcript()
    p = tmp_path / "transcript.json"

    written = save_transcript_json(t, p)
    assert written == str(p)

    loaded = load_transcript_json(p)

    # segment count + per-segment timing
    assert len(loaded.segments) == len(t.segments) == 2
    for got, want in zip(loaded.segments, t.segments):
        assert got.text == want.text
        assert got.start_s == want.start_s
        assert got.end_s == want.end_s
        assert got.duration_s == want.duration_s
        assert got.speaker == want.speaker

    # word count + per-word timing/confidence
    assert len(loaded.segments[0].words) == 2
    assert len(loaded.segments[1].words) == 0
    for got, want in zip(loaded.segments[0].words, t.segments[0].words):
        assert got.text == want.text
        assert got.start_s == want.start_s
        assert got.end_s == want.end_s
        assert got.confidence == want.confidence

    # transcript-level fields
    assert loaded.duration_s == t.duration_s
    assert loaded.engine == t.engine
    assert loaded.language == t.language
    assert loaded.corrections_applied == t.corrections_applied == ("特斯拉→Tesla", "fixed typo")


def test_save_overwrites_existing_file(tmp_path):
    """Saving to an existing path replaces its content (idempotent overwrite)."""
    p = tmp_path / "transcript.json"
    p.write_text("{\"stale\": true}", encoding="utf-8")

    t = _sample_transcript()
    save_transcript_json(t, p)
    save_transcript_json(t, p)  # twice — second write must overwrite, not append

    loaded = load_transcript_json(p)
    assert len(loaded.segments) == 2
    assert loaded.corrections_applied == t.corrections_applied

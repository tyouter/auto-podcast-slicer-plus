"""I/O boundary: ms↔s conversion happens ONLY here, legacy JSON tolerated."""

from __future__ import annotations

import json

from garden_core.io_.source import load_transcript_json
from garden_core.types import Segment


def test_load_ms_based_segments(tmp_path):
    """Legacy transcript.json uses start_ms/end_ms — converted to seconds here."""
    data = {
        "engine": "funasr_mixed",
        "language": "zh",
        "duration": 5.0,
        "segments": [
            {"start_ms": 0, "end_ms": 1500, "text": "你好"},
            {"start_ms": 1500, "end_ms": 3000, "text": "世界"},
        ],
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    t = load_transcript_json(p)
    assert t.segments[0].start_s == 0.0
    assert t.segments[0].end_s == 1.5
    assert t.segments[1].start_s == 1.5
    assert t.engine == "funasr_mixed"
    assert t.duration_s == 5.0


def test_load_seconds_based_with_words(tmp_path):
    """Aligned transcripts carry word timing — must survive ingestion."""
    data = {
        "engine": "mms",
        "segments": [{
            "start_s": 0.0, "end_s": 1.0, "text": "你好",
            "spk": 0,
            "words": [
                {"text": "你", "start": 0.0, "end": 0.5},
                {"text": "好", "start": 0.5, "end": 1.0},
            ],
        }],
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    t = load_transcript_json(p)
    seg = t.segments[0]
    assert isinstance(seg, Segment)
    assert len(seg.words) == 2
    assert seg.words[1].text == "好"
    assert seg.speaker == "0"  # spk int → str


def test_load_bare_list_form(tmp_path):
    """A bare list of segments (no envelope) is tolerated."""
    data = [{"start_ms": 0, "end_ms": 500, "text": "a"}]
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    t = load_transcript_json(p)
    assert len(t.segments) == 1
    assert t.segments[0].start_s == 0.0


def test_no_mutation_of_input(tmp_path):
    """Loading must not mutate caller state — pure read."""
    data = {"segments": [{"start_ms": 0, "end_ms": 500, "text": "a"}]}
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    t1 = load_transcript_json(p)
    t2 = load_transcript_json(p)
    assert t1 == t2  # same input → equal immutable objects

"""Readers: foreign JSON / legacy transcript formats → typed Transcript.

This is where ms↔s conversion happens (and only here). Compatible with the
legacy ``transcript.json`` / ``transcript_aligned.json`` shapes so the new
library can ingest old project data without re-running ASR.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from garden_core.infra.time_util import ms_to_s, parse_time_heuristic
from garden_core.types import Segment, Transcript, Word

log = logging.getLogger(__name__)

__all__ = ["load_transcript_json", "load_transcript_aligned_json"]


def _segment_from_dict(item: dict) -> Segment:
    # Accept ms fields, s fields, or ambiguous start/begin.
    if "start_ms" in item and "end_ms" in item:
        start_s = ms_to_s(item["start_ms"])
        end_s = ms_to_s(item["end_ms"])
    elif "start_s" in item and "end_s" in item:
        start_s = float(item["start_s"])
        end_s = float(item["end_s"])
    else:
        start_s = parse_time_heuristic(item.get("start", item.get("begin", 0)))
        end_s = parse_time_heuristic(item.get("end", 0))
    text = str(item.get("text", item.get("sentence", ""))).strip()
    speaker = item.get("speaker") or item.get("spk")
    speaker = None if speaker is None else str(speaker)
    words = ()
    raw_words = item.get("words") or item.get("word_timestamps")
    if isinstance(raw_words, list):
        built = []
        for w in raw_words:
            if not isinstance(w, dict):
                continue
            built.append(Word(
                text=str(w.get("text", w.get("word", ""))),
                start_s=float(w.get("start", w.get("start_s", 0.0))),
                end_s=float(w.get("end", w.get("end_s", 0.0))),
                confidence=float(w.get("confidence", 1.0)),
            ))
        words = tuple(built)
    return Segment(
        text=text, start_s=start_s, end_s=end_s,
        speaker=speaker, words=words,
        confidence=float(item.get("confidence", 1.0)),
    )


def load_transcript_json(path: str | Path) -> Transcript:
    """Load a legacy/standard transcript.json into a typed Transcript."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # Tolerate either a dict with 'segments' or a bare list.
    if isinstance(data, list):
        segments_data = data
        meta: dict = {}
    else:
        segments_data = data.get("segments", []) or []
        meta = data

    segments = tuple(_segment_from_dict(it) for it in segments_data if isinstance(it, dict))
    duration = float(meta.get("duration", meta.get("duration_s", 0.0)) or 0.0)
    if duration == 0.0 and segments:
        duration = segments[-1].end_s - segments[0].start_s

    return Transcript(
        segments=segments,
        source_file=str(path),
        engine=str(meta.get("engine", "unknown")),
        language=str(meta.get("language", "zh")),
        duration_s=duration,
    )


def load_transcript_aligned_json(path: str | Path) -> Transcript:
    """Alias kept explicit: aligned transcripts have the same shape."""
    return load_transcript_json(path)

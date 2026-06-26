"""Stage 2: forced alignment (word-level timestamps).

Public contract::

    def align(transcript: Transcript, aligner: Aligner) -> Transcript

BibbGPT-inspired optimisation: if the ASR engine already returned word-level
timestamps (``Segment.words`` populated and trustworthy), this stage
**pass-throughs** without re-aligning. Only ASR engines without word timing
need a real Aligner (e.g. MMS wav2vec2, mirroring legacy forced_aligner.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from garden_core.types import Segment, Transcript

__all__ = ["Aligner", "align", "_segments_have_word_timing"]


class Aligner(ABC):
    """Abstract aligner. Stateful — load model once, reuse across calls."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def align_segment(self, audio_path: str, segment: Segment) -> Segment:
        """Return a new Segment with ``words`` populated."""

    @property
    def needs_audio(self) -> bool:
        """Whether this aligner needs the raw audio (most do)."""
        return True


def _segments_have_word_timing(transcript: Transcript) -> bool:
    """True if every segment already carries non-empty, plausible word timing.

    Used to decide whether stage 2 can be a no-op (BibbGPT skip-if-accurate).
    """
    if not transcript.segments:
        return False
    for seg in transcript.segments:
        if not seg.words:
            return False
        # Plausibility: words must cover most of the segment span.
        if seg.words[0].start_s > seg.start_s + 1.0:
            return False
        if seg.words[-1].end_s < seg.end_s - 1.0:
            return False
    return True


def align(transcript: Transcript, aligner: Aligner, audio_path: str) -> Transcript:
    """Run stage 2: fill word-level timing. No-op if already aligned.

    Step API: part of ``garden_core.steps``. Persist via
    ``save_transcript_json`` / reload via ``load_transcript_json``.
    """
    if _segments_have_word_timing(transcript):
        return transcript
    if not aligner.needs_audio:
        new_segs = tuple(aligner.align_segment("", s) for s in transcript.segments)
    else:
        new_segs = tuple(aligner.align_segment(audio_path, s) for s in transcript.segments)
    from dataclasses import replace as _replace
    return _replace(transcript, segments=new_segs)

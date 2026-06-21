"""Gap healing: detect "has speech, no subtitle" regions and re-transcribe them.

Rewritten from legacy gap_healer.py with the critical fix to **bug #5**: the
old ``_insert_segments`` only sorted, never deduplicated, so repeated heal
rounds could insert duplicate/overlapping segments — and subtitle overlap is a
hard-fail invariant in this project. Here:

  * ``insert_segments`` merges by interval: any new segment that overlaps an
    existing one (by > tolerance) is dropped, and near-duplicates (same text,
    close times) are collapsed.
  * Gap detection is self-contained (a simple energy/VAD heuristic) rather than
    depending on an external subtitle_audio_checker JSON.
  * The result is verified to contain NO overlapping subtitles before return;
    if it would, we keep the pre-merge transcript (fail-safe, not silent).

The re-transcribe step needs a Transcriber (FunASR) injected — when none is
provided, healing degrades to gap *reporting* only (no silent data invention).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["Gap", "detect_gaps", "insert_segments", "heal_gaps", "has_overlaps"]

# A "gap" is a speech-containing region longer than this with no subtitle.
DEFAULT_MIN_GAP_S = 1.5
# Two segments are considered overlapping if their time spans intersect by more
# than this many seconds (small slivers are tolerated).
OVERLAP_TOLERANCE_S = 0.05


@dataclass(frozen=True)
class Gap:
    """A detected speech region with no subtitle coverage."""

    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def has_overlaps(transcript: Transcript, tolerance: float = OVERLAP_TOLERANCE_S) -> bool:
    """True if any two consecutive segments overlap beyond tolerance."""
    segs = sorted(transcript.segments, key=lambda s: s.start_s)
    for a, b in zip(segs, segs[1:]):
        if a.end_s - b.start_s > tolerance:
            return True
    return False


def detect_gaps(
    transcript: Transcript,
    audio_path: str,
    *,
    min_gap_s: float = DEFAULT_MIN_GAP_S,
    silence_threshold_db: float = -40.0,
) -> list[Gap]:
    """Find speech regions in the audio with no subtitle coverage.

    Uses ffmpeg's silencedetect (energy-based VAD) to find speech spans, then
    subtracts the union of subtitle spans to find uncovered speech ≥ min_gap_s.
    Pure detection — does not invent transcript text.
    """
    if not audio_path or not os.path.exists(audio_path):
        log.warning("detect_gaps: no audio (%s) — returning no gaps", audio_path)
        return []

    speech_spans = _detect_speech_spans(audio_path, silence_threshold_db)
    if not speech_spans:
        return []

    # subtitle coverage intervals (sorted, merged)
    sub = sorted(((s.start_s, s.end_s) for s in transcript.segments), key=lambda x: x[0])
    merged_sub: list[list[float]] = []
    for st, en in sub:
        if merged_sub and st <= merged_sub[-1][1]:
            merged_sub[-1][1] = max(merged_sub[-1][1], en)
        else:
            merged_sub.append([st, en])

    gaps: list[Gap] = []
    for sp_start, sp_end in speech_spans:
        if sp_end - sp_start < min_gap_s:
            continue
        # subtract each covered sub-interval from [sp_start, sp_end]
        uncovered = [(sp_start, sp_end)]
        for cst, cen in merged_sub:
            if cen <= sp_start or cst >= sp_end:
                continue
            new_unc = []
            for ust, uen in uncovered:
                if cen <= ust or cst >= uen:
                    new_unc.append((ust, uen))  # no overlap
                    continue
                if cst > ust:
                    new_unc.append((ust, cst))
                if cen < uen:
                    new_unc.append((cen, uen))
            uncovered = new_unc
        for ust, uen in uncovered:
            if uen - ust >= min_gap_s:
                gaps.append(Gap(start_s=ust, end_s=uen))
    return gaps


def insert_segments(
    transcript: Transcript, new_segs: list[Segment],
    tolerance: float = OVERLAP_TOLERANCE_S,
) -> Transcript:
    """Merge new segments into the transcript, deduplicating by overlap.

    **Fixes bug #5**: the legacy code only sorted. Here a new segment is dropped
    if it overlaps an existing one (beyond tolerance) OR is a near-duplicate
    (same text and close times). The merge is fail-safe: if the result would
    contain overlaps, the original transcript is returned unchanged.
    """
    from dataclasses import replace as _replace

    existing = sorted(transcript.segments, key=lambda s: s.start_s)
    accepted: list[Segment] = []
    for cand in sorted(new_segs, key=lambda s: s.start_s):
        if _overlaps_any(cand, existing, tolerance):
            log.debug("drop overlapping heal segment: %.1f-%.1f %r",
                      cand.start_s, cand.end_s, cand.text[:20])
            continue
        if _is_duplicate(cand, existing):
            log.debug("drop duplicate heal segment: %r", cand.text[:20])
            continue
        accepted.append(cand)
        existing.append(cand)
        existing.sort(key=lambda s: s.start_s)

    if not accepted:
        return transcript

    # fail-safe: never return an overlapping transcript
    merged = tuple(existing)
    probe = Transcript(
        segments=merged, source_file=transcript.source_file, engine=transcript.engine,
        language=transcript.language, duration_s=transcript.duration_s,
    )
    if has_overlaps(probe, tolerance):
        log.error("insert_segments would create overlaps — keeping original transcript")
        return transcript
    return _replace(transcript, segments=merged)


def _overlaps_any(seg: Segment, others: list[Segment], tolerance: float) -> bool:
    for o in others:
        if seg.start_s < o.end_s - tolerance and o.start_s < seg.end_s - tolerance:
            return True
    return False


def _is_duplicate(cand: Segment, others: list[Segment]) -> bool:
    """Near-duplicate: same text and very close start time."""
    for o in others:
        if o.text.strip() == cand.text.strip() and abs(o.start_s - cand.start_s) < 0.5:
            return True
    return False


def _detect_speech_spans(audio_path: str, silence_db: float) -> list[tuple[float, float]]:
    """Invert silencedetect output into speech spans."""
    cmd = ["ffmpeg", "-i", audio_path, "-af",
           f"silencedetect=noise={silence_db}dB:d=0.3", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning("silencedetect failed: %s", e)
        return []
    stderr = r.stderr or ""
    # parse silence_start / silence_end lines
    starts: list[float] = []
    ends: list[float] = []
    for line in stderr.splitlines():
        low = line.lower()
        if "silence_start:" in low:
            try:
                starts.append(float(low.split("silence_start:")[1].strip()))
            except (ValueError, IndexError):
                pass
        elif "silence_end:" in low:
            try:
                ends.append(float(low.split("silence_end:")[1].strip().split()[0]))
            except (ValueError, IndexError):
                pass
    # speech = gaps between silence regions. If audio starts with speech,
    # there's no leading silence_start, so speech begins at 0.
    spans: list[tuple[float, float]] = []
    prev_end = 0.0
    for s_start in starts:
        if s_start > prev_end + 0.01:
            spans.append((prev_end, s_start))
        # find the matching silence_end after this start
    # simpler robust approach: speech is [end_i, start_{i+1}]
    if ends and starts:
        # interleave: speech runs from each silence_end to the next silence_start
        paired = []
        si = 0
        for e in ends:
            # next start after this end
            while si < len(starts) and starts[si] <= e:
                si += 1
            if si < len(starts):
                paired.append((e, starts[si]))
        spans.extend(paired)
        # leading speech before first silence
        if starts and starts[0] > 0.01:
            spans.append((0.0, starts[0]))
    return spans


def heal_gaps(
    transcript: Transcript,
    audio_path: str,
    transcriber: Optional[Callable[[str, float, float], list[Segment]]] = None,
    *,
    min_gap_s: float = DEFAULT_MIN_GAP_S,
    max_rounds: int = 5,
) -> tuple[Transcript, list[Gap]]:
    """Detect + heal gaps. Returns (healed transcript, final gap list).

    ``transcriber`` is a callable (audio_path, start_s, end_s) -> [Segment]
    (e.g. wrapping FunASRBackend on a slice). When None, only detection runs —
    no transcript text is invented (fail-safe).
    """
    current = transcript
    all_unfilled: list[Gap] = []
    for rnd in range(1, max_rounds + 1):
        gaps = detect_gaps(current, audio_path, min_gap_s=min_gap_s)
        if not gaps:
            log.info("heal_gaps: round %d — no gaps remain", rnd)
            break
        log.info("heal_gaps: round %d — %d gaps", rnd, len(gaps))
        if transcriber is None:
            all_unfilled.extend(gaps)
            break  # detection-only mode
        new_segs: list[Segment] = []
        for g in gaps:
            try:
                segs = transcriber(audio_path, g.start_s, g.end_s)
            except Exception as e:
                log.warning("gap transcribe failed [%s]: %s", g, e)
                continue
            new_segs.extend(segs)
        current = insert_segments(current, new_segs)
        all_unfilled = detect_gaps(current, audio_path, min_gap_s=min_gap_s)
        if not all_unfilled:
            break
    return current, all_unfilled

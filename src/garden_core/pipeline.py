"""Pipeline orchestration: wire the 7 stages into one call.

This is a *library* API, not a watcher. The caller injects all stateful engines
(transcriber / aligner / llm / style resolver). The cross-boundary watcher /
HTTP-service layer is intentionally out of scope for this rewrite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from garden_core.infra.llm_client import LLMClient, NoLLMClient
from garden_core.stage_align import Aligner, align
from garden_core.stage_asr import AudioRef, Transcriber, transcribe
from garden_core.stage_cut import cut
from garden_core.stage_proofread import ErrataConfig, ProofOptions, proofread
from garden_core.stage_render import RenderOptions, render
from garden_core.stage_segment import SegmentOptions, segment
from garden_core.stage_style import StyleResolver, resolve_style
from garden_core.types import CutPoint, Cue, RenderResult, Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["Engines", "PipelineOptions", "run_from_audio", "run_from_transcript"]


@dataclass(frozen=True)
class Engines:
    """All stateful engines, injected once, reused across the whole run."""

    transcriber: Optional[Transcriber] = None
    aligner: Optional[Aligner] = None
    llm: LLMClient = field(default_factory=NoLLMClient)
    style_resolver: Optional[StyleResolver] = None


@dataclass(frozen=True)
class PipelineOptions:
    hotwords: tuple[str, ...] = ()
    errata: ErrataConfig = field(default_factory=ErrataConfig.empty)
    proof: ProofOptions = field(default_factory=ProofOptions)
    segment: SegmentOptions = field(default_factory=SegmentOptions)
    render: Optional[RenderOptions] = None
    video_height: int = 1080  # used when no source video probing is available
    # When rendering from a transcript loaded out-of-band, transcript.source_file
    # is usually the JSON path, NOT the media. Set this to the actual source
    # video/audio so cut() / render() address the right file.
    source_media: str = ""
    heal_gaps: bool = False        # run gap healing before segmentation
    heal_max_rounds: int = 5


def run_from_transcript(
    transcript: Transcript,
    cut_points: list[CutPoint],
    style_name: str,
    engines: Engines,
    opts: PipelineOptions,
    audio_path: str = "",
) -> list[RenderResult]:
    """Run stages 2–7 starting from an existing Transcript.

    Use this for the execute-layer loop (Milestone 1 entry): you already have a
    transcript (e.g. loaded from legacy JSON) and want rendered clips out.
    ``opts.source_media`` should point at the real source video/audio —
    ``transcript.source_file`` alone is often just the JSON path.
    """
    # Stage 2: align (no-op if word timing already present).
    if engines.aligner:
        transcript = align(transcript, engines.aligner, audio_path)
    else:
        log.info("no aligner provided — skipping stage 2 (transcript used as-is)")

    # Stage 3: proofread.
    transcript = proofread(transcript, opts.errata, engines.llm, opts.proof, audio_path)

    # Optional: heal gaps (speech-with-no-subtitle) before segmentation.
    if opts.heal_gaps and audio_path:
        from garden_core.stage_segment.gap_heal import heal_gaps
        transcript, unfilled = heal_gaps(
            transcript, audio_path,
            transcriber=_make_gap_transcriber(engines.transcriber) if engines.transcriber else None,
            max_rounds=opts.heal_max_rounds,
        )
        if unfilled:
            log.warning("gap healing left %d unfilled gaps (no recoverable speech)", len(unfilled))

    # Stage 4: segment.
    cues = segment(transcript, opts.segment)

    # Pipeline-wide invariant: subtitle cues must never overlap. This is the
    # project's hard quality rule. If segmentation somehow produced overlaps,
    # we fix them defensively rather than emit bad output.
    from garden_core.stage_segment.gap_heal import has_overlaps
    if has_overlaps(_cues_as_transcript(cues)):
        log.warning("segmentation produced overlapping cues — flattening")
        cues = _flatten_overlaps(cues)

    # Stage 5: cut.
    plans = cut(transcript, cues, cut_points)
    # Override source_ref with the real media file when provided (the loaded
    # transcript's source_file is often the JSON path, not the media).
    if opts.source_media:
        from dataclasses import replace as _replace
        plans = tuple(_replace(p, source_ref=opts.source_media) for p in plans)

    # Stages 6 + 7: style + render per clip.
    results: list[RenderResult] = []
    for plan in plans:
        resolver = engines.style_resolver
        if resolver:
            style = resolve_style(style_name or plan.style_name, opts.video_height, resolver)
        else:
            # No resolver injected → fall back to the built-in mold system so
            # named styles (cinematic, broadcast, …) still resolve properly.
            from garden_core.stage_style.molds import YamlStyleResolver
            resolver = YamlStyleResolver()
            style = resolve_style(style_name or plan.style_name, opts.video_height, resolver)
        if opts.render is None:
            log.warning("no RenderOptions — skipping render, returning plans only")
            continue
        results.append(render(plan, style, opts.render))
    return results


def run_from_audio(
    audio_path: str,
    cut_points: list[CutPoint],
    style_name: str,
    engines: Engines,
    opts: PipelineOptions,
) -> list[RenderResult]:
    """Run the full chain (stages 1–7): audio → rendered clips.

    Requires ``engines.transcriber``. This is the full-loop entrypoint
    (Milestone 2+).
    """
    if engines.transcriber is None:
        raise ValueError("run_from_audio requires engines.transcriber")
    transcript = transcribe(AudioRef(path=audio_path), engines.transcriber, opts.hotwords)
    return run_from_transcript(
        transcript, cut_points, style_name, engines, opts, audio_path=audio_path,
    )


# --------------------------------------------------------------------------- #
# Internal helpers for gap healing + overlap invariants
# --------------------------------------------------------------------------- #
def _cues_as_transcript(cues):
    """Adapt Cues into Segments so has_overlaps/insert_segments can inspect them."""
    return Transcript(
        segments=tuple(
            Segment(text=c.text, start_s=c.start_s, end_s=c.end_s) for c in cues
        ),
        source_file="", engine="",
    )


def _flatten_overlaps(cues):
    """Defensively resolve any cue overlaps by trimming the earlier cue's end.

    The segmenter already tries to avoid overlaps, but if one slips through we
    trim rather than emit overlapping subtitles (hard quality rule).
    """
    ordered = sorted(cues, key=lambda c: c.start_s)
    out = []
    for c in ordered:
        if out and c.start_s < out[-1].end_s - 0.01:
            # trim previous cue to this one's start
            prev = out[-1]
            out[-1] = Cue(index=prev.index, text=prev.text,
                          start_s=prev.start_s, end_s=max(prev.start_s + 0.1, c.start_s - 0.05),
                          text_en=prev.text_en)
        out.append(c)
    return tuple(out)


def _make_gap_transcriber(transcriber):
    """Wrap a stage-1 Transcriber into the (audio, start_s, end_s) -> [Segment]
    callable that heal_gaps expects, by slicing audio and rebasing timestamps.
    """
    import os
    import subprocess
    import tempfile

    def transcribe_slice(audio_path: str, start_s: float, end_s: float):
        from garden_core.stage_asr import AudioRef
        # FunASRBackend chunks internally, but for a small gap slice we feed the
        # slice directly so timestamps come back relative to the slice origin.
        tmp = tempfile.mktemp(suffix=".wav")
        try:
            cmd = ["ffmpeg", "-y", "-ss", str(start_s), "-to", str(end_s),
                   "-i", audio_path, "-ar", "16000", "-ac", "1", tmp]
            subprocess.run(cmd, capture_output=True, check=True)
            res = transcriber.transcribe(AudioRef(path=tmp, duration_s=end_s - start_s))
            # rebase slice-relative timestamps back to source timeline
            from dataclasses import replace as _replace
            return [
                _replace(s, start_s=s.start_s + start_s, end_s=s.end_s + start_s)
                for s in res.segments
            ]
        except Exception as e:
            log.warning("gap slice transcribe failed [%s-%s]: %s", start_s, end_s, e)
            return []
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    return transcribe_slice

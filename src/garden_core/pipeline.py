"""Pipeline orchestration: wire the 7 stages into one call.

This is a *library* API, not a watcher. The caller injects all stateful engines
(transcriber / aligner / llm / style resolver). The cross-boundary watcher /
HTTP-service layer is intentionally out of scope for this rewrite.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from typing import Optional

from garden_core.infra.llm_client import LLMClient, NoLLMClient
from garden_core.stage_align import Aligner, align
from garden_core.stage_asr import AudioRef, Transcriber, transcribe
from garden_core.stage_cut import cut
from garden_core.stage_proofread import ErrataConfig, ProofOptions, proofread
from garden_core.stage_render import RenderOptions, render
from garden_core.stage_segment import SegmentOptions, segment
from garden_core.stage_style import StyleResolver, resolve_style
from garden_core.types import ClipPlan, CutPoint, Cue, RenderResult, Segment, Transcript

log = logging.getLogger(__name__)

__all__ = [
    "Engines",
    "PipelineOptions",
    "run_from_audio",
    "run_from_transcript",
    "run_montage",
]


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
    render_gate: bool = True        # mechanical post-render quality gate (BLOCKs bad clips)


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
    plans = _prepare_plans(transcript, cut_points, engines, opts, audio_path)
    return _render_plans(plans, style_name, engines, opts)


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


def run_montage(
    transcript: Transcript,
    cut_points: list[CutPoint],
    style_name: str,
    engines: Engines,
    opts: PipelineOptions,
    montage_id: str = "montage",
    audio_path: str = "",
) -> RenderResult:
    """Splice N source windows into ONE continuous horizontal video (montage).

    This is the "fine-cut / mix-cut" entry point, complementary to
    ``run_from_transcript`` (which emits one independent clip per CutPoint).
    Each window is rendered to its own subtitle-burned horizontal mp4 through
    the very same cut → style → render stages, then the clips are joined into a
    single continuous video with ffmpeg's concat demuxer.

    **Output order == the cut_points list order**, which may differ from source
    chronology — that is the whole point: a wrap-up segment that sits early in
    the source can be placed last simply by listing its CutPoint last. ``cut()``
    and ``render()`` never reorder, so the rendered clips keep that order.

    The companion ``.srt`` / ``.ass`` carry a *continuous, non-overlapping*
    timeline: each clip's clip-local cues are shifted by the cumulative
    duration of the preceding clips (measured from the actual rendered mp4s, so
    the subtitles line up with the joined video) and concatenated. A defensive
    overlap-flatten guards the clip boundaries against sub-frame drift.

    Only the horizontal montage is produced (4K is selected via
    ``opts.render.horizontal_width/height``). Pass ``render_vertical=False`` in
    ``opts.render`` to skip the unused per-clip vertical renders.
    """
    if opts.render is None:
        raise ValueError("run_montage requires opts.render (RenderOptions)")

    plans = _prepare_plans(transcript, cut_points, engines, opts, audio_path)
    if not plans:
        raise ValueError("run_montage: no clip plans (empty cut_points?)")

    # Stages 6–7: render every window to its own horizontal clip (in order).
    results = _render_plans(plans, style_name, engines, opts)

    seg_mp4s: list[str] = []
    for plan, res in zip(plans, results):
        if not (res.horizontal_mp4 and os.path.exists(res.horizontal_mp4)):
            raise ValueError(
                f"run_montage: segment {plan.clip_id!r} produced no horizontal mp4"
            )
        seg_mp4s.append(res.horizontal_mp4)

    # Join the rendered clips into one continuous video, in output order.
    from garden_core.stage_render.concat import concat_videos
    out_dir = opts.render.output_dir
    long_mp4 = os.path.join(out_dir, f"{montage_id}_horizontal.mp4")
    joined = concat_videos(seg_mp4s, long_mp4)
    if not joined:
        raise ValueError("run_montage: ffmpeg concat failed (see log)")

    # Rebuild a single continuous subtitle timeline: shift each clip's
    # clip-local cues by the cumulative ACTUAL duration of preceding clips.
    merged_cues: list[Cue] = []
    seg_durations: list[float] = []
    offset = 0.0
    running = 0
    for plan, mp4 in zip(plans, seg_mp4s):
        for cue in plan.cues:
            merged_cues.append(replace(
                cue, index=running,
                start_s=cue.start_s + offset,
                end_s=cue.end_s + offset,
            ))
            running += 1
        dur = _probe_duration(mp4, fallback=plan.duration_s)
        seg_durations.append(dur)
        offset += dur

    # Defensive: sub-frame mp4-duration drift could nudge a clip's last cue past
    # the next clip's start. Flatten any such overlap (hard quality rule).
    flat = _flatten_overlaps(tuple(merged_cues))
    merged_cues = [replace(c, index=i) for i, c in enumerate(flat)]

    from garden_core.io_.sink import write_text_file
    from garden_core.stage_render.ass_writer import build_ass
    from garden_core.stage_render.srt_writer import build_srt

    style = _resolve_style_for(plans[0], style_name, engines, opts)
    merged_plan = ClipPlan(
        clip_id=montage_id,
        source_ref=joined,
        start_s=0.0,
        end_s=offset,
        cues=tuple(merged_cues),
        style_name=style.name,
        title=montage_id,
    )
    srt_path = write_text_file(
        os.path.join(out_dir, f"{montage_id}.srt"), build_srt(merged_plan),
    )
    ass_path = write_text_file(
        os.path.join(out_dir, f"{montage_id}.ass"),
        build_ass(merged_plan, style, opts.render.horizontal_height),
    )

    return RenderResult(
        clip_id=montage_id,
        horizontal_mp4=joined,
        vertical_mp4="",
        srt_path=srt_path,
        ass_path=ass_path,
        metadata={
            "kind": "montage",
            "style": style.name,
            "duration_s": offset,
            "cues": len(merged_cues),
            "segments": [
                {
                    "clip_id": p.clip_id,
                    "source_start_s": p.start_s,
                    "source_end_s": p.end_s,
                    "duration_s": d,
                    "cues": len(p.cues),
                }
                for p, d in zip(plans, seg_durations)
            ],
        },
    )


def _probe_duration(mp4_path: str, fallback: float) -> float:
    """Actual duration of a rendered mp4 (ffprobe), or ``fallback`` if unknown."""
    from garden_core.infra.media_probe import probe_media
    info = probe_media(mp4_path)
    if info and info.duration_s > 0:
        return info.duration_s
    log.warning("could not probe duration of %s — using nominal %.3fs", mp4_path, fallback)
    return fallback


# --------------------------------------------------------------------------- #
# Internal helpers for gap healing + overlap invariants
# --------------------------------------------------------------------------- #
def _prepare_plans(
    transcript: Transcript,
    cut_points: list[CutPoint],
    engines: Engines,
    opts: PipelineOptions,
    audio_path: str,
) -> tuple[ClipPlan, ...]:
    """Stages 2–5: transcript → ClipPlans (one per CutPoint, in input order).

    Shared by run_from_transcript and run_montage. The CutPoint *list order is
    preserved* into the returned plans, so callers control output ordering
    (this is what lets a montage place an earlier-in-source segment last).
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
    return plans


def _resolve_style_for(plan: ClipPlan, style_name: str, engines: Engines, opts: PipelineOptions):
    resolver = engines.style_resolver
    if resolver is None:
        # No resolver injected → fall back to the built-in mold system so
        # named styles (cinematic, broadcast, …) still resolve properly.
        from garden_core.stage_style.molds import YamlStyleResolver
        resolver = YamlStyleResolver()
    return resolve_style(style_name or plan.style_name, opts.video_height, resolver)


def _render_plans(
    plans: tuple[ClipPlan, ...],
    style_name: str,
    engines: Engines,
    opts: PipelineOptions,
) -> list[RenderResult]:
    """Stages 6–7: render each plan to its own clip + run the render gate.

    Shared by run_from_transcript and run_montage. Returns one RenderResult per
    plan, in plan (== CutPoint input) order.
    """
    results: list[RenderResult] = []
    for plan in plans:
        style = _resolve_style_for(plan, style_name, engines, opts)
        if opts.render is None:
            log.warning("no RenderOptions — skipping render, returning plans only")
            continue
        results.append(render(plan, style, opts.render))

    # Independent mechanical render gate: read the rendered ASS artifacts and
    # verify hard, machine-computable specs (font-size ratio consistency,
    # subtitle safe area, Simplified-Chinese). Zero LLM. It does NOT touch
    # render logic; on failure it BLOCKs loudly (RenderGateError) so a human
    # decides — it never auto-fixes a clip.
    if opts.render_gate and results:
        from garden_core.stage_render.render_gate import gate_results
        gate_results(results)
    return results


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
        # FunASRLocal transcribes whole files, but for a small gap slice we feed
        # the slice directly so timestamps come back relative to the slice origin.
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

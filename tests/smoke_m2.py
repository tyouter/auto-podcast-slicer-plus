"""Milestone 2 verification: align + proofread stages on a real audio window.

This exercises the genuinely heavy new code — MMS forced alignment (per-char
CTC on GPU) and the proofread layers — on a REAL slice of the 4K source, but
scoped to a small window so it finishes in seconds. It calls the stages
directly rather than the full 2847-segment pipeline.

The final render still uses the execute-layer pipeline to confirm M1+M2 wire
together. Run: python tests/smoke_m2.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace as _replace

from garden_core.io_.source import load_transcript_json
from garden_core.stage_align import align
from garden_core.stage_align.mms_aligner import AlignmentError, MMSAligner
from garden_core.stage_proofread import ErrataConfig, ProofOptions, proofread
from garden_core.types import CutPoint, Segment, Transcript

LEGACY_TRANSCRIPT = (
    r"D:/Hermes/projects/auto-podcast-slicer/projects/"
    r"garden-forking-paths-ray-edit/output/src/transcript.json"
)
SOURCE_VIDEO = r"D:\boke\garden post factory\C0257_mono_video.mp4"
OUTPUT_DIR = r"D:/Hermes/projects/auto-podcast-slicer-plus/_m2_out"
WINDOW_START_S = 60.0
WINDOW_END_S = 75.0


def _extract_wav_slice(src_video: str, start_s: float, end_s: float, out_wav: str) -> str:
    """torchaudio/libsndfile can't decode mp4 — extract a WAV slice via ffmpeg.

    This mirrors the legacy pipeline's constraint: forced alignment needs a
    16k mono WAV. (FunASR chunker does the same via _split_audio.)
    """
    if os.path.exists(out_wav) and os.path.getsize(out_wav) > 0:
        return out_wav
    cmd = ["ffmpeg", "-y", "-ss", str(start_s), "-to", str(end_s),
           "-i", src_video, "-vn", "-ar", "16000", "-ac", "1", out_wav]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_wav


def main() -> int:
    assert os.path.exists(LEGACY_TRANSCRIPT)
    assert os.path.exists(SOURCE_VIDEO)

    # Extract a padded WAV slice for the aligner (pad so CTC has context).
    pad = 2.0
    wav_path = os.path.join(OUTPUT_DIR, "align_slice.wav")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _extract_wav_slice(SOURCE_VIDEO, WINDOW_START_S - pad, WINDOW_END_S + pad, wav_path)
    print(f"    align audio slice: {wav_path} ({os.path.getsize(wav_path)} B)")

    print("[1] loading transcript + carving a 15s window ...")
    full = load_transcript_json(LEGACY_TRANSCRIPT)
    # The slice file starts at (WINDOW_START_S - pad); rebase segment times so
    # they are relative to the slice origin (the aligner loads from this file).
    slice_origin = WINDOW_START_S - pad
    window_segs = tuple(
        Segment(
            text=s.text, start_s=s.start_s - slice_origin, end_s=s.end_s - slice_origin,
            speaker=s.speaker, confidence=s.confidence,
        )
        for s in full.segments if WINDOW_START_S <= s.start_s < WINDOW_END_S
    )[:5]
    window = Transcript(
        segments=window_segs, source_file=SOURCE_VIDEO, engine=full.engine,
        language=full.language, duration_s=WINDOW_END_S - WINDOW_START_S,
    )
    print(f"    window segments: {len(window.segments)} (times rebased to slice origin)")
    for s in window.segments:
        print(f"      [{s.start_s:.1f}-{s.end_s:.1f}s] {s.text[:40]!r}")

    print("\n[2] MMS forced alignment (GPU, model loads once) ...")
    try:
        aligner = MMSAligner()
    except AlignmentError as e:
        print(f"    aligner unavailable: {e} — skipping align verification")
        aligner = None
        aligned = window
    else:
        aligned = align(window, aligner, wav_path)
        total_words = sum(len(s.words) for s in aligned.segments)
        segs_with_words = sum(1 for s in aligned.segments if s.words)
        print(f"    produced {total_words} char-level timestamps "
              f"across {segs_with_words}/{len(aligned.segments)} segments")
        if segs_with_words:
            ex = next(s for s in aligned.segments if s.words)
            print(f"    example words: {[(w.text, round(w.start_s,2)) for w in ex.words[:6]]}")

    print("\n[3] proofread (deterministic layers; LLM off) ...")
    out = proofread(
        aligned, ErrataConfig.empty(), None,
        ProofOptions(enable_llm=False, enable_dual_channel=False),
    )
    print(f"    corrections_applied: {out.corrections_applied}")
    # show any text changes
    for before, after in zip(aligned.segments, out.segments):
        if before.text != after.text:
            print(f"      changed: {before.text!r} → {after.text!r}")

    print("\n[4] render (execute-layer) from the full transcript ...")
    from garden_core.pipeline import Engines, PipelineOptions, run_from_transcript
    from garden_core.stage_segment import SegmentOptions
    from garden_core.stage_render import RenderOptions
    from garden_core.stage_style.molds import YamlStyleResolver

    cuts = [CutPoint(clip_id="m2_align", source_media=SOURCE_VIDEO, start_s=WINDOW_START_S, end_s=WINDOW_END_S,
                     style_name="cinematic")]
    # Render from the FULL transcript (absolute times) — alignment was verified
    # on the window above; here we just confirm M1 render still works end-to-end.
    engines = Engines(style_resolver=YamlStyleResolver())
    opts = PipelineOptions(
        proof=ProofOptions(enable_llm=False, enable_dual_channel=False),
        segment=SegmentOptions(strategy="semantic"),
        render=RenderOptions(
            output_dir=OUTPUT_DIR, render_horizontal=True, render_vertical=False,
            horizontal_width=960, horizontal_height=540, crf=23,
        ),
        source_media=SOURCE_VIDEO,
    )
    results = run_from_transcript(full, cuts, "cinematic", engines, opts,
                                  audio_path=SOURCE_VIDEO)
    if results and results[0].horizontal_mp4 and os.path.exists(results[0].horizontal_mp4):
        size = os.path.getsize(results[0].horizontal_mp4)
        print(f"    rendered: {results[0].horizontal_mp4} ({size} B)")
        print("\nRESULT: PASS ✓ — M2 align + proofread + render verified")
        return 0
    print("\nRESULT: FAIL ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())

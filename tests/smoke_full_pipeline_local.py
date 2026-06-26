"""Full pipeline test using FunASR Python SDK directly (no MCP server).

Bypasses the MCP transport layer to test the real ASR→render pipeline
end-to-end. The MCP server is a deployment concern; the transcription
quality is what matters here.
"""

from __future__ import annotations

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from garden_core.pipeline import Engines, PipelineOptions
from garden_core.stage_asr import AudioRef, FunASRLocal
from garden_core.stage_proofread import ProofOptions
from garden_core.stage_segment import SegmentOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

# ---- config ----------------------------------------------------------------
AUDIO_CLIP = r"D:/Hermes/projects/auto-podcast-slicer-plus/_m3_out/test_clip.wav"
SOURCE_VIDEO = r"D:\boke\garden post factory\C0257_mono_video.mp4"
OUTPUT_DIR = r"D:/Hermes/projects/auto-podcast-slicer-plus/_m3_out/full_pipeline"


def main() -> int:
    assert os.path.exists(AUDIO_CLIP), f"audio clip missing: {AUDIO_CLIP}"
    assert os.path.exists(SOURCE_VIDEO), f"source video missing: {SOURCE_VIDEO}"

    from garden_core.pipeline import run_from_transcript

    print("[1] Transcribing with FunASR AutoModel (local GPU) ...")
    transcriber = FunASRLocal(device="cuda")
    transcript = transcriber.transcribe(AudioRef(path=AUDIO_CLIP))
    print(f"    Transcript: {len(transcript.segments)} segments")
    for i, seg in enumerate(transcript.segments[:5]):
        print(f"    [{i}] {seg.text[:40]}... {seg.start_s:.1f}-{seg.end_s:.1f}s")

    engines = Engines(
        transcriber=None,
        aligner=None,
        llm=None,
        style_resolver=None,
    )

    opts = PipelineOptions(
        proof=ProofOptions(
            enable_normalize=True,
            enable_errata=False,
            enable_phonetic=True,
            enable_llm=False,
            enable_dual_channel=False,
        ),
        segment=SegmentOptions(strategy="semantic"),
        render=RenderOptions(
            output_dir=OUTPUT_DIR,
            render_horizontal=True,
            render_vertical=True,
            horizontal_width=960,
            horizontal_height=540,
            vertical_width=540,
            vertical_height=960,
            crf=23,
        ),
        video_height=2160,
        source_media=SOURCE_VIDEO,
    )

    cut_point = CutPoint(clip_id="full_pipeline_demo", source_media=SOURCE_VIDEO, start_s=10.0, end_s=50.0,
                         style_name="cinematic", title="Full Pipeline Demo")

    print(f"\n[2] Running stages 2-7: align(noop) -> proofread -> segment -> cut -> style -> render")
    results = run_from_transcript(
        transcript, [cut_point], "cinematic", engines, opts,
        audio_path=AUDIO_CLIP,
    )

    if not results:
        print("\nFAIL: no render results")
        return 1

    r = results[0]
    ok = True
    print(f"\n[3] Results for clip '{r.clip_id}':")
    for label, path in [("SRT", r.srt_path), ("ASS", r.ass_path),
                         ("Horizontal MP4", r.horizontal_mp4),
                         ("Vertical MP4", r.vertical_mp4)]:
        exists = os.path.exists(path) if path else False
        size = os.path.getsize(path) if exists else 0
        status = "OK" if (exists and size > 0) else "FAIL"
        print(f"    [{status}] {label}: {os.path.basename(path) if path else 'N/A'} ({size} B)")
        if not (exists and size > 0):
            ok = False

    if ok:
        print("\nRESULT: PASS -- full pipeline (ASR->render) works end-to-end!")
    else:
        print("\nRESULT: FAIL -- one or more outputs missing/empty")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

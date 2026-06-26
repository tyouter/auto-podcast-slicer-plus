"""Full end-to-end pipeline test: audio → ASR → align → proofread → segment → cut → render.

Exercises the ``run_from_audio`` entry point with the in-process ``FunASRLocal``
backend (ASR runs inside the pipeline). The transcript-first counterpart lives
in ``smoke_full_pipeline_local.py`` (``run_from_transcript``).
Run: python tests/smoke_full_pipeline.py
"""

from __future__ import annotations

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from garden_core.pipeline import Engines, PipelineOptions, run_from_audio
from garden_core.stage_asr import FunASRLocal
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

    # 1. Build engines — in-process FunASR on the local GPU.
    print("[1] Loading FunASR AutoModel (local GPU) ...")
    transcriber = FunASRLocal(device="cuda")

    engines = Engines(
        transcriber=transcriber,
        aligner=None,  # skip alignment for now
        llm=None,      # no LLM correction
        style_resolver=None,
    )

    # 2. Build options.
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

    # 3. Cut: first 60s of the clip.
    cut_point = CutPoint(clip_id="full_pipeline_demo", source_media=SOURCE_VIDEO, start_s=0.0, end_s=60.0,
                         style_name="cinematic", title="Full Pipeline Demo")

    print(f"[2] Running full pipeline: {AUDIO_CLIP}")
    print(f"    stages 1-7: ASR → align(noop) → proofread → segment → cut → style → render")
    results = run_from_audio(
        AUDIO_CLIP,
        [cut_point],
        "cinematic",
        engines,
        opts,
    )

    # 4. Verify outputs.
    if not results:
        print("\nFAIL: no render results — pipeline didn't produce any output")
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

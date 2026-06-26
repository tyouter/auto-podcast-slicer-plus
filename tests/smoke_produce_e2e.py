"""E2E smoke test for garden_core-based produce phase.
Tests one short clip from garden-production to verify the new pipeline works.
"""
import os
import sys

# Ensure garden_core is importable
GARDEN_CORE_SRC = r"D:\Hermes\projects\auto-podcast-slicer-plus\src"
sys.path.insert(0, GARDEN_CORE_SRC)

from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

TRANSCRIPT = r"D:\Hermes\projects\garden-production\output\transcript_aligned.json"
SOURCE_VIDEO = r"D:\Hermes\projects\podcast\garden in  forking pathies\garden in forking pathes podcast.mp4"
OUTPUT_DIR = r"D:\Hermes\projects\garden-production\output\_e2e_test"

def main():
    assert os.path.exists(TRANSCRIPT), f"Transcript missing: {TRANSCRIPT}"
    assert os.path.exists(SOURCE_VIDEO), f"Source video missing: {SOURCE_VIDEO}"

    print("[1] Loading transcript...")
    transcript = load_transcript_json(TRANSCRIPT)
    print(f"    segments={len(transcript.segments)} dur={transcript.duration_s:.0f}s")

    # Test with just one clip: AI_BIRD (20s, quick)
    cut_points = [
        CutPoint(
            clip_id="AI_BIRD",
            source_media=SOURCE_VIDEO,
            start_s=55.0,
            end_s=75.0,
            style_name="cinematic",
            title="报喜鸟 · 自然的第一个分岔",
        )
    ]

    print("[2] Running produce (garden_core pipeline)...")
    results = run_from_transcript(
        transcript,
        cut_points,
        style_name="cinematic",
        engines=Engines(),
        opts=PipelineOptions(
            source_media=SOURCE_VIDEO,
            render=RenderOptions(
                output_dir=OUTPUT_DIR,
                horizontal_width=3840,
                horizontal_height=2160,
                vertical_width=1080,
                vertical_height=1920,
                crf=20,
            ),
        ),
    )

    print(f"[3] Results: {len(results)} clip(s)")
    for r in results:
        h_ok = os.path.exists(r.horizontal_mp4) if r.horizontal_mp4 else False
        v_ok = os.path.exists(r.vertical_mp4) if r.vertical_mp4 else False
        print(f"    {r.clip_id}:")
        print(f"      horizontal: {r.horizontal_mp4} ({os.path.getsize(r.horizontal_mp4)//1024}KB)" if h_ok else f"      horizontal: FAILED")
        print(f"      vertical:   {r.vertical_mp4} ({os.path.getsize(r.vertical_mp4)//1024}KB)" if v_ok else f"      vertical:   FAILED")
        print(f"      cues: {r.metadata.get('cues', '?')}")

    ok = all(r.horizontal_mp4 and r.vertical_mp4 and os.path.exists(r.horizontal_mp4) and os.path.exists(r.vertical_mp4) for r in results)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())

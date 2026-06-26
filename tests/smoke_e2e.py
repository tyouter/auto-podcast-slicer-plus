"""End-to-end smoke test for Milestone 1.

Feeds a REAL legacy transcript (start_ms/end_ms format) through the execute
layer: load → segment → cut → style → ASS/SRT → ffmpeg → mp4.
Run directly: python tests/smoke_e2e.py
"""

from __future__ import annotations

import os
import sys

from garden_core.io_.source import load_transcript_json
from garden_core.stage_cut import cut
from garden_core.stage_render import RenderOptions, render
from garden_core.stage_segment import SegmentOptions, segment
from garden_core.stage_style import DEFAULT_STYLE
from garden_core.types import CutPoint

LEGACY_TRANSCRIPT = (
    r"D:/Hermes/projects/auto-podcast-slicer/projects/"
    r"garden-forking-paths-ray-edit/output/src/transcript.json"
)
# Real 4K source video (3840x2160, 5168s) matching the transcript duration.
SOURCE_VIDEO = r"D:\boke\garden post factory\C0257_mono_video.mp4"
OUTPUT_DIR = r"D:/Hermes/projects/auto-podcast-slicer-plus/_e2e_out"


def main() -> int:
    assert os.path.exists(LEGACY_TRANSCRIPT), "transcript missing"
    assert os.path.exists(SOURCE_VIDEO), "source video missing"

    print("[1] loading legacy transcript (start_ms/end_ms) ...")
    t = load_transcript_json(LEGACY_TRANSCRIPT)
    print(f"    segments={len(t.segments)} engine={t.engine} dur={t.duration_s:.0f}s")

    print("[2] segmenting (semantic) ...")
    cues = segment(t, SegmentOptions(strategy="semantic"))
    print(f"    cues={len(cues)}")
    print(f"    sample cue[0]: {cues[0].text[:30]!r} {cues[0].start_s:.1f}-{cues[0].end_s:.1f}s")

    # pick a cut window that has cues AND fits in the short source video.
    # First probe the source duration.
    from garden_core.infra.media_probe import probe_media
    info = probe_media(SOURCE_VIDEO)
    assert info, "could not probe source video"
    print(f"    source: {info.width}x{info.height} {info.duration_s:.1f}s fps={info.fps:.1f}")
    clip_end = min(10.0, info.duration_s)
    cut_point = CutPoint(clip_id="e2e_demo", source_media=SOURCE_VIDEO, start_s=0.0, end_s=clip_end,
                         style_name="cinematic", title="E2E Demo")

    print("[3] cutting ...")
    plans = cut(t, cues, [cut_point])
    assert plans, "no clip plan produced"
    plan = plans[0]
    # repoint source_ref to the actual source video on disk
    from dataclasses import replace as _replace
    plan = _replace(plan, source_ref=SOURCE_VIDEO)
    print(f"    clip cues={len(plan.cues)} window=0-{clip_end:.0f}s")

    print("[4] resolving style + rendering (ASS/SRT + ffmpeg) ...")
    from garden_core.stage_style.molds import YamlStyleResolver
    resolver = YamlStyleResolver()
    style = resolver.resolve("cinematic", info.height)

    # Render at a downscaled size for speed (4K source → 540p output); the
    # pipeline scales internally. Vertical enabled by default for this run.
    do_vertical = "--no-vertical" not in sys.argv
    result = render(plan, style, RenderOptions(
        output_dir=OUTPUT_DIR,
        render_horizontal=True,
        render_vertical=do_vertical,
        horizontal_width=960,
        horizontal_height=540,
        vertical_width=540,
        vertical_height=960,
        crf=23,
    ))
    print(f"    ass: {os.path.basename(result.ass_path)} ({os.path.getsize(result.ass_path)} B)")
    print(f"    srt: {os.path.basename(result.srt_path)} ({os.path.getsize(result.srt_path)} B)")
    print(f"    horizontal_mp4: {result.horizontal_mp4 or 'FAILED'}")
    if result.horizontal_mp4 and os.path.exists(result.horizontal_mp4):
        print(f"      size={os.path.getsize(result.horizontal_mp4)} B")
    print(f"    vertical_mp4:   {result.vertical_mp4 or 'FAILED'}")
    if result.vertical_mp4 and os.path.exists(result.vertical_mp4):
        print(f"      size={os.path.getsize(result.vertical_mp4)} B")

    ok = bool(result.horizontal_mp4 and result.vertical_mp4
              and os.path.exists(result.horizontal_mp4) and os.path.exists(result.vertical_mp4))
    print("\nRESULT:", "PASS ✓ — execute-layer loop works end-to-end" if ok else "FAIL ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

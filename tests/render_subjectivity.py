"""Render the '主体性讨论' clip (升级版, ~3.5min) from garden-production.
cinematic style, 4K horizontal + vertical.
"""
import os, sys, time
sys.path.insert(0, r"D:\Hermes\projects\auto-podcast-slicer-plus\src")

from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.stage_style.molds import YamlStyleResolver
from garden_core.types import CutPoint

# xr (font_size_ratio) is read from style config, never code. The resolver's
# default layer is garden_core's packaged styles/ (cinematic xr=0.078). To
# override per-project, pass config_dir=<project styles dir> (project wins).
STYLE_RESOLVER = YamlStyleResolver()

TRANSCRIPT = r"D:\Hermes\projects\garden-production\output\transcript_aligned.json"
SOURCE = r"D:\Hermes\projects\podcast\garden in  forking pathies\garden in forking pathes podcast.mp4"
OUTPUT = r"D:\Hermes\projects\garden-production\output\clips\subjectivity"

def main():
    t0 = time.time()
    transcript = load_transcript_json(TRANSCRIPT)
    print(f"[1] transcript: {len(transcript.segments)} segments", flush=True)

    cuts = [CutPoint(
        clip_id="EP01_SUBJECTIVITY",
        source_media=SOURCE,
        start_s=1800.93,
        end_s=2006.54,
        style_name="cinematic",
        title="主体性——可能性是被时间决定，还是被你的选择决定",
    )]

    print("[2] rendering (cinematic 4K, h+v)...", flush=True)
    results = run_from_transcript(
        transcript, cuts, style_name="cinematic",
        engines=Engines(style_resolver=STYLE_RESOLVER),
        opts=PipelineOptions(
            source_media=SOURCE,
            render=RenderOptions(output_dir=OUTPUT, horizontal_width=3840,
                                 horizontal_height=2160, vertical_width=1080,
                                 vertical_height=1920, crf=20),
        ),
    )
    for r in results:
        print(f"[3] {r.clip_id}: cues={r.metadata.get('cues')}", flush=True)
        print(f"    h: {r.horizontal_mp4}", flush=True)
        print(f"    v: {r.vertical_mp4}", flush=True)
        print(f"    ass: {r.ass_path}", flush=True)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()

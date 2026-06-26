"""Render ONE frame to preview a 'fresh/clean' variant of cinematic.
Weaker outline + weaker shadow + pure white, no code change (StaticResolver inject).
"""
import os, sys, subprocess
sys.path.insert(0, r"D:\Hermes\projects\auto-podcast-slicer-plus\src")

from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.stage_style import StaticResolver
from garden_core.stage_style.molds import MOLDS, mold_to_style
from garden_core.types import CutPoint, replace

TRANSCRIPT = r"D:\Hermes\projects\garden-production\output\transcript_aligned.json"
SOURCE = r"D:\Hermes\projects\podcast\garden in  forking pathies\garden in forking pathes podcast.mp4"
OUT = r"D:\Hermes\projects\garden-production\output\clips\subjectivity\_freshtest"
os.makedirs(OUT, exist_ok=True)

# base cinematic, then: xr=0.078, weaker outline+shadow, pure white, no bold
base = mold_to_style(MOLDS["cinematic"])
print(f"cinematic base: outline={base.outline_width} shadow={base.shadow_depth} color={base.primary_color} bold={base.bold}")
fresh = replace(
    base,
    name="cinematic",
    font_size_ratio=0.078,
    outline_width=0.006,      # 0.025 -> 0.006 非常弱的描边 (@4K ~1px)
    shadow_depth=0.0,         # 去掉阴影
    primary_color="&H00FFFFFF",  # 纯白
    bold=False,
)
print(f"fresh:          outline={fresh.outline_width} shadow={fresh.shadow_depth} color={fresh.primary_color} bold={fresh.bold}")
print(f"  @4K: font={fresh.font_size_ratio*2160:.0f}px outline={fresh.outline_width*fresh.font_size_ratio*2160:.1f}px shadow={fresh.shadow_depth*fresh.font_size_ratio*2160:.1f}px")

resolver = StaticResolver({"cinematic": fresh, "default": fresh})
cuts = [CutPoint(clip_id="FRESH_TEST", source_media=SOURCE, start_s=1800.93, end_s=1809.0, style_name="cinematic", title="fresh test")]
res = run_from_transcript(
    transcript=load_transcript_json(TRANSCRIPT), cut_points=cuts,
    style_name="cinematic", engines=Engines(style_resolver=resolver),
    opts=PipelineOptions(source_media=SOURCE, render=RenderOptions(
        output_dir=OUT, horizontal_width=3840, horizontal_height=2160,
        render_vertical=False, crf=23)),
)
clip = res[0].horizontal_mp4
frame = os.path.join(OUT, "frame_fresh_v2.jpg")
subprocess.run(["ffmpeg","-y","-ss","3.5","-i",clip,"-vframes","1","-q:v","2",frame], capture_output=True)
print("frame:", frame, f"{os.path.getsize(frame)//1024}KB" if os.path.exists(frame) else "MISSING")
print("DONE")

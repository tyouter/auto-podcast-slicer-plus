"""Render ONE frame to preview 2x font size for cinematic style.
Does NOT touch garden_core code — injects an enlarged StyleDef via StaticResolver.
"""
import os, sys, subprocess
sys.path.insert(0, r"D:\Hermes\projects\auto-podcast-slicer-plus\src")

from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.stage_style import StaticResolver
from garden_core.stage_style.molds import YamlStyleResolver
from garden_core.types import CutPoint, replace

TRANSCRIPT = r"D:\Hermes\projects\garden-production\output\transcript_aligned.json"
SOURCE = r"D:\Hermes\projects\podcast\garden in  forking pathies\garden in forking pathes podcast.mp4"
BASE = r"D:\Hermes\projects\garden-production\output\clips\subjectivity"
OUT = os.path.join(BASE, "_fonttest")
os.makedirs(OUT, exist_ok=True)

# cinematic xr now comes from style config (styles/cinematic.yaml = 0.078),
# not a code default; preview doubles it.
cur = YamlStyleResolver().resolve("cinematic", 2160)
print(f"current font_size_ratio = {cur.font_size_ratio} -> {cur.font_size_ratio*2160:.0f}px @4K")
big = replace(cur, font_size_ratio=cur.font_size_ratio * 2)
print(f"2x      font_size_ratio = {big.font_size_ratio} -> {big.font_size_ratio*2160:.0f}px @4K")

resolver = StaticResolver({"cinematic": big, "default": big})

# render an 8s window that contains the first subtitle
cuts = [CutPoint(clip_id="FONT_TEST_2X", source_media=SOURCE, start_s=1800.93, end_s=1809.0,
                 style_name="cinematic", title="font test")]
res = run_from_transcript(
    transcript=load_transcript_json(TRANSCRIPT), cut_points=cuts,
    style_name="cinematic", engines=Engines(style_resolver=resolver),
    opts=PipelineOptions(source_media=SOURCE, render=RenderOptions(
        output_dir=OUT, horizontal_width=3840, horizontal_height=2160,
        render_vertical=False, crf=23)),
)
clip2x = res[0].horizontal_mp4
print(f"2x clip: {clip2x}")

# grab a frame from the 2x clip (around 3.5s in, mid-subtitle)
frame2x = os.path.join(OUT, "frame_2x.jpg")
subprocess.run(["ffmpeg","-y","-ss","3.5","-i",clip2x,"-vframes","1","-q:v","2",frame2x],
               capture_output=True)
# grab a frame from the existing master (0.052 baseline), same subtitle ~4s in
master = os.path.join(BASE, "EP01_SUBJECTIVITY_horizontal.mp4")
frame_cur = os.path.join(OUT, "frame_current.jpg")
subprocess.run(["ffmpeg","-y","-ss","4","-i",master,"-vframes","1","-q:v","2",frame_cur],
               capture_output=True)

for f in [frame_cur, frame2x]:
    print(f"  {f}: {os.path.getsize(f)//1024}KB" if os.path.exists(f) else f"  {f}: MISSING")
print("DONE")

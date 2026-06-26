"""Full E2E: all 13 clips from garden-production via garden_core.
"""
import os, sys, time

GARDEN_CORE_SRC = r"D:\Hermes\projects\auto-podcast-slicer-plus\src"
sys.path.insert(0, GARDEN_CORE_SRC)

from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

TRANSCRIPT = r"D:\Hermes\projects\garden-production\output\transcript_aligned.json"
SOURCE_VIDEO = r"D:\Hermes\projects\podcast\garden in  forking pathies\garden in forking pathes podcast.mp4"
OUTPUT_DIR = r"D:\Hermes\projects\garden-production\output\_e2e_full"

# All 13 clips from production_protocol.yaml
ALL_CLIPS = [
    ("EP01_GARDEN", 30, 270, "小径分岔的花园——名字的来源和创作初衷"),
    ("EP01_AGE35", 1020, 1320, "35岁的焦虑——无论哪个行业都在意年龄"),
    ("EP01_SOUL", 2100, 2400, "分岔即方法——产品有灵魂是因为来自人的可能性"),
    ("EP01_EDUCATE", 3480, 3780, "回到过去教育自己——选择是多元的"),
    ("EP01_DIALECTIC", 4680, 4980, "戏剧中的辩证——不是绝对的好人或坏人"),
    ("AI_BIRD", 55, 75, "报喜鸟 · 自然的第一个分岔"),
    ("AI_WHITEBOARD", 440, 470, "白牌 · 拒绝标签的入场券"),
    ("AI_FORK", 850, 910, "十年分岔 · 从剧场出发的两条路"),
    ("AI_SOUL", 2421, 2475, "灵魂悖论 · 艺术不必神圣"),
    ("AI_WOZHI", 4090, 4140, "我执 · 当执念变成牢笼"),
    ("AI_BOTTLE", 3960, 4015, "漂流瓶 · 不为谁而做的节目"),
    ("AI_DAYDREAM", 5110, 5168, "白日梦与达达 · 创造的另一条路"),
    ("AI_AI_NAMED", 92, 115, "AI 命名了我们 · 镜中镜"),
]

def main():
    t0 = time.time()
    assert os.path.exists(TRANSCRIPT), f"Missing: {TRANSCRIPT}"
    assert os.path.exists(SOURCE_VIDEO), f"Missing: {SOURCE_VIDEO}"

    print(f"[1] Loading transcript...")
    transcript = load_transcript_json(TRANSCRIPT)
    print(f"    {len(transcript.segments)} segments, {transcript.duration_s:.0f}s")

    cuts = [CutPoint(clip_id=cid, source_media=SOURCE_VIDEO, start_s=float(s), end_s=float(e), style_name="cinematic", title=t)
            for cid, s, e, t in ALL_CLIPS]

    print(f"[2] Running produce for {len(cuts)} clips...")
    results = run_from_transcript(
        transcript, cuts, style_name="cinematic", engines=Engines(),
        opts=PipelineOptions(
            source_media=SOURCE_VIDEO,
            render=RenderOptions(output_dir=OUTPUT_DIR, horizontal_width=3840,
                                 horizontal_height=2160, vertical_width=1080,
                                 vertical_height=1920, crf=20),
        ),
    )

    ok = 0; fail = 0
    for r in results:
        h = r.horizontal_mp4 and os.path.exists(r.horizontal_mp4)
        v = r.vertical_mp4 and os.path.exists(r.vertical_mp4)
        if h and v: ok += 1
        else: fail += 1
        status = "✓" if (h and v) else "✗"
        print(f"    {status} {r.clip_id}: h={'OK' if h else 'FAIL'} v={'OK' if v else 'FAIL'} cues={r.metadata.get('cues','?')}")

    elapsed = time.time() - t0
    print(f"\nDONE in {elapsed:.0f}s: {ok}/{len(results)} passed, {fail} failed")
    return 0 if fail == 0 else 1

if __name__ == "__main__":
    sys.exit(main())

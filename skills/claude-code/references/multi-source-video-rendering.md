# 多源视频渲染：source_offset_s 时间轴平移（T4+ 一等公民）

## 问题

一段完整对话由多个视频文件拼接而成（如特斯拉试驾：DJI_0089 14:10 + DJI_0090 7:25）。全链转录对齐纠错跑在拼接后的音频上（单一时间轴 0–1294s），但渲染时 ffmpeg 只能对一个源视频 seek——超出第一个文件时长（850s）的片段需要切到第二个源文件并偏移时间。

## 解决方案（T4+）

`CutPoint.source_media`（必填）指定源文件，`source_offset_s` 把全局时间轴平移到源本地时间，无需手动列表推导：

```python
from garden_core.types import CutPoint

SRC1 = r"path/to/video1.MP4"  # 覆盖 0–850s
SRC2 = r"path/to/video2.MP4"  # 覆盖 850–1294s
SEG1_END = 850.0

# Batch 1: 0–850s → SRC1（source_offset_s 默认为 0.0，时间戳不变）
BATCH1 = [
    CutPoint(clip_id="t01", source_media=SRC1, start_s=0,   end_s=81,   style_name="fresh"),
    CutPoint(clip_id="t02", source_media=SRC1, start_s=81,  end_s=103,  style_name="fresh"),
    # ...
]

# Batch 2: 850–1294s → SRC2（source_offset_s 平移全局时间到 SRC2 本地）
BATCH2 = [
    CutPoint(clip_id="t14", source_media=SRC2, start_s=850,  end_s=911,  source_offset_s=SEG1_END, style_name="fresh"),
    CutPoint(clip_id="t15", source_media=SRC2, start_s=911,  end_s=1040, source_offset_s=SEG1_END, style_name="fresh"),
    # ...
]
```

`stage_cut.cut()` 自动计算 `ClipPlan.start_s = cp.start_s - cp.source_offset_s`，BATCH1 得到 `0..850`，BATCH2 得到 `0..444`（源本地时间）。

每批独立调 `run_from_transcript()`，output_dir 相同（产物自然合并）。

## 旧方案（T4 前，已废弃）

```python
# ❌ 旧：手动列表推导做时间减法（已由 source_offset_s 取代）
BATCH2 = [
    CutPoint(clip_id=c.clip_id,
             start_s=max(0, c.start_s - SEG1_END),
             end_s=c.end_s - SEG1_END,
             style_name=c.style_name, title=c.title)
    for c in BATCH2_RAW
]
```

## 注意事项

- 转录/对齐/纠错仍跑在拼接后的**单一音频**上（`tesla_full.wav`），时间轴保持统一。
- `source_offset_s` 默认 `0.0`，单源场景无需关心此字段。
- cues 的 rebase 始终相对 `cp.start_s`（全局时间轴），不受 `source_offset_s` 影响。
- `PipelineOptions.source_media` 已退化为防御性兜底（仅当 plan 无 source_ref 时生效），新代码应通过 `CutPoint.source_media` 指定。
- 本次 Tesla 项目实测：seg1 850.18s / seg2 444.78s，拼接 1294.96s。Batch 1 13 条（0–850s）→ SRC1，Batch 2 6 条（850–1294s）→ SRC2（source_offset_s=850.0）。19/19 全过。

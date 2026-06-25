# 多源视频渲染：拼接时间轴 + 分发到各自源文件

## 问题

一段完整对话由多个视频文件拼接而成（如特斯拉试驾：DJI_0089 14:10 + DJI_0090 7:25）。全链转录对齐纠错跑在拼接后的音频上（单一时间轴 0–1294s），但渲染时 ffmpeg 只能对一个源视频 seek——超出第一个文件时长（850s）的片段会失败。

## 解决方案

分两批渲染，每批指向不同源视频并偏移时间戳：

```python
SRC1 = r"path/to/video1.MP4"  # 覆盖 0–850s
SRC2 = r"path/to/video2.MP4"  # 覆盖 850–1294s（需 -850 偏移）
SEG1_END = 850.0

# Batch 1: 0–850s → SRC1（时间戳不变）
BATCH1 = [CutPoint(...), ...]

# Batch 2: 850–1294s → SRC2（时间戳减去 SEG1_END）
BATCH2_RAW = [CutPoint(clip_id="t14", start_s=850, end_s=911, ...), ...]
BATCH2 = [
    CutPoint(clip_id=c.clip_id,
             start_s=max(0, c.start_s - SEG1_END),
             end_s=c.end_s - SEG1_END,
             style_name=c.style_name, title=c.title)
    for c in BATCH2_RAW
]
```

每批独立调 `run_from_transcript()`，output_dir 相同（产物自然合并）。

## 注意事项

- 转录/对齐/纠错仍跑在拼接后的**单一音频**上（`tesla_full.wav`），时间轴保持统一。
- 只分渲染批次，不拆分 transcript。
- ffprobe 获取每个源视频的实际时长用来设 `SEG1_END`，不用估算：
  ```bash
  ffprobe -v quiet -show_entries format=duration -of csv=p=0 video.MP4
  ```
- 偏移后的 `start_s` 用 `max(0, ...)` 兜底防止负数。
- 本次 Tesla 项目实测：seg1 850.18s / seg2 444.78s，拼接 1294.96s。Batch 1 13 条（0–850s）→ SRC1，Batch 2 6 条（850–1294s）→ SRC2（-850s 偏移）。19/19 全过。

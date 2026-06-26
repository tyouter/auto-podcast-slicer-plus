# garden-core E2E 验证方法

用真实项目数据独立验证 garden-core produce 管线。

## 独立验证脚本

```python
"""E2E smoke test for garden_core-based produce phase."""
import os, sys
sys.path.insert(0, "src")  # 在 repo 根下运行

from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

TRANSCRIPT = r"<project>\output\transcript_aligned.json"
SOURCE_VIDEO = r"D:\path\to\source.mp4"
OUTPUT_DIR = r"<project>\output\_e2e_test"

transcript = load_transcript_json(TRANSCRIPT)
cuts = [
    CutPoint(clip_id="TEST", source_media=SOURCE_VIDEO, start_s=55.0, end_s=75.0,
             style_name="cinematic", title="Test Clip"),
]
results = run_from_transcript(
    transcript, cuts, "cinematic", Engines(),
    PipelineOptions(
        source_media=SOURCE_VIDEO,
        render=RenderOptions(
            output_dir=OUTPUT_DIR,
            horizontal_width=3840, horizontal_height=2160,
            vertical_width=1080, vertical_height=1920,
            crf=20,
        ),
    ),
)

for r in results:
    h_ok = os.path.exists(r.horizontal_mp4)
    v_ok = os.path.exists(r.vertical_mp4)
    print(f"{r.clip_id}: h={'PASS' if h_ok else 'FAIL'} v={'PASS' if v_ok else 'FAIL'}")
```

## 验证清单

- [ ] transcript 加载成功（segments 数 > 0）
- [ ] `run_from_transcript()` 不抛异常
- [ ] 横版 mp4 产出（文件存在 + 非零大小）
- [ ] 竖版 mp4 产出（文件存在 + 非零大小）
- [ ] cues 数 > 0
- [ ] 用 MediaInfo 或 ffprobe 确认 4K 分辨率（3840×2160）

## 2026-06-22 验证记录

- 项目：garden-production（花园 EP01）
- 测试片段：AI_BIRD（55s–75s, 20s）
- 结果：横版 62MB ✓ 竖版 12MB ✓ 7 cues
- scribe：`smoke_produce_e2e.py` 位于 `tests/`

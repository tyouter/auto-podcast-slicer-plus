# garden-core API 速查

> 版本：0.1.0 | `auto-podcast-slicer-plus/src/garden_core/`

## 入口函数

### `run_from_transcript(transcript, cut_points, style_name, engines, opts, audio_path="") → list[RenderResult]`

从已有 Transcript 出发，跑阶段 2–7（对齐→校对→分段→裁剪→样式→渲染）。生产环境（Watcher）的标准入口。

```python
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.io_.source import load_transcript_json
from garden_core.types import CutPoint

transcript = load_transcript_json("transcript_aligned.json")
cuts = [
    CutPoint(clip_id="v1", start_s=10.0, end_s=120.0, style_name="cinematic", title="分岔路径v1"),
    CutPoint(clip_id="v2", start_s=200.0, end_s=350.0, style_name="cinematic", title="分岔路径v2"),
]
engines = Engines()  # 空引擎 = 跳过对齐+校对，直接分段渲染
opts = PipelineOptions(source_media="/path/to/source.mp4")

results = run_from_transcript(transcript, cuts, "cinematic", engines, opts, audio_path="/path/to/audio.wav")
```

### `run_from_audio(audio_path, cut_points, style_name, engines, opts) → list[RenderResult]`

全链路（阶段 1–7）：音频 → 转录 → 对齐 → 校对 → 分段 → 裁剪 → 渲染。需要 `engines.transcriber`。

---

## 核心类型

所有 dataclass 都是 `frozen=True`。时间单位统一为**秒 (float)**。

| 类型 | 用途 | 关键字段 |
|---|---|---|
| `Transcript` | 阶段 1–3 产出 | `segments`, `source_file`, `engine`, `duration_s` |
| `Segment` | 单条 ASR 片段 | `text`, `start_s`, `end_s`, `speaker`, `words` |
| `Word` | 词级时间戳 | `text`, `start_s`, `end_s` |
| `Cue` | 字幕单元（阶段 4→7 流通） | `index`, `text`, `start_s`, `end_s` |
| `CutPoint` | 用户指定的裁剪边界 | `clip_id`, `start_s`, `end_s`, `style_name`, `title` |
| `ClipPlan` | 裁剪计划（参数对象） | `clip_id`, `source_ref`, `start_s`, `end_s`, `cues` |
| `StyleDef` | 字幕样式定义 | `name`, `font_family`, `font_size_ratio`, `outline_width`… |
| `RenderResult` | 渲染产出 | `clip_id`, `horizontal_mp4`, `vertical_mp4`, `srt_path`, `ass_path` |

---

## 配置对象

### `Engines` (frozen dataclass)

注入一次，管线全程复用。所有字段可选。

```python
Engines(
    transcriber=None,   # Transcriber 实例（run_from_audio 必需）
    aligner=None,       # Aligner 实例
    llm=NoLLMClient(),  # LLM 客户端（校对用）
    style_resolver=None # StyleResolver（默认用 YamlStyleResolver）
)
```

### `PipelineOptions` (frozen dataclass)

```python
PipelineOptions(
    hotwords=(),             # ASR 热词
    errata=ErrataConfig.empty(),  # 勘误表
    proof=ProofOptions(),    # 校对选项
    segment=SegmentOptions(strategy="semantic"),  # 分段策略
    render=RenderOptions(output_dir="..."),  # 渲染选项
    video_height=1080,       # 默认视频高度
    source_media="",         # ⚠️ 源视频路径（Transcript.source_file 只是 JSON 路径）
    heal_gaps=False,         # 是否修复语音空隙
)
```

### `RenderOptions`

```python
RenderOptions(
    output_dir="/path/to/output",
    render_horizontal=True,
    render_vertical=True,
    horizontal_width=1920,   # 4K: 3840
    horizontal_height=1080,  # 4K: 2160
    vertical_width=1080,
    vertical_height=1920,
    crf=18,                  # 4K 高质量: 18–20
)
```

---

## I/O 工具

```python
from garden_core.io_.source import load_transcript_json, load_transcript_aligned_json

# 加载旧 transcript.json / transcript_aligned.json（自动 ms→s 转换）
transcript = load_transcript_json("transcript_aligned.json")
```

---

## 典型用法（Production Watcher produce 阶段）

```python
from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

def produce(project_dir: str, protocol: dict):
    """替代旧的 garden clip CLI 调用"""
    source_media = protocol["source_video"]
    transcript_path = os.path.join(project_dir, "transcript_aligned.json")
    output_dir = os.path.join(project_dir, "output", "clips")

    transcript = load_transcript_json(transcript_path)
    cuts = [
        CutPoint(
            clip_id=c["id"],
            start_s=c["start_s"],
            end_s=c["end_s"],
            style_name=c.get("style", "cinematic"),
            title=c.get("title", ""),
        )
        for c in protocol["clips"]
    ]

    results = run_from_transcript(
        transcript,
        cuts,
        style_name="cinematic",
        engines=Engines(),
        opts=PipelineOptions(
            source_media=source_media,
            render=RenderOptions(
                output_dir=output_dir,
                horizontal_width=3840,
                horizontal_height=2160,
                crf=20,
            ),
        ),
    )

    for r in results:
        print(f"  {r.clip_id}: {r.horizontal_mp4}")

    return results
```

---

## 与旧代码的关键区别

| | 旧 (`garden clip`) | 新 (`garden_core`) |
|---|---|---|
| 时间单位 | 毫秒/秒混用 | 全秒 |
| 字幕形状 | 3 种 entry | 单一 `Cue` |
| 样式系统 | 双系统互相覆盖 | 单一 `StyleDef` + `StyleResolver` |
| 配置全局变量 | `_DEFAULT_ERRATA_CONFIG` 等模块级可变 | 全部 dataclass 传参 |
| LLM 静默 PASS | 有 | 无（NoLLMClient 显式跳过） |
| `eval()` 解析帧率 | 有 | 无（`media_probe.py` JSON 解析） |

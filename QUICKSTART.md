# Quick Start

两种方式使用 auto podcast slicer plus：**Agent SKILL**（对话驱动）和 **Python API**（编程集成）。

## 前置条件

- Python ≥ 3.10
- conda（推荐，一键装齐 funasr / torch / ffmpeg）
- FFmpeg 在 `PATH`
- CUDA GPU（转录用 FunASRLocal，进程内 CUDA）
- 一期素材：视频 `.mp4` / 音频 `.wav`，或已有转录 `.json`

## 安装

```bash
conda env create -f environment.yml
conda activate garden
```

验证：

```bash
python -c "from garden_core.stage_asr import FunASRLocal; print('OK')"
```

## 核心架构：意图与执行分离

```
意图层（制作团队 · 需要智能）        执行层（garden_core · 确定性）
──────────────────────────        ──────────────────────────
选什么片段？                        转录、对齐、校对、分段
起什么标题？          ──CutPoint──→  裁切、字幕、渲染
提炼什么钩子？                      横版 / 竖版 / 质量门
```

- **Agent SKILL**：LLM 理解意图 → 生成 `CutPoint` → 调 garden_core 执行
- **Python API**：你自己构造 `CutPoint` → 调 garden_core

## 项目配置

auto podcast slicer plus 是纯库，配置分三处：

1. **字幕样式** `stage_style/styles/<name>.yaml`：字体 / 字号(xr) / 描边 / 阴影。**xr 必填、代码零硬编码**（缺失即报错，绝不静默兜底）。
2. **勘误表** `corrections.yaml`：`{错: 对}` 子串替换（也可代码直传 `ErrataConfig`）。
3. **其余一切走 Python dataclass 直传**：源路径 / 分辨率 / CRF / 引擎，全在脚本里传 `PipelineOptions` / `RenderOptions` / `Engines`。

最小项目骨架：

```
my-podcast/
├── source/ep01.mp4          # 源视频（绝对路径引用，不拷进项目）
├── output/{clips,release}/  # 渲染产物
├── corrections.yaml         # 勘误（只增不减）
└── (拷一份 styles/fresh.yaml，调好 xr 和 font_family)
```

---

## 方式一：Agent SKILL（推荐）

与 AI Agent 对话，自动完成「意图理解 → 生成 CutPoint → 调 pipeline」全流程，无需手写代码。

```
你：  帮我从这期播客剪 5 个最精彩的短视频
Agent：[激活 video-clip skill]
      → 制作人与你对话，理解创作意图
      → 生成切片方案（CutPoint 列表）
      → 调 garden_core 执行剪辑 + 字幕 + 音频 + 竖版
      → 调 quality-audit skill 四维度终审
      → 不过则优化迭代（≤3 轮）
      → 交付成品
```

更多对话示例：

```
"这期播客有哪些值得做短视频的高光时刻？"
"帮我做一期深度思考的长视频"
"字幕大一点，再饱满一点"
"审核一下生成的视频质量"
```

| 平台 | 安装 |
|------|------|
| Hermes | 加载 `skills/hermes/SKILL.md` 为 skill |
| Claude Code | 用 `skills/claude-code/SKILL.md` |
| OpenClaw | 加载 `skills/openclaw/SKILL.md` |

---

## 方式二：Python API

直接调用 garden_core，适合集成到自己的应用、Notebook、自定义工作流。

> 不含意图理解：你需要自己确定每个切片的 `start_s` / `end_s`，或用任意 LLM 生成 `CutPoint` 列表。

### 三个入口

| 入口 | 用途 | 阶段 |
|------|------|------|
| `run_from_audio(audio, cuts, style, engines, opts)` | 全链路（需 transcriber） | 1–7 |
| `run_from_transcript(transcript, cuts, style, engines, opts)` | 已有转录 → 切片（最常用） | 2–7 |
| `run_montage(transcript, cuts, style, engines, opts, montage_id=)` | N 区间拼一条连续长片 | 2–7 |

### 已有转录 → 切片

```python
import sys; sys.path.insert(0, "src")
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.io_.source import load_transcript_json
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

transcript = load_transcript_json("transcript_aligned.json")

cuts = [
    CutPoint(clip_id="v1", start_s=10.0,  end_s=120.0, style_name="cinematic", title="分岔路径 v1"),
    CutPoint(clip_id="v2", start_s=200.0, end_s=350.0, style_name="cinematic", title="分岔路径 v2"),
]

results = run_from_transcript(
    transcript, cuts, "cinematic",
    engines=Engines(),                       # 空引擎 = 跳过对齐/校对，直接分段渲染
    opts=PipelineOptions(
        source_media="/path/to/source.mp4",
        render=RenderOptions(output_dir="output/clips",
                             horizontal_width=3840, horizontal_height=2160, crf=20),
    ),
)
for r in results:
    print(r.clip_id, r.horizontal_mp4, r.vertical_mp4)
```

### 全链路（音频 → 成品）

```python
from garden_core.pipeline import run_from_audio, Engines, PipelineOptions
from garden_core.stage_asr import FunASRLocal

run_from_audio(
    "audio.wav", cuts, "cinematic",
    engines=Engines(transcriber=FunASRLocal(device="cuda"), aligner=..., llm=...),
    opts=PipelineOptions(source_media="source.mp4", heal_gaps=True,
                         render=RenderOptions(output_dir="output/clips")),
)
```

### 整期精剪 / 混剪

```python
from garden_core.pipeline import run_montage

# N 个区间 → 一条连续长片（字幕时间轴自动偏移合并）
# 输出顺序 == cut_points 顺序（可 ≠ 原片时间序）
run_montage(transcript, cuts, "cinematic", Engines(...), opts, montage_id="ep01")
```

### 核心类型（全部 frozen，时间统一为秒）

| 类型 | 用途 | 关键字段 |
|------|------|----------|
| `Transcript` | 阶段 1–3 产出 | `segments`, `duration_s` |
| `Cue` | 字幕单元（4→7 流通） | `index`, `text`, `start_s`, `end_s` |
| `CutPoint` | 用户指定的裁剪边界 | `clip_id`, `start_s`, `end_s`, `style_name`, `title` |
| `StyleDef` | 字幕样式 | `name`, `font_family`, `font_size_ratio`(xr), `outline_width` |
| `RenderResult` | 渲染产出 | `clip_id`, `horizontal_mp4`, `vertical_mp4`, `srt_path`, `ass_path` |

---

## 两种方式对比

| | Agent SKILL | Python API |
|---|-------------|------------|
| 适合 | 创意对话、端到端交付 | 应用集成、自定义工作流 |
| 交互 | 自然语言对话 | 函数调用 |
| 意图理解 | ✅ LLM 自动生成 CutPoint | ❌ 自己确定 start_s / end_s |
| 质量审核 | ✅ 自动调 quality-audit | 自己调 render_gate / 审核 |
| 学习成本 | 低（对话即可） | 中（需了解 API） |

### 用其他 Agent 生成切片方案

CutPoint 格式是开放的，可以用任何 LLM 生成：

```
分析以下播客转录，选出 5 个最精彩的高光片段，
每个输出：clip_id, title, start_s, end_s。片段时长建议 30–120 秒。
```

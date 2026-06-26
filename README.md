# auto podcast slicer plus

> 本项目脱胎于播客节目《小径分岔的花园》，是该节目的日常制作管线。节目灵感来自博尔赫斯的同名短篇——而把制作工具开源，本身就是时间分岔的一个选择：一切可能性，同时发生。

**一个人，驱动一整支视频制作团队。** 从「我有一段几十分钟的对话」到「我有一组带烧录字幕、可直接发布的成品切片」——转录、对齐、校对、分段、裁切、字幕、渲染，七个阶段，一条确定性管线。

---

## 双层结构：制作团队 + 干净引擎

auto podcast slicer plus 分两层：

- **意图层 = 制作团队（skill）**：制作人对话理解你想要什么 → 编排工作流 → 调引擎执行 → 出品终审。需要审美和判断的部分。
- **执行层 = garden_core（纯 Python 库）**：转录 / 对齐 / 校对 / 分段 / 裁切 / 样式 / 渲染。确定性、可测试、无全局状态、无 CLI、无守护进程——直接 `import` 调用。

> 这就是「意图与执行分离」：选什么片段、起什么标题、提炼什么钩子，由制作团队决定；切割、字幕、渲染，由引擎确定性执行。

---

## 特性

- **对话驱动的制作团队**：一个制作人 + 5 条工作流，从创意对话到多平台交付全覆盖
- **七阶段全链路**：ASR 转录 → 词级对齐 → 校对纠错 → 语义分段 → 裁切 → 样式 → 渲染
- **双格式输出**：横版 4K（16:9）+ 竖版（9:16，模糊背景填充，不裁原画）
- **字幕质量门 render_gate**：字号比例 + 安全区机械校验，坏片段一票否决，不靠人眼
- **词级强制对齐**：MMS_FA 毫秒级时间戳，字幕跟读不飘
- **LLM 校对绝不静默失败**：统一 LLM 网关，显式超时 / 重试 / 降级——LLM 故障永远不会被当成「质检通过」
- **进程内 CUDA 转录**：FunASRLocal（Paraformer + VAD + Punc + Speaker），零网络、零 server、长音频不 OOM
- **不可变数据流**：每个阶段产出都是 `frozen` dataclass，零模块级可变全局，并发项目互不污染
- **四维度出品审核**：技术 / 文化 / 传播 / 影视，配合 quality-audit 协作 skill 做终审
- **三平台 skill**：Hermes / Claude Code / OpenClaw，clone 即用

---

## 制作团队（skill）

制作人是创意中枢，**不亲自剪辑**——负责对话、理解意图、编排工作流、审核出品。

| 工作流 | 场景 | 产出 |
|--------|------|------|
| **0 · 制作人对话** | 创意对话 → 意图转化 → 蓝图确认 | 创作蓝图 |
| **1 · 一期一剪** | 整期对话 → 精剪长视频 | 横版 4K + 竖版 |
| **2 · 内容原子化** | 长视频 → 多条独立短视频 | 抖音 / Shorts 切片 |
| **3 · 主题系列** | 多期素材 → 主题系列 | 系列视频 |
| **4 · 全平台出品** | 成品 → 各平台适配 | B站 / 抖音 / YouTube / 小宇宙 |
| **5 · 素材库打包** | 全部产出 → 标准化交付 | 规范化目录 |

审核不过时，制作人触发优化迭代（最多 3 轮）再重新生成。

---

## 七个阶段

```
audio ─▶ [1 转录 asr]       FunASRLocal · 进程内 CUDA · VAD 分块
       ─▶ [2 对齐 align]     MMS_FA 词级毫秒时间戳
       ─▶ [3 校对 proofread] 规范化 → 勘误 → 同音检测 → LLM → 双通道合并
       ─▶ [4 分段 segment]   语义断句 + 间隙自愈
       ─▶ [5 裁切 cut]       按 CutPoint 切割
       ─▶ [6 样式 style]     styles/*.yaml（xr 是唯一主变量）
       ─▶ [7 渲染 render]    横版 4K + 竖版 ─▶ ✅ render_gate 机械门
```

---

## 使用方式

### 方式一：Agent SKILL（推荐）

与 AI Agent 对话，自动编排完整工作流。三平台 clone 即用：

```
你：  帮我从这期播客剪 5 个最精彩的短视频
Agent：[激活 video-clip skill]
      → 制作人对话，理解创作意图
      → 调 garden_core 执行转录 / 对齐 / 校对 / 切片 / 渲染
      → quality-audit 四维度终审
      → 交付横竖双格式成品
```

| 平台 | 入口文件 |
|------|----------|
| Hermes | `skills/hermes/SKILL.md` |
| Claude Code | `skills/claude-code/SKILL.md` |
| OpenClaw | `skills/openclaw/SKILL.md` |

### 方式二：Python API

直接 `import garden_core`：

```python
from garden_core.project import create_project, load_project, ProjectRun, SourceSpec
from garden_core.pipeline import Engines
from garden_core.stage_asr import FunASRLocal

cfg = create_project("my-podcast", "./ep01",
    sources=[SourceSpec(id="SRC1", path="source/ep01.mp4")],
    audio_path="source/ep01.wav")

run = ProjectRun(load_project("./ep01"), Engines(transcriber=FunASRLocal("cuda")))
run.transcribe()   # ASR + align
run.proofread()    # errata + LLM
# → edit project.yaml cut_points → reload
run.render()       # clips + subtitles
run.audit()        # ffprobe + ASS gate
```

> 完整用法见 [QUICKSTART.md](QUICKSTART.md)。

---

## 安装

```bash
conda env create -f environment.yml && conda activate garden
```

---

## 许可

MIT

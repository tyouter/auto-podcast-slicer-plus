---
name: video-clip
description: >-
  Use when user wants to produce video content from raw footage — transcribe,
  align, proofread, segment, cut, style, render, and deliver. Covers full
  pipeline from podcast/interview source to platform-ready clips. Triggers on
  "剪视频", "做字幕", "渲染", "切片", "转录", "做个短视频", "帮我处理这段素材",
  "出片", "clip this", "render subtitles", "make a highlight".
version: 3.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [video, subtitle, podcast, production, ffmpeg, garden-core]
    category: media-production
    requires_toolsets: [terminal]
    related_skills: [quality-audit]
    repo: auto-podcast-slicer-plus
    repo_url: https://github.com/tyouter/auto-podcast-slicer-plus
---

# Video Clip — 视频制作团队

你是完整视频制作团队，把素材变成可发布成品。

## When to Use

- 用户有视频/音频素材要处理
- "剪视频" "做字幕" "渲染" "切片" "转录" "出片" "做个短视频"
- "帮我处理这段素材" "clip this" "render subtitles"

**Don't use for**：纯文本创作、代码编写、非视频类文件处理。

---

## 快速开始

三步：建项目 → 转录纠错 → 渲染出品。

```python
from garden_core.project import create_project, load_project, ProjectRun
from garden_core.pipeline import Engines
from garden_core.stage_asr import FunASRLocal

# 1. 建项目（生成 project.yaml + 目录结构）
cfg = create_project(
    "<project-name>", "<root-dir>",
    sources=[{"id": "SRC1", "path": "<source>.mp4"}],
    audio_path="<audio>.wav",
)

# 2. 加载并编排
run = ProjectRun(load_project("<root-dir>"), Engines(
    transcriber=FunASRLocal("cuda"),
))

# 3. 全链执行
run.transcribe()    # ASR 转录 + 对齐
run.proofread()     # 纠错（默认走 corrections.yaml）
# → 编辑 project.yaml 填 cut_points
# → 重新 load
run.render()        # 切片 + 字幕 + 渲染
run.audit()         # 出品质检
```

Agent 做决策（剪什么/风格/受众），skill 做执行。AI 导演的选题判断不写进 skill。

---

## 项目管理（project.yaml）

项目是一等公民。`project.yaml` 是唯一配置入口，`ProjectRun` 是运行时编排器。

### 项目结构

```
<root>/
├── project.yaml          # 唯一配置入口
├── corrections.yaml      # 勘误表
├── source/               # 源素材
├── output/
│   ├── clips/            # 切片成品
│   ├── fullcut/          # 全片
│   └── release/          # 发布版
└── run_manifest.json     # 运行记录（自动生成）
```

### 项目操作

| 操作 | 函数 | 说明 |
|------|------|------|
| 创建 | `create_project(name, root_dir, *, sources, ...)` | 脚手架 + 生成 project.yaml |
| 加载 | `load_project(root_dir, strict=True)` | 读 yaml → 校验 → 返回 ProjectConfig |
| 编辑 | `edit_project(root_dir, **overrides)` | 改配置 → 校验 → 写回 |
| 运行 | `ProjectRun(cfg, engines).transcribe()` 等 | 分阶段执行 |
| 续跑 | `ProjectRun(...).resume()` | 读 `run_manifest.json`，跳过已完成 stage |

### ProjectRun 阶段

| 方法 | 产物 |
|------|------|
| `transcribe()` | `transcript.json`（ASR + 对齐） |
| `proofread()` | `transcript.json`（纠错更新） |
| `render()` | `output/clips/*.mp4` + `.ass`/`.srt` |
| `audit()` | `audit_report.json`（ffprobe + ASS 门检） |
| `resume()` | 续跑未完成 stage |
| `rerender(clip_ids)` | 增量重渲指定 clip |
| `reproofread(errata)` | 重新纠错 + 可选重渲 |

多源视频：`sources` 配多个 `SourceSpec`，`cut_points` 引 `source` id。`render()` 自动做多源翻译（`CutPointSpec → CutPoint` + 时间偏移）。

---

## 工作流

### 工作流 0：制作人对话（强制入口）

你是完整制作团队——同时担任导演、剪辑、字幕、质检四个角色。无论用户请求多具体，先进对话确认意图，不跳过直接执行。

**角色分工**：

| 角色 | 职责 | 谁决策 |
|------|------|--------|
| 导演 | 选题、叙事结构、节奏、风格方向 | 用户 |
| 剪辑 | 切哪段、时长、转场、B-roll | Agent 提案，用户确认 |
| 字幕 | 字体、位置、描边、背景框 | 用户定风格，Agent 执行 |
| 质检 | 编码、响度、字幕门检 | Agent 自动执行 |

**四阶段**：

**1. 创作对话** — 理解意图，不是收集参数。

先问一个维度，听完再问下一个。不列多选题、不催促。

- 这期/这段想表达什么？（核心观点）
- 给谁看？（受众）
- 想达到什么效果？（说服/启发/记录/传播）
- 有没有特别想保留或删掉的内容？

产出：对话理解（不写文件）。

**2. 意图转化** — 把对话翻译成可执行的创作蓝图。

输出一份蓝图，包含：
- 创作意图（一句话）
- 目标受众
- 切片列表（每条：标题 + 大致区间 + 为什么选这段）
- 字幕风格（引用 `stage_style/styles/<name>.yaml`）
- 交付格式（横版/竖版/平台）

等用户回复"可以"/"开始"再进入执行。用户改蓝图内容 → 更新蓝图 → 再次确认。

**3. 执行编排** — 按蓝图逐个切片执行。

- 每条切片走对应执行工作流（工作流 1-5）
- 每完成一条 → `audit()` 质检
- 质检不通过 → 自动优化（≤3 轮），超过则标记并汇报
- 全部切片完成后 → 出质检汇总

**4. 交付发布** — 成品清单 + 发布物料。

- 成品清单（clip 名 + 时长 + 分辨率 + 文件大小）
- 可选的发布物料：标题建议、简介文案、封面帧
- 用户确认后交付

**触发规则**：

| 用户表达 | 行为 |
|----------|------|
| 明确需求（"剪 3 个短视频"） | 快速确认 → 出蓝图 → 等确认 → 执行 |
| 模糊想法（"做点东西"） | 进完整对话，从创作对话开始 |
| 修改（"字幕大一点"） | 定位阶段 → 调参 → 重跑 |
| 质量不满 | 定位问题 → 优化 → 重新生成 |

### 五个执行工作流

所有工作流统一走 `ProjectRun`，不手写脚本。

**工作流 1 · 一期一剪**

整期精剪为单条连续成片——去废料、保主体、可选高光片头。

1. `create_project(...)` 或 `load_project(...)` 加载项目
2. `run.transcribe()` → `run.proofread()` 完成转录纠错
3. 通读全片 transcript，标记废料区间（开头设备调试/中场调整/结尾半句话）。参照 工作流 0 出创作蓝图 → 用户确认。
4. 可选：挑 5-8 个 ≤5s 金句做 preview 高光片头。先给金句清单让用户确认，再精确定位时间戳。
5. 组装 `cut_points`：preview 金句 + 正片保留段。**输出顺序 = cut_points 列表顺序**——可将原片靠后的段落列在前面做乱序拼接。用 `run_montage`（N 区间拼一条连续长片，字幕时间轴自动偏移合并），不走标准 `render()`。
6. `run.audit()` 确认编码/字幕门检通过

→ 产出：`output/fullcut/<project>_full.mp4`

**工作流 2 · 内容原子化**

长视频拆为独立短视频。宁精勿滥。

1. 同工作流 1 完成转录纠错
2. 审阅 transcript，标记高光区间（3-5min/段）
3. 编辑 `project.yaml`，为每段设独立 `cut_point`（id 唯一，title 有吸引力）
4. `run.render()` 逐段渲染
5. `run.audit()` 逐段质检

→ 产出：`output/clips/<clip_id>.mp4`（每段一条）

**工作流 3 · 主题系列**

按主题组织跨源素材，每章 2-4min。

1. `create_project(...)` 配多个 `sources`
2. `run.transcribe()` → `run.proofread()` 全源转录
3. 按主题分组 transcript 区间 → 设 `cut_points`（各 `source` 字段指向对应源 id）
4. `run.render()` — render 自动做多源时间偏移拼接
5. `run.audit()`

→ 产出：`output/clips/<chapter_N>.mp4`

**工作流 4 · 全平台出品**

基于成品做多平台适配。

1. 确保 `output/clips/` 或 `output/fullcut/` 有 mp4
2. 按平台规格 ffmpeg 转码：
   - B站/YouTube：横版 16:9，H.264 4K
   - 抖音/小红书：竖版 9:16，H.264 1080p
   - 小宇宙/播客：仅提取音频，MP3 320kbps
3. 文件名含平台标识（`<clip>_bilibili.mp4` 等）

→ 产出：`output/release/<platform>/`

**工作流 5 · 素材库打包**

标准化交付。

1. 确保全部成品在 `output/` 下
2. 生成 `summary.md`（含各 clip 时长/标题/关键词）
3. 生成 `COPYRIGHT`（标注字体/素材来源）

→ 产出目录：
```
output/release/
├── full_episode/         # 全片
├── clips/                # 切片
├── platforms/            # 多平台版本
└── LICENSE / COPYRIGHT / summary.md
```

---

## 技术参考

### 7 个 stage

```
① ASR 转录 (stage_asr/FunASRLocal·CUDA·内部分块)
→ ② 对齐 (stage_align/MMS_FA 词级)
→ ③ 纠错 (stage_proofread/errata+LLM)
→ ④ 分段 (stage_segment·含 gap_heal 自愈)
→ ⑤ 裁切 (stage_cut)
→ ⑥ 样式 (stage_style/styles/*.yaml)
→ ⑦ 渲染 (stage_render)
→ ✅ render_gate 机械门
```

### 三个入口

| 入口 | 用途 |
|------|------|
| `run_from_audio` | 全链：音频 → 成品（需 transcriber） |
| `run_from_transcript` | 已有 transcript：从 stage 2 起 |
| `run_montage` | N 区间 → 一条连续长片 |

日常推荐 `ProjectRun`（封装了入口 + 编排 + manifest），不直接调三入口。

### 关键输入格式

**corrections.yaml** — 勘误表，转录纠错依据。

```yaml
common:              # 全局文本替换（原文→正确）
  "错误词A": "正确词A"
  "错误词B": "正确词B"
speakers:            # 说话人映射（SPK0→真实姓名）
  SPK0: "张三"
  SPK1: "李四"
```

**cut_points**（project.yaml 中）— 切片时间定义。

```yaml
cut_points:
  - id: clip_01              # 唯一标识，输出文件名用
    title: "切片标题"
    source: SRC1              # 引用 sources 中 source.id
    start: "00:01:23.500"     # HH:MM:SS.mmm 或浮点秒
    end: "00:03:45.000"
    style: cinematic          # 可选，覆盖项目默认字幕风格
```

多源时 `source` 指向对应源；同一源多个区间用多条 `cut_point`。

### 配置层

- **`config.yaml`**（仓库根目录）：全局默认——字幕风格、字体路径、ffmpeg 参数。
- **`project.yaml`**（项目目录）：项目级配置，优先级高于 `config.yaml`。

### 环境

**首选**：`scripts/run_garden.bat python <脚本>`（封装 garden conda env + DLL + ffmpeg + PYTHONPATH）。从 git-bash 调用：

```bash
MSYS_NO_PATHCONV=1 cmd /c 'scripts\\run_garden.bat python <脚本.py>'
```

**手动**：子 shell prepend garden env PATH（用 `( )` 隔离，避免污染 session）：

```bash
(
  G="/c/Users/<you>/anaconda3/envs/garden"
  export PATH="$G:$G/Library/bin:$G/Library/usr/bin:$G/Library/mingw-w64/bin:$G/Scripts:$G/DLLs:$G/bin:$PATH"
  cd <repo>
  PYTHONPATH=src "$G/python.exe" <脚本.py>
)
```

- 必须用 `( )` 子 shell——export 跨调用持久，直接 export 会污染 session
- ffmpeg 需在 PATH 中
- garden env 无 `DEEPSEEK_API_KEY`：LLM 纠错需脚本自行注入

### 字幕样式

样式定义在 `stage_style/styles/<name>.yaml`。

- **xr（`font_size_ratio`）是唯一主变量**：描边/阴影/留白全从 xr 按比例算。"放大一倍" = 只改 xr。
- **xr 必填，代码零硬编码**：缺失 → `ConfigError`，不静默兜底。
- **新增样式只加 yaml，不动 molds.py**。
- **字重 > 描边**：字幕"看不清"先查字体族（瘦宋体 → 换黑体），而非加描边。
- **字体商用许可**：声明字体前必查——Noto Sans/Serif SC（SIL OFL ✅），微软雅黑/宋体/黑体（❌ 商用受限）。libass 找不到字体名时会静默 fallback 到系统字体，可能落到受限字体。

---

## Common Pitfalls

1. **手写转录脚本绕过产线**。转录走 `ProjectRun.transcribe()` 或 `run_from_audio`，不手写 `AutoModel()` 调用。

2. **LLM 纠错不生效**。确认 `DEEPSEEK_API_KEY` 在环境变量中（`Engines.from_env()` 自动检测）。大 transcript（>200 segments）需 `LLMClient(timeout=300)`，默认 30s 不够。

3. **重渲全量不跳过**。`render()` 默认 `skip_existing=True`，已有 mp4 不重渲。改样式后必须先删旧 mp4 再重渲，否则 ASS 更新了但视频字幕不变。

4. **示例数据污染**。skill/reference 中所有示例必须是占位符（`<...>`），不写真实项目路径、文件名、勘误条目。

5. **project.yaml 中 transcript 用绝对路径**。相对路径会导致 `garden clip` 报告「转录条目: 0」。始终写 `/path/to/project/transcript.json`。

6. **corrections.yaml 需 `corrections:` 顶层键**。pipeline 的 `load_custom_errata` 路径读 `corrections:` 嵌套键，平铺键值对会被静默忽略。

7. **4K 源输出被压到 1080p**。风格 yaml 的 `horizontal:` 段默认 `output_width: 1920`/`output_height: 1080`。出 4K 需显式设 `output_width: 3840` + `output_height: 2160`。

---

## Verification Checklist

- [ ] `project.yaml` 存在且 `validate()` 通过
- [ ] `corrections.yaml` 勘误表已填写
- [ ] `source/` 下源素材存在
- [ ] 转录完成（`transcript.json` 含 segments）
- [ ] 纠错完成（`corrections_applied` 标记为 true）
- [ ] `render()` 后 `output/clips/` 有 mp4 + ass/srt
- [ ] `audit()` 无 BLOCK（分辨率/编码/cue 计数/ASS gate 全过）

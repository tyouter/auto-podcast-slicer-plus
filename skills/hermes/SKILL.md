---
name: video-clip
description: >
  对话驱动的视频制作团队：从播客/访谈长素材，到各平台可发布的成品。
  覆盖转录、对齐、纠错、切片、字幕渲染、质检、多平台交付全流程。
  当用户要制作、剪辑、包装、分发视频内容时激活。
version: 2.0.0
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [video, audio, subtitle, podcast, production, ffmpeg, clipping, garden-core]
    category: media-production
    requires_toolsets: [terminal]
    related_skills: [quality-audit, nas-access, reasonix]
---

# Video Clip — 自媒体个体的视频制作团队

你是一个完整的视频制作团队，把创作者从「我有素材」带到「我有一整套可发布的成品」。

## 职责分离（架构铁律）

- **skill = 通用剪辑「执行」能力**：转录/对齐/纠错/切片/字幕/渲染/质检/交付。不耦合任何具体项目。
- **「剪什么 / 剪辑意图」由 Hermes Agent（制作人）决策**，再调本 skill 执行。
- AI 导演、选题判断、创作意图 = Agent 的决策逻辑，**不写进 skill**。skill 只负责把意图变成成品。

---

## 执行层：garden_core 纯 Python 库

执行层是 **garden_core**（`src\garden_core`），纯库、无 CLI、无 Watcher、无协议文件。直接 import 调用。

> ⛔ **已弃用**：旧 `auto-podcast-slicer` 的 `garden clip` CLI、`production_watcher.py`、`production_protocol.yaml` 协议驱动那套 —— 全部废弃，不再使用。统一走 garden_core 库 API。

### 7 个 stage（一条链）
```
①ASR转录(stage_asr/FunASRLocal·进程内CUDA·AutoModel内部分块) → ②对齐(stage_align/MMS_FA词级)
→ ③纠错(stage_proofread/errata+LLM·不耦合项目) → ④分段(stage_segment·含gap_heal自愈)
→ ⑤裁切(stage_cut) → ⑥样式(stage_style/styles/*.yaml) → ⑦渲染(stage_render) → ✅render_gate机械门
```

### 三个入口（run_from_audio 全链 / run_from_transcript 独立片段 / run_montage 拼一条长片）
```python
import sys; sys.path.insert(0, r"src")
from garden_core.pipeline import run_from_audio, run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.stage_asr import FunASRLocal
from garden_core.types import CutPoint

# 全链（audio → 成品）：转录/对齐/纠错引擎注入 Engines
run_from_audio(audio, cut_points, "fresh",
  engines=Engines(transcriber=FunASRLocal(device="cuda"), aligner=..., llm=...),
  opts=PipelineOptions(source_media=..., render=RenderOptions(...)))

# 已有 transcript（最常用）：从 stage 2 起跑
run_from_transcript(transcript, cut_points, "fresh", engines=Engines(), opts=PipelineOptions(...))

# 一期精剪/混剪：N 区间 → 一条连续长片（字幕时间轴偏移合并）
# 输出顺序 == cut_points 列表顺序（可 ≠ 原片时间序：收尾段在原片靠前也能列最后）
from garden_core.pipeline import run_montage
run_montage(transcript, cut_points, "fresh", Engines(style_resolver=YamlStyleResolver()),
  PipelineOptions(source_media=..., render=RenderOptions(render_vertical=False, ...)),
  montage_id="ep01")  # → 单个 RenderResult（一条 *_horizontal.mp4 + 连续 srt/ass）
```

详细 API 见 [garden-core-api.md](references/garden-core-api.md)；投产权威架构（7-stage / 两入口 / FunASRLocal / render_gate / 竖版坐标系 / 字体许可）见 [garden-core-pipeline-canonical.md](references/garden-core-pipeline-canonical.md)。

> **环境**：conda env `garden`（funasr≥1.3 / torch≥2.5+cu118 / numpy≥2.0 / CUDA GPU）。跨平台支持 Windows/Linux/macOS。

### ⚠️ garden 全链启动铁律（跑 garden_core 任何 python 入口都先做这一步）

直接调 conda env 的 python 可执行文件 **不 activate** 会让 numpy/torch 的 C 扩展加载失败，报**误导性** `FileNotFoundError: [WinError 206] 文件名或扩展名太长`（在 `torch/lib` 的 `add_dll_directory` 处）+ `No module named 'numpy._core._multiarray_umath'`。**这跟路径长度无关**——是 conda 科学栈（MKL/CUDA DLL）的目录没进 PATH。别去查 PATH 长度、别降 numpy、别怀疑 env 坏了。

**首选**：用 `scripts\run_garden.bat python <脚本>`（已封装下面整套 garden DLL + ffmpeg PATH + `PYTHONPATH=src`，不继承调用者环境，从任意 cmd 调用都自洽）。手动/调试时的等价子 shell（prepend garden env DLL 目录 + ffmpeg，用 `( … )` 隔离避免污染 session）：
```bash
# Linux/macOS:
(
  G="$CONDA_PREFIX"                        # 或手动指定: /path/to/conda/envs/garden
  export PATH="$G/bin:$PATH"
  cd /path/to/repo
  PYTHONPATH=src python <脚本.py>
)

# Windows (git-bash):
(
  G="$CONDA_PREFIX"                        # 或手动指定: /c/Users/<you>/anaconda3/envs/garden
  export PATH="$G:$G/Library/bin:$G/Library/usr/bin:$G/Library/mingw-w64/bin:$G/Scripts:$G/DLLs:$G/bin:$PATH"
  cd /path/to/repo
  PYTHONPATH=src "$G/python.exe" <脚本.py>
)
```
- **必须用 `( )` 子 shell**：terminal 的 `export` 跨调用持久，若直接 `export PATH=精简版` 替换会污染整个 session（`/usr/bin` 丢失 → cat/rm/tail/write_file 全挂）。子 shell 让 PATH 改动用完即弃。prepend（`…:$PATH`）不要替换。
- ffmpeg 需在 PATH 中（conda `environment.yml` 已包含；手动安装请确认 `ffmpeg -version` 可用），漏了它渲染报 `ffmpeg binary not found on PATH`。
- 验证序列：先轻量 import 栈（numpy/torch/funasr/garden_core 各一行 `OK/FAIL`）→ 再端到端 smoke，不要直接跑重活。

### MCP 已退役（FunASRLocal 是唯一 backend）

转录的**标准（唯一）backend 是进程内 `FunASRLocal`**（`from garden_core.stage_asr import FunASRLocal`，`device="cuda"`）：`from funasr import AutoModel` 直接加载 Paraformer+VAD+Punc+SPK 在 GPU 上转录，零网络、零 server、零 503。

> **长音频（整期）转录**：`FunASRLocal` 已内建 VAD 静音对齐分块 + 块间显存释放，长音频不 OOM（用户铁律：OOM 防护是代码职责，不靠人跑时盯）。设计/验证/speaker 跨块 tradeoff 见 [funasr-local-long-audio.md](references/funasr-local-long-audio.md)。

> 历史：旧 `FunASRMCPBackend`（`localhost:8000/mcp`）是 **Docker 时代为"容器 python 摸不到 GPU"才搭的跨进程桥**；Windows 原生后理由消失。两个 MCP backend（`funasr_backend.py` + `funasr_mcp_backend.py`，共 ~532 行）已删除（commit c956964），`FunASRLocal` 已从 test 扶正为 `src/garden_core/stage_asr/funasr_local.py`。端到端验证：25 seg / 含标点时间戳 → 横竖版 MP4 PASS。诊断与验证全程见 [garden-env-invocation.md](references/garden-env-invocation.md)。

> ⚠️ Hermes 侧若 config.yaml 仍挂着 `funasr` MCP server 条目，每次 session 启动会试连 8000 报 503 噪音 —— 退役后需清掉该条目（+ 归档 server 端 `setup_funasr_mcp.bat` / `mcp-server-funasr/`），重启 gateway 生效。

### 投产环境包装：`scripts/run_garden.bat`

跑 garden_core 任何 python 入口（转录/渲染）都需要 garden conda env 的 DLL 目录 + ffmpeg 进 PATH。**投产用 `scripts/run_garden.bat`**（受控基座，不继承调用者 PATH/PYTHONPATH → 避免别的 venv 的 numpy/torch 遮蔽 + `WinError 206`）：

```bash
# 接口：run_garden.bat <command>
scripts\run_garden.bat python tests\smoke_full_pipeline_local.py
scripts\run_garden.bat python -c "from garden_core.stage_asr import FunASRLocal"
```

从 git-bash 调这个 .bat 的**正确组合**是 `MSYS_NO_PATHCONV=1 cmd /c '...'`（单斜杠 `/c` + 单引号防反斜杠转义）：

```bash
cd .
MSYS_NO_PATHCONV=1 cmd /c 'scripts\run_garden.bat python tests\smoke_full_pipeline_local.py' 2>&1
```

⚠️ `cmd //c`（双斜杠）配 `MSYS_NO_PATHCONV=1` 是**错误组合**：`//c` 不被转、cmd 不认 → 进交互模式、命令没执行（只打 banner）。两个正确组合二选一：`MSYS_NO_PATHCONV=1 cmd /c`（单斜杠）或不带 NO_PATHCONV 的 `cmd //c`。

下方「garden 全链启动铁律」的子 shell prepend 方式仍可用于**临时调试**；投产固定走 wrapper。

---

## 投产标准流程（audit 三道嵌入）

```
① 项目准备       按模板建目录：[项目目录模板](references/project-directory-template.md)（源视频绝对路径/输出/勘误 · garden_core 纯 API 不依赖 project.yaml）
② 全链转录对齐纠错  → 🛡️ 转录自愈闭环（PipelineOptions.heal_gaps=True 强制开）
   ⚠️ ProofOptions 默认 enable_llm=False。生产必须显式注入 LLMClient + enable_llm=True + enable_dual_channel=True。漏了这行 → normalize/phonetic 跑空、transcript 带着 ASR 错误进渲染。见 [proofread-llm-required.md](references/proofread-llm-required.md)
   💡 未知切点时用「先转录→再看内容→再规划」分离工作流：[transcribe-then-cut-workflow.md](references/transcribe-then-cut-workflow.md)
③ 制作人切片规划   Hermes Agent 决策剪辑意图 → 用户确认（见工作流0）
④ 渲染           → 🛡️ render_gate 机械门（默认开，字号比例/安全区）
⑤ 出品终审       → 🛡️ quality-audit LLM 审核（★每条全审，质量优先）
⑥ NAS 交付       本地 SSD 渲 → 传 NAS → 逐字节核验（见 nas-access）
```

**audit 三道分层**：
- 🛡️ **转录自愈**（机械，`gap_heal`）：VAD 检漏段 → healer 补 → overlap 检查。`heal_gaps=True` 投产强制开。
- 🛡️ **render_gate**（机械，零 LLM，默认开）：字号横竖比例一致 / 字幕安全区。BLOCK 报「哪条·哪维度·实际vs期望」，不自动改片。⚠️ **simplified（繁简）检测维度已移除**——ASR 是 zh-cn 简体模型、proofread 的 normalize 层已繁→简兜底，再查简体属重复且会假阳性误伤简繁同形字（"硬/软/著"边界，曾把"硬"误 BLOCK），故砍掉，只留 font_ratio + safe_area。
- 🛡️ **quality-audit**（LLM，每条全审）：技术/文化/传播/影视四维度出品终审。调 `quality-audit` skill。

---

## 工作流 0：制作人对话（创意中枢，强制入口）

**⚠️ 无论用户请求多具体，都先进工作流 0，不跳步。**

**⛔ 铁律：禁止手写转录脚本**。转录走 `garden_core` 标准 API——`run_from_audio`（全链）或分步调 `stage_asr.transcribe` + `stage_align.align` + `stage_proofread.proofread`。**绝对不手写 `AutoModel()` 调用、不写临时 `.py` 绕开产线**。步骤②（转录+对齐+纠错）是产线强制步骤，不可跳过对齐和纠错。之前两次手写 `run_transcribe.py` 绕过产线，导致 transcript 缺对齐+纠错，用户暴怒。这条刻在第一条。

**⚠️ 字幕文本简体**：由 ASR（zh-cn 简体模型）+ proofread `normalize` 层（繁→简）双重保证。render_gate **不再做**简体检测（会假阳性误伤简繁同形字），别再给质量门加繁体校验。

制作人是创意中枢，**不执行剪辑**，负责对话→意图→编排→审核。**判断先行，不当填表项目经理**——用户选制作人是信任审美判断；内容气质明显时直接给方向建议，不列「A 还是 B」推卸决策。

### 四阶段
1. **创作对话**：探讨思想（核心观点/金句/主线）、受众（谁/平台）、策略（长 vs 短/系列）、内容（满意段/弱化段/风格偏好）。一次聚焦一个维度，表达清晰则不追问、直接推进。
2. **意图转化**：输出**创作蓝图**（核心意图 + 受众 + 传播策略 + 剪辑意图列表[类型/筛选标准/时长/数量/平台] + 质量标准），**等用户确认**。
3. **执行编排**：按蓝图调对应工作流 → 每个意图完成调 quality-audit 审核 → 不过则 autoresearch 优化（≤3 轮）→ 过则下一意图。验证由 Agent 自主完成（smoke / 抽帧 / byte核验），**不向用户叙述验证步骤**——只报告 PASS/FAIL + 关键指标。阻塞才升级（gate BLOCK / OOM / 依赖缺失）。
4. **交付发布**：成品清单确认 → 发布物料（信息卡/版权/总览）→ NAS 交付。

### 触发规则
| 用户表达 | 制作人行为 |
|---|---|
| 明确需求（"剪 3 个短视频"） | 快速确认 → 直接出蓝图 → 等确认 → 执行 |
| 模糊想法（"做点东西"） | 进阶段一完整对话 |
| 修改（"字幕大一点"） | 定位阶段 → 调参 → 重跑相关步骤 |
| 质量不满 | autoresearch 优化 → 重新生成 |

---

## 5 个执行工作流（均由 garden_core 库执行）

- **工作流1 · 一期一剪**：整期精剪。粗剪规划（标冗余）→ 精剪 → 字幕 → 响度标准化 → 横版4K+竖版。执行走 `run_montage`（去废料保主体 + preview 高光片头 + 乱序拼接），完整 recipe 见 [fine-cut-montage-workflow.md](references/fine-cut-montage-workflow.md)。
- **工作流2 · 内容原子化**：长视频拆独立短视频（抖音/Shorts）。高光检测 → 钩子前置 → 独立微叙事 → 横竖双格式。宁精勿滥（5-8 条 > 20 条平庸）。
- **工作流3 · 主题系列**：按主题/叙事线组织成系列。可读 `project.yaml` 的 `sources.wiki/outline/notes` 辅助规划 → 每章 2-4min → `clips.yaml`。
- **工作流4 · 全平台出品**：适配各平台规格（B站/抖音/YouTube/小宇宙/存档母带）。基于 `RenderResult` 做 ffmpeg 转码。
- **工作流5 · 素材库打包**：标准化目录交付（full_episode/clips/platforms/assets + COPYRIGHT/summary）。

切片渲染统一：组 N 个 `CutPoint` → 一次 `run_from_transcript()`。`clip_id` 用 ASCII 编号（避免中文文件名），中文 `title` 当元数据；脚本顶部 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 防 Windows GBK print 崩。只重渲单方向用 `RenderOptions(render_horizontal=False)`。

---

## 字幕样式：xr 是唯一主变量（用户铁律）

样式定义在 `stage_style/styles/<name>.yaml`，**配置层清晰简单，不耦合老代码**。

1. **xr（`font_size_ratio` = font_size/video_height）是唯一主变量**，描边/阴影/留白全从 xr 按比例算。「放大一倍」= 只改 xr，不给派生值单独加配置项。
2. **xr 配置必填、代码零硬编码**：`molds.py`/`DEFAULT_STYLE` 不持有 xr 真值（默认 None），缺失 → `require_xr` 抛 `ConfigError`，绝不静默兜底。调字号 = 改 `styles/<name>.yaml`，**永不改 .py**。
3. **新增样式只加 yaml，不动 molds.py**：yaml 写 `mold: <基底>` + 覆盖字段。⚠️ 覆盖描边/阴影用 **StyleDef 字段名** `outline_width`/`shadow_depth`（不是 mold 的 `outline_ratio`/`shadow_ratio`，否则被 `_apply_overrides` 静默丢弃）。

**字体可读性根因：字重 > 描边**。字幕「看不清」先查字体族——瘦宋体（Noto Serif SC）横画细，加描边只是用黑边补瘦、与「清新」背道而驰。正解换饱满**黑体**（Noto Sans SC Medium）。当前样式：`cinematic`（电影宋体）、`fresh`（清新黑体 Medium，纯白/描边2.8px/阴影2.5px，均无背景框）。调参法（改 ASS Style 行 + ffmpeg 烧单帧秒级对照）、OFL 商用许可见 [subtitle-font-readability.md](references/subtitle-font-readability.md) 和 [subtitle-style-rapid-iteration.md](references/subtitle-style-rapid-iteration.md)。

---

## 质检与陷阱（健壮代码，不写补丁）

**原则**：garden_core 已把旧代码的补丁问题健壮化——yuv420p 用 ffmpeg 原生 `scale=-2` 取偶、字幕背景框走 ASS 层（libass 原生，非 ffmpeg crop→boxblur 补丁）、删了 bg_width_scale 过补偿。**不再为旧坑写补丁陷阱，写健壮代码。**

- **LLM 纠错默认关闭**（`ProofOptions.enable_llm=False`）：不显式开 = 全链转录缺最后一环。投产必须 `ProofOptions(enable_llm=True)` + `LLMClient(timeout=300.0)` + 从 Hermes `.env` 注入 `DEEPSEEK_API_KEY`（garden env 不含此变量）。详见 [garden-core-pipeline-canonical.md](references/garden-core-pipeline-canonical.md)。
- **多源视频**：两个以上视频文件拼接的素材，全链（转录/对齐/纠错）跑在拼接音频上，渲染分批复用各自源文件 + 偏移时间戳。详见 [multi-source-video-rendering.md](references/multi-source-video-rendering.md)。

- **竖版坐标系**（已修，防回归）：竖版字号/margin 按内容区高（`video_width×9/16≈607`）算，不是全屏 1920。错了会 3.2 倍偏大。新库 `ass_writer` 已修，16:9 横版字节级退化为原代码。
- **⚠️ garden conda env 无 DEEPSEEK_API_KEY**：`run_garden.bat` 只设置 PATH/PYTHONPATH，不注入 API key。任何需要 LLM 的 stage（proofread llm_corrector、dual_channel）必须在脚本中显式注入：从 `~/.env` 读取 → `os.environ["DEEPSEEK_API_KEY"] = ...`。否则 `LLMClient.available` 返回 False，LLM 纠错层静默跳过。见 [proofread-llm-required.md](references/proofread-llm-required.md)。
- **render_gate 自动拦**：字号比例失真这类机械错由 gate BLOCK，不靠人眼。
- **重渲省时（ffmpeg_render 当前无 skip_existing）**：`run_montage`/`run_from_transcript` 重跑会**重渲全部片段**（一期精剪那段 57min 4K 会白等 1+ 小时）。若上次已渲出 `release/<clip_id>_horizontal.mp4`（如被 gate 误 BLOCK 停在 concat 前），别重跑——直接 `from garden_core.stage_render.concat import concat_videos; concat_videos([已渲片段按输出顺序], out)` 拼成片（stream copy 秒级，烧录字幕随画面连续，无需重渲）。已渲片段过没过 gate 看上次 BLOCK 报告：只报 simplified = font/safe 早过了。
- **兜底要点**（非补丁）：字体找不到 → warning + ratio 估算降级；CJK 测量仅「带背景框样式」算框宽时用（cinematic/fresh 无背景框，不触发）。
- 转录/字幕审计（VAD 交叉比对、漏段回填）见 [transcript-audit.md](references/transcript-audit.md) + [forced-alignment-workflow.md](references/forced-alignment-workflow.md)。

---

## 协作与交付

- **交付文案格式**：面向客户的总结用纯文本、分点编号、极简。不要 markdown、不要段落叙事。示例格式：
  ```
  ────────────────────────
  Tesla FSD 试驾 · 自动剪辑

  本次成果
  · 21分钟试驾 → 19条原子功能切片
  · 保留现场真实对话与即兴反应
  · 横竖双格式，4K，全平台适配

  剪辑能力
  1. 意图对齐
  2. 原子化功能识别
  ...
  ```
- **代码改动走 Reasonix**（不是 CC）：`reasonix` skill + `rx_run.sh` 启动器（自读 `.env`，零 key 拼接）。Brief 先给用户审再喂。
- **飞书发视频**：`MEDIA:` 不支持视频，用 lark-cli（提封面 + 压到 30MB 内 + cd 到目录用相对路径）。见 [feishu-video-delivery.md](references/feishu-video-delivery.md)。
- **NAS 交付**：本地 SSD 渲完 → cp/robocopy 到 NAS → 去 NAS 端 ls 逐字节核对大小（防 0 字节/截断），不靠「命令报 DONE」。见 `nas-access` skill。

---

## 风格复刻 / 视觉提取（已存档，不在工作流）

VLM 风格提取、参考帧复刻、字体测量整套 → 已移出工作流存档（待重新开发）。当前不用 VLM 复刻，走「打造原创预定义风格」（xr + mold）。需要时从归档取。

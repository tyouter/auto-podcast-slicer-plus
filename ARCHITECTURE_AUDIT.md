# 架构审计报告：代码库模板边界

**审计对象**：`auto-podcast-slicer-plus`（garden_core 执行库 + 三平台 skill）
**审计边界**：代码库只含「通用工具 + 模板」；具体项目的实际数据应生成/存放在用户指定的项目目录，不进代码库。
**审计方式**：只读分析（未修改任何源码/配置/文档；仅产出本报告）。所有结论附文件路径 + 行号 / 具体内容为证。
**审计日期**：2026-06-25

---

## 0. 总体结论（TL;DR）

| 维度 | 评级 | 一句话 |
|---|---|---|
| 1. 代码层 `src/garden_core/` | ✅ **良好** | 产物强制写到用户传入的 `output_dir`，errata/hotwords/style 全是模板/外部注入，无硬编码项目数据 |
| 2. 代码库现有（被 git 跟踪的）内容 | ✅ **干净** | 被跟踪文件无实际项目数据；产物目录已 gitignore |
| 3. skill + reference 文档 | ❌ **多处违反** | reference 把某次真实 Tesla 试驾项目的实测数据/真实文件名/真实勘误条目/真实本地路径当作"通用示例"写进了文档 |
| 4. 架构设计本身 | ⚠️ **代码侧清晰、文档侧不一致** | 「模板→实例化」边界在代码 + `project-directory-template.md` 里建立得很好，但被一众 reference 文档反向破坏 |

**核心病灶**：违反集中在一处——**reference 文档把"某次真实项目（特斯拉 FSD 试驾）的实证数据"固化成了"通用示例"**。代码库本身是干净的，但文档侧的污染会让任何复制这些 reference 的下游用户/Agent 把别人的项目数据当模板继承。

---

## 1. 边界现状评估（设计良好、确实遵守边界的部分）

### 1.1 代码层强制用户指定输出目录 ✅
- `src/garden_core/stage_render/__init__.py:22-43` —— `RenderOptions.__init__` 的 `output_dir: str` 是**必填位置参数（无默认值）**，不传无法构造。所有渲染产物（`.srt`/`.ass`/`.mp4`）一律 `os.path.join(opts.output_dir, ...)` 写入（同文件 L57/61/70）。
- `src/garden_core/io_/sink.py:1-25` —— 全库**唯一**写盘入口，写哪由调用方传的路径决定，库本身不持有任何固定输出位置。
- `src/garden_core/pipeline.py:153-203`（`run_montage`）—— montage 长片也写 `opts.render.output_dir`，不写死。

### 1.2 项目专属数据（勘误 / 热词）走外部注入，库内零默认数据 ✅
- `src/garden_core/stage_proofread/__init__.py:32-37` —— `ErrataConfig` 默认 `flat={}`，`ErrataConfig.empty()` 是唯一默认；库内**没有任何内置勘误条目**。
- `src/garden_core/config.py:38-61`（`build_errata_config`）—— 勘误内容来自**用户传入的 `errata_yaml_path`**（项目自己的 errata.yaml），文件不存在则返回空配置。
- `src/garden_core/stage_asr/hotwords.py:20-31`（`load_hotwords`）—— 热词来自**用户传入的文件/可迭代对象**，库内无任何默认热词。

### 1.3 样式系统是纯模板 ✅
- `src/garden_core/stage_style/styles/*.yaml`（fresh/cinematic/broadcast 等 8 个）—— 全部是**比例模板**（xr、outline_width、shadow_depth 均为 font_size 的比例），无任何项目数据、无硬编码字号真值。`fresh.yaml` 全文检查为纯审美参数。
- `src/garden_core/stage_style/molds.py:1-40` —— molds 是"分辨率无关的比例模板"，由 `video_height` 展开成 `StyleDef`。
- `src/garden_core/types.py:159-188`（`StyleDef`）—— `font_family` / `font_size_ratio` **必填且无代码默认**（缺失抛 `ConfigError`），杜绝静默兜底。

### 1.4 代码库被跟踪内容无项目数据 ✅
- `git ls-files` 全量核对：被 git 跟踪的文件中**没有任何**实际切片视频 / 转录 / 勘误条目 / 项目专属配置。
- 产物目录 `task_*/`、`_e2e_out/`、`_m2_out/`、`tests/`、`_verify/`、`_m3_out/` 均已在 `.gitignore` 中（`git ls-files task_01/` 等返回空）。说明"commit 过实际视频"的反模式已在 `da4cf9a` 清除并加忽略规则。

### 1.5 模板/实例化边界在文档侧有正确建立 ✅
- `skills/claude-code/references/project-directory-template.md:1-105` —— 明确画出「项目目录骨架（源视频绝对路径/`output/`/`corrections.yaml`）」，初始化命令 `echo "corrections: {}" > <project>/corrections.yaml`（L61），并强调"garden_core 纯 API 不依赖 project.yaml""开新项目 = 按模板建目录 + 拷一份 style yaml + 写脚本传 PipelineOptions/RenderOptions/ErrataConfig"（L102-105）。
- `skills/hermes/SKILL.md:23-25` —— 明确"skill = 通用剪辑执行能力，不耦合任何具体项目"。
- `README.md`、`ARCHITECTURE.md` 全文为通用库描述，无项目数据。

---

## 2. 违反清单

> 说明：以下违反**几乎全部出现在三平台 skill 的 reference 文档中**（hermes/claude-code/openclaw 三份内容相同或近似），属于维度 3。代码层（维度 1）与被跟踪仓库内容（维度 2）未见实质违反。

### V1 ⛔ reference 把真实项目（特斯拉 FSD 试驾）的实测数据当成"通用示例"
**维度**：3（skill + reference）
**严重度**：高——把别人项目的隐私实证数据固化进了开源模板库。

| 文件（三平台均有同名文件） | 行号 | 违反内容（实证数据） |
|---|---|---|
| `skills/{hermes,claude-code,openclaw}/references/multi-source-video-rendering.md` | L5 | "如特斯拉试驾：**<SRC_FILE_1> 14:10 + <SRC_FILE_2> 7:25**"——真实拍摄机型号 + 真实时长 |
| 同上 | L34 | "仍跑在拼接后的单一音频上（**`tesla_full.wav`**）"——真实项目音频文件名 |
| 同上 | L41 | "本次 **Tesla 项目实测**：seg1 **850.18s** / seg2 **444.78s**，拼接 **1294.96s**。Batch 1 **13 条**（0–850s）→ SRC1，Batch 2 **6 条**（850–1294s）→ SRC2（-850s 偏移）。**19/19 全过**"——完整真实项目指标 |
| `skills/*/references/funasr-local-long-audio.md` | L23 | " **`C0257_mixed_normalized.wav`**（86min）：17 块全跑通…**2019 segments**；末段 **end_s=5168.15s / 音频 5168.16s**"——真实源文件名 + 真实转录指标 |
| `skills/*/references/proofread-llm-required.md` | L78 | "本次 **Tesla 项目**：**70 处修正后仍有 8 处**" |
| 同上 | L84 | 真实勘误条目示例：`ErrataConfig(flat={"途材": "FSD", "逗哈": "都行", ...})`——**这是某次真实项目的真实勘误**，混进了通用文档 |
| `skills/*/references/garden-core-pipeline-canonical.md` | L54 | `ErrataConfig(flat={"途材": "FSD", ...})`——同上，真实勘误进"投产权威架构"文档 |
| `skills/*/references/transcript-audit.md` | L29 | "已验证案例：86 分钟播客 → **19 个 chunk_corrected** → **1375 段**，时间戳 **0-5168s**" |
| `skills/*/references/vad-subtitle-verification.md` | L138/142/146 | "VAD 段：**619 个**，校准 transcript：**1375 段**…最终：**1383 段，0~5168s**" |
| 同上 | L148 | "DeepSeek 纠错管线在 **chunk 09/10 边界跳过 45s** 内容"——真实项目排错细节 |
| `skills/*/references/known-pitfalls.md` | L722 | "19 个文件，**1375 段**，含 start_ms/end_ms" |

**问题本质**：这些数字（5168s / 1375 段 / 850.18s / <SRC_FILE_1> / C0257 / tesla_full.wav / 途材→FSD）是**某一个具体特斯拉试驾项目的运行实证**，被原样写进了号称"通用"的 reference。它们既不是模板也不是虚构示例，是真实项目数据沉淀错了位置。

---

### V2 ⛔ reference 里硬编码真实本地绝对路径 / 真实设备文件名
**维度**：3（skill + reference）

| 文件 | 行号 | 违反内容 |
|---|---|---|
| `skills/*/references/transcribe-then-cut-workflow.md` | L16 | `audio = AudioRef(path=r"N:\project\source\full.wav")`——真实风格本地路径（`N:` 盘 + `project` 目录名） |
| 同上 | L28 | `PipelineOptions(source_media=r"N:\project\<SRC_FILE_1>_D.MP4", ...)`——**真实大疆相机原始文件名** `<SRC_FILE_1>_D.MP4`，与 V1 的特斯拉项目同源 |
| `skills/hermes/references/garden-core-pipeline-canonical.md` | L53 | `open(r"D:\Hermes\.env").read().split("DEEPSEEK_API_KEY=***)[1...`——① 硬编码**作者本机绝对路径** `D:\Hermes\.env`；② 还附带一段半掩码的 API key 切片代码。这是把"我机器上怎么读 key"写进了"投产权威架构"文档。**（仅 hermes 平台有此行；claude-code/openclaw 同文件已泛化为"项目根的 .env 或环境变量"。）** |

**对照正面例子**：`skills/claude-code/references/garden-core-e2e-validation.md:18` 用 `SOURCE_VIDEO = r"D:\path\to\source.mp4"`、`garden-core-api.md:22` 用 `/path/to/source.mp4`——这些是正确的占位符写法。V2 的几处应统一改成这种占位符。

---

### V3 ⚠️ SKILL.md / CLAUDE.md 的交付文案示例夹带具体节目名
**维度**：3（skill + reference）

| 文件 | 行号 | 违反内容 |
|---|---|---|
| `skills/hermes/SKILL.md` | L220 | 交付文案示例里写死 "**Tesla FSD 试驾** · 自动剪辑" + "21分钟试驾 → 19条原子功能切片"——把具体节目名 + 具体项目指标当模板示例 |
| `skills/claude-code/CLAUDE.md` | L58-75 | 同位置的"Delivery Format"示例已泛化为 "Project · Auto Clip / X min source → N atomic clips"——**这才是正确写法**，hermes 版应向其对齐 |

---

### V4 ⚠️ 工作树存在未跟踪、且未被 gitignore 的项目专属脚本（泄漏风险）
**维度**：2（代码库现有内容）/ 4（架构）
**现状**：`git status` 显示 `scripts/` 为未跟踪目录，内含 **Tesla 专属编排脚本**：
- `scripts/tesla_audit.py`、`scripts/tesla_gate.py`、`scripts/tesla_refix.py`、`scripts/tesla_stage02.py`、`scripts/tesla_stage04.py`（文件名即带项目代号）

**问题**：`.gitignore` 只忽略了 `scripts/run_garden.bat`，**没有忽略 `scripts/tesla_*.py`**。这些脚本当前虽未被跟踪，但既未被忽略、又躺在仓库目录里，属于"一次 `git add .` 就会进库"的高危状态——正是本审计要防的"项目产物/项目专属逻辑进代码库"反模式的入口。（注：审计未读取其内容，仅据文件名判定其项目专属属性。）

**同类**：工作树还散落 `.hermes-tmp.37684`、`.hermes-tmp.37693`、`.rx_cleanup.md`、`.rx_review.md` 等临时/审查草稿文件，同样未跟踪也未忽略。

---

### V5 ⚠️ API 入口对"源媒体路径"未强制必填（宽松默认，非硬违反）
**维度**：1（代码层）/ 4（架构）
**现状**：
- `src/garden_core/pipeline.py:57` —— `PipelineOptions.source_media: str = ""`（默认空串）
- `src/garden_core/pipeline.py:69` —— `run_from_transcript(..., audio_path: str = "")`（默认空串）

**问题**：与 `RenderOptions.output_dir`（必填、无默认）不同，源媒体路径给了空串默认值。空串时代码会"优雅降级"（如 L257-260 对齐器跳过、L291-293 仅在非空时覆盖 source_ref），不会崩，但意味着调用方可能忘记传真实源媒体、却拿到"看似成功"的结果。这不是"把数据写进代码库"的边界违反，而是**边界未被 API 强制收紧**——建议把"项目源路径/输出路径"都设为必填以从结构上保证实例化必须来自用户。

---

### V6 ⚠️ reference 文档大量描述已废弃的旧 CLI/协议（架构一致性噪声）
**维度**：4（架构）
**现状**：`skills/*/references/known-pitfalls.md` 通篇围绕已废弃的 `garden clip` CLI、`project.yaml`、`production_watcher`、`errata_engine`、`load_custom_errata` 等旧产物展开（如 L27-36、L367-390、L586-619、L718-722）。
**问题**：执行层 `src/garden_core/` 是纯库、明确"无 CLI、无 watcher、无 project.yaml"（`pipeline.py:1-6`、`README.md`、`SKILL.md:31-33`）。这些 reference 描述的是**已被架构判定废弃的旧形态**，留在库里会模糊"模板（新库 API）↔ 实例化（项目脚本调 API）"的边界，让读者误以为还要写 `project.yaml` / 跑 `garden clip`。属架构一致性违反，非数据泄漏。

---

## 3. 修复建议

### A. 机械可做（路径泛化 / 删数据 / 加忽略，无需改架构）

> 这些都是文档/配置层面的等价替换，不改任何代码逻辑。

**A1. 清洗 V1 的真实项目数据（reference 文档去实证化）**
对 `skills/{hermes,claude-code,openclaw}/references/` 下的下列文件，把"真实项目实测值"替换为占位符或泛化表述（3 个平台同改）：
- `multi-source-video-rendering.md`：`<SRC_FILE_1>/<SRC_FILE_2>` → `<source1.MP4>`/`<source2.MP4>`；`tesla_full.wav` → `<concatenated_audio.wav>`；L41 的 `850.18s/444.78s/1294.96s/13条/6条/19/19` 整段实测 → 改成"用 ffprobe 取每段实际时长设 `SEG1_END`，按 SEG1_END 偏移分批（示意：seg1 约 Ts / seg2 约 Ts）"。
- `funasr-local-long-audio.md` L23：`C0257_mixed_normalized.wav` → `<long_audio.wav>`；`2019 segments / 5168.15s` → 泛化为"长音频（如 ~85min）：分块全跑通，末段 end_s ≈ 音频总时长"。
- `transcript-audit.md` L29、`vad-subtitle-verification.md` L138-148、`known-pitfalls.md` L722、`forced-alignment-workflow.md`（hermes L28）：所有 `1375 段 / 1383 段 / 619 / 5168s / 45s / 19 个 chunk` → 删除具体数字或改为"（示例：N 段 / Ts）"。
- `proofread-llm-required.md` L78、`garden-core-pipeline-canonical.md` L54：删除"本次 Tesla 项目：70 处修正后仍有 8 处"；勘误示例 `{"途材": "FSD", "逗哈": "都行"}` → `{"<asr_wrong_word>": "<correct_word>", ...}`。

**A2. 清洗 V2 的硬编码本地路径（统一占位符）**
- `transcribe-then-cut-workflow.md` L16/L28：`r"N:\project\source\full.wav"` → `r"<project>\source\full.wav"`；`r"N:\project\<SRC_FILE_1>_D.MP4"` → `r"<project>\source\source_video.MP4"`。
- `garden-core-pipeline-canonical.md`（hermes）L53：`open(r"D:\Hermes\.env")...` → 改为 claude-code/openclaw 同位置已有的泛化表述"从项目根的 `.env` 或环境变量 `DEEPSEEK_API_KEY` 注入"，并删除半掩码 key 切片片段。

**A3. 清洗 V3 的节目名**
- `skills/hermes/SKILL.md` L220-225：交付文案示例 "Tesla FSD 试驾 / 21分钟试驾 → 19条" → 对齐 `skills/claude-code/CLAUDE.md` L58-75 的泛化版（"Project · Auto Clip / X min source → N atomic clips"）。

**A4. 收口 V4 的项目脚本泄漏入口（gitignore）**
- 在 `.gitignore` 增加：`scripts/tesla_*.py`（或更稳妥地 `scripts/tesla_*`）、`.hermes-tmp.*`、`.rx_*.md`。
- 进一步建议：项目专属编排脚本（`tesla_*`）本就不应放在开源仓库目录下，应迁出到各自的项目目录；仓库 `scripts/` 只保留通用脚本（`check_env.py`、`run_garden.bat`）。

**A5. 收口 V6 的旧文档噪声**
- 将 `known-pitfalls.md` 等通篇描述已废弃 `garden clip` CLI / `project.yaml` 的内容，要么删除、要么集中迁移到一个明确的"legacy 参考"小节并标注"以下为旧 slicer 行为，garden_core 不适用"，避免与"新库纯 API"的模板边界混淆。

### B. 需要架构调整（改 API 形状/约束）

**B1. 收紧 V5：把源媒体路径设为必填（无默认值）**
- `src/garden_core/pipeline.py:57`：`PipelineOptions.source_media` 去掉 `= ""` 默认，或在 `_prepare_plans` 入口处对"既无 `source_media` 又无 `audio_path`"显式 `raise ValueError`，从结构上强制"实例化必须由用户提供源路径"——与 `RenderOptions.output_dir` 的强制风格对齐。
- 这是把"边界靠文档约定"升级为"边界靠类型/运行时强制"，是本审计推荐的根因级修复。

**B2. 给 reference 建立一条"示例数据卫生"硬规（流程性架构补强）**
- 在贡献指南/`ARCHITECTURE.md` 增加一条明确条款：**reference 文档中的所有示例必须是占位符（`<...>` / `/path/to/`）或明确标注的虚构数据；任何真实项目的运行数字、真实文件名、真实勘误条目、真实本地路径不得进入 `skills/*/references/`**。
- 可加一个轻量 CI 检查（grep 黑名单词：`tesla`/`DJI_0`/`C0257`/`途材`/`D:\Hermes`/`N:\project` 等）防止回归——这正是当初"commit 过实际视频"反模式在文档侧的等价物。

---

## 4. 附：审计方法与证据索引

- 被跟踪文件清单：`git ls-files`（共 ~110 个文件，含 `src/garden_core/**` + 三平台 `skills/**` + 顶层配置/文档）。
- 代码层硬编码扫描：`grep -rn -E "[A-Z]:\\\\|/Users/|/home/|D:\\\\Hermes" src/` → 命中**仅在 `__pycache__/*.pyc` 二进制**（已 gitignore），源码 `.py` 零命中。
- 项目数据关键词扫描（`tesla|特斯拉|DJI_00|C0257|FSD|1375|5168|1294|850\.18|途材|逗哈|N:\\\\project|D:\\\\Hermes`）→ 命中**全部位于 `skills/*/references/*.md` 与 `skills/hermes/SKILL.md`**，源码零命中（佐证维度 1 干净、维度 3 受污染）。
- 样式/勘误/热词默认值核查：`stage_proofread/__init__.py`、`config.py`、`hotwords.py`、`stage_style/styles/*.yaml`、`molds.py` 均确认无内置项目数据。
- 工作树未跟踪项：`git status --short` → `?? scripts/`、`?? .hermes-tmp.*`、`?? .rx_*.md`。

> 本报告为只读审计产出，未对任何源码/配置/文档执行写操作，未执行任何 git 写操作。

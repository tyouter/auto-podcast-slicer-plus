# 管线标准调用机制 Review

> 范围：只读架构诊断。基于 `src/garden_core/pipeline.py`、`src/garden_core/io_/{source,sink}.py`、`scripts/tesla_*.py`（5 个）、`skills/hermes/SKILL.md` 的实际证据。
> 立场：正向架构改进——设计「管线本应提供的标准调用机制」，让 agent 自然不拼脚本，而不是批评 tesla 脚本本身。

---

## 0. 结论先行（TL;DR）

agent 拼脚本不是因为懒，而是因为 **`pipeline.py` 的三个入口（`run_from_audio` / `run_from_transcript` / `run_montage`）是「单次、全 stage、内存内」的同步函数**——它们：

1. **不落中间产物**（transcript.json 的存/读不对称：有 `load_transcript_json`，无 `save_transcript_json`）。
2. **不支持分阶段执行 + checkpoint-resume**（一次调用从 stage 2 跑到 stage 7，中途无法停、看、纠、续）。
3. **不处理多源视频**（`source_media` 是 `PipelineOptions` 的单值字段，agent 被迫自己分批 + 偏移时间戳）。
4. **质量门只能对内存中的 `RenderResult` 跑**（无法对已落盘的产物目录复审，agent 只能手搓 ffprobe / 伪造 `RenderResult`）。
5. **没有项目级「运行」概念**（errata 注入、API key 注入、cut_points 来源、源文件映射全部散落在调用方）。

这五个缺口恰好一一对应 tesla 那五个脚本要做的事。下面逐条用证据说话，再给设计建议，区分「小改 API」与「新增编排层」。

---

## 1. 缺口诊断（证据 + 行号）

### 缺口 A：transcript 没有「存」对称函数 → agent 手搓序列化 + 手搓反序列化

`io_/source.py` 有 `load_transcript_json`（L43-71），但 `io_/sink.py` 只有 `write_text_file` / `write_json_file`，**没有 `save_transcript_json(transcript, path)`**。

证据 `scripts/tesla_stage02.py`：
- L22-43：agent **手搓** 从 JSON 重建 `Transcript`（逐字段构造 `Segment`/`Word`/`Transcript`），而不是调 `load_transcript_json`。
- L97-101：保存时用 `asdict(t)` + 原生 `json.dump`，而不是库提供的对称函数。

这说明：① 库的「读」没有被 agent 当成对称的标准入口（因为库没把「写」补齐，agent 把整条存/读视为 DIY）；② 任意想「跑完转录→存盘→之后再用」的工作流，都要 agent 自己写序列化。**这正是分阶段执行的最底层障碍**：没有标准中间产物格式 + 落盘 helper，stage 之间无法稳定断点。

### 缺口 B：三入口是「同步全链」单次函数，无分阶段 / checkpoint / resume

`pipeline.py`：
- `run_from_audio`（L83-96）：一次调用 stage 1→7。
- `run_from_transcript`（L57-71）：一次调用 stage 2→7。
- `_prepare_plans`（L154-189）把 align → proofread → heal_gaps → segment → cut 全部串在 **一个函数返回值里**，中间任何一步产物都不落盘、不可观测、不可重入。

证据 `scripts/tesla_stage02.py` 的整个存在意义：
- 这脚本只做 stage 1-3（转录 + 对齐 + 纠错），**故意不渲染**——因为 agent 想「先转录→看转录对不对→人工填 errata→再纠错→存盘→之后再切片渲染」。
- 由于 `run_from_audio` 一口气跑到渲染，agent 没法在「纠错」之后停下，所以只能 **拆开**：直接调 `stage_asr.transcribe` / `stage_align.align` / `stage_proofread.proofread`（tesla_stage02.py L46-95），自己拼前 3 个 stage。
- L12-20 的 `if os.path.exists(EXISTING)` 分支，就是 agent **手搓的 checkpoint-resume**：跑过就跳过 ASR+align，直接 load JSON 进纠错。

> 这是「逼 agent 拼脚本」的头号结构性原因：**生产现实需要「分阶段 + 停看纠续」，而管线只提供「一次性全链」**。

### 缺口 C：多源视频不是一等公民 → agent 手动分批 + 偏移时间戳

`PipelineOptions.source_media`（pipeline.py L52）是**单值** `str`。一次 `run_from_transcript` 只能指向一个源视频文件。

证据 `scripts/tesla_stage04.py`：
- L34-49：定义 BATCH1（t01-t13，落在 SRC1，0-850s 原始时间轴）。
- L51-62：定义 BATCH2_RAW（t14-t19，原始时间轴 >850s）。
- L63-67：**手算偏移** `c.start_s - SEG1_END` 把 BATCH2 时间戳搬到 SRC2 的本地时间轴。
- L83-104：调 `run_from_transcript` **两次**（opts1 用 SRC1，opts2 用 SRC2），各自带不同 `source_media`。

SKILL.md 已经把这套写进 [multi-source-video-rendering.md](references/multi-source-video-rendering.md)，承认它是「陷阱」级操作——但 **管线没给原语**，每个多源项目都得 agent 重写一遍「切批 + 偏移 + 双调用 + 合并结果」。多源场景在生产中是常态（一期录着录着换电池 / 双机位），把它留给 agent 拼脚本是缺口。

### 缺口 D：render_gate 只认内存 RenderResult，无法复审已落盘产物

`_render_plans`（pipeline.py L208-228）在渲染完后 **就地** 调 `gate_results(results)`，`results` 是内存对象。库**没有**「扫一个输出目录、对已渲染的 mp4+ass 复审」的入口。

证据 `scripts/tesla_gate.py`：
- L17-22：agent 用 `type("R", (), {...})()` **动态造一个假类**，伪造 `RenderResult` 的字段（`clip_id`/`horizontal_mp4`/`vertical_mp4`/`ass_path`/`srt_path`），只为能调 `gate_results(results)`。
- 这是典型的「库 API 形状不对，调用方用反射硬凑」的信号。

证据 `scripts/tesla_audit.py`：
- L1-54：**重新实现** 了 render_gate 的一部分（文件存在性、分辨率、codec、cues 计数），全部用 `subprocess.run(["ffprobe", ...])` 手搓。
- 这部分功能（机械规格校验）本来就在 `stage_render/render_gate.py` 里，但因为「只能对内存对象跑」，agent 复审已落盘产物时只能重写一遍。

> 缺口 D 的本质：**质量门绑死在渲染管线的尾巴上**，缺少「独立、可重入、对目录」的复审入口。生产里 gate 经常要在渲染完成几小时后、或 errata 修正后单独重跑，现在没有标准方式。

### 缺口 E：没有「项目运行」概念，errata / API key / cut_points 全靠调用方拼

`Engines`（pipeline.py L34-39）需要调用方注入 `transcriber/aligner/llm/style_resolver`；`PipelineOptions` 需要 `errata/proof/segment/render` 一堆子配置；LLM 还要 `DEEPSEEK_API_KEY`。

证据——以下 5-7 行 env 注入块在 **三个脚本里几乎逐字重复**：
- `tesla_stage02.py` L12-17
- `tesla_stage04.py` L9-15
- `tesla_refix.py` L6-12

证据——errata 是项目专属数据，却只能写死在脚本里：
- `tesla_stage02.py` L74-89：一整块 `ErrataConfig(flat={...})` + `ProofOptions(enable_llm=True, ...)` 写死在脚本中。

这些本应是 **项目级配置**（一个项目一份 errata、一份 cut_points、一份源文件映射），现在每个项目变成一份 `.py` 脚本。SKILL.md 的「投产标准流程」 L 里说「garden_core 纯 API 不依赖 project.yaml」——但代价就是把项目状态全部逼进临时脚本。

### 缺口 F：重渲 / 选择性重跑没有标准入口

`tesla_refix.py` 做的事其实标准 API **能做**（调 `run_from_transcript` 传子集 cut_points，见 L26-37），但：
- 因为没有 `skip_existing`（SKILL.md「重渲省时」段明确警告「ffmpeg_render 当前无 skip_existing，重跑会重渲全部」），agent 必须自己挑出要重跑的那几条。
- 没有「按 clip_id 重跑 + 自动复用上次 transcript」的一等入口，agent 还得自己 `load_transcript_json` + 重新构造 `PipelineOptions`。

SKILL.md 甚至专门留了一段「已渲片段别重跑，直接 `concat_videos`」的应急指引——这是**管线缺 checkpoint/skip 能力、靠 skill 文档打补丁**的典型表现。

---

## 2. 标准调用机制设计建议

按「改动成本 / 收益」分两层。第一层是 API 小补丁，能消掉大部分拼脚本动机；第二层是新增编排层，解决分阶段 + checkpoint 这个根问题。

### 第一层：小改 API（成本低，立刻见效）

#### A1. 补齐 transcript 存/读对称：`save_transcript_json`
在 `io_/sink.py` 加 `save_transcript_json(transcript, path)`（`dataclasses.asdict` + 已有 `write_json_file`）。配合现有 `load_transcript_json` 形成对称标准。
→ 直接消掉 `tesla_stage02.py` L22-43 的手搓反序列化 + L97-101 的手搓序列化。

#### A2. `Engines.from_env()` / 标准 env 注入 helper
把「从 `~/.env` 读 `DEEPSEEK_API_KEY` 并构造 `LLMClient`」封装成 `Engines.from_env(llm_default_model="deepseek-chat")` 或一个 `inject_garden_env()` 函数。
→ 消掉三处重复的 5-7 行 env 注入块（tesla_stage02/04/refix）。

#### A3. 质量门独立化：`render_gate.audit_dir(output_dir)`
让 `render_gate` 提供「扫目录、把 `{clip_id}_horizontal.mp4` + `.ass` 自动还原成 `RenderResult`、跑 gate、返回报告」的入口。
→ 直接消掉 `tesla_gate.py`（不用再造假类）和 `tesla_audit.py` 的大部分（ffprobe 那段本来就是 gate 的子集）。
→ 顺带让 gate 报告可序列化写盘（`gate_report.json`），方便 agent 事后读。

#### A4. `CutPoint.source_media` 字段 + 多源渲染内置
给 `CutPoint` 加可选 `source_media: str = ""` 和 `source_offset_s: float = 0.0`；`cut()` / `render()` 优先用 cutpoint 自带的源文件 + 偏移，`PipelineOptions.source_media` 退化为兜底默认值。
→ `tesla_stage04.py` 的 BATCH1/BATCH2 双调用（L83-104）合并成 **一次** `run_from_transcript`，19 条 cut_points 各自携带自己的源文件。消掉手算偏移（L63-67）。

#### A5. `RenderOptions.skip_existing=True` + 按 clip_id 跳过
渲染前检查 `output_dir/{clip_id}_horizontal.mp4` 是否存在且与当前 plan 一致（可先做朴素存在性跳过，后续加参数哈希）。
→ 消掉 SKILL.md 里「重渲省时」那段打补丁说明，也让 `tesla_refix.py` 退化成「传子集 cut_points」的标准调用。

#### A6. 显式「分步函数」命名并写入文档
把现在已经存在的 stage 函数（`transcribe`/`align`/`proofread`/`segment`/`cut`/`render`）在文档里 **正式命名为「step API」**，并保证每个 step 的输入输出都有 `save_*` / `load_*` 对（A1 是第一块拼图）。
→ 让 agent 知道「分阶段执行有官方姿势，不必拆 run_from_audio」。

> 第一层做完，5 个 tesla 脚本里 **4 个**（audit / gate / refix / stage04 的多源部分）会基本消失或退化为 2-3 行标准调用。

### 第二层：新增编排层（成本中等，解决根问题 B/E）

缺口 B（分阶段 + checkpoint-resume + 中间产物管理）和 E（项目状态散落）用小补丁解决不了，需要一个 **`ProjectRun` 编排对象**。这是让 agent 「完全不需要拼脚本」的关键。

#### B1. `ProjectRun`：项目级运行器，带 manifest + checkpoint-resume

形状建议（仅设计，不实现）：

```python
from garden_core.project import ProjectRun, ProjectConfig

# 项目配置（替代散落在脚本里的 errata/cuts/sources/env）
cfg = ProjectConfig.from_yaml("N:/<DATE> Tesla/project.yaml")
# 字段：sources (多源时间轴映射)、transcript_path、errata、proof_opts、
#       cut_points、style、render_opts、output_dir

run = ProjectRun(cfg, engines=Engines.from_env())

# 分阶段，每步自动落盘 + 写 manifest（stage 状态 + 产物路径 + 参数哈希）
run.transcribe()          # → transcript.json，manifest[transcribe]=done
run.proofread()            # errata 已在 cfg 里，读 transcript.json，覆盖写回
# agent / 人可在这里停 → 看 transcript → 改 project.yaml 的 errata → 再跑 proofread（幂等覆盖）
run.render()               # 多源、skip_existing、render_gate 全自动
run.audit()                # 质量门 + quality-audit skill 之外的机械复审

# resume： crashed 或人为中断后
run = ProjectRun.load(".../run_manifest.json")
run.resume()               # 跳过 manifest 里已 done 的 stage
```

关键设计点：
- **`run_manifest.json`** 是唯一状态源：每个 stage 跑完写一行 `{stage, status, artifact_path, params_hash, started/finished}`。agent 判断「跑到哪了」「要不要重跑」只读这个文件，不靠 `if os.path.exists(EXISTING)`（tesla_stage02.py L12）这种手搓检查。
- **幂等 + 覆盖**：同一 stage 重跑覆盖产物（transcript 是覆盖、render 是 skip_existing），让「纠错 → 重跑」成为一等流程，而不是 `tesla_refix.py` 那种「另写一个脚本只跑 t06/t09」。
- **多源时间轴进 `ProjectConfig.sources`**：把 tesla_stage04 的 SEG1_END/偏移逻辑沉到配置 + 编排层，cut_points 用原始时间轴，编排器负责翻译到每段源文件。

→ 这一层的存在，让 SKILL.md「投产标准流程」6 步 **每一步都对应 `run.xxx()` 一个调用**，agent 不再需要写 `.py`，只写/改 `project.yaml` + 调 `ProjectRun`。

#### B2. 标准 refix / 重跑入口：`run.rerender(clip_ids=...)` / `run.reproofread(errata=...)`

把 `tesla_refix.py` 这种「只重跑某几条」标准化：
- `run.reproofread(errata=...)`：更新 cfg.errata → 重跑 proofread → 覆盖 transcript.json。
- `run.rerender(clip_ids=["t06","t09"])`：从 manifest 拿 cut_points 子集 → 强制不 skip → 覆盖那几条。

#### B3. 让 SKILL.md 的「投产标准流程」用 `ProjectRun` 重写

现在 SKILL.md 教 agent 「直接 import 调用库 API」——但「直接调 stage 函数」恰恰催生了 tesla_stage02。SKILL.md 应改为：「建 `project.yaml` → `ProjectRun(cfg).transcribe()` → 审 → `run.render()`」。文档驱动 + API 双更新，agent 才会自然走标准路径。

---

## 3. 缺口 → 脚本 → 建议的对应表

| 缺口 | tesla 脚本里的证据（行号） | 建议 | 层 |
|---|---|---|---|
| A 无对称 save | stage02 L22-43, L97-101 | A1 `save_transcript_json` | 小 |
| B 无分阶段/checkpoint | stage02 整体（L12-20 手搓 resume） | **B1 `ProjectRun` + manifest** | 编排层 |
| C 多源非一等 | stage04 L34-67, L83-104 | A4 `CutPoint.source_media` + B1 配置层 | 小+编排 |
| D gate 只认内存 | gate L17-22（造假类）；audit L1-54（重写 ffprobe） | A3 `render_gate.audit_dir` | 小 |
| E 项目状态散落 | stage02 L74-89 errata；3 处 env 块 | A2 `Engines.from_env` + B1 `ProjectConfig` | 小+编排 |
| F 无选择性重跑 | refix 整体；SKILL「重渲省时」补丁段 | A5 `skip_existing` + B2 `run.rerender` | 小+编排 |

---

## 4. 优先级建议

1. **先做第一层（A1-A6）**：成本很低，能消掉 audit / gate / refix / 多源分批 这四类拼脚本动机，立刻让 agent 的「重跑某几条」「复审已落盘产物」「多源渲染」变成 2-3 行标准调用。
2. **再做 B1 `ProjectRun`**：这是根治「分阶段 + checkpoint + 项目状态」的编排层。做完后 SKILL.md「投产标准流程」每一步对应一个 `run.xxx()`，agent 真正不需要再写 `.py`。
3. **B2/B3 跟随 B1**：refix/rerender 入口 + SKILL.md 文档改写，闭环。

> 关键判据：当 `tesla_stage02.py`（最典型的「agent 自行编排前 3 个 stage + 手搓 checkpoint」）能被 `ProjectRun(cfg).transcribe_then_proofread()` + 一个 `project.yaml` 完全替代时，这套标准调用机制就算到位了。

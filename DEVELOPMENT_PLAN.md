# 项目管理 + 管线标准调用机制 · 开发计划

> 范围：基于 `PIPELINE_INVOCATION_REVIEW.md`（Ray 已认可）的两层设计 + **Ray 在评审中拍板的 6 个设计决策（D1-D6，全部已定）**，在原 plan 基础上更新。
> 核心升级（D1）：第二层从「ProjectConfig 数据形状 + ProjectRun 运行器」**扩展为完整项目管理系统**——把「项目」做成一等公民，从根上杜绝 agent 拼脚本 / 状态散落。
> 铁律：本文件是**计划**，不含代码实现。每个任务粒度 = 一次 RX 执行可独立完成 + 独立验收。
> 代码事实核对来源（已读真实代码，非凭摘要）：
> - `src/garden_core/pipeline.py` — `Engines`、`PipelineOptions`、`run_from_audio` / `run_from_transcript` / `run_montage`、`_prepare_plans`、`_render_plans`
> - `src/garden_core/types.py` — `Word`/`Segment`/`Transcript`/`Cue`/`CutPoint`/`ClipPlan`/`RenderResult`（全部 `frozen=True`）。**CutPoint 当前字段 = `clip_id/start_s/end_s/style_name(="default")/title(="")`，无 source_media。**
> - `src/garden_core/io_/source.py` — `load_transcript_json`、`_segment_from_dict`（已处理 words）
> - `src/garden_core/io_/sink.py` — 仅 `write_text_file` / `write_json_file` / `ensure_dir`（**无** save_transcript_json）
> - `src/garden_core/stage_cut/__init__.py` — `cut()`：用 `transcript.source_file` 作 `source_ref`，**不读 CutPoint 的源**
> - `src/garden_core/stage_render/__init__.py` — `RenderOptions`（普通类，**无** `skip_existing`）、`render()`
> - `src/garden_core/stage_render/ffmpeg_render.py` — `render_horizontal/vertical`，输出 `{clip_id}_{horizontal,vertical}.mp4`
> - `src/garden_core/stage_render/render_gate.py` — `gate_results` / `check_render_result` / `check_ass_pair` / `parse_ass` / `_vertical_ass_path`（**无** `audit_dir`，gate 现仅查 ASS 字体/安全区）
> - `src/garden_core/config.py` — **已有** `load_yaml` / `build_errata_config` / `ConfigError`（YAML 加载基础已就绪，T7-T10 直接复用）
> - `src/garden_core/infra/llm_client.py` — `LLMClient` / `NoLLMClient`
> - `scripts/tesla_stage02.py` / `tesla_stage04.py` / `tesla_refix.py` / `tesla_gate.py` / `tesla_audit.py`（tesla_audit.py 的 ffprobe 机械校验 = 存在性 + 3840×2160/1080×1920 + h264 + cue 计数）
> - `skills/hermes/references/project-directory-template.md`（项目目录模板：`source/` + `output/{clips,fullcut,release}` + `corrections.yaml` + `AGENTS.md` + `README.md`）

---

## 0. 任务总览（依赖序 + 优先级）

> **D1-D6 已全部拍板**（见末尾「决策点清单」）。第二层不再被任何决策阻塞。

```
第一层（小改 API，互相独立，可并行/任意序）
  T1  save_transcript_json          [P0] 无依赖
  T2  Engines.from_env()            [P0] 无依赖（D3：env_path 调用方传，不硬编码）
  T3  render_gate.audit_dir()       [P0] 无依赖（D4：合并 ffprobe 机械校验，目录复审；tesla_audit.py 整个消失）
  T4  CutPoint.source_media 必填     [P0] 无依赖（D2：breaking change + 迁移子项）
  T5  RenderOptions.skip_existing   [P1] 无依赖（D5：朴素文件存在性跳过）
  T6  step API 命名 + 文档化         [P2] 依赖 T1

第二层 · 项目管理系统（D1：YAML + 完整项目管理；串行）
  T7  project.yaml schema + ProjectConfig 数据形状 + 校验   [P1] 无依赖（D1 已定，不被阻塞）
  T8  create_project（建目录 + 生成 project.yaml + 默认配置/样式） [P1] 依赖 T7
  T9  load_project（project.yaml / 目录 → ProjectConfig）   [P1] 依赖 T7
  T10 项目修改 + 配置管理（CRUD + 重校验 + 持久化）          [P1] 依赖 T7, T9
  T11 ProjectRun + run_manifest.json（schema_version, D6）   [P1] 依赖 T1/T2/T3/T4/T5/T7/T9
  T12 run.rerender / run.reproofread（标准重跑入口）         [P2] 依赖 T11
  T13 SKILL.md「投产标准流程」改写（用项目管理 API）         [P2] 依赖 T11/T12
```

每个任务下面标注：**改什么 / 验收标准 / 自测方法 / 风险**。

---

## 第一层 · 小改 API

---

### T1 · `save_transcript_json` —— 补齐 transcript 存/读对称

**改什么**
- 文件：`src/garden_core/io_/sink.py`
- 新增 `save_transcript_json(transcript: Transcript, path: str | Path) -> str`。
- 实现：`dataclasses.asdict(transcript)` → `write_json_file(path, data)`。对称于 `io_/source.py::load_transcript_json`。
- 把 `save_transcript_json` 加入 `io_/sink.py` 的 `__all__`。
- （建议）保持 `from garden_core.io_.sink import save_transcript_json` 路径即可，与 `load_transcript_json` 的导入路径对称。

**关键事实核对**
- `load_transcript_json`（source.py）能容忍 `data` 是 dict 或 bare list，并能从 `asdict` 产生的嵌套结构还原 `Word`/`Segment`（见 `_segment_from_dict` 对 `words`/`word_timestamps` 的处理）。因此 `asdict` 输出可被 `load_transcript_json` 原样读回——**这是「对称」的可验证含义**。
- `Transcript` 是 `frozen=True`，`asdict` 可用。

**验收标准**
- `save_transcript_json(t, p)` 写出的 JSON，用 `load_transcript_json(p)` 读回，得到字段相等的 `Transcript`（segments 数、words 数、start/end/duration、corrections_applied 一致）。
- 文件存在则覆盖（幂等）。

**自测方法**
- 新增 `tests/test_io_roundtrip.py`：构造一个含 words + corrections_applied 的 `Transcript` → save → load → 逐字段断言相等。
- 回归：现有 `tests/test_io_source.py` 全绿（load 路径未动）。

**风险**：无破坏性。纯新增。

---

### T2 · `Engines.from_env()` —— 标准 env/API key 注入 helper（D3：env_path 调用方传）

**改什么**
- 文件：`src/garden_core/pipeline.py`（`Engines` dataclass 同文件）
- 给 `Engines` 加一个 `@classmethod from_env(...)`，封装三处脚本里逐字重复的块：
  - 读 `DEEPSEEK_API_KEY`（从 `.env` 或 `os.environ`）
  - 构造 `LLMClient(default_model=..., timeout=...)`
  - 返回 `Engines(llm=llm, transcriber=None, aligner=None, style_resolver=None)`
- **D3 决策（已定）**：`.env` 路径**默认由调用方传 `env_path`，不硬编码** `D:\Hermes\.env`。`env_path=None` 时仅读 `os.environ`；给路径则按脚本里「逐行 parse `.env`」merge 进 `os.environ`。
- **注意**：`transcriber`/`aligner` 是有状态重对象（GPU 模型），**不应**在 `from_env` 里默认构造。`from_env` 只负责「无状态/环境相关」的部分（LLM key）。transcriber/aligner 仍由调用方显式注入：`from_env(env_path=..., transcriber=..., aligner=...)` 透传。
- 参数：`from_env(*, llm_default_model="deepseek-chat", llm_timeout=300.0, env_path=None, transcriber=None, aligner=None, style_resolver=None)`。

**关键事实核对**
- 重复块出现在 `tesla_stage02.py` L12-17、`tesla_stage04.py` L9-15、`tesla_refix.py` L6-12，**三处逐字相同**（均硬编码 `r"D:\Hermes\.env"`）。
- `LLMClient` 构造签名见 `infra/llm_client.py`（`default_model`、`timeout`）。

**验收标准**
- `Engines.from_env(env_path=...)` 在 `DEEPSEEK_API_KEY` 存在时返回带可用 `llm` 的 Engines；缺失时降级为 `NoLLMClient`（不抛，让 LLM 层自己报 UNAVAILABLE——与现有「fixes legacy bug #7」哲学一致）。
- 三处脚本里的 env 注入块可被 `engines = Engines.from_env(env_path=r"D:\Hermes\.env")` 一行替代（**注意：env_path 仍由调用方显式传**，库不内置 Hermes 路径）。

**自测方法**
- 新增 `tests/test_engines_from_env.py`：mock `os.environ` / 写临时 `.env` → 断言 `engines.llm` 类型与 default_model；`env_path=None` 且无环境变量时降级 `NoLLMClient`。
- 回归：`tests/test_llm_client.py` 全绿（未改 LLMClient 本体）。

**风险**：无破坏性。纯新增 classmethod。**D3 已定，无悬念。**

---

### T3 · `render_gate.audit_dir()` —— 目录复审（D4：合并 ffprobe 机械校验）

**改什么**
- 文件：`src/garden_core/stage_render/render_gate.py`
- 新增 `audit_dir(output_dir, *, pattern="{clip_id}", expected_horizontal=(3840,2160), expected_vertical=(1080,1920), expected_codec="h264", render_horizontal=True, render_vertical=True, raise_on_fail=True) -> AuditReport`。
  - **范围（D4）= 现有 ASS gate + ffprobe 机械校验，统一成「目录复审」**：
    1. **文件存在性**：每条 clip 检查 `{cid}_horizontal.mp4` / `{cid}_vertical.mp4` / `{cid}.ass` / `{cid}_vertical.ass` 是否齐全（对齐 `tesla_audit.py` 第 1 段）。
    2. **ffprobe 机械规格**：对存在的 mp4 调 `ffprobe -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0`，比对 `expected_horizontal/vertical` 分辨率 + `expected_codec`（对齐 `tesla_audit.py` 第 2 段 ffprobe）。
    3. **ASS cue 计数**：对存在的 `.ass` 统计 `Dialogue:` 行数，0 条记 violation（对齐 `tesla_audit.py` 第 3 段）。
    4. **ASS 内容 gate**：复用现有 `check_ass_pair(clip_id, h_text, v_text)`（字体/安全区），逻辑不变。
  - 返回结构化 `AuditReport`：per-clip violations（分类：`missing_file` / `resolution` / `codec` / `zero_cues` / `ass_gate`）+ pass/block 汇总。可选 `raise_on_fail=True` 抛 `RenderGateError`。
  - `AuditReport.to_dict()` / `save(path)`：写 `audit_report.json`，供 agent 事后读。
  - **clip_id 发现规则**：从 `{*_horizontal.mp4, *_vertical.mp4, *.ass}` 文件名里提取（去 `_horizontal`/`_vertical` 后缀、去 `.ass` 扩展名），去重；`_vertical.ass` 不能被误当成独立 clip_id——复用现成 `_vertical_ass_path` 反推逻辑。
  - **ffprobe 缺失兜底**：若系统无 `ffprobe`，机械项标记为 `skipped`（不 BLOCK），但 ASS gate 仍执行——避免在无 ffprobe 环境里误伤。

**关键事实核对**
- `check_ass_pair(clip_id, horizontal_ass, vertical_ass)` 已是纯函数（不依赖 RenderResult）。
- `tesla_audit.py` 手搓 ffprobe 段（L19-46）：硬编码 3840×2160 / 1080×1920 / h264 + cue 计数——这些就是 `expected_*` 参数的默认值来源。
- `tesla_gate.py` 现在用 `type("R",(),{...})()` 造假类 + 引用不存在的 `GateOutcome`（脚本已坏）。
- **D4 决策（已定）**：`tesla_audit.py` 整个被 `audit_dir` 替代后**从 scripts/ 删除**（或留一份注释说明「已被 render_gate.audit_dir 取代」）。

**验收标准**
- 对一个已渲染的 output_dir 调 `audit_dir(d)`，结果覆盖 `tesla_audit.py` 的全部检查项：缺失文件/分辨率不符/codec 非 h264/0 cue/ASS gate 失配均被正确报为 violation。
- `audit_dir` 的 ASS gate 部分，与「对该目录对应的内存 RenderResult 列表调 `gate_results`」产生**完全一致**的 ASS 违规集合（复用 check_ass_pair）。
- `AuditReport` 可 `to_dict()` / 写 JSON。

**自测方法**
- 新增 `tests/test_render_gate_audit_dir.py`：在 tmp 目录写几对 `{cid}.ass` + `{cid}_vertical.ass`（含一个故意 font_ratio 失配的）+ 用 mock ffprobe 产物模拟分辨率/codec/cue 场景 → `audit_dir` → 断言：
  - 故意失配 clip 报 `ass_gate` violation；
  - 一个 0-cue ASS 报 `zero_cues`；
  - mock 一个分辨率不对的 mp4 报 `resolution`。
- 回归：`tests/test_render_gate.py` 全绿（现有 `gate_results`/`check_ass_pair` 未改）。

**风险**：无破坏性。纯新增。**D4 已定（范围扩大到目录复审）。** `tesla_audit.py` 删除是独立验收项。

---

### T4 · `CutPoint.source_media`（必填）+ `source_offset_s` —— 多源渲染一等公民（D2：breaking）

**改什么**
- 文件：`src/garden_core/types.py`（`CutPoint`）、`src/garden_core/stage_cut/__init__.py`（`cut()`）、`src/garden_core/pipeline.py`（`_prepare_plans`）、**所有现存 `CutPoint(...)` 构造点（scripts/tests）**
- **D2 决策（已定）**：`CutPoint.source_media` 改为**必填（无默认值）= breaking change**。
  - 新字段布局：`CutPoint(clip_id, source_media, start_s, end_s, *, style_name="default", title="", source_offset_s=0.0)`。
  - `source_offset_s: float = 0.0`（带默认值，非破坏，仅当多源偏移需要时填）。
- `cut()`：构造 `ClipPlan` 时 `source_ref` **强制用 `cp.source_media`**（不再回退 `transcript.source_file`——因为 source_media 必填，永远有值）。
- 时间偏移：`ClipPlan.start_s/end_s` = `cp.start_s - cp.source_offset_s` / `cp.end_s - cp.source_offset_s`（仅当 `source_offset_s != 0`）。**消除 `tesla_stage04.py` L63-67 手算偏移。**
- `pipeline._prepare_plans`：现有「`opts.source_media` 无条件覆盖所有 plan 的 source_ref」逻辑改为——**仅当 plan 没自带 source_media 时才用 `opts.source_media` 兜底**（多源场景下每条 cut 自带源，opts.source_media 仅作单源兜底）。

**迁移子项（breaking 必做）**
- **T4-migrate**：grep 全仓所有 `CutPoint(...)` 构造点（`scripts/*.py`、`tests/*.py`、SKILL.md / references 示例），逐处补 `source_media`：
  - 单源项目：`CutPoint("t01", "N:\\...\\src.mp4", 0, 10)` 形式（source_media 作为位置参 2）。
  - 多源项目（tesla）：BATCH1 填 SRC1、BATCH2 填 SRC2 + `source_offset_s=850.0`。
- 测试里的构造点同步更新；新增 `tests/test_cut_multisource.py` 用必填形式。

**关键事实核对**
- `cut()` 现状（stage_cut/__init__.py）：`source_ref=transcript.source_file`，忽略 CutPoint。
- `_prepare_plans` 现状（pipeline.py）：无条件 `replace(p, source_ref=opts.source_media)`。
- `CutPoint` 现字段（types.py L111-118）：`clip_id/start_s/end_s/style_name(="default")/title(="")`，无 source_media。
- `tesla_stage04.py` BATCH1/BATCH2 + 双调用的本质：19 条 cut_points 各自带源 + 偏移 → 一次 `run_from_transcript` 搞定。

**验收标准**
- 给 19 条 CutPoint 各自填 `source_media`（SRC1/SRC2）+ BATCH2 填 `source_offset_s=850.0`，**一次** `run_from_transcript` 产出与现有双调用等价的 19 条 RenderResult。
- **breaking 验证**：`CutPoint("x", 0, 10)`（旧式省略 source_media）**构造期即报 TypeError**——证明迁移完成、没有遗漏的旧式构造。
- 全仓无残留旧式 `CutPoint(` 构造（grep 为空）。

**自测方法**
- 新增 `tests/test_cut_multisource.py`：两条 CutPoint 各自带 `source_media`（SRC1/SRC2）+ 第二条带 `source_offset_s`，断言 `ClipPlan.source_ref` 与 start/end 偏移正确（不真渲染）。
- 新增 `tests/test_cut_source_required.py`：`pytest.raises(TypeError)` 验证缺 source_media 报错。
- 回归：更新后的 `tests/test_types.py` + cut 相关断言全绿；`run_from_transcript` 单源场景（opts.source_media 兜底）产物不变。

**风险**：⚠️ **breaking change（D2 已定）**。需迁移所有 `CutPoint(...)` 构造点。一次 RX 执行内必须完成「改字段 + 迁移所有构造点 + 更新测试」三件事，否则仓库进入不可运行状态。建议 RX 执行时先 grep 出全部构造点清单，逐个改完再合并。

---

### T5 · `RenderOptions.skip_existing` —— 选择性重跑（D5：朴素跳过）

**改什么**
- 文件：`src/garden_core/stage_render/__init__.py`（`RenderOptions`、`render()`）
- `RenderOptions.__init__` 增参 `skip_existing: bool = False`。
- `render()` 入口：若 `skip_existing` 且 `output_dir/{clip_id}_horizontal.mp4`（及 vertical，若启用）已存在 → 直接返回引用已存在文件的 `RenderResult`，跳过 ffmpeg。
- **D5 决策（已定）**：第一版做**朴素文件存在性跳过**（文件在就跳）。参数哈希（plan/style 哈希写进 manifest 比对）作为 T11 `run_manifest.json` 的能力，**不在 T5 做**。

**关键事实核对**
- `render()` 现状（stage_render/__init__.py）：无条件写 ass/srt + 调 ffmpeg_render。
- `tesla_refix.py` 存在的全部理由 = 没法跳过；SKILL.md「重渲省时」段是打补丁说明。

**验收标准**
- `skip_existing=True` 时，已存在的 clip 不触发 ffmpeg（可用 mock/计数验证），返回的 RenderResult 路径指向已存在文件。
- `skip_existing=False`（默认）行为与改动前完全一致。

**自测方法**
- 新增 `tests/test_render_skip_existing.py`：在 tmp output_dir 预放 `{cid}_horizontal.mp4` → `render(..., skip_existing=True)` → 断言未调 ffmpeg（mock `render_horizontal`）、返回路径命中预放文件。
- 回归：`tests/test_render.py` 全绿（默认 skip_existing=False）。

**风险**：无破坏性（默认 False）。**D5 已定。**

---

### T6 · step API 正式命名 + 文档化

**改什么**
- 文件：`src/garden_core/__init__.py`（或新建 `src/garden_core/steps.py`）、各 stage `__init__.py` 的 docstring
- 把现有 stage 函数正式命名为「step API」并在文档里列出每步的 `save_*/load_*` 对（T1 是首块拼图）：
  - step1 transcribe (`stage_asr.transcribe`) — 产物 `Transcript`
  - step2 align (`stage_align.align`) — 产物 `Transcript`
  - step3 proofread (`stage_proofread.proofread`) — 产物 `Transcript`
  - step4 segment (`stage_segment.segment`) — 产物 `tuple[Cue,...]`
  - step5 cut (`stage_cut.cut`) — 产物 `tuple[ClipPlan,...]`
  - step6 render (`stage_render.render`) — 产物 `RenderResult`
- 文档：每个 stage docstring 标注「step API 一部分，可单独调用 + 用 `save_transcript_json`/`load_transcript_json` 落盘」。
- **不新建函数**——命名 + 文档 + re-export。

**验收标准**
- `from garden_core import steps`（或等价）能拿到全部 6 个 step 函数引用；文档里有「step API 表」。

**自测方法**
- `python -c "from garden_core.steps import transcribe, align, proofread, segment, cut, render"` 不报错。
- 回归：全量 `tests/` 绿。

**风险**：无破坏性。纯文档/re-export。依赖 T1。

---

## 第二层 · 项目管理系统（D1：YAML + 完整项目管理）

> **D1 决策（已定）**：`ProjectConfig` 走 **YAML（`project.yaml`）**，且第二层扩展为**完整项目管理系统**——`create_project` / `load_project` / 项目修改 + 配置增删改查 + 校验，并与 `ProjectRun` / `run_manifest.json` 整合成闭环。
> 基础设施已就绪：`config.py` 的 `load_yaml` / `build_errata_config` / `ConfigError` 可直接复用；项目目录模板见 `skills/hermes/references/project-directory-template.md`（`source/` + `output/{clips,fullcut,release}` + `corrections.yaml` + `AGENTS.md` + `README.md`）。
> 这一层把「项目」做成一等公民：agent 不再拼脚本，而是 `create_project` → `load_project` → `ProjectRun.xxx()`。

---

### T7 · `project.yaml` schema 定义 + `ProjectConfig` 数据形状 + 校验

**改什么**
- 文件：新建 `src/garden_core/project/__init__.py`（或 `src/garden_core/project.py`，建议拆成子模块包：`schema.py` / `config.py`）
- **定义 `project.yaml` 文件格式**（注释完备的 schema 文档 + 一份示例 `project.example.yaml` 放 `references/`）：
  ```yaml
  project:
    name: tesla-<DATE>
    root: N:\<DATE> Tesla        # 项目根目录；相对路径都相对此解析
  sources:                          # 多源时间轴映射（沉淀 tesla_stage04 SEG1_END/偏移逻辑）
    - id: SRC1
      path: source/ep01.mp4
      timeline_start_s: 0
      timeline_end_s: 850
    - id: SRC2
      path: source/ep02.mp4
      timeline_start_s: 850         # 原始时间轴上的起点
      source_offset_s: 850          # 翻译到源本地时间的偏移
  transcript:                       # step1/2 产物 + 输入
    audio_path: source/ep01.wav
    path: output/transcript.json
  errata: corrections.yaml          # 复用 build_errata_config
  proof_opts:                       # ProofOptions 字段子集
    heal_gaps: true
  cut_points:                       # 原始时间轴（编排器负责翻译到每段源）
    - clip_id: t01
      source: SRC1                  # 引用 sources[].id（多源一等公民）
      start_s: 10.5
      end_s: 45.2
      style_name: fresh
      title: "开场"
  style:
    name: fresh                     # stage_style/styles/<name>.yaml
  render_opts:
    output_dir: output/clips
    horizontal_width: 3840
    horizontal_height: 2160
    vertical_width: 1080
    vertical_height: 1920
    crf: 18
    render_horizontal: true
    render_vertical: true
  output_dir: output               # 项目级默认输出根（clips/fullcut/release 的父）
  ```
- **`ProjectConfig` 数据类**（`@dataclass(frozen=True)`，与现有 types 风格一致）：
  - `ProjectMeta(name, root)`、`SourceSpec(id, path, timeline_start_s, timeline_end_s, source_offset_s=0.0)`、`CutPointSpec(clip_id, source_id, start_s, end_s, style_name="default", title="")`、`RenderOptsSpec(...)`、`ProofOptsSpec(...)`、`ProjectConfig(meta, sources, transcript, errata_path, proof_opts, cut_points, style_name, render_opts, output_dir)`。
  - `from_dict(d) -> ProjectConfig` / `to_dict() -> dict`（往返等价）。
  - `from_yaml(path) -> ProjectConfig`（复用 `config.load_yaml`）、`to_yaml(path)`。
- **`validate(cfg) -> None`（raise `ConfigError`）**：
  - sources 列表里 `id` 唯一；每个 cut_point 的 `source_id` 必须能在 sources 里找到。
  - `transcript.path` / `errata_path` / source `path`：相对路径相对 `meta.root` 解析；缺失时 `ConfigError`（或允许「尚未生成」，给出明确分类）。
  - `style_name` 对应的 `stage_style/styles/<name>.yaml` 存在；`render_opts` 字段合法（复用现有 RenderOptions 校验哲学）。
  - cut_points 时间轴在 sources 的 `[timeline_start_s, timeline_end_s]` 范围内（越界 `ConfigError`）。

**关键事实核对**
- `config.py` 已有 `load_yaml` / `ConfigError`，T7 直接 import 复用。
- `SourceSpec.source_offset_s` 与 T4 的 `CutPoint.source_offset_s` 同义——T11 翻译时透传。
- `cut_points[].source`（引用 source id）是 D1 多源一等公民的关键：原始时间轴写一次，编排器按 id 翻译到每段源（消除 tesla 双调用的根因）。

**验收标准**
- `ProjectConfig` 能表达 tesla 项目的全部状态（SRC1/SRC2 + 19 cut_points + errata + render opts）。
- `from_dict(cfg_dict)` 往返（to_dict → from_dict）等价。
- `validate()` 对合法 cfg pass；对「cut_point.source_id 不存在 / 时间轴越界 / style 文件缺失」分别抛 `ConfigError` 并带可定位信息。

**自测方法**
- 新增 `tests/test_project_config.py`：用 tesla 项目真实形状构造 dict → `from_dict` → 断言字段；to_dict→from_dict 往返等价。
- 新增 `tests/test_project_validate.py`：构造 4 类非法 cfg（坏 source_id / 越界 / 缺 style / 重复 source id）→ 断言 `ConfigError` + 信息含 clip_id/source_id。
- 回归：无（新模块）。

**风险**：无破坏性。新模块。**D1 已定，schema 形状不再有悬念。** 这是 T8-T11 的硬前置。

---

### T8 · `create_project` —— 项目初始化（建目录 + 生成 project.yaml + 默认配置/样式）

**改什么**
- 文件：`src/garden_core/project/create.py`
- 新增 `create_project(name, root_dir, *, sources, audio_path=None, style="fresh", render_opts=None, corrections=None, wiki=False, overwrite=False) -> ProjectConfig`：
  - **按模板建目录结构**（对齐 `project-directory-template.md`）：
    - `root_dir/source/`（仅建空目录，源素材用绝对路径引用，不拷贝——模板铁律）
    - `root_dir/output/clips/`、`root_dir/output/fullcut/release/`
    - `root_dir/corrections.yaml`（空勘误 `{}` 或传入的 corrections）
    - `root_dir/AGENTS.md`（从模板拷贝/生成最小版）
    - `root_dir/README.md`（含项目名 + 入口链接）
    - `root_dir/project.yaml`（**核心产物**）
    - 可选 `wiki=False`：花园式项目时建 `Wiki/<name>/` 子树（模板里的 A-M 目录）
  - **生成 `project.yaml`**：按 T7 schema 写默认配置——sources 来自参数、style 用传入（默认 fresh）、render_opts 用默认（4K horizontal / 1080×1920 vertical / crf 18）或传入、cut_points 留空 `[]`（投产时由人/AI 补）。
  - **默认样式**：把 `stage_style/styles/fresh.yaml` 复制到 `root_dir/styles/fresh.yaml`（或引用全局，二选一，文档说明）；若 style 名不存在则 `ConfigError`。
  - 返回 `ProjectConfig`（已 validate 过）；**create 即 validate**，创建后立即可被 load_project 读回。

**关键事实核对**
- 模板铁律：源视频不拷进项目（绝对路径引用），output 走本地 SSD。
- `stage_style/styles/fresh.yaml` 已存在（现有默认样式）。
- AGENTS.md 模板：参考 `garden-production` 的 garden 精神/权限/工作流模板（T13 再细化，T8 先放最小版）。

**验收标准**
- `create_project("demo", tmp_dir, sources=[SourceSpec(...)])` 后：目录结构完整、`project.yaml` 合法可被 `load_project` 读回且字段与传入一致、`corrections.yaml` 存在。
- `overwrite=False` 时，目标 `root_dir` 已存在且非空 → `ConfigError`（防覆盖已有项目）。
- `overwrite=True` 时允许重建（仍不删 source/）。
- `style="nonexistent"` → `ConfigError`。

**自测方法**
- 新增 `tests/test_create_project.py`：tmp 目录 → create → 断言目录树（source/、output/{clips,fullcut,release}、corrections.yaml、AGENTS.md、README.md、project.yaml）；`load_project(root_dir)` 读回等价。
- 回归：无（新模块，不碰现有 styles）。

**风险**：低。新模块。依赖 T7（schema/validate）。**这是 D1「创建项目」能力的落地。**

---

### T9 · `load_project` —— 从 project.yaml / 项目目录加载成 ProjectConfig

**改什么**
- 文件：`src/garden_core/project/load.py`
- 新增 `load_project(path) -> ProjectConfig`，`path` 既可是：
  - `project.yaml` 文件路径；
  - 项目根目录（自动找 `<root>/project.yaml`）。
- 加载流程：
  1. `load_yaml(project.yaml_path)` → dict。
  2. `ProjectConfig.from_dict(d)`（T7）。
  3. **相对路径解析**：所有相对路径（source.path / transcript.path / errata_path / output_dir）相对 `meta.root` 解析成绝对路径。
  4. **errata 合并**：`errata_path` 指向的 `corrections.yaml` 用 `config.build_errata_config` 合并成 `ErrataConfig`，挂到 cfg 的运行时视图（或由 ProjectRun 在用时取，二选一，文档说明）。
  5. `validate(cfg)` → 不合法抛 `ConfigError`。
- 可选 `load_project(path, *, strict=True)`：`strict=False` 时允许部分产物（transcript/audio）尚未存在（用于「创建后未运行」的项目），但 schema 类错误仍抛。

**关键事实核对**
- `config.build_errata_config` 已支持 `corrections.yaml` → `ErrataConfig`。
- 与 T8 的 `create_project` 闭环：create 写出的 project.yaml 必须能被 load 读回（T8 验收项之一）。

**验收标准**
- T8 创建的项目，`load_project(root_dir)` 读回的 `ProjectConfig` 与 create 时返回的字段一致（路径解析成绝对）。
- 传 `project.yaml` 文件路径与传根目录结果一致。
- 合法 tesla 形状的 project.yaml 能 load 成可用 cfg。

**自测方法**
- 新增 `tests/test_load_project.py`：create → load 等价；手写一份 tesla 形状的 project.yaml → load → 断言 sources/cut_points/render_opts 正确；非法 project.yaml（坏 source_id）→ `ConfigError`。
- 回归：无。

**风险**：低。依赖 T7。**这是 D1「加载项目」能力的落地。**

---

### T10 · 项目修改 + 配置管理（CRUD + 重校验 + 持久化）

**改什么**
- 文件：`src/garden_core/project/edit.py`
- 提供**配置增删改查 API**（返回新的 `ProjectConfig`，frozen 风格；落盘由 `save_project` 显式触发）：
  - `add_source(cfg, source: SourceSpec) -> ProjectConfig`
  - `remove_source(cfg, source_id: str) -> ProjectConfig`（连带移除引用该 source 的 cut_points？策略：默认禁止删除被引用的 source，`force=True` 才删 + 清 cut_points）
  - `add_cut_point(cfg, cp: CutPointSpec) -> ProjectConfig`
  - `update_cut_point(cfg, clip_id, **fields) -> ProjectConfig`
  - `remove_cut_point(cfg, clip_id) -> ProjectConfig`
  - `set_style(cfg, style_name) -> ProjectConfig`
  - `update_render_opts(cfg, **fields) -> ProjectConfig`
  - `update_proof_opts(cfg, **fields) -> ProjectConfig`
  - `set_errata(cfg, corrections_yaml_path) -> ProjectConfig`
- **每次修改后自动 `validate()`**：改完即校验，非法改动当场抛 `ConfigError`（如删 source 后仍有 cut_point 引用它、cut_point 越界）。
- `save_project(cfg, path=None)`：把 cfg `to_yaml` 写回 `project.yaml`（默认写回 `meta.root/project.yaml`）。
- 可选 `diff_projects(cfg_a, cfg_b) -> dict`：人/AI 审阅修改点（用于「修改前确认」）。

**关键事实核对**
- 这是 D1「修改项目 + 配置管理」的核心：errata 改、cut_points 增删、源增删都在这里，agent 不再手搓 yaml。
- `frozen=True` + 返回新实例，与 types.py 风格一致，避免共享可变状态（legacy bug #9 哲学）。

**验收标准**
- add/remove/update cut_point 后，`validate()` 立即反映（越界/引用坏 source → `ConfigError`）。
- 删除被 cut_point 引用的 source → 默认 `ConfigError`；`force=True` → 连带删 cut_points 并 pass validate。
- `save_project` 写出的 project.yaml 能被 `load_project` 读回等价。

**自测方法**
- 新增 `tests/test_project_edit.py`：对一份 tesla cfg 依次 add_source / add_cut_point（引用新 source）/ update_cut_point（越界 → `ConfigError`）/ remove_source（被引用 → `ConfigError`，force=True 通过）/ save → load 等价。
- 回归：无。

**风险**：低。依赖 T7（schema/validate）、T9（load，用于 save→load 往返测试）。**这是 D1「修改项目 + 配置增删改查 + 校验」的落地。**

---

### T11 · `ProjectRun` + `run_manifest.json`（schema_version, D6）—— 项目管理 → 运行编排闭环

**改什么**
- 文件：`src/garden_core/project/run.py`
- `ProjectRun(cfg: ProjectConfig, engines: Engines)`：持有 config + engines，提供分阶段方法（内部调用现有 `run_from_*` 入口，**不改它们**）：
  - `run.transcribe()` → 调 step1+step2（ASR+align），落 `transcript.path`（用 T1 `save_transcript_json`），写 manifest
  - `run.proofread()` → 读 transcript → step3（errata 来自 cfg）→ 覆盖写回，写 manifest
  - `run.render()` → 读 transcript → **多源翻译**：根据 `cfg.sources` 把原始时间轴 cut_points 翻译成「带 `source_media`（T4 必填）+ `source_offset_s` 的 `CutPoint` 列表」→ 一次调 `run_from_transcript`（T5 skip_existing + T4 多源）→ 写 manifest
  - `run.audit()` → T3 `audit_dir(cfg.render_opts.output_dir)` → 写 `audit_report.json`
  - `run.resume()` → 读 manifest，跳过已 done 的 stage
  - `run.all()` → transcribe→proofread→render→audit 串行（便利方法）
- **`run_manifest.json`（D6：带 `schema_version`）**：
  - 顶层：`{"schema_version": 1, "project": {...meta...}, "stages": [...]}`
  - 每 stage 一行：`{stage, status, artifact_path, params_hash, started, finished}`。
  - `schema_version` 字段冻结为 `1`；未来格式变更时迁移器按版本号路由（D6 落地）。
  - **agent 判断「跑到哪」只读 manifest**，不再 `if os.path.exists(...)`（tesla_stage02 L12 手搓 resume 消失）。
- **幂等覆盖**：同 stage 重跑覆盖产物（transcript 覆盖、render 用 skip_existing），让「纠错→重跑」成一等流程。
- **多源翻译细节**（用 T4 字段）：遍历 `cfg.cut_points`，按 `cut_point.source_id` 找到 `SourceSpec`，生成 `CutPoint(clip_id, source_media=<spec.path 绝对>, start_s=cp.start_s, end_s=cp.end_s, source_offset_s=<spec.source_offset_s>, style_name=..., title=...)`。这就是 tesla 双调用退化为一次 `run.render()` 的机制。

**依赖**：T1（save transcript）、T2（engines from env）、T3（audit）、T4（多源必填字段）、T5（skip_existing）、T7（ProjectConfig schema）、T9（load_project，用于 `ProjectRun.from_project_dir(dir)` 便利构造）。

**验收标准**
- `tesla_stage02.py` 全部行为（ASR+align+proofread + 手搓 checkpoint）能被 `ProjectRun(load_project(dir), Engines.from_env(env_path=...)).transcribe(); run.proofread()` 完全替代。
- `tesla_stage04.py` 的双调用多源渲染能被 `run.render()` 一次调用替代。
- 人为中断后 `ProjectRun.load(manifest).resume()` 跳过已完成 stage。
- manifest 含 `schema_version: 1`；load 时校验版本号，不匹配给出明确报错（D6 落地）。

**自测方法**
- 新增 `tests/test_project_run.py`：
  - happy path：transcribe→proofread→render→audit 全跑（mock engines/ffmpeg），manifest 每步 done，产物落盘。
  - resume：跑完 transcribe 后构造新 run → resume → 断言 transcribe 跳过、proofread 执行。
  - 多源：cfg.sources 两条（含 source_offset_s）→ render 后断言每条 clip 指向正确源文件 + 偏移正确。
  - schema_version：手改 manifest 的 `schema_version=999` → load 报明确错。
- 回归：`run_from_audio` / `run_from_transcript` / `run_montage` 三入口行为不变（ProjectRun 内部调用它们，不改）。

**风险**：中等。新层，不动现有入口 → 对现有调用方零破坏。**D6 已定（schema_version=1）。**

---

### T12 · `run.rerender(clip_ids=)` / `run.reproofread(errata=)` —— 标准重跑入口

**改什么**
- 文件：`src/garden_core/project/run.py`（同 T11）
- `run.reproofread(errata=...)`：更新 cfg.errata（用 T10 的 `set_errata` 或直接传 `ErrataConfig`）→ 重跑 proofread → 覆盖 transcript → 更新 manifest。
- `run.rerender(clip_ids=["t06","t09"])`：从 cfg.cut_points 取子集 → **强制不 skip**（临时关 `skip_existing`，或 manifest 标记这些 clip 为 stale）→ 覆盖那几条 → 更新 manifest。

**验收标准**
- `tesla_refix.py`（重渲 t06/t09）退化为 `run.rerender(clip_ids=["t06","t09"])` 一行。
- errata 修正后 `run.reproofread(errata=new_errata)` 覆盖 transcript 并可立即 `run.rerender(...)`。

**自测方法**
- 新增 `tests/test_project_rerun.py`：rerender 子集 → 断言仅指定 clip 重新 ffmpeg（mock）、其余不动；reproofread 换 errata → transcript 覆盖。
- 回归：T11 测试全绿。

**风险**：低。建立在 T11。

---

### T13 · `SKILL.md`「投产标准流程」改写（用项目管理 API）

**改什么**
- 文件：`skills/hermes/SKILL.md`（及其 references/）
- 把「投产标准流程」改写为项目管理 API 驱动（D1 闭环）：
  1. `create_project(...)` 建项目（或 `load_project(dir)` 打开已有）
  2. `ProjectRun(cfg, Engines.from_env(env_path=...)).transcribe()`
  3. 人审 transcript → 改 `corrections.yaml` 或 `run.reproofread(errata=...)`
  4. `run.proofread()`
  5. `run.render()`
  6. `run.audit()`
- 重跑：`run.rerender(clip_ids=[...])` / `run.reproofread(errata=...)`。
- 删除/降级现有「重渲省时」「多源陷阱」「直接 import 调 stage 函数拼脚本」等打补丁段落（根因已被 T4/T5/T7-T12 消除）。
- 更新 `references/project-directory-template.md` 的「项目配置层」段：从「garden_core 不依赖 project.yaml」改写为「**project.yaml 是一等配置**（D1）」，三处分散配置合并到 project.yaml + corrections.yaml + style yaml。
- 文档驱动 + API 双更新（review 第 2 节 B3）。

**依赖**：T11/T12 落地后才能如实改写。

**验收标准**
- SKILL.md 流程里**不再出现**「直接 import 调 stage 函数拼脚本」的指引；每步是 `create_project/load_project + run.xxx()`。
- `references/project-directory-template.md` 与 D1 一致（project.yaml 一等公民）。

**自测方法**
- 人工 review：照新 SKILL.md 走一遍 tesla 项目，不写任何 `.py` 即可完成全链。
- 回归：无代码改动，纯文档。

**风险**：低。但需与 T11/T12 同步发布，否则文档与 API 错位。

---

## 决策点清单（D1-D6 全部已定 ✅）

| # | 决策点 | Ray 决策 | 影响 / 落地任务 |
|---|---|---|---|
| **D1** ✅ | `ProjectConfig` 走 YAML 还是纯 Python？ | **YAML（`project.yaml`）+ 完整项目管理系统**（create/load/modify + CRUD + 校验） | T7 schema、T8 create、T9 load、T10 edit、T11 run 闭环。第二层不再被阻塞。把「项目」做成一等公民，杜绝 agent 拼脚本。 |
| **D2** ✅ | `CutPoint.source_media` 必填还是可选？ | **必填（breaking change）** | T4 改必填 + 迁移子项（全仓 grep `CutPoint(` 逐处补 source_media）。`source_offset_s` 仍带默认 0.0。 |
| **D3** ✅ | `Engines.from_env` 的 `.env` 路径约定？ | **默认由调用方传 `env_path`，库不硬编码** | T2 实现：`env_path=None` 读 `os.environ`；给路径 merge。 |
| **D4** ✅ | `audit_dir` 是否合并 ffprobe 机械校验？ | **合并（目录复审）** | T3 范围扩大：存在性/分辨率/codec/cue 计数 + ASS gate 统一 `audit_dir`；`tesla_audit.py` 整个删除。 |
| **D5** ✅ | `skip_existing` 第一版策略？ | **朴素文件存在性跳过** | T5 做朴素跳过；参数哈希留 T11 manifest。 |
| **D6** ✅ | `run_manifest.json` 是否带 schema 版本号？ | **带 `schema_version` 字段（=1）** | T11 manifest 顶层带 `schema_version`，load 时校验，未来按版本号迁移。 |

> D1-D6 全部已定，**无悬而未决的阻塞项**。可立即按依赖序开第一层 + 第二层。

---

## 自测 / 回归计划

### 全局回归基线（每个任务合并前都要跑）
1. `pytest tests/` 全绿。
2. 三入口冒烟（用现有 `tests/smoke_*` 里最小的一个）：
   - `run_from_audio`：audio → 渲染产物，行为不变。
   - `run_from_transcript`：transcript → 渲染产物，行为不变。
   - `run_montage`：transcript + cut_points → 单段拼接 mp4，行为不变。
3. 关键不变量（pipeline 已有 `_flatten_overlaps` 等防御逻辑）：
   - 字幕 cue 无重叠（`has_overlaps` 不触发）。
   - 渲染门 `gate_results` 对合格产物 pass、对故意失配 font_ratio 的 BLOCK。

### 每个任务的专项自测（见各任务「自测方法」）
- **T1**：transcript round-trip（save→load 字段相等）。
- **T2**：env 注入单元测试（mock env；env_path 调用方传）。
- **T3**：audit_dir 覆盖 tesla_audit 全部项（存在性/分辨率/codec/cue + ASS gate 等价）+ 报告序列化。
- **T4**：多源 cut 单测（断言 ClipPlan.source_ref + 偏移）+ 单源回归不变 + **缺 source_media 报 TypeError**（breaking 验证）+ 全仓无残留旧式构造。
- **T5**：skip_existing 单测（mock ffmpeg，断言未调用）+ 默认 False 回归。
- **T6**：import 可达性 + 文档存在性。
- **T7**：ProjectConfig 往返 + validate 4 类非法场景。
- **T8**：create_project 目录树完整 + load 读回等价 + overwrite/坏 style 报错。
- **T9**：load_project（文件路径 vs 根目录一致）+ tesla 形状 load + 非法报错。
- **T10**：CRUD（add/remove/update cut_point、remove source force）+ 改完即 validate + save→load 往返。
- **T11**：ProjectRun happy path + resume + 多源 + schema_version 校验。
- **T12**：rerender 子集 + reproofread 覆盖。
- **T13**：人工照新文档走 tesla 全链不写脚本。

### 端到端验收（第二层完成后）
- **判据**（D1 闭环）：5 个 tesla 脚本的退化目标：
  - `tesla_gate.py` → `run.audit()` 一行（T3，D4）
  - `tesla_audit.py` → **删除**（T3 合并 ffprobe 后整文件消失，D4）
  - `tesla_refix.py` → `run.rerender(clip_ids=[...])` 一行（T12）
  - `tesla_stage04.py` → `run.render()` 一次调用（T4 + T11，多源翻译）
  - `tesla_stage02.py` → `run.transcribe()` + `run.proofread()`（T11）
- **新项目零脚本**：`create_project(...)` → `ProjectRun(...).all()` 全链不写任何 `.py`。

---

## 风险 / 兼容性总览

| 任务 | 破坏性 | 兼容策略 |
|---|---|---|
| T1 save_transcript_json | 无 | 纯新增 |
| T2 Engines.from_env | 无 | 纯新增 classmethod |
| T3 audit_dir | 无 | 纯新增；现有 gate_results/check_ass_pair 不动；`tesla_audit.py` 删除是独立验收项 |
| T4 CutPoint 字段 | ⚠️ **breaking（D2）** | `source_media` 必填 → 迁移全仓所有 `CutPoint(...)` 构造点；`source_offset_s` 带默认值 |
| T5 skip_existing | 无 | 默认 False |
| T6 step API 文档 | 无 | 纯文档/re-export |
| T7 project.yaml schema + ProjectConfig | 无 | 新模块 |
| T8 create_project | 无 | 新模块；不碰现有 styles |
| T9 load_project | 无 | 新模块 |
| T10 project edit/CRUD | 无 | 新模块；frozen + 返回新实例 |
| T11 ProjectRun + manifest | 无（对现有入口） | 新层，内部调用现有入口，不改它们；manifest 带 schema_version |
| T12 rerender/reproofread | 无 | 建立在 T11 |
| T13 SKILL.md | 无（代码） | 文档；需与 T11/T12 同步 |

**唯一 breaking change**：T4 的 `CutPoint.source_media` 必填（D2 已定接受）。必须在一次 RX 执行内完成「改字段 + 迁移全仓构造点 + 更新测试」，否则仓库不可运行。

---

## 实施顺序建议（给 Reasonix）

> D1-D6 全部已定，**无阻塞**，可立即开工。

1. **第一层并行批次**（互不依赖）：T1、T2、T3、T4、T5 可同时开；T6 等 T1。
   - ⚠️ T4 是 breaking，建议**单独一批**并在合并后立即跑全量回归 + tesla 脚本冒烟，确认迁移无遗漏。
2. **第二层串行**（D1 项目管理系统）：
   - T7（schema + ProjectConfig + validate）→ 是 T8/T9/T10/T11 的硬前置。
   - T8（create）、T9（load）可在 T7 后并行。
   - T10（edit/CRUD）依赖 T7、T9。
   - T11（ProjectRun + manifest）依赖 T1/T2/T3/T4/T5/T7/T9。
   - T12（rerender/reproofread）依赖 T11。
   - T13（SKILL.md）依赖 T11/T12。
3. 每个任务一次 RX 执行 + 一次验收，不揉合。

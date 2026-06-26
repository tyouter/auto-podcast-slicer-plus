# RX Brief · T11 — `ProjectRun` + `run_manifest.json`（schema_version, D6）

> **一句话**：新建 `src/garden_core/project/run.py`，实现运行时编排器 `ProjectRun(cfg: ProjectConfig, engines: Engines)`——持有 config + engines，提供分阶段方法 `transcribe() / proofread() / render() / audit()`，串行便利 `all()`，断点续跑 `resume()`，把每步产物路径 + status + 时间戳写进 `<root>/run_manifest.json`（顶层带 `schema_version: 1`，D6）。核心机制是**多源翻译**：`cfg.cut_points`（`CutPointSpec`：全局时间轴 + `source` id）→ `types.CutPoint`（`source_media` 绝对路径 + `source_offset_s`），从而把 `tesla_stage04` 的双 batch 手搓渲染退化成一次 `run.render()`。**内部复用现有三入口与 step 函数，不改它们**；纯新模块。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第二层 · 项目管理系统」→ **T11 · `ProjectRun` + `run_manifest.json`（schema_version, D6）**（D1 闭环 + D6 schema_version=1；依赖 T1/T2/T3/T4/T5/T7/T9）。`IMPLEMENTATION_PLAN.md` L29/L85（T11 风险：汇聚层，硬约束「不改 run_from_*/run_montage」，核心核多源翻译 + resume）。

---

## ⚠️ 执行前必读：Meta-Brief / Plan 与 T1-T9 已落地代码的出入

Meta-Brief 给的方法名是 `transcribe / proofread / segment / cut_and_render`；Plan T11 原文给的是 `transcribe / proofread / render / audit / resume / all`。对照已落地的 `pipeline.py`（三入口真实签名）+ `steps.py`（step 函数）+ `io_/sink.py`（T1）+ `render_gate.py`（T3 audit），有六处必须澄清。**默认按「Plan + 卡帕西 Simplicity First」走**：

### 出入 1：Meta-Brief 的 `segment` / `cut_and_render` vs Plan 的 `render` —— 默认收敛为 `render()`

- Meta-Brief 列 `transcribe / proofread / segment / cut_and_render` 四个阶段。Plan 列 `transcribe / proofread / render / audit (+resume/all)`。
- 现实代码里，**segment + cut + render 在 `run_from_transcript` 内部是原子的一串**（`_prepare_plans` 做 align→proofread→segment→cut，`_render_plans` 做 style→render）。`segment`（stage 4）产出的是内存里的 `tuple[Cue]`，**当前没有任何持久化约定**（T1 的 `save_transcript_json` 只存 Transcript，cue 不单独落盘）。单独暴露 `run.segment()` 会产生一个没有 artifact、manifest 无法记录的幽灵阶段，且需要把 segment 从 `run_from_transcript` 里拆出来调用 —— 违反「不改现有入口」。
- **结论**：默认**只做 `render()`**（= segment + cut + render，内部一次调 `run_from_transcript`）。Meta-Brief 的 `segment`/`cut_and_render` 收敛进 `render()`。`audit` 单独成阶段（有 `audit_report.json` artifact，T3 `audit_dir` 已落地）。见 Q1。

### 出入 2：`transcribe()` 不能调 `run_from_audio`（它跑全链 1-7）—— 直接调 step1 + step2 + T1 save

- `run_from_audio` 的实现是 `transcribe(...) → run_from_transcript(...)`，即 stage 1 之后**直接串到 stage 2-7**（align + proofread + segment + cut + render）。它不是「只做 ASR」。
- Plan T11 原文写得很清楚：`transcribe()` → 「调 step1+step2（ASR+align），落 transcript.path（用 T1 `save_transcript_json`）」。所以 `transcribe()` **不复用 `run_from_audio`**，而是直接调 `stage_asr.transcribe`（step1）→ `stage_align.align`（step2）→ `io_.sink.save_transcript_json(transcript, cfg.transcript.path)`。这一步**不碰** proofread/render。
- `engines.transcriber` 为 None → `transcribe()` 抛 `RuntimeError`（明确信息「transcribe() 需要 engines.transcriber」）。`engines.aligner` 为 None → 跳过 step2（对齐），只做 ASR（与 `run_from_transcript` 对齐缺失的容忍语义一致，日志 warning）。见 Q2。

### 出入 3：`render()` 调 `run_from_transcript` 会**重复 align + 重复 proofread** —— 默认在 render 时关掉这俩

- `run_from_transcript` → `_prepare_plans` 里会：① `if engines.aligner: align(...)`（stage 2 再跑一遍）② `proofread(...)`（stage 3 再跑一遍，用 `opts.errata`）。
- 但在 T11 的阶段模型里，`transcribe()` 已经 align 过、`proofread()` 已经纠错过并覆盖写回 `transcript.json`。`render()` 加载的是**已对齐 + 已纠错**的 transcript。让 `run_from_transcript` 再 align + 再 proofread 一次是**重复劳动**，且重复 errata 可能叠加副作用。
- **结论**：`render()` 内部构造一个**render 专用配置**喂给 `run_from_transcript`：
  - `engines_render = dataclasses.replace(self.engines, aligner=None, llm=NoLLMClient())`（关掉对齐重跑；关掉 LLM，因 proofread 内部若 enable_llm 且有 key 会再调一次）。
  - `opts.proof = ProofOptions(全 False)` + `opts.errata = ErrataConfig.empty()`（让 `_prepare_plans` 里的 stage3 proofread 变 no-op，不二次纠错）。
  - `opts.source_media = ""`（多源模式下每条 CutPoint 自带 `source_media`，`cut()` 会用它；`opts.source_media` 留空避免覆盖，见 `pipeline._prepare_plans` 的「`if opts.source_media:` 仅在 plan.source_ref 为空时兜底」语义）。
  - 其余 opts：`opts.render`（由 `cfg.render_opts` 翻译成 `RenderOptions`）、`opts.skip_existing = True`（复用 T5）、`opts.render_gate = True`（render 阶段自带 gate；audit 阶段额外做 dir 级 audit）。
- 这样 `render()` = 「加载已纠错 transcript → 多源翻译 → segment+cut+render（无 align/proof 副作用）」。**前提**：调用方应先 `transcribe()` 再 `proofread()` 再 `render()`（`all()` 强制此序）；若直接 `render()` 而 transcript.json 未就位/未纠错，render 会「按现状加载」但**不**做 errata 纠错（那是 `proofread()` 的职责）。见 Q3。

### 出入 4：多源翻译的 `style_name` 处理 —— 默认项目级单一 style

- `run_from_transcript(transcript, cut_points, style_name, ...)` 的 `style_name` 是**单一标量**，`_render_plans` → `_resolve_style_for` 用 `style_name or plan.style_name`（传入的 style_name 优先于 plan 自带）。即「传一个 style 给全部 clip」。
- `CutPointSpec` 带每条 clip 的 `style_name`（默认 `"default"`），理论上支持每条 clip 不同样式。但当前 `run_from_transcript` 不支持 per-clip style（一次调用一个 style）。要支持需「按 style_name 分组 → 多次调 run_from_transcript → 重组结果」，是额外复杂度。
- 对照 `tesla_stage04`：19 条 clip 全用 `"fresh"`，单 style 调用一次。这是现实主用例。
- **结论**：默认 `render()` 把 `cfg.style_name` 作为单一 style 传给 `run_from_transcript`；`CutPointSpec.style_name` 在翻译时**透传进 `types.CutPoint.style_name`**（保信息，`_resolve_style_for` 在 style_name 传入非空时用传入的，所以实际渲染统一用 cfg.style_name）。per-clip style 分组渲染 **defer**（如未来真有「一项目多 style」需求，另开任务加 `render()` 内分组逻辑）。见 Q4。

### 出入 5：`proofread()` 的 errata 从哪来 —— `build_errata_config(cfg.errata_path)`

- T9 brief Q1 已定：**T9 不合并 errata**，`ErrataConfig` 构造留给 T11 ProjectRun 在用时调 `config.build_errata_config(resolved_errata_path)`。
- `cfg`（经 `load_project` 或 `ProjectConfig` 直接构造）的 `errata_path` 是**绝对路径**（若 cfg 来自 `load_project`）或**相对路径**（若 cfg 来自 `from_dict` 原样）。`ProjectRun` 不假设哪种——在 `proofread()` 里用 `Path(cfg.errata_path)`：绝对则直用，相对则相对 `cfg.meta.root` 解析（与 T9 `_resolve` 同口径，内联 ~3 行，不 import T9 私有）。
- `build_errata_config` 对缺失文件返回 `ErrataConfig.empty()`（T9/config.py 已实现），不抛错。
- `proofread()` 流程：`load_transcript_json(cfg.transcript.path)` → `stage_proofread.proofread(t, errata, engines.llm, ProofOptions(...from cfg.proof_opts...), audio_path=cfg.transcript.audio_path)` → `save_transcript_json(t, cfg.transcript.path)`（**覆盖写回**，幂等）。见 Q5。

### 出入 6：manifest 落在哪 + `resume()` / `load()` 形状

- Meta-Brief 没指定 manifest 路径；Plan 说「agent 判断跑到哪只读 manifest」。
- **结论**：manifest = **`<cfg.meta.root>/run_manifest.json`**（项目根，与 `project.yaml` 同级，运行元数据归属项目而非 output 子目录）。原子写（tmp + `os.replace`，同 T10 Q5 口径）。
- `resume()` 是**实例方法**：读自身 manifest（路径来自 `self._manifest_path`），对每个 stage 看 status==`done` 且 artifact_path 存在 → 跳过；否则执行。`resume()` 内部按 `transcribe → proofread → render → audit` 序循环。
- `ProjectRun.load(manifest_path, engines)` 是**classmethod**：读 manifest → 校验 `schema_version==1`（D6，不符抛 `ConfigError` 明确信息）→ 从 manifest 的 `project.root` 调 `load_project(root, strict=False)` 重建 cfg → 返回 `ProjectRun(cfg, engines)`（已记下 manifest_path）。随后调用方可 `.resume()`。见 Q6。
- `all()` = 串行 `transcribe → proofread → render → audit`（不读 manifest 跳过，强制全跑；幂等因各步覆盖写）。见 Q7。

> 若人审对以上六处（+ Q1-Q7）有异议，开工前拍板；否则按上述默认走。

---

## 核心目标

### 1. 新建 `src/garden_core/project/run.py`

```
src/garden_core/project/
├── __init__.py      # T7-T10 已存在 —— T11 追加 re-export ProjectRun
├── schema.py        # T7，不动
├── config.py        # T7，不动
├── create.py        # T8，不动
├── load.py          # T9，不动
├── edit.py          # T10，不动
└── run.py           # ★ T11 新增
```

- `run.py` 只 import 已落地公开符号：`ProjectConfig`（T7）、`load_project`（T9）、`build_errata_config` / `ConfigError`（config.py）、`Engines` / `run_from_transcript` / `PipelineOptions`（pipeline.py）、`Transcriber`/`AudioRef`/`transcribe`（stage_asr）、`align`（stage_align）、`proofread` / `ProofOptions` / `ErrataConfig`（stage_proofread）、`RenderOptions`（stage_render）、`audit_dir` / `AuditReport`（render_gate，T3）、`save_transcript_json` / `load_transcript_json`（io_）、`CutPoint`（types）。**不重复定义类型**、不改三入口实现、不 import 私有。
- `project/__init__.py` 的 `__all__` 追加 `"ProjectRun"`，并 `from garden_core.project.run import ProjectRun`。

### 2. `ProjectRun` 签名（按 Meta-Brief + Plan）

```python
@dataclass(frozen=True)
class ProjectRun:
    cfg: ProjectConfig
    engines: Engines

    # —— 便利构造 ——
    @classmethod
    def from_project_dir(cls, dir: str | Path, engines: Engines, *, strict: bool = False) -> "ProjectRun": ...

    # —— 分阶段 ——
    def transcribe(self) -> "StageResult": ...
    def proofread(self) -> "StageResult": ...
    def render(self) -> "StageResult": ...
    def audit(self) -> "StageResult": ...

    # —— 编排 ——
    def all(self) -> list["StageResult"]: ...
    def resume(self) -> list["StageResult"]: ...

    # —— manifest I/O ——
    @classmethod
    def load(cls, manifest_path: str | Path, engines: Engines) -> "ProjectRun": ...
    def manifest_path(self) -> Path: ...   # <cfg.meta.root>/run_manifest.json
    def read_manifest(self) -> dict: ...    # 不存在 → {}
    def _write_manifest(self, stages: list[dict]) -> None: ...  # 原子写
    def _record(self, stage: str, status: str, artifact: str, params: dict) -> None: ...
```

- `ProjectRun` frozen（frozen dataclass）；不持有可变运行态，manifest 始终落盘读盘（状态在磁盘不在内存，断点续跑才可靠）。
- `StageResult` 是 run.py 内定义的轻量返回值（frozen dataclass：`stage: str, status: str, artifact_path: str, skipped: bool`），让调用方能 `for r in run.all(): print(r)`。纯便利，**不进 `__all__` 顶层**（run.py 内部用，可 export 但非必须）。
- `manifest_path()` = `Path(cfg.meta.root) / "run_manifest.json"`。

### 3. 各阶段实现（内部调 step / 现有入口，不改它们）

**`transcribe()`**（step1 ASR + step2 align + T1 save）
```
1. if engines.transcriber is None → raise RuntimeError("transcribe() requires engines.transcriber")
2. audio = AudioRef(path=cfg.transcript.audio_path)
3. t = stage_asr.transcribe(audio, engines.transcriber, hotwords=())   # hotwords 暂不进 cfg（T7 无字段），留 ()
4. if engines.aligner: t = stage_align.align(t, engines.aligner, cfg.transcript.audio_path)
   else: log.warning("transcribe(): no aligner — skipping stage 2")
5. save_transcript_json(t, cfg.transcript.path)
6. _record("transcribe", "done", cfg.transcript.path, {"engine": engines.transcriber.__class__.__name__})
7. return StageResult("transcribe", "done", cfg.transcript.path, False)
```

**`proofread()`**（load → step3 proofread（errata from cfg）→ 覆盖写回）
```
1. t = load_transcript_json(cfg.transcript.path)   # 不存在 → 抛（proofread 前置 transcribe）
2. errata = build_errata_config(_resolve_errata_path())   # build_errata_config 对缺失返回 empty
3. opts = ProofOptions(**dataclasses.asdict(cfg.proof_opts))
4. t2 = stage_proofread.proofread(t, errata=errata, llm=engines.llm, opts=opts, audio_path=cfg.transcript.audio_path)
5. save_transcript_json(t2, cfg.transcript.path)   # 覆盖
6. _record("proofread", "done", cfg.transcript.path, {"corrections": list(t2.corrections_applied)})
7. return StageResult(...)
```

**`render()`**（load → 多源翻译 → run_from_transcript（render 专用配置，见出入 3）→ 记产物）
```
1. t = load_transcript_json(cfg.transcript.path)
2. cut_points = _translate_cut_points()           # CutPointSpec → types.CutPoint，见 §4
3. engines_r = replace(self.engines, aligner=None, llm=NoLLMClient())
4. opts = PipelineOptions(
       errata=ErrataConfig.empty(),
       proof=ProofOptions(enable_normalize=False, enable_errata=False, enable_phonetic=False,
                          enable_llm=False, enable_dual_channel=False),
       render=_render_options_from_cfg(),          # RenderOptsSpec → RenderOptions
       source_media="",                             # 多源：每条 CutPoint 自带 source_media
       skip_existing=True,                          # T5
       render_gate=True,                            # gate 在 render 内跑（同 run_from_transcript）
   )
5. results = run_from_transcript(t, cut_points, cfg.style_name, engines_r, opts,
                                  audio_path=cfg.transcript.audio_path)
6. _record("render", "done", cfg.render_opts.output_dir, {"clips": len(results), "style": cfg.style_name})
7. return StageResult("render", "done", cfg.render_opts.output_dir, False)
```

**`audit()`**（T3 audit_dir → 写 audit_report.json）
```
1. ro = cfg.render_opts
2. report = audit_dir(
       ro.output_dir,
       expected_horizontal=(ro.horizontal_width, ro.horizontal_height),
       expected_vertical=(ro.vertical_width, ro.vertical_height),
       render_horizontal=ro.render_horizontal,
       render_vertical=ro.render_vertical,
       raise_on_fail=False,        # T11 把 raise 收敛成「记进 manifest + 写 report」，不在此抛（让人看 report）
   )
3. report_path = str(Path(cfg.output_dir) / "audit_report.json"); report.save(report_path)
4. _record("audit", "done" if report.passed else "failed", report_path,
           {"passed": report.passed, "violations": len(report.violations)})
5. return StageResult("audit", "done" if report.passed else "failed", report_path, False)
```
- 注：`audit_dir` 默认 `raise_on_fail=True` 会抛 `RenderGateError`；T11 传 `False`，把结果收进 manifest + report，让 `all()` 不因 audit 失败中断后续（audit 是末步，本就最后；但 resume/all 的健壮性优先）。调用方读 `audit_report.json` 或 manifest.status 判断。

**`all()`**：`[self.transcribe(), self.proofread(), self.render(), self.audit()]`（强制全跑，不读 manifest 跳过）。

**`resume()`**：
```
manifest = self.read_manifest()
done = { row["stage"]: row for row in manifest.get("stages", []) if row.get("status") == "done" }
out = []
for fn, name in [(self.transcribe,"transcribe"),(self.proofread,"proofread"),
                 (self.render,"render"),(self.audit,"audit")]:
    row = done.get(name)
    if row and row.get("artifact_path") and Path(row["artifact_path"]).exists():
        out.append(StageResult(name, "done", row["artifact_path"], skipped=True))   # 跳过
    else:
        out.append(fn())
return out
```
- 跳过判定 = `status==done` **且** artifact_path 存在（朴素，D5 一脉相承；不用 params_hash 比对）。

### 4. 多源翻译 `_translate_cut_points()`（核心，T4 字段）

```
source_map = {s.id: s for s in cfg.sources}
out: list[CutPoint] = []
for cp in cfg.cut_points:
    spec = source_map[cp.source]   # validate(T7) 已保证存在；防御性 KeyError → ConfigError
    out.append(CutPoint(
        clip_id   = cp.clip_id,
        source_media = spec.path,          # load_project 已解析成绝对；直接透传
        start_s   = cp.start_s,            # 全局时间轴原值
        end_s     = cp.end_s,
        style_name= cp.style_name,         # 透传（render 实际用 cfg.style_name，见出入 4）
        title     = cp.title,
        source_offset_s = spec.source_offset_s,   # 全局→源本地的时间平移（T4 同义）
    ))
return out
```
- 这就是把 `tesla_stage04` 的 BATCH1/BATCH2（手搓 `source_media=SRC1/SRC2` + `source_offset_s=850`）退化成 `project.yaml` 里 19 条 `CutPointSpec` + 2 条 `SourceSpec(source_offset_s=850)`，再由 `run.render()` 一次翻译调用的机制。验证等价：SRC1 的 clip `source_offset_s=0`（默认），SRC2 的 clip `source_offset_s=850`，与 tesla_stage04 的 SEG1_END=850 逐字对齐。

### 5. `run_manifest.json` 形状（D6：schema_version=1）

```jsonc
{
  "schema_version": 1,
  "project": { "name": "<meta.name>", "root": "<meta.root 绝对>" },
  "updated": "2026-06-26T12:00:00",
  "stages": [
    { "stage": "transcribe", "status": "done",
      "artifact_path": "<root>/output/transcript.json",
      "params": {"engine": "FunASRLocal"},
      "started": "...", "finished": "..." },
    { "stage": "proofread", "status": "done", "artifact_path": "...", "params": {...}, "started": "...", "finished": "..." },
    { "stage": "render",    "status": "done", "artifact_path": "<root>/output/clips", "params": {"clips":19,"style":"fresh"}, "started": "...", "finished": "..." },
    { "stage": "audit",     "status": "done", "artifact_path": "<root>/output/audit_report.json", "params": {"passed":true,"violations":0}, "started": "...", "finished": "..." }
  ]
}
```
- **schema_version 冻结 = 1**；`load()` 读到 ≠1 → `ConfigError("run_manifest.json: unsupported schema_version=X (expected 1)")`（D6 落地）。
- params_hash：**v1 不算哈希**（D5 已定朴素跳过；Plan 的 params_hash 字段在 v1 留空/省略，resume 仅凭 status+artifact 存在）。若想留扩展位，可写 `"params_hash": null`；默认省略（to_dict 干净）。见 Q8。
- 同 stage 重跑 → 该行被新行覆盖（按 stage 去重，保留 last）。原子写（tmp + os.replace）。
- manifest 写时机：每个 `_record()` 重写整个 manifest（读旧 stages → 替换/追加同 stage 行 → 写回）。started/finished 用 ISO 本地时间字符串。

### 6. 错误语义汇总

| 场景 | 抛 / 行为 | 来源 |
|---|---|---|
| `transcribe()` 时 `engines.transcriber is None` | `RuntimeError` | T11 出入 2 |
| `transcribe()` 时 audio 文件不存在 | step1 内部抛（透传） | stage_asr |
| `proofread()` 时 transcript.json 不存在 | `FileNotFoundError`（透传 load_transcript_json） | T11（前置 transcribe 未跑） |
| `render()` 时 transcript.json 不存在 | 同上 | T11 |
| `render()` 时某 CutPointSpec.source 无对应 source | `ConfigError`（防御性包 KeyError） | T11 §4（理论上 T7 validate 已挡） |
| `audit()` 时 output_dir 不存在/无 clip | `audit_dir` 返回 violations（missing_file），status=failed，不抛（raise_on_fail=False） | T3 |
| `load(manifest)` schema_version ≠ 1 | `ConfigError`（明确信息） | D6 |
| `load(manifest)` manifest 不存在 / 非合法 json | `ConfigError` | T11 |
| manifest 写盘失败 | 原生 `OSError`（不吞；tmp+replace 保护原文件） | T11 |

---

## 需人拍板

### Q1：阶段方法名 —— Plan 的 `render()` 还是 Meta-Brief 的 `segment`/`cut_and_render`？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **`transcribe / proofread / render / audit`**（Plan 命名）。`render()` = segment+cut+render 一次调 `run_from_transcript`（内部原子，无 segment 单独 artifact）。 |
| B | 按 Meta-Brief 拆 `segment()` + `cut_and_render()`。 | 需把 segment 从 run_from_transcript 拆出来调 `stage_segment.segment`，但 cue 无持久化约定，manifest 无 artifact 可记；且违反「不改现有入口」。 |

> **默认 A**。Meta-Brief 的「segment/cut_and_render」是对 render 内部数据流的描述，非要求拆成两个公开方法。卡帕西 Simplicity First。

### Q2：`transcribe()` 复用 `run_from_audio` 还是直接调 step1+step2？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **直接调 `stage_asr.transcribe` + `stage_align.align` + `save_transcript_json`**。`run_from_audio` 跑全链 1-7，不是「只 ASR」。 |
| B | 调 `run_from_audio`。 | 会连带 proofread+segment+cut+render 全跑，与「分阶段」相悖。**否决**。 |

> **默认 A**（Plan T11 原文即此）。

### Q3：`render()` 要不要关掉 `run_from_transcript` 内部的 align + proofread？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **关掉**：render 专用 `engines_r = replace(engines, aligner=None, llm=NoLLMClient())` + `proof=ProofOptions(全False)` + `errata=empty`。理由：transcribe() 已 align、proofread() 已纠错覆盖写回 transcript.json；render 加载的是成品 transcript，不应二次处理。 |
| B | 不关，让它重跑 align + proofread。 | 重复劳动；errata 叠加可能副作用；与「阶段职责分离」相悖。 |

> **默认 A**。前提是调用方遵循 `transcribe → proofread → render` 序（`all()`/`resume()` 强制）。

### Q4：多源翻译的 per-clip `style_name` 怎么处理？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **项目级单一 style**：`render()` 把 `cfg.style_name` 作为 `run_from_transcript` 的 style_name；`CutPointSpec.style_name` 透传进 `types.CutPoint`（保信息）。现实主用例（tesla 19 条全 fresh）即此。 |
| B | 按 `CutPointSpec.style_name` 分组多次调 run_from_transcript。 | 支持 per-clip 多 style，但 +复杂度；当前无需求。defer。 |

> **默认 A**。per-clip 多 style 留待真有需求时另开任务。

### Q5：`proofread()` 的 errata 路径解析口径？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `Path(cfg.errata_path)`：绝对直用；相对则相对 `cfg.meta.root` 解析（内联 ~3 行，同 T9 `_resolve` 口径，不 import T9 私有）。`build_errata_config` 对缺失返回 empty（不抛）。 |
| B | 要求 cfg 必须来自 load_project（errata_path 已绝对）。 | 限制 ProjectRun 必须配 load_project，不够灵活（直传 from_dict cfg 也应能用）。 |

> **默认 A**。

### Q6：`resume()` 是实例方法还是 `load()` classmethod？manifest 落哪？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `resume()` **实例方法**（读自身 manifest 路径 `<cfg.meta.root>/run_manifest.json`）；`ProjectRun.load(manifest_path, engines)` **classmethod**（读 manifest → 校验 schema_version → `load_project(manifest.project.root, strict=False)` 重建 cfg → 返回 run）。manifest 落 **项目根**（与 project.yaml 同级）。 |
| B | manifest 落 `<output_dir>/`。 | output 是产物目录，运行元数据归属项目根更合理（project.yaml 旁）。 |

> **默认 A**。

### Q7：`all()` 要不要读 manifest 跳过？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **不跳过**，强制全跑（幂等：各步覆盖写）。`all()` = 「我要从头到尾跑一遍」。跳过语义归 `resume()`。 |
| B | `all()` 也读 manifest 跳过 done。 | 与 `resume()` 语义重叠，命名混乱。 |

> **默认 A**。`all()` 强制跑、`resume()` 智能跳过，职责分明。

### Q8：manifest 要不要带 params_hash？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **v1 不算哈希**（D5 已定朴素跳过）。manifest 只记 `params`（dict，便于人读）+ status + artifact_path + 时间戳。resume 仅凭 `status==done && artifact 存在` 跳过。 |
| B | 算 sha1(params) 存 params_hash，resume 比对哈希决定 stale。 | 哈希口径易错（哪些字段进哈希），且 D5 明确 defer。 |

> **默认 A**。params_hash 留作未来 stale 检测的扩展位（v1 省略该字段）。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **`pipeline.run_from_transcript`**（已读全文）：签名 `(transcript, cut_points, style_name, engines, opts, audio_path="")`。内部 `_prepare_plans` 做 align（若 engines.aligner）→ proofread（用 opts.errata + opts.proof）→ 可选 gap_heal → segment → cut；`_render_plans` 做 style 解析 + T5 skip_existing + render + 可选 render_gate。**这是 render() 要复用的入口，且必须用出入 3 的 render 专用配置避免二次 align/proof**。
- **`pipeline.Engines`**（已读）：frozen dataclass，字段 `transcriber/aligner/llm/style_resolver`。`from_env(env_path=...)` 只建 LLM，transcriber/aligner/style_resolver 由调用方注入。`dataclasses.replace(engines, aligner=None, llm=NoLLMClient())` 对 frozen 安全。`NoLLMClient` 在 `infra/llm_client`。
- **`pipeline.PipelineOptions`**（已读）：字段 `hotwords/errata/proof/segment/render/video_height/source_media/heal_gaps/heal_max_rounds/render_gate/skip_existing`。render() 构造时按出入 3 填。
- **`stage_asr`**（已读）：`transcribe(audio: AudioRef, engine: Transcriber, hotwords=()) -> Transcript`；`AudioRef(path)`；`Transcriber` 是 ABC。`engines.transcriber` 为 None 时 ProjectRun.transcribe() 抛 RuntimeError（run_from_audio 也是这口径）。
- **`stage_align`**（已读）：`align(transcript, aligner, audio_path) -> Transcript`。
- **`stage_proofread`**（已读）：`proofread(transcript, errata, llm, opts, audio_path="") -> Transcript`；`ProofOptions(enable_normalize/enable_errata/enable_phonetic/enable_llm/enable_dual_channel/llm_temperature)`；`ErrataConfig.empty()`。`dataclasses.asdict(cfg.proof_opts)` 可把 `ProofOptsSpec` → dict → `ProofOptions(**dict)`（字段名一一对应，已核对两边字段名完全一致）。
- **`config.build_errata_config(path)`**（已读）：缺失返回 `ErrataConfig.empty()`，不抛。
- **`stage_render.RenderOptions`**（已读）：plain class，`__init__(output_dir, render_horizontal, render_vertical, vertical_height, vertical_width, horizontal_height, horizontal_width, crf)`。`RenderOptsSpec`（T7）字段名一一对应（已核对），`RenderOptions(**asdict(cfg.render_opts))` 可翻译。注意 RenderOptsSpec.output_dir 默认 `"output/clips"`，RenderOptions.output_dir 是位置首参 —— dict 展开安全。
- **`render_gate.audit_dir`**（T3，已读）：签名含 `expected_horizontal/expected_vertical/expected_codec/render_horizontal/render_vertical/raise_on_fail/...`，返回 `AuditReport`。`AuditReport.save(path)` 写 json（已读 to_dict/save）。`AuditReport.passed` / `.violations` / `.skipped`。
- **`io_.sink.save_transcript_json`**（T1，已读）：`asdict` + json dump，覆盖写，幂等。
- **`io_.source.load_transcript_json`**（已读）：从 json 重建 Transcript（含 words）。不存在抛 FileNotFoundError。
- **`types.CutPoint`**（T4，已读）：`clip_id, source_media(必填), start_s, end_s, style_name="default", title="", source_offset_s=0.0`。与 `CutPointSpec` 字段对应（spec 的 `source`→CutPoint 的 `source_media`；spec 无 `source_media`）。
- **`project.schema.SourceSpec`**（T7，已读）：`id, path, timeline_start_s=0.0, timeline_end_s=None, source_offset_s=0.0`。`source_offset_s` 与 `CutPoint.source_offset_s` 同义（schema docstring 明示 T11 透传）。
- **`project.schema.CutPointSpec`**（T7，已读）：`clip_id, source, start_s, end_s, style_name="default", title=""`。`source` 是 id 引用。
- **`project.load.load_project`**（T9，已读）：返回绝对路径解析后的 cfg（运行时视图）；`load_project(root, strict=False)` 不查文件存在性 —— `ProjectRun.load()` 用 strict=False（manifest 续跑时产物可能不全，不卡）。
- **三入口签名**（已读）：`run_from_audio / run_from_transcript / run_montage` —— T11 只复用 `run_from_transcript`，**不改这三者**。
- **示例数据卫生**（AGENTS.md）：测试用 `tmp_path` + 占位 `SourceSpec(id="SRC1", path="source/ep01.mp4")` + 占位 transcript（`Segment`/`Word` 手搓）/ mock engines / mock ffmpeg，**禁止**真实 tesla 路径 / 真实 clip 标题 / 真实 errata（tesla_stage02/04 里的 `途材→FSD` 等不得进测试）。

---

## 验收标准

1. **新建 `src/garden_core/project/run.py`** + `project/__init__.py` 追加 re-export：`from garden_core.project import ProjectRun` 可达。
2. **构造**：`run = ProjectRun(cfg, engines)`；`run.manifest_path()` == `<cfg.meta.root>/run_manifest.json`。
3. **transcribe()**：mock `engines.transcriber`（返回固定 Transcript）+ `engines.aligner=None` → `run.transcribe()` 落 `<cfg.transcript.path>` 的 json（`load_transcript_json` 能读回，segments 数一致）；manifest 出现 `stage=transcribe, status=done, artifact_path=<transcript.path>`。`engines.transcriber=None` → `RuntimeError`。
4. **proofread()**：先跑 transcribe 落 transcript，再写一份占位 `corrections.yaml`（`{common: {错字: 对的}}`）→ `run.proofread()` → 读回 transcript 断言「错字」被替换成「对的」；manifest `stage=proofread, status=done`。
5. **render() 多源翻译**：cfg 含 2 条 `SourceSpec`（SRC1 `source_offset_s=0`、SRC2 `source_offset_s=850`）+ 2 条 `CutPointSpec`（一条 source=SRC1、一条 source=SRC2）。mock `run_from_transcript`（用 `monkeypatch` 拦 `garden_core.project.run.run_from_transcript`）→ 断言传给它的 `cut_points[0].source_media == <SRC1.path 绝对> && source_offset_s==0`，`cut_points[1].source_media == <SRC2.path> && source_offset_s==850`，`style_name == cfg.style_name`。manifest `stage=render, status=done`。
6. **render() 不二次 align/proof**：monkeypatch 拦 `stage_align.align` 与 `stage_proofread.proofread`，断言 render() 执行期间二者**未被调用**（出入 3）。
7. **audit()**：在 `<cfg.render_opts.output_dir>` 放占位 `{cid}_horizontal.mp4`/`{cid}.ass`（或空目录让 audit 报 missing_file）→ `run.audit()` 落 `<cfg.output_dir>/audit_report.json`；manifest `stage=audit`。`raise_on_fail=False` 保证不抛。
8. **all()**：monkeypatch 四个阶段方法为 spy → `run.all()` 断言四者按 `transcribe→proofread→render→audit` 序各调一次。
9. **resume() 跳过**：先 `run.all()`（或手动 `_record` 四个 done）→ 构造**新** `run2 = ProjectRun(cfg, engines)` → `run2.resume()` → 断言四个阶段方法**均未执行**（spy 计数 0），返回四个 `skipped=True` 的 StageResult。
10. **resume() 部分续跑**：manifest 只记 transcribe=done → `run.resume()` → transcribe 跳过、proofread/render/audit 执行。
11. **resume() artifact 丢失重跑**：transcribe 标 done 但删掉 transcript.json → `resume()` 重跑 transcribe（artifact 存在性兜底）。
12. **manifest schema_version**：`ProjectRun.load(manifest)` 正常 case 读回 cfg.meta.name 一致；手改 manifest `schema_version=999` → `ConfigError`（信息含 999 与 expected 1）。
13. **manifest 原子写**：跑若干阶段后 `run_manifest.json` 是合法 json；无残留 `.tmp`；同 stage 重跑该行被覆盖（不堆积）。
14. **load() classmethod**：`run2 = ProjectRun.load(run.manifest_path(), engines)` → `run2.cfg.meta.name == run.cfg.meta.name`；`.resume()` 可续。
15. **from_project_dir()**：`create_project` 建项目 → `ProjectRun.from_project_dir(root, engines)` 内部 `load_project(root, strict=False)` → cfg 字段一致。
16. **多源等价 tesla_stage04**：用占位数据构造 tesla_stage04 同构 cfg（2 source + offset 850 + 2 条 cut_point 跨源）→ render() 翻译出的 CutPoint 列表与 tesla_stage04 手搓的 BATCH1/BATCH2 在 `source_media`/`start_s`/`end_s`/`source_offset_s` 上逐字等价（占位路径，非真实 tesla 路径）。
17. **不破坏现有代码**：`pytest tests/` 全绿；T7/T8/T9/T10 的 schema/config/create/load/edit **零改动**；三入口 `run_from_audio`/`run_from_transcript`/`run_montage` 行为不回归（内部调用它们，不改）。

**pytest / 校验命令**：
```bash
# 可达性
python -c "from garden_core.project import ProjectRun; print('ok')"
# 专项
python -m pytest tests/test_project_run.py -v
# 全量回归
python -m pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 project/run.py (新增) + project/__init__.py (追加 re-export) + tests/test_project_run.py (新增)
# 卫生检查（无真实 tesla 数据泄露）
grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>|途材|逗哈" src/garden_core/project/run.py tests/test_project_run.py
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ 新建 `src/garden_core/project/run.py` | ❌ 改 `run_from_audio` / `run_from_transcript` / `run_montage`（pipeline.py 三入口，**硬约束**；只调用不改） |
| ✅ `project/__init__.py` 追加 `ProjectRun` 到 `__all__` + import | ❌ 改 `pipeline.py`（含 Engines/PipelineOptions/_prepare_plans/_render_plans） |
| ✅ 新建 `tests/test_project_run.py` | ❌ 改 T7 schema/config、T8 create、T9 load、T10 edit |
|  | ❌ 改 `types.py`（CutPoint）/ `stage_*`（asr/align/proofread/segment/cut/render）/ `render_gate`（T3）/ `io_`（T1）—— 只 import 复用 |
|  | ❌ 改 `ProjectConfig` / 任何 spec 字段或默认值（「不改 schema」铁律） |
|  | ❌ 拆 `segment()` 单独公开方法（Q1 默认 A，render 内含 segment） |
|  | ❌ 实现 per-clip 多 style 分组渲染（Q4 默认 A，defer） |
|  | ❌ 实现 params_hash / stale 检测（Q8 默认 A，v1 朴素 status 跳过） |
|  | ❌ 实现 T12 的 `rerender(clip_ids=)` / `reproofread(errata=)`（那是 T12，依赖 T11） |
|  | ❌ 新建/改 `scripts/tesla_*.py`（T11 是库层，不碰脚本；scripts 的替代由 T13 文档化） |
|  | ❌ 在测试里放真实 tesla 数据 / 真实 errata（卫生铁律） |

---

## 自测方法

1. **可达性**（验收 1）：`python -c "from garden_core.project import ProjectRun"`。
2. **transcribe happy**（验收 3）：`tmp_path` → `create_project("demo", root, sources=[SourceSpec("SRC1","source/ep01.wav")])` → 手搓一个最小 transcript（`Transcript(segments=(Segment(text="测试",start_s=0,end_s=1),), source_file=audio, engine="mock")`）→ 用一个 fake transcriber（实现 `transcribe(audio, hotwords)` 返回该 transcript）+ `engines=Engines(transcriber=fake)` → `run.transcribe()` → `load_transcript_json(cfg.transcript.path).segments[0].text == "测试"`；manifest stage=transcribe done。
3. **transcribe 无 transcriber**（验收 3）：`Engines()` → `pytest.raises(RuntimeError)`。
4. **proofread errata 生效**（验收 4）：transcribe 后写 `corrections.yaml`（`common: {"甲": "乙"}`）+ 手搓 transcript 含「甲」→ `run.proofread()` → 读回含「乙」。注：errata 替换是 segment 级文本替换（`apply_errata_to_segments`），断言 segment.text 含「乙」。
5. **render 多源翻译**（验收 5/16）：cfg 两 source（SRC1 offset=0、SRC2 offset=850）+ 两 cut_point（t01→SRC1 0-81、t14→SRC2 850-911）→ monkeypatch `garden_core.project.run.run_from_transcript` 为 lambda 返回 `[]` 并捕获入参 → `run.render()` → 断言捕获的 cut_points[0] source_media==SRC1.path / offset 0；cut_points[1] source_media==SRC2.path / offset 850；style_name==cfg.style_name。
6. **render 不二次 align/proof**（验收 6）：monkeypatch `stage_align.align`、`stage_proofread.proofread` 为会抛的 spy → render() 不触发它们（即不抛）。先准备一份 transcript.json 让 load 成功。
7. **audit**（验收 7）：render_opts.output_dir 空目录 → `run.audit()` → `audit_report.json` 存在且 `passed==False`（missing_file）；manifest stage=audit failed；未抛异常。
8. **all() 序**（验收 8）：spy 四方法 → all() 调用序 == [transcribe,proofread,render,audit]。
9. **resume 全跳过**（验收 9）：跑完 all() → 新 run2 → spy 四方法 → resume() 四方法计数 0，返回 skipped=True ×4。
10. **resume 部分**（验收 10）：手写 manifest 只 transcribe done → resume() → transcribe 跳、其余跑。
11. **resume artifact 丢失重跑**（验收 11）：manifest transcribe done 但删 transcript.json → resume() 重跑 transcribe。
12. **schema_version 校验**（验收 12）：load 合法 manifest ok；改 schema_version=999 → `ConfigError`。
13. **原子写 / 无 tmp 残留**（验收 13）：跑若干阶段后 `not (root/"run_manifest.json.tmp").exists()`；manifest 合法 json；同 stage 重跑行数不增。
14. **load classmethod**（验收 14）：`ProjectRun.load(manifest, engines).cfg.meta.name == run.cfg.meta.name`。
15. **from_project_dir**（验收 15）：create → `ProjectRun.from_project_dir(root, engines).cfg.meta.name == "demo"`。
16. **diff 范围**（验收 17）：`git diff --name-only` 仅 `project/run.py`（新增）+ `project/__init__.py`（追加）+ `tests/test_project_run.py`（新增）。
17. **回归**：`pytest tests/ -v` 全绿（T11 纯新模块，T7-T10 测试保持绿；三入口测试不回归）。
18. **卫生检查**：`grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>|途材|逗哈" src/garden_core/project/run.py tests/test_project_run.py` 无命中。

---

## 风险

- **无破坏性（对现有调用方）**：纯新模块（`run.py` + `__init__.py` 追加 re-export + tests），不碰 pipeline 三入口、不碰 T7-T10、不碰 stage_*/io_/render_gate。`pytest tests/` 应全绿。
- ⚠️ **render() 关 align/proof 的前提**（出入 3）：render() 假设 transcript.json 已被 transcribe()+proofread() 处理过。若调用方**跳过 proofread 直接 render**，render 不会做 errata 纠错（`proof=全False, errata=empty`）。这是设计意图（阶段职责分离），但 docstring + 测试 6 须显式说明：「render() 不纠错，纠错归 proofread()」。`all()`/`resume()` 强制正确顺序，正常使用不会踩坑。
- ⚠️ **单一 style 限制**（出入 4/Q4）：render() 全部 clip 用 `cfg.style_name`。若 project.yaml 里不同 CutPointSpec 写了不同 style_name，render 时**被忽略**（透传进 CutPoint 但 run_from_transcript 用传入的 cfg.style_name）。docstring 说明；真需要 per-clip 多 style 另开任务。
- ⚠️ **manifest 是项目级单文件**（Q6）：`<root>/run_manifest.json`。同一项目并发跑两个 ProjectRun 会互相覆盖 manifest —— 不是本任务范围（单机串行是既有假设，AGENTS.md 执行环境单 conda env）。docstring 注明「非并发安全」。
- ⚠️ **params_hash defer**（Q8）：v1 resume 仅凭 `status==done && artifact 存在`，**不检测参数变更导致的 stale**（改了 cut_points 后 resume 会误跳 render）。这是 D5 一脉相承的「朴素跳过」权衡；调用方改配置后想强制重跑用 `all()` 或手动删 manifest 对应行。docstring 说明。
- ⚠️ **audit 收敛 raise**（§3 audit）：T11 把 `audit_dir(raise_on_fail=False)`，audit 失败不抛、记进 manifest status=failed。若调用方想要「audit 失败即阻断」，自行读 `audit_report.json` / manifest 判断。这与 T3 原生 `raise_on_fail=True` 默认不同，是 T11 编排层的刻意选择（all/resume 健壮性优先）。
- **依赖 T1-T9 已落地**：T11 建立在 T1（save_transcript_json）+ T2（Engines.from_env）+ T3（audit_dir）+ T4（CutPoint.source_media 必填 + source_offset_s）+ T5（skip_existing）+ T7（ProjectConfig/spec/validate）+ T9（load_project）之上。均已验收，本 brief 假设其冻结。T12（rerender/reproofread）建立在 T11 之上，本任务不实现。

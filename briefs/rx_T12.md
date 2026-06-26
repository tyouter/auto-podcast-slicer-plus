# RX Brief · T12 — `ProjectRun.rerender(clip_ids=)` / `.reproofread(errata=)`（增量重跑入口）

> **一句话**：在 T11 已落地的 `src/garden_core/project/run.py` 里**新增两个增量方法**——`rerender(clip_ids)`（只重渲指定 clip，不改 transcript）与 `reproofread(errata=None, *, rerender_clip_ids=None)`（用新 errata 重跑纠错覆盖 transcript，可选顺带重渲指定 clip）。两者**复用 T11 已有的内部逻辑**（`_translate_cut_points` / `proofread` / `run_from_transcript`），通过**抽取两个私有 helper**（`_render_cut_points` / `_apply_proofread`）让 `render()`/`proofread()` 与新方法共享实现，**不改 T11 已有方法的对外行为**。`rerender` 的核心是「取 cut_points 子集 + 强制 `skip_existing=False`」；`reproofread` 的核心是「注入 ErrataConfig + 覆盖 transcript.json + manifest」。纯增量，不碰 pipeline 三入口、不碰 T7-T10、不碰 stage_*/io_/render_gate。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第二层 · 项目管理系统」→ **T12 · `run.rerender(clip_ids=)` / `run.reproofread(errata=)`**（L452-470；依赖 T11）。`IMPLEMENTATION_PLAN.md` L30/L86（T12 风险：低，建立在 T11）。

---

## ⚠️ 执行前必读：Meta-Brief / Plan 与 T11 已落地代码的出入

Meta-Brief（本次任务输入）给的方法形是 `rerender(clip_ids)` + `reproofread(overrides)`，并写「reproofread —— 重新纠错**+重渲受影响 clip**」。Plan T12 原文给的是 `rerender(clip_ids=["t06","t09"])`（强制不 skip，覆盖那几条）+ `reproofread(errata=new_errata)`（覆盖 transcript），且 Plan 验收示例明确写「errata 修正后 `run.reproofread(errata=new_errata)` 覆盖 transcript **并可立即 `run.rerender(...)`**」——即 Plan 把「重渲」当作 reproofread 之后的**独立一步**，不内置进 reproofread。对照已落地的 `run.py`（T11，已读全文），有四处必须澄清。**默认按「Plan + 卡帕西 Simplicity First」走**：

### 出入 1：Meta-Brief 的 `reproofread(overrides)` vs Plan 的 `reproofread(errata=...)` —— 收敛签名 + 可选顺带重渲

- Meta-Brief 用 `overrides`（泛指），Plan 用 `errata=new_errata`（明确是 ErrataConfig）。Plan 更具体，**按 Plan**：`reproofread(errata: ErrataConfig | None = None, *, rerender_clip_ids: Sequence[str] | None = None)`。
- `errata=None` → 复用 `cfg.errata_path`（与 `proofread()` 同源；便于「外部手改 corrections.yaml → reproofread()」工作流）。`errata=<ErrataConfig>` → 直接注入，**不持久化到 project.yaml**（ProjectRun 是运行时编排器，不替 T10 `edit_project` 干活；持久化 errata 是调用方/人审的职责，见 Q1）。
- 「重渲受影响 clip」（Meta-Brief）落到 `rerender_clip_ids` 可选 kw-only 参数：传 `None`（默认）→ **只纠错覆盖 transcript，不重渲**（与 Plan 验收示例「reproofread 后另行 rerender」一致）；传 `["t06"]` → 纠错后**顺带**调 `self.rerender(rerender_clip_ids)`。这样既满足 Plan 的「分离」语义（默认不重渲），又满足 Meta-Brief 的「纠错+重渲」意图（opt-in 一行完成）。见 Q2。
- **不追踪 transcript diff**（不实现「自动判定哪些 clip 文本变了」）——「受影响 clip」由调用方显式传 `rerender_clip_ids` 指定；自动 diff 是过度设计，defer。见 Q3。

### 出入 2：`rerender` 怎么「强制不 skip」—— 选 `skip_existing=False`（非 manifest 标 stale）

- Plan 给了两条路：「临时关 `skip_existing`」或「manifest 标记这些 clip 为 stale」。后者要在 manifest 里维护 per-clip stale 标记 + 改 `_render_plans`/`_maybe_skip` 读 manifest —— 违反「不改 pipeline」+ 跨模块耦合，且 T11 manifest 的 stage 行粒度是「整阶段」不是「per-clip」。
- **结论**：`rerender` 走「子集 cut_points + `opts.skip_existing=False`」——`run_from_transcript` 收到子集 + 不跳过，自然只重渲那几条（其余 clip 因不在 cut_points 列表里，`_render_plans` 根本不碰它们的 mp4）。这是最小改动、零跨模块耦合。见 Q4。
- 副作用确认（已读 `_render_plans`）：`skip_existing=False` 时每条 plan 都走 `render(plan, ...)` 覆盖写 mp4/ass/srt；末尾 `gate_results(results)` 只对**本次返回的子集 results** 跑 gate（不会扫全目录），符合预期。

### 出入 3：要不要改 `render()` / `proofread()` 的对外签名 —— 不改，只抽 helper

- 新方法与 T11 的 `render()`/`proofread()` 共享约 90% 逻辑（load transcript → 构造 engines_r/opts → 调 run_from_transcript / proofread → save → _record）。直接复制粘贴会留下两份近重复代码（卡帕西「最简」反例：重复≠简）。
- **结论**：抽两个**私有** helper（run.py 内部，不进 `__all__`）：
  - `_render_cut_points(self, cut_points: list[CutPoint], *, skip_existing: bool) -> list[RenderResult]`：含 load transcript + 构造 engines_r/opts（`proof=全False/errata=empty`，同 T11 出入 3）+ 调 `run_from_transcript`，返回 results。**不**做 `_record`（落 manifest 归调用方，便于 render/rerender 记不同 params）。
  - `_apply_proofread(self, errata: ErrataConfig) -> StageResult`：含 load transcript + `proofread(...)` + save + `_record("proofread", ...)`。
  - `render()` 改为：`results = self._render_cut_points(self._translate_cut_points(), skip_existing=True)` → `_record("render", ...)`。`proofread()` 改为：`return self._apply_proofread(build_errata_config(self._resolve_errata_path()))`。
  - `rerender(clip_ids)`：`subset = [cp for cp in self._translate_cut_points() if cp.clip_id in set(clip_ids)]` → 校验非空且 id 全命中 → `self._render_cut_points(subset, skip_existing=False)` → `_record("render", "done", cfg.render_opts.output_dir, {"clips": list(clip_ids), "rerender": True})`。
  - `reproofread(errata=None, *, rerender_clip_ids=None)`：`e = errata if errata is not None else build_errata_config(self._resolve_errata_path())` → `self._apply_proofread(e)` → 若 `rerender_clip_ids` 非 None → `self.rerender(rerender_clip_ids)`（返回值合并进 list 或忽略 rerender 的 StageResult，见 §签名）。
- **T11 已有方法的对外行为零回归**：`render()`/`proofread()` 的签名、返回值、manifest 记录内容、stage 名全部不变；仅内部走 helper。T11 测试须全绿（验收回归项）。见 Q5。

### 出入 4：manifest 怎么记 rerender / reproofread —— 复用现有 stage 行（last-write-wins）

- T11 manifest 的 stage 行按 `stage` 名去重（`_record` 里 `[s for s in stages if s.get("stage") != stage]`）。`rerender` 仍记 `stage="render"`（覆盖原 render 行），`reproofread` 仍记 `stage="proofread"`（覆盖原 proofread 行）。**不新增 stage 名**（如 `rerender`/`reproofread`），保持 manifest schema 稳定（D6 schema_version 仍=1，不动）。
- 区分全量 vs 增量靠 **params dict**：`render()` 记 `{"clips": N, "style": ...}`；`rerender()` 记 `{"clips": ["t06","t09"], "style": ..., "rerender": True}`。`proofread()`/`reproofread()` 记 `{"corrections": [...]}`；reproofread 额外可在 params 加 `"errata_source": "inline"|"cfg"`（便于人读，可选）。见 Q6。
- 这样 `resume()` 语义不变（看 `stage=="render"` done + artifact 存在 → 跳过）；rerender 后 manifest 的 render 行被刷新，artifact_path 仍是 `cfg.render_opts.output_dir`（目录级，存在），resume 仍正确跳过。**不引入 stale 概念**。

> 若人审对以上四处（+ Q1-Q6）有异议，开工前拍板；否则按上述默认走。

---

## 核心目标

### 1. 改动文件清单（仅 2 个）

```
src/garden_core/project/run.py     # ★ T12 主改：抽 2 helper + 加 2 方法 + 改 render()/proofread() 内部
tests/test_project_rerun.py         # ★ T12 新增测试
```

- **不改** `project/__init__.py`（`ProjectRun` 已在 T11 re-export；新方法是 ProjectRun 的成员，无需新增顶层符号）。
- **不改** pipeline / stage_* / io_ / render_gate / types / T7-T10 任何文件。
- **不改** `scripts/tesla_*.py`（T12 是库层；tesla_refix 的退化为「一行 `run.rerender(...)`」由 T13 文档化，本任务不碰脚本）。

### 2. `ProjectRun` 新增 / 改动签名（T11 基础上）

```python
@dataclass(frozen=True)
class ProjectRun:
    cfg: ProjectConfig
    engines: Engines

    # —— T11 已有（对外不变；内部改走 helper）——
    def transcribe(self) -> StageResult: ...
    def proofread(self) -> StageResult: ...          # 内部改为 _apply_proofread(build_errata_config(...))
    def render(self) -> StageResult:                  # 内部改为 _render_cut_points(..., skip_existing=True)
        ...
    def audit(self) -> StageResult: ...
    def all(self) -> list[StageResult]: ...
    def resume(self) -> list[StageResult]: ...

    # —— T12 新增 ——
    def rerender(self, clip_ids: Sequence[str]) -> StageResult: ...
    def reproofread(
        self,
        errata: ErrataConfig | None = None,
        *,
        rerender_clip_ids: Sequence[str] | None = None,
    ) -> list[StageResult]: ...

    # —— T12 新增私有 helper（不进 __all__）——
    def _render_cut_points(
        self, cut_points: list[CutPoint], *, skip_existing: bool
    ) -> list[RenderResult]: ...
    def _apply_proofread(self, errata: ErrataConfig) -> StageResult: ...
```

- `rerender` 返回单个 `StageResult`（与 `render()` 同形，stage="render"）。
- `reproofread` 返回 `list[StageResult]`：至少含 proofread 那一条；若传了 `rerender_clip_ids`，追加 rerender 那一条。这样调用方能拿到两步的产物路径。（若只纠错不重渲，返回长度 1 的 list。）

### 3. `_render_cut_points(cut_points, *, skip_existing)` 实现（抽自 T11 render()）

```python
def _render_cut_points(self, cut_points, *, skip_existing):
    t = load_transcript_json(self.cfg.transcript.path)
    engines_r = dataclasses.replace(
        self.engines, aligner=None, llm=NoLLMClient()
    )
    opts = PipelineOptions(
        errata=ErrataConfig.empty(),
        proof=ProofOptions(
            enable_normalize=False, enable_errata=False, enable_phonetic=False,
            enable_llm=False, enable_dual_channel=False,
        ),
        render=self._render_options_from_cfg(),
        source_media="",
        skip_existing=skip_existing,        # ← 唯一变量：render() 传 True，rerender() 传 False
        render_gate=True,
    )
    return run_from_transcript(
        t, cut_points, self.cfg.style_name, engines_r, opts,
        audio_path=self.cfg.transcript.audio_path,
    )
```

- 与 T11 `render()` 内部逻辑**逐字一致**，唯一区别是把 `skip_existing` 参数化、把 `cut_points` 参数化（不再固定调 `_translate_cut_points()`）。
- `render()` 改为：
  ```python
  def render(self):
      results = self._render_cut_points(
          self._translate_cut_points(), skip_existing=True
      )
      self._record("render", "done", self.cfg.render_opts.output_dir,
                   {"clips": len(results), "style": self.cfg.style_name})
      return StageResult("render", "done", self.cfg.render_opts.output_dir, False)
  ```

### 4. `rerender(clip_ids)` 实现

```python
def rerender(self, clip_ids):
    ids = list(clip_ids)
    if not ids:
        raise ValueError("rerender(): clip_ids must be a non-empty sequence")
    wanted = set(ids)
    all_cps = self._translate_cut_points()
    known = {cp.clip_id for cp in all_cps}
    unknown = wanted - known
    if unknown:
        raise ConfigError(
            f"rerender(): unknown clip_ids {sorted(unknown)}; "
            f"known: {sorted(known)}"
        )
    subset = [cp for cp in all_cps if cp.clip_id in wanted]
    # 保持 cfg.cut_points 原顺序（_translate_cut_points 已保序）；若想按 clip_ids 顺序可再 sort，默认保 cfg 序。
    results = self._render_cut_points(subset, skip_existing=False)
    self._record("render", "done", self.cfg.render_opts.output_dir,
                 {"clips": ids, "style": self.cfg.style_name, "rerender": True})
    return StageResult("render", "done", self.cfg.render_opts.output_dir, False)
```

- 空 `clip_ids` → `ValueError`（明确信息）。未知 id → `ConfigError`（同 T7/T11 防御性口径）。
- `skip_existing=False` 强制覆盖指定 clip 的 mp4/ass/srt；其余 clip 不在 subset，`_render_plans` 不碰。
- manifest 记 `stage="render"`（覆盖原 render 行），params 标 `"rerender": True` + 具体 clips 列表，便于人读区分全量 vs 增量。

### 5. `_apply_proofread(errata)` 实现（抽自 T11 proofread()）

```python
def _apply_proofread(self, errata):
    t = load_transcript_json(self.cfg.transcript.path)
    opts = ProofOptions(**dataclasses.asdict(self.cfg.proof_opts))
    t2 = proofread(
        t, errata=errata, llm=self.engines.llm, opts=opts,
        audio_path=self.cfg.transcript.audio_path,
    )
    save_transcript_json(t2, self.cfg.transcript.path)
    self._record("proofread", "done", self.cfg.transcript.path,
                 {"corrections": list(t2.corrections_applied)})
    return StageResult("proofread", "done", self.cfg.transcript.path, False)
```

- `proofread()` 改为：`return self._apply_proofread(build_errata_config(self._resolve_errata_path()))`。
- 与 T11 `proofread()` 内部逻辑**逐字一致**，唯一区别是把 `errata` 参数化（不再固定 `build_errata_config(self._resolve_errata_path())`）。

### 6. `reproofread(errata=None, *, rerender_clip_ids=None)` 实现

```python
def reproofread(self, errata=None, *, rerender_clip_ids=None):
    if errata is None:
        e = build_errata_config(self._resolve_errata_path())
        src = "cfg"
    else:
        e = errata
        src = "inline"
    out = [self._apply_proofread(e)]
    # 在 proofread 的 params 上补一个 errata_source 标记（便于人读；last-write-wins 重写该行）
    # —— 实现上：_apply_proofread 已 _record 一次；若想标 src，改 _apply_proofread 接受 extra_params，
    #     或 reproofread 之后再 _record 一次覆盖。默认走「_apply_proofread 记标准行」，
    #     reproofread 不额外改 manifest（保持与 proofread() 记录一致），src 标记 defer（见 Q6）。
    if rerender_clip_ids is not None:
        out.append(self.rerender(rerender_clip_ids))
    return out
```

- `errata=None`（默认）：复用 `cfg.errata_path`（外部手改 corrections.yaml 后直接 `run.reproofread()` 即可重纠错）。
- `errata=<ErrataConfig>`：注入式，**不写盘**（不调 `edit_project`、不写 corrections.yaml、不改 project.yaml）。调用方想持久化自行用 T10 `edit_project(errata_path=...)` 或手写 yaml。
- `rerender_clip_ids=None`（默认）：只纠错覆盖 transcript，返回 `[proofread_StageResult]`。传 list：纠错后顺带 `self.rerender(...)`，返回 `[proofread_sr, rerender_sr]`。
- docstring 显式说明：「reproofread 不持久化 errata 到 project.yaml；要持久化用 `edit_project(errata_path=...)`。」

### 7. 错误语义汇总（T12 新增行）

| 场景 | 抛 / 行为 | 来源 |
|---|---|---|
| `rerender([])` 空 clip_ids | `ValueError`（明确信息） | T12 §4 |
| `rerender(["t99"])` 未知 clip_id | `ConfigError`（信息含 unknown + known 列表） | T12 §4 |
| `rerender(...)` 时 transcript.json 不存在 | `FileNotFoundError`（透传 `load_transcript_json`） | T11 同 |
| `reproofread(errata=None)` 时 corrections.yaml 缺失 | `build_errata_config` 返回 empty（不抛），按空 errata 纠错 | T9/config.py |
| `reproofread(rerender_clip_ids=["t99"])` 未知 id | 透传 `rerender` 的 `ConfigError` | T12 §4 |
| `rerender` / `reproofread` 时 manifest 写盘失败 | 原生 `OSError`（T11 原子写口径） | T11 |

---

## 需人拍板

### Q1：`reproofread(errata=)` 要不要把 errata 持久化到 project.yaml / corrections.yaml？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **不持久化**。`errata=<ErrataConfig>` 仅用于本次纠错运行，覆盖 transcript.json 后即弃。要持久化由调用方用 T10 `edit_project(errata_path=...)` 或手写 corrections.yaml。理由：ProjectRun 是运行时编排器，写配置文件是 T10 `edit_project` 的职责（单一职责）；混在一起破坏「cfg 不可变 + manifest 是唯一运行态」的 T11 模型。 |
| B | reproofread 内部调 `edit_project(errata_path=...)` 把新 errata 落盘。 | 需要把 ErrataConfig 序列化成 yaml（ErrataConfig 无 to_yaml），且改 project.yaml 副作用大（frozen cfg 与磁盘 cfg 漂移）。**否决**。 |

> **默认 A**。docstring 明示「不持久化」。

### Q2：`reproofread` 默认要不要顺带重渲？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **默认不重渲**（`rerender_clip_ids=None`）。与 Plan 验收示例「reproofread 后另行 rerender」一致。想一行搞定传 `rerender_clip_ids=[...]`。 |
| B | 默认重渲全部 clip。 | 无 diff 追踪下「全部」过宽（19 条全重渲很贵）；「受影响」又需 diff。**否决**。 |

> **默认 A**。Meta-Brief 的「纠错+重渲」由 `rerender_clip_ids` opt-in 满足。

### Q3：要不要自动追踪 transcript diff 决定「受影响 clip」？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **不追踪**。「受影响 clip」由调用方显式传 `rerender_clip_ids`。 | 卡帕西 Simplicity First；diff 口径易错（segment↔clip 映射、时间区间相交判定）。 |
| B | reproofread 内部对比纠错前后 transcript，按 segment 文本变化映射到 clip，自动算受影响集。 | +显著复杂度（segment→clip 区间相交几何）；当前无强需求。defer。 |

> **默认 A**。

### Q4：`rerender` 强制不 skip 的机制？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **子集 cut_points + `skip_existing=False`**。最小改动，零跨模块耦合。 |
| B | manifest 维护 per-clip stale 标记，改 `_render_plans`/`_maybe_skip` 读 manifest。 | 违反「不改 pipeline」+ T11 manifest 是 stage 级非 per-clip。**否决**。 |

> **默认 A**。

### Q5：要不要抽 helper（改 render()/proofread() 内部）？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **抽 `_render_cut_points` + `_apply_proofread`**，render()/proofread() 改走 helper。对外签名/返回值/manifest 记录零变化，T11 测试须全绿。避免两份近重复代码。 |
| B | 不抽，rerender/reproofread 各自复制粘贴 ~15 行。 | 重复代码，未来维护两份。卡帕西「最简」反例。 |

> **默认 A**。surgical：只动 run.py，render()/proofread() 对外不变。

### Q6：manifest 要不要新增 stage 名 / params 标记区分增量？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **复用现有 stage 名**（`render`/`proofread`），靠 params dict 区分（rerender 加 `"rerender": True` + clips 列表）。schema_version 仍=1，不动。`resume()` 语义不变。 |
| B | 新增 `stage="rerender"` / `"reproofread"` 行。 | manifest schema 膨胀；resume 须新增分支；D6 schema_version 要不要 bump？过度。**否决**。 |

> **默认 A**。reproofread 的 `errata_source` 标记（inline/cfg）**可选**，默认不加（保持与 proofread() 记录完全一致）；想加可在 `_apply_proofread` 接 `extra_params`，defer。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **`run.py`（T11，已读全文）**：`render()` 内部构造 `engines_r = replace(engines, aligner=None, llm=NoLLMClient())` + `proof=ProofOptions(全False)` + `errata=ErrataConfig.empty()` + `source_media=""` + `skip_existing=True` + `render_gate=True`，调 `run_from_transcript`。`proofread()` 内部 `load → build_errata_config(_resolve_errata_path()) → proofread(...) → save → _record`。`_record` 按 stage 名去重（last-write-wins）。`_translate_cut_points()` 保 `cfg.cut_points` 顺序。`_resolve_errata_path()` 绝对/相对口径已定。`ProjectRun` 是 frozen dataclass（不能改 cfg，故 reproofread 不持久化 errata，见 Q1）。
- **`pipeline.run_from_transcript`（已读）**：签名 `(transcript, cut_points, style_name, engines, opts, audio_path="")`。`_prepare_plans`（align→proofread→segment→cut）+ `_render_plans`（style→skip→render→gate）。cut_points 是 `list[CutPoint]`，子集传入即只处理子集。
- **`pipeline._render_plans`（已读）**：`if opts.skip_existing: _maybe_skip(...)` —— `skip_existing=False` 时每条 plan 都走 `render(plan, ...)` 覆盖写。末尾 `gate_results(results)` 只对本次 results（子集）跑 gate。**确认 rerender 子集 + skip_existing=False 语义正确**。
- **`pipeline.PipelineOptions.skip_existing`（已读）**：字段，默认 True。render()/rerender() 各自传 True/False。
- **`stage_proofread.ErrataConfig`（已读）**：frozen dataclass，`flat: dict` + `patterns: tuple`；`ErrataConfig.empty()` 返回 `cls()`。`proofread(transcript, errata, llm, opts, audio_path="")`。**确认 reproofread 注入 ErrataConfig 可行**。
- **`config.build_errata_config(path)`（已读）**：缺失文件返回 `ErrataConfig.empty()`，不抛。reproofread(errata=None) 复用此。
- **`project.edit.edit_project`（T10，已读全文）**：`edit_project(root_dir, **overrides)`，`errata_path` 是合法 scalar override key。**但 T12 不用它**（Q1 默认 A，reproofread 不持久化）。
- **`project.schema`（T7，已读）**：`CutPointSpec(clip_id, source, start_s, end_s, style_name, title)`；`SourceSpec(id, path, source_offset_s, ...)`。`_translate_cut_points` 产出 `types.CutPoint`（带 clip_id）。rerender 按 `cp.clip_id` 过滤。
- **manifest 去重（T11 `_record`，已读）**：`stages = [s for s in stages if s.get("stage") != stage]` 后 append。**确认 rerender/reproofread 记 `render`/`proofread` 行会覆盖原行，schema_version 不变**。
- **示例数据卫生（AGENTS.md）**：测试用 `tmp_path` + 占位 `SourceSpec/CutPointSpec` + 占位 transcript + mock ffmpeg（monkeypatch `run_from_transcript`），**禁止**真实 tesla clip id（如 `t06/t09` 进测试要换成 `c01/c02` 占位）/ 真实 errata 内容。

---

## 验收标准

1. **新增方法可达**：`python -c "from garden_core.project import ProjectRun; assert hasattr(ProjectRun, 'rerender') and hasattr(ProjectRun, 'reproofread'); print('ok')"`。
2. **rerender 子集 + 强制不 skip**：cfg 含 3 条 cut_point（c01/c02/c03）→ monkeypatch `garden_core.project.run.run_from_transcript` 捕获入参 → `run.rerender(["c01","c03"])` → 断言传给 `run_from_transcript` 的 `cut_points` 恰好是 `[c01, c03]`（按 cfg 序，clip_id 集合相等）**且** `opts.skip_existing is False`。manifest `stage=render, status=done, params={"clips":["c01","c03"], "rerender":True, ...}`。
3. **rerender 不碰其余 clip**：验收 2 的 fake `run_from_transcript` 返回固定 `[]`；断言它**只被调用一次**（不会为 c02 单独调用）；c02 的 mp4 不在 subset 里，`_render_plans` 不碰（由 monkeypatch 保证，不实测 ffmpeg）。
4. **rerender 空 clip_ids**：`run.rerender([])` → `pytest.raises(ValueError)`。
5. **rerender 未知 id**：`run.rerender(["c99"])` → `pytest.raises(ConfigError)`，信息含 `c99` 与 known 列表。
6. **reproofread(errata=) 注入式**：先 transcribe 落占位 transcript（含「甲」）→ 构造 `ErrataConfig(flat={"甲":"乙"})` → `run.reproofread(errata=that)` → 读回 transcript 断言 segment.text 含「乙」、不含「甲」；返回 list 长度 1（proofread StageResult）；manifest `stage=proofread, status=done`。
7. **reproofread(errata=None) 复用 cfg.errata_path**：外部写占位 corrections.yaml（`common: {"甲":"乙"}`）→ `run.reproofread()`（不传 errata）→ 同验收 6 断言。
8. **reproofread 不持久化 errata**：验收 6 后断言 project.yaml 的 `errata_path` 字段**未变**（reproofread 没写盘 cfg）；corrections.yaml（若存在）内容未变。
9. **reproofread + rerender_clip_ids 顺带重渲**：`run.reproofread(errata=that, rerender_clip_ids=["c01"])` → 返回 list 长度 2（proofread + rerender 两个 StageResult）；rerender 的 StageResult.stage=="render"。monkeypatch `run_from_transcript` 断言被调一次（rerender 触发）、cut_points==[c01]、skip_existing False。
10. **render() / proofread() 对外零回归**：spy 或复用 T11 测试 —— `run.render()` 返回 StageResult(stage="render", artifact=cfg.render_opts.output_dir)；`run.proofread()` 返回 StageResult(stage="proofread", artifact=cfg.transcript.path)；manifest 记录与 T11 完全一致（params 不含 `rerender` 键）。**T11 的 `test_project_run.py` 全绿**（关键回归项）。
11. **helper 私有**：`_render_cut_points` / `_apply_proofread` 不在 `project/__init__.py` 的 `__all__`，也不在 `run.py` 的 `__all__`（`__all__` 仍仅 `["ProjectRun", "StageResult"]`）。
12. **manifest schema 稳定**：rerender/reproofread 后 manifest 仍是 `schema_version=1`，stage 名仍只有 `transcribe/proofread/render/audit` 四种（无 `rerender`/`reproofread` 新名）。`resume()` 在 rerender 后仍能正确识别 render 行 done 并跳过。
13. **不破坏现有代码**：`pytest tests/` 全绿；pipeline 三入口、T7-T10、stage_*/io_/render_gate/types 零改动。

**pytest / 校验命令**：
```bash
# 可达性
python -c "from garden_core.project import ProjectRun; assert hasattr(ProjectRun,'rerender') and hasattr(ProjectRun,'reproofread'); print('ok')"
# 专项（T12 新测试）
python -m pytest tests/test_project_rerun.py -v
# T11 回归（必须全绿）
python -m pytest tests/test_project_run.py -v
# 全量回归
python -m pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 project/run.py (改) + tests/test_project_rerun.py (新增)
# 卫生检查（无真实 tesla 数据泄露；c01/c02 占位 ok，t06/t09 真实 id 禁止）
grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>|途材|逗哈|\"t0[0-9]" src/garden_core/project/run.py tests/test_project_rerun.py
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ `src/garden_core/project/run.py`（抽 2 helper + 加 `rerender`/`reproofread` + render()/proofread() 内部改走 helper） | ❌ 改 `run_from_audio` / `run_from_transcript` / `run_montage`（pipeline.py 三入口，硬约束） |
| ✅ 新建 `tests/test_project_rerun.py` | ❌ 改 `pipeline.py`（含 `_render_plans`/`_maybe_skip`/PipelineOptions/Engines） |
|  | ❌ 改 `project/__init__.py`（ProjectRun 已 re-export；新方法是成员，无需动） |
|  | ❌ 改 T7 schema/config、T8 create、T9 load、T10 edit |
|  | ❌ 改 `types.py`（CutPoint）/ `stage_*` / `render_gate`（T3）/ `io_`（T1）—— 只 import 复用 |
|  | ❌ 改 `ProjectConfig` / 任何 spec 字段或默认值 |
|  | ❌ 改 manifest schema（schema_version 仍=1；不新增 stage 名；不加 params_hash） |
|  | ❌ reproofread 内部持久化 errata 到 project.yaml/corrections.yaml（Q1 默认 A） |
|  | ❌ 实现 transcript diff 自动算「受影响 clip」（Q3 默认 A，defer） |
|  | ❌ manifest 维护 per-clip stale 标记 / 改 `_maybe_skip` 读 manifest（Q4 默认 A） |
|  | ❌ reproofread 默认重渲全部 clip（Q2 默认 A） |
|  | ❌ 改 render()/proofread() 的对外签名 / 返回值 / manifest 记录内容（仅内部走 helper，Q5 默认 A） |
|  | ❌ 新建/改 `scripts/tesla_*.py`（tesla_refix 退化由 T13 文档化，本任务不碰脚本） |
|  | ❌ 在测试里放真实 tesla 数据 / 真实 clip id（t06/t09）/ 真实 errata（卫生铁律；用 c01/c02 占位） |

---

## 自测方法

1. **可达性**（验收 1）：`python -c "..."` 如上。
2. **rerender 子集 + skip_existing=False**（验收 2/3）：`tmp_path` → cfg 3 条 cut_point（c01/c02/c03，占位 source）→ 写占位 transcript.json → monkeypatch `garden_core.project.run.run_from_transcript` 为捕获入参 + 返回 `[]` 的 fake → `run.rerender(["c01","c03"])` → 断言 `captured.cut_points` 的 clip_id 集合 == `{"c01","c03"}` 且顺序按 cfg（c01 在 c03 前）；`captured.opts.skip_existing is False`；fake 调用计数==1。
3. **rerender 空 / 未知 id**（验收 4/5）：`pytest.raises(ValueError)` / `pytest.raises(ConfigError)`。
4. **reproofread 注入式**（验收 6）：transcribe 落占位 transcript（含「甲」，用 `_make_transcript()` 同 T11 测试 helper）→ `ErrataConfig(flat={"甲":"乙"})` → `run.reproofread(errata=that)` → `load_transcript_json(cfg.transcript.path).segments[0].text` 含「乙」；返回 `[sr]`，`sr.stage=="proofread"`。
5. **reproofread 复用 cfg.errata_path**（验收 7）：写 `corrections.yaml`（`common: {"甲":"乙"}`，格式同 T11 test 验收 4）→ `run.reproofread()` → 同验收 4 断言。
6. **reproofread 不持久化**（验收 8）：验收 4 后读 `project.yaml`（若用 create_project 建的）断言 errata_path 未变；或断言 `run.cfg.errata_path`（frozen）未变（必然，frozen）。
7. **reproofread + rerender_clip_ids**（验收 9）：`run.reproofread(errata=that, rerender_clip_ids=["c01"])` → 返回 `[proofread_sr, render_sr]`；monkeypatch `run_from_transcript` 断言被调一次、cut_points==[c01]、skip_existing False。
8. **render/proofread 零回归**（验收 10）：直接跑 `pytest tests/test_project_run.py -v` 全绿（关键）。额外加一个 spy 测试：spy `run.render()` → manifest params 不含 `rerender` 键（与 T11 一致）。
9. **manifest schema 稳定**（验收 12）：rerender 后 `json.load(manifest)["schema_version"]==1`；`set(stage["stage"] for stage in stages) ⊆ {"transcribe","proofread","render","audit"}`。
10. **resume 在 rerender 后仍正确**（验收 12）：rerender 后新 `run2 = ProjectRun(cfg, engines)` → `run2.resume()` → render 行因 artifact（output_dir）存在而 skipped（与 T11 行为一致）。
11. **diff 范围**（验收 13）：`git diff --name-only` 仅 `project/run.py`（改）+ `tests/test_project_rerun.py`（新增）。
12. **回归**：`pytest tests/ -v` 全绿。
13. **卫生检查**：`grep -rnE "<DATE>|<SRC_FILE>|途材|逗哈|\"t0[0-9]" src/garden_core/project/run.py tests/test_project_rerun.py` 无命中（占位用 c01/c02/c03）。

---

## 风险

- **低（纯增量 + 内部重构）**：T12 只动 `run.py`（加 2 方法 + 抽 2 helper + render/proofread 内部走 helper）+ 新测试。不碰 pipeline 三入口、不碰 T7-T10、不碰 stage_*/io_/render_gate/types。`pytest tests/` 应全绿。
- ⚠️ **render()/proofread() 内部重构须零行为回归**（Q5）：抽 helper 后 render()/proofread() 的对外签名、返回 StageResult、manifest 记录内容（params dict）必须与 T11 逐字一致。**T11 的 `test_project_run.py` 是回归基线**，必须全绿；若有失败说明 helper 抽取引入偏差（如忘了 `_record`、params dict 漏键）。
- ⚠️ **reproofread 不持久化 errata 是有意为之**（Q1）：调用方若期望「reproofread(errata=X) 后下次 proofread() 也用 X」，会落空（下次 proofread() 仍读 cfg.errata_path）。docstring 显式说明「不持久化；要持久化用 edit_project(errata_path=...) 或手写 corrections.yaml」。
- ⚠️ **rerender 的 gate 只跑子集**（已确认）：`_render_plans` 末尾 `gate_results(results)` 只对子集 results 跑 ASS gate，不扫全目录。若其余 clip 的 ass 之前就违规，rerender 不会发现 —— 这是预期（rerender 只对本次重渲的 clip 负责；全目录复审归 `audit()`）。docstring 可提一句「rerender 后建议跑 `audit()` 做全目录复审」。
- ⚠️ **rerender 不删旧产物**：`skip_existing=False` 覆盖写 mp4/ass/srt，但若 cfg 里删了某 clip（不在 cut_points），rerender 不会删 output_dir 里它旧的 mp4（rerender 只处理传入子集）。清理旧产物是调用方/`audit()` 的职责。非本任务范围。
- **依赖 T11 已落地**：T12 建立在 T11 的 `ProjectRun` / `_translate_cut_points` / `_record` / `_resolve_errata_path` / `_render_options_from_cfg` 之上。均已验收，本 brief 假设其冻结。T13（SKILL.md 改写）建立在 T11+T12 之上，本任务不实现。

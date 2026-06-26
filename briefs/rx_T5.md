# RX Brief · T5 — `skip_existing`（朴素跳过已渲染 clip）

> **一句话**：在 `pipeline.py::_render_plans()` 内部、逐 clip 渲染前加一道「输出 mp4 已存在就跳过 ffmpeg」的朴素检查；新增 `PipelineOptions.skip_existing: bool = True`（**默认开**，开箱即用跳过）；被跳过的 clip 不抛异常，照常返回一个指向已存在文件的 `RenderResult`，并在 `metadata` 里打 `skipped=True` 标记。**只改 `pipeline.py` 一个文件。**

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第一层 · 小改 API」→ **T5 · `RenderOptions.skip_existing` —— 选择性重跑（D5：朴素跳过）**。决策依据见末尾「决策点清单」**D5 ✅**。

---

## ⚠️ 执行前必读：Meta-Brief 对 Plan T5 的三处改写（已按 Meta-Brief 执行）

下发的 meta-brief 对 T5 的**实现位置 / 默认值 / 参数归属**做了与 Plan 原文不同的硬性约束。本 brief 一律**按 Meta-Brief**执行（Meta-Brief 是本次下发的最终指令）：

| # | Plan（Ray 已认可）原文 | Meta-Brief（本次下发） | 本 Brief 采用 |
|---|---|---|---|
| L1 | 实现位置 = `stage_render/__init__.py`（`RenderOptions` + `render()` 入口检查） | 实现位置 = `pipeline.py::_render_plans()`，**只改 pipeline.py** | **Meta-Brief** |
| L2 | `skip_existing: bool = False`（默认关，纯新增不破坏） | `skip_existing` 默认 **`True`**（开箱即用跳过） | **Meta-Brief** |
| L3 | 参数挂在 `RenderOptions`（stage_render 层） | 只改 pipeline.py → 参数挂 **`PipelineOptions`**（pipeline 层） | **Meta-Brief** |

> 三处改写的连锁影响见下文「核心目标」与「需人拍板」。**默认全部按 Meta-Brief。** 若人审要回到 Plan 原版（下沉到 stage_render 层、默认 False），需明确改写本 brief 正文。

---

## 核心目标（逐条提炼自 Meta-Brief + Plan T5）

### 1. 新增 `PipelineOptions.skip_existing: bool = True`（`pipeline.py`）

在 `PipelineOptions` dataclass 增加字段：

```python
@dataclass(frozen=True)
class PipelineOptions:
    ...
    render_gate: bool = True
    skip_existing: bool = True   # T5: 朴素跳过已渲染 clip（D5）。默认开——开箱即用跳过
```

- **默认 `True`**（Meta-Brief L2）：重跑 / 纠错重渲场景下，已存在的 clip 不再触发 ffmpeg，省时。
- `frozen=True` dataclass 带默认值 → **非破坏**：现有 `PipelineOptions(...)` 调用点无需改。
- 命名沿用 Plan 原词 `skip_existing`，但归属从 `RenderOptions` 上移到 `PipelineOptions`（Meta-Brief L1/L3）。

### 2. 在 `_render_plans()` 内逐 clip 检查（`pipeline.py`）

现状（`_render_plans` 循环体）：

```python
for plan in plans:
    style = _resolve_style_for(plan, style_name, engines, opts)
    if opts.render is None:
        log.warning("no RenderOptions — skipping render, returning plans only")
        continue
    results.append(render(plan, style, opts.render))
```

改为：渲染前先做**朴素文件存在性检查**——

```python
for plan in plans:
    style = _resolve_style_for(plan, style_name, engines, opts)
    if opts.render is None:
        log.warning("no RenderOptions — skipping render, returning plans only")
        continue

    # T5 (D5): 朴素跳过——输出 mp4 已存在则不重渲。
    if opts.skip_existing:
        skipped = _maybe_skip(plan, opts.render)
        if skipped is not None:
            log.info("skip_existing: %s already rendered — skipping ffmpeg", plan.clip_id)
            results.append(skipped)
            continue

    results.append(render(plan, style, opts.render))
```

新增模块级 helper `_maybe_skip(plan, render_opts) -> Optional[RenderResult]`（同文件内）：

- 计算预期输出路径（**与 `render()` / `ffmpeg_render` 的命名约定严格对齐**）：
  - 横版：`os.path.join(render_opts.output_dir, f"{plan.clip_id}_horizontal.mp4")`
  - 竖版：`os.path.join(render_opts.output_dir, f"{plan.clip_id}_vertical.mp4")`
  - 辅产物（不在「跳过判据」里，仅用于回填 RenderResult 路径）：`{clip_id}.srt` / `{clip_id}.ass` / `{clip_id}_vertical.ass`。
- **跳过判据（朴素，D5）**：仅看 mp4 是否存在——
  - `render_horizontal=True` → 横版 mp4 必须存在；
  - `render_vertical=True` → 竖版 mp4 必须存在；
  - 所有「启用的方向」mp4 都在 → 判定已渲染，返回带这些路径的 `RenderResult`；任一缺失 → 返回 `None`（走正常 render）。
- **返回的 `RenderResult`**（**不改 `RenderResult` 结构**，用现有 `metadata` 标记）：

```python
return RenderResult(
    clip_id=plan.clip_id,
    horizontal_mp4=h_path if render_opts.render_horizontal else "",
    vertical_mp4=v_path if render_opts.render_vertical else "",
    srt_path=<若 {clip_id}.srt 存在则填，否则 "">,
    ass_path=<若 {clip_id}.ass 存在则填，否则 "">,
    metadata={
        "skipped": True,            # T5 跳过标记（用 metadata，不动 RenderResult 字段）
        "style": style_name or plan.style_name,
        "cues": len(plan.cues),
    },
)
```

> `style` / `cues` 沿用 `render()` 现有 `metadata` 形状（见 `stage_render/__init__.py` 末尾），保持一致；`skipped: True` 是 T5 唯一新增键。**被跳过的 clip 不抛异常**（Meta-Brief 明确）。

### 3. 不动的东西（范围红线）

- **不改 `RenderResult` 结构**（Meta-Brief）：用现有 `metadata: dict` 标记 `skipped=True`。
- **不改 `stage_render/__init__.py`**（`RenderOptions` / `render()` 一律不动）。
- **不改 `ffmpeg_render.py` / `ass_writer.py` / `srt_writer.py`**。
- **不改三入口签名**（`run_from_audio` / `run_from_transcript` / `run_montage`）。
- **不改 `render_gate`**。

---

## 需人拍板

### Q1：被跳过的 clip 是否仍过 `render_gate`？

现状 `_render_plans` 末尾：`if opts.render_gate and results: gate_results(results)` —— 对**全部** results（含被跳过的）跑 ASS gate。

| 选项 | 做法 | 影响 |
|---|---|---|
| **A（默认，本 brief 采用）** | 跳过的 clip 也在 `results` 里 → gate 照常对它们跑（读已存在的 `.ass`）。 | 保持现状控制流最少改动；跳过的 clip 若 ASS 有问题仍会被 BLOCK（一致的质量门）。前提：跳过时 `{clip_id}.ass` 存在（已渲染过的目录通常齐全）。 |
| B | gate 跳过 `metadata["skipped"] is True` 的结果。 | 需在 `gate_results` 调用前过滤，或给 gate 加参数——**越出「只改 pipeline.py」红线**（要么改 render_gate.py，要么在 pipeline 里 filter）。 |

> **默认 A**：最小改动，且「跳过 = 信任上次产物」与「仍跑机械 gate 复审」并不矛盾（gate 是只读检查）。若人审要 B，需说明是否放宽红线改 `render_gate.py`。

### Q2：「跳过判据」只看 mp4，还是也看 ASS/SRT？

Meta-Brief 明确：**朴素文件存在性**（`os.path.exists(..._horizontal.mp4)`，竖版同理）。参数哈希 / 完整性校验是 T11 `run_manifest.json` 的事，**不在 T5**。

| 选项 | 做法 |
|---|---|
| **A（默认，本 brief 采用）** | 判据 = 启用方向的 mp4 是否存在。ASS/SRT 缺失不阻止跳过（仅在回填 RenderResult 时按存在性填路径，缺失留空串）。 |
| B | 判据 = mp4 + ASS + SRT 全齐才跳过。 |

> **默认 A**（最朴素，贴合 D5「文件在就跳」）。若人审要 B，把 `_maybe_skip` 的判据加上 ASS/SRT 存在性即可，零额外成本。

### Q3：默认 `True` 对现有调用方 / 测试的影响

Meta-Brief 把默认从 Plan 的 `False` 翻成 `True`。影响评估：

- **生产脚本**（`tesla_stage04.py` / `tesla_refix.py` 等）：重跑场景**正好想要**跳过（`tesla_refix.py` 的存在理由就是没法跳过）→ 默认 True 受益。
- **测试**：现有 `tests/test_render*.py` / `smoke_*.py` 多数在 tmp 空目录起跑，mp4 不存在 → 不会被跳过，行为不变。**但**若有测试依赖「同目录下预置同名 mp4 后仍期望重渲」，需显式传 `PipelineOptions(skip_existing=False)`——见自测方法里的回归检查。
- **`run_montage`**：内部调 `_render_plans`，若某 segment 的横版 mp4 已存在会被跳过 → concat 直接用旧文件，**符合预期**（montage 自身的 `{montage_id}_horizontal.mp4` 不在 _render_plans 跳过范围，不受影响）。

> **默认按 Meta-Brief = True**。执行时需 grep 现有测试是否有「预置 mp4 后重渲」的假设，必要时局部 `skip_existing=False`。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **`_render_plans(plans, style_name, engines, opts)`**（`pipeline.py`）：循环 `for plan in plans` 逐条 `render(plan, style, opts.render)`，末尾 `gate_results(results)`。T5 在循环体顶部插检查、helper 同文件新增 → **只动 pipeline.py**。
- **输出文件命名**（`stage_render/ffmpeg_render.py` L61）：`os.path.join(opts.output_dir, f"{clip.clip_id}_{suffix}.mp4")`，suffix ∈ `{"horizontal", "vertical"}`。ASS：`{clip_id}.ass` / `{clip_id}_vertical.ass`；SRT：`{clip_id}.srt`（见 `stage_render/__init__.py::render`）。`_maybe_skip` 必须与此**逐字对齐**，否则跳过判据会查错文件。
- **`render()` 返回的 `RenderResult.metadata`**（`stage_render/__init__.py` 末尾）：`{"style": style.name, "cues": len(clip.cues)}`。T5 跳过分支沿用此形状 + 加 `"skipped": True`。
- **`RenderResult`**（`types.py` L202-210）：`clip_id / horizontal_mp4 / vertical_mp4 / srt_path / ass_path / metadata: dict`，`frozen=True`。**不动结构**。
- **`RenderOptions`**（`stage_render/__init__.py`）：普通类，字段 `output_dir / render_horizontal / render_vertical / ...`。T5 **不改它**——`_maybe_skip` 只**读** `render_opts.output_dir` / `render_horizontal` / `render_vertical`。
- **`PipelineOptions`**（`pipeline.py`）：`frozen=True` dataclass；加 `skip_existing: bool = True` 是带默认值字段 → 非破坏。
- **`run_montage`** 也走 `_render_plans`（`pipeline.py` L191 `results = _render_plans(plans, ...)`），随后检查 `res.horizontal_mp4` 存在。跳过分支回填的 `horizontal_mp4` 指向已存在文件 → 该检查通过，concat 正常。**无需改 run_montage**。
- **D5 与 T11 的边界**：参数哈希 / manifest 比对是 T11 `run_manifest.json`（`params_hash` 字段）的能力，T5 只做朴素存在性跳过。

---

## 验收标准

1. **跳过生效**：`skip_existing=True` 时，若 `output_dir/{clip_id}_horizontal.mp4`（及竖版，若启用）已存在 → **不调 `render()` / 不触发 ffmpeg**（mock `garden_core.stage_render.render` 计数为 0 对该 clip），返回的 `RenderResult.horizontal_mp4` 指向该已存在文件、`metadata["skipped"] is True`。
2. **不跳过**：`skip_existing=True` 但 mp4 不存在 → 走正常 `render()`，`metadata` 无 `skipped` 键（或 `False`）。
3. **默认行为**：`PipelineOptions()` 不传 `skip_existing` → 默认 `True`（开箱即用跳过）。
4. **显式关闭**：`PipelineOptions(skip_existing=False)` → 行为与改动前**完全一致**（全部 clip 都走 `render()`）。
5. **不抛异常**：被跳过的 clip 照常返回 `RenderResult`，不抛。
6. **结构不变**：`RenderResult` 字段未改；`metadata` 仅多一个 `skipped` 键。
7. **三入口不回归**：`run_from_audio` / `run_from_transcript` / `run_montage` 行为不变（`pytest tests/` 全绿）。
8. **范围**：`git diff --name-only` 仅 `src/garden_core/pipeline.py`（+ 新增测试文件）。

**pytest 命令**：
```bash
pytest tests/test_pipeline_skip_existing.py -v
# 全量回归
pytest tests/ -v
# 范围检查
git diff --name-only
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ `src/garden_core/pipeline.py`（`PipelineOptions.skip_existing` 字段 + `_render_plans` 循环体检查 + 新增 `_maybe_skip` helper） | ❌ `src/garden_core/stage_render/__init__.py`（`RenderOptions` / `render()` 不动） |
| ✅ `tests/test_pipeline_skip_existing.py`（新增） | ❌ `src/garden_core/stage_render/ffmpeg_render.py` |
| ✅ `tests/` 里若有测试因默认翻 True 而需显式 `skip_existing=False`，就地补一行（最小改动） | ❌ `src/garden_core/stage_render/ass_writer.py` / `srt_writer.py` |
|  | ❌ `src/garden_core/types.py`（`RenderResult` 不动） |
|  | ❌ `src/garden_core/stage_render/render_gate.py`（Q1 默认 A 不动它） |
|  | ❌ 三入口 `run_from_audio` / `run_from_transcript` / `run_montage` 签名 |
|  | ❌ `scripts/*.py`（T5 不迁移脚本，tesla_refix 的退化是 T12 的活） |

---

## 自测方法（`tests/test_pipeline_skip_existing.py`，新增）

**不真跑 ffmpeg**——直接 mock `garden_core.stage_render.render`（pipeline 里 `from garden_core.stage_render import render` 的导入点），用 `ClipPlan` + 最小 `RenderOptions` + tmp 目录：

1. **跳过命中**：tmp `output_dir` 预放 `{cid}_horizontal.mp4`（及 `{cid}_vertical.mp4`，当 `render_vertical=True`）→ `_render_plans((plan,), ..., PipelineOptions(skip_existing=True, render=opts))` → 断言：
   - `render` mock **未被调用**（`call_count == 0`）；
   - 返回 1 条 `RenderResult`，`horizontal_mp4` == 预放路径；
   - `metadata["skipped"] is True`。
2. **跳过未命中（mp4 缺）**：空 tmp 目录 → 同上调用 → 断言 `render` mock **被调用 1 次**、返回结果的 `metadata` 无 `skipped`（或 `False`）。
3. **仅横版启用**：`RenderOptions(render_vertical=False)` + 预放横版 mp4（无竖版）→ 跳过生效；mock 未调用。
4. **竖版缺失不跳**：`render_vertical=True`，只预放横版、不放竖版 → `_maybe_skip` 返回 None → 走 `render()`（mock 调用 1 次）。
5. **默认 True**：`PipelineOptions()`（不传 skip_existing）→ `opts.skip_existing is True`。
6. **显式关闭**：`PipelineOptions(skip_existing=False)` + 预放 mp4 → `render` mock **被调用**（不跳过），行为同改动前。
7. **不抛异常**：跳过分支返回的 `RenderResult` 字段齐全（`clip_id` / `horizontal_mp4` / `vertical_mp4` / `srt_path` / `ass_path` / `metadata`），不抛。
8. **命名对齐**：用 `clip_id="t99"` → 预放 `t99_horizontal.mp4` → 跳过；预放成 `t99.mp4`（错误命名）→ 不跳过（验证 `_maybe_skip` 用对了命名约定）。
9. **回归**：`pytest tests/ -v` 全绿（重点看 `test_render*.py` / `smoke_*` 是否因默认翻 True 误跳——这些测试多在 tmp 空目录起跑，mp4 不存在，应不受影响；若有受影响者，就地 `PipelineOptions(skip_existing=False, ...)` 最小修补）。

> mock 注意：`pipeline.py` 顶部是 `from garden_core.stage_render import RenderOptions, render`，所以 patch 目标是 `garden_core.pipeline.render`（已绑入 pipeline 模块命名空间的引用）。

---

## 风险

- **无破坏性（字段层）**：`PipelineOptions.skip_existing` 带默认值 → 现有调用点零改动。
- ⚠️ **默认翻 True 的行为变化（Meta-Brief L2）**：相对 Plan 原文（默认 False），这是**行为默认值翻转**——任何依赖「同名 mp4 存在仍重渲」的调用方/测试需显式 `skip_existing=False`。执行时必须 grep 现有测试确认无误伤（自测 9）。
- **命名约定耦合**：`_maybe_skip` 必须与 `ffmpeg_render.py` / `stage_render/__init__.py` 的文件命名**逐字一致**；若未来命名变了，这里要同步（用单测 8 兜住）。
- **Q1/Q2/Q3 需人拍板**：默认 A / A / True。不拍板按默认走。
- **D5 已定，无悬念**：朴素存在性跳过；参数哈希留 T11。

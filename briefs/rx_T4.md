# RX Brief · T4 — `CutPoint.source_media` 必填（breaking change）+ `source_offset_s`

> **一句话**：把 `CutPoint.source_media` 从 `str = ""` 改为**必填字段（无默认值）**，新增带默认值的 `source_offset_s: float = 0.0`；让 `stage_cut.cut()` 强制用 `cp.source_media` 做 `source_ref` 并按偏移修正时间，并在**同一次执行内**迁移全仓所有 `CutPoint(...)` 构造点 + 改写 `pipeline._prepare_plans` 的覆盖语义 + 更新/新增测试，使仓库一次性进入新契约。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第一层 · 小改 API」→ **T4 · `CutPoint.source_media`（必填）+ `source_offset_s` —— 多源渲染一等公民（D2：breaking）**。决策依据见末尾「决策点清单」**D2 ✅**。

---

## ⚠️ 执行前必读：高风险 breaking，一次执行内必须全闭环

D2 已定：`source_media` **必填**。这意味着改完字段定义后，**任何一处**未迁移的 `CutPoint(...)` 构造点都会在 import / 运行期立即 `TypeError`。**不允许分两次执行**（先改字段、后迁移）——那样会留下不可运行的中间仓库。rx 必须：

1. 先按本 brief 附录的「**全仓构造点清单**」逐个确认，无遗漏。
2. 一次性改完：字段定义 → `cut()` → `_prepare_plans` → 所有构造点 → 测试。
3. 跑 `pytest tests/` 全绿 + `grep "CutPoint(" src/ tests/ scripts/ | grep -v source_media` 零残留。

---

## 核心目标（逐条提炼自 Plan T4）

### 1. 改 `CutPoint` 字段定义（`src/garden_core/types.py`）

新字段布局（**注意 source_media 是位置参 2，紧跟 clip_id**）：

```python
@dataclass(frozen=True)
class CutPoint:
    clip_id: str
    source_media: str        # 必填，无默认值（D2 breaking）
    start_s: float
    end_s: float
    style_name: str = "default"
    title: str = ""
    source_offset_s: float = 0.0   # 带默认值，非破坏；多源时间轴平移用
```

- `source_media` 必填 → 旧式 `CutPoint("x", 0, 10)` 构造期即 `TypeError`（breaking 验证项）。
- `source_offset_s` 带 `0.0` 默认 → 非破坏，仅多源场景填。

### 2. 改 `stage_cut.cut()`（`src/garden_core/stage_cut/__init__.py`）

- `ClipPlan.source_ref` **强制用 `cp.source_media`**（**不再回退 `transcript.source_file`**）。
- 时间偏移：`ClipPlan.start_s = cp.start_s - cp.source_offset_s`，`ClipPlan.end_s = cp.end_s - cp.source_offset_s`（`source_offset_s == 0` 时即原值，单源行为不变）。
- cues 的 rebase 仍相对 `cp.start_s`（剪辑内本地时间），**不变**。
- 这样 `tesla_stage04.py` 里 BATCH2 的「列表推导手算 `start_s - SEG1_END`」整段（L55-58）可删，改用 `source_offset_s=850.0`。

### 3. 改 `pipeline._prepare_plans`（`src/garden_core/pipeline.py` L335-341）

现状：`if opts.source_media: plans = tuple(_replace(p, source_ref=opts.source_media) ...)` ——**无条件覆盖**。

Plan 要求：**仅当 plan 没自带 source_media 时才用 `opts.source_media` 兜底**。改完后，由于 `cut()` 已经把 `cp.source_media` 写进 `source_ref`，`opts.source_media` 只对「CutPoint.source_media 为空」的 plan 生效——**但 source_media 现在必填，永远不会为空**。

> ⚠️ **需要人拍板的语义点（见下文「需人拍板」Q1）**：`PipelineOptions.source_media` 现在事实上变成**死兜底分支**。本 brief 默认处理：**保留 `PipelineOptions.source_media: str = ""` 字段不动**（不改 PipelineOptions 签名，避免扩大 breaking 面），但把覆盖逻辑改成「仅当 `plan.source_ref` 为空时才兜底」（防御性保留）。Q1 给出两种选择，默认选 A。

### 4. 迁移全仓所有 `CutPoint(...)` 构造点（见附录清单）

- **单源脚本**（`smoke_*` / `render_*` / `tesla_refix.py`）：每个 CutPoint 加 `source_media=<对应 SOURCE 常量>`（位置参 2 或 kw）。
- **多源脚本**（`tesla_stage04.py`）：BATCH1 填 `source_media=SRC1`；BATCH2_RAW 直接用（**删掉 BATCH2 列表推导偏移**），改在调 `run_from_transcript` 时让 BATCH2 的 CutPoint 带 `source_offset_s=SEG1_END`（850.0）。最终目标是「一次 `run_from_transcript` 搞定 19 条」——但**注意**：T4 的范围是**字段 + cut() + 迁移**；把 tesla_stage04 双调用合并成单调用属于 T11 的 `run.render()` 范畴。本 brief 只要求 tesla_stage04 的 CutPoint 迁移到新签名、双调用结构保留即可（见「范围红线」）。两个 batch 各自 `source_media` 不同，所以保持两次调用（每次一个 batch）是合理的；关键是 BATCH2 不再手算时间偏移。

### 5. 测试（`tests/`）

- **更新**所有现有 `CutPoint(` 构造点（见附录）补 `source_media`。
- **特别改写 `tests/test_stage_segment.py::test_pipeline_source_media_overrides_source_ref`（L100-119）**：该测试目前断言「`cut()` 后 `source_ref == "transcript.json"`，再用 `opts.source_media` 覆盖」——**这套契约 T4 后失效**（`cut()` 不再用 transcript.source_file）。需改写为：「CutPoint 自带 source_media → `cut()` 后 `source_ref == cp.source_media`」。
- **新增 `tests/test_cut_source_required.py`**：`pytest.raises(TypeError)` 验证 `CutPoint("x", 0, 10)`（缺 source_media）报错。
- **新增 `tests/test_cut_multisource.py`**：两条 CutPoint（SRC1 / SRC2），第二条带 `source_offset_s` → 断言 `ClipPlan.source_ref` 与 start/end 偏移正确（不真渲染）。

---

## 需人拍板

### Q1：`PipelineOptions.source_media` 的归宿

D2 让 `CutPoint.source_media` 必填后，`_prepare_plans` 里「opts.source_media 无条件覆盖」事实上变成不可达分支（每个 plan 都已自带 source_media）。两个选择：

| 选项 | 做法 | 影响 |
|---|---|---|
| **A（默认，本 brief 采用）** | `PipelineOptions.source_media: str = ""` **字段保留不动**；覆盖逻辑改为「仅当 `plan.source_ref` 为空才兜底」（防御性，实际不可达）。 | 不扩大 breaking 面；opts.source_media 变成事实上的死参数，靠 docstring 注明「多源一等公民后已退化为防御性兜底，新代码请用 CutPoint.source_media」。 |
| B | 删除 `PipelineOptions.source_media` 字段 + 删除 `_prepare_plans` 覆盖逻辑。 | 更彻底，但**又一个 breaking**：所有 `PipelineOptions(source_media=...)` 调用点（附录统计：11 处）全要改。越出 T4「只改 CutPoint」红线。 |

> **默认 A**。若人审要 B，需明确放宽红线并补迁移。

### Q2：`tesla_stage04.py` 是否在 T4 合并成单调用

Plan 验收项写了「一次 `run_from_transcript` 产出 19 条」。但那其实是 T11 `run.render()` 的目标（多源翻译在 ProjectRun 里做）。**本 brief 默认 T4 不合并 tesla_stage04 的双调用结构**——只迁移 CutPoint 到新签名 + 用 source_offset_s 取代手算偏移，保留两个 batch 各一次调用（因 SRC1/SRC2 不同）。合并到单调用属 T11。若人审坚持 T4 内合并，需说明「在脚本层手搓 19 条合并 list」是否可接受（可行，但不优雅，留给 T11 更干净）。

---

## 验收标准

1. **breaking 验证**：`CutPoint("x", 0, 10)`（旧式省略 source_media）**构造期即 `TypeError`**（`tests/test_cut_source_required.py` 断言）。
2. **全仓无残留旧式构造**：`grep -rn "CutPoint(" src/ tests/ scripts/ | grep -v source_media` 输出为空（注意 egg-info / 文档见下文「范围红线」排除项）。
3. **多源正确**：`tests/test_cut_multisource.py` 两条带 source_media + source_offset_s 的 CutPoint → `ClipPlan.source_ref` 分别命中 SRC1/SRC2，BATCH2 的 start/end 正确减去 offset。
4. **单源回归**：`run_from_transcript` 单源场景（CutPoint 自带 source_media）产物与改动前一致。
5. **三入口不回归**：`pytest tests/` 全绿；`run_from_audio` / `run_from_transcript` / `run_montage` 行为不变。
6. **tesla 脚本迁移**：`tesla_stage04.py` / `tesla_refix.py` 的 CutPoint 全部用新签名；`tesla_stage04.py` 的 BATCH2 不再手算时间偏移（用 source_offset_s）。
7. **文档示例同步**：`skills/*/references/*.md` + `skills/openclaw/SKILL.md` 里的 `CutPoint(...)` 示例补 source_media（见附录 D 段）。

**pytest 命令**：
```bash
pytest tests/test_stage_segment.py tests/test_cut_source_required.py tests/test_cut_multisource.py -v
# 全量回归
pytest tests/ -v
# 残留检查
grep -rn "CutPoint(" src/ tests/ scripts/ | grep -v source_media
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ `src/garden_core/types.py`（`CutPoint` 字段） | ❌ `src/garden_core/types.py` 其他类型（`ClipPlan` / `RenderResult` / `Cue` 等不动） |
| ✅ `src/garden_core/stage_cut/__init__.py`（`cut()` 用 source_media + offset） | ❌ 三入口 `run_from_audio` / `run_from_transcript` / `run_montage` 的签名（行为通过 _prepare_plans 间接调整） |
| ✅ `src/garden_core/pipeline.py`（仅 `_prepare_plans` 的 source_media 覆盖逻辑；Q1 默认 A：字段保留） | ❌ `PipelineOptions` 字段增删（Q1 默认 A 不动签名） |
| ✅ 全仓所有 `CutPoint(...)` 构造点（附录 A/B/C） | ❌ `src/garden_core.egg-info/PKG-INFO`（**构建产物，勿手改**；它的 CutPoint 来自 README.md，改 README 即可，下次 build 自动重生成） |
| ✅ `tests/` 现有构造点 + 新增两个测试文件 | ❌ `scripts/tesla_stage02.py`（T2/T11 的活） |
| ✅ `skills/*/references/*.md` + `skills/openclaw/SKILL.md` 文档示例 | ❌ `scripts/tesla_gate.py` / `tesla_audit.py`（T3 的活） |
| ✅ `README.md`（L94 那条 CutPoint 示例） | ❌ 把 tesla_stage04 双调用合并成单调用（T11 的活，见 Q2） |

---

## 自测方法

1. **`tests/test_cut_source_required.py`（新增）**：
   - `with pytest.raises(TypeError): CutPoint(clip_id="x", start_s=0, end_s=10)`。
   - `CutPoint("x", "src.mp4", 0, 10)` 正常构造，`source_media == "src.mp4"`。
2. **`tests/test_cut_multisource.py`（新增）**：
   - 两条 CutPoint：`cp1 = CutPoint("a", SRC1, 10, 20)`、`cp2 = CutPoint("b", SRC2, 860, 911, source_offset_s=850.0)`。
   - 构造一个覆盖两者的 cue 集 → `cut(transcript, cues, [cp1, cp2])`。
   - 断言 `plans[0].source_ref == SRC1`、`plans[0].start_s == 10`（offset 0）。
   - 断言 `plans[1].source_ref == SRC2`、`plans[1].start_s == 10`（860-850）、`plans[1].end_s == 61`（911-850）。
   - cues 的 rebase 仍相对原始 `cp.start_s`（语义不变，仅 ClipPlan 的绝对时间被平移到源本地）。
3. **改写 `tests/test_stage_segment.py`**：
   - L76 / L94 / L111 的 CutPoint 补 `source_media`（用测试 transcript 的 source_file）。
   - **重写 `test_pipeline_source_media_overrides_source_ref`（L100-119）**：新契约是「cut() 用 cp.source_media」；若 Q1 选 A，opts.source_media 兜底分支保留但不可达，该测试改为断言「CutPoint 自带 source_media → cut() 后 source_ref == cp.source_media，opts.source_media 不再覆盖」。
4. **回归**：`pytest tests/ -v` 全绿。

---

## 风险

- ⚠️ **breaking change（D2 已定）**：任何遗漏的 `CutPoint(...)` 构造点都会让对应文件 import/运行期 `TypeError`。**必须一次执行内全闭环**，不得分批。
- ⚠️ **`test_pipeline_source_media_overrides_source_ref` 是契约翻转点**：该测试当前断言的旧契约（cut 用 transcript.source_file）在 T4 后失效，**必须改写而非简单补字段**，否则会误绿。
- **Q1 / Q2 需人拍板**：默认 A / 不合并。不拍板按默认走。
- **egg-info / README**：`src/garden_core.egg-info/PKG-INFO` 是构建产物，改 `README.md` L94 即可，勿手改 egg-info。
- 文档示例（skills/*/references）量大但纯文本，迁移机械，无风险。

---

## 附录 · 全仓 `CutPoint(...)` 构造点清单（rx 逐条改）

> 已用 `grep -rn "CutPoint("` 全仓扫描。下表「改法」给迁移指引；`SOURCE`/`SRC1`/`SRC2` 等常量名沿用各文件已定义的变量。

### A. 代码库源码（`src/`）

| 文件 | 行 | 现状 | 改法 |
|---|---|---|---|
| `src/garden_core/types.py` | L111-118 | `CutPoint` 定义 | **改字段定义**（核心目标 1） |

> `src/garden_core/` 内**无**其他 `CutPoint(...)` 构造点（仅 stage_cut / pipeline 引用类型，不构造）。

### B. 脚本（`scripts/`）

| 文件 | 行 | 现状 | 改法 |
|---|---|---|---|
| `scripts/tesla_stage04.py` | L31-43 | BATCH1（t01-t13）13 条 | 每条加 `source_media=SRC1`（位置参 2） |
| `scripts/tesla_stage04.py` | L48-53 | BATCH2_RAW（t14-t19）6 条 | 每条加 `source_media=SRC2` + **改用 `source_offset_s=SEG1_END`（850.0）保留原始时间戳** |
| `scripts/tesla_stage04.py` | L55-58 | BATCH2 列表推导手算偏移 | **删除**（offset 交给 source_offset_s） |
| `scripts/tesla_refix.py` | L24-25 | t06 / t09 两条 | 加 `source_media=SRC1` |

### C. 测试（`tests/`）

| 文件 | 行 | 现状 | 改法 |
|---|---|---|---|
| `tests/test_stage_segment.py` | L76 | `CutPoint(clip_id="c1", start_s=10.0, end_s=20.0)` | 加 `source_media`（用 transcript 的 source_file，如 `t.source_file`） |
| `tests/test_stage_segment.py` | L94 | 同上 | 同上 |
| `tests/test_stage_segment.py` | L111 | 同上 | 同上 |
| `tests/test_stage_segment.py` | L100-119 | **`test_pipeline_source_media_overrides_source_ref` 整个测试** | **重写**（契约翻转，见自测 3）；L116 的 CutPoint 也要加 source_media |
| `tests/smoke_e2e.py` | L49 | `cut_point = CutPoint(...)` | 加 `source_media=<SOURCE 常量>`（查文件顶部 SOURCE 定义） |
| `tests/smoke_full_13.py` | L43 | 列表推导构造 | 加 `source_media=<SOURCE_VIDEO>` |
| `tests/smoke_full_pipeline.py` | L70 | `cut_point = CutPoint(...)` | 加 `source_media=<SOURCE_VIDEO>` |
| `tests/smoke_full_pipeline_local.py` | L72 | 同上 | 加 `source_media=<SOURCE_VIDEO>` |
| `tests/smoke_full_test_comprehensive.py` | L235 | `cut_points = [CutPoint(...)]` | 加 `source_media=<对应 SOURCE>` |
| `tests/smoke_m2.py` | L114 | `cuts = [CutPoint(...)]` | 加 `source_media=<SOURCE_VIDEO>` |
| `tests/smoke_produce_e2e.py` | L30 | `CutPoint(...)` | 加 `source_media=<SOURCE_VIDEO>` |
| `tests/render_fresh_frame.py` | L35 | `cuts = [CutPoint(...)]` | 加 `source_media=<SOURCE>` |
| `tests/render_one_frame_fonttest.py` | L30 | 同上 | 加 `source_media=<SOURCE>` |
| `tests/render_subjectivity.py` | L27 | `cuts = [CutPoint(...)]` | 加 `source_media=<SOURCE>` |

> ⚠️ 这些 smoke/render 脚本目前**同时**传 `PipelineOptions(source_media=...)` 和（迁移后）`CutPoint(source_media=...)`。Q1 选 A 时两者不冲突（opts.source_media 是不可达兜底）。保留两者即可，不要为了「去重」而删 opts.source_media（那是 Q1 选 B 才做的事）。

### D. 文档示例（`skills/` + `README.md`）

| 文件 | 行 | 改法 |
|---|---|---|
| `README.md` | L94 | `CutPoint(...)` 补 `source_media="/path/to/src.mp4"`（占位符，遵守仓库卫生铁律） |
| `skills/openclaw/SKILL.md` | L42 | 同上（占位符） |
| `skills/claude-code/references/garden-core-api.md` | L18, L19, L124 | 同上 |
| `skills/claude-code/references/garden-core-e2e-validation.md` | L23 | 同上 |
| `skills/claude-code/references/multi-source-video-rendering.md` | L17, L20, L22 | **重点改**：多源示例，BATCH2 加 `source_offset_s`，体现新机制 |
| `skills/hermes/references/garden-core-api.md` | L18, L19, L124 | 同 claude-code |
| `skills/hermes/references/garden-core-e2e-validation.md` | L23 | 同上 |
| `skills/hermes/references/multi-source-video-rendering.md` | L17, L20, L22 | 同 claude-code（重点） |
| `skills/openclaw/references/garden-core-api.md` | L18, L19, L124 | 同 claude-code |
| `skills/openclaw/references/garden-core-e2e-validation.md` | L23 | 同上 |
| `skills/openclaw/references/multi-source-video-rendering.md` | L17, L20, L22 | 同 claude-code（重点） |

### E. 排除项（勿改）

| 文件 | 原因 |
|---|---|
| `src/garden_core.egg-info/PKG-INFO` | 构建产物，改 README.md 后下次 build 自动重生成，勿手改 |

---

## 决策依据

- **D2 ✅**：`CutPoint.source_media` 必填（breaking change）。`source_offset_s` 带默认 `0.0`（非破坏）。

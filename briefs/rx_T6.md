# RX Brief · T6 — step API 命名规范化 + 文档化

> **一句话**：确认 7 个 stage 的公开 step 函数命名约定（裸动词 = stage 名），新建 `src/garden_core/steps.py` 把 6 个 step 函数（`transcribe`/`align`/`proofread`/`segment`/`cut`/`render`）集中 re-export 成「step API」，给每个 stage `__init__.py` 补 docstring 标注「step API + `save_/load_transcript_json` 落盘对」，在 `ARCHITECTURE.md`（或 `__init__.py` 顶部）写一张「step API 表」。**不新建函数、不改任何函数签名、不改实现**——纯命名确认 + 文档 + re-export。依赖 T1（`save_transcript_json` 必须已存在，凑齐 save_/load_ 对）。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第一层 · 小改 API」→ **T6 · step API 正式命名 + 文档化**。

---

## ⚠️ 执行前必读：Meta-Brief 前提与代码事实的出入（需人确认）

Meta-Brief 称「当前各 stage 函数名参差不齐（有的叫 `run`、有的叫 `process`、有的叫模块名动词）」。**全仓实测（已 grep `src/garden_core/stage_*/`）否定这一前提**：

- `stage_*/__init__.py` 里**没有任何**叫 `run` / `process` / `execute` / `do_*` / `handle_*` 的公开函数（`grep -rnE "^def (run|process|execute|do_|handle)"` 返回空）。
- 6 个 stage 的公开 step 函数**已经是裸动词**（= stage 名本身）：

| stage 包 | 公开 step 函数 | 现状命名 |
|---|---|---|
| `stage_asr` | `transcribe` | ✅ 裸动词 |
| `stage_align` | `align` | ✅ 裸动词 |
| `stage_proofread` | `proofread` | ✅ 裸动词 |
| `stage_segment` | `segment` | ✅ 裸动词 |
| `stage_cut` | `cut` | ✅ 裸动词 |
| `stage_render` | `render` | ✅ 裸动词 |
| `stage_style` | `resolve_style` | ⚠️ **唯一偏离**——前缀 `resolve_` |

**因此 T6 的实质工作量被 Meta-Brief 高估**：6 个 step 函数命名**已统一**，无需重命名。T6 真正能落地的只有：
1. **统一约定写进文档**（把「裸动词 = step API」从隐式约定变成显式 docstring + step API 表）。
2. **新建 `steps.py` re-export 模块**（Plan 验收标准的硬要求）。
3. **`resolve_style` 的归类决定**（见 Q1）。

> 若人审坚持「真要重命名某些函数」，请明确指名（否则默认**不重命名任何 step 函数**——它们已合规）。

---

## 核心目标

### 1. 新建 `src/garden_core/steps.py`（step API 集中 re-export）

```python
"""Step API — the 6 public pipeline steps, re-exported in one place.

Each step is independently callable and persists its product via the
``save_*`` / ``load_*`` pairs in ``garden_core.io_`` (see step table in
ARCHITECTURE.md). Re-export only — no new functions, no renamed wrappers.

    from garden_core.steps import transcribe, align, proofread, segment, cut, render
"""

from garden_core.stage_asr import transcribe
from garden_core.stage_align import align
from garden_core.stage_proofread import proofread
from garden_core.stage_segment import segment
from garden_core.stage_cut import cut
from garden_core.stage_render import render

__all__ = ["transcribe", "align", "proofread", "segment", "cut", "render"]
```

- **纯 re-export**：`steps.py` 里**不写任何 `def`**，只是 `from stage_x import f` + `__all__`。
- **6 个函数**，与 Plan T6 的 step 表逐字对齐（step1–step6）。
- **不 re-export `resolve_style`**：style 解析是 render step 的内部依赖（pipeline 通过 `engines.style_resolver` 或 `resolve_style` 兜底解析，调用方不直接把它当 step 调）。归类见 Q1。
- 导入路径用 `from garden_core.steps import ...`（Plan 验收标准原文如此）。

### 2. step API 表（写进 `ARCHITECTURE.md`，若不存在则写进 `src/garden_core/__init__.py` docstring）

```
step | 函数              | 来源模块              | 产物                | 落盘对
-----|-------------------|-----------------------|---------------------|------------------------
1    | transcribe(audio, engine, hotwords) -> Transcript            | stage_asr      | Transcript     | save_transcript_json / load_transcript_json (T1)
2    | align(transcript, aligner, audio_path) -> Transcript         | stage_align    | Transcript     | save_transcript_json / load_transcript_json
3    | proofread(transcript, errata, llm, opts, audio_path)         | stage_proofread| Transcript     | save_transcript_json / load_transcript_json
4    | segment(transcript, opts) -> tuple[Cue,...]                  | stage_segment  | tuple[Cue,...] | （无落盘对——Cue 是中间态，直接喂 step5）
5    | cut(transcript, cues, cut_points) -> tuple[ClipPlan,...]     | stage_cut      | tuple[ClipPlan,...] | （同上——直接喂 step6）
6    | render(clip, style, opts) -> RenderResult                    | stage_render   | RenderResult   | RenderResult 字段已是文件路径（mp4/ass/srt）
```

- **落盘对说明**：step1/2/3 的产物都是 `Transcript`，统一用 T1 的 `save_transcript_json` / `load_transcript_json`（**这是 T6 依赖 T1 的原因**）。step4/5 是中间元组，不单独落盘（喂下一步）。step6 的 `RenderResult` 本身就携带产出文件路径。
- **style（stage 6）不在 step API 表里**：见 Q1。

### 3. 各 stage `__init__.py` docstring 标注

给 6 个 step 函数的 docstring 追加一行「Step API」标记。**只改 docstring 字符串，不改函数体 / 签名**。例：

```python
# stage_asr/__init__.py
def transcribe(...):
    """Run stage 1: audio → Transcript (seconds-based, no words yet).

    Step API: part of ``garden_core.steps``. Persist via
    ``save_transcript_json`` / reload via ``load_transcript_json``.
    """
    return engine.transcribe(audio, tuple(hotwords))
```

- 每个函数的 docstring 末尾加 2 行：`Step API: part of garden_core.steps.` + `Persist via save_/load_*` 对（step4/5 写「intermediate tuple, fed to next step, no disk pair」）。
- **不改函数签名、不改返回类型、不改实现**。

### 4. 不动的东西（范围红线）

- **不重命名任何 step 函数**（它们已是裸动词，合规）。
- **不改任何 step 函数签名 / 实现**。
- **不新建 step 函数**（Plan 原文：「不新建函数——命名 + 文档 + re-export」）。
- **不改 `pipeline.py`**（三入口行为不得回归）。
- **不改 `types.py`**。
- **不删 `resolve_style`**（见 Q1 默认 A）。

---

## 需人拍板

### Q1：`resolve_style`（stage_style 的公开函数）算不算 step？

代码事实：pipeline 的 7-stage 设计里，stage 6 = style 解析，stage 7 = render。但 `render(clip, style, opts)` 的签名**已经吃解析好的 `style: StyleDef`**——即 style 解析发生在 render **之前**，由 pipeline 内部 `_resolve_style_for`（用 `engines.style_resolver` 或 `resolve_style` 兜底）完成，**调用方不直接调**。所以：

| 选项 | 做法 | 影响 |
|---|---|---|
| **A（默认，本 brief 采用）** | `resolve_style` **不进 step API**（steps.py 只 6 个函数，与 Plan T6 的 step 表一致）。在 `stage_style/__init__.py` docstring 注明「support helper for step 6 render，非 step API」。 | 与 Plan T6 原文 step 表逐字一致（6 步）。resolve_style 保持现状，pipeline 内部照常用。 |
| B | 把 `resolve_style` 也 re-export 进 steps.py（变成 7 个 step），或重命名为 `style`（裸动词）。 | 与 Plan T6 原文 step 表不符；需同步改 pipeline 里 `from stage_style import resolve_style` 的引用——**越出「纯 re-export」红线**。 |

> **默认 A**：尊重 Plan T6 的 step 表（6 步）+ 「纯 re-export」红线。若人审要把 style 独立成第 7 个 step，需明确允许改 pipeline 导入点。

### Q2：step API 表写哪个文件？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `ARCHITECTURE.md`（若存在）新增「Step API」节；不存在则写进 `src/garden_core/__init__.py` 顶部 docstring。 |
| B | 单独新建 `docs/step_api.md`。 |

> **默认 A**：与现有文档结构贴合（`__init__.py` 顶部已有「See ARCHITECTURE.md / README.md」引用）。执行时先 `ls ARCHITECTURE.md`，存在就追加，不存在就写进 `__init__.py` docstring。

### Q3：`steps.py` 要不要 re-export `Transcript` / `Cue` / `ClipPlan` 等类型？

Plan 验收标准只要求 6 个 step 函数引用可达。类型仍走 `from garden_core.types import ...`（现状）。

> **默认不 re-export 类型**：steps.py 只放 6 个函数，保持单一职责。类型导入路径不变。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **6 个 step 函数命名已统一为裸动词**（见上文表；`grep -rnE "^def (run|process|execute)" src/garden_core/stage_*/` 返回空）。Meta-Brief 的「参差不齐」前提**不成立**——这是本 brief 与 Meta-Brief 的关键出入。
- **各 step 函数签名**（用于 step API 表，已逐字核对 `__init__.py`）：
  - `transcribe(audio: AudioRef, engine: Transcriber, hotwords=()) -> Transcript`（stage_asr L52）
  - `align(transcript, aligner, audio_path) -> Transcript`（stage_align L57，audio_path 是位置参）
  - `proofread(transcript, errata, llm, opts, audio_path="") -> Transcript`（stage_proofread L50）
  - `segment(transcript, opts) -> tuple[Cue,...]`（stage_segment L56）
  - `cut(transcript, cues, cut_points) -> tuple[ClipPlan,...]`（stage_cut L13）
  - `render(clip, style, opts) -> RenderResult`（stage_render L46）
- **`resolve_style`**（stage_style L91）：`resolve_style(style_name, video_height, resolver)`——pipeline 通过 `engines.style_resolver` 或它兜底解析，**不在 step API 列表**（Q1 默认 A）。
- **stage_render docstring 现写「Run stage 7」**（ASS + SRT + mp4）；stage_style resolve_style docstring 写「Run stage 6」。Plan T6 的 step 表把 render 列为 step6（合并了 stage 6+7）——step API 层面的编号与内部 stage 编号不同，文档里需说明（step6 render 内部含 style 解析）。
- **T1 依赖已就绪**：`save_transcript_json`（T1 产物）+ `load_transcript_json`（已存在于 `io_/source.py`）构成 Transcript 的落盘对。若 T1 尚未合并，本 brief 的「落盘对」列需待 T1 落地后再填实（step API 表可先标注「依赖 T1」）。
- **`src/garden_core/__init__.py` 现状**：仅 export `types` + `__version__`，无 step 引用。新增 `steps.py` 不与现有 export 冲突。
- **`pipeline.py` 顶部已有** `from stage_x import ...` 全部 6 个 step + `resolve_style`（L16-22）——steps.py 的 re-export 与之并行，不冲突。

---

## 验收标准

1. **新建 `src/garden_core/steps.py`**：存在；含 6 个 `from garden_core.stage_x import f` + `__all__` 列 6 个名字；**不含任何 `def`**（纯 re-export）。
2. **import 可达**：`python -c "from garden_core.steps import transcribe, align, proofread, segment, cut, render"` 不报错（6 个引用全部可达）。
3. **step API 表存在**：`ARCHITECTURE.md`（或 `__init__.py` docstring）里有一张含 6 行的 step 表（step1–step6 + 函数名 + 来源模块 + 产物 + 落盘对）。
4. **docstring 标注**：6 个 step 函数的 docstring 各含「Step API」+ 落盘对说明（step4/5 写「intermediate tuple」）。
5. **`resolve_style` 归类**：`stage_style/__init__.py` docstring 注明「support helper for step6 render，非 step API」（Q1 默认 A）。
6. **不重命名 / 不改签名 / 不改实现**：`git diff` 对 6 个 stage `__init__.py` 仅 docstring 字符串变更；`steps.py` 是全新文件；`pipeline.py` / `types.py` 零改动。
7. **三入口不回归**：`run_from_audio` / `run_from_transcript` / `run_montage` 行为不变（`pytest tests/` 全绿）。

**pytest / 校验命令**：
```bash
# step API 可达性
python -c "from garden_core.steps import transcribe, align, proofread, segment, cut, render; print('ok')"
# 确认 steps.py 无 def（纯 re-export）
! grep -nE "^\s*def " src/garden_core/steps.py
# 全量回归
pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 steps.py(新增) + ARCHITECTURE.md 或 __init__.py + 6 个 stage __init__.py(docstring)
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ 新建 `src/garden_core/steps.py`（纯 re-export，6 个函数） | ❌ 重命名任何 step 函数（已合规） |
| ✅ 6 个 `stage_*/__init__.py` 的 step 函数 **docstring**（追加 Step API 标注） | ❌ 改任何 step 函数的**签名 / 实现 / 返回类型** |
| ✅ `stage_style/__init__.py` 的 `resolve_style` **docstring**（注明非 step API） | ❌ 删 `resolve_style`（Q1 默认 A 保留） |
| ✅ `ARCHITECTURE.md`（追加 Step API 节）或 `src/garden_core/__init__.py` docstring（写 step 表） | ❌ `src/garden_core/pipeline.py`（三入口不得回归） |
|  | ❌ `src/garden_core/types.py` |
|  | ❌ 在 `steps.py` 里 re-export 类型（Q3 默认不） |
|  | ❌ 在 `steps.py` 里写任何 `def`（包装器 / 别名） |
|  | ❌ `scripts/*.py`（T6 不碰脚本） |

---

## 自测方法

1. **可达性**（验收 2）：`python -c "from garden_core.steps import transcribe, align, proofread, segment, cut, render"` 输出 ok。
2. **纯 re-export**（验收 1）：`grep -nE "^\s*def " src/garden_core/steps.py` 无输出。
3. **__all__ 完整**：`python -c "import garden_core.steps as s; assert set(s.__all__)=={'transcribe','align','proofread','segment','cut','render'}"`。
4. **引用一致**：`python -c "from garden_core.steps import render as a; from garden_core.stage_render import render as b; assert a is b"`（确认是 re-export 不是副本，6 个函数各验一次）。
5. **docstring 标注落地**：对 6 个 stage `__init__.py`，`grep -n "Step API" src/garden_core/stage_*/__init__.py` 每个文件至少 1 命中；`stage_style/__init__.py` 含「非 step API」或「support helper」字样。
6. **step API 表存在**：`grep -nE "step.*(transcribe|align|proofread|segment|cut|render)" ARCHITECTURE.md`（或 `__init__.py`）有命中。
7. **diff 范围**：`git diff --name-only` 仅含 `steps.py`(新增) + `ARCHITECTURE.md`(或 `__init__.py`) + 6 个 stage `__init__.py` + `stage_style/__init__.py`；`pipeline.py` / `types.py` 不在列表。
8. **回归**：`pytest tests/ -v` 全绿（T6 是纯文档/re-export，不应有任何测试失败；若失败说明误改了函数体）。

---

## 风险

- **无破坏性**：纯 re-export + docstring + 文档；不改任何函数签名 / 实现 / 类型。
- ⚠️ **Meta-Brief 前提与代码事实不符**（见「执行前必读」）：Meta-Brief 假设「函数名参差不齐需重命名」，实测 6 个 step 已统一为裸动词。**默认不重命名**；若人审坚持重命名，需明确指名 + 放宽红线（同步改 pipeline 导入点）。
- **T1 依赖**：step API 表的「落盘对」列依赖 T1 的 `save_transcript_json` 已落地。若 T1 未合并，本 brief 的 step 表可先标注「Transcript 落盘对 = save_transcript_json（T1）/ load_transcript_json」，待 T1 合并后填实。
- **Q1/Q2/Q3 需人拍板**：默认 A / A / 不 re-export 类型。不拍板按默认走。
- **stage 编号 vs step 编号的混淆**：内部「stage 6 style / stage 7 render」与 step API「step6 render」编号不同，文档需一句说明（step6 render 内部含 style 解析），避免读者困惑。

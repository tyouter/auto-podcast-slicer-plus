# RX Brief · T13 — 文档收尾（ARCHITECTURE.md / README.md / scripts 清理）

> **一句话**：T1–T12 已全部落地（项目管理系统 `src/garden_core/project/` + 第一层 API 全部就位，302 个测试）。本任务收尾**纯文档**：① 把「项目管理 API（T7–T12）」补进 `ARCHITECTURE.md`；② 在 `README.md` 加一段 `project.yaml` 快速上手；③ 删除已被 `ProjectRun` 取代的 `scripts/tesla_*.py`（4 个，`tesla_audit.py` 已不存在）。可选 ④ 更新三平台 skill reference。**零代码改动、零测试改动**，只动 markdown + 删脚本。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「T13 · SKILL.md「投产标准流程」改写」节 + 末尾「端到端验收」退化目标表。

> ⚠️ **Meta-Brief 范围说明**：Plan 原文 T13 主体是「改写 `skills/hermes/SKILL.md` 投产标准流程」。本 Meta-Brief 把范围**收窄**为「库级文档收尾（ARCHITECTURE + README + 清脚本）」，SKILL.md 的全面改写 + `project-directory-template.md` 翻转留作后续独立任务（见文末「明确不在本任务范围」）。理由：SKILL.md 改写量大且与人审强耦合，宜单独成任务；本任务先把「库对外两张脸（ARCHITECTURE / README）」和「仓库卫生（废脚本）」收口，让第二层成果可被发现。若人审要求本任务一并改 SKILL.md，请在「人审待决」栏打勾后扩展范围。

---

## 代码事实（已读真实代码，非凭摘要）

### 项目管理系统现状（T7–T12 产物，全部已落地）

`src/garden_core/project/` 模块公开面（`from garden_core.project import …`）：

| 符号 | 来源 | 作用 | Plan 任务 |
|---|---|---|---|
| `ProjectConfig` / `validate` | `config.py` | 顶层 project.yaml 数据模型 + 结构/引用校验（6 类检查，不碰文件系统） | T7 |
| `ProjectMeta` / `SourceSpec` / `CutPointSpec` / `RenderOptsSpec` / `ProofOptsSpec` / `TranscriptSpec` | `schema.py` | frozen spec 值对象（每类 `from_dict`/`to_dict` 往返） | T7 |
| `create_project(name, root_dir, *, sources, ...)` | `create.py` | 建目录树（output/clips,fullcut,release + source + 可选 Wiki）+ 写 project.yaml + corrections.yaml + AGENTS.md/README.md，返回已校验 `ProjectConfig` | T8 |
| `load_project(path, *, strict=True)` | `load.py` | 接受 yaml 文件路径或根目录 → 解析所有相对路径到绝对 → `validate()` → 可选 strict 文件存在性检查；返回「runtime view」config | T9 |
| `edit_project(root_dir, /, **overrides)` | `edit.py` | config-view 读取 → 字段级覆盖（标量/嵌套spec部分合并/集合替换）→ 再 `validate()` → 原子写回 project.yaml | T10 |
| `ProjectRun(cfg, engines)` | `run.py` | 运行编排器；每 stage 产一份产物 + 写 `<root>/run_manifest.json`（`schema_version=1`） | T11 |
| `ProjectRun.from_project_dir(dir, engines, *, strict=False)` | `run.py` | 一行 load+run | T11 |
| `ProjectRun.load(manifest_path, engines)` | `run.py` | 从旧 manifest 重建 run（校验 schema_version==1）→ 可 `.resume()` | T11 |
| `run.transcribe() / proofread() / render() / audit()` | `run.py` | 四个分阶段方法，各返回 `StageResult` | T11 |
| `run.all()` | `run.py` | 全跑（幂等覆盖，无视 manifest） | T11 |
| `run.resume()` | `run.py` | 跳过 manifest 标 done 且产物存在的 stage（D5 朴素跳过） | T11 |
| `run.reproofread(errata=None, *, rerender_clip_ids=None)` | `run.py` | 增量纠错（可注入临时 ErrataConfig 不落盘）+ 可选指定 clip 重渲 | T12 |
| `run.rerender(clip_ids)` | `run.py` | 仅重渲指定 clip（`skip_existing=False` 覆盖），不重跑转录/纠错 | T12 |

**多源翻译核心机制**（让手写多源批脚本 obsolete）：`cfg.cut_points`（`CutPointSpec`：全局时间轴 + `source` id）→ `ProjectRun._translate_cut_points()` → `types.CutPoint`（解析后的 `source_media` 绝对路径 + `source_offset_s`）。一次 `run.render()` 替代 `tesla_stage04.py` 的 BATCH1/BATCH2。

### manifest 形态（`<root>/run_manifest.json`，D6）

```json
{
  "schema_version": 1,
  "project": {"name": "...", "root": "..."},
  "updated": "<iso8601>",
  "stages": [
    {"stage": "transcribe", "status": "done", "artifact_path": "...",
     "params": {...}, "started": "...", "finished": "..."},
    ...
  ]
}
```

### 第一层 API（T1–T5，也已在代码就位，文档里顺带提一句即可）

- `save_transcript_json(transcript, path)` — `io_/sink.py`（T1，与 `load_transcript_json` 对称）。
- `Engines.from_env(env_path=None)` — `pipeline.py`（T2，D3：路径调用方传，None 读 `os.environ`）。
- `audit_dir(...)` — `stage_render/render_gate.py`（T3，D4：合并 ffprobe 机械校验，目录复审；`tesla_audit.py` 因此整个消失）。
- `CutPoint.source_media` 必填（T4，D2，唯一 breaking，已全仓迁移）。
- `RenderOptions(skip_existing=...)`（T5，D5：朴素文件存在性跳过，默认 False）。

### 要删除的 scripts（已被 ProjectRun 取代）

| 脚本 | 现状取代物 | 判据 |
|---|---|---|
| `scripts/tesla_gate.py` | `run.audit()`（T3+T11，D4 合并 ffprobe + ASS gate 到 `audit_dir`） | Plan 端到端验收退化目标表第 1 行：`tesla_gate.py → run.audit()` |
| `scripts/tesla_refix.py` | `run.rerender(clip_ids=[...])`（T12） | 退化目标表第 3 行 |
| `scripts/tesla_stage04.py` | `run.render()`（T4+T11，多源翻译） | 退化目标表第 4 行 |
| `scripts/tesla_stage02.py` | `run.transcribe()` + `run.proofread()`（T11） | 退化目标表第 5 行 |

> `scripts/tesla_audit.py` **已不存在**（git status 显示 scripts/ 下只有这 4 个 tesla 脚本 + `check_env.py` + `run_garden.bat`）。Plan 验收目标「tesla_audit.py → 删除」已天然满足。
>
> **保留** `scripts/check_env.py` 和 `scripts/run_garden.bat`：前者是环境自检（无关项目系统），后者是 garden env DLL/ffmpeg PATH wrapper（SKILL.md「garden 全链启动铁律」仍依赖它），都不属于「被取代的 tesla 脚本」。

### 三平台 skill reference 现状（影响「可选」范围）

- `skills/hermes/references/`、`skills/claude-code/references/`、`skills/openclaw/references/` **内容完全相同**（实测 `diff` 三方零差异）。任一改动需同步复制到另外两份（或建脚本同步——本任务**不建**同步脚本，手动复制）。
- `project-directory-template.md` 当前明确写着「**⚠️ 项目配置层（取代 project.yaml）… garden_core 是纯 Python 库，不依赖 project.yaml**」——**与 D1 已定结论（project.yaml 是一等公民）直接矛盾**。这是后续 SKILL.md 改写任务的硬考点。
- 项目管理 API（`ProjectConfig`/`ProjectRun`/`create_project`/`load_project`/`rerender`/`reproofread`）**目前没有任何 reference 文档**（grep 全仓零命中）。
- 入口文件三平台不同（hermes=SKILL.md 详尽中文 / claude-code=CLAUDE.md 极简英文 / openclaw=SKILL.md 极简英文），但本任务**不动入口文件**。

### 文档现状

- `ARCHITECTURE.md`（6910B）：目前只描述第一层 7-stage + problem→fix 表，**完全没提** project 管理系统；末尾「Verification」段写「80 unit tests」，实际已 **302 个测试**。
- `README.md`（6233B）：Quick start 段是手写 `CutPoint(...)` + `run_from_transcript(...)` 的旧范式，**没有** `project.yaml` / `create_project` / `ProjectRun` 任何示例；「Skills」表仍把三平台当「clone-and-use skill」描述（这部分不变）。

---

## 核心目标

### 1. 更新 `ARCHITECTURE.md` —— 加入「项目管理 API（T7–T12）」章节

**新增一节**（建议放在「## Step API」之后、「## Problem → fix map」之前），标题如 `## Project management layer (T7–T12)`，内容：

1. **一句定位**：「`garden_core.project` is an optional orchestration layer on top of the step API. It makes a *project* a first-class citizen (D1): a `project.yaml` + a directory tree, so an agent never hand-rolls a transcribe/render script.」明确这是**可选层**，不破坏三入口零回归（AGENTS.md 铁律：不改 `run_from_audio`/`run_from_transcript`/`run_montage` 行为）。

2. **公开 API 表**（直接抄本 brief「代码事实」第一张表，精简成 markdown 表）：列 `create_project` / `load_project` / `edit_project` / `ProjectRun.{from_project_dir,load,transcribe,proofread,render,audit,all,resume,rerender,reproofread}` 一行说明 + 所属任务号。

3. **`project.yaml` 一等公民（D1）**：点明三处分散配置（旧：style yaml + corrections.yaml + Python 入口脚本直传 dataclass）合并为 `project.yaml` + `corrections.yaml` + style yaml；schema 权威参考指向 `schema/project.schema.yaml`。

4. **多源翻译机制**：`CutPointSpec（全局时间轴 + source id）→ _translate_cut_points() → CutPoint（source_media 绝对路径 + source_offset_s）`，一次 `run.render()` 替代手写多源批脚本。

5. **`run_manifest.json`（D6）**：`schema_version=1`，每 stage 一行（status/artifact_path/params/started/finished）；`resume()` 据此跳过（D5 朴素：status==done 且 artifact 存在）；`ProjectRun.load(manifest)` 重建 run 续跑。

6. **设计约束（硬）**（抄自 `run.py` 顶部 docstring）：「不改三入口 / 不改任何 stage_*、io_*、render_gate、types 模块 / 不改 T7–T10 project 模块 / manifest 非并发安全（单机串行假设）」。

**更新现有段落**：
- **Verification 段**：把「80 unit tests pass」改为「302 unit tests pass（`pytest tests/`）」，并补一句「包括 7 个 project 管理系统测试（`test_project_config/validate/create/load/edit/run/rerun`）」。
- **「What's out of scope」段**：把原「watcher / HTTP-service layer is a future layer」补一句「`garden_core.project` 是库内编排层，仍是 library；不引入 watcher/server」。

**保持不变**：7-stage 图、Step API 表、Problem→fix map、Design principles、hard quality rule、out of scope 其余项。**surgical changes only**（AGENTS.md 铁律 3）。

### 2. 更新 `README.md` —— 加 `project.yaml` 快速上手段

在现有「## Quick start」**之后**新增一节 `## Quick start (project.yaml)`（不删现有手写 `CutPoint` 段——它仍是最贴近 step API 的最小示例，保留）：

- 一段简述：T7–T12 引入了 `garden_core.project`，把项目做成一等公民（`project.yaml`），免手写 transcribe/render 脚本。
- **示例 1：建项目**（最小占位数据，遵守 AGENTS.md 示例数据卫生——用 `<...>` / `/path/to/` 占位，**绝不出现真实路径**）：

```python
from garden_core.project import create_project, SourceSpec, ProjectRun
from garden_core.pipeline import Engines
from garden_core.stage_asr import FunASRLocal
from garden_core.stage_align.mms_aligner import MMSAligner

cfg = create_project(
    name="<project-name>",
    root_dir="/path/to/project",
    sources=[SourceSpec(id="<src-1>", path="/path/to/source.mp4")],
    audio_path="source/<name>.wav",
    style="fresh",
)
# → 写出 /path/to/project/{project.yaml, corrections.yaml, source/, output/...}
```

- **示例 2：全链运行**：

```python
run = ProjectRun.from_project_dir(
    "/path/to/project",
    Engines(transcriber=FunASRLocal(device="cuda"),
            aligner=MMSAligner(...), llm=...),
)
run.transcribe()   # 人审 transcript → 编辑 corrections.yaml → 再 proofread
run.proofread()
run.render()
run.audit()
# 或一行： run.all()
```

- **示例 3：增量重跑**：

```python
run.rerender(["<clip-id-1>", "<clip-id-3>"])          # 只重渲这两条
run.reproofread(rerender_clip_ids=["<clip-id-1>"])     # 增量纠错 + 自动重渲
```

- 末尾一句指向：schema 权威参考 `schema/project.schema.yaml`；完整架构见 `ARCHITECTURE.md` 的「Project management layer」。

**数据卫生硬约束**（AGENTS.md 铁律）：示例里**所有路径、项目名、clip id 必须是 `<...>` / `/path/to/...` 占位符**。不得出现 `N:\`、`tesla`、`t06` 等任何真实项目痕迹。

### 3. 删除 `scripts/tesla_*.py`（4 个，仓库卫生）

```bash
git rm scripts/tesla_gate.py scripts/tesla_refix.py scripts/tesla_stage02.py scripts/tesla_stage04.py
```

- 删除前**全仓 grep** 确认无其他文件 import / 引用这 4 个脚本（预期只在 git 历史、`.rx_*.md` 备忘、本 brief 出现）。若有 README/SKILL 文档提到，一并在文档里删掉对应引用（surgical）。
- ⚠️ **AGENTS.md 铁律：不做任何 git 操作**。本任务只 `rm`（删除工作区文件），git add/commit 留给人审。Brief 里写 `git rm` 仅为语义说明，执行用 `rm` 或工作区删除工具。

**删除理由写进本 brief 的执行回执**（给审计人看）：每个脚本对应哪个 `run.*()` 取代（抄退化目标表）。

### 4.（可选）更新三平台 skill reference

> 人审决定是否纳入本任务。**若纳入**，范围如下；**若不纳入**，留作「明确不在本任务范围」。

**最小改动**（推荐）：新增一份 `references/project-management.md`（hermes 版中文为主、claude-code/openclaw 版可英文，或三份都用同一份中文——三平台 reference 现状是逐字相同的，保持一致即可），内容 = 本 brief「代码事实」第一张 API 表 + project.yaml 一等公民说明 + manifest 说明 + 多源翻译说明。**不改 `project-directory-template.md`**（它的 D1 翻转属于 SKILL.md 改写任务，见下）。

**同步机制**：手写一份，`cp` 到 `skills/{hermes,claude-code,openclaw}/references/project-management.md`（三平台 reference 现状逐字相同，保持惯例）。

---

## 明确不在本任务范围

1. **`skills/hermes/SKILL.md`「投产标准流程」全面改写**（Plan T13 主体）——SKILL.md 里「项目准备：garden_core 纯 API 不依赖 project.yaml」「重渲省时」「多源陷阱」「直接 import 调 stage 函数拼脚本」等打补丁段落需要逐段用项目管理 API 重写，量大且与人审强耦合，**单列后续任务**。
2. **`references/project-directory-template.md` 的 D1 翻转**（把「⚠️ 项目配置层（取代 project.yaml）… 不依赖 project.yaml」整段改为「project.yaml 是一等公民」）——同属 SKILL.md 改写任务，因为该 template 是 SKILL.md 投产流程的依赖物，二者必须同批翻转否则文档自相矛盾。
3. **三平台入口文件差异**（hermes 详尽中文 vs claude/openclaw 极简英文）——本任务不动入口文件。
4. **建 reference 同步脚本**（三平台逐字复制目前靠手动）——不引入新工具链。
5. **任何代码改动**（AGENTS.md：本任务是文档收尾，零代码 / 零测试改动）。

---

## 验收标准

1. **ARCHITECTURE.md**：新增「Project management layer (T7–T12)」节，含 API 表 + D1/D5/D6 说明 + 多源翻译 + manifest + 设计约束；Verification 段测试数从 80 → 302（含 7 个 project 测试）。`pytest tests/` 仍全绿（文档改动不影响测试，但跑一遍确认无 import 副作用）。
2. **README.md**：新增「Quick start (project.yaml)」节，含建项目 / 全链 / 增量重跑三例；所有数据为 `<...>`/`/path/to/` 占位符（grep 实测无 `tesla`/`N:\\`/`t06` 等真实痕迹）。
3. **scripts/**：`tesla_gate.py`/`tesla_refix.py`/`tesla_stage02.py`/`tesla_stage04.py` 已从工作区删除；`check_env.py`、`run_garden.bat` 保留；全仓 grep 确认无残留引用。
4. **（若纳入可选 4）** `skills/{hermes,claude-code,openclaw}/references/project-management.md` 三份新增且逐字相同。
5. **零回归**：三入口冒烟不动（无代码改动）；ARCHITECTURE.md / README.md 其余段落字节级不变（surgical）。

## 自测方法

1. `pytest tests/` 全绿（302 passed）—— 纯文档，不应有任何变化，跑一遍是铁律确认。
2. 全仓 grep 验证删除干净：
   ```bash
   ls scripts/  # 应只见 check_env.py、run_garden.bat
   grep -rn "tesla_gate\|tesla_refix\|tesla_stage0[24]" --include="*.md" --include="*.py" .
   # 预期：仅本 brief (briefs/rx_T13.md) + .rx_*.md 备忘命中，无活文档/活代码引用
   ```
3. 数据卫生 grep（README 示例）：
   ```bash
   grep -nE "N:\\\\|tesla|t0[0-9]\b" README.md  # 预期 0 命中
   ```
4. 人工通读 ARCHITECTURE.md「Project management layer」节，确认 API 表符号名与 `src/garden_core/project/__init__.py` 的 `__all__` 逐字一致。

## 风险

- **低**。纯文档 + 删脚本，无代码/测试改动。
- **唯一注意点**：README 示例数据卫生（AGENTS.md 铁律）——若不慎写入真实项目路径/clip id，违反「真实项目数据不得进仓库」。执行后必须 grep 验证。
- 删脚本前 grep 确认无活引用，避免误删仍被文档/CI 引用的脚本（预期无，但 surgical 原则要求确认）。

---

## 人审待决（执行前请勾选）

- [ ] 可选范围 4（三平台 reference 新增 `project-management.md`）：**纳入** / **不纳入**（默认不纳入，留后续 SKILL.md 改写任务）。
- [ ] 若人审坚持本任务一并翻转 `project-directory-template.md` 的 D1 矛盾段，请在「明确不在本任务范围」第 2 项打叉并把它移入核心目标。

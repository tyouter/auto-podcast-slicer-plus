# RX Brief · T7 — `project.yaml` schema + `ProjectConfig` 数据形状 + 校验

> **一句话**：新建 `src/garden_core/project/` 包（`schema.py` / `config.py`），定义 `project.yaml` 的完整 schema（一份带注释的 `schema/project.schema.yaml` 规范 + 一份 `references/project.example.yaml` 示例），落地一组 `@dataclass(frozen=True)` 的 spec 类型（`ProjectMeta` / `SourceSpec` / `CutPointSpec` / `RenderOptsSpec` / `ProofOptsSpec` / `TranscriptSpec` / `ProjectConfig`），提供 `from_dict` / `to_dict` / `from_yaml` / `to_yaml` 往返 + `validate(cfg) -> None`（raise `ConfigError`）。**这是 T8–T11 的硬前置**——schema 一旦定下，create/load/edit/run 全部围着它转。无破坏性（纯新模块），但形状必须一次定对。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第二层 · 项目管理系统」→ **T7 · `project.yaml` schema 定义 + `ProjectConfig` 数据形状 + 校验**（D1：YAML + 完整项目管理）。

---

## ⚠️ 执行前必读：Meta-Brief 与 Plan/代码的三处出入（需人确认）

Meta-Brief 标题写的是「**ProjectRun** 数据类」，但对照 Plan T7 原文 + 代码事实，有出入。**默认按 Plan/代码走，不按 Meta-Brief 字面走**：

### 出入 1：T7 的数据类叫 `ProjectConfig`，不是 `ProjectRun`

- **Plan T7 原文**（L237 / L271）：「定义 `ProjectConfig` 数据类（`@dataclass(frozen=True)`）」+ 「`ProjectConfig(meta, sources, transcript, errata_path, proof_opts, cut_points, style_name, render_opts, output_dir)`」。
- **`ProjectRun` 是 T11 的产物**（L413：「`ProjectRun(cfg: ProjectConfig, engines: Engines)`：持有 config + engines，提供分阶段方法」）——它**不是 dataclass**，是一个持有运行状态的 runner 类，且依赖 T1–T5 + T9 才能实现。
- Meta-Brief 描述的「字段覆盖：项目元信息、源媒体、转录路径、风格配置、clip 定义、渲染参数」**正是 `ProjectConfig` 的字段**（Plan L271 逐字对应）。
- **结论**：T7 交付 `ProjectConfig`（frozen dataclass）。`ProjectRun` 留给 T11，本任务**不建**。

### 出入 2：`schema_version`（D6）属于 T11 的 `run_manifest.json`，不属于 T7 的 `project.yaml`

- **D6 决策原文**（L510 / L424）：「`run_manifest.json` 顶层带 `schema_version`（=1），load 时校验」——绑在 **run manifest** 上，不是 project.yaml。
- Plan T7 的 `project.yaml` schema 示例（L241–271）**没有 `schema_version` 字段**。
- **结论**：T7 的 `project.yaml` **不加 `schema_version`**。若人审坚持要给 project.yaml 也加版本号，见 Q3（默认不加）。

### 出入 3：Meta-Brief 指定的产物文件名 `schema/project.schema.yaml` 与 Plan 不完全一致

- Plan T7 原文（L239）：「新建 `src/garden_core/project/__init__.py`（或 `project.py`，建议拆成子模块包：`schema.py` / `config.py`）」+「一份示例 `project.example.yaml` 放 `references/`」。
- Plan **没有**单独要求一个 `schema/project.schema.yaml` JSON Schema 文件——schema 形状由 `ProjectConfig.from_dict` 的字段契约 + 注释规范表达。
- Meta-Brief 额外要求「`schema/project.schema.yaml`（JSON Schema 或 YAML 注释规范）」。
- **结论**：默认按 Meta-Brief 多做一步——产出 `schema/project.schema.yaml`（带注释的 YAML 规范文档，**不是**运行时 JSON Schema 校验器；运行时校验全靠 `validate()`）。理由：给 T8–T13 + agent 一个单一权威 schema 参考点，成本低、收益高。见 Q2。

> 若人审对以上三点有异议，请在开工前拍板；否则按上述默认走。

---

## 核心目标

### 1. 新建 `src/garden_core/project/` 包

```
src/garden_core/project/
├── __init__.py      # re-export: ProjectConfig + 所有 spec + validate
├── schema.py        # spec 数据类（frozen dataclass）+ from_dict/to_dict
└── config.py        # ProjectConfig 主体 + from_yaml/to_yaml + validate()
```

- 拆包理由：spec 类型（纯数据形状）与 `ProjectConfig` + `validate`（含校验逻辑）职责不同，分开便于 T8/T9/T10 各自 import 子集而不引入循环。
- `__init__.py` re-export 全部公开符号，调用方写 `from garden_core.project import ProjectConfig, validate, SourceSpec, ...`。

### 2. spec 数据类清单（全部 `@dataclass(frozen=True)`，与 `types.py` 风格一致）

> 时间单位铁律继承自 `types.py`：**所有 `_s` 字段是秒（float）**。

#### `ProjectMeta`
```python
@dataclass(frozen=True)
class ProjectMeta:
    name: str                 # 项目名，如 "tesla-<DATE>"
    root: str                 # 项目根目录（绝对路径或待解析的相对路径）
```

#### `SourceSpec`（沉淀 tesla_stage04 的 SRC1/SRC2 + SEG1_END 偏移逻辑）
```python
@dataclass(frozen=True)
class SourceSpec:
    id: str                   # "SRC1" / "SRC2" —— cut_points 引用此 id（多源一等公民）
    path: str                 # 源媒体路径（相对 meta.root 或绝对）
    timeline_start_s: float = 0.0   # 该源在【原始时间轴】上的起点
    timeline_end_s: float | None = None  # 该源在原始时间轴上的终点（None=未限定）
    source_offset_s: float = 0.0    # 翻译到源本地时间的偏移（与 types.CutPoint.source_offset_s 同义，T11 透传）
```
- **关键事实**：`source_offset_s` 与 `types.CutPoint.source_offset_s`（types.py L150，已存在，默认 0.0）**同义**。tesla_stage04 的 `SEG1_END=850.0` 就是 SRC2 的 `source_offset_s=850` + `timeline_start_s=850`。本字段把那段手搓逻辑沉淀成数据。

#### `CutPointSpec`（原始时间轴上的 clip 定义；编排器负责翻译到每段源）
```python
@dataclass(frozen=True)
class CutPointSpec:
    clip_id: str              # "t01"
    source: str               # 引用 sources[].id（多源一等公民；YAML key 叫 source）
    start_s: float            # 原始时间轴起点（秒）
    end_s: float              # 原始时间轴终点（秒）
    style_name: str = "default"
    title: str = ""
```
- ⚠️ **命名注意**：YAML 里 key 叫 `source`（引用 source id），dataclass 字段也叫 `source`（与 Plan L256 示例 `source: SRC1` 一致）。Plan 正文 L271 写的是 `source_id`，但 Plan 的 yaml 示例 L256 写的是 `source`——**以 yaml 示例为准，字段名 `source`**（避免 from_dict/to_dict 往返时 key 不一致）。
- ⚠️ **与 `types.CutPoint` 的区别**：`CutPointSpec` 是**项目配置层**（原始时间轴 + 引用 source id）；`types.CutPoint`（types.py L138）是**运行时层**（已翻译成具体 `source_media` 绝对路径 + `source_offset_s`）。T11 的「多源翻译」负责 `CutPointSpec → CutPoint`。**T7 不做翻译，只定义 spec。**

#### `RenderOptsSpec`（frozen 版本的 `stage_render.RenderOptions`）
```python
@dataclass(frozen=True)
class RenderOptsSpec:
    output_dir: str                       # 相对 meta.root（如 "output/clips"）
    horizontal_width: int = 1920
    horizontal_height: int = 1080
    vertical_width: int = 1080
    vertical_height: int = 1920
    crf: int = 18
    render_horizontal: bool = True
    render_vertical: bool = True
```
- **关键事实**：现有 `stage_render.RenderOptions`（stage_render/__init__.py L22）是**普通 class（非 frozen dataclass）**，字段默认值与上述一致（vertical 1080×1920 / horizontal 1920×1080 / crf 18）。T7 引入 `RenderOptsSpec`（frozen）作为配置层；T11 运行时把 `RenderOptsSpec` 转成 `RenderOptions`（`RenderOptions(**asdict(spec))` 之类）。**T7 不改 `RenderOptions`**。
- tesla_stage04 用的非默认值是 `horizontal_width=3840, horizontal_height=2160, crf=20`（4K + crf 20）——schema 必须能表达这些覆盖。

#### `ProofOptsSpec`（`stage_proofread.ProofOptions` 的配置层镜像）
```python
@dataclass(frozen=True)
class ProofOptsSpec:
    enable_normalize: bool = True
    enable_errata: bool = True
    enable_phonetic: bool = True
    enable_llm: bool = False
    enable_dual_channel: bool = True
    llm_temperature: float = 0.1
```
- **关键事实**：`stage_proofread.ProofOptions`（stage_proofread/__init__.py L41）**已经是 frozen dataclass，字段完全一致**。两个选项：
  - **A（默认）**：T7 仍定义 `ProofOptsSpec`（独立类型，配置层），T11 转 `ProofOptions`。保持「配置层 spec 与运行时类型分离」的一致性（与 RenderOptsSpec/RenderOptions 对称）。
  - B：直接复用 `ProofOptions`，不引入 `ProofOptsSpec`。
  - 默认 A（对称性 > 省一个类）。
- tesla_stage02 用的覆盖：`enable_llm=True`（其余默认）。

#### `TranscriptSpec`
```python
@dataclass(frozen=True)
class TranscriptSpec:
    audio_path: str           # 源音频（相对 meta.root 或绝对），step1/2 输入
    path: str                 # transcript.json 路径（step1/2 产物 + step3+ 输入）
```

#### `ProjectConfig`（顶层聚合）
```python
@dataclass(frozen=True)
class ProjectConfig:
    meta: ProjectMeta
    sources: tuple[SourceSpec, ...]            # 至少 1 条
    transcript: TranscriptSpec
    errata_path: str                           # corrections.yaml（相对 meta.root）
    proof_opts: ProofOptsSpec = ProofOptsSpec()
    cut_points: tuple[CutPointSpec, ...] = ()
    style_name: str = "default"                # 对应 stage_style/styles/<name>.yaml
    render_opts: RenderOptsSpec = field(default_factory=lambda: RenderOptsSpec(output_dir="output/clips"))
    output_dir: str = "output"                 # 项目级默认输出根（clips/fullcut/release 的父）
```
- 用 `tuple`（不可变）而非 `list`，与 `types.py` 的 frozen 风格一致。
- `from_dict(d) -> ProjectConfig` / `to_dict() -> dict`：往返等价（`to_dict(from_dict(d)) == d`，忽略 yaml 注释 / key 顺序）。
- `from_yaml(path) -> ProjectConfig`：复用 `config.load_yaml`（config.py L22，已存在）→ `from_dict`。
- `to_yaml(path)`：`to_dict` → `yaml.safe_dump`（`allow_unicode=True, sort_keys=False`）。

### 3. `validate(cfg: ProjectConfig) -> None`（raise `ConfigError`）

`ConfigError` 直接 import `config.ConfigError`（config.py L18，已存在），**不新建异常类**。校验项：

| # | 校验 | 失败信息需含 |
|---|---|---|
| 1 | `sources` 非空，且每个 `id` 唯一 | 重复的 source id |
| 2 | 每个 `cut_point.source` 能在 `sources[].id` 里找到 | clip_id + 不存在的 source id |
| 3 | `cut_point` 的 `[start_s, end_s]` 落在其引用 source 的 `[timeline_start_s, timeline_end_s]` 范围内（`timeline_end_s is None` 时只校验下界） | clip_id + 越界数值 |
| 4 | `style_name` 对应的 `stage_style/styles/<name>.yaml` 存在（用 `importlib.resources` 或相对仓库定位 styles 目录） | 缺失的 style_name |
| 5 | `cut_points` 的 `clip_id` 唯一 | 重复的 clip_id |
| 6 | `start_s < end_s`（每个 cut_point） | clip_id |

- **路径存在性校验的策略**（source.path / transcript.path / errata_path）：见 Q1。默认 `validate` **不校验文件存在性**（创建项目时文件还没生成；存在性校验由 T9 `load_project(strict=...)` 负责）。`validate` 只做**结构 / 引用 / 范围**校验。这样 T8 的 `create_project` 能在「目录刚建、文件未落」时调用 `validate`。

### 4. `schema/project.schema.yaml`（带注释的 schema 规范文档）

- 一份人/AI 可读的 YAML，逐字段注释类型 / 默认值 / 是否必填 / 引用关系。**不是**运行时 JSON Schema 校验器（运行时校验全靠 `validate()`）。
- 内容与 `ProjectConfig.from_dict` 的字段契约**逐字一致**——这份文档是单一权威 schema 参考点，T8–T13 + agent 都以它为准。
- 见 Q2（是否同时再出一份 JSON Schema）。

### 5. `references/project.example.yaml`（示例 project.yaml）

- 用 **占位符**（`<project-root>` / `<source-video>.mp4` / `/path/to/`），**严禁真实 tesla 数据**（AGENTS.md 示例数据卫生铁律）。
- 覆盖单源 + 多源两种形态（多源示例用 `SRC1` + `SRC2` + `source_offset_s`，结构对齐 tesla_stage04 但数值全用占位符）。

---

## 需人拍板

### Q1：`validate` 要不要校验文件存在性（source.path / transcript.path / errata_path）？

| 选项 | 做法 | 影响 |
|---|---|---|
| **A（默认）** | `validate` **不校验文件存在性**，只做结构 / 引用 / 范围校验。存在性留给 T9 `load_project(strict=True/False)`。 | T8 `create_project`（目录刚建、文件未落）能立即 `validate`；T7/T8 解耦清晰。 |
| B | `validate` 也校验文件存在性，缺失即 `ConfigError`。 | T8 create 后无法直接 validate（文件还没生成），需先写文件再 validate，顺序耦合。 |

> **默认 A**：与 Plan T9 的 `strict` 参数职责分工一致（L377：「strict=False 时允许部分产物尚未存在，但 schema 类错误仍抛」）。

### Q2：除了 `schema/project.schema.yaml`（注释规范），要不要再出一份标准 JSON Schema（`project.schema.json`）？

| 选项 | 做法 |
|---|---|
| **A（默认）** | 只出 `schema/project.schema.yaml`（带注释规范）。运行时校验全靠 `validate()`。 |
| B | 同时出标准 JSON Schema 文件，支持 `jsonschema` 库做声明式校验。 |

> **默认 A**：Plan 未要求 JSON Schema；引入 `jsonschema` 依赖 + 维护两份 schema 是过度设计（违反 Simplicity First）。`validate()` 的 Python 校验就是单一真相源。

### Q3：`project.yaml` 要不要带 `schema_version` 字段？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **不加**。D6 的 `schema_version` 绑在 T11 的 `run_manifest.json` 上，Plan T7 的 schema 示例没有此字段。 |
| B | 加 `schema_version: 1` 到 project.yaml 顶层。 | 与 D6 范围重叠，且 Plan 未要求。 |

> **默认 A**：严格遵循 Plan + D6 范围。若人审想给 project.yaml 也版本化，需明确允许（并在 T8 create 时写入）。

### Q4：`ProjectConfig` 的可变默认值（`render_opts` / `proof_opts`）怎么处理？

frozen dataclass 的可变默认值要用 `field(default_factory=...)`。`RenderOptsSpec(output_dir=...)` 的 output_dir 默认值依赖业务约定。

> **默认**：`render_opts` 用 `field(default_factory=lambda: RenderOptsSpec(output_dir="output/clips"))`；`proof_opts` 用 `field(default_factory=ProofOptsSpec)`（ProofOptsSpec 无必填字段，可直接工厂）。`output_dir`（项目级）默认 `"output"`。与 Plan 示例 + tesla_stage04 的 `output/clips` 一致。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **`config.py`**（已读全文）：`load_yaml(path) -> dict`（L22，文件不存在返回 `{}`）、`ConfigError(ValueError)`（L18）、`build_errata_config(errata_yaml_path) -> ErrataConfig`（L31）。T7 直接 `from garden_core.config import load_yaml, ConfigError`，**不重写**。
- **`types.py` `CutPoint`**（L138）：`(clip_id, source_media, start_s, end_s, style_name="default", title="", source_offset_s=0.0)`，已 frozen，`source_media` 必填（D2 已落地）。**T7 不改它**——`CutPointSpec` 是配置层新类型，与运行时 `CutPoint` 并存。
- **`stage_render.RenderOptions`**（stage_render/__init__.py L22）：普通 class（非 dataclass），字段 `output_dir / render_horizontal / render_vertical / vertical_height=1920 / vertical_width=1080 / horizontal_height=1080 / horizontal_width=1920 / crf=18`。T7 的 `RenderOptsSpec` 字段默认值逐字对齐。
- **`stage_proofread.ProofOptions`**（stage_proofread/__init__.py L41）：已是 frozen dataclass，字段 `enable_normalize=True / enable_errata=True / enable_phonetic=True / enable_llm=False / enable_dual_channel=True / llm_temperature=0.1`。`ProofOptsSpec` 字段镜像（Q1 默认 A 仍新建独立类型）。
- **`stage_style/styles/`**（已 ls）：`fresh.yaml` / `default.yaml` / `bold_impact.yaml` / `broadcast.yaml` / `cinematic.yaml` / `classic_outline.yaml` / `frosted_glass.yaml` / `minimal_clean.yaml`。validate 校验 `style_name` 时查这个目录。
- **tesla_stage04.py**（已读全文）：双源 `SRC1`(0–850s) + `SRC2`(850–1294s, `source_offset_s=850`)；19 条 cut_points（t01–t19）；`RenderOptions(output_dir=OUTPUT, horizontal_width=3840, horizontal_height=2160, crf=20)`；style `"fresh"`。**schema 必须能完整表达这个形状**（验收硬指标）。
- **tesla_stage02.py**（已读全文）：`AUDIO` + `OUT=transcript.json` + `ProofOptions(enable_llm=True)`。对应 `TranscriptSpec(audio_path, path)` + `ProofOptsSpec(enable_llm=True)`。
- **`project-directory-template.md`**（已读）：`source/` + `output/{clips,fullcut,release}` + `corrections.yaml` + `AGENTS.md` + `README.md`。T7 的 `errata_path` 默认 `corrections.yaml`、`output_dir` 默认 `output` 与此一致。
- **示例数据卫生**（AGENTS.md）：tesla 真实路径（`N:\<DATE> Tesla` / `<SRC_FILE>*.MP4`）/ 真实 clip 标题 / 真实 errata 条目**不得进仓库**。`project.example.yaml` + 测试数据全用占位符或虚构值。

---

## 验收标准

1. **新建 `src/garden_core/project/` 包**：`__init__.py` + `schema.py` + `config.py`；`from garden_core.project import ProjectConfig, ProjectMeta, SourceSpec, CutPointSpec, RenderOptsSpec, ProofOptsSpec, TranscriptSpec, validate` 全部可达。
2. **frozen**：所有 spec 类 + `ProjectConfig` 均为 `@dataclass(frozen=True)`（`python -c "from garden_core.project import ProjectConfig; import dataclasses; assert dataclasses.is_dataclass(ProjectConfig) and ProjectConfig.__dataclass_params__.frozen"`）。
3. **往返等价**：构造一份 tesla 形状的 dict（多源 + 19 cut_points + errata + render_opts 覆盖）→ `ProjectConfig.from_dict(d)` → `.to_dict()` → 与原 dict 语义等价（值相等；忽略 key 顺序）。
4. **`from_yaml` / `to_yaml` 往返**：`to_yaml(p)` 写出 → `from_yaml(p)` 读回 → 与原 cfg 相等。
5. **`validate` 合法 pass**：对验收 3 的 tesla 形状 cfg，`validate(cfg)` 不抛。
6. **`validate` 4 类非法场景分别抛 `ConfigError` 且信息可定位**：
   - (a) `cut_point.source` 在 `sources` 里找不到 → 信息含 clip_id + 坏 source id。
   - (b) `cut_point` 时间轴越界（超出其 source 的 `[timeline_start_s, timeline_end_s]`）→ 信息含 clip_id + 数值。
   - (c) `style_name` 对应的 styles yaml 不存在 → 信息含 style_name。
   - (d) `sources` 里有重复 `id` → 信息含重复的 id。
   - （另加 (e) 重复 clip_id / (f) start_s ≥ end_s，作为完整覆盖。）
7. **新建 `schema/project.schema.yaml`**：带注释的 schema 规范，字段与 `ProjectConfig.from_dict` 契约逐字一致。
8. **新建 `references/project.example.yaml`**：单源 + 多源两份示例，全占位符（无真实 tesla 数据）。
9. **不破坏现有代码**：`pytest tests/` 全绿；`config.py` / `types.py` / `stage_render/__init__.py` / `stage_proofread/__init__.py` **零改动**。

**pytest / 校验命令**：
```bash
# 可达性 + frozen
python -c "from garden_core.project import ProjectConfig, SourceSpec, CutPointSpec, RenderOptsSpec, ProofOptsSpec, validate; import dataclasses; assert ProjectConfig.__dataclass_params__.frozen"
# 往返
python -m pytest tests/test_project_config.py tests/test_project_validate.py -v
# styles 目录可定位（validate 用）
python -c "from garden_core.project import validate; print('styles dir resolved')"
# 全量回归
python -m pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 project/* (新增) + schema/project.schema.yaml (新增) + references/project.example.yaml (新增) + tests/test_project_*.py (新增)
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ 新建 `src/garden_core/project/{__init__.py, schema.py, config.py}` | ❌ 改 `src/garden_core/config.py`（只 import 复用 `load_yaml` / `ConfigError`） |
| ✅ 新建 `schema/project.schema.yaml`（注释规范，Q2 默认 A） | ❌ 改 `src/garden_core/types.py`（`CutPoint` 保持现状） |
| ✅ 新建 `references/project.example.yaml`（占位符） | ❌ 改 `stage_render/__init__.py` 的 `RenderOptions`（T7 引入 `RenderOptsSpec` 并存） |
| ✅ 新建 `tests/test_project_config.py` | ❌ 改 `stage_proofread/__init__.py` 的 `ProofOptions`（并存） |
| ✅ 新建 `tests/test_project_validate.py` | ❌ 新建 `ProjectRun`（那是 T11） |
|  | ❌ 给 `project.yaml` 加 `schema_version`（Q3 默认 A，那是 T11 run_manifest 的事） |
|  | ❌ 引入 `jsonschema` 依赖（Q2 默认 A） |
|  | ❌ 校验文件存在性（Q1 默认 A，留给 T9） |
|  | ❌ 在 `project.example.yaml` / 测试里放真实 tesla 数据（AGENTS.md 卫生铁律） |
|  | ❌ `pipeline.py` / `scripts/*.py`（T7 不碰） |

---

## 自测方法

1. **可达性**（验收 1）：`python -c "from garden_core.project import ProjectConfig, ProjectMeta, SourceSpec, CutPointSpec, RenderOptsSpec, ProofOptsSpec, TranscriptSpec, validate"`。
2. **frozen**（验收 2）：对每个 spec 类跑 `assert Cls.__dataclass_params__.frozen`。
3. **往返等价**（验收 3/4）：在 `test_project_config.py` 里构造 tesla 形状 dict（`SRC1`+`SRC2`、`source_offset_s=850`、19 条 cut_points、`render_opts` 覆盖 4K+crf20、`proof_opts.enable_llm=True`）→ `from_dict` → 断言字段 → `to_dict` → 与原 dict 比相等；再 `to_yaml(tmp)` → `from_yaml(tmp)` → 与原 cfg 相等。
4. **validate 合法 pass**（验收 5）：对验收 3 的 cfg，`validate(cfg)` 不抛。
5. **validate 4+2 类非法**（验收 6）：在 `test_project_validate.py` 里各构造一个坏 cfg，`pytest.raises(ConfigError)` 并断言 str(e) 含可定位信息（clip_id / source id / style_name / 数值）。
6. **styles 目录定位**：`validate` 能解析到 `stage_style/styles/<name>.yaml`（用 `importlib.resources.files("garden_core.stage_style") / "styles" / f"{name}.yaml"`，与现有 stage_style 的资源定位方式一致——开工时先 grep `stage_style/__init__.py` 确认现有定位方式，复用之，不新发明）。
7. **diff 范围**：`git diff --name-only` 仅含新增文件（project/* + schema/* + references/project.example.yaml + tests/test_project_*）；现有文件零改动。
8. **回归**：`pytest tests/ -v` 全绿（T7 是纯新模块，不应有任何现有测试失败）。
9. **卫生检查**：`grep -rnE "<DATE>|<SRC_FILE>|tesla_full|N:\\\\<DATE>" src/ schema/ references/ tests/` 无命中（确保无真实 tesla 数据泄露）。

---

## 风险

- **无破坏性**：纯新模块（`project/` 包 + schema + references + tests），不碰任何现有文件。`pytest tests/` 应全绿。
- ⚠️ **Meta-Brief 与 Plan 命名/范围有三处出入**（见「执行前必读」）：默认按 Plan/代码走（`ProjectConfig` 而非 `ProjectRun`；不加 `schema_version`；多出一份 `schema/project.schema.yaml`）。若人审坚持 Meta-Brief 字面（建 `ProjectRun` / 加 schema_version），需明确放宽红线——否则按默认走。
- **styles 目录定位**：`validate` 校验 `style_name` 时需定位 `stage_style/styles/`。开工时先确认现有 `stage_style` 的资源定位方式（grep `importlib.resources` / `__file__`），复用同一机制，避免 editable install 下路径错位。
- **shape 一次定对**：T7 是 T8–T11 的硬前置，schema 字段一旦发布就会被子任务依赖。本 brief 的字段清单已逐项对齐 Plan T7 + tesla 真实形状 + 现有 types/RenderOptions/ProofOptions，开工时**不再临时增删字段**；若发现遗漏，停下来升级本 brief 再动手（Goal-Driven Execution）。
- **Q1–Q4 需人拍板**：默认 A / A / A /（render_opts+proof_opts 用 default_factory）。不拍板按默认走。

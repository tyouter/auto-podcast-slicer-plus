# garden-core API Reference

> 版本：0.3.0 | 源码：`src/garden_core/`
>
> 导入根：`from garden_core.project import ...` / `from garden_core.pipeline import Engines`

本文是 garden-core 的完整 API 参考，以 **`ProjectRun`** 为主线。

`ProjectRun` 是唯一的运行时编排器：它封装了「`project.yaml` 配置 + 注入引擎 + 阶段化执行 + `run_manifest.json` 记录」。整个生命周期只有一条主路径：

```
create_project(...)        # 脚手架项目目录 + 写 project.yaml
   → 编辑 project.yaml 填 cut_points（edit_project 或手改）
   → load_project(...)     # 读 yaml → 校验 → 返回 ProjectConfig
   → ProjectRun(cfg, engines)
   → run.transcribe() / proofread() / render() / audit()
   → run.resume() / rerender() / reproofread()  # 增量 / 续跑
```

> 日常推荐 `ProjectRun`。底层 pipeline 入口（`run_from_transcript` / `run_from_audio`）已被 `ProjectRun` 封装取代，不再作为对外推荐 API；唯一例外是 montage（精剪混剪），仍走 `run_montage`（见文末）。

---

## 目录

- [一、公共导出](#一公共导出)
- [二、project.yaml schema](#二projectyamlschema)
  - [2.1 ProjectConfig（顶层模型）](#21-projectconfig顶层模型)
  - [2.2 ProjectMeta](#22-projectmeta)
  - [2.3 SourceSpec（多源一等公民）](#23-sourcespec多源一等公民)
  - [2.4 CutPointSpec（切片定义）](#24-cutpointspec切片定义)
  - [2.5 TranscriptSpec](#25-transcriptspec)
  - [2.6 RenderOptsSpec（渲染选项）](#26-renderoptsspec渲染选项)
  - [2.7 ProofOptsSpec（纠错选项）](#27-proofoptsspec纠错选项)
  - [2.8 project.yaml 示例](#28-projectyaml-示例)
- [三、项目操作函数](#三项目操作函数)
  - [3.1 create_project](#31-create_project)
  - [3.2 load_project](#32-load_project)
  - [3.3 edit_project](#33-edit_project)
  - [3.4 validate](#34-validate)
- [四、Engines（引擎注入）](#四engines引擎注入)
- [五、ProjectRun（运行时编排器）](#五projectrun运行时编排器)
  - [5.1 构造与便捷入口](#51-构造与便捷入口)
  - [5.2 阶段方法](#52-阶段方法)
  - [5.3 编排方法（all / resume）](#53-编排方法all--resume)
  - [5.4 增量方法（rerender / reproofread）](#54-增量方法rerender--reproofread)
  - [5.5 StageResult](#55-stageresult)
  - [5.6 run_manifest.json](#56-run_manifestjson)
  - [5.7 内部：多源翻译 _translate_cut_points](#57-内部多源翻译-_translate_cut_points)
- [六、run_montage（精剪混剪）](#六run_montage精剪混剪)
- [七、完整 workflow 示例](#七完整-workflow-示例)

---

## 一、公共导出

```python
from garden_core.project import (
    # 配置模型 + spec dataclass
    ProjectConfig,
    ProjectMeta,
    SourceSpec,
    CutPointSpec,
    TranscriptSpec,
    RenderOptsSpec,
    ProofOptsSpec,
    # 项目操作
    validate,
    create_project,
    load_project,
    edit_project,
    # 运行时编排器
    ProjectRun,
)
```

引擎注入单独从 pipeline 取：

```python
from garden_core.pipeline import Engines
```

---

## 二、project.yaml schema

所有 spec 都是 `@dataclass(frozen=True)` 的不可变值对象，各提供 `from_dict` / `to_dict` 做 YAML 往返。

**时间铁律**（继承自 `types.py`）：所有 `_s` 后缀字段均为**秒（float）**，不是 `HH:MM:SS` 字符串。

### 2.1 ProjectConfig（顶层模型）

`ProjectConfig`（`src/garden_core/project/config.py`）—— `project.yaml` 的单一 frozen dataclass，持有全部字段。`sources` 和 `cut_points` 是 tuple（不可变）。

```python
@dataclass(frozen=True)
class ProjectConfig:
    meta: ProjectMeta
    sources: tuple[SourceSpec, ...]
    transcript: TranscriptSpec
    errata_path: str = "corrections.yaml"
    proof_opts: ProofOptsSpec = field(default_factory=ProofOptsSpec)
    cut_points: tuple[CutPointSpec, ...] = ()
    style_name: str = "default"
    render_opts: RenderOptsSpec = field(
        default_factory=lambda: RenderOptsSpec(output_dir="output/clips")
    )
    output_dir: str = "output"
```

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `meta` | `ProjectMeta` | （必填） | 项目身份 + root 目录 |
| `sources` | `tuple[SourceSpec, ...]` | （必填） | 源素材列表（≥1 条，id 唯一） |
| `transcript` | `TranscriptSpec` | （必填） | ASR 音频路径 + transcript.json 路径 |
| `errata_path` | `str` | `"corrections.yaml"` | 勘误表路径（相对 `meta.root` 解析） |
| `proof_opts` | `ProofOptsSpec` | `ProofOptsSpec()` | 纠错阶段开关 |
| `cut_points` | `tuple[CutPointSpec, ...]` | `()` | 切片定义（转录完成后再填） |
| `style_name` | `str` | `"default"` | 项目级字幕风格（须存在于 `stage_style/styles/`） |
| `render_opts` | `RenderOptsSpec` | `RenderOptsSpec(output_dir="output/clips")` | 渲染参数（分辨率 / CRF / 朝向） |
| `output_dir` | `str` | `"output"` | 项目级输出根目录（audit 报告写这里） |

方法：

| 方法 | 签名 | 说明 |
|------|------|------|
| `from_dict` | `ProjectConfig.from_dict(d: dict) -> ProjectConfig` | 从原始 dict 构建（不做校验） |
| `to_dict` | `to_dict() -> dict` | 序列化为可写 YAML 的 dict（默认值字段被省略） |
| `from_yaml` | `ProjectConfig.from_yaml(path) -> ProjectConfig` | 加载 `project.yaml`（不做校验） |
| `to_yaml` | `to_yaml(path) -> None` | 写入 `project.yaml`（自动建父目录） |

> **路径语义差异**：`ProjectConfig.from_dict` / `edit_project` 返回 **config view**（路径与磁盘一致，通常相对）；`load_project` 返回 **runtime view**（所有路径字段解析为绝对）。运行时代码用 `load_project`。

### 2.2 ProjectMeta

```python
@dataclass(frozen=True)
class ProjectMeta:
    name: str   # 项目名
    root: str   # 项目根目录（绝对，或相对 cwd）
```

### 2.3 SourceSpec（多源一等公民）

一条源素材。`timeline_start_s` / `timeline_end_s` 定义该源在**全局（原始）时间轴**上的位置；`source_offset_s` 把全局时间窗口翻译为源媒体本地时间（多源拼接用）。

```python
@dataclass(frozen=True)
class SourceSpec:
    id: str                                 # 唯一 id，被 cut_points.source 引用
    path: str                               # 源媒体路径
    timeline_start_s: float = 0.0           # 全局时间轴起点（秒）
    timeline_end_s: Optional[float] = None  # 全局时间轴终点（None = 不限）
    source_offset_s: float = 0.0            # 全局→本地时间偏移（秒）
```

> 多源时配多条 `SourceSpec`，`cut_points` 通过 `source` 字段引用各自 id；`render()` 自动做多源时间偏移翻译。

### 2.4 CutPointSpec（切片定义）

切片边界，定义在**全局（原始）时间轴**上。`source` 字段引用 `sources[].id`。运行时 `ProjectRun._translate_cut_points()` 通过 `SourceSpec.source_offset_s` 把全局窗口翻译为每源本地时间，生成 runtime `types.CutPoint`。

这是 **config 层**类型；`types.CutPoint` 是 **runtime** 类型（已携带解析后的 `source_media` 绝对路径 + `source_offset_s`）。

```python
@dataclass(frozen=True)
class CutPointSpec:
    clip_id: str            # 唯一标识，输出文件名用
    source: str             # 引用 sources[].id（YAML key: "source"）
    start_s: float          # 全局时间轴起点（秒）
    end_s: float            # 全局时间轴终点（秒）
    style_name: str = "default"  # per-clip 风格（当前版本 render 用项目级 style_name）
    title: str = ""         # clip 标题
```

> **输出顺序 = `cut_points` 列表顺序**。Montage 场景下可把原片靠后的段落列在前面做乱序拼接（见 [run_montage](#六run_montage精剪混剪)）。

### 2.5 TranscriptSpec

```python
@dataclass(frozen=True)
class TranscriptSpec:
    audio_path: str   # ASR 源音频路径
    path: str         # transcript.json 路径
```

> ⚠️ **Pitfall**：`transcript.path` 应写**绝对路径**（`load_project(strict=True)` 也会校验存在性）。相对路径可能导致下游报告「转录条目: 0」。

### 2.6 RenderOptsSpec（渲染选项）

`stage_render.RenderOptions` 的 frozen 镜像，运行时由 `ProjectRun._render_options_from_cfg()` 转成可变的 `RenderOptions`。

```python
@dataclass(frozen=True)
class RenderOptsSpec:
    output_dir: str = "output/clips"
    horizontal_width: int = 1920
    horizontal_height: int = 1080
    vertical_width: int = 1080
    vertical_height: int = 1920
    crf: int = 18
    render_horizontal: bool = True
    render_vertical: bool = True
```

> 4K 源默认被压到 1080p——出 4K 需显式设 `horizontal_width: 3840` / `horizontal_height: 2160`。

### 2.7 ProofOptsSpec（纠错选项）

`stage_proofread.ProofOptions` 的 frozen 镜像。

```python
@dataclass(frozen=True)
class ProofOptsSpec:
    enable_normalize: bool = True
    enable_errata: bool = True
    enable_phonetic: bool = True
    enable_llm: bool = True           # 默认开；有 DEEPSEEK_API_KEY 就用，无则跳过
    enable_dual_channel: bool = True
    llm_temperature: float = 0.1
```

### 2.8 project.yaml 示例

```yaml
meta:
  name: <project-name>
  root: <root-dir>
sources:
  - id: SRC1
    path: <source-1>.mp4
    timeline_start_s: 0.0
    timeline_end_s: 3600.0
    # source_offset_s: 0.0   # 多源时填
transcript:
  audio_path: <audio>.wav
  path: /path/to/<project>/transcript.json
errata_path: corrections.yaml
style_name: fresh
proof_opts:
  enable_llm: true
cut_points:
  - clip_id: <clip-01>
    title: <切片标题>
    source: SRC1
    start_s: 83.5
    end_s: 225.0
    style_name: cinematic
render_opts:
  horizontal_width: 3840
  horizontal_height: 2160
  crf: 18
output_dir: output
```

---

## 三、项目操作函数

### 3.1 create_project

`create_project(name, root_dir, *, sources, ...)` —— 脚手架项目目录 + 写 `project.yaml` + 返回校验过的 `ProjectConfig`。

```python
def create_project(
    name: str,
    root_dir: str | Path,
    *,
    sources: Sequence[SourceSpec],
    audio_path: str | None = None,
    style: str = "fresh",
    render_opts: RenderOptsSpec | None = None,
    corrections: dict | None = None,
    wiki: bool = False,
    overwrite: bool = False,
) -> ProjectConfig
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `name` | — | 项目名 → `meta.name` + README 占位符 |
| `root_dir` | — | 项目根目录（不存在则创建） |
| `sources` | — | `SourceSpec` 序列（≥1 条） |
| `audio_path` | `None` | ASR 音频路径；`None` → `source/<name>.wav` |
| `style` | `"fresh"` | 风格名（须存在于 `stage_style/styles/`） |
| `render_opts` | `None` | 渲染选项；`None` → 4K preset（3840×2160 横 / 1080×1920 竖 / crf 18） |
| `corrections` | `None` | `corrections.yaml` 初值；`None` → 写空 `{}` |
| `wiki` | `False` | `True` → 建 `Wiki/<name>/A..M` 全花园子树 |
| `overwrite` | `False` | `False` → 拒绝在非空目录创建；`True` → 允许（**绝不**删 `source/` 内容） |

副作用（磁盘）：
- `<root>/output/{clips,fullcut,release}/`
- `<root>/source/`
- `<root>/project.yaml`（通过 `ProjectConfig.to_yaml`）
- `<root>/corrections.yaml`
- `<root>/AGENTS.md` / `<root>/README.md`
- （可选）`<root>/Wiki/<name>/<A..M>/`

**create = validate**：先在内存构造 `ProjectConfig` 并跑 `validate()`，**通过后才落盘**。失败抛 `ConfigError`，磁盘不被改动。

### 3.2 load_project

`load_project(path, *, strict=True)` —— 加载 + 解析路径 + 校验 + （可选）文件存在性检查。

```python
def load_project(
    path: str | Path,
    *,
    strict: bool = True,
) -> ProjectConfig
```

`path` 可传 **`project.yaml` 文件**或**项目根目录**（自动发现 `<root>/project.yaml`）。

执行步骤：
1. 定位 `project.yaml`
2. `load_yaml` 读原始 dict
3. `ProjectConfig.from_dict` 构建原始 cfg
4. `meta.root` 解析为绝对（绝对保持，相对则相对 `cwd`）
5. 所有路径字段相对 `meta.root` 解析为绝对
6. 跑 `validate()`（结构 / 引用一致性，无文件 IO）
7. `strict=True` 时检查 `source.path` / `transcript.audio_path` / `transcript.path` / `errata_path` 是否存在——**所有缺失文件聚合为单个 `ConfigError`**

返回：`ProjectConfig`，路径字段全部**绝对**（runtime view）。

> 任何加载 / 解析 / 校验 / 文件存在性问题都抛 `ConfigError`。

### 3.3 edit_project

`edit_project(root_dir, /, **overrides)` —— 改 `project.yaml` → 校验 → 原子写回。

```python
def edit_project(
    root_dir: str | Path,
    /,
    **overrides: Any,
) -> ProjectConfig
```

`root_dir` 语义同 `load_project.path`。`**overrides` 是顶层 `ProjectConfig` 字段名 → 新值。

override 三类：

| 类型 | 字段 | 行为 |
|------|------|------|
| **标量** | `errata_path`, `style_name`, `output_dir` | 直接替换 |
| **嵌套 spec** | `meta`, `transcript`, `proof_opts`, `render_opts` | 传 spec 实例 = 全替换；传 dict = `dataclasses.replace` 部分合并 |
| **集合** | `sources`, `cut_points` | 传 tuple / list = 全替换；元素可为 spec 实例或 dict（`Spec.from_dict` 转换） |

设计约束：
- **不**走 `load_project`：用 `load_yaml → from_dict` 保留磁盘路径表示（相对留相对，绝对留绝对）
- **不**跑 strict 文件存在性检查，只跑 `validate()`
- **原子写**：`project.yaml.tmp` → `os.replace`，失败时原文件不受损
- **只动 `project.yaml`**：源媒体 / 转录 / `corrections.yaml` / output 绝不删改

未知 key 抛 `ConfigError`（typo 防护）。返回的新 cfg 路径为 **config view**（与磁盘一致，通常相对）。

### 3.4 validate

`validate(cfg: ProjectConfig) -> None` —— 结构 / 引用一致性检查（**无文件 IO**）。失败抛 `ConfigError`。

检查顺序：
1. `sources` 非空，每个 `id` 唯一
2. 每个 `cut_point.source` 引用已知 `sources[].id`
3. 每个 `cut_point` 落在其 source 的时间轴范围内
4. `style_name` 在 `stage_style/styles/` 有对应 YAML
5. `cut_points` 的 `clip_id` 唯一
6. 每个 `cut_point` 的 `start_s < end_s`

> 文件存在性检查是调用方职责（`load_project(strict=True)`）。

---

## 四、Engines（引擎注入）

`Engines`（`src/garden_core/pipeline.py`，frozen dataclass）—— 所有有状态引擎，注入一次，全 run 复用。`ProjectRun` 必须接收一份 `Engines`。

```python
@dataclass(frozen=True)
class Engines:
    transcriber: Optional[Transcriber] = None
    aligner: Optional[Aligner] = None
    llm: LLMClient = field(default_factory=NoLLMClient)
    style_resolver: Optional[StyleResolver] = None
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `transcriber` | `Optional[Transcriber]` | ASR 引擎（如 `FunASRLocal`）；`ProjectRun.transcribe` 必填，`None` 时跑会抛 `RuntimeError` |
| `aligner` | `Optional[Aligner]` | 词级对齐器（MMS_FA）；`None` 跳过 stage 2 对齐（warning） |
| `llm` | `LLMClient` | LLM 客户端；默认 `NoLLMClient()`（调用时报 UNAVAILABLE） |
| `style_resolver` | `Optional[StyleResolver]` | 风格解析器；`None` 回退到内置 `YamlStyleResolver` |

工厂：

```python
@classmethod
def Engines.from_env(
    cls,
    *,
    llm_default_model: str = "deepseek-chat",
    llm_timeout: float = 300.0,
    env_path: Optional[str] = None,
    transcriber: Optional[Transcriber] = None,
    aligner: Optional[Aligner] = None,
    style_resolver: Optional[StyleResolver] = None,
) -> "Engines"
```

- `env_path`（caller 提供，库不硬编码）→ 把每行 `KEY=VALUE` 合入 `os.environ`（空行 / `#` 跳过）
- 合并后有 `DEEPSEEK_API_KEY` → 建真实 `LLMClient`；否则降级为 `NoLLMClient()`（绝不因 env 设置硬崩）
- `transcriber` / `aligner` / `style_resolver` 是重型有状态对象（GPU 模型等），**不**在此构造——按需作为 kwarg 传入

---

## 五、ProjectRun（运行时编排器）

`ProjectRun`（`src/garden_core/project/run.py`）—— frozen dataclass，持有解析过的 `ProjectConfig` + 注入的 `Engines`。**每个阶段方法产出恰好一个 artifact，并把结果写入 `<cfg.meta.root>/run_manifest.json`**（schema_version=1）。

```python
@dataclass(frozen=True)
class ProjectRun:
    cfg: ProjectConfig
    engines: Engines
```

### 5.1 构造与便捷入口

```python
# 直接构造
run = ProjectRun(cfg, engines)

# 一行加载 + 构造
run = ProjectRun.from_project_dir("<root-dir>", engines, *, strict=False)

# 从已有 manifest 重建（用于 resume）
run = ProjectRun.load("<manifest-path>", engines)
```

- `from_project_dir(dir, engines, *, strict=False)`：等价于 `ProjectRun(load_project(dir, strict=strict), engines)`
- `load(manifest_path, engines)`：读 `run_manifest.json`，校验 `schema_version==1`，用 `manifest.project.root` 调 `load_project(..., strict=False)` 重建 cfg；返回的 run 可直接 `.resume()`。文件缺失 / 非 JSON / schema_version 不为 1 都抛 `ConfigError`

manifest 工具方法：

| 方法 | 返回 | 说明 |
|------|------|------|
| `manifest_path()` | `Path` | `<cfg.meta.root>/run_manifest.json` |
| `read_manifest()` | `dict` | 当前 manifest（缺失 / 损坏返回 `{}`） |

### 5.2 阶段方法

| 方法 | 签名 | 产物 | 前置条件 |
|------|------|------|---------|
| `transcribe()` | `-> StageResult` | `cfg.transcript.path`（transcript.json，ASR + 对齐） | `engines.transcriber` 必填 |
| `proofread()` | `-> StageResult` | `cfg.transcript.path`（纠错覆盖） | `transcribe()` 已跑 |
| `render()` | `-> StageResult` | `cfg.render_opts.output_dir`（clips mp4 + ass / srt） | transcript.json 已存在；理想先 `proofread()` |
| `audit()` | `-> StageResult` | `cfg.output_dir/audit_report.json` | output_dir 有渲染产物 |

#### `transcribe()`

跑 ASR（stage 1）+ 对齐（stage 2，`engines.aligner` 提供则对齐，否则跳过并 warning）。`engines.transcriber is None` 时抛 `RuntimeError`。产物写 `cfg.transcript.path`。

#### `proofread()`

加载已存 transcript，应用纠错（errata + normalizer + phonetic + 可选 LLM / dual-channel），覆盖 `cfg.transcript.path`。errata 从 `cfg.errata_path` 加载（相对 `cfg.meta.root` 解析；缺失文件被容忍为空配置）。**前置：`transcribe()` 已跑**。

#### `render()`

加载 transcript，把 `cfg.cut_points`（`CutPointSpec`，config 层）翻译为 runtime `types.CutPoint`（多源翻译），再调底层渲染并**跳过对齐和纠错**（这两步由 `transcribe()` / `proofread()` 负责）。

所有 clip 用 `cfg.style_name`（项目级单一风格）。per-clip `CutPointSpec.style_name` 被保留在翻译后的 `CutPoint` 中，但**本版本渲染不使用**。

`skip_existing=True`：已有 mp4 跳过 ffmpeg 重渲。**改样式后必须先删旧 mp4**，否则 ASS 更新但视频字幕不变。

> 设计：若不先 `proofread()` 直接 `render()`，errata 纠正**不会**被应用（阶段分离）。

#### `audit()`

对 `cfg.render_opts.output_dir` 跑 `stage_render.render_gate.audit_dir`：检查文件存在性、ffprobe 分辨率 / 编码、ASS cue 计数、ASS 内容门检（字重比 + 安全区）。**不抛**——结果记入 manifest + report 供人工审阅。报告写 `cfg.output_dir/audit_report.json`。`passed=False` 时 stage status = `"failed"`。

### 5.3 编排方法（all / resume）

| 方法 | 返回 | 行为 |
|------|------|------|
| `all()` | `list[StageResult]` | 全部 4 阶段顺序执行（transcribe → proofread → render → audit），始终全跑（幂等覆盖）。改了 config 想全部重跑用这个 |
| `resume()` | `list[StageResult]` | 读 manifest，跳过 `status=="done"` 且 `artifact_path` 文件存在的 stage；缺失则执行 |

> `resume()` 跳过逻辑（naive）：仅看 `status=="done"` + artifact 文件存在，**无参数哈希比较**。改了 config 要么用 `all()`，要么手动删 manifest 行。

### 5.4 增量方法（rerender / reproofread）

#### `rerender(clip_ids: Sequence[str]) -> StageResult`

不重跑转录 / 纠错，增量重渲指定 clip。翻译 `cfg.cut_points`，过滤到请求 id，`skip_existing=False` 覆盖既有 mp4 / ass / srt。

- 空序列抛 `ValueError`
- 未知 id 抛 `ConfigError`
- 返回的 `StageResult.stage="render"`，覆盖 manifest 中 render 行（`params` 含 `"rerender": True` + 具体 clip 列表）
- 保留 cfg 顺序（非调用方顺序）

> `rerender()` 只门检它处理的子集。之后应跑 `audit()` 做全目录复核。

#### `reproofread(errata=None, *, rerender_clip_ids=None) -> list[StageResult]`

重新纠错，可选注入内联 errata + 可选重渲特定 clip。

- `errata=None`（默认）：从 `cfg.errata_path` 加载（与 `proofread()` 同源）
- 传 `ErrataConfig`：直接注入，**不落盘**；要持久化请用 `edit_project(errata_path=...)` 或手改 `corrections.yaml`
- `rerender_clip_ids=None`（默认）：只纠错
- 传 list：纠错后立即调 `rerender(rerender_clip_ids)`

返回 `list[StageResult]`：至少含 proofread 条目；给了 `rerender_clip_ids` 时追加一条 `render`。

### 5.5 StageResult

`StageResult`（`src/garden_core/project/run.py`）—— 单阶段执行的轻量不可变返回值。**不存入 manifest**（manifest 是权威记录），仅为调用方迭代 `run.all()` / `run.resume()` 结果提供便利。

```python
@dataclass(frozen=True)
class StageResult:
    stage: str             # "transcribe" | "proofread" | "render" | "audit"
    status: str            # "done" | "failed"
    artifact_path: str
    skipped: bool = False  # resume() 跳过时为 True
```

### 5.6 run_manifest.json

`ProjectRun` 把每个阶段结果写入 `<cfg.meta.root>/run_manifest.json`（schema_version=1）。原子写（tmp + `os.replace`）。

结构：

```json
{
  "schema_version": 1,
  "project": {"name": "<project-name>", "root": "<root>"},
  "updated": "<ISO8601>",
  "stages": [
    {
      "stage": "render",
      "status": "done",
      "artifact_path": "<path>",
      "params": {"clips": 3, "style": "fresh"},
      "started": "<ISO8601>",
      "finished": "<ISO8601>"
    }
  ]
}
```

- 每阶段写入时**移除该 stage 的既有行再追加**（last-write wins）
- `ProjectRun.load(manifest_path, engines)` 重建 run 以便 `.resume()`
- **非并发安全**（单机串行假设）

### 5.7 内部：多源翻译 `_translate_cut_points`

把 `cfg.cut_points`（`CutPointSpec`：全局时间轴 + source id）翻译为 `types.CutPoint`（runtime：`source_media=绝对路径` + `source_offset_s`）。这是核心多源机制——**一条 `run.render()` 取代手写多源批量脚本**。未知 source id 抛 `ConfigError`。

---

## 六、run_montage（精剪混剪）

`run_montage`（`src/garden_core/pipeline.py`）是 `ProjectRun` 之外唯一的辅助入口，用于 SKILL.md「工作流 1 · 一期一剪」：把 N 个源窗口拼成**一条**连续横版长片（精剪 / montage / 混剪），字幕时间轴自动偏移合并。

```python
from garden_core.pipeline import Engines, PipelineOptions, run_montage

def run_montage(
    transcript: Transcript,
    cut_points: list[CutPoint],
    style_name: str,
    engines: Engines,
    opts: PipelineOptions,
    montage_id: str = "montage",
    audio_path: str = "",
) -> RenderResult
```

行为：
- `opts.render` 必填，否则抛 `ValueError`
- 每个 window 走 cut → style → render 渲成自带字幕的横版 mp4，再用 ffmpeg concat demuxer 拼成单条连续视频
- **输出顺序 == cut_points 列表顺序**（可与源内时间顺序不同——这是 montage 的意义）：靠后的段落列在前面即可放到片头
- 配套 `.srt` / `.ass` 时间轴连续不重叠：每个 clip 的 clip-local cue 按前序 clip 的**实际渲染时长**偏移后拼接（防御性 overlap-flatten 防亚帧漂移）
- 只产出横版 montage（4K 经 `opts.render.horizontal_width/height`）；可设 `render_vertical=False` 跳过无用的 per-clip 竖渲
- plan 空、或某段无横版 mp4 → 抛 `ValueError`
- 返回单个 `RenderResult`，`metadata.kind == "montage"`

> 标准 `ProjectRun.render()` 每条 cut_point 出一条独立 clip；montage 与之互补，**不走 `ProjectRun`**，需直接调 `run_montage`。

`RenderResult` 结构（`garden_core.types`）：含 `horizontal_mp4` / `vertical_mp4` / `srt_path` / `ass_path` / `metadata`。

---

## 七、完整 workflow 示例

```python
from garden_core.project import (
    create_project, load_project, edit_project, ProjectRun, SourceSpec, CutPointSpec,
)
from garden_core.pipeline import Engines
from garden_core.stage_asr import FunASRLocal

# 1. 建项目（生成 project.yaml + 目录结构）
cfg = create_project(
    "<project-name>", "<root-dir>",
    sources=[SourceSpec(id="SRC1", path="<source>.mp4")],
    audio_path="<audio>.wav",
)

# 2. 加载并编排
engines = Engines(transcriber=FunASRLocal("cuda"))
run = ProjectRun(load_project("<root-dir>"), engines)

# 3. 转录 + 纠错
run.transcribe()    # ASR + 对齐 → transcript.json
run.proofread()     # 纠错（默认走 corrections.yaml）→ 更新 transcript.json

# → 此刻通读 transcript，编辑 project.yaml 填 cut_points（用 edit_project 或手改）
edit_project(
    "<root-dir>",
    cut_points=[
        CutPointSpec(clip_id="<clip-01>", source="SRC1",
                     start_s=83.5, end_s=225.0, title="<切片标题>"),
    ],
)

# 重新加载（路径解析为绝对 runtime view），再编排
run = ProjectRun(load_project("<root-dir>"), run.engines)

# 4. 渲染 + 质检
run.render()        # 切片 + 字幕 + 渲染 → output/clips/*.mp4 + .ass/.srt
run.audit()         # ffprobe + ASS 门检 → audit_report.json

# 增量操作
run.rerender(["<clip-01>"])                          # 重渲指定 clip（覆盖既有 mp4）
run.reproofread(rerender_clip_ids=["<clip-01>"])     # 重纠错 + 重渲

# 续跑（读 manifest 跳过已完成 stage）
run.resume()

# 改了 config 想全量重跑
run.all()
```

参考：每个函数 / 类 / 字段均对应当前 `src/garden_core/` 源码，无虚构。

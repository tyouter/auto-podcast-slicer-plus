# RX Brief · T9 — `load_project`（加载 + 校验项目）

> **一句话**：新建 `src/garden_core/project/load.py`，实现 `load_project(path, *, strict=True) -> ProjectConfig`——接受 `project.yaml` 文件路径**或**项目根目录（自动找 `<root>/project.yaml`），流程 `load_yaml → ProjectConfig.from_dict → 相对路径解析成绝对（相对 `meta.root`）→ validate`；`strict=True` 额外校验文件存在性（每个 `source.path` / `transcript.audio_path` / `transcript.path` / `errata_path`，**缺什么报什么**，一次性聚合所有缺失项）；`strict=False` 只跑 T7 的结构/引用/范围校验。无破坏性（纯新模块），完全复用 T7 的 `ProjectConfig` + `validate` + T8 的 create 闭环，**不改 schema**。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第二层 · 项目管理系统」→ **T9 · `load_project` —— 从 project.yaml / 项目目录加载成 ProjectConfig**（D1：YAML + 完整项目管理；依赖 T7）。

---

## ⚠️ 执行前必读：Meta-Brief / Plan 与 T7 已落地代码的出入

Meta-Brief 给的流程是 `read project.yaml → from_yaml → validate` + strict 文件存在性校验，很简洁。但对照 Plan T9 原文 + T7 已落地的 `ProjectConfig` 真实形状，有四处必须澄清。**默认按「Meta-Brief + T7 代码」走**：

### 出入 1：`ProjectConfig.from_yaml` 已存在，但它**不做路径解析、不查文件存在性**

- T7 已落地 `ProjectConfig.from_yaml(path)`（`config.py`）：仅 `load_yaml(path) → from_dict`，**不 validate、不解析路径、不查存在性**。
- Meta-Brief 的 `load_project` 流程「读 → from_yaml → validate」若直接调 `from_yaml`，会跳过「相对路径解析」这一步（Plan T9 step 3 明确要求）。
- **结论**：T9 **不直接复用 `from_yaml` 的全部语义**，而是 `load_yaml(path) → from_dict(d)` 拿到原始 cfg → 自己做路径解析 → 再 `validate`。`from_yaml` 可作为「不解析、不 strict」的薄包装继续保留（T7 不动），T9 是更上层的入口。

### 出入 2：`ProjectConfig` 是 frozen，路径解析必须返回**新实例**

- T7 的 `ProjectConfig` 及所有 spec 都是 `@dataclass(frozen=True)`，路径字段（`source.path` / `transcript.audio_path` / `transcript.path` / `errata_path` / `render_opts.output_dir` / `output_dir`）都是 `str`。
- Plan T9 step 3 要求「相对路径相对 `meta.root` 解析成绝对」。
- **结论**：用 `dataclasses.replace` 递归重建一份**路径已解析成绝对**的 `ProjectConfig` 返回（spec 也是 frozen，同样用 `replace`）。原始 yaml 内容不动，磁盘上的 `project.yaml` 仍是相对路径；T9 返回的是「运行时视图」。验收「load 读回字段与 create 返回一致（路径解析成绝对）」即此意——create 返回相对占位，load 返回绝对，二者**在「相对 root 解析后」语义上等价**（测试按此断言，见自测 2）。

### 出入 3：Meta-Brief 没提 errata 合并，Plan step 4 提了——T9 **不做**

- Plan T9 step 4：「errata 合并：`errata_path` 指向的 `corrections.yaml` 用 `config.build_errata_config` 合并成 `ErrataConfig`，挂到 cfg 的运行时视图（或由 ProjectRun 在用时取，二选一，文档说明）」。
- Meta-Brief（本任务实际指令）**完全没提 errata 合并**，只要求 strict 模式校验 errata 文件存在性。
- **结论**：见 Q1。**默认 T9 不合并 errata、不往 `ProjectConfig` 挂 `ErrataConfig`**（保持 schema 纯净，单一职责）。T9 只在 `strict=True` 时校验 `errata_path` 文件**存在**；`ErrataConfig` 的实际构造留给 T11 `ProjectRun` 在用时调 `build_errata_config(resolved_errata_path)`（Plan 给的二选一之 B）。理由：(a) `ProjectConfig` 没有 errata 字段，挂载需改 schema（违反「不改 schema」红线）；(b) errata 是运行期数据（勘误会迭代），不应固化进 config 快照；(c) Meta-Brief 没要求，越界风险高。

### 出入 4：路径输入判定——文件 vs 目录的歧义

- Meta-Brief / Plan：`path` 既可是 `project.yaml` 文件路径，也可是项目根目录。
- **结论**：见 Q2。**默认用 `pathlib.Path` 判定**：`is_file()` → 当 yaml 用；`is_dir()` → 找 `<dir>/project.yaml`；都不是或目录下无 `project.yaml` → `ConfigError`（信息说清「既不是 yaml 文件，也不是含 project.yaml 的目录」）。不靠后缀名猜（`.yaml` 后缀的目录理论上存在，虽然怪）。

> 若人审对以上四点有异议，开工前拍板；否则按上述默认走。

---

## 核心目标

### 1. 新建 `src/garden_core/project/load.py`

```
src/garden_core/project/
├── __init__.py      # T7/T8 已存在 —— T9 追加 re-export load_project
├── schema.py        # T7，不动
├── config.py        # T7，不动
├── create.py        # T8，不动
└── load.py          # ★ T9 新增
```

- `load.py` 只 import T7/T8 公开符号（`ProjectConfig` / `validate` / 各 spec）+ `config.ConfigError` / `config.load_yaml`，**不重复定义任何类型**。
- `project/__init__.py` 的 `__all__` 追加 `"load_project"`，并 `from garden_core.project.load import load_project`。

### 2. `load_project` 签名（按 Meta-Brief + Plan）

```python
def load_project(
    path: str | Path,
    *,
    strict: bool = True,
) -> ProjectConfig: ...
```

- `path`：`project.yaml` 文件路径 **或** 项目根目录（自动找 `<path>/project.yaml`）。判定见出入 4 / Q2。
- `strict`：
  - `True`（默认）：T7 结构/引用/范围校验 **+** 文件存在性校验（见 §4）。
  - `False`：只跑 T7 的 `validate(cfg)`，不查任何文件存在性（用于「create 后未运行」的项目）。
- 返回：路径已解析成绝对的 `ProjectConfig`（见 §3）。

### 3. 加载流程（按 Plan step 1–3 + 5）

```
1. 定位 project.yaml（Q2）
2. load_yaml(project.yaml_path) → dict（空文件 → ConfigError）
3. ProjectConfig.from_dict(d) → raw cfg（路径仍是 yaml 里的原样，可能相对）
4. 解析 meta.root：若相对 → 相对 cwd 解析成绝对（root 是路径锚点，必须先定）
5. 路径解析（Q3）：对 raw cfg 用 dataclasses.replace 递归重建，
   把所有相对路径字段相对 meta.root 解析成绝对；已是绝对路径则原样保留
6. validate(resolved_cfg)（T7，结构/引用/范围；不查文件）
7. strict=True 时：文件存在性校验（§4）；strict=False 跳过
8. return resolved_cfg
```

- 步骤 4 关键：`meta.root` 是所有相对路径的锚。若 yaml 里 `meta.root` 写的是相对路径，先 `(cwd / root).resolve()`；若是绝对路径，直接 `Path(root).resolve()`。create_project 写的是绝对（`str(root.resolve())`），手写 yaml 可能写相对——两种都正确处理。
- 步骤 5 路径解析范围（逐字段）：
  - `meta.root`：步骤 4 已解析。
  - 每个 `source.path`：相对 root 解析。
  - `transcript.audio_path` / `transcript.path`：相对 root 解析。
  - `errata_path`：相对 root 解析。
  - `render_opts.output_dir` / `output_dir`：相对 root 解析（目录路径，无需存在性校验，仅解析）。
- 「相对 / 绝对」判定：`Path(p).is_absolute()`。绝对则原样（仍 `.resolve()` 收敛符号但**不强制要求文件存在**——用 `Path(p).resolve(strict=False)` 或手动 `(root / p).resolve() if not abs else Path(p).resolve()`，注意 `Path.resolve(strict=False)` 在旧 Python 上行为差异，**用 `(root / p if not abs else p)` 再 `.absolute()` 拼接，不调会抛的 resolve**）。

### 4. `strict=True` 文件存在性校验（缺什么报什么）

- 检查项（**全部检查，一次性聚合**，不命中一个就停）：
  1. 每个 `source.path`（解析后绝对路径）→ `Path(...).is_file()`。
  2. `transcript.audio_path`（解析后）→ `is_file()`。
  3. `transcript.path`（解析后）→ `is_file()`。
  4. `errata_path`（解析后）→ `is_file()`。
- **不检查** `render_opts.output_dir` / `output_dir`（目录会在运行时由各 stage 自建，存在性无意义）。
- 任一缺失 → 收集到列表，**统一抛一个 `ConfigError`**，信息列出全部缺失路径，例如：

  ```
  ConfigError: project "<name>": missing required files (strict=True):
    - source SRC1: <abs-path> (source.path)
    - source SRC2: <abs-path> (source.path)
    - transcript.audio_path: <abs-path>
    - transcript.path: <abs-path>
    - errata_path: <abs-path>
  Use strict=False to skip file-existence checks.
  ```

- 「缺什么报什么」= 一次报全（不让用户改一个重跑再发现下一个）。
- 注意：strict 校验在 `validate` **之后**（先保证结构合法，再查文件；结构坏时文件检查无意义）。

### 5. 错误语义汇总

| 场景 | 抛 | 来源 |
|---|---|---|
| `path` 既非 yaml 文件也非含 project.yaml 的目录 | `ConfigError` | T9 step 1（Q2） |
| `project.yaml` 空文件 / 不存在 | `ConfigError` | T9 step 2 |
| `from_dict` 缺必填字段（如 `transcript` 整块缺失） | `KeyError`/`TypeError`？ | T7 from_dict（`TranscriptSpec.from_dict` 取 `d["audio_path"]`，无 fallback）→ **T9 包一层**，转 `ConfigError`（信息含 yaml 路径 + 缺字段线索）。见 Q4。 |
| 结构/引用/范围不合法（坏 source_id、重复 id、style 不存在、start≥end…） | `ConfigError` | T7 `validate` |
| `strict=True` 且文件缺失 | `ConfigError`（聚合列表） | T9 §4 |

---

## 需人拍板

### Q1：T9 要不要把 errata 合并成 `ErrataConfig` 挂到返回值？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **不合并、不挂载**。T9 只在 strict=True 校验 `errata_path` 文件存在；`ErrataConfig` 构造留给 T11 `ProjectRun` 在用时调 `build_errata_config(resolved_errata_path)`。Meta-Brief 没要求 errata 合并。 |
| B | T9 调 `build_errata_config` 把 `ErrataConfig` 挂到 `ProjectConfig`（需新增字段，改 schema）。 | 违反「不改 schema」红线 + 越界 Meta-Brief。 |
| C | T9 提供独立 helper `load_errata(cfg) -> ErrataConfig`（不改 schema，但多一个公开函数）。 | 可选增强；默认不做，留给 T11。 |

> **默认 A**：T9 单一职责 = 「加载 + 校验 project.yaml 成 ProjectConfig」。errata 是运行期数据，由 ProjectRun 取。

### Q2：`path` 是文件还是目录怎么判？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `Path(path).is_file()` → 当 yaml；`is_dir()` → 找 `<dir>/project.yaml`，没有则 `ConfigError`；既非文件也非目录（不存在）→ `ConfigError`（信息：「path 不存在」）。不靠后缀名。 |
| B | 按后缀 `.yaml`/`.yml` 判文件，否则当目录。 | 后缀不可靠（目录可能带后缀，文件可能无后缀）。 |

> **默认 A**：`is_file` / `is_dir` 语义清晰，覆盖「不存在」分支。

### Q3：相对路径解析的「绝对/相对」判定 + 解析方式？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `Path(p).is_absolute()` 为真 → 原样（仅 `.resolve(strict=False)` 收敛符号，不要求存在）；为假 → `(resolved_root / p)` 拼接。`resolved_root = Path(meta.root).resolve()`，若 `meta.root` 相对则相对 cwd 先 resolve。 |
| B | 不解析，原样返回 yaml 里的字符串。 | 违反 Plan step 3 + 验收「路径解析成绝对」。 |

> **默认 A**。注意 Python 3.10+ `Path.resolve(strict=False)` 对不存在路径不抛错（3.6+ 行为）；实现时显式传 `strict=False`，并在注释里说明，避免 3.5 语义歧义（本仓库 Python 3.11/3.12，安全）。

### Q4：`from_dict` 缺必填字段时抛 `KeyError`/`TypeError`，要不要包成 `ConfigError`？

| 选项 | 做法 |
|---|---|
| **A（默认）** | T9 在 `from_dict` 调用外层 try/except，把 `KeyError`/`TypeError`/`ValueError` 包成 `ConfigError(f"project.yaml {path}: {原信息}")`。统一错误家族（T7 validate 抛 `ConfigError`，调用方只 catch 一种）。 |
| B | 不包，原样抛 `KeyError`。 | 错误类型不统一，调用方需 catch 多种。 |

> **默认 A**：统一 `ConfigError` 家族，对调用方友好（T11 ProjectRun 只 catch `ConfigError`）。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **T7 `project/config.py`**（已读全文）：
  - `ProjectConfig.from_dict(d)`：读顶层 `meta` / `sources` / `transcript` / `errata_path`（默认 `"corrections.yaml"`）/ `proof_opts` / `cut_points` / `style_name`（默认 `"default"`）/ `render_opts` / `output_dir`（默认 `"output"`）。
  - `ProjectConfig.from_yaml(path)`：`load_yaml` → 空则 `ConfigError` → `from_dict`。**不 validate、不解析路径**。
  - `validate(cfg)`：sources 非空 + id 唯一 + cut_point.source 引用合法 + 时间轴在 source 范围 + style_name 在全局 styles 目录 + clip_id 唯一 + start<end。**不查文件存在性**（T7 Q1 默认 A）→ strict=False 的纯结构校验正好是它。
  - `ProjectConfig` frozen；`sources`/`cut_points` 是 tuple。
- **T7 `project/schema.py`**（已读全文）：各 spec 均 frozen，`from_dict` 对必填字段（`SourceSpec.id`/`path`、`TranscriptSpec.audio_path`/`path`、`CutPointSpec.clip_id`/`source`/`start_s`/`end_s`）用 `d["key"]` 直取，缺则 `KeyError`（Q4 包错点）。`RenderOptsSpec.output_dir` 默认 `"output/clips"`；`ProjectMeta(name, root)` 均 `str(d.get(..., ""))` 有 fallback。
- **`config.py`**（已读）：`load_yaml(path)` 不存在返回 `{}`，空文件返回 `{}`；`ConfigError(ValueError)`；`build_errata_config(path)` 对空/缺失返回 `ErrataConfig.empty()`（T9 strict=True 时 `errata_path` 缺失会先被 §4 文件校验拦下，不会进到 build_errata_config）。
- **T8 `create.py`**（已读全文）：`create_project` 写 `meta.root = str(root.resolve())`（绝对）、`transcript.audio_path = source/<name>.wav`（相对占位）、`transcript.path = output/transcript.json`（相对）、`errata_path = corrections.yaml`（相对）、`source.path` 由调用方传（通常相对 `source/`）。create 返回的 cfg 路径是**相对**的；T9 load 后应是**绝对**（相对 root 解析）。这是 create→load 等价测试的断言要点。
- **`stage_style/styles/`**：`fresh.yaml` / `default.yaml` 等 8 个。手写 tesla 形状 yaml 用 `style_name: default` 或 `fresh` 都能过 validate。
- **示例数据卫生**（AGENTS.md）：测试用 `tmp_path` + 占位 SourceSpec（`SourceSpec(id="SRC1", path="source/ep01.mp4")`），**禁止**真实 tesla 路径 / 真实 clip 标题 / 真实 errata。

---

## 验收标准

1. **新建 `src/garden_core/project/load.py`** + `project/__init__.py` 追加 re-export `load_project`：`from garden_core.project import load_project` 可达。
2. **create → load 闭环**：`create_project("demo", tmp, sources=[SourceSpec("SRC1", "source/ep01.mp4")])` 后，`load_project(tmp, strict=False)` 读回的 `ProjectConfig` 与 create 返回值**在「相对 root 解析后」语义等价**：`meta.name`/`meta.root`/`sources`（id/timeline/offset 相等，`source.path` 解析成绝对且指向 `tmp/source/ep01.mp4`）/`style_name`/`render_opts`/`transcript`（`audio_path`→`tmp/source/demo.wav`、`path`→`tmp/output/transcript.json`）/`errata_path`→`tmp/corrections.yaml`/`cut_points==()` 全部一致。
3. **传文件路径 == 传根目录**：`load_project(tmp/"project.yaml", strict=False)` 与 `load_project(tmp, strict=False)` 返回的 cfg 相等。
4. **手写 tesla 形状 yaml 能 load**：在 `tmp` 手写一份多源 + cut_points + style 的 `project.yaml`（值全占位），`load_project(tmp, strict=False)` 成功，断言 sources/cut_points/render_opts 字段正确解析；cut_points 的 source 引用、时间轴范围通过 validate。
5. **strict=False 不查文件**：create 后（source/transcript/errata 文件均不存在，只有 corrections.yaml 是空 `{}`）`load_project(tmp, strict=False)` 不抛。
6. **strict=True 缺文件聚合报错**：create 后（无 source 媒体、无 transcript.json、无 source audio），`load_project(tmp, strict=True)` 抛 `ConfigError`，信息**同时**列出缺失的 source.path / transcript.audio_path / transcript.path（corrections.yaml 由 create 创建，存在，不在缺失列表）。补齐所有文件后 strict=True 通过。
7. **strict=True 缺什么报什么**：构造只缺 `transcript.path` 的场景（其他文件都 touch 出来），`ConfigError` 信息只列 `transcript.path` 一项。
8. **非法 yaml 报 ConfigError**：手写 `project.yaml` 含坏 source_id（cut_point 引用不存在的 source）→ `load_project(tmp, strict=False)` 抛 `ConfigError`（validate 抛，信息含坏 id）。
9. **缺必填字段报 ConfigError**：手写 `project.yaml` 缺 `transcript` 块 → `ConfigError`（Q4 包错，信息含 yaml 路径 + 线索）。
10. **路径不存在报 ConfigError**：`load_project(tmp/"nonexistent")` → `ConfigError`（信息说「path 不存在」）；`load_project(tmp/"not_a_yaml.txt")`（既非 yaml 也非含 project.yaml 的目录）→ `ConfigError`。
11. **不破坏现有代码**：`pytest tests/` 全绿；T7/T8 的 `schema.py` / `config.py` / `create.py` / `__init__.py`（除追加 re-export）**零改动**；三入口 `run_from_audio` / `run_from_transcript` / `run_montage` 行为不回归。

**pytest / 校验命令**：
```bash
# 可达性
python -c "from garden_core.project import load_project; print('ok')"
# 专项
python -m pytest tests/test_load_project.py -v
# 全量回归
python -m pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 project/load.py (新增) + project/__init__.py (追加 re-export) + tests/test_load_project.py (新增)
# 卫生检查（无真实 tesla 数据泄露）
grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>" src/garden_core/project/load.py tests/test_load_project.py
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ 新建 `src/garden_core/project/load.py` | ❌ 改 T7 的 `schema.py` / `config.py`（只 import 复用） |
| ✅ `project/__init__.py` 追加 `load_project` 到 `__all__` + import | ❌ 改 `ProjectConfig` / 任何 spec 的字段或默认值（「不改 schema」铁律） |
| ✅ 新建 `tests/test_load_project.py` | ❌ 新建/改 `create_project`（那是 T8，已落地） |
|  | ❌ 给 `ProjectConfig` 加 `ErrataConfig` 字段（Q1 默认 A，越界 + 改 schema） |
|  | ❌ 实现 `ErrataConfig` 合并 / `load_errata` helper（Q1 默认 A，留给 T11） |
|  | ❌ 新建 `ProjectRun` / `run_manifest`（那是 T11） |
|  | ❌ 改 `config.py`（`load_yaml` / `build_errata_config` / `ConfigError` 只 import） |
|  | ❌ 实现项目修改 / CRUD / `save_project`（那是 T10） |
|  | ❌ `pipeline.py` / `scripts/*.py` / `stage_*`（T9 不碰） |
|  | ❌ 在测试里放真实 tesla 数据（卫生铁律） |

---

## 自测方法

1. **可达性**（验收 1）：`python -c "from garden_core.project import load_project"`。
2. **create → load 等价**（验收 2）：`tmp_path` → `cfg_create = create_project("demo", tmp_path, sources=[SourceSpec("SRC1", "source/ep01.mp4")])` → `cfg_load = load_project(tmp_path, strict=False)` → 逐字段断言：`meta.name`/`meta.root` 相等；`cfg_load.sources[0].id == "SRC1"`；`cfg_load.sources[0].path == str(tmp_path / "source" / "ep01.mp4")`（绝对）；`cfg_load.transcript.audio_path == str(tmp_path / "source" / "demo.wav")`；`cfg_load.transcript.path == str(tmp_path / "output" / "transcript.json")`；`cfg_load.errata_path == str(tmp_path / "corrections.yaml")`；`cfg_load.style_name == "fresh"`；`cfg_load.cut_points == ()`。
3. **文件路径 == 根目录**（验收 3）：`load_project(tmp_path / "project.yaml", strict=False) == load_project(tmp_path, strict=False)`（dataclasses 相等比较；注意路径解析后两者应完全相等）。
4. **手写 tesla 形状**（验收 4）：在 `tmp_path/project.yaml` 用 `yaml.safe_dump` 写一份多源 + cut_points + style=default 的配置（值全占位 `source/part1.mp4` 等，**不 touch 真实文件**），`load_project(tmp_path, strict=False)` 成功，断言 `len(cfg.sources)==2`、`len(cfg.cut_points)==N`、cut_points 的 source 引用解析正确、时间轴范围通过。
5. **strict=False 不查文件**（验收 5）：create 后直接 `load_project(tmp_path, strict=False)` 不抛（验收 2 已覆盖，单列一条断言显式）。
6. **strict=True 聚合报错**（验收 6）：create 后 `load_project(tmp_path, strict=True)` → `pytest.raises(ConfigError)`；`str(e)` 同时含 `"source"`/`"SRC1"`、`"transcript.audio_path"`、`"transcript.path"`，**不含** `errata_path`（corrections.yaml 存在）。然后 `touch` 出 `source/ep01.mp4` / `source/demo.wav` / `output/transcript.json` → `load_project(tmp_path, strict=True)` 通过。
7. **缺什么报什么**（验收 7）：上一条全 touch 后，删掉 `output/transcript.json` → `load_project(tmp_path, strict=True)` 抛 `ConfigError`，信息只含 `transcript.path`。
8. **坏 source_id**（验收 8）：手写 `project.yaml`（strict=False）含 `cut_points: [{clip_id: t01, source: NOPE, start_s: 0, end_s: 10}]` → `pytest.raises(ConfigError)` + `"NOPE"` 在信息里。
9. **缺 transcript 块**（验收 9）：手写 `project.yaml` 不写 `transcript` 键 → `pytest.raises(ConfigError)`（Q4 包错，信息含 yaml 路径）。
10. **路径不存在 / 非 yaml**（验收 10）：`load_project(tmp_path/"nonexistent")` → `ConfigError`；`load_project(tmp_path/"README.md")`（文件但非含 project.yaml 的目录、且本身不是 project.yaml）→ `ConfigError`。
11. **diff 范围**（验收 11）：`git diff --name-only` 仅 `project/load.py`（新增）+ `project/__init__.py`（追加）+ `tests/test_load_project.py`（新增）。
12. **回归**：`pytest tests/ -v` 全绿（T9 纯新模块，T7/T8 测试保持绿；三入口测试不回归）。
13. **卫生检查**：`grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>" src/garden_core/project/load.py tests/test_load_project.py` 无命中。

---

## 风险

- **无破坏性**：纯新模块（`load.py` + `__init__.py` 追加 re-export + tests），不碰 T7 schema/config、不碰 T8 create、不碰任何现有文件。`pytest tests/` 应全绿。
- ⚠️ **路径解析改变 cfg 形状**（出入 2）：load 返回的 cfg 路径是绝对，与磁盘 yaml（相对）和 create 返回值（相对）不同。这是设计意图（运行时视图），但需在测试里按「解析后等价」断言（自测 2），不能直接 `cfg_load == cfg_create`（会因路径相对/绝对不等而失败）。文档/`load.py` docstring 需说明「返回值路径已解析成绝对」。
- ⚠️ **`Path.resolve(strict=False)` 跨平台**：Windows 上 `/` 与 `\` 混用、符号链接。本仓库 Windows + conda garden，Python 3.11/3.12，`resolve(strict=False)` 安全。实现时统一用 `pathlib`，不手搓字符串拼接。
- ⚠️ **strict 聚合报错 vs 早停**：本 brief 默认「全部检查一次性聚合」（§4）。若人审要「命中第一个就停」，简化实现但用户体验差（改一个重跑再发现下一个）。默认聚合。
- **Meta-Brief 没提 errata 合并**（出入 3 / Q1）：默认不做，留给 T11。若人审要 T9 就合并，需另开任务改 schema 或加 helper，不在 T9 范围。
- **依赖 T7/T8 已落地**：T9 建立在 T7（schema/config/validate）+ T8（create 闭环）之上。二者已验收，本 brief 假设其冻结。

# RX Brief · T10 — `edit_project`（修改项目配置 + 重校验 + 持久化）

> **一句话**：新建 `src/garden_core/project/edit.py`，实现唯一公开入口 `edit_project(root_dir, **overrides) -> ProjectConfig`——流程 `定位 project.yaml → 原样读取（**不**解析路径成绝对，保持磁盘上的相对路径表示）→ dataclasses.replace 逐字段覆盖（嵌套 frozen spec 用 dict 部分合并或整实例替换）→ validate 重校验 → to_yaml 写回同一 `project.yaml` → 返回新 cfg`。纯新模块，**不改 schema**、不动 T7/T8/T9。保护铁律：edit 只覆写 `project.yaml` 一个文件，**绝不删/动任何数据文件**（source 媒体 / transcript / corrections.yaml / output 产物全部原样保留）。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第二层 · 项目管理系统」→ **T10 · 项目修改 + 配置管理（CRUD + 重校验 + 持久化）**（D1；依赖 T7、T9）。`IMPLEMENTATION_PLAN.md` L28/L84（T10 风险：frozen + 返回新实例；force 策略需 brief 锁定）。

---

## ⚠️ 执行前必读：Meta-Brief / Plan 与 T7-T9 已落地代码的出入

Meta-Brief 的指令是**单一函数** `edit_project(root_dir, **overrides) -> ProjectConfig`，流程「load → 逐字段覆盖 → validate → 写回」，frozen 用 replace 重建，保护数据文件。但 Plan T10 原文（L382-394）给的是一整套**粒度 CRUD**（`add_source` / `remove_source(force=)` / `add_cut_point` / `update_cut_point` / `remove_cut_point` / `set_style` / `update_render_opts` / `update_proof_opts` / `set_errata` / `save_project` / `diff_projects`）。二者形状差异大。对照 T7-T9 已落地代码，有五处必须澄清。**默认按「Meta-Brief + 卡帕西 Simplicity First」走**：

### 出入 1：Meta-Brief 只要 `edit_project`，Plan 要整套 CRUD —— 默认只做 `edit_project`

- Meta-Brief 明确把 T10 收敛为 `edit_project(root_dir, **overrides)`。卡帕西四原则 #2「最简代码，无投机、无过度抽象」。
- Plan 的粒度函数大部分**被 `edit_project` 的 `**overrides` 直接覆盖**：
  - `set_style` → `edit_project(root, style_name="fresh")`
  - `update_render_opts(**fields)` → `edit_project(root, render_opts={"crf": 20})`（嵌套 dict 合并，见 Q4）
  - `update_proof_opts(**fields)` → `edit_project(root, proof_opts={"enable_llm": True})`
  - `set_errata(path)` → `edit_project(root, errata_path="corrections.yaml")`
  - `add_cut_point` / `remove_cut_point` / `add_source` → 调用方传完整 `cut_points` / `sources` tuple（见 Q4）
- **唯一 `edit_project` 表达不了的**：`remove_source(source_id, force=)` 的「删除被引用 source 时，force=True 连带清 cut_points / force=False 禁止」这条**安全策略**。`edit_project` 接收的是已算好的 tuple，绕过引用检查。但 `validate()` 仍会兜底——若删了 source 没清 cut_points，validate 当场抛 `ConfigError`（坏 source 引用），等价于「force=False」的禁删效果（见 Q1）。
- **结论**：默认**只实现 `edit_project`**（+ 见出入 4 的 save）。Plan 的粒度 CRUD **全部 defer**——它们是纯便利层，可由调用方组合 `edit_project` + `validate` 达成；不在 T10 范围内增加 10 个函数。见 Q1。

### 出入 2：`load` 用 T9 的 `load_project` 会把路径解析成绝对 → 写回会破坏「相对路径」磁盘约定

- T9 `load_project` 返回的 cfg **所有路径字段是绝对的**（相对 `meta.root` 解析后的「运行时视图」）。
- T8 `create_project` 写出的 `project.yaml` 是**相对路径**（`source/<name>.wav` / `output/transcript.json` / `corrections.yaml`）。
- 若 `edit_project` 内部用 `load_project(root)` 读，再 `cfg.to_yaml(...)` 写回，**磁盘上的相对路径会被永久改写成绝对路径**——破坏 T8 约定 + 让 project.yaml 不可移植（绑死到某台机器的绝对路径）。
- **结论**：`edit_project` 的「load」**不调 `load_project`**，而是 `load_yaml(path) → ProjectConfig.from_dict(d)`（**原样读，路径保持 yaml 里的写法**）。validate（T7，**不查文件存在性**）照常跑。写回时 `to_yaml` 自然写出原始（相对/绝对）路径表示。即：edit_project 返回的是「**配置视图**」（与磁盘一致），不是 T9 的「运行时视图」（绝对）。两种视图并存是设计意图，docstring 说明。见 Q2。

### 出入 3：edit 要不要 strict 查文件存在性？—— 默认**不查**

- 编辑配置 ≠ 投产运行。用户改 `style_name` / `render_opts.crf` 时，source 媒体可能还没就位。
- T9 `load_project(strict=True)` 会因缺文件抛 `ConfigError`，对「编辑」场景过于严格。
- **结论**：`edit_project` **永远只跑 T7 `validate()`**（结构/引用/范围），**不查任何文件存在性**。strict 行为留给调用方（要查就先 `load_project(root, strict=True)` 再 edit，或 edit 后再 load 校验）。见 Q3。

### 出入 4：写回是 edit_project 内联完成，还是另起 `save_project`？

- Meta-Brief：「load → 逐字段覆盖 → validate → **写回** project.yaml」——写回是 `edit_project` 流程的一步，**隐式内置**。
- Plan：把写回拆成独立 `save_project(cfg, path=None)`。
- **结论**：按 Meta-Brief——`edit_project` **写回是调用的一部分**（默认写回 `<root>/project.yaml`，覆盖原文件）。**不另起 `save_project`**（surgical：不增加未被 Meta-Brief 要求的函数；T12 `reproofread` 若需要「改 errata + 不落盘」可直接构造 cfg + `to_yaml`，或后续另开任务）。见出入 5 的原子写。

### 出入 5：写回的原子性 / 保护数据文件

- AGENTS.md 铁律 + Meta-Brief「保护：不删已有数据文件」。
- `edit_project` 只 `open(project.yaml, "w")` 覆写**一个文件**，不 `os.remove` / `shutil.rmtree` 任何东西——source 媒体 / transcript / corrections.yaml / output/ 全部原样。
- 写回用「先写临时文件 `project.yaml.tmp` → `os.replace` 原子替换」避免半写损坏（Windows `os.replace` 原子）。见 Q5。
- edit 前若 `project.yaml` 不存在 → `ConfigError`（edit 是「改已有」，不是 create；指向 `create_project`）。

> 若人审对以上五点有异议，开工前拍板；否则按上述默认走。

---

## 核心目标

### 1. 新建 `src/garden_core/project/edit.py`

```
src/garden_core/project/
├── __init__.py      # T7/T8/T9 已存在 —— T10 追加 re-export edit_project
├── schema.py        # T7，不动
├── config.py        # T7，不动
├── create.py        # T8，不动
├── load.py          # T9，不动
└── edit.py          # ★ T10 新增
```

- `edit.py` 只 import T7/T9 公开符号（`ProjectConfig` / `validate` / 各 spec）+ `config.ConfigError` / `config.load_yaml`，**不重复定义任何类型**、不 import T9 的私有 `_locate_yaml`（见出入 2，自己内联定位，~6 行）。
- `project/__init__.py` 的 `__all__` 追加 `"edit_project"`，并 `from garden_core.project.edit import edit_project`。

### 2. `edit_project` 签名（按 Meta-Brief）

```python
def edit_project(
    root_dir: str | Path,
    /,
    **overrides: Any,
) -> ProjectConfig: ...
```

- `root_dir`：项目根目录 **或** `project.yaml` 文件路径（与 T9 `load_project` 的 `path` 同语义，便于复用习惯）。定位见出入 2 / Q2。
- `**overrides`：ProjectConfig 的**顶层字段名**作 key（见 §3 白名单）。未知 key → `ConfigError`（typo 守卫，如 `stlye_name` 误写当场报）。
- 返回：**新** `ProjectConfig`（frozen，replace 重建），路径表示与磁盘一致（出入 2）。**同时**已写回 `<root>/project.yaml`（覆盖）。
- 保护：仅覆写 `project.yaml`；不碰任何数据文件（出入 5）。

### 3. 覆盖流程（按 Meta-Brief「load → 逐字段覆盖 → validate → 写回」）

```
1. 定位 project.yaml（Q2）：is_file → 用；is_dir → <dir>/project.yaml；不存在 → ConfigError。
2. load_yaml(yaml_path) → dict；空/非 dict → ConfigError。
3. ProjectConfig.from_dict(d) → cfg（原样，路径不解析）。
4. 逐字段覆盖（Q4）：
   a. 校验每个 override key 在白名单 {meta, sources, transcript, errata_path,
      proof_opts, cut_points, style_name, render_opts, output_dir}；未知 → ConfigError。
   b. 标量字段（errata_path / style_name / output_dir）：dataclasses.replace(cfg, key=value)。
   c. 嵌套 spec 字段（meta / transcript / proof_opts / render_opts）：
      - value 是对应 spec 实例 → 整替换。
      - value 是 dict → 与现有 spec 做部分合并：dataclasses.replace(existing_spec, **dict)
        （dict 的 key 必须是该 spec 的合法字段名，否则 replace 抛 TypeError → 包成 ConfigError）。
   d. 集合字段（sources / cut_points）：
      - value 是 tuple/list → 整替换；元素可为 spec 实例或 dict（dict → 对应 spec.from_dict 转换）。
      - 统一成 tuple（保持 frozen 不变性）。
5. validate(new_cfg)（T7，结构/引用/范围；不查文件）→ 非法当场 ConfigError，**不写盘**。
6. 原子写回：new_cfg.to_yaml(yaml_path)（出入 5：tmp + os.replace）。
7. return new_cfg。
```

- 步骤 5 是「改完即校验」的铁律落地：越界 cut_point / 坏 source 引用 / 重复 clip_id / 未知 style / start≥end → 全部在写盘前抛 `ConfigError`，**磁盘 project.yaml 保持 edit 前状态**（因为还没写）。
- 步骤 4c 的「dict 部分合并」是让 `edit_project(root, render_opts={"crf": 20})` 等价于 Plan 的 `update_render_opts(crf=20)` 的最小机制（~3 行/字段，不引入新函数）。

### 4. 错误语义汇总

| 场景 | 抛 | 来源 |
|---|---|---|
| `root_dir` 不存在 / 既非 yaml 文件也非含 project.yaml 的目录 | `ConfigError` | T10 step 1（Q2） |
| `project.yaml` 空文件 / 非 dict | `ConfigError` | T10 step 2 |
| `from_dict` 缺必填字段 | `ConfigError`（包 KeyError/TypeError） | T7 from_dict（同 T9 Q4 处理） |
| `overrides` 含未知 key（typo） | `ConfigError` | T10 step 4a（typo 守卫） |
| 嵌套 spec 的 dict 含非法字段名 | `ConfigError`（包 TypeError） | T10 step 4c |
| 覆盖后结构/引用/范围非法（坏 source 引用 / 越界 / 重复 id / 未知 style / start≥end） | `ConfigError` | T7 `validate`（写盘前） |
| 写盘失败（权限/磁盘满） | 原生 `OSError` | T10 step 6（不吞，但 tmp + os.replace 保证原文件不被半写破坏） |

---

## 需人拍板

### Q1：范围——只做 `edit_project`，还是连 Plan 的整套 CRUD 一起做？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **只做 `edit_project(root_dir, **overrides)`**。粒度 CRUD 全部 defer。理由：`edit_project` + `validate` 组合可覆盖 set_style/update_render_opts/update_proof_opts/set_errata/add/remove（传完整 tuple）；`remove_source` 的「force 禁删被引用」安全语义由 `validate` 兜底（删 source 不清 cut_points → validate 抛坏引用 → 等价 force=False 禁删）。卡帕西 Simplicity First。 |
| B | 同时实现 Plan 的 10 个函数。 | 越界 Meta-Brief；10 个函数大多是被 `edit_project` 覆盖的便利层，违反「无过度抽象」。 |

> **默认 A**。若后续 T12 `reproofread` 证明需要 `remove_source(force=True)` 的「连带清 cut_points」便利，另开任务加（不阻塞 T11/T12，因 T12 已注明「set_errata 或直接传 ErrataConfig」）。

### Q2：`root_dir` 是文件还是目录怎么判 + load 用哪个？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `Path(root_dir).is_file()` → 当 yaml；`is_dir()` → `<dir>/project.yaml`，没有则 `ConfigError`；不存在 → `ConfigError`（信息说「不存在，用 create_project 新建」）。**不调 T9 `load_project`**（避免路径被解析成绝对、避免 strict），而是 `load_yaml → from_dict` 原样读（出入 2）。内联定位 ~6 行，不 import T9 私有 `_locate_yaml`。 |
| B | 复用 T9 `load_project(root, strict=False)` 读。 | 路径被解析成绝对 → 写回破坏相对路径约定（出入 2）。**否决**。 |

> **默认 A**。

### Q3：edit 要不要 strict 查文件存在性？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **不查**。永远只跑 T7 `validate()`（结构/引用/范围）。编辑配置不应依赖媒体文件就位。 |
| B | 默认 strict=True（同 T9）。 | 编辑场景过严（改 style 时 source 可能没就位）。 |

> **默认 A**。要查存在性由调用方 `load_project(root, strict=True)` 自行做。

### Q4：嵌套 spec / 集合字段的 override 语义？

| 选项 | 做法 |
|---|---|
| **A（默认）** | 标量字段（errata_path/style_name/output_dir）直替换；嵌套 spec（meta/transcript/proof_opts/render_opts）接受「实例→整替换 / dict→部分合并（replace(existing, **dict)）」；集合（sources/cut_points）接受「tuple/list→整替换，元素可实例或 dict（dict→from_dict 转）」，统一成 tuple。等价于 Plan 的 update_render_opts/update_proof_opts 的最小实现，不新增函数。 |
| B | 嵌套只接受整实例，不支持 dict 部分合并。 | 失去 `render_opts={"crf":20}` 的人体工学，调用方需手搓完整 `RenderOptsSpec(...)`。 |

> **默认 A**（~10 行实现，非过度抽象；覆盖 Plan 的 update_* 人体工学）。

### Q5：写回用原子替换还是直接覆写？

| 选项 | 做法 |
|---|---|
| **A（默认）** | 原子替换：写 `project.yaml.tmp` → `os.replace(tmp, project.yaml)`（Windows/Linux 均原子）。避免半写损坏原配置。 |
| B | 直接 `to_yaml(project.yaml)` 覆写。 | 写到一半崩溃会留下残缺 yaml，原配置丢失。 |

> **默认 A**。成本 ~3 行，换「edit 永不损坏现有 project.yaml」的保证，符合 Meta-Brief「保护」铁律。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **T7 `project/config.py`**（已读全文）：
  - `ProjectConfig.from_dict(d)` 读 `meta` / `sources`(list) / `transcript` / `errata_path`(默认 `"corrections.yaml"`) / `proof_opts` / `cut_points`(list) / `style_name`(默认 `"default"`) / `render_opts` / `output_dir`(默认 `"output"`)。**不 validate、不解析路径**——正合 edit_project「原样读」需求。
  - `ProjectConfig.to_yaml(path)`：`mkdir(parents=True)` + `yaml.safe_dump(to_dict(), sort_keys=False)`。to_dict 已对默认值做「相等则省略」处理，写出的 yaml 干净。edit_project 写回直接复用。
  - `validate(cfg)`：sources 非空 + id 唯一 + cut_point.source 引用合法 + 时间轴在 source 范围 + style_name 在 styles 目录 + clip_id 唯一 + start<end。**不查文件存在性** → edit 的 validate 安全（改配置不依赖媒体）。
  - `ProjectConfig` frozen；`sources`/`cut_points` 是 tuple。
- **T7 `project/schema.py`**（已读全文）：各 spec frozen。`SourceSpec(id, path, timeline_start_s=0.0, timeline_end_s=None, source_offset_s=0.0)` / `CutPointSpec(clip_id, source, start_s, end_s, style_name="default", title="")` / `RenderOptsSpec(output_dir, horizontal_width, ..., crf, render_horizontal, render_vertical)` / `ProofOptsSpec(enable_normalize, enable_errata, enable_phonetic, enable_llm, enable_dual_channel, llm_temperature)` / `TranscriptSpec(audio_path, path)` / `ProjectMeta(name, root)`。`dataclasses.replace(spec, **dict)` 对 frozen 安全（返回新实例）。`fields(spec)` 可枚举字段名做 dict-key 合法性校验。
- **T9 `project/load.py`**（已读全文）：`load_project` 会 `_resolve_paths` 把所有路径解析成绝对——**edit_project 不复用它**（出入 2）。`_locate_yaml` 是私有函数，edit 不 import，自己内联（Q2）。
- **T8 `project/create.py`**（已读全文）：写出的 `project.yaml` 是**相对路径**（`source/<name>.wav` / `output/transcript.json` / `corrections.yaml`）。edit_project 写回必须保持这个约定（出入 2）——所以 edit 读 `from_dict` 原样、写 `to_yaml` 原样，路径表示不变。
- **`config.py`**（已读）：`load_yaml(path)` 不存在/空文件返回 `{}`；`ConfigError(ValueError)`。edit step 2 检查 `not isinstance(data, dict) or not data` → ConfigError。
- **`stage_style/styles/`**：8 个 yaml 含 `default` / `fresh`。edit 测试用 `style_name="fresh"`/`"default"` 能过 validate。
- **示例数据卫生**（AGENTS.md）：测试用 `tmp_path` + 占位 `SourceSpec(id="SRC1", path="source/ep01.mp4")`，**禁止**真实 tesla 路径 / 真实 clip 标题 / 真实 errata。

---

## 验收标准

1. **新建 `src/garden_core/project/edit.py`** + `project/__init__.py` 追加 re-export：`from garden_core.project import edit_project` 可达。
2. **顶层标量覆盖**：`edit_project(root, style_name="fresh")` / `edit_project(root, errata_path="other.yaml")` / `edit_project(root, output_dir="out")` 改完 `load_project(root, strict=False)` 读回字段一致；磁盘 `project.yaml` 相应 key 更新。
3. **嵌套 spec 部分合并**：`edit_project(root, render_opts={"crf": 20, "render_vertical": False})` → 新 cfg 的 `render_opts.crf==20`、`render_opts.render_vertical is False`、其余 render_opts 字段（horizontal_width 等）**保持原值**；磁盘 yaml 的 `render_opts` 块正确更新。
4. **嵌套 spec 整替换**：`edit_project(root, proof_opts=ProofOptsSpec(enable_llm=True))` → 新 cfg.proof_opts == 传入实例。
5. **集合整替换**：`edit_project(root, sources=(SourceSpec("SRC2","source/b.mp4"),))` → 新 cfg.sources == 该 tuple；`edit_project(root, cut_points=[{"clip_id":"t01","source":"SRC1","start_s":0,"end_s":10}])`（dict 元素自动 from_dict）→ 新 cfg.cut_points 长度 1、字段正确。
6. **改完即校验（写盘前抛）**：`edit_project(root, cut_points=[{"clip_id":"t01","source":"NOPE","start_s":0,"end_s":10}])` → 抛 `ConfigError`（坏 source 引用，信息含 `"NOPE"`）；**磁盘 project.yaml 保持 edit 前内容**（断言文件 mtime/内容未变）。同理 cut_point 越界（end_s 超 source.timeline_end_s）/ start≥end / 重复 clip_id / 未知 style_name → 均 `ConfigError` 且磁盘未动。
7. **remove source 被引用 → validate 兜底**：先 add 一个被 cut_point 引用的 source（写盘成功），再 `edit_project(root, sources=(去掉该 source 的 tuple,))` 不动 cut_points → 抛 `ConfigError`（坏引用）。等价 Plan 的 `remove_source(force=False)` 禁删效果（Q1/A）。
8. **未知 override key → typo 守卫**：`edit_project(root, stlye_name="fresh")` → `ConfigError`（信息含未知 key 名）。
9. **保护数据文件**：create 后往 `source/` / `output/` 放几个占位文件，跑若干次 `edit_project`，断言这些文件**全部还在**、内容未变（edit 只动 `project.yaml`）。
10. **edit 不查文件存在性**：create 后（source 媒体 / transcript.json 均不存在）`edit_project(root, style_name="default")` 成功（不抛 strict 错）。
11. **project.yaml 不存在 → ConfigError**：`edit_project(tmp_path/"nope")` → `ConfigError`（信息指向 `create_project`）。
12. **写回原子性**：edit 后 `project.yaml` 存在且为合法 yaml；无残留 `project.yaml.tmp`。
13. **往返等价**：edit 改任意字段后，`load_project(root, strict=False)` 读回的 cfg（路径解析成绝对的运行时视图）与 edit 返回的 cfg（配置视图）在「相对 root 解析后」语义等价（同 T9 验收 2 的断言口径）。
14. **不破坏现有代码**：`pytest tests/` 全绿；T7/T8/T9 的 `schema.py` / `config.py` / `create.py` / `load.py` / `__init__.py`（除追加 re-export）**零改动**；三入口 `run_from_audio` / `run_from_transcript` / `run_montage` 行为不回归。

**pytest / 校验命令**：
```bash
# 可达性
python -c "from garden_core.project import edit_project; print('ok')"
# 专项
python -m pytest tests/test_project_edit.py -v
# 全量回归
python -m pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 project/edit.py (新增) + project/__init__.py (追加 re-export) + tests/test_project_edit.py (新增)
# 卫生检查（无真实 tesla 数据泄露）
grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>" src/garden_core/project/edit.py tests/test_project_edit.py
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ 新建 `src/garden_core/project/edit.py` | ❌ 改 T7 的 `schema.py` / `config.py`（只 import 复用） |
| ✅ `project/__init__.py` 追加 `edit_project` 到 `__all__` + import | ❌ 改 `ProjectConfig` / 任何 spec 的字段或默认值（「不改 schema」铁律） |
| ✅ 新建 `tests/test_project_edit.py` | ❌ 新建/改 `create_project`（T8）/ `load_project`（T9）（已落地） |
|  | ❌ 实现 Plan 的整套粒度 CRUD（`add_source`/`remove_source`/`add_cut_point`/`update_cut_point`/`remove_cut_point`/`set_style`/`update_render_opts`/`update_proof_opts`/`set_errata`/`diff_projects`）（Q1 默认 A，defer） |
|  | ❌ 实现 `save_project` 独立函数（Q1/A：写回内联进 edit_project） |
|  | ❌ 删除/移动任何数据文件（保护铁律；edit 只覆写 project.yaml） |
|  | ❌ 调用 T9 `load_project` 读 cfg（出入 2：会解析成绝对、破坏相对约定） |
|  | ❌ 新建 `ProjectRun` / `run_manifest`（那是 T11） |
|  | ❌ 改 `config.py`（`load_yaml` / `build_errata_config` / `ConfigError` 只 import） |
|  | ❌ `pipeline.py` / `scripts/*.py` / `stage_*`（T10 不碰） |
|  | ❌ 在测试里放真实 tesla 数据（卫生铁律） |

---

## 自测方法

1. **可达性**（验收 1）：`python -c "from garden_core.project import edit_project"`。
2. **顶层标量覆盖**（验收 2）：`tmp_path` → `create_project("demo", tmp_path, sources=[SourceSpec("SRC1","source/ep01.mp4")])` → `edit_project(tmp_path, style_name="fresh", errata_path="other.yaml")` → 读磁盘 yaml 断言 `style_name: fresh` / `errata_path: other.yaml`；`load_project(tmp_path, strict=False).style_name == "fresh"`。
3. **嵌套部分合并**（验收 3）：`cfg = edit_project(tmp_path, render_opts={"crf":20, "render_vertical":False})` → `cfg.render_opts.crf==20`、`cfg.render_opts.render_vertical is False`、`cfg.render_opts.horizontal_width` 保持 create 默认（3840）。
4. **嵌套整替换**（验收 4）：`cfg = edit_project(tmp_path, proof_opts=ProofOptsSpec(enable_llm=True))` → `cfg.proof_opts.enable_llm is True` 且其余 proof_opts 为默认。
5. **集合整替换 + dict 元素**（验收 5）：`cfg = edit_project(tmp_path, sources=(SourceSpec("SRC2","source/b.mp4"),), cut_points=[{"clip_id":"t01","source":"SRC2","start_s":0,"end_s":5}])` → `cfg.sources[0].id=="SRC2"`、`cfg.cut_points[0].clip_id=="t01"`、`len(cfg.cut_points)==1`。注意：SRC1 被整替换掉（集合语义），cut_points 引用 SRC2 合法 → validate 过。
6. **改完即校验（磁盘未动）**（验收 6）：记录 `project.yaml` 内容 → `edit_project(tmp_path, cut_points=[{"clip_id":"t01","source":"NOPE","start_s":0,"end_s":10}])` → `pytest.raises(ConfigError, match="NOPE")` → 再读 `project.yaml` 断言**与 edit 前逐字节相等**。另测越界（source.timeline_end_s=100 时 cut_point end_s=200 → ConfigError）/ start≥end / 重复 clip_id / `style_name="not_a_style"` → 均 ConfigError 且磁盘未动。
7. **remove source 被引用兜底**（验收 7）：先 `edit_project(tmp_path, sources=(SourceSpec("SRC1","source/a.mp4"), SourceSpec("SRC2","source/b.mp4")), cut_points=[{"clip_id":"t01","source":"SRC2","start_s":0,"end_s":5}])` 成功 → 再 `edit_project(tmp_path, sources=(SourceSpec("SRC1","source/a.mp4"),))`（删 SRC2 不动 cut_points）→ `ConfigError`（cut_point t01 引用不存在的 SRC2）。
8. **typo 守卫**（验收 8）：`edit_project(tmp_path, stlye_name="fresh")` → `ConfigError`（match 未知 key）。
9. **保护数据文件**（验收 9）：create 后 `(tmp_path/"source").mkdir(exist_ok=True)` + 写 `(tmp_path/"source"/"ep01.mp4").write_bytes(b"x")` + `(tmp_path/"output"/"marker.txt").write_text("keep")` → 跑 3 次不同 edit → 断言 `source/ep01.mp4`、`output/marker.txt`、`corrections.yaml`、`AGENTS.md`、`README.md` 全部还在且内容未变。
10. **edit 不查文件**（验收 10）：create 后（无任何媒体/transcript）`edit_project(tmp_path, style_name="default")` 成功（不抛）。
11. **不存在 → ConfigError**（验收 11）：`edit_project(tmp_path/"nope")` → `ConfigError`（信息含 `create_project` 线索）；`edit_project(tmp_path)` 但删掉 `project.yaml` → `ConfigError`。
12. **原子写 / 无残留 tmp**（验收 12）：edit 后 `not (tmp_path/"project.yaml.tmp").exists()`，`project.yaml` 是合法 yaml（`load_yaml` 能读）。
13. **往返等价**（验收 13）：edit 改若干字段后 `cfg_edit = edit_project(...)`、`cfg_load = load_project(tmp_path, strict=False)` → 逐字段断言「相对 root 解析后」等价（`meta.name`/`sources[*].id,timeline,offset`/`style_name`/`cut_points`/`proof_opts`/`render_opts` 全等；路径字段 cfg_load 是绝对、cfg_edit 是原样，按「解析后」口径断言）。
14. **diff 范围**（验收 14）：`git diff --name-only` 仅 `project/edit.py`（新增）+ `project/__init__.py`（追加）+ `tests/test_project_edit.py`（新增）。
15. **回归**：`pytest tests/ -v` 全绿（T10 纯新模块，T7/T8/T9 测试保持绿；三入口测试不回归）。
16. **卫生检查**：`grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>" src/garden_core/project/edit.py tests/test_project_edit.py` 无命中。

---

## 风险

- **无破坏性**：纯新模块（`edit.py` + `__init__.py` 追加 re-export + tests），不碰 T7 schema/config、不碰 T8 create、不碰 T9 load、不碰任何数据文件。`pytest tests/` 应全绿。
- ⚠️ **路径表示二视图**（出入 2）：edit_project 返回「配置视图」（路径与磁盘一致，通常相对），load_project 返回「运行时视图」（绝对）。两者并存是设计意图，但调用方需明白差异——**不要拿 edit_project 的返回值直接喂给依赖绝对路径的运行时代码**（应先 `load_project` 取运行时视图）。docstring + 测试 13 显式说明。
- ⚠️ **集合字段是整替换语义**（Q4/A）：`edit_project(root, sources=(...))` 是**整替换**整个 sources，不是 append。调用方要「新增一个 source」需先读现有 sources 再拼新 tuple。这是 frozen + surgical 的必然（不做粒度 add_source，Q1/A）。文档 + 测试 5 显式断言整替换语义，防误用为 append。
- ⚠️ **写回覆盖原 project.yaml**：edit 是 in-place 覆写。原子替换（Q5/A）保证不半写损坏，但**不保留历史版本**（无备份）。若需版本历史靠 git（项目目录是 git 仓库的话）。不在 T10 范围内做备份。
- ⚠️ **`remove_source(force)` 语义被 defer**（Q1/A）：edit_project 无「连带清 cut_points」的便利；删被引用 source 时 validate 兜底抛错（等价 force=False）。force=True 的「连带删 cut_points」留给可能的后续任务；T11/T12 不依赖它（T12 reproofread 走 errata_path override）。
- **依赖 T7/T8/T9 已落地**：T10 建立在 T7（from_dict/to_yaml/validate）+ T8（create，用于测试脚手架）+ T9（load，用于往返等价断言）之上。三者已验收，本 brief 假设其冻结。

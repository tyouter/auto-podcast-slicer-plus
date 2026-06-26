# RX Brief · T8 — `create_project`（项目脚手架）

> **一句话**：新建 `src/garden_core/project/create.py`，实现 `create_project(name, root_dir, *, sources, audio_path=None, style="fresh", render_opts=None, corrections=None, wiki=False, overwrite=False) -> ProjectConfig`——按 `project-directory-template.md` 建目录树（`source/` + `output/{clips,fullcut,release}` + `corrections.yaml` + `AGENTS.md` + `README.md` + `project.yaml`），按 T7 schema 生成默认 `project.yaml`（sources 来自参数、cut_points 留空 `[]`、style/render_opts 用默认或传入），**create 即 validate**，返回的 `ProjectConfig` 立刻可被 T9 `load_project` 读回。无破坏性（纯新模块），完全复用 T7 的 `ProjectConfig` + `to_yaml` + `validate`，**不改 schema**。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` →「第二层 · 项目管理系统」→ **T8 · `create_project` —— 项目初始化（建目录 + 生成 project.yaml + 默认配置/样式）**（D1：YAML + 完整项目管理；依赖 T7）。

---

## ⚠️ 执行前必读：Meta-Brief / Plan 与 T7 已落地代码的出入

Meta-Brief 给的签名是 `create_project(name, root, **overrides) -> ProjectConfig`，极简。但对照 Plan T8 原文 + T7 已落地的 `ProjectConfig` 真实形状，有五处必须澄清。**默认按 Plan + T7 代码走**：

### 出入 1：函数签名按 Plan 详细版，不按 Meta-Brief 的 `**overrides`

- **Plan T8 原文**（L291）：`create_project(name, root_dir, *, sources, audio_path=None, style="fresh", render_opts=None, corrections=None, wiki=False, overwrite=False) -> ProjectConfig`。
- Meta-Brief 的 `create_project(name, root, **overrides)` 是抽象表述，丢掉了 `wiki` / `overwrite` / `style` / `corrections` 等关键控制参。
- **结论**：按 Plan 详细签名实现。`root` 参数名在 Plan 里叫 `root_dir`，实现用 `root_dir`（与 Plan 一致；Meta-Brief 的 `root` 只是简写）。

### 出入 2：T7 已落地的 `project.yaml` 顶层 key 是 `meta`，不是 Plan 示例里的 `project`

- Plan T7 的 yaml 示例（L241）写的是顶层 `project:` 块含 `name`/`root`。但 **T7 实际实现**（已读 `project/config.py::ProjectConfig.from_dict` / `to_dict`）用的是顶层 key **`meta`**：`d.get("meta", {})` → `ProjectMeta(name, root)`，`to_dict` 写 `"meta": self.meta.to_dict()`。
- **结论**：T8 生成的 `project.yaml` 顶层用 `meta:` 块（`name` + `root`），**不是** `project:`。这直接复用 `ProjectConfig.to_yaml(cfg)`——它已经按 `meta` 序列化，T8 不需要手搓 yaml 文本，只构造 `ProjectConfig` 再调 `cfg.to_yaml(path)` 即可。这样 schema 与产物天然一致，零漂移风险。

### 出入 3：`render_opts` 的「默认 4K」与 `RenderOptsSpec` 的 schema 默认（1080p）冲突

- Plan T8（L301）：「render_opts 用默认（**4K horizontal** / 1080×1920 vertical / crf 18）或传入」。
- T7 已落地的 `RenderOptsSpec`（schema.py L155）schema 默认是 **1920×1080**（horizontal）/ 1080×1920（vertical）/ crf 18。
- 即：Plan 想要的「create 默认值」≠ 「schema 默认值」。
- **结论**：见 Q2。默认让 `create_project` 构造一份 **4K 默认** `RenderOptsSpec(horizontal_width=3840, horizontal_height=2160, vertical_width=1080, vertical_height=1920, crf=18, output_dir="output/clips")`（对齐 tesla_stage04 的 4K 横屏），`render_opts` 参数传入则覆盖。理由：tesla 投产就是 4K，create 作为「投产脚手架」应给生产可用默认；纯 1080 是 schema 的最小默认，不应作为 create 默认。

### 出入 4：`ProjectConfig.transcript` 是**必填字段**，但 Meta-Brief/Plan 的 `audio_path=None` 默认与之冲突

- T7 已落地：`ProjectConfig.transcript: TranscriptSpec`（无默认值，必填），`TranscriptSpec(audio_path, path)` 两个都必填（from_dict 无 fallback）。
- Plan T8 签名 `audio_path=None` → 若真传 None，无法构造合法 `TranscriptSpec`。
- **结论**：见 Q3。默认 `audio_path` 给一个**约定占位**：`source/<name>.wav`（相对 `meta.root`，符合模板「source/ 放源素材」），`transcript.path` 默认 `output/transcript.json`（对齐 tesla_stage02 的产物路径约定）。`audio_path` 显式传入则覆盖。validate **不校验文件存在性**（T7 已定 Q1 默认 A），所以占位路径能通过 validate。

### 出入 5：`style` 默认 `"fresh"`（Plan），但 schema 默认 + validate 现状是 `"default"`

- Plan T8：`style="fresh"`（默认用 fresh 样式，对齐 tesla + `project-directory-template.md` 的「拷贝一份 fresh.yaml」）。
- T7 schema：`ProjectConfig.style_name` 默认 `"default"`；validate 查 `stage_style/styles/`，`fresh` 与 `default` 都存在（已 ls：8 个 yaml 含 fresh + default）。
- **结论**：T8 的 `style` 参数默认 `"fresh"`（Plan 指定），传入则覆盖。validate 对 fresh 通过。两个默认值（create=fresh / schema=default）各自合理，不冲突——create 是「投产脚手架」用 fresh 更贴近真实，schema 默认 default 是纯数据层的最小值。

> 若人审对以上五点有异议，开工前拍板；否则按上述默认走。

---

## 核心目标

### 1. 新建 `src/garden_core/project/create.py`

```
src/garden_core/project/
├── __init__.py      # T7 已存在 —— T8 追加 re-export create_project
├── schema.py        # T7，不动
├── config.py        # T7，不动
└── create.py        # ★ T8 新增
```

- `create.py` 只 import T7 的公开符号（`ProjectConfig` / `ProjectMeta` / `SourceSpec` / `TranscriptSpec` / `RenderOptsSpec` / `validate`）+ `config.ConfigError`，**不重复定义任何 schema 类型**。
- `project/__init__.py` 的 `__all__` 追加 `"create_project"`，并 `from garden_core.project.create import create_project`。

### 2. `create_project` 签名（按 Plan + 上述出入澄清）

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
) -> ProjectConfig: ...
```

- `name`：项目名（写入 `meta.name` + README 标题）。
- `root_dir`：项目根（写入 `meta.root`，全部相对路径相对此解析；create 时 `mkdir -p`）。
- `sources`：`Sequence[SourceSpec]`（至少 1 条，validate 强制）。注意 `SourceSpec` 是 frozen，调用方直接传 spec 实例；create 把它们的 `path` 当相对 `root_dir` 的占位写入 yaml，**不校验存在性**（validate 不查文件）。
- `audio_path`：见出入 4 / Q3。None → 默认 `source/<name>.wav`。
- `style`：默认 `"fresh"`；不存在则 validate 抛 `ConfigError`（create 即 validate，所以会当场抛）。
- `render_opts`：None → 见出入 3 / Q2 的 4K 默认；传入则原样用。
- `corrections`：写入 `corrections.yaml` 的内容；None → 空 `{}`（见 Q4）。
- `wiki`：见 Q5。默认 False（最小骨架）；True 则建 `Wiki/<name>/{A..M}` 子树（对齐模板）。
- `overwrite`：见 Q1。默认 False（root_dir 已存在且非空 → `ConfigError`）；True 允许重建（仍不删 `source/`，见红线）。

### 3. 建目录树（对齐 `project-directory-template.md` 最小骨架）

```
<root_dir>/
├── source/                    # 仅建空目录（源素材用绝对路径引用，模板铁律：不拷贝）
├── output/
│   ├── clips/                 # 独立切片
│   ├── fullcut/               # 整期精剪/混剪
│   └── release/               # 最终交付成品
├── corrections.yaml           # 空 {} 或传入的 corrections（见 Q4）
├── AGENTS.md                  # 最小版（见 Q6，T13 再细化）
├── README.md                  # 项目名 + 入口说明
└── project.yaml               # ★ 核心产物：ProjectConfig.to_yaml 写出
```

- 用 `pathlib.Path.mkdir(parents=True, exist_ok=True)` 建目录；`output/{clips,fullcut,release}` 三层一次性建。
- **模板铁律**：`source/` 只建空目录，**绝不拷贝 / 绝不写入**任何源视频文件（AGENTS.md「源视频不用拷进项目」）。源素材在 yaml 里以绝对路径或相对 `source/` 的占位引用。

### 4. 生成 `project.yaml`（核心产物）

- **不手搓 yaml 文本**——构造 `ProjectConfig` 实例后调 `cfg.to_yaml(root_dir / "project.yaml")`，序列化与 T7 schema 天然一致（出入 2）。
- 构造逻辑：
  ```python
  cfg = ProjectConfig(
      meta=ProjectMeta(name=name, root=str(root_dir)),
      sources=tuple(sources),
      transcript=TranscriptSpec(
          audio_path=audio_path or f"source/{name}.wav",
          path="output/transcript.json",
      ),
      errata_path="corrections.yaml",
      cut_points=(),                    # 投产时由人/AI 补
      style_name=style,
      render_opts=render_opts or RenderOptsSpec(
          output_dir="output/clips",
          horizontal_width=3840, horizontal_height=2160,   # 4K 默认，见出入 3
          vertical_width=1080, vertical_height=1920,
          crf=18,
      ),
      output_dir="output",
      proof_opts=ProofOptsSpec(),       # schema 默认
  )
  validate(cfg)                          # create 即 validate
  cfg.to_yaml(root_dir / "project.yaml")
  ```
- `cut_points` 留空 `()`（to_dict 在空时不写该 key，T7 已处理）→ 读回等价。

### 5. 生成 `corrections.yaml`（空勘误）

- `corrections=None` → 写 `{}`（空 yaml mapping；`build_errata_config` 对空文件返回 `ErrataConfig.empty()`，已验证）。
- `corrections=dict(...)` → `yaml.safe_dump(corrections)`（见 Q4：是否做结构校验）。
- 路径固定 `root_dir / "corrections.yaml"`（与 `errata_path` 默认一致）。

### 6. 默认样式处理（见 Q5）

- **默认（Q5 选 A）**：`style` 引用**全局** `stage_style/styles/<name>.yaml`，**不**拷贝到 `root_dir/styles/`。
  - 理由：T7 的 `validate` 只查全局 styles 目录，不查项目本地；若拷到本地 validate 也认不出，反而制造漂移。T13 文档层统一说明「style 引用全局」。
  - 若 style 名在全局不存在 → validate 当场 `ConfigError`（create 即 validate 自动覆盖此验收）。
- 备选（Q5 选 B）：拷贝 `fresh.yaml` 到 `root_dir/styles/fresh.yaml`——**不做**，因为 validate 不认项目本地 styles，会引入「文件在但 validate 不认」的撕裂。

### 7. `AGENTS.md` / `README.md` 最小版（见 Q6）

- **AGENTS.md**（T13 细化，T8 先放最小版）：一段花园精神 + 权限边界 + 「本项目由 `garden_core.project.create_project` 生成，配置见 `project.yaml`」+ 指向 SKILL.md。**严禁**真实项目数据（AGENTS.md 卫生铁律）。
- **README.md**：`# <name>` + 一行简介 + 「入口：`load_project("<root_dir>")`」+ 生成时间戳（可选）。占位为主。

### 8. 返回 `ProjectConfig`（已 validate 过）

- create 全程：构造 cfg → `validate(cfg)` → 落盘（目录 + yaml + corrections + AGENTS + README）→ `return cfg`。
- 调用方拿到返回值立即可：`load_project(root_dir)` 读回等价（T8 验收硬指标）、或直接喂 T11 `ProjectRun(cfg, engines)`。

---

## 需人拍板

### Q1：`overwrite` 的语义——`root_dir` 已存在时怎么办？

| 选项 | 做法 |
|---|---|
| **A（默认）** | `overwrite=False`：`root_dir` 已存在且**非空** → `ConfigError`（防覆盖已有项目）；`root_dir` 不存在或空目录 → 正常建。`overwrite=True`：允许重建（`mkdir(exist_ok=True)`），但**绝不删 `source/`**（保护源素材，模板铁律）。 |
| B | `overwrite` 直接清空重建（含删 `source/`）。 | 危险，违反模板铁律。 |

> **默认 A**：与 Plan T8 验收「overwrite=False 时目标已存在且非空 → ConfigError」「overwrite=True 仍不删 source/」逐字一致。

### Q2：`render_opts=None` 时 create 的默认分辨率？

| 选项 | 做法 |
|---|---|
| **A（默认）** | 4K 默认：`RenderOptsSpec(output_dir="output/clips", horizontal_width=3840, horizontal_height=2160, vertical_width=1080, vertical_height=1920, crf=18)`。对齐 tesla 投产 + Plan T8「默认 4K」。 |
| B | 用 `RenderOptsSpec()` 的 schema 默认（1080p）。 | 与 Plan「默认 4K」相悖。 |

> **默认 A**。create 是「投产脚手架」，给生产可用默认；schema 默认 1080 是纯数据层最小值。

### Q3：`audio_path=None` 时 transcript 怎么填？

| 选项 | 做法 |
|---|---|
| **A（默认）** | 占位 `source/<name>.wav` + `transcript.path = output/transcript.json`。validate 不查存在性（T7 Q1 默认 A），占位能通过。投产时人/AI 改 yaml 填真实路径。 |
| B | `audio_path` 设为必填（去掉 None 默认）。 | 与 Plan 签名 `audio_path=None` 冲突。 |
| C | `audio_path=None` 时跳过 transcript 字段。 | 不可能——`ProjectConfig.transcript` 必填（T7 已落地）。 |

> **默认 A**：保持 Plan 签名 + 占位约定，validate 不卡。

### Q4：`corrections` 参数要不要做结构校验？

| 选项 | 做法 |
|---|---|
| **A（默认）** | 不校验结构，`yaml.safe_dump(corrections or {})` 原样写。结构合法性留给 T9 `load_project` 调 `build_errata_config` 时校验。 |
| B | create 时调 `build_errata_config` 预校验。 | 越界（T8 不该懂 errata 内部结构），且 build_errata_config 对「未生成文件」语义与 create 冲突。 |

> **默认 A**：T8 只负责「写一个可被 build_errata_config 读回的空/非空 corrections.yaml」，不做语义校验（单一职责）。

### Q5：默认样式是「拷贝 fresh.yaml 到项目本地」还是「引用全局」？

| 选项 | 做法 |
|---|---|
| **A（默认）** | **引用全局** `stage_style/styles/<name>.yaml`，不拷贝。validate 查全局目录（T7 已落地），天然一致。 |
| B | 拷贝 `fresh.yaml` → `root_dir/styles/fresh.yaml`。 | validate 不认项目本地 styles → 「文件在但 validate 报缺失」撕裂。需同时改 validate 才合理，越界 T8。 |

> **默认 A**。T13 文档层统一说明「style 引用全局 styles 目录」。

### Q6：`AGENTS.md` / `README.md` 最小版内容由谁定？

| 选项 | 做法 |
|---|---|
| **A（默认）** | T8 内联一段最小模板字符串（Python 常量），含花园精神摘要 + 权限边界 + 「由 create_project 生成」+ 指向 project.yaml / SKILL.md。T13 再升级。 |
| B | 从 `skills/*/references/` 拷贝现成 AGENTS.md 模板。 | 现有模板是 skill 侧（给 agent 的），不是项目侧；拷贝会带无关内容。 |

> **默认 A**：内联最小模板，自包含、可测试、零外部文件依赖。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **T7 `project/config.py`**（已读全文）：
  - `ProjectConfig.from_dict` 读顶层 `meta`（不是 `project`）/ `sources` / `transcript` / `errata_path` / `proof_opts` / `cut_points` / `style_name` / `render_opts` / `output_dir`。
  - `to_dict` 对默认值字段**省略不写**（如 `style_name=="default"` 时不写、`cut_points` 空时不写、`render_opts` 全默认时不写）→ create 默认用 `style="fresh"`（非默认）会写出来；4K render_opts 会写出覆盖字段。**注意**：create 必须保证 to_dict 写出的内容能被 from_dict 完整读回（T7 已保证往返，T8 复用即可）。
  - `to_yaml(path)`：`mkdir(parents=True, exist_ok=True)` + `yaml.safe_dump(allow_unicode=True, sort_keys=False, default_flow_style=False)`。
  - `validate(cfg)`：sources 非空 + id 唯一 + cut_point.source 引用合法 + 时间轴在 source 范围内（cut_points 空时跳过）+ style_name 在全局 styles 目录 + clip_id 唯一 + start<end。**不查文件存在性**（T7 Q1 默认 A）→ create 占位路径能通过。
- **T7 `project/schema.py`**（已读全文）：`SourceSpec(id, path, timeline_start_s=0.0, timeline_end_s=None, source_offset_s=0.0)` / `TranscriptSpec(audio_path, path)`（均必填）/ `RenderOptsSpec` 默认 1080p / `ProofOptsSpec` / `CutPointSpec` / `ProjectMeta(name, root)`。全部 frozen。
- **`config.py`**（已读）：`load_yaml` / `ConfigError(ValueError)` / `build_errata_config`（对空文件返回 `ErrataConfig.empty()`）。T8 用 `ConfigError` 抛 overwrite/style 类错误，**不新建异常类**。
- **`stage_style/styles/`**（已 ls）：`fresh.yaml` / `default.yaml` / `bold_impact.yaml` / `broadcast.yaml` / `cinematic.yaml` / `classic_outline.yaml` / `frosted_glass.yaml` / `minimal_clean.yaml`。create 默认 `style="fresh"` → validate 通过。
- **`project-directory-template.md`**（已读全文）：最小骨架 = `source/` + `output/{clips,fullcut,release}` + `corrections.yaml` + `AGENTS.md` + `README.md`；花园式 = 额外 `Wiki/<节目名>/{A..M}`。模板铁律：源视频不拷进项目、产物走本地 SSD、勘误只增不减。**注意**：该模板末尾「项目配置层（取代 project.yaml）」段是 D1 之前的旧描述（「garden_core 不依赖 project.yaml」），**已被 D1 推翻**——T8 正是落地 D1 的 project.yaml 一等公民，T13 会同步改写该模板段。T8 实现时**忽略**那段过时描述，按 D1 走。
- **tesla_stage04.py**（T7 brief 已核对）：4K（3840×2160）/ crf 20 / style fresh / 双源。T8 的 4K 默认 render_opts 对齐其分辨率（crf 取 18 而非 20，见 Q2——create 给通用默认，tesla 投产时人改 crf=20）。
- **示例数据卫生**（AGENTS.md）：真实 tesla 路径 / 真实 clip 标题 / 真实 errata **不得进仓库**。create 生成的 AGENTS.md/README.md 模板 + 测试全用占位符（`<name>` / `tmp_path` / 虚构 SourceSpec）。

---

## 验收标准

1. **新建 `src/garden_core/project/create.py`** + `project/__init__.py` 追加 re-export `create_project`：`from garden_core.project import create_project` 可达。
2. **目录树完整**：`create_project("demo", tmp, sources=[SourceSpec("SRC1", "source/ep01.mp4")])` 后，`tmp/source/`、`tmp/output/clips/`、`tmp/output/fullcut/`、`tmp/output/release/`、`tmp/corrections.yaml`、`tmp/AGENTS.md`、`tmp/README.md`、`tmp/project.yaml` 全部存在。
3. **project.yaml 合法可读回**：`ProjectConfig.from_yaml(tmp / "project.yaml")` 不抛；字段与 create 返回值（及传入参数）一致——`meta.name=="demo"`、`meta.root==str(tmp)`、`sources` 等价、`style_name=="fresh"`、`render_opts` 为 4K、`transcript.audio_path=="source/demo.wav"`（占位）、`transcript.path=="output/transcript.json"`、`cut_points==()`。
4. **create 即 validate**：返回的 `ProjectConfig` 已通过 `validate`（create 内部先 validate 再落盘）。
5. **load 闭环**：T9 `load_project(tmp)`（T9 实现后）读回与 create 返回字段一致（T8 先用 `ProjectConfig.from_yaml` 自测读回等价，T9 落地后补 load_project 断言）。
6. **corrections.yaml**：存在；`corrections=None` 时内容为 `{}`；`corrections={"a":"b"}` 时内容含该映射。
7. **overwrite=False 守护**：`tmp` 已存在且非空（预先 touch 一个文件）→ `create_project(..., overwrite=False)` 抛 `ConfigError`。
8. **overwrite=True 重建**：同上场景 `overwrite=True` 不抛，且**不删 `source/`**（预先在 `tmp/source/` 放一个 marker 文件，重建后仍在）。
9. **坏 style 报错**：`create_project(..., style="nonexistent_style")` → `ConfigError`（validate 抛，信息含 style_name）。
10. **wiki=False（默认）** 不建 `Wiki/`；`wiki=True` 建 `Wiki/<name>/{A_花园地图, ..., M_概念花园}` 子树（见 Q5 默认 A 下 wiki 仍按模板建子目录）。
11. **不破坏现有代码**：`pytest tests/` 全绿；T7 的 `schema.py` / `config.py` / `__init__.py`（除追加 re-export）**零改动**；`config.py` / `types.py` / `stage_*` 零改动。

**pytest / 校验命令**：
```bash
# 可达性
python -c "from garden_core.project import create_project, SourceSpec; print('ok')"
# 专项
python -m pytest tests/test_create_project.py -v
# 全量回归
python -m pytest tests/ -v
# 范围检查
git diff --name-only   # 仅 project/create.py (新增) + project/__init__.py (追加 re-export) + tests/test_create_project.py (新增)
# 卫生检查（无真实 tesla 数据泄露）
grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>" src/garden_core/project/ tests/test_create_project.py
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ 新建 `src/garden_core/project/create.py` | ❌ 改 T7 的 `schema.py` / `config.py`（只 import 复用） |
| ✅ `project/__init__.py` 追加 `create_project` 到 `__all__` + import | ❌ 改 `ProjectConfig` / 任何 spec 的字段或默认值（「不改 schema」铁律） |
| ✅ 新建 `tests/test_create_project.py` | ❌ 新建/改 `load_project`（那是 T9） |
|  | ❌ 新建 `ProjectRun` / `run_manifest`（那是 T11） |
|  | ❌ 拷贝 `fresh.yaml` 到项目本地（Q5 默认 A，引用全局） |
|  | ❌ 校验 errata 内部结构（Q4 默认 A，留给 T9） |
|  | ❌ 校验文件存在性（T7 Q1 默认 A，留给 T9 strict） |
|  | ❌ 改 `project-directory-template.md`（那是 T13） |
|  | ❌ 删 `source/` 内容（Q1 默认 A，模板铁律） |
|  | ❌ `pipeline.py` / `scripts/*.py` / `stage_*`（T8 不碰） |
|  | ❌ 在 AGENTS.md/README.md 模板或测试里放真实 tesla 数据（卫生铁律） |

---

## 自测方法

1. **可达性**（验收 1）：`python -c "from garden_core.project import create_project"`。
2. **目录树 + 读回等价**（验收 2/3/4/5）：`test_create_project.py` 用 `tmp_path` fixture → `create_project("demo", tmp_path, sources=[SourceSpec("SRC1", "source/ep01.mp4")])` → 断言全部目录/文件存在 → `ProjectConfig.from_yaml(tmp_path/"project.yaml")` 读回 → 逐字段断言（meta/sources/style/render_opts 4K/transcript 占位/cut_points 空）与 create 返回值相等。
3. **corrections**（验收 6）：分两个 case——`corrections=None` 读回 `{}`；`corrections={"foo":"bar"}` 读回含该键。
4. **overwrite=False 守护**（验收 7）：`tmp_path` 预 touch `tmp_path/.exists` → `pytest.raises(ConfigError)`。
5. **overwrite=True 不删 source**（验收 8）：先 create 一次 → 在 `tmp_path/source/marker.txt` 写内容 → 再次 `create_project(..., overwrite=True)` → 断言 `marker.txt` 仍在 + project.yaml 被重建。
6. **坏 style**（验收 9）：`create_project(..., style="no_such_style")` → `pytest.raises(ConfigError)` + `str(e)` 含 `"no_such_style"`。
7. **wiki**（验收 10）：`wiki=False` 断言 `not (tmp_path/"Wiki").exists()`；`wiki=True` 断言 `Wiki/demo/A_花园地图` ... `M_概念花园` 全部存在。
8. **diff 范围**（验收 11）：`git diff --name-only` 仅 `project/create.py`（新增）+ `project/__init__.py`（追加）+ `tests/test_create_project.py`（新增）。
9. **回归**：`pytest tests/ -v` 全绿（T8 纯新模块，不应有任何现有测试失败；尤其 T7 的 `test_project_config.py` / `test_project_validate.py` 保持绿）。
10. **卫生检查**：`grep -rnE "<DATE>|<SRC_FILE>|N:\\\\<DATE>" src/garden_core/project/ tests/test_create_project.py` 无命中。

---

## 风险

- **无破坏性**：纯新模块（`create.py` + `__init__.py` 追加 re-export + tests），不碰 T7 schema/config、不碰任何现有文件。`pytest tests/` 应全绿。
- ⚠️ **Meta-Brief 签名简化**（出入 1）：按 Plan 详细签名实现；若人审要严格 `**overrides` 风格，需明确放宽——但 `**overrides` 无法表达 `wiki`/`overwrite` 的布尔语义 + `sources` 的类型约束，不推荐。
- ⚠️ **5 处出入需人拍板**（出入 1–5 / Q1–Q6）：默认全部按「Plan + T7 代码」走。最关键的是出入 2（顶层 `meta` key）和出入 4（transcript 必填 vs audio_path=None）——这两处若不澄清，create 写出的 yaml 会与 schema 漂移或直接构造失败。本 brief 已给默认解。
- **create 即 validate 的副作用**：create 内部先 `validate(cfg)` 再落盘。若调用方传了非法 sources（如重复 id）/ 坏 style，会在落盘前抛 `ConfigError`，**不会留下半成品目录**（目录创建在 validate 之后，或 validate 之前建目录但抛错时目录已建——见实现细节：建议先 validate 内存 cfg，通过后再 mkdir + 落盘，避免「抛错但留空目录」）。实现时注意顺序：**构造 cfg → validate(cfg) → mkdir 目录树 → to_yaml + 写 corrections/AGENTS/README → return cfg**。
- **`output/transcript.json` 占位**：create 不生成 transcript.json（那是 T11 `run.transcribe()` 的产物），只在 yaml 里写路径占位。validate 不查存在性，所以 OK。文档（README）需说明「transcript 由 run.transcribe() 生成」。
- **依赖 T7 已落地**：T8 完全建立 T7 之上。若 T7 schema 后续被改（不应该，T7 已验收），T8 需同步——本 brief 假设 T7 schema 冻结。

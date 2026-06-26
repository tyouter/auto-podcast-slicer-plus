# RX Brief · T3 — `render_gate.audit_dir()` 目录复审（合并 ffprobe 机械校验）

> **一句话**：在 `stage_render/render_gate.py` 新增目录级复审函数 `audit_dir()`，把 `tesla_audit.py` 手搓的四类机械检查（文件存在性 / ffprobe 分辨率+编码 / ASS cue 计数 / ASS 内容 gate）合并进一个返回 `AuditReport` 的统一入口，现有 `gate_results` / `check_ass_pair` / `check_render_result` 一律不动。

**Plan 位置引用**：`DEVELOPMENT_PLAN.md` → 「第一层 · 小改 API」→ **T3 · `render_gate.audit_dir()` —— 目录复审（D4：合并 ffprobe 机械校验）**。决策依据见末尾「决策点清单」**D4 ✅**。

---

## ⚠️ 执行前必读：Meta-Brief 与 Plan 的三处冲突（必须先拍板）

下发本任务的 meta-brief 对 D4 / T3 有**三处误读**，与 Ray 已认可的 `DEVELOPMENT_PLAN.md` 直接冲突。rx 执行前请人确认按 **Plan 版本**（下文正文）执行：

| # | Meta-Brief 说法 | Plan（Ray 已认可）实际说法 | 本 Brief 采用 |
|---|---|---|---|
| C1 | "ffprobe 检查**合入 `gate_results`**，不是另起独立函数；`gate_results(results: list[RenderResult])` 签名不变破，内部加 ffprobe 层" | D4 的"合并"指：**新建 `audit_dir()` 一个函数同时做 ASS-gate + ffprobe**（替代"两个独立函数"的备选方案），**不是**把 ffprobe 塞进现有 `gate_results`。`gate_results` 是 RenderResult 内存入口、只查 ASS；`audit_dir` 是**目录级**入口，从磁盘文件发现 clip。两者并存，互不改。 | **Plan** |
| C2 | "ffprobe 失败是 **BLOCK**" | Plan 明确：**系统无 ffprobe 时机械项标记 `skipped`（不 BLOCK）**，ASS gate 仍执行——避免在无 ffprobe 环境误伤。分辨率/编码不符本身是 violation（BLOCK），但"ffprobe 工具不可用"不是。 | **Plan** |
| C3 | 新增"**时长偏差 < 5%**"检查 | Plan 与 `tesla_audit.py` 均**无时长检查**。T3 范围 = 存在性 + 分辨率 + 编码 + cue 计数 + ASS gate，**不含 duration**。 | **Plan**（不引入 duration） |

> 若人审后坚持 meta-brief 版本（改 `gate_results` 内部 / ffprobe 缺失即 BLOCK / 加 duration），请改写本 brief 正文后再交 rx。**默认按 Plan 执行。**

---

## 核心目标（逐条提炼自 Plan T3）

1. **新增 `audit_dir(output_dir, *, pattern="{clip_id}", expected_horizontal=(3840,2160), expected_vertical=(1080,1920), expected_codec="h264", render_horizontal=True, render_vertical=True, raise_on_fail=True) -> AuditReport`**，位于 `render_gate.py`。
2. **目录复审四项检查**（对齐 `tesla_audit.py` 全部分段）：
   - **(a) 文件存在性**：每条 clip 检查 `{cid}_horizontal.mp4` / `{cid}_vertical.mp4` / `{cid}.ass` / `{cid}_vertical.ass` 齐全（按 `render_horizontal` / `render_vertical` 决定要不要对应竖版文件）；缺失记 `missing_file` violation。
   - **(b) ffprobe 机械规格**：对存在的 mp4 调 `infra/media_probe.py::probe_media()`，比对 `expected_horizontal` / `expected_vertical` 分辨率 + `expected_codec`；不符记 `resolution` / `codec` violation。
   - **(c) ASS cue 计数**：对存在的 `.ass` 统计 `Dialogue:` 行数，0 条记 `zero_cues` violation。
   - **(d) ASS 内容 gate**：复用现有 `check_ass_pair(clip_id, h_text, v_text)`（字体 ratio / 安全区），逻辑不变，产出 violation 归类为 `ass_gate`。
3. **clip_id 发现规则**：从目录里 `{*_horizontal.mp4, *_vertical.mp4, *.ass}` 文件名提取（去 `_horizontal`/`_vertical` 后缀、去 `.ass` 扩展名），去重；`_vertical.ass` **不能**被误当成独立 clip_id——复用现成 `_vertical_ass_path` 反推逻辑。
4. **结构化 `AuditReport`**：含 per-clip violations（按类别 `missing_file` / `resolution` / `codec` / `zero_cues` / `ass_gate` / `skipped`）+ pass/block 汇总；提供 `to_dict()` 与 `save(path)`（写 `audit_report.json`，供 agent 事后读）。
5. **`raise_on_fail=True`** 时有任何 violation 抛现有 `RenderGateError`（**复用，不新建异常类**）。
6. **ffprobe 缺失兜底**：`probe_media()` 返回 `None`（ffprobe 不在 PATH / 超时 / 解析失败）→ 该 clip 的机械项标记 `skipped`（**不 BLOCK**），ASS gate 仍照常执行。
7. **删除 `scripts/tesla_audit.py`**（独立验收项；D4：被 `audit_dir` 取代）。

---

## 关键事实核对（已读真实代码，非凭摘要）

- **`probe_media(path, ffprobe_bin="ffprobe") -> Optional[MediaInfo]`**（`infra/media_probe.py`）：失败（ffprobe 不存在 / 非零退出 / 非 JSON）一律返回 `None`，**不抛**。`MediaInfo` 字段 = `width / height / duration_s / fps / has_audio / audio_sample_rate`，**无 `codec` 字段**——⚠️ 见下方"实现注意"。
- **`check_ass_pair(clip_id, horizontal_ass, vertical_ass, *, font_ratio_tol=...) -> list[GateViolation]`**：已是纯函数（不依赖 RenderResult / 不读盘），`audit_dir` 读盘后直接喂 ASS 文本即可。
- **`_vertical_ass_path(ass_path)`**：现成的"横版 ass 路径 → 竖版 ass 路径"反推，复用做 clip_id 发现的去重。
- **`RenderResult` 字段**（`types.py` L195）：`clip_id / horizontal_mp4 / vertical_mp4 / srt_path / ass_path / metadata`——`audit_dir` **不接收 RenderResult**，从目录发现 clip_id，故不需要改 `RenderResult`。
- **`tesla_audit.py` 现状**：硬编码 `DIR = r"N:\..."`（真实项目路径，违反仓库卫生——删除它正好清掉）；ffprobe 用 `csv=p=0` 裸解析，`audit_dir` 改用 `probe_media()` 更稳。tesla_audit 的检查项 = 存在性(4 文件) + H 分辨率/编码 + V 分辨率 + cue 计数（**注意：tesla_audit 的竖版只查分辨率不查编码——`audit_dir` 应双侧都查编码，更严，Plan 默认值 `expected_codec="h264"` 对双侧生效**）。
- **`tesla_gate.py` 现状**：用 `type("R",(),{...})()` 造假类 + 引用不存在的 `GateOutcome`，**脚本已坏**——不在 T3 范围（T3 只删 `tesla_audit.py`，`tesla_gate.py` 留待 T11/T13）。

### ⚠️ 实现注意：`probe_media()` 不返回 codec
`MediaInfo` **没有 `codec_name` 字段**（只有 width/height/duration/fps/has_audio）。而 T3 要求检查 `expected_codec="h264"`。两条路：
- **方案 A（推荐）**：在 `audit_dir` 内对需要查编码的 mp4 直接补一次 `ffprobe -show_entries stream=codec_name`（与 `tesla_audit.py` 一致的最小 subprocess 调用），`probe_media()` 仍只管分辨率/时长。
- **方案 B**：扩展 `MediaInfo` + `probe_media()` 增加 `codec_name` 字段。

> **方案 B 会动 `infra/media_probe.py`**，越出 T3 "只改 render_gate.py" 红线。**本 brief 默认方案 A**（ffprobe 编码查询封装在 `render_gate.py` 内部的小 helper），保持 `media_probe.py` 不动。若人审倾向 B，需明确放宽红线。

---

## 验收标准

1. 对一个已渲染的 `output_dir` 调 `audit_dir(d)`，结果覆盖 `tesla_audit.py` 的**全部**检查项：缺失文件 / 分辨率不符 / codec 非 h264 / 0 cue / ASS gate 失配均被正确报为对应类别 violation。
2. `audit_dir` 的 ASS gate 部分，与「对该目录对应的内存 RenderResult 列表调 `gate_results`」产生**完全一致**的 ASS 违规集合（同一份 `check_ass_pair` 复用）。
3. `AuditReport.to_dict()` 可序列化、`save(path)` 写出合法 JSON 且能被 `json.load` 读回。
4. `raise_on_fail=True`（默认）且有 violation → 抛 `RenderGateError`；`raise_on_fail=False` → 仅返回 report 不抛。
5. 系统**无 ffprobe** 时（`probe_media` 返回 None / 编码查询失败）→ 机械项 `skipped`，**不 BLOCK**，但 ASS gate 仍执行并可能 BLOCK。
6. `scripts/tesla_audit.py` **已删除**。
7. **回归**：现有 `gate_results` / `check_ass_pair` / `check_render_result` / `parse_ass` 行为完全不变（`tests/test_render_gate.py` 全绿）。

**pytest 命令**：
```bash
pytest tests/test_render_gate.py tests/test_render_gate_audit_dir.py -v
# 全量回归
pytest tests/ -v
```

---

## 范围红线

| 允许改 | 禁止改 |
|---|---|
| ✅ `src/garden_core/stage_render/render_gate.py`（新增 `audit_dir` / `AuditReport` + 内部 ffprobe 编码 helper） | ❌ `src/garden_core/stage_render/ass_writer.py` |
| ✅ `scripts/tesla_audit.py`（**删除**） | ❌ `src/garden_core/stage_render/ffmpeg_render.py` |
| ✅ `tests/test_render_gate_audit_dir.py`（新增） | ❌ `src/garden_core/stage_render/__init__.py`（`render()` / `RenderOptions`） |
| ✅ `tests/test_render_gate.py`（仅在必要时补 import，不改现有断言） | ❌ `src/garden_core/infra/media_probe.py`（见"实现注意"——默认方案 A 不动它） |
|  | ❌ `src/garden_core/types.py`（`RenderResult` 不动） |
|  | ❌ 三入口 `run_from_audio` / `run_from_transcript` / `run_montage` |
|  | ❌ `src/garden_core/stage_cut/__init__.py`（T4 的活，不是 T3） |
|  | ❌ `scripts/tesla_gate.py`（留给 T11/T13） |

> `__all__` 需把 `audit_dir` / `AuditReport` 加进 `render_gate.py` 的导出列表。

---

## 自测方法（`tests/test_render_gate_audit_dir.py`，新增）

用 tmp 目录构造场景，**不真跑 ffmpeg**（ffprobe 用 mock）：

1. **ASS gate 失配**：写一对 `{cid}.ass` + `{cid}_vertical.ass`（用真实 `ass_writer.build_ass` 生成，竖版注入超大 fontsize 复刻 old bug）→ `audit_dir` → 断言该 clip 报 `ass_gate` violation（类别正确）。
2. **zero_cues**：写一个无 `Dialogue:` 行的 `.ass` → 断言 `zero_cues` violation。
3. **resolution 不符**：mock `probe_media` 返回 `MediaInfo(width=1920, height=1080, ...)`（横版期望 3840×2160）→ 断言 `resolution` violation。
4. **codec 不符**：mock 内部编码查询返回 `hevc` → 断言 `codec` violation。
5. **missing_file**：只放横版 mp4 不放竖版 → 断言 `missing_file` violation（`render_vertical=True` 时）。
6. **ffprobe 缺失兜底**：mock `probe_media` 返回 `None` → 断言机械项 `skipped`、**不抛**、ASS gate 仍跑。
7. **happy path**：全部合法 → `AuditReport` 无 violation、`to_dict()` 可序列化、`save()` 写出可读回 JSON、`raise_on_fail=True` 不抛。
8. **clip_id 发现**：目录里混放 `{cid}_vertical.ass` → 断言不被误当成独立 clip_id（去重正确）。
9. **等价性**：对同一组 ASS 文件，`audit_dir` 产出的 `ass_gate` violation 集合 == 直接调 `check_ass_pair` 的集合。
10. **回归**：`tests/test_render_gate.py` 现有断言全绿（未改 `gate_results` 等）。

---

## 风险

- **无破坏性**（Plan 原话）：纯新增函数；现有 gate 链路不动。
- **唯一需要人拍板的点**：上文「实现注意」的方案 A vs B（编码查询放哪）+「冲突表」C1/C2/C3 三处 meta-brief 误读。**默认全部按 Plan。**
- D4 已定，无悬念。

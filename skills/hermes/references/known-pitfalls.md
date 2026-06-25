---
name: video-clip
description: 拥有完整视频制作团队能力的剪辑专家。当用户需要从播客/录像素材制作、编辑、包装或分发视频内容时激活。这是一个对话驱动的视频制作工具，不是简单的根据时间点裁剪工具。
triggers:
  - "剪视频"
  - "做一期视频"
  - "帮我剪"
  - "切片制作"
  - "视频制作"
  - "auto-podcast"
---

# Video Clip — 自媒体个体的视频制作团队

你是一个完整的视频制作团队，服务于自媒体个体创作者。你的目标是将一个人从"我有素材"带到"我有一整套可以在各平台发布的成品"，如同拥有一支专业团队。

## ⚠️ 已知陷阱

### 工作流纪律

**严禁绕过 Skill 直接调底层 CLI。** 必须通过 Skill 定义的工作流（制作人对话 → 蓝图确认 → 执行）驱动 garden CLI。不允许跳过工作流直接用 terminal 跑 `garden clip` 或手写参数拼接底层接口——这会导致转录缺失、字幕为空、参数不一致等系统性 bug。用户已明确纠正过此行为。

### project.yaml 中 transcript 必须用绝对路径 ⚠️

**症状**：`garden clip` 报告「转录条目: 0」，所有切片「超出转录范围 [0.0s–0.0s]」。但 `transcript.json` 文件存在且内容正确（1383 段，时间戳完整）。

**根因**：`project.yaml` 中 `sources.transcript` 使用了相对路径（如 `transcript: transcript.json`）。garden CLI 的相对路径解析基准不是项目目录，而是 CLI 工作目录或模板目录，导致找不到文件。

```yaml
# ❌ 错误 — 相对路径
sources:
  transcript: transcript.json          # → 转录条目: 0

# ✅ 正确 — 绝对路径
sources:
  transcript: /path/to/projects/garden-production/transcript.json  # → 转录条目: 1481
```

**修复**：始终用绝对路径。如果 transcript 在项目目录下，写完整路径，不依赖相对路径解析。

**⚠️ 已有项目 ≠ 可以跳过 Workflow 0。** 当项目目录已存在、clips.yaml 已定义好、转录已就绪时，最大的陷阱是直接把用户请求当作「跑已有配置」而非「创作对话」。典型错误路径：

```
用户: "让我们剪辑首集《小径分岔的花园》吧"
                                     ↓
❌ 错误：检查项目状态 → 列出已有 clip → 提议直接跑 garden clip
✅ 正确：介绍能力 → 确认理解 → 输出创作蓝图 → 等用户确认 → 执行
```

即使 clips.yaml 全写好了、转录覆盖 75 分钟、风格也定了，Workflow 0 的四步（介绍 → 确认 → 蓝图 → 等确认）一步不能少。用户可能在看到蓝图后改主意（如「7 段完整版」→「1 段爆款」），跳过对话就丢失了这个机会。已有项目状态是执行时的便利，不是跳过创作对话的理由。

### 制作人的判断力（不是填表项目经理）

**制作人必须有创作判断。** 用户问"你现在是制作人吗"就是越界信号——你在列 ABC 选项而不是给判断。

- **先听素材再说话**：拿到转录后基于内容给方向性建议
- **判断先行于选项**：内容气质是探索型流动的→直接建议"做主题段落"，不列"A 高光引流还是 B 主题深挖"
- 用户选制作人是信任审美判断，列选项 = 推卸责任 必须通过 Skill 定义的工作流（制作人对话 → 蓝图确认 → 执行）驱动 garden CLI。不允许跳过工作流直接用 terminal 跑 `garden clip` 或手写参数拼接底层接口——这会导致转录缺失、字幕为空、参数不一致等系统性 bug。用户已明确纠正过此行为。

### 转录是前置步骤

执行任何剪辑工作流之前，必须先确保有完整转录。`garden transcribe` 是正式 CLI 命令：

```bash
garden transcribe --project-dir <项目目录>          # 首次转录
garden transcribe --project-dir <项目目录> --force  # 强制重新转录（老转录有文字 bug）
garden clip --project-dir <项目目录> --auto-transcribe  # 切片时自动转录
```

- 默认：transcript.json 已存在 → 跳过并提示用 `--force`
- `--force`：无视已有文件，完整重新转录
- 输入源：优先 `sources.audio`，无则从 `sources.video` 提取音频
- `garden clip` 会校验转录覆盖范围，切片超出范围时报错（不再静默产出空字幕）

### 转录路径选择

- **有 GPU**（容器）→ `garden transcribe --engine funasr` → `transcript.json`
- **无 GPU**（仅 CPU）→ FunASR MCP (Windows CUDA) → `transcribe_chunked.py` → `transcript.json`
- **拿到 transcript.json 后**：`garden clip` 一步到位。不要手工逐段纠错——garden 内置 errata_engine 自动处理。
- **MCP 端口**：8000（不是 8765）。容器直连 HTTP 返回 406，必须走 Hermes MCP 工具或 Windows 脚本。

详见 [funasr-mcp-transcription.md](references/funasr-mcp-transcription.md)。

### 字幕风格陷阱

**打造 > 复刻**：不从真实视频扒样式参数做 1:1 复刻。设计原创预定义风格，每款有清晰的审美定位和场景描述。

**配置驱动，零硬编码回退**：风格名只存在于 `default.yaml` 和 `project.yaml`，代码层不出 `"cinematic"` / `"frosted_glass_dark"` 等硬编码回退。⚠️ 删代码层回退后必须确保 project.yaml 有 `pipeline.subtitle.style`，否则所有切片 0/N 失败。

### `garden clip` 陷阱

**`--make-vertical` 默认关闭**：不传 `--make-vertical` 只出横版，竖版 0 个，不报错不提示。

**输出路径解析**：`output.base_dir` 相对路径以 cwd（repo 根）为基准，非项目目录。用绝对路径避免。

**超长片段渲染静默失败**：>30 分钟素材（尤其 4K 全时长 86 分钟），`garden clip` 可能报告 "完成: 1/1 成功" 但 `_subtitled.mp4` 未生成。ASS/SRT/WAV/MP3/metadata.json 全部正常产出——只有视频缺失。pipeline 在 ffmpeg 字幕烧录步骤静默失败，不报错。**绕过**：用产出的 ASS 文件直接手动 ffmpeg 烧录。`ffmpeg -ss <start> -i <source.mp4> -t <duration> -vf ass=<file.ass> -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 192k <output.mp4>`。原因待排查（可能是 ffmpeg 超时被 pipeline 误判为成功、或 4K+字幕滤镜链 OOM）。

### `resolve_style_definition(None)` 兜底

clip 级不设 style 是合法场景（继承项目级默认），不能 raise。兜底逻辑从 `default.yaml` 读 `pipeline.subtitle.style`值。缺配时 `raise ValueError`，不静默回退——回退值会掩盖配置错误。

**风格文件三层**：用户层（`*.yaml`，审美参数）→ 内部层（`*.internal.yaml`，mold 公式 + 测量补偿）→ 全局层（`default.yaml`，唯一默认风格来源）。

**当前默认风格**：cinematic（好莱坞电影）—— 白字粗体 + 粗黑描边，无背景无阴影。

调参流程见 [style-tuning-workflow.md](references/style-tuning-workflow.md)，CC 协作规范见 [claude-code-collaboration.md](references/claude-code-collaboration.md)。

### Style vs Mold 分层
模具（Mold）是制造层，不暴露给用户。用户只选风格（Style），风格封装了：用哪个模具、是否自动优化、优化策略。
详见 [subtitle-style-architecture.md](references/subtitle-style-architecture.md)

### 字幕样式设计

参考 [字幕样式设计指南](references/subtitle-style-design.md) — 6步流程从定调到截图验证。

### 竖版坐标系 ⚠️

竖版字幕的 font_size 和 margin_v 必须按**内容区高度**（607px）计算，不是全屏高度（1920px）。
- 每个 style 的 vertical 段必须设 `overlay_content_aspect: "16:9"`
- pipeline 已在 `_expand_mold_orientation()` 和 `_compute_from_mold()` 中用 `ref_height` 替代 `video_height`
- 验证：横竖版空隙比例应一致（底部空隙 / 内容高）

### Config 解析双路径陷阱

`PipelineConfig(project_dir=...)` 走完整合并路径，而 `garden clip` 内部 `process_clip()` 调的是裸 `resolve_style_definition(None)`。**改了 config 加载逻辑后必须两条路径都测**，否则 CLI 端可能静默报错。

验证命令：
```bash
# 路径1 — 完整合并
python3 -c "from pipeline.config import PipelineConfig; c = PipelineConfig(project_dir='projects/xxx'); print(c.get('pipeline.subtitle.style'))"

# 路径2 — 裸调用（garden clip 实际走这条）
python3 -c "from pipeline.config import resolve_style_definition; print(resolve_style_definition(None).mold_name)"
```

`resolve_style_definition(None)` 不能直接 raise——clip 级不设 style 是合法场景（继承项目级默认）。兜底逻辑必须从 `default.yaml` 读 `pipeline.subtitle.style`，不能硬编码字符串。

### 优化陷阱

- 用户层 `*.yaml` 放审美参数，`*.internal.yaml` 放 mold 公式
- **设计迭代期间 `optimize: false`**，否则 StyleOptimizer 会覆盖手工值
- 竖版必须设 `overlay_content_aspect: "16:9"`
- 完整陷阱列表见 [字幕风格迭代陷阱](references/subtitle-style-pitfalls.md)
- 调参流程与竖版修复详见 [subtitle-style-development.md](references/subtitle-style-development.md)

- 两层配置：用户层 `{name}.yaml`（审美参数）+ 内部层 `{name}.internal.yaml`（mold 公式）
- **设计阶段必须设 `optimize: false`**，否则 StyleOptimizer 会静默覆盖手动参数
- 用独立测试项目（blank 模板）验证，不要污染已有项目
- 验证方法：检查 `.ass` 文件的 Style 行确认 outline/shadow/font_size 与设计一致
- 已知 bug：项目级 `pipeline.subtitle.style` 不生效，需在 clips.yaml 每个 clip 显式设 `style:`

### 竖版字幕坐标系缺陷

竖版 ffmpeg 滤镜链：横版视频居中叠加在 1080×1920 竖屏画布 → ASS 以 1080×1920 为 PlayRes 烧录。已知问题：

1. **字号计算错误**（`subtitle_style.py:367`）：`font_size = round(xr * 1920)` 按全屏高算，应为 `xr * content_h`（内容区高 = 1080 * 9/16 ≈ 607）。当前竖版字比内容区比例偏大。
2. **位置偏移缺失**：竖版配置需设 `overlay_content_aspect: "16:9"` 才能激活 `effective_margin_v`（`subtitle_style.py:125-135`）的内容区偏移。缺此字段时字幕定位在画布底部而非内容区底部。

两项均待修复。详见 [subtitle-style-architecture.md](references/subtitle-style-architecture.md) 和 [subtitle-style-design.md](references/subtitle-style-design.md)。

### yuv420p 奇数高度陷阱
ffmpeg 的 `pad` 滤镜要求高度为偶数，竖版 1080x1920 转横版时需确保 `h=trunc(oh/2)*2`

### 竖版坐标陷阱

竖版 ASS 坐标系 1080×1920，但 ffmpeg 滤镜链将横版画面居中叠在 1080×607 区域内。竖版配置**必须**设 `overlay_content_aspect: "16:9"`，否则字幕按全屏 1920px 算字号和位置，结果跑到底部 656px 空白区。

已修复 `_expand_mold_orientation()` 和 `_compute_from_mold()`：检测 overlay_content_aspect 后用内容区高度替代全屏高度。

### skip_existing 陷阱
`clip_processor.py` 默认 `skip_existing=True`。如果 ASS 字幕文件因样式修改而重新生成，但 MP4 已存在，旧 MP4 不会被替换——导致 ASS 正确但视频仍用旧字幕渲染。

### 提取管线硬编码参数
字幕风格提取管线（`subtitle_style_extractor.py`）中存在多个参数是硬编码默认值而非从参考帧检测的（blur_radius、bg_alpha 等）。每次渲染后发现"不对"才修一个参数。需要在发现此类问题时进行系统性审计。详见 [extraction-hardcoded-parameters.md](references/extraction-hardcoded-parameters.md)
**规则：修改样式后必须先删除旧 MP4，再重渲。** 验证方法：`ls -la` 对比 ASS 和 MP4 的修改时间。

### 切片时间无转录
`clips.yaml` 的 `start_s`/`end_s` 超出转录覆盖范围时，生成 0 条 Dialogue，字幕完全空白。渲染前检查转录时间范围。
### Pipeline 执行陷阱

渲染期容易踩的坑（VLM 提取颜色缺字段、转录范围不匹配、skip_existing 跳过重渲、base_dir 污染等）。详见 [pipeline-pitfalls.md](references/pipeline-pitfalls.md)。

### 字幕风格提取研究

从参考视频帧自动提取字幕渲染参数是一个学术空白。详见 [字幕风格提取研究现状](references/subtitle-style-extraction-research.md)。

### 风格提取调试

提取的颜色不对时，按方法论排查：VLM 分析参考帧获取真值 → 对比 yaml → 检查 ASS → 区分颜色问题和 frosted_glass 效果问题。完整流程见 [风格提取调试方法论](references/style-extraction-debugging.md)。

### 项目级 style 不生效

`project.yaml` 中设置 `pipeline.subtitle.style: <name>` 可能不生效，pipeline 回退到默认 `frosted_glass_dark`。

**根因**：`_process_single_clip` 中，当 `subtitle_style` 是已加载的 SubtitleStyle 对象（truthy）时，代码路径走到 `clip.get("style")` → None → `resolve_style_definition(None)` → 默认值。

**绕过**：在 `clips.yaml` 中为每个 clip 显式设 `style: <name>`。

### 字幕文本完整性诊断

**症状**：视频播放时字幕最后一个词或几个字不显示。

**诊断方法**：对比 ASS 字幕文件与 transcript.json 的文本内容。如果 ASS 的字符数明显少于对应转录段的字符数，说明渲染过程中文本被截断。

```python
import json, re, os

# 加载 ASS 并提取对话文本
ass_path = "output/.../TEASER01_seg0.ass"
with open(ass_path) as f:
    ass_texts = []
    for line in f:
        if line.startswith('Dialogue:'):
            parts = line.split(',', 9)
            text = re.sub(r'\{[^}]*\}', '', parts[9].strip())
            text = text.replace('\\N', ' ')
            ass_texts.append(text)

# 与转录比较
with open("transcript.json") as f:
    segs = json.load(f)["segments"]

ass_full = ''.join(ass_texts)
t_full = ''.join(s["text"] for s in matching_segs)

if len(ass_full) < len(t_full):
    missing = t_full[len(ass_full):]
    print(f"ASS 比转录少 {len(t_full)-len(ass_full)} 字: '{missing[:60]}'")
```

**根因有两层**：

#### 层1：语速限制截断（`subtitle_content.py`）

`process_subtitle_content()` 中 `max_by_speed = int(duration_s * 4)` 对短时长子段（如 1.5s）将 `effective_max` 压到 6 字，句尾被硬截断。

```
原文：一般说白头的是代表智慧，说我们干这件事儿，应该在这件好事。
↓ 拆分后每段 1.5s → max_by_speed = 6
ASS：一般说白头的是代 | 说我们干这件 | 应该在这件
                                                   ↑ 丢失: 表智慧 / 事儿 / 好事
```

**修复**：去掉语速上限。字幕起止时间本身就是最精确的约束，不需要额外的 `duration * 4` 限制。

```python
# subtitle_content.py — 删除 max_by_speed 逻辑
# Before:
effective_max = max_chars
if duration_s > 0:
    max_by_speed = max(4, int(duration_s * 4))
    effective_max = min(max_chars, max_by_speed)
text = format_subtitle_single_line(text, effective_max)

# After:
text = format_subtitle_single_line(text, max_chars)
```

#### 层2：标点边界硬截断（`subtitle_formatter.py`）

`format_subtitle_single_line()` 在文本超过 `max_chars` 时，会在 `max_chars + 3` 范围内搜索标点断句。但找到标点后，如果标点位置 > `max_chars`，就直接硬截到 `max_chars` 而不是延伸到标点。

```
原文：但我也不是特别执意于打一个标签在我身上。(21字)
         搜索窗口 max_chars+3 = 21，找到 "。" 位置 20
         但 pos=20 > max_chars=18 → 硬截到 18
ASS：但我也不是特别执意于打一个标签在我身
                                          ↑ 丢失: 上。
```

**修复**：把条件从 `pos <= max_chars` 改为 `pos <= max_chars + 3`，让搜索缓冲区内找到的标点真正生效。

```python
# subtitle_formatter.py — format_subtitle_single_line 和 format_subtitle_by_mode
# Before:
if pos <= max_chars:
    result = text[:pos]
else:
    result = text[:max_chars]

# After:
if pos <= max_chars + 3:
    result = text[:pos]
else:
    result = text[:max_chars]
```

### ⚠️ clips.yaml 优先于 project.yaml 的 clips 键

**症状：** 往 `project.yaml` 里加了 `clips: {new_series: [...]}` 但 `garden clip -s new_series` 报"无切片定义"。

**根因：** `PipelineConfig._load_project()` 的加载顺序：先检查 `clips.yaml` 文件是否存在 → 存在则用它覆盖 `self._clips` → 只有 `clips.yaml` 不存在时，才读 `project.yaml` 的 `clips` 键（`elif` 分支）。

```python
# pipeline/config.py _load_project
clips_yaml = project_dir / "clips.yaml"
if clips_yaml.exists():
    project_clips = load_yaml(clips_yaml)
    if project_clips:
        self._clips = project_clips           # ← 覆盖！project.yaml 的 clips 被忽略
elif "clips" in project_data:                 # ← 只有 clips.yaml 不存在时才走这里
    self._clips = project_data["clips"]
```

**修复：** 新增系列直接追加到 `clips.yaml`，不要放 `project.yaml`。或者删掉 `clips.yaml` 让 `project.yaml` 的 clips 生效。建议统一用 `clips.yaml` 管理所有切片定义，避免两处分散。生产目录搭建流程见 [production-project-setup.md](references/production-project-setup.md)。

### clips.yaml 风格继承规则

**不要在 clips.yaml 的单个 clip 里设 `style: xxx`。** clip 继承 `project.yaml` 的 `pipeline.subtitle.style`，项目级风格是唯一来源。用户之前的决策就是「一个项目一个风格」，per-clip style 已被废弃。

```yaml
# ✅ 正确 — 不设 style，从项目继承
- id: TEASER01
  segments:
    - start_s: 57
      end_s: 77

# ❌ 错误 — 设了也被 pipeline 忽略，还制造混乱
- id: TEASER01
  style: bold_impact  # 不生效，clip 继承项目风格
  segments: ...
```

### 勘误表勿动原则

**勘误表是用户的知识资产，不能擅自修改或删除。** 用户纠正过的勘误条目（如人名修正），即使看起来和当前音频不一致，也是用户确认过的正确值。错误路径：

```
用户: "字幕和说的话对不上"
                         ↓
❌ 错误：删掉勘误条目试试 → 被纠正 "勘误表是对的，别瞎改"
✅ 正确：问用户具体哪句不对 → 往勘误表加新条目
```

勘误表不是 Hermes 的实验田——每条条目来自用户的实际收听验证。怀疑条目有问题时，问用户，不自己动手改。

### 字幕渲染层溢出（字数 vs 像素宽度脱节）

**症状**：ASS 文件文本完整（如"一般说白头的是代表智慧" 11 字），但播放时文字在画面右边界被裁剪。

**根因**：`segment_subtitle_entries()` 用**字符数**（max_chars_per_line=14）判断是否拆行，但大字号的粗体字实际像素宽度远超字数预算。例如 cinematic 风格 163px 粗体，单字约 179px，11 字 ≈ 1970px，超过 1920px 帧宽。

```python
# 当前逻辑：字数检查
if len(current_text) >= max_chars_per_line:  # 14 → 11 < 14 → 不拆
    should_break = True

# 实际：11 字 × 179px = 1969px > 1920px → 被 libass 裁边
```

**诊断**：ASS 文本完整但播放时边缘被裁 → 不是文本截断，是渲染溢出。计算 `实际字号（含粗体系数）× 字数` 是否超过 `video_width × max_text_width_ratio`。

**修复**：在 `clip_processor.py` 的 `process_clip()` 中，调用 `segment_subtitle_entries` 前根据 style 的实际参数计算像素宽度上限，转换为有效字数上限：

```python
# clip_processor.py — 像素宽度 → 有效字数
char_px = style.font_size * (1.1 if style.bold else 1.0)
max_px = style.video_width * style.max_text_width_ratio
pixel_max_chars = max(6, int(max_px / char_px))
effective_max = min(max_chars, pixel_max_chars)
processed_entries = segment_subtitle_entries(
    clip_entries_raw,
    max_chars_per_line=effective_max,
)
```

原则：**分句在 formatter 阶段做对，不靠渲染层兜底。** 截断到 ASS 渲染层就是废的——libass 在帧边缘硬裁，字幕缺字毫无意义。

**⚠️ style.video_width 与实际输出分辨率不一致**：cinematic 风格默认 `video_width=3840`（4K），但 `garden clip` 实际输出 1920×1080。像素计算用 3840 → `pixel_max_chars=18`（无效），应用 1920 → `pixel_max_chars=9`（正确）。修复：`actual_width = min(style.video_width, 1920)`，因为所有输出最终都是 1080p。

### errata.yaml 格式陷阱

erratas/corrections 文件有两条不同的加载路径，格式要求不同：

1. **`corrections.yaml`（pipeline `load_custom_errata` 路径）** — 需要 `corrections:` 顶层键嵌套：
```yaml
# ✅ pipeline 能读到的格式
corrections:
  报喜鸟啊: 报喜了报喜鸟啊
  应该事一件好事: 应该是一件好事
```

2. **`errata.yaml`（`errata_engine` 路径）** — dict 格式，按类别分组：
```yaml
common:
  俞传奇: 余传奇
  宋瑞: 宋锐
```

**两种格式不兼容。** 写平铺键值对到 `corrections.yaml` 时，`load_custom_errata` 读 `data.get("corrections", {})` 返回空 `{}` → 纠错静默不生效。ASS 文本不变，但无任何报错。

**排查**：字幕没纠错 → 在 `clip_processor.py` 加 `logger.info(f"custom_errata loaded: {len(errata)} entries")` → 输出 0 → 格式问题。

**绕过**：直接加载 corrections.yaml → 正则替换 ASS 文件 → 重烧视频。等 pipeline 修复 `load_custom_errata` 支持平铺格式。

errata_engine 识别的类别：`authors`, `works`, `idioms`, `common`, `variants`, `asr_phonetic`, `asr_noise`。人名修正用 `common`。

### 勘误表勿动原则

当修改 `pipeline/` 下的 Python 文件后 `garden clip` 行为未变：

1. **`.pyc` 缓存** — 删除 `pipeline/__pycache__/clip_processor*.pyc`。Python 可能用旧的字节码。
2. **`print()` 被日志吞** — garden CLI 使用 logging 框架，`print()` 输出不显示。调试用 `logger.info(...)`。
3. **代码在错误分支** — `process_clip()` 中有 `if use_semantic_segmentation:` （默认 `False`）和 `else` 两个分支。garden CLI 不传 `--semantic` 时走 `else` 分支（`process_clip_subtitles`），改了 `if` 分支但实际执行的是 `else` → 无效果。**像素宽度计算等通用逻辑应移到分支之前**，两个路径都适用。

### SubtitleStyle 属性访问层级

`SubtitleStyle` 对象的顶层不直接暴露 `font_size`/`video_width`/`bold` 等渲染参数。这些属性在 `.horizontal` 或 `.vertical`（`OrientationStyle`）子对象中：

```python
# ❌ 错误
style.font_size       # AttributeError
style.video_width     # AttributeError

# ✅ 正确
style.horizontal.font_size
style.horizontal.video_width
style.horizontal.bold
style.horizontal.max_text_width_ratio
```

### FunASR 幻听陷阱

Paraformer-large 在多人对话、语速快、背景噪声等场景下可能**编造不存在的内容**——即 transcript 某时间戳处的文本与实际音频完全不符。不是时间戳偏移，是模型"听错了"。

**已验证案例**：transcript 在 545s 标注"大家好，我是俞传奇，是一名青年编剧导演"，但实际音频说的是"我觉得还是先介绍我们的节目"。

**排查流程**：用户说"字幕和话对不上"→ 对比多个锚点检查是否时间戳系统性偏移 → 排除偏移后→ 大概率 hallucination。

**应对**：找到实际内容在 transcript 中的位置 → 修正 clips.yaml 时间戳。幻觉内容加勘误表没用（文本本来就不对）。无法自动化——靠人肉审。

从 VLM 复刻转向打造原创预定义风格。当前 6 款风格（`cinematic`/`bold_impact`/`broadcast`/`classic_outline`/`frosted_glass_dark`/`minimal_clean`），每条有明确场景定位。风格配置三层架构（用户层/内部层/全局层），xr 为唯一真值。详见 [references/subtitle-styles.md](references/subtitle-styles.md)。

### 转录路径选择

- **有 GPU**（容器）→ `garden transcribe --engine funasr` → `transcript.json`
- **无 GPU**（仅 CPU）→ FunASR MCP (Windows CUDA) → `transcribe_chunked.py` → `transcript.json`
- **拿到 transcript.json 后**：`garden clip` 一步到位。不要手工逐段纠错——garden 内置 errata_engine 自动处理。
- **MCP 端口**：8000（不是 8765）。容器直连 HTTP 返回 406，必须走 Hermes MCP 工具或 Windows 脚本。

详见 [funasr-mcp-transcription.md](references/funasr-mcp-transcription.md)。

### 字幕风格陷阱

提取管线 (`pipeline/subtitle_style_extractor.py`) 有三个已知坑，详见 [references/subtitle-style-extraction-pitfalls.md](references/subtitle-style-extraction-pitfalls.md)：
1. **K-means 颜色反转** — 已迁移 Otsu，旧函数已删除
2. **blur_radius 硬编码** — 参考帧实底变磨砂，已加自动检测
3. **optimize=true + mold=custom 报错** — 优化器不支持自定义 mold，需手动关掉

### VLM 颜色反转陷阱

K-means 颜色聚类在背景框是少数簇时会反转文本/背景颜色。修复方案：Otsu 阈值 + 连通分量分析。详见 [vlm-color-extraction-pitfalls.md](references/vlm-color-extraction-pitfalls.md)

VLM 从参考帧提取字幕颜色时，**可能反转前景/背景色**。已验证案例：geopolitics 参考帧实际黄底黑字，VLM 提取为金字暗底（`text_color: CFBB8B`, `bg_color: 23222B`）。

**强制验证步骤**：
1. VLM 提取后用代码计算字幕区域像素分布，独立确认主色
2. VLM 判断与像素分析不一致时，以像素分析为准
3. 渲染后人工过目确认颜色方向正确

**像素分析参考**：
```python
from PIL import Image
img = Image.open("reference_frame.png")
region = img.crop((x, y, x+w, y+h))  # crop to subtitle area
colors = region.getcolors(maxcolors=10)
```

**VLM 质量反馈循环 (2026-05-27 已实现)：** `extract_style_with_vlm_loop()` 提供 CV 提取 → VLM 9 维度结构化对比 → 自动调参 → 重对比的 3 轮闭环。详见 [VLM 提取循环](references/vlm-style-extraction-loop.md)。Pitfalls：测试帧黑底非真实背景 / xr 优先级 mold > project / 质检门需考虑阴影 / VLM 评分偏宽松。

### Garden CLI 调用

常见陷阱及正确用法见 [garden-cli-pitfalls.md](references/garden-cli-pitfalls.md)。

### `garden clip --only` 不存在 ⚠️

**症状**：尝试 `garden clip --only CRISIS_01` 验证单条切片 → 报错 `Error: No such option '--only'`。

**根因**：`garden clip` 不支持按单个 clip ID 筛选。只有 `-s/--series` 系列级过滤。

**正确做法**：
- 验证单条：将该 clip 单独写进一个临时 clips.yaml 系列，跑完验证后删掉
- 实用替代：选最小的系列先跑，检查第一条 ASS 文件确认字幕质量
- 批量验证后：确认「转录条目: 1481」（修正版）后再全量跑

### CC 协作（样式提取任务）

- VLM 提取任务通常 20-25 轮，`--max-turns 25` 容易不够，建议 30-35
- CC 撞上限退出时已生成的文件保留，补渲即可
- 后台 >10min 无产出 = 卡死，主动 kill
- git commit 被硬封锁，需用户手动提交
- **GLM-5.1 首次 `claude -p` 只出 plan 不写代码**：第一次跑 CC 经常只分析代码库、出计划就停了。此时用户说"让它继续按 plan 实现"→ 写第二份 brief 明确说"实现这个 plan，直接写代码，不要再出 plan"→ 再跑一次。不要认为 CC 失败了——plan 阶段是有价值的，只是需要显式触发实现阶段。
- 详见 [CC 协作参考](references/cc-collaboration.md)
- **🆕 Hermes 不自己分析根因/提方案**：发现 bug 时即使看起来是简单配置修改（如改字号），也直接描述现象给 CC。Hermes 的单点修复容易掩盖整体问题——CC 从代码全貌排查才是正确路径。用户明确纠正："不是这样的，你让cc排查吧"。

### Vision 模型切换

- GLM-4.6V 免费额度耗尽 → 429
- OpenRouter 免费模型（nemotron/gemini-2.0-flash）**不支持 Hermes vision_analyze**（image_url 格式不兼容）
- 绕过：Python base64 直调 API
- 详见 [Vision 模型切换参考](references/vision-model-switching.md)

### custom mold + optimize=true ❌

`mold=custom` 设 `optimize: true` 渲染报错 `'custom'`。规则：mold=custom 必须 `optimize: false`。

**VLM 驱动的提取质量闭环**（2026-05-27 落地）：提取→渲染→VLM 9维度结构化对比→自动调参→重试（最多3轮），解决了旧 Otsu+K-means 路线视觉不匹配的问题。详见 [VLM 风格提取质量闭环](references/vlm-style-extraction-loop.md)。

### yuv420p 奇数高度陷阱（⚠️ ffmpeg 静默失败）
ffmpeg crop 在 yuv420p 格式下遇到奇数高度会悄无声息地降 1px（135→134），导致 alphamerge 尺寸不匹配、输出 mp4 为 0 字节。
诊断：差值恰为 1px → 大概率是此问题。修复：强制偶数量度。
详见 [yuv420p-odd-height-pitfall.md](references/yuv420p-odd-height-pitfall.md)

### CJK 文字测量偏差（毛玻璃背景框宽度）
测量 font_size 与 ASS 渲染 font_size 不一致（如 80 vs 119），叠加 PIL vs libass CJK 宽度 ~18% 低估，导致背景框宽度与实际渲染文字不匹配。
详见 [cjk-text-measurement-pitfalls.md](references/cjk-text-measurement-pitfalls.md)

### ⚠️ `bg_width_scale` 过补偿陷阱

`bg_width_scale`（默认 1.18）最初是为补偿 PIL `getlength()` 低估 CJK 文字宽度 ~18% 而加。但 PIL 改用 Noto Sans SC（Google Fonts 下载）后，纯 CJK 字符都输出 1.0em 宽度——PIL 测量与 libass 渲染完全一致。1.18 是过补偿，背景框会肉眼可见比文字宽。

**诊断信号：** 17字 @119px 文字 2023px，背景框 2435px（×1.18+padding）→ 多了 ~412px

**什么时候真的需要 bg_width_scale：**
- 混合文本（CJK+ASCII）：PIL 和 libass 的 ASCII 宽度差 ~5-9%
- 字体回退路径不同时
- 需要更大呼吸空间的视觉设计

### ⚠️ PIL 测量字体 ≠ libass 渲染字体

PIL 用 Noto Sans SC，libass 用 wqy-zenhei.ttc（fontconfig 无 Noto Sans SC 注册）。

| 文本类型 | 宽度差 | 影响 |
|---------|--------|------|
| 纯 CJK | 0%（都 1.0em） | bg_width_scale=1.0 即够 |
| CJK+EN | ~5-9%（PIL 更宽） | 背景框偏宽 |

### 字体加载静默降级
`_load_font()` 找不到字体时（如 Noto Sans SC 未安装）会静默降级到 ratio 估算，CJK 宽度偏差 ~49%，表现为字幕背景框包不住文字。详见 [font-measurement-diagnostics](references/font-measurement-diagnostics.md)

### 毛玻璃背景框渲染（ffmpeg 滤镜 + ASS 定位）

三个核心陷阱，详见 [frosted-glass-background-bar.md](references/frosted-glass-background-bar.md)：

1. **PIL vs libass 宽度不一致** — 文字锚点必须用 `\an8`（上中）让 libass 自行居中，不要用 PIL 测宽手动算偏移
2. **default.yaml 静默覆盖** — `bg_width_scale` 等参数不应在运行时从 default.yaml 覆盖风格文件中的值
3. **Per-clip 单一 bar 宽度**（架构限制）— ffmpeg 滤镜链整条 clip 只算一次 bar_w，短句也拿最长句的宽度。解决方案：单次模糊 + 逐句裁剪 + `enable='between(t,start,end)'` overlay，详见 [subtitle-background-rendering.md](references/subtitle-background-rendering.md)
4. **`\an8` 锚点消除 PIL/libass 度量差** — 将 ASS 文字锚点从 `\an7`（左上角手动居中）改为 `\an8`（上中），libass 原生居中，不再依赖 PIL 测量精度。详见 [subtitle-background-rendering.md](references/subtitle-background-rendering.md)

### 渲染问题分层诊断
背景框透明度/文字偏移/毛玻璃缺失等视觉问题，先分层隔离再下结论。用纯色背景替代视频帧排除"暗色背景看起来黑"的干扰；用 PIL+numpy 像素级分析替代视觉 API（可能余额不足）。详见 [rendering-layer-isolation.md](references/rendering-layer-isolation.md)

### Style Optimizer 陷阱（2026-05-27）
优化器 `around_base` 从 MOLD xr 起步（非用户 font_size），`_overflow()` 给无背景满分制造错误激励，`bg_width_scale` 调用时未传导。详见 `references/subtitle-style-debugging.md`。

### bg_width_scale 被 default.yaml 无声覆盖（2026-05-27）
`PipelineConfig.subtitle_style` 加载风格后，额外检查 `pipeline.subtitle.bg_width_scale` 并覆盖内部层值。`config/default.yaml` 旧值 1.18 会无声覆盖 `internal.yaml` 的 1.0。
排查：`grep bg_width_scale config/default.yaml`。通用教训：任何被 `PipelineConfig.subtitle_style` 显式 get 的参数都会覆盖三层合并结果。

### 毛玻璃需要真实视频源（2026-05-27）
`video_source` 传入 WAV → ffmpeg 无视频帧做 `crop→boxblur→overlay` → 输出只有音频流。必须用 MP4/MOV。

### 质检门字号阈值（2026-05-27）
横版字号 ≥ 96px（4K 阈值）。`xr × video_height` 需 ≥ 96。4K(2160p) 下 xr ≥ 0.0445。xr=0.044 → 95px 被拦。

### 质检门假阳性：无背景框风格的溢出检查

`quality_gate.py` 的 `run_rule_checks()` 中「文字溢出背景框」检查对所有风格生效，包括 `bg_enabled=false` 的风格（如 cinematic）。无背景框时 `bg_width = text_width * bg_width_scale + 2 * padding_h` 仍然被计算，长文本会触发误报导致 `质检未通过`。

**症状**：cinematic 风格 21 字行被拦（文字实际不溢出，只是计算的 bg_width > max_available）。

**修复**：溢出检查外包 `if style.bg_enabled:` 条件。无背景框时字幕仅检查可见性（outline/shadow），不检查框宽。

```python
# quality_gate.py — run_rule_checks
# Before: 无条件检查 bg_width > max_available
# After:
if style.bg_enabled:
    # overflow check only when background box is rendered
    ...
```

### 像素级分析（视觉 API 备用方案）
视觉 API 经常因余额不足不可用。替代方案：ffmpeg 纯色背景渲染测试帧 → PIL/Numpy 像素分析。
详见 [pixel-analysis-verify.md](references/pixel-analysis-verify.md)

### FunASR MCP 转录

容器内通过 MCP 直接调用 Windows CUDA 加速转录。详见 [funasr-mcp-transcription.md](references/funasr-mcp-transcription.md)。

### ⚠️ delegate_task 子代理：必须写磁盘（2026-06-01 重大教训）

**任何用 delegate_task 做数据处理的场景，子代理必须把结果写入磁盘文件，不能只 return 文本。**

```
❌ 错误：子代理 return "corrected text..." → session 压缩后永久丢失
✅ 正确：子代理 read raw file → process → write corrected file to disk
```

这个教训来自 FunASR 转录纠错：上次 session 跑了 15 个子代理纠错，全部只返回文本在对话里，session 压缩后荡然无存，用户原话「气笑了」。本次 session 改为写磁盘后 19 个 chunk 全部安全落地。

**验证方法**：纠错完成后 `ls corrections/chunk_*_corrected.json | wc -l` 应等于 chunk 总数。

完整工作流见 [FunASR 转录纠错并行工作流](references/funasr-transcription-correction.md)。

### 跨段剪辑（segments 字段）

clips.yaml 支持 `segments` 字段做跨段萃取——从视频不同位置取多段，合并成一条输出。适合爆款短视频（跨章节提取高光时刻）。

```yaml
- id: VIRAL01
  segments:                    # 替代 start_s/end_s
    - start_s: 34
      end_s: 46
    - start_s: 2267
      end_s: 2280
  style: bold_impact
```

工作流层面：在工作流 0 蓝图确认后，制作人根据内容判断是否需要跨段。如需跨段 → 在转录中精确定位每句话的时间戳 → 写入 clips.yaml 的 segments 字段 → 走标准 `garden clip`。

**注意**：跨段剪辑的视频源必须是同一个文件。不同视频文件的片段不支持。字幕样式（xr/font_size/outline）跨段继承项目级设置。

**转录时间戳漂移**：转录重新生成后时间戳整体偏移，之前精确定位的 segments 全部失效。每次换转录后必须重新验证。

### ⚠️ 跨段剪辑：双层字幕陷阱（v2 架构致命缺陷）

**症状：** 最终视频字幕重叠（两层字幕叠在一起），或视频播放时同时看到两组字幕。

**根因：** v2 架构「独立产出 + 后拼接」中，每段走 `process_clip()` 产出的是 **`_subtitled.mp4`**（字幕已烧入画面）。concat 把这些已烧字幕的片段拼在一起后，pipeline 又把完整的 ASS 烧了一层 → 双层字幕。

```
process_clip(seg_0) → seg_0_subtitled.mp4 (字幕已烧)
process_clip(seg_1) → seg_1_subtitled.mp4 (字幕已烧)
                     ↓ concat
                TEASER01_concat.mp4 (画面已有字幕)
                     ↓ 再烧 TEASER01.ass
                TEASER01_subtitled.mp4 (双层字幕！)
```

**诊断方法：**
```bash
# 检查 segment 视频是否已有烧录字幕（只有 video+audio stream = 硬字幕）
ffprobe -v error -show_entries stream=codec_type <segment_subtitled.mp4>
# 输出: video, audio → 字幕已烧入画面（hardcoded）
```

**修复（已验证）：** 从源视频切**无字幕**的 raw segment → concat → 只烧一次 ASS。

```python
# 不再用 segment _subtitled.mp4 做 concat
# 而是从源视频直接 ffmpeg -ss -t cut raw segments
for seg in segments:
    ffmpeg -ss {start} -t {duration} -i source.mp4 -c copy seg_raw_{i}.mp4

# concat raw segments
ffmpeg -f concat -i concat.txt -c copy raw_concat.mp4

# 只烧一次 ASS
ffmpeg -i raw_concat.mp4 -vf ass=full.ass final.mp4
```

**根本修复方向：** pipeline 应产出两种 segment 视频——`_raw.mp4`（无字幕，给 concat 用）和 `_subtitled.mp4`（有字幕，独立观看用）。concat 用 `_raw.mp4`。

### 跨段剪辑：设计演变

**v1（已废弃 — pipeline/multi_segment.py）：管线内部拼接**

最初尝试在管线内做端到端跨段拼接——提取片段→时间戳重算→字幕生成→视频/音频拼接。实测发现两个致命问题：
1. 字幕在拼接步骤丢失（时间戳累加偏移在多人对话碎片化场景下不可靠）
2. 链路太长——提取、字幕、音频、视频全在一条路径，一处断全断

**v2（推荐）：独立产出 + 后拼接**

每段走现有 `process_clip` 独立产出完整字幕视频 → ffmpeg concat 拼成品。字幕已烧在各子视频中，拼接不丢。

核心思路：不要自己做拼接管线。利用已有的成熟 `process_clip`（完整字幕+音频+视频渲染），每段独立产出一条带字幕的成品视频，最后一步用 ffmpeg concat demuxer 拼接。同源视频 codec 一致，`-c copy` 无损拼接。

### 跨段剪辑：转录碎片化

FunASR Paraformer-large 在**两人对话**场景下产出大量短碎片（实测 12 秒内 47 条 subtitle entry），字幕切换频率极高，视觉上跳跃感强，不适合直接做成品。

**症状**：94 条字幕/60 秒视频 → 切换太快，沉浸感丢失。首条字幕甚至可能只有 1-2 个字。

**缓解方向**：
- 跑 DeepSeek 纠错层合并相邻碎片
- 优先选单人独白段落（无交叉说话的时间段）
- 用 SenseVoiceSmall 快速试跑确认段落转录质量后再精确定位

### 飞书视频发送

`send_message` 的 `MEDIA:` 前缀对飞书视频无效（报 `Expecting value` 错误）。正确方式：

```bash
# 1. 压缩到 <30MB（飞书 Bot 限制）
ffmpeg -i input.mp4 -c:v libx264 -crf 28 -preset fast -c:a aac -b:a 128k compressed.mp4

# 2. 提取封面帧
ffmpeg -ss 3 -i input.mp4 -vframes 1 cover.jpg

# 3. lark-cli 发送（文件路径必须相对当前目录）
cd <视频目录> && npx @larksuite/cli im +messages-send \
  --chat-id <oc_xxx> --video "./compressed.mp4" --video-cover "./cover.jpg"
```

限制：Bot 上传 ≤30MB，文件路径必须相对，`--video-cover` 必填。

### 4K 源视频输出被压到 1080p

**症状：** 源视频是 3840×2160，但 `garden clip` 产出的 `_subtitled.mp4` 是 1920×1080。

**根因：** `OrientationStyle` 数据类的 `output_width` 和 `output_height` 默认值就是 1920×1080，即使 `video_width=3840` / `video_height=2160`。pipeline 在 `generate_video_subtitled()` 中读 `style.output_width/output_height` 作为 ffmpeg 输出分辨率。

**修复：** `output_width` 和 `output_height` 都在 `_ORIENTATION_FIELDS` 元组中，所以**可以在风格 yaml 的 `horizontal:` 段直接写**：

```yaml
# config/subtitle_styles/cinematic.yaml
horizontal:
  output_width: 3840
  output_height: 2160
  font_size: 163
  # ... 其他审美参数
```

重跑 `garden clip` 后输出即为 4K。CRF 20 + medium preset + 86 分钟 4K ≈ 30-60 分钟 CPU 编码。

**验证：**
```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height \
  -of csv=p=0 <output_subtitled.mp4>
# 应为: 3840,2160
```

**注意：** 这个修复只影响横版输出。竖版 `output_width/output_height` 在 `vertical:` 段独立设置（通常 1080×1920）。竖版修改前确认实际需求——短视频平台通常只需 1080p。

### 生产目录搭建

从实验阶段进入对外发布时，创建独立生产目录。完整步骤见 [production-project-setup.md](references/production-project-setup.md)。

核心要点：
- 源视频和 transcript 可共享，但配置、切片、输出完全隔离
- 生产目录锁死一种字幕风格
- 4K 源 → 风格 yaml 加 `output_width: 3840` / `output_height: 2160`
- 多期扩展：每期在 `clips.yaml` 新增系列

### 文档空间结构（生产项目）

每个生产项目建议包含标准化 Obsidian vault（A-Z 字母前缀保证混排）：

```
Wiki/
├── A_花园地图          ← 入口 + 全站导航
├── B_宣言
├── D_花园对话/         ← 每期简介 + 透明制作账本
├── E_人类创作/         ← 人类导演独立空间
├── F_AI 创作/          ← AI 导演独立空间
├── I_发布日志/         ← 按日期记录
├── G_发布管线/         ← 多平台策略
├── J_长期反馈/         ← 跨期追踪
├── L_开源说明/         ← 管线仓库链接
└── M_概念花园/         ← llm-wiki
```

人类和 AI 各有独立创作空间，结构同构、节奏自主。

### transcript.json 时间戳全零陷阱

**症状**：`transcript.json`（含 `transcript_aligned.json`）的所有 segment 的 `start_ms`/`end_ms` 均为 0。但用户说"字幕时间是对的"——说明某处有正确时间戳的版本。

**根因**：DeepSeek 纠错管线产出的是 `corrections/chunk_*_corrected.json`（19 个文件，1375 段，含 `start_ms`/`end_ms`），但主 `transcript.json` 从未被更新。纠错输出是准确的，只是没回灌到主文件。

**修复**：合并 corrections/ 下的所有 chunk：
```python
import json, glob
all_segs = []
for f in sorted(glob.glob("corrections/chunk_*_corrected.json")):
    with open(f) as fp:
        data = json.load(fp)
    for s in data['segments']:
        all_segs.append({
            'start': s['start_ms'] / 1000,
            'end': s['end_ms'] / 1000,
            'text': s['text']
        })
with open('transcript_corrected_merged.json', 'w') as fp:
    json.dump({'segments': all_segs}, fp, ensure_ascii=False)
```

**防范**：做任何字幕修复/验证之前，先检查 `corrections/` 目录是否存在已校准的 chunk 文件。不要在零时间戳的 transcript 上浪费时间。

### VAD 交叉验证字幕覆盖

**场景**：用户反馈"字幕有跟丢""时间错乱"——需要客观判断哪些时间段有语音但无字幕。

**方法**：
1. VAD 获取全量语音段 → `mcp_funasr_get_voice_activity_segments(audio_path)`
2. 合并 corrections/ 下的校准 transcript（含时间戳）
3. 交叉比对：对每个 VAD 段检查是否有字幕覆盖

```python
# 核心逻辑
uncovered = []
for vs, ve in vad_segments:
    overlaps = [s for s in subs if s['start'] < ve and s['end'] > vs]
    if not overlaps:
        uncovered.append((vs, ve))
```

**已验证案例**：86 分钟播客 → 619 个 VAD 段 → 发现 1 处 45 秒缺口（2421-2469s，\"艺术的灵魂\"段落完全丢失）。619 段中仅 5 段无覆盖，准确率 99.2%。

详见 [VAD 字幕验证](references/vad-subtitle-verification.md)。

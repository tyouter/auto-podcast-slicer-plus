# garden_core 投产管线 — 权威架构 + 关键渲染事实

> 本库取代旧 `auto-podcast-slicer` 管线。
> 执行层**唯一标准 = garden_core 纯库**（`<repo>/src/garden_core`）。本文件是重建后的权威知识。

## 7-stage 库（pipeline.py 自述「This is a library API, not a watcher」）

```
① ASR转录(stage_asr) → ② 对齐(stage_align/MMS_FA) → ③ 纠错(stage_proofread)
→ (可选 gap heal) → ④ 分段(stage_segment) → ⑤ 裁切(stage_cut)
→ ⑥ 样式(stage_style/8款yaml) → ⑦ 渲染(stage_render) → ✅ render_gate
```

两个入口（都在 `garden_core.pipeline`）：
- `run_from_audio(audio, cut_points, style, engines, opts)` — 全链（需 transcriber）
- `run_from_transcript(transcript, cut_points, style, engines, opts)` — 从已有 transcript 起（execute 层常用）

`Engines(transcriber=, aligner=, llm=, style_resolver=)` 注入所有有状态引擎；`PipelineOptions(render=RenderOptions(...), source_media=, heal_gaps=, render_gate=)`。

**转录走进程内 `FunASRLocal`**（`from garden_core.stage_asr import FunASRLocal`，`device="cuda"`）：`funasr.AutoModel` 直接在 GPU 加载 Paraformer+VAD+Punc+SPK，AutoModel 内部分块。零网络 / 零 server / 零 503。MCP backends（`funasr_backend.py` + `funasr_mcp_backend.py`，~532 行）已删除（commit c956964）——不用搬旧项目的 `transcribe_chunked`，也不再有 `mcp_url`/`sse` 那套坑。跑任何 garden_core python 入口都应在激活的 garden conda env 中运行（受控 PATH，不继承调用者环境）。

## 投产标准流程（audit 三道嵌入）

```
① 项目准备
② 全链转录对齐纠错  → 🛡️ 转录自愈（heal_gaps=True 强制开）
③ 制作人切片规划（人：定主题→切点→确认）
④ 渲染             → 🛡️ render_gate 机械门（render_gate=True 默认开）
⑤ 🛡️ quality-audit 出品终审（LLM四维度，★每条 clip 全审 — 用户铁律：质量优先不省 token）
⑥ 交付（NAS 等）
```

### ⚠️ LLM Proofread 必须显式配置（关键坑）

`ProofOptions` 默认 `enable_llm=False`。不显式开 = LLM 纠错层静默跳过，纠错输出为空。**标准投产调用**：

```python
from garden_core.infra.llm_client import LLMClient
from garden_core.stage_proofread import proofread, ProofOptions, ErrataConfig

llm = LLMClient(default_model="deepseek-chat", timeout=300.0)  # 大 transcript 需 300s
opts = ProofOptions(
    enable_normalize=True,
    enable_errata=True,
    enable_phonetic=True,
    enable_llm=True,          # ← 投产必须显式 True
    enable_dual_channel=True,
)
t = proofread(t, errata=errata, llm=llm, opts=opts, audio_path=AUDIO)
```

- **timeout**：`llm_correct_segments` 将所有 segment 一次塞进单次 API 调用。789 segment ≈ 30K+ token，默认 30s 超时必然炸。≥300s 才稳定。
- **API key**：`LLMClient` 读 `os.environ["DEEPSEEK_API_KEY"]`，garden conda env **不含此变量**。入口脚本必须在 `main()` 开头从项目根的 `.env` 或环境变量 `DEEPSEEK_API_KEY` 注入。
- **errata**：`ErrataConfig(flat={"途材": "FSD", ...})` 做**子串替换**，不是整段匹配。5–10 条手工修正 + LLM 纠错双管齐下效果最好。
- **dual_channel** 批处理（`batch_size=40`），在 LLM 超时时仍能兜底修正 ~10–20 处。

**audit 三道分层原则 —「纳入完整 audit」≠「每道都自动跑」：**
- **转录自愈**（`stage_segment/gap_heal.py`，self-contained VAD 启发式，不依赖旧 subtitle_audio_checker）：机械，⚠️**默认 `heal_gaps=False`**，投产必须显式开。
- **render_gate**（`stage_render/render_gate.py`）：机械，零 LLM，默认开。检查字号比例一致性 / 字幕安全区 / 简体。BLOCK 时抛 `RenderGateError` 精确报「哪条/哪维度/实际vs期望」，从不自动改片。这是**防回归的事后机械防线**——拦机械错（如竖版字号比例失真），不是修 bug。
- **quality-audit**（`media-quality/quality-audit` skill）：重 LLM 四维度（技术/文化/传播/影视制作质量）。**★每条 clip 全审（用户铁律：质量优先，不省 token）**，作为交付前终审节点。它的字幕清单只查字体名/字数/时长，**不查字号比例**——所以拦不住竖版比例 bug，那是 render_gate 的活。

## 竖版坐标系（已修复的关键 bug，永久有效）

竖版是把横版 16:9 画面居中叠在 1080×1920 竖屏画布，画面实际只占中间 **1080×607 内容区**（`content_h = video_width × 9/16`，取偶）。字号和 margin_v **必须按内容区高 607 算，不是全屏 1920**。
- bug 表现：竖版字号按 1920 算 → 比横版大 3.2 倍（如 fresh xr=0.078：错 150px / 对 47px）。
- 修复点：`stage_render/ass_writer.py` 的 `build_ass` 派生 `content_height` + `content_bottom_offset` 下传；16:9 横版画布时 `content_height==video_height、offset==0` 字节级退化为原代码（横版零影响）。
- 对照老项目 `auto-podcast-slicer/pipeline/subtitle_style.py` 的 `_expand_mold_orientation`（`ref_height=content_h`）+ `margin_v` property（`content_bottom` 偏移）。

## 字幕可读性根因（用户实证，非直觉）

**「弱描边看不清」的根因常是字体太瘦，不是描边不够。** 宋体（Serif，如 Noto Serif SC）横画细如发丝，无描边一糊就看不清。靠加黑描边补 = 黑色越多、白区越小，**与「清新干净」反着来**。正解：换笔画饱满的**黑体（Sans，Noto Sans SC Medium weight 500）**，字芯自己够白够亮，描边只留 ~1.5-2.8px 保命。横竖版字号占内容区高比例应一致（如 ~7.8%）。

## 字体商用许可（声明字体前必查）

- ✅ 可商用（SIL OFL）：Noto Serif SC / Noto Sans SC（含 Medium/Bold）/ Source Han Serif SC。Windows 已装。
- ❌ 商用受限：微软雅黑(msyh) / 宋体(simsun) / 黑体(simhei) / 等线(DengXian)。
- ⚠️ libass 字体名不精确匹配时会静默 fallback——新建样式声明的 font_family 只能用白名单字体，否则可能落到受限字体。
- 调试单帧法：复制现成 ASS → 改 Style 行一个数字 → `ffmpeg -ss <t> -i <无字幕母版> -vf "subtitles=x.ass" -frames:v 1 frame.jpg` 抽帧对比。比走全管线快。

## 竖版坐标系（已修，防回归 — 投产必读）
竖版把横版 16:9 画面居中叠在 1080×1920 画布，画面实际只占中间 **1080×607**（= `video_width × 9/16`）的内容区。**字号和 margin_v 必须按内容区高 607 算，不是全屏 1920**——错了竖版字号 3.2 倍偏大（错误 150 vs 正确 47，按 xr=0.078）。

`stage_render/ass_writer.py` 已修：`band_h = round(video_width*9/16)`，竖版用它当字号/坐标基准，margin 再加 `content_bottom_offset` 推到内容区底部。16:9 横版时 `band_h == video_height` → `content_height = video_height, offset = 0` → **字节级退化为原代码，横版零影响**。

- **回归防线**：render_gate 的字号比例检查自动 BLOCK 这类失真（横版 `font/video_height` ≈ 竖版 `font/内容区高`）。
- **排查法**：竖版字幕偏大/悬空时，对照老项目 `auto-podcast-slicer/pipeline/subtitle_style.py` 的 `_expand_mold_orientation`（ref_height）+ `margin_v` property（content_bottom），做等价修复。

# 步骤②-③-④分离工作流（转录→规划→渲染）

当你不确定切哪些片段时，先转录再看内容规划——不要硬凑 `CutPoint` 去调 `run_from_audio`。

## 标准分步走

```python
import sys; sys.path.insert(0, "src")

from garden_core.stage_asr import AudioRef, FunASRLocal, transcribe
from garden_core.stage_align import align
from garden_core.stage_align.mms_aligner import MMSAligner
from garden_core.stage_proofread import proofread, ProofOptions, ErrataConfig

# ② 全链转录+对齐+纠错
audio = AudioRef(path=r"N:\project\source\full.wav")
t = transcribe(audio, FunASRLocal(device="cuda"))
t = align(t, MMSAligner(device="cuda"), audio.path)
t = proofread(t, ErrataConfig.empty(), None, ProofOptions())

# 保存 → 调用方读 transcript → 规划 CutPoint 列表 → 用户确认

# ④ 渲染
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.types import CutPoint

results = run_from_transcript(t, cut_points, "fresh", Engines(),
    PipelineOptions(source_media=r"N:\project\DJI_0089_D.MP4", ...))
```

## 与 `run_from_audio` 的区别

| | `run_from_audio` | 分步走 |
|---|---|---|
| 何时用 | 已知切点，一步到位 | 未知内容，先看再切 |
| 输入 | audio + cut_points | audio（②）→ transcript → cut_points（③） |
| 输出 | list[RenderResult] | ②输出 transcript.json，④输出 RenderResult |
| 适用场景 | 重复切同一素材 | 首次接触素材 |

## 注意事项

- 多段音频拼接后再转录（`ffmpeg -f concat`），避免分段转录导致时间轴断裂
- transcript 保存用 `dataclasses.asdict(t)` + `json.dump`
- 渲染时 `source_media` 指向原始视频文件（不是拼接音频）

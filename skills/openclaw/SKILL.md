# garden_core — AI-powered video production pipeline

You are a video producer. Use garden_core to transcribe, subtitle, cut, and render videos. All code goes through `src/garden_core/` — a pure Python library.

## Setup

```bash
# Conda (recommended)
conda env create -f environment.yml
conda activate garden

# pip
pip install -e '.[gpu]'
```

## Production Flow

1. **Transcribe + Align + Proofread**
```python
import sys; sys.path.insert(0, "src")
from garden_core.stage_asr import AudioRef, FunASRLocal, transcribe
from garden_core.stage_align import align
from garden_core.stage_align.mms_aligner import MMSAligner
from garden_core.stage_proofread import proofread, ProofOptions, ErrataConfig
from garden_core.infra.llm_client import LLMClient

audio = AudioRef(path="source/full.wav")
t = transcribe(audio, FunASRLocal(device="cuda"))
t = align(t, MMSAligner(device="cuda"), audio.path)
t = proofread(t, ErrataConfig.empty(), LLMClient(timeout=300),
              ProofOptions(enable_llm=True, enable_dual_channel=True))
```

2. **Plan cuts** — read transcript, propose clips, get user approval

3. **Render**
```python
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

cuts = [CutPoint(clip_id="v1", source_media="source/video.mp4", start_s=10.0, end_s=60.0, style_name="fresh")]
results = run_from_transcript(t, cuts, "fresh", Engines(),
    PipelineOptions(source_media="source/video.mp4",
                    render=RenderOptions(output_dir="output/",
                                         horizontal_width=3840, horizontal_height=2160))))
```

## Rules

- **Never hand-write AutoModel()**. Use garden_core's stage_asr API.
- **Always run align + proofread**. Both are mandatory.
- `enable_llm=True` must be explicit. Default is off.
- Unknown cut points → transcribe first, then plan. See `references/transcribe-then-cut-workflow.md`.
- Multi-source videos → transcribe concatenated audio, render per-source with offset timestamps.

## Quality

- `render_gate`: automatic font_ratio + safe_area check (BLOCKs bad clips)
- `quality-audit`: technical, cultural, communication, production review

## Styles

- `fresh` — Noto Sans SC Medium, white, 2.8px outline, no background
- `cinematic` — Noto Serif SC, film serif

## Reference

Full docs in `references/`. Key files:
- `garden-core-api.md` — API reference
- `transcribe-then-cut-workflow.md` — unknown content workflow
- `proofread-llm-required.md` — LLM config iron law
- `multi-source-video-rendering.md` — multiple video sources

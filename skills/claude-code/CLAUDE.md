# garden_core — AI-powered video production pipeline

You are a video producer. Use garden_core to transcribe, subtitle, cut, and render videos.

## Quick Start

```python
import sys; sys.path.insert(0, "src")
from garden_core.stage_asr import AudioRef, FunASRLocal, transcribe
from garden_core.stage_align import align
from garden_core.stage_align.mms_aligner import MMSAligner
from garden_core.stage_proofread import proofread, ProofOptions, ErrataConfig
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint
```

## Production Workflow

1. Project setup — create output directories, corrections.yaml
2. Transcribe + align + proofread (full chain: ASR → MMS_FA → errata+LLM)
3. Plan cuts — read transcript, propose clip boundaries, get user approval
4. Render — `run_from_transcript()` with 4K fresh style

## Hard Rules

- NEVER hand-write AutoModel() calls. Always use garden_core's stage_asr API.
- Always run align + proofread. Skipping = incomplete subtitles.
- LLM proofread requires `ProofOptions(enable_llm=True)` + `LLMClient(timeout=300)`.
- For unknown cut points: transcribe first, read content, then plan cuts. See references/transcribe-then-cut-workflow.md.
- Multi-source videos: transcribe on concatenated audio, render per-source with offset timestamps. See references/multi-source-video-rendering.md.

## Environment

- Conda env `garden` (funasr 1.3.9 / torch 2.7+cu118 / numpy 2.4)
- Or `pip install -e '.[gpu]'` from repo root
- FFmpeg must be on PATH

## Styles

- `fresh` — Noto Sans SC Medium, white text, outline 2.8px, shadow 2.5px, no background
- `cinematic` — Noto Serif SC, film-style serif

## Entry Points

- `run_from_audio(audio, cut_points, style, engines, opts)` — full chain ASR→render
- `run_from_transcript(transcript, cut_points, style, engines, opts)` — from existing transcript
- `run_montage(transcript, cut_points, style, engines, opts, montage_id)` — multi-segment concat

## Quality Gates

- render_gate (mechanical, auto): font_ratio + safe_area checks
- quality-audit (LLM): technical/cultural/communication/production review

## Delivery Format

```
────────────────────────
Project · Auto Clip

Result
· X min source → N atomic clips
· Original dialogue + reactions preserved
· Horizontal 4K + vertical, all-platform

Capabilities
1. Intent alignment
2. Atomic function identification
3. Cut plan recommendation
4. Auto subtitle + AI proofread
5. Mechanical quality gate
6. Final review
7. Dual format rendering

Output: <path>
────────────────────────
```

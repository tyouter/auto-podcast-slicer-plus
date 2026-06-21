# garden-core

A clean rewrite of the podcast clipping + subtitle pipeline. The legacy
`auto-podcast-slicer` is **frozen** as a reference; this package is a
from-scratch re-architecture designed for clarity, stability, and subtitle
quality.

## Why a rewrite

The legacy codebase had accumulated structural problems: scattered LLM calls
that silently swallowed errors and reported false PASSes, two parallel style
systems, two parallel segmenters, three different "entry" shapes flowing
between stages, a ms/s unit split, and config carried in module-level mutable
globals that leaked across concurrent projects. See `ARCHITECTURE.md` for the
full problem→fix mapping.

## Design principles

1. **Immutable dataclass flow.** Every stage output is `frozen=True`. Stages
   never mutate; they build new values. No module-level mutable globals.
2. **Engines loaded once, reused.** ASR / aligner / LLM / style-resolver are
   stateful objects injected into the pipeline — never constructed per call
   (the WhisperX discipline).
3. **Unified LLM gateway.** All DeepSeek/VLM traffic goes through one
   `LLMClient` with timeout, retry, and *explicit* degradation logging. An LLM
   outage is never silently turned into "quality check passed".
4. **One stage = one responsibility.** No overlapping `apply_errata` /
   `validate_errata` name collisions. errata only *applies*; phonetic only
   *detects*.
5. **One time unit, one subtitle type.** Seconds everywhere internally; `Cue`
   is the single subtitle shape from segmentation through rendering.

## The 7 stages

```
audio ─▶ [1 asr]        ─▶ Transcript
       ─▶ [2 align]      ─▶ Transcript  (word timing filled; no-op if ASR already gave it)
       ─▶ [3 proofread]  ─▶ Transcript  (normalize → errata → phonetic → LLM → dual-channel)
       ─▶ [4 segment]    ─▶ tuple[Cue, ...]
       ─▶ [5 cut]        ─▶ tuple[ClipPlan, ...]
       ─▶ [6 style]      ─▶ StyleDef
       ─▶ [7 render]     ─▶ RenderResult (horizontal + vertical mp4, srt, ass)
```

## Quick start

```python
from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.io_.source import load_transcript_json
from garden_core.types import CutPoint
from garden_core.stage_style import StaticResolver

transcript = load_transcript_json("transcript_aligned.json")
cuts = [CutPoint(clip_id="c1", start_s=10.0, end_s=70.0, style_name="default")]

results = run_from_transcript(
    transcript, cuts, "default",
    Engines(),
    PipelineOptions(),
)
```

## Environment

Heavy deps (torch/CUDA, funasr, PIL, ffmpeg) are provided by the shared venv at
`../auto-podcast-slicer/.venv`. This package only pins lightweight deps.

## Status

Milestone 0 (skeleton + types + infra) is complete. Milestones 1–3 fill in the
stage implementations; see the project todo list.

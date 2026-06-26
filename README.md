# garden-core

**AI-powered podcast / long-video clipping & subtitle pipeline.** Feed it a long
audio or video, and garden-core transcribes it, fills in millisecond-accurate
word timing, proofreads the transcript (rule-based + LLM), segments it into
subtitle cues, cuts it into clips, and renders each clip as a finished video —
**horizontal 4K + vertical**, with burned-in subtitles plus `.srt` / `.ass`
sidecars.

It is a **pure Python library** (`src/garden_core/`) with no watcher, no server,
and no global state — every stage is an immutable, injectable function. Three
ready-to-mount agent skills (`skills/hermes`, `skills/claude-code`,
`skills/openclaw`) wrap the library so an AI agent can drive the whole pipeline.

## What it can do

- **Transcribe** Chinese speech in-process with FunASR (Paraformer + VAD + Punc +
  Speaker), GPU-accelerated, chunked for OOM-safe long audio.
- **Align** to millisecond-accurate word timing with MMS forced alignment.
- **Proofread** the transcript: normalize → errata substitution → phonetic
  detection → LLM correction → dual-channel merge. The LLM gateway has explicit
  timeout/retry/degradation logging — an LLM outage is never silently reported as
  "passed".
- **Segment** into subtitle cues, **cut** into clips, apply a **style**, and
  **render** to horizontal 4K + vertical MP4 with `.srt` / `.ass`.
- **Quality gates**: a mechanical `render_gate` (font-ratio + safe-area checks
  that BLOCK bad clips) and an optional LLM quality audit.

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

## Installation

garden-core ships its own cross-platform environment configuration — use it
directly, no external venv needed. **FFmpeg must be on your `PATH`** (the conda
environment includes it).

### One-click

```bash
# Linux / macOS
./setup.sh

# Windows (PowerShell)
./setup.ps1
```

The script creates the conda environment if `conda` is available, otherwise falls
back to a pip install.

### Conda (recommended — pins torch/CUDA, funasr, ffmpeg)

```bash
conda env create -f environment.yml
conda activate garden
```

### pip

```bash
pip install -e '.[gpu]'   # or '.[cpu]' for CPU-only torch
```

### Verify

```bash
python -c "from garden_core.stage_asr import FunASRLocal; print('OK')"
```

## Quick start

The library uses a `src/` layout. After `pip install -e .` you can `import
garden_core` directly; inside a conda env, run from the repo root with `src` on
the path.

```python
import sys; sys.path.insert(0, "src")  # not needed if you ran `pip install -e .`

from garden_core.pipeline import run_from_transcript, Engines, PipelineOptions
from garden_core.io_.source import load_transcript_json
from garden_core.stage_render import RenderOptions
from garden_core.types import CutPoint

transcript = load_transcript_json("transcript_aligned.json")
cuts = [CutPoint(clip_id="c1", source_media="source/video.mp4", start_s=10.0, end_s=70.0, style_name="fresh")]

results = run_from_transcript(
    transcript, cuts, "fresh",
    Engines(),
    PipelineOptions(
        source_media="source/video.mp4",
        render=RenderOptions(output_dir="output/",
                             horizontal_width=3840, horizontal_height=2160),
    ),
)
```

For the full chain starting from audio (ASR → render), use `run_from_audio(...)`
with a transcriber in `Engines(...)`. See `skills/*/references/garden-core-api.md`
for the complete API.

## Quick start — `project.yaml` (T7–T12)

> *New in garden_core 2.0.* `garden_core.project` makes a project a first-class
> citizen: one `project.yaml` describes sources / cut-points / render options /
> proof options in a single place. An agent no longer hand-rolls a per-project
> transcribe/render script — it calls `ProjectRun` orchestration methods instead.

### Create a project

```python
from garden_core.project import create_project, SourceSpec, ProjectRun
from garden_core.pipeline import Engines

cfg = create_project(
    name="<project-name>",
    root_dir="/path/to/project",
    sources=[SourceSpec(id="<src-1>", path="/path/to/source.mp4")],
    audio_path="source/<name>.wav",
    style="fresh",
)
# Writes: /path/to/project/{project.yaml, corrections.yaml, source/, output/...}
```

### Run the full pipeline

```python
run = ProjectRun.from_project_dir(
    "/path/to/project",
    Engines(transcriber=..., aligner=..., llm=...),
)
run.transcribe()   # then: human review transcript → edit corrections.yaml → proofread
run.proofread()
run.render()
run.audit()
# or one-shot: results = run.all()
```

### Incremental re-runs

```python
run.rerender(["<clip-id-1>", "<clip-id-3>"])         # re-render only those two
run.reproofread(rerender_clip_ids=["<clip-id-1>"])    # incremental fix + auto re-render
```

The authoritative schema reference is `schema/project.schema.yaml`. Full
architecture coverage is in [`ARCHITECTURE.md`](ARCHITECTURE.md) under
“Project management layer”.

## Skills — drive the pipeline from an AI agent

Each platform folder is a **self-contained, clone-and-use skill**: one entry file
plus its own `references/` (the same technical docs, written platform-neutral).
Install the environment above, then mount the entry file for your platform.

| Platform     | Entry file                   | How to mount                                                                 |
|--------------|------------------------------|-----------------------------------------------------------------------------|
| Hermes       | `skills/hermes/SKILL.md`     | Load as a Hermes agent skill; `references/` is read on demand.               |
| Claude Code  | `skills/claude-code/CLAUDE.md` | Use as the project's `CLAUDE.md` (or a Claude Code skill); `references/` for deep dives. |
| OpenClaw     | `skills/openclaw/SKILL.md`   | Load as an OpenClaw skill; `references/` is read on demand.                  |

Every entry file gives the agent the production workflow (transcribe → align →
proofread → plan cuts → render), the hard rules (always align + proofread; LLM
proofread must be enabled explicitly), the available styles, and the quality
gates. The `references/` folders hold the deep technical docs — garden-core API,
FunASR long-audio handling, forced alignment, subtitle style/readability, the
vertical-layout coordinate system, Windows DLL/PATH/ffmpeg pitfalls, and more.

## Status

**Complete and production-validated.** All 7 stages are implemented; the full
chain (ASR → align → proofread → segment → cut → style → render) has been run
end-to-end on real podcast material, producing horizontal 4K + vertical MP4 with
burned-in, AI-proofread subtitles and `.srt` / `.ass` sidecars.

## Architecture

garden-core is a clean rewrite of an earlier clipping pipeline, built around
immutable dataclass flow, engines loaded once and injected, a unified LLM gateway
with explicit degradation logging, one responsibility per stage, and a single
time unit (seconds) and subtitle type (`Cue`) end to end. The full
problem → fix mapping and design rationale live in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## License

MIT — see `pyproject.toml`.

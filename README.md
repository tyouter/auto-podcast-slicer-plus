# garden-core

**AI-powered video production pipeline.** Feed it long audio/video, get finished clips with burned-in subtitles — horizontal 4K + vertical, `.srt`/`.ass` sidecars.

Pure Python library (`src/garden_core/`). No server, no watcher, no global state. Every stage is an injectable function.

## What it does

- **Transcribe** Chinese speech with FunASR (Paraformer + VAD + Punc + Speaker), GPU-accelerated
- **Align** to millisecond word timing with MMS forced alignment
- **Proofread** via errata substitution → phonetic detection → LLM correction → dual-channel merge
- **Cut** into clips, apply **subtitle styles**, **render** to 4K MP4
- **Quality gates**: mechanical `render_gate` + optional LLM audit

## Quick Start

```python
from garden_core.project import create_project, load_project, ProjectRun, SourceSpec
from garden_core.pipeline import Engines
from garden_core.stage_asr import FunASRLocal

# 1. Create project
cfg = create_project(
    "<name>", "<root>",
    sources=[SourceSpec(id="SRC1", path="<source>.mp4")],
    audio_path="<audio>.wav",
)

# 2. Run pipeline
run = ProjectRun(load_project("<root>"), Engines(transcriber=FunASRLocal("cuda")))
run.transcribe()   # ASR + align → transcript.json
run.proofread()    # errata + LLM → updated transcript
# → edit project.yaml cut_points → reload
run.render()       # clips + subtitles → output/clips/
run.audit()        # ffprobe + ASS gate → audit_report.json
```

Full API: `skills/hermes/references/garden-core-api.md`

## Skills

Three self-contained agent skills — clone the repo, mount the entry file:

| Platform    | Entry |
|-------------|-------|
| Hermes      | `skills/hermes/SKILL.md` |
| Claude Code | `skills/claude-code/SKILL.md` |
| OpenClaw    | `skills/openclaw/SKILL.md` |

All three share identical content. Each includes `references/garden-core-api.md` (645-line API reference) and `references/project-directory-template.md`.

## Installation

```bash
conda env create -f environment.yml
conda activate garden
# FFmpeg included in conda env
```

## License

MIT

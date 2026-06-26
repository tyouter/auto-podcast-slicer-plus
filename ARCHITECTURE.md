# garden-core architecture

This document records *why* the rewrite exists: the structural problems in the
legacy `auto-podcast-slicer` and exactly how this codebase addresses each one.
The legacy code is frozen and kept only as a reference.

## The 7 stages

```
audio ─▶ [1 asr]        ─▶ Transcript
       ─▶ [2 align]      ─▶ Transcript  (word timing; no-op if ASR gave it)
       ─▶ [3 proofread]  ─▶ Transcript  (normalize → errata → phonetic → LLM → dual-channel)
       ─▶ [gap-heal]     ─▶ Transcript  (optional: recover speech-with-no-subtitle)
       ─▶ [4 segment]    ─▶ tuple[Cue, ...]
       ─▶ [5 cut]        ─▶ tuple[ClipPlan, ...]
       ─▶ [6 style]      ─▶ StyleDef
       ─▶ [7 render]     ─▶ RenderResult (horizontal + vertical mp4, srt, ass)
```

## Step API (public pipeline entry points)

Each step is a bare-verb function re-exported from ``garden_core.steps``.
Stage 6 (style resolution) is an internal helper of step 6 — ``render()``
consumes a resolved ``StyleDef``; the pipeline resolves it via ``resolve_style``
before calling ``render()``.

| step | function | source module | product | disk pair |
|------|----------|---------------|---------|-----------|
| 1 | ``transcribe(audio, engine, hotwords)`` | ``stage_asr`` | ``Transcript`` | ``save_transcript_json`` / ``load_transcript_json`` |
| 2 | ``align(transcript, aligner, audio_path)`` | ``stage_align`` | ``Transcript`` | ``save_transcript_json`` / ``load_transcript_json`` |
| 3 | ``proofread(transcript, errata, llm, opts, audio_path)`` | ``stage_proofread`` | ``Transcript`` | ``save_transcript_json`` / ``load_transcript_json`` |
| 4 | ``segment(transcript, opts)`` | ``stage_segment`` | ``tuple[Cue, ...]`` | *(intermediate — feeds step 5)* |
| 5 | ``cut(transcript, cues, cut_points)`` | ``stage_cut`` | ``tuple[ClipPlan, ...]`` | *(intermediate — feeds step 6)* |
| 6 | ``render(clip, style, opts)`` | ``stage_render`` | ``RenderResult`` | ``RenderResult`` fields are file paths |

Import::

    from garden_core.steps import transcribe, align, proofread, segment, cut, render

Each stage is a pure function `(input data, injected engines) → output data`.
The only code that touches the filesystem is `io_/`. Everything else builds
immutable values.

## Project management layer (T7–T12)

`garden_core.project` is an **optional orchestration layer** on top of the step
API.  It makes a *project* a first-class citizen (D1): a `project.yaml` + a
directory tree, so an agent never hand-rolls a transcribe/render script.  It
does **not** modify the three public pipeline entry points
(`run_from_audio` / `run_from_transcript` / `run_montage`).

### Public API

Import::

    from garden_core.project import (
        ProjectConfig,     validate,
        ProjectMeta,       SourceSpec,   CutPointSpec,
        RenderOptsSpec,    ProofOptsSpec, TranscriptSpec,
        create_project,    load_project, edit_project,
        ProjectRun,
    )

| task | symbol | role |
|------|--------|------|
| T7 | `ProjectConfig` / `validate` | Top-level `project.yaml` data model + structural & reference validation (6 checks; no filesystem) |
| T7 | `ProjectMeta` / `SourceSpec` / `CutPointSpec` / `RenderOptsSpec` / `ProofOptsSpec` / `TranscriptSpec` | Frozen spec value objects; each has `from_dict` / `to_dict` round-trip |
| T8 | `create_project(name, root_dir, *, sources, ...)` | Create directory tree (`output/clips,fullcut,release` + `source/` + optional Wiki) + write `project.yaml` + `corrections.yaml` + `AGENTS.md` / `README.md`; returns validated `ProjectConfig` |
| T9 | `load_project(path, *, strict=True)` | Accept yaml file path or root directory → resolve all relative paths to absolute → `validate()` → optional strict file-existence check; returns runtime-view config |
| T10 | `edit_project(root_dir, /, **overrides)` | Read config → field-level override (scalar / nested-spec partial merge / set replacement) → `validate()` → atomic write back to `project.yaml` |
| T11 | `ProjectRun(cfg, engines)` | Runtime orchestrator; each stage produces one artifact + writes `<root>/run_manifest.json` (`schema_version=1`) |
| T11 | `ProjectRun.from_project_dir(dir, engines)` | One-liner load + run |
| T11 | `ProjectRun.load(manifest_path, engines)` | Reconstruct a run from a previous manifest → can `.resume()` |
| T11 | `run.transcribe() / .proofread() / .render() / .audit()` | Four staged methods, each returns `StageResult` |
| T11 | `run.all()` | Full pipeline, always runs every stage (idempotent overwrite) |
| T11 | `run.resume()` | Skip stages marked `done` in manifest whose artifact still exists (D5 naive skip) |
| T12 | `run.rerender(clip_ids)` | Re-render only specified clips (`skip_existing=False` override); no re-transcribe / re-proofread |
| T12 | `run.reproofread(errata=None, *, rerender_clip_ids=None)` | Incremental correction (optional temporary `ErrataConfig`, not persisted) + optional auto re-render of specified clips |

### `project.yaml` as first-class citizen (D1)

Three previously scattered config sources are unified into `project.yaml` +
`corrections.yaml` + style yaml (`stage_style/styles/<name>.yaml`).  The single
authoritative schema reference is `schema/project.schema.yaml`.

### Multi-source translation

```
cfg.cut_points  (CutPointSpec: global timeline + source id)
    → _translate_cut_points()
    → types.CutPoint  (source_media = absolute path + source_offset_s)
```

One `run.render()` replaces hand-rolled multi-source batch scripts.

### `run_manifest.json` (D6)

```json
{
  "schema_version": 1,
  "project": {"name": "...", "root": "..."},
  "updated": "<iso8601>",
  "stages": [
    {"stage": "transcribe", "status": "done", "artifact_path": "...",
     "params": {...}, "started": "...", "finished": "..."}
  ]
}
```

`resume()` reads this manifest and skips stages whose `status=="done"` and whose
artifact file still exists (D5).  `ProjectRun.load(manifest)` rebuilds a run
from a prior manifest for continuation.

### Design constraints (hard)

- Does **not** modify `run_from_audio` / `run_from_transcript` / `run_montage`
- Does **not** modify any `stage_*` / `io_*` / `render_gate` / `types` module
- Does **not** modify T7–T10 project modules (schema / config / create / load / edit)
- Manifest is **not** concurrency-safe (single-machine serial assumption)

## Problem → fix map

| Legacy problem | Fix | Location |
|---|---|---|
| **ms/s double time unit** (3 entry shapes flowed between stages) | One unit (seconds) everywhere; `Cue` is the single subtitle type | `types.py`, `io_/source.py` (only place ms↔s happens) |
| **3 different "entry" shapes** (SubtitleEntry / raw dict / processed dict) | One `Cue` flows segment→cut→render | `types.py` |
| **spk / word timing dropped in the production path** | `Segment.words` is first-class; aligner fills it | `types.py`, `stage_align/` |
| **#3 dual style systems** (SubtitleStyle + StyleDefinition drifted) | One `StyleDef`, one `resolve_style` path | `stage_style/molds.py` |
| **#5 gap-heal never deduplicated** (repeated rounds piled up overlaps) | `insert_segments` drops overlaps + near-dupes; fail-safe guard | `stage_segment/gap_heal.py` |
| **#6 polish ran per-chunk** (no cross-chunk context) | LLM corrector runs on the whole transcript | `stage_proofread/llm_corrector.py` |
| **#7 LLM calls scattered + silently swallowed errors** (false PASS) | Unified `LLMClient` with timeout/retry; UNAVAILABLE is never silent | `infra/llm_client.py` |
| **#9 config in module-level mutable globals** (leaked across projects) | All config is a value passed explicitly; no globals | `config.py`, all stages |
| **#10 dual transcribers duplicated** | One `Transcriber` interface; FunASR/Whisper are swappable backends | `stage_asr/` |
| **#11 time parse/format duplicated + fragile** | One `time_util` owns ASS/SRT/heuristic parsing | `infra/time_util.py` |
| **#12 `eval()` on ffprobe fps** | Safe `Fraction` parsing | `infra/media_probe.py` |
| **#14 `bold` accepted but ignored** in width measurement | Real bold-variant font loading | `stage_render/text_measure.py` |
| **errata/validator name collision** (two `apply_errata` w/ different sigs) | errata = apply-only; phonetic = detect-only; one return type | `stage_proofread/errata.py`, `phonetic.py` |

## Design principles

1. **Immutable dataclass flow** — every stage output is `frozen=True`. Stages
   evolve data via `dataclasses.replace`, never mutation. No module-level
   mutable state anywhere.
2. **Engines loaded once, reused** (WhisperX discipline) — ASR, aligner, LLM,
   style-resolver are stateful objects injected into the pipeline, never
   constructed per call.
3. **Unified LLM gateway** — all DeepSeek/VLM traffic goes through `LLMClient`.
   `LLMOutcome.UNAVAILABLE` and `.DEGRADED` are distinct, explicit states; an
   outage is *never* turned into "quality check passed".
4. **One stage = one responsibility** — no overlapping function names, no
   apply/detect confusion.
5. **One time unit, one subtitle type** — seconds internally; `Cue` is the only
   subtitle shape.
6. **Fail-safe, not silent** — when something can't be done (no audio, no LLM,
   would-create-overlap), the pipeline degrades visibly (warning + unchanged
   data) rather than fabricating output.

## The hard quality rule

Subtitle cues must **never** overlap. This is enforced in two places:
- `gap_heal.has_overlaps` rejects any merge that would overlap.
- The pipeline flattens any overlapping cues defensively before render
  (`_flatten_overlaps`).

Tests in `tests/test_gap_heal.py` and `tests/test_pipeline_invariants.py`
lock this invariant, including a repeated-round stress test.

## What's out of scope (deliberately)

- The cross-boundary problem (Agent in Docker, editing on Windows CUDA). This
  rewrite is a *library*. The watcher / HTTP-service layer is a future layer on
  top. The legacy watcher is preserved unchanged in the old repo.
  `garden_core.project` is an in-library orchestration layer — still library, not
  a watcher or server.
- A full multimodal dual-channel pass (audio bytes to a VLM). The current
  `dual_channel.py` approximates "audio-conditioned" correction with context
  windows; it's structured to swap in a true audio-capable model later.
- A full pypinyin-based phonetic confusion detector. `phonetic.py` ships a
  small high-confidence table; the full forward-max-match detector is a later
  enhancement.

## Verification

- 303 unit tests pass (`pytest tests/`), with 7 pre-existing failures in
  `test_render.py` (5: ASS TypeErrors from font-size hardening) and
  `test_stage_proofread.py` (2: OpenCC normalize), unrelated to project layer.
  Includes 164 project-management tests across 7 test files
  (`test_project_config` / `test_project_validate` / `test_create_project` /
  `test_load_project` / `test_project_edit` / `test_project_run` /
  `test_project_rerun`).
- End-to-end: a real 4K source + legacy transcript renders both horizontal and
  vertical mp4 with burned-in subtitles (`tests/smoke_e2e.py`).
- MMS forced alignment verified on real audio: 88 char-level timestamps
  produced across 5 segments (`tests/smoke_m2.py`).
- The one path not yet exercised live is FunASR-from-audio (MCP server not
  running in the dev env); it's protected by the bug-#4 assertion.

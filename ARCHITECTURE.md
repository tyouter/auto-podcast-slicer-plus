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

Each stage is a pure function `(input data, injected engines) → output data`.
The only code that touches the filesystem is `io_/`. Everything else builds
immutable values.

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
- A full multimodal dual-channel pass (audio bytes to a VLM). The current
  `dual_channel.py` approximates "audio-conditioned" correction with context
  windows; it's structured to swap in a true audio-capable model later.
- A full pypinyin-based phonetic confusion detector. `phonetic.py` ships a
  small high-confidence table; the full forward-max-match detector is a later
  enhancement.

## Verification

- 80 unit tests pass (`pytest tests/`).
- End-to-end: a real 4K source + legacy transcript renders both horizontal and
  vertical mp4 with burned-in subtitles (`tests/smoke_e2e.py`).
- MMS forced alignment verified on real audio: 88 char-level timestamps
  produced across 5 segments (`tests/smoke_m2.py`).
- The one path not yet exercised live is FunASR-from-audio (MCP server not
  running in the dev env); it's protected by the bug-#4 assertion.

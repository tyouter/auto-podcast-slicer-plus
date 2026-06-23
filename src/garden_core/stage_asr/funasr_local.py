"""In-process FunASR backend — the standard single-machine ASR engine.

Loads Paraformer-large + VAD + Punc + SPK directly on the local GPU via
``funasr.AutoModel`` (no MCP server, no HTTP transport). This is the
production backend for Windows-native single-machine batch processing:
zero network overhead, RTF ~0.03 on CUDA.

Models are pulled from the shared modelscope cache; ``funasr`` is imported
lazily so importing this module stays cheap and side-effect free.

**Long-audio safety**: feeding an 86-minute file to ``generate`` in one call
leaks CUDA memory across the model's internal batches (the MCP-era pipeline hit
``CUDA error: unknown error`` / OOM after ~8×5-min worth of audio). To make
*the code* — not human babysitting — guarantee a clean run, ``transcribe``:

  * runs a lightweight VAD pass over the whole file to find speech spans,
  * groups those spans into chunks of ``chunk_target_s`` whose boundaries fall
    in **silence between spans** (so no sentence is ever cut in half — no
    dropped/duplicated sentences at chunk seams),
  * transcribes each chunk on its own, releasing CUDA memory + a short cooldown
    *between* chunks so leaked allocations are reclaimed before the next chunk,
  * offsets each chunk's millisecond timestamps by the chunk start so the
    merged transcript carries absolute timestamps right to the tail.

Tradeoff (intentional, out of surgical scope to fix): the cam++ speaker model
clusters *within each chunk*, so speaker ids are only locally consistent —
``"0"`` in chunk 5 is not guaranteed to be the same person as ``"0"`` in chunk
3. Whole-file speaker re-clustering would require carrying embeddings across
chunks, which this change deliberately does not do. Ids keep the same plain
numeric format as the single-pass output so downstream stays unchanged.
"""

from __future__ import annotations

import time

from garden_core.stage_asr import AudioRef, Transcriber
from garden_core.types import Segment, Transcript

__all__ = ["FunASRLocal"]

_SAMPLE_RATE = 16000

_VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"


class FunASRLocal(Transcriber):
    """Transcribe using FunASR's AutoModel directly (no MCP server)."""

    def __init__(
        self,
        device: str = "cuda",
        chunk_target_s: float = 300.0,
        cooldown_s: float = 0.5,
    ):
        self._model = None
        self._vad = None
        self._device = device
        self._chunk_target_s = chunk_target_s
        self._cooldown_s = cooldown_s

    @property
    def name(self) -> str:
        return "funasr-local"

    def _load_model(self):
        if self._model is not None:
            return
        from funasr import AutoModel
        self._model = AutoModel(
            model="iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            vad_model=_VAD_MODEL,
            punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
            spk_model="iic/speech_campplus_sv_zh-cn_16k-common",
            device=self._device,
            batch_size_s=300,
        )
        # A separate VAD-only model used purely to plan silence-aligned chunk
        # boundaries before transcription. fsmn-vad is tiny and streaming, so a
        # single pass over an hour-plus of audio is cheap and never OOMs.
        self._vad = AutoModel(model=_VAD_MODEL, device=self._device)

    def transcribe(self, audio: AudioRef, hotwords: tuple[str, ...] = ()) -> Transcript:
        self._load_model()
        import gc

        import numpy as np
        import soundfile as sf

        try:
            import torch
        except Exception:  # pragma: no cover - torch is always present with funasr
            torch = None

        wav, sr = sf.read(audio.path, dtype="float32")
        if wav.ndim > 1:  # defensive: collapse stereo to mono
            wav = wav.mean(axis=1)
        if sr != _SAMPLE_RATE:
            raise ValueError(
                f"FunASRLocal expects {_SAMPLE_RATE} Hz mono audio, got {sr} Hz "
                f"({audio.path}); resample to 16k mono before transcribing."
            )
        total_s = len(wav) / _SAMPLE_RATE

        t0 = time.monotonic()

        # 1) VAD over the whole file → speech spans (ms).
        vr = self._vad.generate(input=wav)
        spans = (vr[0].get("value") if isinstance(vr, list) else vr.get("value")) or []

        # 2) Group spans into silence-aligned chunks of ~chunk_target_s.
        chunks = _plan_chunks(spans, total_s, self._chunk_target_s)

        # 3) Transcribe each chunk on its own, releasing GPU memory between chunks.
        segments: list[Segment] = []
        for i, (cs, ce) in enumerate(chunks):
            a = int(round(cs * _SAMPLE_RATE))
            b = int(round(ce * _SAMPLE_RATE))
            chunk = wav[a:b]
            result = self._model.generate(input=chunk, batch_size_s=300)
            chunk_segs = _build_segments(result, offset_s=cs)
            segments.extend(chunk_segs)
            tail = chunk_segs[-1].end_s if chunk_segs else cs
            print(
                f"    ASR chunk {i + 1}/{len(chunks)} "
                f"[{cs:.0f}-{ce:.0f}s]: {len(chunk_segs)} segs, tail end {tail:.1f}s"
            )
            del result, chunk, chunk_segs
            gc.collect()
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
            if self._cooldown_s > 0:
                time.sleep(self._cooldown_s)

        elapsed = time.monotonic() - t0
        end_s = segments[-1].end_s if segments else 0.0
        print(
            f"    ASR done: {len(segments)} segments in {elapsed:.1f}s "
            f"(last end {end_s:.1f}s / audio {total_s:.1f}s, {len(chunks)} chunks)"
        )
        return Transcript(
            segments=tuple(segments),
            source_file=audio.path,
            engine="funasr-local",
            language="zh",
            duration_s=end_s,
        )


def _plan_chunks(spans, total_s: float, target_s: float) -> list[tuple[float, float]]:
    """Group VAD speech spans into silence-aligned chunks (seconds).

    ``spans`` is FunASR's VAD output: ``[[start_ms, end_ms], ...]`` ascending.
    A chunk runs from the first span's start to the span end at which the chunk
    has reached ``target_s``; the next chunk starts at the next span. Because
    every boundary sits in the silence *between* spans, no speech — and so no
    sentence — is ever split across chunks.
    """
    if not spans:
        return [(0.0, total_s)]
    target_ms = target_s * 1000.0
    chunks: list[tuple[float, float]] = []
    block_start = float(spans[0][0])
    prev_end = float(spans[0][1])
    for s, e in spans[1:]:
        if (prev_end - block_start) >= target_ms:
            chunks.append((block_start / 1000.0, prev_end / 1000.0))
            block_start = float(s)
        prev_end = float(e)
    chunks.append((block_start / 1000.0, prev_end / 1000.0))
    return chunks


def _build_segments(result, offset_s: float = 0.0) -> list[Segment]:
    """Parse FunASR AutoModel output into garden-core Segment list.

    ``offset_s`` is added to every timestamp so a chunk's chunk-relative ms
    timestamps become absolute on the source timeline.
    """
    if not result:
        return []
    sentences = result[0].get("sentence_info", []) if isinstance(result, list) else result.get("sentence_info", [])
    segs = []
    for s in sentences:
        if not isinstance(s, dict) or not s.get("text"):
            continue
        segs.append(Segment(
            text=str(s["text"]).strip(),
            start_s=offset_s + float(s.get("start", 0)) / 1000.0,
            end_s=offset_s + float(s.get("end", 0)) / 1000.0,
            speaker=str(s.get("spk", -1)) if s.get("spk", -1) >= 0 else None,
        ))
    return segs

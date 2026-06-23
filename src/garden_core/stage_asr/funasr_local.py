"""In-process FunASR backend — the standard single-machine ASR engine.

Loads Paraformer-large + VAD + Punc + SPK directly on the local GPU via
``funasr.AutoModel`` (no MCP server, no HTTP transport). This is the
production backend for Windows-native single-machine batch processing:
zero network overhead, RTF ~0.03 on CUDA.

Models are pulled from the shared modelscope cache; ``funasr`` is imported
lazily so importing this module stays cheap and side-effect free.
"""

from __future__ import annotations

import time

from garden_core.stage_asr import AudioRef, Transcriber
from garden_core.types import Segment, Transcript

__all__ = ["FunASRLocal"]


class FunASRLocal(Transcriber):
    """Transcribe using FunASR's AutoModel directly (no MCP server)."""

    def __init__(self, device: str = "cuda", chunk_s: float = 30.0):
        self._model = None
        self._device = device
        self._chunk_s = chunk_s

    @property
    def name(self) -> str:
        return "funasr-local"

    def _load_model(self):
        if self._model is not None:
            return
        from funasr import AutoModel
        self._model = AutoModel(
            model="iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
            spk_model="iic/speech_campplus_sv_zh-cn_16k-common",
            device=self._device,
            batch_size_s=300,
        )

    def transcribe(self, audio: AudioRef, hotwords: tuple[str, ...] = ()) -> Transcript:
        self._load_model()
        t0 = time.monotonic()
        result = self._model.generate(
            input=audio.path,
            batch_size_s=int(self._chunk_s),
        )
        elapsed = time.monotonic() - t0
        segments = _build_segments(result)
        print(f"    ASR done: {len(segments)} segments in {elapsed:.1f}s")
        return Transcript(
            segments=tuple(segments),
            source_file=audio.path,
            engine="funasr-local",
            language="zh",
            duration_s=segments[-1].end_s if segments else 0.0,
        )


def _build_segments(result) -> list[Segment]:
    """Parse FunASR AutoModel output into garden-core Segment list."""
    if not result:
        return []
    sentences = result[0].get("sentence_info", []) if isinstance(result, list) else result.get("sentence_info", [])
    segs = []
    for s in sentences:
        if not isinstance(s, dict) or not s.get("text"):
            continue
        segs.append(Segment(
            text=str(s["text"]).strip(),
            start_s=float(s.get("start", 0)) / 1000.0,
            end_s=float(s.get("end", 0)) / 1000.0,
            speaker=str(s.get("spk", -1)) if s.get("spk", -1) >= 0 else None,
        ))
    return segs

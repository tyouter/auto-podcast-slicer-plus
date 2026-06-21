"""MMS forced alignment backend (torchaudio wav2vec2 CTC).

Rewritten from legacy forced_aligner.py. Differences:
  * Implements the ``stage_align.Aligner`` interface → returns typed
    ``Segment`` with ``words`` filled (typed ``Word`` tuples), not a raw dict.
  * Model + dictionary loaded ONCE in ``__init__`` and reused (WhisperX
    discipline) — the legacy code did this too; we keep it.
  * Timestamps stay in seconds throughout (no ms).
  * Graceful degradation: audio too short for the text → returns the segment
    unchanged (no words) instead of crashing, so the pipeline continues.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from garden_core.stage_align import Aligner
from garden_core.types import Segment, Word

log = logging.getLogger(__name__)

__all__ = ["MMSAligner", "AlignmentError"]


class AlignmentError(RuntimeError):
    pass


class MMSAligner(Aligner):
    """Character-level forced alignment for Chinese via MMS_FA + uroman.

    Stateful: loads the CTC model and token dictionary once in __init__ and
    reuses across all ``align_segment`` calls.
    """

    def __init__(
        self, model_name: str = "MMS_FA", language: str = "zho", device: str = "cuda",
    ) -> None:
        try:
            import torch  # noqa: F401
            import torchaudio
        except ImportError as e:  # pragma: no cover
            raise AlignmentError(
                "torch/torchaudio required for MMSAligner") from e

        self.torch = __import__("torch")
        self._torchaudio = torchaudio
        self.device = self.torch.device(
            device if self.torch.cuda.is_available() else "cpu")

        bundle = getattr(torchaudio.pipelines, model_name, None)
        if bundle is None:
            raise AlignmentError(f"unknown torchaudio pipeline: {model_name}")
        self.bundle = bundle
        self.sample_rate = bundle.sample_rate

        log.info("loading alignment model %s on %s", model_name, self.device)
        self.model = bundle.get_model().to(self.device)
        self.model.eval()
        self._token_to_id = self._load_dictionary()
        self._uroman = None  # lazy

    @property
    def name(self) -> str:
        return "mms_fa"

    def _load_dictionary(self) -> dict:
        if hasattr(self.bundle, "get_dict"):
            d = self.bundle.get_dict()
            if d:
                return d
        raise AlignmentError("cannot load token dictionary (need torchaudio>=2.1)")

    def _romanize(self, text: str) -> str:
        if not any("一" <= ch <= "鿿" for ch in text):
            return text
        if self._uroman is None:
            import uroman as _uroman  # noqa
            self._uroman = _uroman.Uroman()
        return self._uroman.romanize_string(text)

    def _tokenize(self, text: str):
        text = self._romanize(text)
        chars, ids = [], []
        for ch in text:
            if ch.isspace():
                continue
            if ch in self._token_to_id:
                chars.append(ch)
                ids.append(self._token_to_id[ch])
        if not ids:
            raise AlignmentError(f"no valid tokens for text: {text!r}")
        return chars, self.torch.tensor(ids, dtype=self.torch.long, device=self.device)

    def align_segment(self, audio_path: str, segment: Segment) -> Segment:
        """Return a new Segment with ``words`` populated (per-character timing).

        Falls back to returning the segment unchanged if alignment can't be
        done (audio missing, too short, etc.) — never raises to the caller.
        """
        if not audio_path or not Path(audio_path).exists():
            log.debug("align_segment: no audio, returning segment as-is")
            return segment
        try:
            words = self._do_align(
                audio_path, segment.text, segment.start_s, segment.end_s,
            )
        except AlignmentError as e:
            log.warning("alignment failed for %r: %s", segment.text[:30], e)
            return segment
        if not words:
            return segment
        from dataclasses import replace as _replace
        return _replace(segment, words=tuple(words))

    def _do_align(
        self, audio_path: str, text: str, start_s: float, end_s: float,
        padding_s: float = 0.5,
    ) -> list[Word]:
        torchaudio = self._torchaudio
        torch = self.torch
        sr = self.sample_rate
        pad_frames = int(padding_s * sr)
        frame_offset = max(0, int(start_s * sr) - pad_frames)
        end_frame = int(end_s * sr) + pad_frames
        num_frames = end_frame - frame_offset
        waveform, actual_sr = torchaudio.load(
            str(audio_path), frame_offset=frame_offset, num_frames=num_frames,
        )
        if actual_sr != sr:
            waveform = torchaudio.functional.resample(waveform, actual_sr, sr)
        if waveform.dim() > 1:
            waveform = waveform[:1]
        waveform = waveform.to(self.device)
        offset_s = start_s

        chars, token_ids = self._tokenize(text)
        with torch.no_grad():
            emissions, _ = self.model(waveform)
        emissions = torch.log_softmax(emissions, dim=-1)

        # audio too short for the text → skip gracefully
        if len(token_ids) > emissions.shape[1]:
            log.warning("skip align: %d tokens > %d frames (%.30s…)",
                        len(token_ids), emissions.shape[1], text)
            return []

        alignment, _ = torchaudio.functional.forced_align(
            emissions, token_ids.unsqueeze(0),
            input_lengths=torch.tensor([emissions.shape[1]], device=self.device),
            target_lengths=torch.tensor([len(token_ids)], device=self.device),
        )
        n_frames = emissions.shape[1]
        audio_dur = waveform.shape[1] / sr
        frame_dur = audio_dur / n_frames
        return _frames_to_words(
            alignment[0], token_ids, chars, frame_dur, offset_s,
        )


def _frames_to_words(
    alignment, target_ids, chars: list[str], frame_dur_s: float, offset_s: float,
) -> list[Word]:
    """Map CTC alignment frames → per-character Word timestamps (seconds).

    Handles CTC blanks and repeated tokens (same logic as legacy
    ``_extract_timestamps``): blank separates; same token after blank = new
    occurrence; same token without blank = CTC repeat (extend current).
    """
    n_frames = alignment.shape[0]
    target_pos = 0
    prev_token = -1
    was_blank = True
    frame_ranges: dict[int, list[int]] = {}

    for f in range(n_frames):
        tok = alignment[f].item()
        if tok == 0:
            was_blank = True
            continue
        is_new = (tok != prev_token) or was_blank
        if is_new:
            if target_pos < len(target_ids) and tok == target_ids[target_pos].item():
                frame_ranges[target_pos] = [f, f]
                target_pos += 1
        else:
            pos = target_pos - 1
            if pos >= 0 and pos in frame_ranges:
                frame_ranges[pos][1] = f
        prev_token = tok
        was_blank = False

    words: list[Word] = []
    for pos in range(len(chars)):
        if pos not in frame_ranges:
            continue
        f0, f1 = frame_ranges[pos]
        words.append(Word(
            text=chars[pos],
            start_s=offset_s + f0 * frame_dur_s,
            end_s=offset_s + (f1 + 1) * frame_dur_s,
        ))
    return words

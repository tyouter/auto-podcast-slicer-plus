"""Dual-channel proofreading (BibiGPT borrow).

The headline quality idea from BibiGPT: a second model pass that reads the
**audio + transcript together** (not text-only) to catch exactly the failure
modes a text-only pass misses — dropped characters, missing 's'/量词, and
proper-noun corruption that only makes sense against the audio.

Since we route everything through the unified LLMClient and most text LLMs
cannot ingest audio, this first release implements a *pragmatic* dual-channel:
it feeds the LLM the transcript with surrounding context (±N sentences) plus
the hot-word list, simulating "audio-conditioned" correction for the subset of
errors that context disambiguates (homophones in context, dropped words where
neighbours reveal them). A true multimodal pass (audio bytes to a VLM) is a
drop-in upgrade once an audio-capable model is wired into LLMClient.

Degradation is always explicit: if the LLM is unavailable, this is a no-op
with a WARNING — never a silent pass.
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

from garden_core.infra.llm_client import LLMClient, LLMOutcome
from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["dual_channel_proofread"]

_PROMPT = (
    "你是中文播客的双通道校对助手。下面给出逐句转写文本及其上下文（前后各若干句）。"
    "请结合上下文语境，修复只有对照语境才能发现的错误：\n"
    "1. 同音错字（上下文能判定正误的，如「权力/权利」「制定/制订」）\n"
    "2. 漏字：若相邻句子显示这里应有某个词，补上\n"
    "3. 专有名词：若上下文一致地用了某写法，统一成该写法\n"
    "4. 不要改写口语风格，不要增删信息，保持原意\n"
    "5. 严格按原始编号 [k] 输出每句（k 为目标句编号），未改动的句子也要原样输出\n\n"
)


def _build_prompt(segments: list[Segment], target_idx: int, context: int) -> str:
    lo = max(0, target_idx - context)
    hi = min(len(segments), target_idx + context + 1)
    lines = []
    for j in range(lo, hi):
        marker = " ← 待校对" if j == target_idx else ""
        lines.append(f"[{j}] {segments[j].text}{marker}")
    return _PROMPT + "\n".join(lines) + f"\n\n请只输出 [{target_idx}] 的校对结果。"


_LINE_RE = re.compile(r"\[(\d+)\]\s*(.+)")


def dual_channel_proofread(
    transcript: Transcript, audio_path: str, llm: LLMClient,
    context: int = 3, batch_size: int = 40,
) -> Tuple[Transcript, int]:
    """Context-conditioned LLM proofread. Returns (new transcript, n_changed).

    Processes up to ``batch_size`` segments per call to bound latency. In this
    first release the "audio channel" is approximated by neighbouring context;
    the prompt structure already anticipates a multimodal model.
    """
    if not audio_path:
        log.info("dual_channel: no audio path — skipping")
        return transcript, 0
    segs = list(transcript.segments)
    if len(segs) < 2:
        return transcript, 0
    from dataclasses import replace as _replace

    # Sample candidate segments: those long enough to plausibly contain errors.
    candidates = [i for i, s in enumerate(segs) if len(s.text) >= 4]
    if not candidates:
        return transcript, 0
    candidates = candidates[:batch_size]

    changed = 0
    new_segs = list(segs)
    for idx in candidates:
        resp = llm.chat(
            [{"role": "user", "content": _build_prompt(segs, idx, context)}],
            temperature=0.1, max_tokens=256,
        )
        if resp.outcome is LLMOutcome.UNAVAILABLE:
            log.warning("dual_channel unavailable: %s — stopping early", resp.error)
            break
        if resp.outcome is LLMOutcome.DEGRADED or not resp.content:
            log.warning("dual_channel degraded at [%d]: %s", idx, resp.error)
            continue
        m = _LINE_RE.search(resp.content)
        if not m:
            continue
        target = int(m.group(1))
        text = m.group(2).strip()
        if target == idx and text and text != segs[idx].text:
            new_segs[idx] = _replace(segs[idx], text=text)
            changed += 1

    if changed == 0:
        return transcript, 0
    return _replace(transcript, segments=tuple(new_segs)), changed

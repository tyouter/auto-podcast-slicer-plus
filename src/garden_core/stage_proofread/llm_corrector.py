"""LLM corrector: DeepSeek-based semantic ASR correction.

Rewritten from legacy text_corrector.py. Goes through the unified
``LLMClient`` (fixes bug #7: scattered calls + silent error swallowing). When
the LLM is unavailable or degraded, this layer is a no-op with a visible
WARNING — it never produces false corrections or hides failures.

Runs on the WHOLE transcript (not per-chunk), fixing legacy bug #6 where
polish ran per-chunk without cross-chunk context.
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

from garden_core.infra.llm_client import LLMClient, LLMOutcome
from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["llm_correct_segments"]

_PROMPT = (
    "你是中文播客 ASR 纠错助手。下面是带编号的逐句转写文本，可能含有同音错字、"
    "漏字、口语重复。请逐句纠正：\n"
    "1. 修复明显的同音/近音错字（如「著名」误成「着名」）\n"
    "2. 合并口吃和重复（「我们我们」→「我们」），但保留自然的口语停顿\n"
    "3. 保持原意与口语风格，不要改写为书面语\n"
    "4. 不要改动专有名词、人名、地名\n"
    "5. 每行输出一句，严格按原始编号 [0] [1] … 顺序\n\n"
)


def _build_prompt(segments: list[Segment]) -> str:
    lines = []
    for i, s in enumerate(segments):
        spk = f"SPK{s.speaker}: " if s.speaker else ""
        lines.append(f"[{i}] {spk}{s.text}")
    return _PROMPT + "\n".join(lines)


_LINE_RE = re.compile(r"\[(\d+)\]\s*(?:SPK\S+:\s*)?(.+)")


def _parse_response(raw: str, n: int) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in (raw or "").splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            idx = int(m.group(1))
            if 0 <= idx < n:
                txt = m.group(2).strip()
                if txt:
                    out[idx] = txt
    return out


def llm_correct_segments(
    transcript: Transcript, llm: LLMClient, temperature: float = 0.1,
) -> Tuple[Transcript, int]:
    """Whole-transcript LLM correction. Returns (new transcript, n_changed)."""
    segs = list(transcript.segments)
    if len(segs) < 2:
        return transcript, 0
    from dataclasses import replace as _replace

    resp = llm.chat(
        [{"role": "user", "content": _build_prompt(segs)}],
        temperature=temperature, max_tokens=8192,
    )
    if resp.outcome is LLMOutcome.UNAVAILABLE:
        log.warning("LLM corrector skipped: unavailable (%s)", resp.error)
        return transcript, 0
    if resp.outcome is LLMOutcome.DEGRADED or not resp.content:
        log.warning("LLM corrector degraded: %s", resp.error)
        return transcript, 0

    corrected = _parse_response(resp.content, len(segs))
    if not corrected:
        log.warning("LLM corrector returned no parseable lines")
        return transcript, 0

    new_segs: list[Segment] = []
    changed = 0
    for i, seg in enumerate(segs):
        if i in corrected and corrected[i] != seg.text:
            new_segs.append(_replace(seg, text=corrected[i]))
            changed += 1
        else:
            new_segs.append(seg)
    return _replace(transcript, segments=tuple(new_segs)), changed

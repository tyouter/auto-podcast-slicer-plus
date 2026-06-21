"""FunASR MCP backend using FastMCP Client library (robust transport).

Rewritten from the minimal _MCP urllib client. Uses FastMCP's built-in
Client + SSETransport which handles the SSE protocol, session management,
and async complexity properly. This replaces the streamable-http / 307 /
SSE parsing issues of the hand-rolled client.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from garden_core.infra.media_probe import probe_media
from garden_core.infra.time_util import ms_to_s
from garden_core.stage_asr import AudioRef, Transcriber
from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["FunASRMCPBackend", "FunASRMCPError"]


class FunASRMCPError(RuntimeError):
    pass


class FunASRMCPBackend(Transcriber):
    """FunASR via MCP SSE transport using FastMCP Client. Stateful — reuse one.

    Requires ``fastmcp`` package (pip install fastmcp).
    """

    def __init__(
        self,
        mcp_url: str = "http://localhost:8000/sse",
        chunk_duration_s: int = 300,
        poll_interval_s: float = 5.0,
        max_polls: int = 60,
    ) -> None:
        self.mcp_url = mcp_url
        self.chunk_duration_s = chunk_duration_s
        self.poll_interval_s = poll_interval_s
        self.max_polls = max_polls

    @property
    def name(self) -> str:
        return "funasr-mcp"

    def transcribe(self, audio: AudioRef, hotwords: tuple[str, ...] = ()) -> Transcript:
        import anyio
        return anyio.run(self._transcribe_async, audio, hotwords)

    async def _transcribe_async(self, audio: AudioRef, hotwords: tuple[str, ...]) -> Transcript:
        from fastmcp import Client
        from fastmcp.client.transports import SSETransport

        audio_path = str(Path(audio.path).resolve())
        out_dir = Path(audio_path).parent
        chunks_dir = out_dir / "chunks"
        chunks = _split_audio(audio_path, self.chunk_duration_s, chunks_dir)
        log.info("FunASR MCP: %d chunks of %ds", len(chunks), self.chunk_duration_s)

        async with Client(SSETransport(self.mcp_url)) as client:
            chunk_results: list[list[dict]] = []
            for i, chunk_path in enumerate(chunks):
                win_path = _to_fwd_slash_path(str(chunk_path))
                segs = await _submit_and_poll(
                    client, win_path, self.poll_interval_s, self.max_polls,
                    label=f"chunk {i + 1}",
                )
                if segs is None:
                    log.warning("chunk %d failed; retrying once", i + 1)
                    segs = await _submit_and_poll(
                        client, win_path, self.poll_interval_s, self.max_polls,
                        label=f"chunk {i + 1} retry",
                    )
                chunk_results.append(segs or [])

        segments = _merge_chunks(chunk_results, audio_path, self.chunk_duration_s, audio.duration_s)
        return Transcript(
            segments=tuple(segments),
            source_file=audio_path,
            engine=self.name,
            language="zh",
            duration_s=audio.duration_s or (segments[-1].end_s if segments else 0.0),
        )


# --------------------------------------------------------------------------- #
# Helpers (shared with original funasr_backend)
# --------------------------------------------------------------------------- #
def _to_fwd_slash_path(p: str) -> str:
    """Normalize to forward-slash path (JSON-safe)."""
    p = p.replace("\\", "/")
    if p.startswith("/d/"):
        p = "D:/" + p[3:]
    elif p.startswith("/mnt/"):
        p = p[5:]
    return p


def _split_audio(audio_path: str, chunk_s: int, chunks_dir: Path) -> list[Path]:
    import math
    info = probe_media(audio_path)
    total = info.duration_s if info else 0.0
    if total <= 0:
        raise FunASRMCPError(f"cannot determine duration of {audio_path}")
    n = max(1, math.ceil(total / chunk_s))
    chunks_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for i in range(n):
        p = chunks_dir / f"chunk_{i:04d}.wav"
        if p.exists() and p.stat().st_size > 0:
            out.append(p)
            continue
        start = i * chunk_s
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(chunk_s),
               "-i", audio_path, "-ar", "16000", "-ac", "1", str(p)]
        subprocess.run(cmd, capture_output=True, check=True)
        out.append(p)
    return out


async def _submit_and_poll(
    client, audio_path: str, poll_s: float, max_polls: int, label: str = "",
) -> Optional[list[dict]]:
    try:
        result = await client.call_tool(
            "start_speech_transcription",
            {"audio_path": audio_path},
        )
        payload = _extract_result(result)
        task_id = payload.get("task_id") or payload.get("id") if isinstance(payload, dict) else (
            payload.strip() if isinstance(payload, str) else None)
        if not task_id:
            log.warning("no task_id for %s", label)
            return None
        task_id = str(task_id)
        for _ in range(max_polls):
            time.sleep(poll_s)
            result = await client.call_tool("get_transcription_result", {"task_id": task_id})
            rp = _extract_result(result)
            if isinstance(rp, dict) and rp.get("status") in ("failed", "error"):
                log.warning("task failed for %s", label)
                return None
            segs = _parse_sentences(rp)
            if segs:
                return segs
        log.warning("timeout after %d polls for %s", max_polls, label)
        return None
    except Exception as e:
        log.error("error for %s: %s", label, e)
        return None


def _extract_result(result):
    """Pull structured result from MCP tool call response."""
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    import json
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, TypeError):
                        return item["text"]
        return result
    return result


def _parse_sentences(payload) -> list[dict]:
    import json
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(payload, dict):
        rl = payload.get("result")
        if isinstance(rl, list) and rl:
            payload = rl[0]
    if not isinstance(payload, dict):
        return []
    sentences = payload.get("sentence_info", []) or []
    out = []
    for s in sentences:
        if isinstance(s, dict) and s.get("text"):
            out.append({
                "start_ms": int(s.get("start", 0)),
                "end_ms": int(s.get("end", 0)),
                "text": str(s["text"]).strip(),
                "spk": int(s.get("spk", -1)),
            })
    return out


def _merge_chunks(chunk_results, audio_path, chunk_s, known_duration_s) -> list[Segment]:
    out: list[Segment] = []
    for idx, sentences in enumerate(chunk_results):
        offset_s = idx * chunk_s
        chunk_max_end = 0.0
        for s in sentences:
            start_s = ms_to_s(s.get("start_ms", s.get("start", 0)))
            end_s = ms_to_s(s.get("end_ms", s.get("end", 0)))
            chunk_max_end = max(chunk_max_end, end_s)
            text = str(s.get("text", "")).strip()
            if not text:
                continue
            spk = s.get("spk")
            spk = None if spk is None or spk < 0 else str(spk)
            out.append(Segment(
                text=text, start_s=start_s + offset_s, end_s=end_s + offset_s,
                speaker=spk, confidence=float(s.get("confidence", 1.0)),
            ))
        if chunk_max_end > chunk_s * 1.5:
            log.error(
                "chunk %d: max end_s=%.1fs >> chunk_duration=%ds — FunASR may be "
                "returning ABSOLUTE timestamps; subtitle timeline will be wrong!",
                idx, chunk_max_end, chunk_s,
            )
    return out

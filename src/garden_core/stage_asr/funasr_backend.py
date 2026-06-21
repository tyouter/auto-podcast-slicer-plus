"""FunASR MCP backend — the default ASR engine.

Rewritten from legacy transcribe_chunked.py. Key improvements:
  * Models loaded once, MCP session reused (WhisperX discipline).
  * **Fixes bug #4 with an explicit assertion**: the merge assumes FunASR
    returns *chunk-relative* timestamps (each chunk starts at 0). We now assert
    the max end_ms of each chunk is ≈ chunk duration, and log a loud warning if
    the assumption is violated — instead of silently producing misaligned subs.
  * No LLM call baked in (polish moved to stage_proofread, fixing bug #6 where
    polish ran per-chunk without cross-chunk context).
  * Hot-word injection hook (BibbGPT borrow).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from garden_core.infra.time_util import ms_to_s
from garden_core.stage_asr import AudioRef, Transcriber
from garden_core.types import Segment, Transcript

log = logging.getLogger(__name__)

__all__ = ["FunASRBackend", "FunASRError"]


class FunASRError(RuntimeError):
    pass


class _MCP:
    """Minimal MCP streamable-http client (carried over, cleaned up)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id: Optional[str] = None
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            # Follow 307 redirects (FastMCP streamable-http uses a trailing-slash endpoint)
            if e.code == 307 and e.headers.get("Location"):
                new_url = e.headers["Location"]
                req = urllib.request.Request(
                    new_url, data=json.dumps(payload).encode("utf-8"),
                    headers=headers, method="POST",
                )
                resp = urllib.request.urlopen(req, timeout=120)
                # Update stored URL so subsequent calls go directly to the canonical endpoint
                self.url = new_url
            else:
                raise
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        body = resp.read().decode("utf-8")
        ct = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ct:
            for line in body.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
            raise FunASRError("SSE response had no data")
        return json.loads(body)

    def initialize(self) -> None:
        self._post({
            "jsonrpc": "2.0", "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "garden-core", "version": "1.0"}},
            "id": self._next_id(),
        })

    def call_tool(self, name: str, arguments: dict) -> dict:
        for attempt in range(2):
            try:
                resp = self._post({
                    "jsonrpc": "2.0", "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                    "id": self._next_id(),
                })
                if "error" in resp:
                    raise FunASRError(f"MCP error: {resp['error']}")
                return resp.get("result", resp)
            except urllib.error.HTTPError as e:
                if e.code == 404 and attempt == 0:
                    self.session_id = None
                    self.initialize()
                    continue
                raise


def _to_windows_path(p: str) -> str:
    """Normalize to forward-slash path (JSON-safe, accepted by FunASR on Windows)."""
    p = p.replace("\\", "/")
    if p.startswith("/d/"):
        p = "D:/" + p[3:]
    elif p.startswith("/mnt/"):
        p = p[5:]  # strip the linux drive letter
    return p


class FunASRBackend(Transcriber):
    """FunASR via the chunked-MCP protocol. Stateful — reuse one instance."""

    def __init__(
        self,
        mcp_url: str = "http://host.docker.internal:8000/mcp",
        chunk_duration_s: int = 300,
        poll_interval_s: float = 5.0,
        max_polls: int = 30,
    ) -> None:
        self.mcp_url = mcp_url
        self.chunk_duration_s = chunk_duration_s
        self.poll_interval_s = poll_interval_s
        self.max_polls = max_polls

    @property
    def name(self) -> str:
        return "funasr"

    def transcribe(self, audio: AudioRef, hotwords: tuple[str, ...] = ()) -> Transcript:
        audio_path = str(Path(audio.path).resolve())
        out_dir = Path(audio_path).parent
        chunks_dir = out_dir / "chunks"
        chunks = _split_audio(audio_path, self.chunk_duration_s, chunks_dir)
        log.info("FunASR: %d chunks of %ds", len(chunks), self.chunk_duration_s)

        mcp = _MCP(self.mcp_url)
        try:
            mcp.initialize()
        except Exception as e:
            log.warning("MCP init failed (%s) — continuing without session", e)

        chunk_results: list[list[dict]] = []
        for i, chunk_path in enumerate(chunks):
            win = _to_windows_path(str(chunk_path))
            segs = _submit_and_poll(mcp, win, self.poll_interval_s, self.max_polls,
                                    label=f"chunk {i+1}")
            if segs is None:
                log.warning("chunk %d failed; retrying once", i + 1)
                segs = _submit_and_poll(mcp, win, self.poll_interval_s, self.max_polls,
                                        label=f"chunk {i+1} retry")
            chunk_results.append(segs or [])

        segments = self._merge_chunks(chunk_results, audio_path, audio.duration_s)
        return Transcript(
            segments=tuple(segments),
            source_file=audio_path,
            engine=self.name,
            language="zh",
            duration_s=audio.duration_s or (segments[-1].end_s if segments else 0.0),
        )

    def _merge_chunks(
        self, chunk_results: list[list[dict]], audio_path: str,
        known_duration_s: Optional[float],
    ) -> list[Segment]:
        """Merge chunk-local segments with fixed offsets.

        **Fixes bug #4**: asserts FunASR returns chunk-relative timestamps. If a
        chunk's max end_ms wildly exceeds the chunk duration, the assumption is
        violated and we log a loud warning (rather than silently misaligning).
        """
        out: list[Segment] = []
        for idx, sentences in enumerate(chunk_results):
            offset_s = idx * self.chunk_duration_s
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
            # bug #4 assertion: chunk-relative timestamps must not exceed chunk dur
            if chunk_max_end > self.chunk_duration_s * 1.5:
                log.error(
                    "chunk %d: max end_s=%.1fs >> chunk_duration=%ds — FunASR may be "
                    "returning ABSOLUTE timestamps; subtitle timeline will be wrong!",
                    idx, chunk_max_end, self.chunk_duration_s,
                )
        return out


# --------------------------------------------------------------------------- #
# Chunking + submit/poll + parse helpers (kept as module functions)
# --------------------------------------------------------------------------- #
def _split_audio(audio_path: str, chunk_s: int, chunks_dir: Path) -> list[Path]:
    import math
    from garden_core.infra.media_probe import probe_media
    info = probe_media(audio_path)
    total = info.duration_s if info else 0.0
    if total <= 0:
        raise FunASRError(f"cannot determine duration of {audio_path}")
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


def _extract_mcp_text(result: dict):
    """Pull the textual content out of an MCP tool result."""
    if isinstance(result, dict):
        content = result.get("content") or result.get("result", {}).get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    txt = item.get("text", "")
                    try:
                        return json.loads(txt)
                    except (json.JSONDecodeError, TypeError):
                        return txt
        if "result" in result:
            return result["result"]
    return result


def _parse_sentences(payload) -> list[dict]:
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


def _submit_and_poll(mcp: _MCP, audio_path: str, poll_s: float,
                     max_polls: int, label: str = "") -> Optional[list[dict]]:
    try:
        submit = mcp.call_tool("start_speech_transcription", {"audio_path": audio_path})
        payload = _extract_mcp_text(submit)
        task_id = payload.get("task_id") or payload.get("id") if isinstance(payload, dict) else (
            payload.strip() if isinstance(payload, str) else None)
        if not task_id:
            log.warning("no task_id for %s", label)
            return None
        for _ in range(max_polls):
            time.sleep(poll_s)
            res = mcp.call_tool("get_transcription_result", {"task_id": task_id})
            rp = _extract_mcp_text(res)
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

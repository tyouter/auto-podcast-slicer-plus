"""Core immutable data types for the garden-core pipeline.

Design invariants (enforced everywhere):
  * All time values are **seconds (float)**. Milliseconds only exist at the I/O
    boundary (io_/source.py, io_/sink.py) and are converted there.
  * Every dataclass is ``frozen=True`` — stage outputs are immutable. To evolve
    a value through a stage, build a new object (``dataclasses.replace``).
  * ``Cue`` is the *single* subtitle unit that flows through
    stage_segment → stage_cut → stage_render. There is no second "entry" shape.
    (Fixes the legacy 3-shape / ms-vs-s mess.)
  * ``Segment.words`` makes word-level timestamps first-class in the data flow,
    so the aligner's output is never silently dropped downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

__all__ = [
    "Word",
    "Segment",
    "Transcript",
    "Cue",
    "CutPoint",
    "ClipPlan",
    "StyleDef",
    "BgStyle",
    "RenderResult",
    "replace",
]


# --------------------------------------------------------------------------- #
# Stage 1–3: transcript-level types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Word:
    """A single word/character with aligned timing."""

    text: str
    start_s: float
    end_s: float
    confidence: float = 1.0

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Segment:
    """An ASR segment. The aligner fills ``words`` with word-level timing."""

    text: str
    start_s: float
    end_s: float
    speaker: Optional[str] = None
    words: tuple[Word, ...] = ()
    confidence: float = 1.0

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class Transcript:
    """Stages 1–3 product: the full timeline, not yet sliced into clips."""

    segments: tuple[Segment, ...]
    source_file: str
    engine: str
    language: str = "zh"
    duration_s: float = 0.0
    corrections_applied: tuple[str, ...] = ()

    @property
    def start_s(self) -> float:
        return self.segments[0].start_s if self.segments else 0.0

    @property
    def end_s(self) -> float:
        return self.segments[-1].end_s if self.segments else 0.0


# --------------------------------------------------------------------------- #
# Stages 4–7: subtitle / clip / render types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Cue:
    """The single subtitle unit flowing through segment → cut → render.

    Fixing the legacy code which had three different "entry" shapes
    (SubtitleEntry / clip_entries_raw dict / processed_entries dict) plus a
    ms-vs-s split. Here there is one type and one time unit (seconds).
    """

    index: int
    text: str
    start_s: float
    end_s: float
    text_en: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class CutPoint:
    """A requested clip boundary on the source timeline."""

    clip_id: str
    start_s: float
    end_s: float
    style_name: str = "default"
    title: str = ""


@dataclass(frozen=True)
class ClipPlan:
    """A clip as a parametric object (source-ref + in/out + cues + style).

    Inspired by LTX's "clip = (source-ref + params)" notion — we never render
    bytes until stage 7, we carry references through the pipeline.
    """

    clip_id: str
    source_ref: str
    start_s: float
    end_s: float
    cues: tuple[Cue, ...]
    style_name: str = "default"
    title: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


# --------------------------------------------------------------------------- #
# Style types — single style object (fixes legacy dual-style-system bug #3)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BgStyle:
    """Optional background box: frosted glass or rounded solid.

    ``corner_radius`` and ``padding`` are stored as RATIOS of font_size; the
    renderer scales them to px via ``StyleDef.font_size_px(video_height)``.
    """

    kind: str  # "frosted_glass" | "rounded"
    corner_radius: float  # ratio of font_size
    padding: float        # ratio of font_size
    alpha: int  # 0–255 box background alpha


@dataclass(frozen=True)
class StyleDef:
    """Single style object. Resolves from one path only (fixes bug #3)."""

    name: str
    # font_family is REQUIRED config, exactly like xr below: there is NO code
    # default. It stays None through mold expansion / the structural fallback,
    # and the style resolver raises ConfigError if a resolved style still has it
    # None (so the font can never silently fall back to a built-in default).
    font_family: Optional[str]
    # xr: font size / video height. REQUIRED — must be supplied by the style
    # config; there is NO code default. It stays None through mold expansion /
    # the structural fallback, and the style resolver raises ConfigError if a
    # resolved style still has it None (so xr can never silently fall back).
    font_size_ratio: Optional[float]
    primary_color: str  # &HAABBGGRR
    outline_color: str
    # outline_width & shadow_depth are RATIOS of font_size (resolution-independent);
    # the renderer scales them to px via font_size_px(video_height).
    outline_width: float
    shadow_color: str
    shadow_depth: float
    background: Optional[BgStyle] = None
    position: str = "bottom"  # "bottom" | "center"
    margins: tuple[float, float, float] = (0.08, 0.08, 0.06)  # L R V (ratios)
    bold: bool = False
    align: int = 2  # ASS numpad alignment (2 = bottom-center)

    def font_size_px(self, video_height: int) -> float:
        return self.font_size_ratio * video_height


# --------------------------------------------------------------------------- #
# Stage 7: render result
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RenderResult:
    """Stage 7 product: written artifacts."""

    clip_id: str
    horizontal_mp4: str
    vertical_mp4: str
    srt_path: str
    ass_path: str
    metadata: dict = field(default_factory=dict)

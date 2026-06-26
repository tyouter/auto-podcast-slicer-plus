"""Step API — the 6 public pipeline steps, re-exported in one place.

Each step is independently callable and persists its product via the
``save_*`` / ``load_*`` pairs in ``garden_core.io_`` (see step table in
ARCHITECTURE.md). Re-export only — no new functions, no renamed wrappers.

    from garden_core.steps import transcribe, align, proofread, segment, cut, render
"""

from garden_core.stage_asr import transcribe
from garden_core.stage_align import align
from garden_core.stage_proofread import proofread
from garden_core.stage_segment import segment
from garden_core.stage_cut import cut
from garden_core.stage_render import render

__all__ = ["transcribe", "align", "proofread", "segment", "cut", "render"]

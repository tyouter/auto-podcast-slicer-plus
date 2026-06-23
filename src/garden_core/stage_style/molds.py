"""Proportional style templates ("molds") + a YAML-driven resolver.

This is the SINGLE style resolution path (fixes legacy bug #3: two parallel
systems, SubtitleStyle + StyleDefinition, that drifted apart). Here one
``StyleResolver`` (``YamlStyleResolver`` or ``StaticResolver``) maps a
``style_name`` to one ``StyleDef``. Molds are ratio templates expanded against
a video height; YAML files can override any field.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace as _replace
from pathlib import Path
from typing import Optional

import yaml

from garden_core.config import load_yaml
from garden_core.stage_style import (
    DEFAULT_STYLE,
    StyleResolver,
    StaticResolver,
    require_xr,
    require_font_family,
)
from garden_core.types import BgStyle, StyleDef

log = logging.getLogger(__name__)

__all__ = ["StyleMold", "MOLDS", "mold_to_style", "YamlStyleResolver"]


@dataclass(frozen=True)
class StyleMold:
    """Ratios relative to font_size / video_height. Resolution-independent."""

    name: str
    # xr (font_size / video_height) is the subtitle master variable. It is a
    # REQUIRED config value with NO code default: molds carry None, and the
    # resolver fills it from the style YAML, raising if it is still missing.
    font_size_ratio: Optional[float] = None
    outline_ratio: float = 0.036          # outline_width / font_size
    shadow_ratio: float = 0.014           # shadow_depth / font_size
    padding_h_ratio: float = 0.15         # box horizontal pad / font_size
    padding_v_ratio: float = 0.08         # box vertical pad / font_size
    corner_radius_ratio: float = 0.0      # box corner r / font_size
    margin_v_ratio: float = 0.042         # margin_v / video_height
    bold: bool = False
    bg_kind: Optional[str] = None         # None | "frosted_glass" | "rounded"
    bg_alpha: int = 180
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    shadow_color: str = "&H96000000"
    position: str = "bottom"
    # font_family, like font_size_ratio (xr) above, is a REQUIRED config value
    # with NO code default: molds carry None, and the resolver fills it from the
    # style YAML, raising if it is still missing.
    font_family: Optional[str] = None


MOLDS: dict[str, StyleMold] = {
    "default": StyleMold(name="default"),
    "classic_outline": StyleMold(
        name="classic_outline", outline_ratio=0.036, shadow_ratio=0.014,
        padding_h_ratio=0.15, padding_v_ratio=0.08, bold=True,
    ),
    "frosted_glass": StyleMold(
        name="frosted_glass", outline_ratio=0.02, shadow_ratio=0.01,
        padding_h_ratio=0.20, padding_v_ratio=0.12, corner_radius_ratio=0.08,
        bg_kind="frosted_glass", bg_alpha=180,
    ),
    "minimal_clean": StyleMold(
        name="minimal_clean", outline_ratio=0.0, shadow_ratio=0.0,
        padding_h_ratio=0.10, padding_v_ratio=0.05, margin_v_ratio=0.040,
    ),
    "bold_impact": StyleMold(
        name="bold_impact", outline_ratio=0.05, shadow_ratio=0.02,
        padding_h_ratio=0.18, padding_v_ratio=0.10, margin_v_ratio=0.035, bold=True,
    ),
    "cinematic": StyleMold(
        name="cinematic", outline_ratio=0.025, shadow_ratio=0.02,
        padding_h_ratio=0.12, padding_v_ratio=0.06, margin_v_ratio=0.045,
    ),
    "broadcast": StyleMold(
        name="broadcast", outline_ratio=0.03, shadow_ratio=0.01,
        padding_h_ratio=0.22, padding_v_ratio=0.10, corner_radius_ratio=0.06,
        bg_kind="rounded", bg_alpha=160,
    ),
}


def mold_to_style(mold: StyleMold) -> StyleDef:
    """Expand a mold into a StyleDef. Font sizes resolve against video_height
    on demand (StyleDef.font_size_px)."""
    bg: Optional[BgStyle] = None
    if mold.bg_kind:
        # padding/corner stored as ratios; rendered units computed in ass_writer
        # from font_size — so we stash ratios as-is here (px values derived at
        # render time). For simplicity store padding as a ratio of font size
        # already scaled: ass_writer adds `pad` as flat px, so we encode the
        # ratio*~54 reference here (font_size at 1080 ≈ 54). A cleaner pass:
        bg = BgStyle(
            kind=mold.bg_kind,
            corner_radius=mold.corner_radius_ratio,  # ratio; scaled in ass_writer
            padding=mold.padding_h_ratio,            # ratio; scaled in ass_writer
            alpha=mold.bg_alpha,
        )
    return StyleDef(
        name=mold.name,
        font_family=mold.font_family,
        font_size_ratio=mold.font_size_ratio,
        primary_color=mold.primary_color,
        outline_color=mold.outline_color,
        # outline_width / shadow_depth are stored as RATIOS of font_size;
        # ass_writer scales them to px via font_size_px(video_height).
        outline_width=mold.outline_ratio,
        shadow_color=mold.shadow_color,
        shadow_depth=mold.shadow_ratio,
        background=bg,
        position=mold.position,
        bold=mold.bold,
    )


def _apply_overrides(base: StyleDef, overrides: dict) -> StyleDef:
    """Return a new StyleDef with valid field overrides from a YAML dict."""
    valid = {f.name for f in __import__("dataclasses").fields(StyleDef)}
    picked = {k: v for k, v in overrides.items() if k in valid}
    if "background" in overrides and isinstance(overrides["background"], dict):
        bgd = overrides["background"]
        valid_bg = {f.name for f in __import__("dataclasses").fields(BgStyle)}
        picked["background"] = BgStyle(**{k: v for k, v in bgd.items() if k in valid_bg})
    return _replace(base, **picked) if picked else base


# Packaged default style configs. These YAML files hold the master variable xr
# (font_size_ratio) that used to be hard-coded in code — so xr now lives in
# config, never as a literal in molds.py / __init__.py.
_DEFAULT_STYLES_DIR = Path(__file__).parent / "styles"


class YamlStyleResolver(StyleResolver):
    """Resolve styles from YAML files (two layers) + built-in molds.

    Two config layers, project beats default:
      * ``config_dir`` — optional project-level overrides (highest priority).
      * ``default_dir`` — packaged default style configs (lowest priority);
        this is where xr lives now that it is a required config value.

    For a style, the default-layer ``<name>.yaml`` and project-layer
    ``<name>.yaml`` are key-merged (project wins), expanded onto the named mold,
    then run through ``require_xr``: a resolved style without xr raises
    ConfigError instead of falling back to a code default (fixes bug #3 too —
    one path, one type).
    """

    def __init__(
        self,
        config_dir: Optional[str | Path] = None,
        default_dir: Optional[str | Path] = None,
    ) -> None:
        # project-level overrides (highest priority); may be None
        self.config_dir = Path(config_dir) if config_dir else None
        # built-in default configs (lowest priority); defaults to packaged dir
        self.default_dir = (
            Path(default_dir) if default_dir is not None else _DEFAULT_STYLES_DIR
        )

    def _load_style_data(self, style_name: str) -> dict:
        """Merge default-layer then project-layer YAML for a style (project wins)."""
        merged: dict = {}
        if self.default_dir:
            merged.update(load_yaml(self.default_dir / f"{style_name}.yaml"))
        if self.config_dir:
            merged.update(load_yaml(self.config_dir / f"{style_name}.yaml"))
        return merged

    def resolve(self, style_name: str, video_height: int) -> StyleDef:
        data = self._load_style_data(style_name)
        if data:
            base_mold = MOLDS.get(data.get("mold", style_name), MOLDS["default"])
            base = mold_to_style(base_mold)
            if data.get("mold"):
                base = _replace(base, name=style_name)
            style = _apply_overrides(base, data)
        elif style_name in MOLDS:
            # built-in mold but no config supplied xr → require_xr will raise.
            style = mold_to_style(MOLDS[style_name])
        else:
            style = DEFAULT_STYLE
        # Required-config gates: xr and font_family must have been provided by
        # config, or these raise (no code-level fallback for either).
        style = require_xr(style, style_name)
        return require_font_family(style, style_name)

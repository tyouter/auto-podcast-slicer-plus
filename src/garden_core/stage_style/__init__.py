"""Stage 6: style resolution.

Single resolution path (fixes legacy bug #3: SubtitleStyle + StyleDefinition
two parallel systems). A ``StyleResolver`` maps ``style_name`` → ``StyleDef``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from garden_core.config import ConfigError
from garden_core.types import StyleDef

__all__ = ["StyleResolver", "resolve_style", "DEFAULT_STYLE"]


# Structural fallback for an unknown style name. It deliberately carries NO
# font_size_ratio (xr) and NO font_family — both are required config values with
# no code default. A resolved style whose font_size_ratio / font_family is None
# means the config did not supply it; `require_xr` / `require_font_family` raise
# ConfigError rather than silently picking a built-in number or font. (The
# derived sizes outline_width/shadow_depth stay ratios of font_size and are
# unrelated to this requirement.)
DEFAULT_STYLE = StyleDef(
    name="default",
    font_family=None,      # required from config, no code default
    font_size_ratio=None,  # xr: required from config, no code default
    primary_color="&H00FFFFFF",
    outline_color="&H00000000",
    outline_width=0.036,   # ratio of font_size → ~1px outline at 1080p
    shadow_color="&H96000000",
    shadow_depth=0.014,    # ratio of font_size → ~0.4px shadow at 1080p
    background=None,
    position="bottom",
    bold=False,
)


def require_xr(style: StyleDef, style_name: str) -> StyleDef:
    """Enforce that the master variable xr (font_size_ratio) came from config.

    Returns the style unchanged when xr is present; raises a clear ConfigError
    when it is None. This is the single gate guaranteeing no code-level fallback
    for xr — every resolver passes its result through here before returning.
    """
    if style.font_size_ratio is None:
        raise ConfigError(
            f"style '{style_name}': font_size_ratio (xr) is required but was not "
            f"provided by any style config. Set 'font_size_ratio' in the style "
            f"YAML — there is no built-in default."
        )
    return style


def require_font_family(style: StyleDef, style_name: str) -> StyleDef:
    """Enforce that font_family came from config (same gate pattern as xr).

    Returns the style unchanged when font_family is present; raises a clear
    ConfigError when it is None. This guarantees no code-level fallback for the
    font — every resolver passes its result through here before returning.
    """
    if style.font_family is None:
        raise ConfigError(
            f"style '{style_name}': font_family is required but was not provided "
            f"by any style config. Set 'font_family' in the style YAML — there is "
            f"no built-in default."
        )
    return style


class StyleResolver(ABC):
    """Maps style_name → StyleDef. Stateless on the caller side; load once."""

    @abstractmethod
    def resolve(self, style_name: str, video_height: int) -> StyleDef: ...


class StaticResolver(StyleResolver):
    """Trivial resolver backed by a dict. Useful for tests / simple configs."""

    def __init__(self, styles: dict[str, StyleDef]) -> None:
        self._styles = styles

    def resolve(self, style_name: str, video_height: int) -> StyleDef:
        style = self._styles.get(style_name) or self._styles.get("default") or DEFAULT_STYLE
        style = require_xr(style, style_name)
        return require_font_family(style, style_name)


def resolve_style(
    style_name: str,
    video_height: int,
    resolver: StyleResolver,
) -> StyleDef:
    """Run stage 6: name → resolved StyleDef (font sizes scaled to video)."""
    style = resolver.resolve(style_name, video_height)
    # font_size_px is derived on demand; nothing to mutate on the frozen object.
    return style

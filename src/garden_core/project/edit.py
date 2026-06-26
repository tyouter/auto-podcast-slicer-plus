"""edit_project — modify a project.yaml config + re-validate + persist.

Implements T10 of the project management system (DEVELOPMENT_PLAN.md D1).

``edit_project(root_dir, **overrides)`` locates ``project.yaml``, loads it as a
**config view** (paths kept exactly as written on disk — no resolution to
absolute), applies field-level overrides, re-validates, atomically writes back
to the same ``project.yaml``, and returns the new ``ProjectConfig``.

Design decisions (per Meta-Brief T10 brief):
- **No** ``load_project``: reads via ``load_yaml → from_dict`` to preserve the
  on-disk path representation (relative stays relative, absolute stays absolute).
- **No** strict file-existence checks: only ``validate()`` runs (structural /
  referential consistency). File checks are the caller's responsibility.
- **Atomic write**: ``project.yaml.tmp`` → ``os.replace`` so the original file
  is never left half-written.
- **Protects data files**: only ``project.yaml`` is ever touched; source media,
  transcript, corrections.yaml, output/ are never deleted or modified.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from garden_core.config import ConfigError, load_yaml
from garden_core.project.config import ProjectConfig, validate
from garden_core.project.schema import (
    CutPointSpec,
    ProjectMeta,
    ProofOptsSpec,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
)

__all__ = ["edit_project"]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# The set of valid override keys — matches ProjectConfig field names.
_VALID_OVERRIDE_KEYS: frozenset[str] = frozenset({
    "meta",
    "sources",
    "transcript",
    "errata_path",
    "proof_opts",
    "cut_points",
    "style_name",
    "render_opts",
    "output_dir",
})

# Which override keys correspond to nested spec types.
_NESTED_SPEC_CLASS: dict[str, type] = {
    "meta": ProjectMeta,
    "transcript": TranscriptSpec,
    "proof_opts": ProofOptsSpec,
    "render_opts": RenderOptsSpec,
}

# Which override keys are collections whose elements must be spec instances.
_COLLECTION_ELEMENT_CLASS: dict[str, type] = {
    "sources": SourceSpec,
    "cut_points": CutPointSpec,
}

# Scalar fields (neither nested spec nor collection) — replaced directly.
_SCALAR_FIELDS: frozenset[str] = frozenset({
    "errata_path",
    "style_name",
    "output_dir",
})


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #

def edit_project(
    root_dir: str | Path,
    /,
    **overrides: Any,
) -> ProjectConfig:
    """Modify a project's ``project.yaml``, re-validate, and atomically persist.

    Parameters
    ----------
    root_dir:
        Either a ``project.yaml`` file path, or a project **root directory**
        (the directory that contains ``project.yaml``).  The same semantics as
        ``load_project``'s *path* parameter.
    **overrides:
        Top-level ``ProjectConfig`` field names mapped to new values.

        - **Scalar fields** (``errata_path``, ``style_name``, ``output_dir``):
          the value replaces the existing value directly.
        - **Nested spec fields** (``meta``, ``transcript``, ``proof_opts``,
          ``render_opts``): pass **either** an instance of the corresponding
          spec class (full replacement) **or** a ``dict`` (partial merge via
          ``dataclasses.replace`` — only the supplied keys are changed).
        - **Collection fields** (``sources``, ``cut_points``): pass a ``tuple``
          or ``list`` (full replacement).  Elements may be spec instances or
          plain ``dict`` (which are converted via ``Spec.from_dict``).

        Unknown keys raise ``ConfigError`` (typo guard).

    Returns
    -------
    ProjectConfig
        The new, validated config.  **Path fields are in the "config view"** —
        they match exactly what is written on disk (usually relative paths).
        This differs from ``load_project`` which returns absolute "runtime view"
        paths.  For runtime code, use ``load_project(root_dir, strict=…)``.

    Raises
    ------
    ConfigError
        - ``root_dir`` does not point to a ``project.yaml`` or a directory
          containing one (info suggests ``create_project``).
        - ``project.yaml`` is empty or not a mapping.
        - ``from_dict`` fails due to missing required fields / malformed data.
        - An override key is unknown (typo).
        - A nested-spec partial-merge dict contains an invalid field name.
        - The resulting config fails ``validate()`` (bad source refs, out-of-
          bounds cut points, duplicate ids, unknown style, start >= end, …).
        The disk ``project.yaml`` is **never** changed when an error occurs.

    OSError
        If the atomic write fails (permissions / disk full).  The temporary
        file is cleaned up on best-effort, and the original ``project.yaml``
        is preserved.
    """
    p = Path(root_dir)

    # --- 1. locate project.yaml -------------------------------------------
    yaml_path = _locate_yaml(p)

    # --- 2. load YAML dict (raw, paths as written on disk) -----------------
    data = load_yaml(yaml_path)
    if not isinstance(data, dict) or not data:
        raise ConfigError(
            f"project.yaml is empty, missing, or not a mapping: {yaml_path}"
        )

    # --- 3. from_dict (config view — paths kept as-is) ---------------------
    try:
        cfg = ProjectConfig.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(
            f"project.yaml {yaml_path}: {exc}"
        ) from exc

    # --- 4. apply overrides ------------------------------------------------
    cfg = _apply_overrides(cfg, overrides)

    # --- 5. validate (structural / referential; no filesystem IO) ----------
    validate(cfg)

    # --- 6. atomic write-back ----------------------------------------------
    _atomic_write(cfg, yaml_path)

    # --- 7. return new config ----------------------------------------------
    return cfg


# --------------------------------------------------------------------------- #
# internal helpers
# --------------------------------------------------------------------------- #

def _locate_yaml(p: Path) -> Path:
    """Given a path that is either a yaml file or a directory, return the
    ``project.yaml`` path, or raise ``ConfigError``."""
    if p.is_file():
        return p
    if p.is_dir():
        candidate = p / "project.yaml"
        if candidate.is_file():
            return candidate
        raise ConfigError(
            f"Directory '{p}' does not contain a 'project.yaml' file"
        )
    raise ConfigError(
        f"Path does not exist: '{p}' — use create_project() to create a new "
        f"project first"
    )


def _apply_overrides(cfg: ProjectConfig, overrides: Mapping[str, Any]) -> ProjectConfig:
    """Apply each override to *cfg* and return a new frozen ``ProjectConfig``.

    Raises ``ConfigError`` for unknown keys or invalid nested-spec dict keys.
    """
    for key, value in overrides.items():
        # --- typo guard ----------------------------------------------------
        if key not in _VALID_OVERRIDE_KEYS:
            raise ConfigError(
                f"Unknown override key '{key}'; valid keys: "
                f"{sorted(_VALID_OVERRIDE_KEYS)}"
            )

        # --- nested spec fields --------------------------------------------
        if key in _NESTED_SPEC_CLASS:
            spec_cls = _NESTED_SPEC_CLASS[key]
            existing = getattr(cfg, key)
            if isinstance(value, spec_cls):
                # Full replacement with an instance
                cfg = dataclasses.replace(cfg, **{key: value})
            elif isinstance(value, dict):
                # Partial merge via dataclasses.replace
                try:
                    new_spec = dataclasses.replace(existing, **value)
                except TypeError as exc:
                    raise ConfigError(
                        f"Cannot apply override for '{key}': {exc}. "
                        f"Valid fields for {spec_cls.__name__}: "
                        f"{[f.name for f in dataclasses.fields(spec_cls)]}"
                    ) from exc
                cfg = dataclasses.replace(cfg, **{key: new_spec})
            else:
                raise ConfigError(
                    f"Override for '{key}' must be a {spec_cls.__name__} "
                    f"instance or a dict, got {type(value).__name__}"
                )
            continue

        # --- collection fields ---------------------------------------------
        if key in _COLLECTION_ELEMENT_CLASS:
            elem_cls = _COLLECTION_ELEMENT_CLASS[key]
            if isinstance(value, (tuple, list)):
                converted = tuple(
                    _ensure_spec_instance(elem, elem_cls) for elem in value
                )
                cfg = dataclasses.replace(cfg, **{key: converted})
            else:
                raise ConfigError(
                    f"Override for '{key}' must be a tuple or list, "
                    f"got {type(value).__name__}"
                )
            continue

        # --- scalar fields -------------------------------------------------
        if key in _SCALAR_FIELDS:
            cfg = dataclasses.replace(cfg, **{key: value})
            continue

        # Should never reach here (all keys in _VALID_OVERRIDE_KEYS are
        # covered by the branches above), but guard defensively.
        raise ConfigError(
            f"Internal error: unhandled override key '{key}'"
        )

    return cfg


def _ensure_spec_instance(elem: Any, spec_cls: type) -> Any:
    """Convert *elem* to a *spec_cls* instance if it is a dict; otherwise
    return as-is."""
    if isinstance(elem, spec_cls):
        return elem
    if isinstance(elem, dict):
        return spec_cls.from_dict(elem)
    raise ConfigError(
        f"Collection element must be a {spec_cls.__name__} instance or a "
        f"dict, got {type(elem).__name__}: {elem!r}"
    )


def _atomic_write(cfg: ProjectConfig, yaml_path: Path) -> None:
    """Write *cfg* to *yaml_path* atomically via tmp + os.replace.

    On Windows ``os.replace`` is atomic (MoveFileEx with
    MOVEFILE_REPLACE_EXISTING).  If the write fails partway through, only the
    temporary file is affected — the original ``project.yaml`` is untouched.
    """
    tmp_path = yaml_path.with_suffix(yaml_path.suffix + ".tmp")
    try:
        cfg.to_yaml(tmp_path)
        os.replace(tmp_path, yaml_path)
    except BaseException:
        # Best-effort cleanup — do not mask the original exception.
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

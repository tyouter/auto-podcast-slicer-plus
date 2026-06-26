"""load_project — load + validate a project.yaml into a resolved ProjectConfig.

Implements T9 of the project management system (DEVELOPMENT_PLAN.md D1).

``load_project(path, *, strict=True)`` accepts a ``project.yaml`` file path **or**
a project root directory (auto-discovers ``<root>/project.yaml``), then:

1. Locates and loads the YAML.
2. Builds a raw ``ProjectConfig`` via ``ProjectConfig.from_dict``.
3. Resolves every relative path field against ``meta.root`` (which itself is
   resolved to absolute first).
4. Runs ``validate()`` (structural / referential checks — no filesystem IO).
5. When ``strict=True`` (default), additionally checks that every required
   file exists on disk (``source.path``, ``transcript.audio_path``,
   ``transcript.path``, ``errata_path``) — **all** missing files are
   reported in a single ``ConfigError``.

Returns a ``ProjectConfig`` whose path fields are all **absolute**
(the "runtime view"), even when the on-disk YAML stores relative paths.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from garden_core.config import ConfigError, load_yaml
from garden_core.project.config import ProjectConfig, validate
from garden_core.project.schema import (
    ProjectMeta,
    RenderOptsSpec,
    SourceSpec,
    TranscriptSpec,
)

__all__ = ["load_project"]


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #

def load_project(
    path: str | Path,
    *,
    strict: bool = True,
) -> ProjectConfig:
    """Load a ``project.yaml`` and return a resolved, validated ``ProjectConfig``.

    Parameters
    ----------
    path:
        Either a ``project.yaml`` file path, or a project **root directory**
        (the directory that contains ``project.yaml``).
    strict:
        If ``True`` (default), also verify that every required file exists on
        disk (``source.path``, ``transcript.audio_path``, ``transcript.path``,
        ``errata_path``).  Missing files are aggregated into a single
        ``ConfigError`` so the caller sees everything at once.
        If ``False``, only structural / referential ``validate()`` is run.

    Returns
    -------
    ProjectConfig
        The validated config with **all path fields resolved to absolute paths**
        (relative paths are resolved against ``meta.root``).

    Raises
    ------
    ConfigError
        For any loading / parsing / validation / file-existence problem.
    """
    p = Path(path)

    # --- 1. locate project.yaml -------------------------------------------
    yaml_path = _locate_yaml(p)

    # --- 2. load YAML dict -------------------------------------------------
    data = load_yaml(yaml_path)
    if not isinstance(data, dict) or not data:
        raise ConfigError(
            f"project.yaml is empty, missing, or not a mapping: {yaml_path}"
        )

    # --- 3. from_dict (raw config, paths as written in yaml) ---------------
    try:
        raw = ProjectConfig.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(
            f"project.yaml {yaml_path}: {exc}"
        ) from exc

    # --- 4. resolve meta.root to absolute (anchor for all other paths) -----
    resolved_root = _resolve_root(raw.meta.root)

    # --- 5. resolve every path field relative to resolved_root -------------
    resolved = _resolve_paths(raw, resolved_root)

    # --- 6. validate (structural / referential, no filesystem IO) ----------
    validate(resolved)

    # --- 7. strict file-existence checks -----------------------------------
    if strict:
        _check_file_existence(resolved, yaml_path)

    return resolved


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
        f"Path does not exist, or is neither a 'project.yaml' file nor a "
        f"directory containing one: '{p}'"
    )


def _resolve_root(root_str: str) -> Path:
    """Resolve ``meta.root`` to an absolute ``Path``.

    - Absolute → return as-is (resolved).
    - Relative → resolve against ``Path.cwd()``.
    """
    r = Path(root_str)
    if r.is_absolute():
        return r
    return (Path.cwd() / r).resolve()


def _resolve_paths(cfg: ProjectConfig, root: Path) -> ProjectConfig:
    """Return a new ``ProjectConfig`` with every path field resolved relative
    to *root* (which must already be absolute).  Paths that are already
    absolute are kept as-is."""
    return dataclasses.replace(
        cfg,
        meta=dataclasses.replace(cfg.meta, root=str(root)),
        sources=tuple(
            dataclasses.replace(s, path=_resolve(s.path, root))
            for s in cfg.sources
        ),
        transcript=dataclasses.replace(
            cfg.transcript,
            audio_path=_resolve(cfg.transcript.audio_path, root),
            path=_resolve(cfg.transcript.path, root),
        ),
        errata_path=_resolve(cfg.errata_path, root),
        render_opts=dataclasses.replace(
            cfg.render_opts,
            output_dir=_resolve(cfg.render_opts.output_dir, root),
        ),
        output_dir=_resolve(cfg.output_dir, root),
    )


def _resolve(path_str: str, root: Path) -> str:
    """Resolve *path_str* relative to *root* (which is absolute).

    - Already absolute → kept as-is (normalised via ``Path.resolve()`` with
      ``strict=False`` to avoid throwing on non-existent paths).
    - Relative → ``root / path_str`` (normalised the same way).
    """
    p = Path(path_str)
    if p.is_absolute():
        return str(p.resolve())
    return str((root / p).resolve())


def _check_file_existence(cfg: ProjectConfig, yaml_path: Path) -> None:
    """Verify every required file exists on disk.

    Raises ``ConfigError`` aggregating **all** missing files so the user sees
    everything at once rather than fixing one at a time.
    """
    missing: list[str] = []

    # source paths
    for src in cfg.sources:
        fp = Path(src.path)
        if not fp.is_file():
            missing.append(f"source {src.id}: {fp} (source.path)")

    # transcript
    tp = Path(cfg.transcript.path)
    if not tp.is_file():
        missing.append(f"transcript.path: {tp}")

    ap = Path(cfg.transcript.audio_path)
    if not ap.is_file():
        missing.append(f"transcript.audio_path: {ap}")

    # errata
    ep = Path(cfg.errata_path)
    if not ep.is_file():
        missing.append(f"errata_path: {ep}")

    if missing:
        lines = "\n    - ".join(missing)
        raise ConfigError(
            f"project \"{cfg.meta.name}\": missing required files "
            f"(strict=True):\n"
            f"    - {lines}\n"
            f"Use strict=False to skip file-existence checks."
        )

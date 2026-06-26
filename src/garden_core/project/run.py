"""ProjectRun: runtime orchestrator for the garden-core pipeline.

T11 (DEVELOPMENT_PLAN.md D1+D6).  ``ProjectRun(cfg, engines)`` holds a resolved
``ProjectConfig`` + injected ``Engines`` and provides staged methods
(transcribe / proofread / render / audit) that each produce exactly one
persistent artifact and record the outcome into ``<root>/run_manifest.json``
(schema_version=1).

Convenience entry points:

* ``ProjectRun.from_project_dir(dir, engines)`` — one-liner load+run
* ``run.all()`` — full pipeline, always runs every stage (idempotent overwrite)
* ``run.resume()`` — skip stages whose artifact already exists per manifest
* ``ProjectRun.load(manifest_path, engines)`` — reconstruct a run from a
  previous manifest so ``.resume()`` can continue

Multi-source translation (the core mechanism)::

    cfg.cut_points  (CutPointSpec: global timeline + source id)
        → _translate_cut_points()
        → types.CutPoint (source_media=absolute path + source_offset_s)

This makes hand-rolled multi-source batch scripts (e.g. tesla_stage04) obsolete
— one ``run.render()`` replaces them.

Design constraints (hard):
    * Does NOT modify run_from_audio / run_from_transcript / run_montage
    * Does NOT modify any stage_* / io_* / render_gate / types module
    * Does NOT modify T7-T10 project modules (schema/config/create/load/edit)
    * Manifest is NOT concurrency-safe (single-machine serial assumption)
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from garden_core.config import ConfigError, build_errata_config
from garden_core.infra.llm_client import NoLLMClient
from garden_core.io_.sink import save_transcript_json
from garden_core.io_.source import load_transcript_json
from garden_core.pipeline import Engines, PipelineOptions, run_from_transcript
from garden_core.project.config import ProjectConfig
from garden_core.project.load import load_project
from garden_core.stage_align import align
from garden_core.stage_asr import AudioRef, transcribe as asr_transcribe
from garden_core.stage_proofread import ErrataConfig, ProofOptions, proofread
from garden_core.stage_render import RenderOptions
from garden_core.stage_render.render_gate import audit_dir
from garden_core.types import CutPoint, RenderResult

log = logging.getLogger(__name__)

__all__ = ["ProjectRun", "StageResult"]

# --------------------------------------------------------------------------- #
# StageResult — lightweight immutable return value for each stage call
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StageResult:
    """Return value from a single stage execution.

    Not stored in the manifest — the manifest is the authoritative record.
    This is a convenience for callers who want to iterate ``run.all()`` results.
    """

    stage: str
    status: str  # "done" | "failed"
    artifact_path: str
    skipped: bool = False


# --------------------------------------------------------------------------- #
# ProjectRun
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProjectRun:
    """Runtime orchestrator: holds a resolved config + injected engines.

    Every stage method produces one artifact and writes to
    ``<cfg.meta.root>/run_manifest.json`` (schema_version=1).

    Usage::

        run = ProjectRun(cfg, engines)
        run.transcribe()
        run.proofread()
        run.render()
        run.audit()
        # or:
        results = run.all()
        # or:
        results = run.resume()
    """

    cfg: ProjectConfig
    engines: Engines

    # ------------------------------------------------------------------ #
    # convenience constructors
    # ------------------------------------------------------------------ #

    @classmethod
    def from_project_dir(
        cls, dir: str | Path, engines: Engines, *, strict: bool = False
    ) -> "ProjectRun":
        """Load a project directory and construct a ProjectRun in one call.

        Equivalent to ``ProjectRun(load_project(dir, strict=strict), engines)``.
        """
        cfg = load_project(dir, strict=strict)
        return cls(cfg=cfg, engines=engines)

    @classmethod
    def load(
        cls, manifest_path: str | Path, engines: Engines
    ) -> "ProjectRun":
        """Reconstruct a ProjectRun from a previous ``run_manifest.json``.

        Reads the manifest, validates ``schema_version==1`` (D6), then calls
        ``load_project(manifest.project.root, strict=False)`` to rebuild the
        config.  The returned run is ready for ``.resume()``.

        Raises ``ConfigError`` if the file is missing / not valid JSON, or if
        ``schema_version`` is not 1.
        """
        mp = Path(manifest_path)
        try:
            with open(mp, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except FileNotFoundError:
            raise ConfigError(
                f"run_manifest.json not found: {mp}"
            )
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"run_manifest.json is not valid JSON: {mp}: {exc}"
            ) from exc

        if not isinstance(manifest, dict):
            raise ConfigError(
                f"run_manifest.json is not a JSON object: {mp}"
            )

        schema_version = manifest.get("schema_version")
        if schema_version != 1:
            raise ConfigError(
                f"run_manifest.json: unsupported schema_version={schema_version!r} "
                f"(expected 1)"
            )

        project_root = manifest.get("project", {}).get("root", "")
        if not project_root:
            raise ConfigError(
                "run_manifest.json: missing 'project.root' — cannot rebuild config"
            )

        cfg = load_project(project_root, strict=False)
        return cls(cfg=cfg, engines=engines)

    # ------------------------------------------------------------------ #
    # manifest helpers
    # ------------------------------------------------------------------ #

    def manifest_path(self) -> Path:
        """Return ``<cfg.meta.root>/run_manifest.json``."""
        return Path(self.cfg.meta.root) / "run_manifest.json"

    def read_manifest(self) -> dict:
        """Read the current manifest dict, or ``{}`` if absent / corrupt."""
        mp = self.manifest_path()
        if not mp.exists():
            return {}
        try:
            with open(mp, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_manifest(self, manifest: dict) -> None:
        """Atomically write the manifest dict to disk (tmp + os.replace)."""
        mp = self.manifest_path()
        mp.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(mp) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, mp)
        except Exception:
            # Clean up tmp on failure; re-raise
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def _record(
        self, stage: str, status: str, artifact: str, params: dict
    ) -> None:
        """Write / update the manifest row for one stage.

        Reads the current manifest, removes any existing row for *stage*,
        appends a new row with *started* / *finished* timestamps, and
        atomically writes the manifest back.
        """
        now = datetime.datetime.now().isoformat()
        manifest = self.read_manifest()

        stages: list[dict] = manifest.get("stages", [])
        # Remove any previous entry for this stage (last-write wins)
        stages = [s for s in stages if s.get("stage") != stage]

        stages.append({
            "stage": stage,
            "status": status,
            "artifact_path": artifact,
            "params": params,
            "started": now,
            "finished": now,
        })

        manifest["schema_version"] = 1
        manifest["project"] = {
            "name": self.cfg.meta.name,
            "root": self.cfg.meta.root,
        }
        manifest["updated"] = now
        manifest["stages"] = stages

        self._write_manifest(manifest)

    # ------------------------------------------------------------------ #
    # stage: transcribe (ASR + align + save)
    # ------------------------------------------------------------------ #

    def transcribe(self) -> StageResult:
        """Run ASR (stage 1) + optional alignment (stage 2) and persist the
        transcript to ``cfg.transcript.path``.

        Requires ``engines.transcriber``.  If ``engines.aligner`` is ``None``,
        alignment is skipped with a warning.

        Returns a ``StageResult`` with ``stage="transcribe"`` and
        ``artifact_path=cfg.transcript.path``.
        """
        if self.engines.transcriber is None:
            raise RuntimeError(
                "transcribe() requires engines.transcriber — "
                "inject a Transcriber instance (e.g. FunASRLocal)"
            )

        audio = AudioRef(path=self.cfg.transcript.audio_path)
        t = asr_transcribe(audio, self.engines.transcriber, hotwords=())

        if self.engines.aligner is not None:
            t = align(t, self.engines.aligner, self.cfg.transcript.audio_path)
        else:
            log.warning(
                "transcribe(): no aligner — skipping stage 2 alignment"
            )

        save_transcript_json(t, self.cfg.transcript.path)

        self._record(
            "transcribe",
            "done",
            self.cfg.transcript.path,
            {"engine": self.engines.transcriber.__class__.__name__},
        )

        return StageResult(
            "transcribe", "done", self.cfg.transcript.path, skipped=False
        )

    # ------------------------------------------------------------------ #
    # stage: proofread (load transcript → apply errata → save)
    # ------------------------------------------------------------------ #

    def proofread(self) -> StageResult:
        """Load the saved transcript, apply proofreading (errata + normalizer
        + phonetic + optional LLM / dual-channel), then overwrite
        ``cfg.transcript.path`` with the corrected transcript.

        **Precondition**: ``transcribe()`` must have been run first (a
        ``transcript.json`` must exist at ``cfg.transcript.path``).

        Errata are loaded from ``cfg.errata_path`` (resolved relative to
        ``cfg.meta.root`` when the path is not absolute).  A missing errata
        file is tolerated (empty config).

        Returns a ``StageResult`` with ``stage="proofread"``.
        """
        errata_path = self._resolve_errata_path()
        errata = build_errata_config(errata_path)
        return self._apply_proofread(errata)

    # ------------------------------------------------------------------ #
    # internal: core proofread logic (shared by proofread / reproofread)
    # ------------------------------------------------------------------ #

    def _apply_proofread(self, errata: ErrataConfig) -> StageResult:
        """Run proofreading with the given *errata* and overwrite
        ``cfg.transcript.path``.  Records ``stage="proofread"`` to manifest.

        Extracted from ``proofread()`` so ``reproofread()`` can inject an
        ``ErrataConfig`` directly without going through ``cfg.errata_path``.
        """
        t = load_transcript_json(self.cfg.transcript.path)

        opts = ProofOptions(**dataclasses.asdict(self.cfg.proof_opts))

        t2 = proofread(
            t,
            errata=errata,
            llm=self.engines.llm,
            opts=opts,
            audio_path=self.cfg.transcript.audio_path,
        )

        save_transcript_json(t2, self.cfg.transcript.path)

        self._record(
            "proofread",
            "done",
            self.cfg.transcript.path,
            {"corrections": list(t2.corrections_applied)},
        )

        return StageResult(
            "proofread", "done", self.cfg.transcript.path, skipped=False
        )

    # ------------------------------------------------------------------ #
    # stage: reproofread (incremental proofread with optional rerender)
    # ------------------------------------------------------------------ #

    def reproofread(
        self,
        errata: ErrataConfig | None = None,
        *,
        rerender_clip_ids: Sequence[str] | None = None,
    ) -> list[StageResult]:
        """Run proofreading with an optional inline errata config, and
        optionally re-render specific clips afterwards.

        ``errata=None`` (default) loads corrections from ``cfg.errata_path``
        (same source as ``proofread()``).  Pass an ``ErrataConfig`` to inject
        errata directly **without persisting** to disk — use
        ``edit_project(errata_path=…)`` or hand-edit ``corrections.yaml`` if
        you need to make the new errata permanent.

        ``rerender_clip_ids=None`` (default) performs **only** proofreading.
        Pass a list of clip ids to re-render those clips immediately after
        the transcript is updated.

        Returns a ``list[StageResult]`` with at least the proofread entry;
        when ``rerender_clip_ids`` is given a second ``render`` entry is
        appended.
        """
        if errata is None:
            e = build_errata_config(self._resolve_errata_path())
        else:
            e = errata

        out: list[StageResult] = [self._apply_proofread(e)]

        if rerender_clip_ids is not None:
            out.append(self.rerender(rerender_clip_ids))

        return out

    # ------------------------------------------------------------------ #
    # stage: render (load transcript → multi-source translate → run)
    # ------------------------------------------------------------------ #

    def render(self) -> StageResult:
        """Load the transcript, translate ``cfg.cut_points`` into runtime
        ``CutPoint`` objects (multi-source translation), then call
        ``run_from_transcript`` with a render-specific configuration that
        **skips alignment and proofreading** — those are the responsibility
        of the ``transcribe()`` and ``proofread()`` stages.

        **Precondition**: ``transcribe()`` (and ideally ``proofread()``)
        should have been run first, so the transcript at ``cfg.transcript.path``
        is already aligned and corrected.  If you call ``render()`` without
        ``proofread()`` first, errata corrections will NOT be applied (this
        is by design — stage separation).

        All clips are rendered with ``cfg.style_name`` (single project-level
        style).  Per-clip ``CutPointSpec.style_name`` is preserved in the
        translated ``CutPoint`` but not used for rendering in this version.

        Returns a ``StageResult`` with ``stage="render"`` and
        ``artifact_path=cfg.render_opts.output_dir``.
        """
        cut_points = self._translate_cut_points()
        results = self._render_cut_points(cut_points, skip_existing=True)

        self._record(
            "render",
            "done",
            self.cfg.render_opts.output_dir,
            {"clips": len(results), "style": self.cfg.style_name},
        )

        return StageResult(
            "render", "done", self.cfg.render_opts.output_dir, skipped=False
        )

    # ------------------------------------------------------------------ #
    # internal: core render logic (shared by render / rerender)
    # ------------------------------------------------------------------ #

    def _render_cut_points(
        self, cut_points: list[CutPoint], *, skip_existing: bool
    ) -> list[RenderResult]:
        """Load the transcript, build a render-specific ``PipelineOptions``
        (no align / no proofread), and call ``run_from_transcript`` with the
        given *cut_points*.

        Extracted from ``render()`` so ``rerender()`` can pass a subset of
        ``CutPoint`` objects and override ``skip_existing`` without
        duplicating the setup logic.
        """
        t = load_transcript_json(self.cfg.transcript.path)

        engines_r = dataclasses.replace(
            self.engines, aligner=None, llm=NoLLMClient()
        )

        opts = PipelineOptions(
            errata=ErrataConfig.empty(),
            proof=ProofOptions(
                enable_normalize=False,
                enable_errata=False,
                enable_phonetic=False,
                enable_llm=False,
                enable_dual_channel=False,
            ),
            render=self._render_options_from_cfg(),
            source_media="",
            skip_existing=skip_existing,
            render_gate=True,
        )

        return run_from_transcript(
            t,
            cut_points,
            self.cfg.style_name,
            engines_r,
            opts,
            audio_path=self.cfg.transcript.audio_path,
        )

    # ------------------------------------------------------------------ #
    # stage: rerender (incremental re-render of specific clips)
    # ------------------------------------------------------------------ #

    def rerender(self, clip_ids: Sequence[str]) -> StageResult:
        """Re-render one or more clips **without** re-running transcription
        or proofreading.

        Translates ``cfg.cut_points``, filters to the requested *clip_ids*,
        and calls ``run_from_transcript`` with ``skip_existing=False`` so
        existing mp4/ass/srt files for those clips are overwritten.

        Raises ``ValueError`` if *clip_ids* is empty, or ``ConfigError`` if
        any id is unknown.

        Returns a ``StageResult`` with ``stage="render"`` — overwrites the
        render row in ``run_manifest.json`` (same stage name as ``render()``,
        but ``params`` includes ``"rerender": True`` + the specific clip list).

        .. note::
            ``rerender()`` only gates the *subset* of clips it processes.
            Run ``audit()`` afterwards for a full-directory review.
        """
        ids = list(clip_ids)
        if not ids:
            raise ValueError(
                "rerender(): clip_ids must be a non-empty sequence"
            )

        wanted = set(ids)
        all_cps = self._translate_cut_points()
        known = {cp.clip_id for cp in all_cps}
        unknown = wanted - known
        if unknown:
            raise ConfigError(
                f"rerender(): unknown clip_ids {sorted(unknown)}; "
                f"known: {sorted(known)}"
            )

        # Preserve cfg order (not caller order)
        subset = [cp for cp in all_cps if cp.clip_id in wanted]

        results = self._render_cut_points(subset, skip_existing=False)

        self._record(
            "render",
            "done",
            self.cfg.render_opts.output_dir,
            {
                "clips": ids,
                "style": self.cfg.style_name,
                "rerender": True,
            },
        )

        return StageResult(
            "render", "done", self.cfg.render_opts.output_dir, skipped=False
        )

    # ------------------------------------------------------------------ #
    # stage: audit (mechanical quality gate over the output directory)
    # ------------------------------------------------------------------ #

    def audit(self) -> StageResult:
        """Run ``audit_dir`` over ``cfg.render_opts.output_dir`` and write an
        ``audit_report.json`` to ``cfg.output_dir``.

        The audit checks file-existence, ffprobe resolution/codec, ASS cue
        count, and ASS content gate (font-ratio + safe-area).  It does **NOT**
        raise on failure — the result is recorded in the manifest and the
        report so a human can review it.

        Returns a ``StageResult`` with ``stage="audit"``.
        """
        ro = self.cfg.render_opts

        report = audit_dir(
            ro.output_dir,
            expected_horizontal=(ro.horizontal_width, ro.horizontal_height),
            expected_vertical=(ro.vertical_width, ro.vertical_height),
            render_horizontal=ro.render_horizontal,
            render_vertical=ro.render_vertical,
            raise_on_fail=False,
        )

        report_path = str(Path(self.cfg.output_dir) / "audit_report.json")
        report.save(report_path)

        status = "done" if report.passed else "failed"
        self._record(
            "audit",
            status,
            report_path,
            {"passed": report.passed, "violations": len(report.violations)},
        )

        return StageResult("audit", status, report_path, skipped=False)

    # ------------------------------------------------------------------ #
    # orchestration
    # ------------------------------------------------------------------ #

    def all(self) -> list[StageResult]:
        """Run every stage in order: transcribe → proofread → render → audit.

        Always runs every stage regardless of manifest state (idempotent
        overwrite).  Use ``resume()`` for breakpoint-continue.
        """
        return [
            self.transcribe(),
            self.proofread(),
            self.render(),
            self.audit(),
        ]

    def resume(self) -> list[StageResult]:
        """Run each stage, skipping those whose artifact already exists on
        disk and is recorded as ``status="done"`` in the manifest.

        Skip logic (D5 naive): ``status=="done"`` **and** ``artifact_path``
        points to an existing file.  No parameter-hash comparison — if you
        changed config, use ``all()`` or manually delete the manifest row.
        """
        manifest = self.read_manifest()
        done: dict[str, dict] = {}
        for row in manifest.get("stages", []):
            if row.get("status") == "done":
                done[row["stage"]] = row

        out: list[StageResult] = []
        for fn, name in [
            (self.transcribe, "transcribe"),
            (self.proofread, "proofread"),
            (self.render, "render"),
            (self.audit, "audit"),
        ]:
            row = done.get(name)
            if (
                row
                and row.get("artifact_path")
                and Path(row["artifact_path"]).exists()
            ):
                out.append(StageResult(
                    name, "done", row["artifact_path"], skipped=True
                ))
            else:
                out.append(fn())
        return out

    # ------------------------------------------------------------------ #
    # internal helpers
    # ------------------------------------------------------------------ #

    def _translate_cut_points(self) -> list[CutPoint]:
        """Translate ``cfg.cut_points`` (CutPointSpec, config-layer) into
        ``types.CutPoint`` (runtime-layer) with resolved ``source_media``
        absolute paths and ``source_offset_s`` from the corresponding
        ``SourceSpec``.

        This is the core multi-source mechanism that makes hand-rolled batch
        scripts (e.g. tesla_stage04 BATCH1/BATCH2) obsolete.
        """
        source_map = {s.id: s for s in self.cfg.sources}
        out: list[CutPoint] = []
        for cp in self.cfg.cut_points:
            try:
                spec = source_map[cp.source]
            except KeyError:
                raise ConfigError(
                    f"cut_point '{cp.clip_id}' references unknown source "
                    f"'{cp.source}'; known sources: {sorted(source_map)}"
                ) from None
            out.append(CutPoint(
                clip_id=cp.clip_id,
                source_media=spec.path,
                start_s=cp.start_s,
                end_s=cp.end_s,
                style_name=cp.style_name,
                title=cp.title,
                source_offset_s=spec.source_offset_s,
            ))
        return out

    def _resolve_errata_path(self) -> str:
        """Resolve ``cfg.errata_path`` to an absolute path.

        If already absolute → return as-is.
        If relative → resolve against ``cfg.meta.root``.
        """
        p = Path(self.cfg.errata_path)
        if p.is_absolute():
            return str(p)
        return str(Path(self.cfg.meta.root) / p)

    def _render_options_from_cfg(self) -> RenderOptions:
        """Translate ``cfg.render_opts`` (frozen RenderOptsSpec) into the
        mutable ``RenderOptions`` that ``stage_render`` expects."""
        ro = self.cfg.render_opts
        return RenderOptions(
            output_dir=ro.output_dir,
            render_horizontal=ro.render_horizontal,
            render_vertical=ro.render_vertical,
            vertical_height=ro.vertical_height,
            vertical_width=ro.vertical_width,
            horizontal_height=ro.horizontal_height,
            horizontal_width=ro.horizontal_width,
            crf=ro.crf,
        )

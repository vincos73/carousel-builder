#!/usr/bin/env python3
"""Serve a local, dependency-free editorial review session for a carousel manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_core import (  # noqa: E402
    VISUAL_STYLE_IDS,
    InterprocessLock,
    LockUnavailableError,
    approval_stage_for_workflow,
    append_only_json,
    atomic_write_json as core_atomic_write_json,
    client_feedback_id,
    copy_limit_issues,
    ensure_private_directory,
    feedback_archive_path,
    feedback_request_fingerprint,
    new_feedback_id,
    normalized_logo_mode,
    normalized_proof_browser,
    normalized_visual_style_system,
    render_context_fingerprint,
    render_snapshot_fingerprint,
    safe_feedback_id,
    sentence_line_breaks,
    sha256_file,
    strict_json_loads,
    strict_json_text,
    valid_sha256,
    validate_emphasis_values,
)
from manifest_contract import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    MAX_SLIDES,
    MAX_TEXT,
    is_current_manifest,
    parsed_schema_version,
    required_proof_ids_for_slides,
    resolved_visual_style_system,
    stable_items,
    text,
    validate_manifest_contract,
    validated_revision,
)


MAX_BODY_BYTES = 1_000_000
MAX_COMMENTS = 200
EDITOR_VERSION = "2.10.0"
RENDER_CONTRACT = "approved-preview-dom-v2"
TYPOGRAPHY_DEFAULTS = {
    "cover_px": 112,
    "cover_subtitle_px": 56,
    "section_title_px": 72,
    "body_px": 64,
    "cover_weight": 800,
    "cover_subtitle_weight": 500,
    "section_title_weight": 800,
    "body_weight": 620,
    "body_line_height": 1.12,
    "sentence_gap_em": 0.6,
    "cover_subtitle_line_height": 1.08,
    "body_tracking_em": -0.025,
    "min_auto_scale": 0.92,
    "overflow_policy": "error_and_copy_revision",
}
FONT_MIME_TYPES = {
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}
IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
FONT_SOURCES = {"uploaded", "bundled", "system", "fallback"}
BUNDLED_FONT_ASSETS = {
    "display": ("Inter", Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Inter-Variable.ttf"),
    "body": ("Inter", Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Inter-Variable.ttf"),
    "serif": (
        "Playfair Display",
        Path(__file__).resolve().parent.parent / "assets" / "fonts" / "PlayfairDisplay-Italic-Variable.ttf",
    ),
}
FONT_ROLE_FALLBACKS = {
    "display": ("display", "sans"),
    "body": ("body", "sans"),
    "serif": ("serif_italic", "serif"),
}
EMPHASIS_ROLES = ("bold", "italic", "serif", "accent", "underline")
PALETTE_COLOR_FIELDS = (
    "background_light",
    "background_dark",
    "text_on_light",
    "text_on_dark",
    "accent",
)
VISUAL_STYLE_SYSTEMS = {
    "editorial-frame": "Editoriale",
    "editorial-halftone": "Geometrico",
    "corporate-modular": "Istituzionale",
}
VISUAL_STYLE_ALTERNATES = {
    "editorial-frame": "corporate-modular",
    "corporate-modular": "editorial-frame",
    "editorial-halftone": "editorial-frame",
}
if frozenset(VISUAL_STYLE_SYSTEMS) != VISUAL_STYLE_IDS:
    raise RuntimeError("Le etichette dei sistemi visivi non coincidono con review_core")


TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


def valid_session_token(value: object) -> str | None:
    return value if isinstance(value, str) and TOKEN_RE.fullmatch(value) else None


class IdempotencyConflictError(RuntimeError):
    """Raised when a client reuses a feedback UUID for different content."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File non trovato: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON non valido in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Il contenuto di {path} deve essere un oggetto JSON")
    return value


def absolute_input_path(path: Path) -> Path:
    """Return an absolute path without dereferencing any path component."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def directory_is_user_controlled(path: Path) -> bool:
    """Return whether the current user can create or replace entries in a directory."""
    if os.name == "nt":
        return os.access(path, os.W_OK)
    path_stat = os.stat(path)
    effective_uid = getattr(os, "geteuid", lambda: -1)()
    if path_stat.st_uid == effective_uid or path_stat.st_mode & stat.S_IWOTH:
        return True
    groups = set(getattr(os, "getgroups", lambda: [])())
    return bool(path_stat.st_mode & stat.S_IWGRP and path_stat.st_gid in groups)


def reject_symlink_path(path: Path, *, field: str) -> None:
    """Reject symlinks in every existing component before any mutation."""
    absolute = absolute_input_path(path)
    current = Path(absolute.anchor) if absolute.anchor else Path()
    parts = absolute.parts[1:] if absolute.anchor else absolute.parts
    for part in parts:
        current /= part
        try:
            path_stat = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(path_stat.st_mode) and (
            current == absolute or directory_is_user_controlled(current.parent)
        ):
            raise ValueError(
                f"{field} non può attraversare un collegamento simbolico: {current}"
            )


def path_entry_exists(path: Path) -> bool:
    """Report directory-entry existence without following a final symlink."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _stable_stat_signature(path_stat: os.stat_result) -> tuple[int, ...]:
    signature = (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_nlink,
    )
    # On Windows, ctime is creation-time metadata and the value exposed by a
    # pathname stat can differ from the value exposed by the already-open file
    # handle.  Inode, size, mtime and link-count still bind the stable read.
    return signature if os.name == "nt" else signature + (path_stat.st_ctime_ns,)


def _validate_private_file_stat(path: Path, path_stat: os.stat_result) -> None:
    if stat.S_ISLNK(path_stat.st_mode):
        raise ValueError(f"Il file di sessione non può essere un collegamento simbolico: {path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"Il file di sessione deve essere un file regolare: {path}")
    if path_stat.st_nlink != 1:
        raise ValueError(f"Il file di sessione non può essere un hard link: {path}")


def read_private_json(path: Path) -> dict:
    """Read a private session JSON through a stable, no-follow descriptor."""
    descriptor = None
    try:
        before = os.lstat(path)
        _validate_private_file_stat(path, before)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        _validate_private_file_stat(path, opened)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError(f"Il file di sessione è cambiato durante l'apertura: {path}")

        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after_descriptor = os.fstat(descriptor)
        after_path = os.lstat(path)
        _validate_private_file_stat(path, after_descriptor)
        _validate_private_file_stat(path, after_path)
        expected = _stable_stat_signature(before)
        if any(
            _stable_stat_signature(candidate) != expected
            for candidate in (opened, after_descriptor, after_path)
        ):
            raise ValueError(f"Il file di sessione è cambiato durante la lettura: {path}")
        raw = b"".join(chunks).decode("utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"File non trovato: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        value = strict_json_loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON non valido in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} deve contenere un oggetto JSON")
    return value


def manifest_revision(manifest_path: Path) -> int:
    """Read only the durable revision; status polling must not hash visual assets."""
    return validated_revision(read_json(manifest_path))


def manifest_status(manifest_path: Path) -> dict:
    """Read the polling contract without constructing or hashing the render model."""
    manifest = read_json(manifest_path)
    workflow_state = manifest.get("workflow_state", "bozza")
    return {
        "manifest_revision": validated_revision(manifest),
        "workflow_state": workflow_state,
        "approval_checkpoint": approval_stage_for_workflow(workflow_state),
    }


def atomic_write_json(path: Path, value: dict) -> None:
    core_atomic_write_json(path, value, mode=0o600, private_parent=True)


def canonical_path(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def same_path(left: Path | str, right: Path | str) -> bool:
    return canonical_path(left) == canonical_path(right)


def validate_state_manifest(state: dict, manifest_path: Path) -> None:
    bound_manifest = state.get("manifest")
    if not isinstance(bound_manifest, str) or not bound_manifest:
        raise ValueError("La sessione non contiene un percorso manifest valido")
    if not same_path(bound_manifest, manifest_path):
        raise ValueError("La cartella di sessione è già associata a un manifest diverso")


def feedback_event(feedback_path: Path, feedback: dict) -> dict:
    archive_path = feedback_archive_path(feedback_path.parent, feedback["feedback_id"])
    return {
        "event": "feedback",
        "feedback_id": feedback["feedback_id"],
        "action": feedback["action"],
        "path": str(feedback_path),
        "archive_path": str(archive_path),
    }


def emit_event(value: dict) -> bool:
    """Best-effort event transport; durable session files remain authoritative."""
    try:
        print(json.dumps(value, ensure_ascii=False), flush=True)
    except (BrokenPipeError, OSError, ValueError):
        return False
    return True


def commit_feedback(
    *,
    journal_path: Path,
    feedback_path: Path,
    state_path: Path,
    manifest_path: Path,
    current_state: dict,
    feedback: dict,
    manifest_revision: int,
) -> dict:
    feedback_id = safe_feedback_id(feedback.get("feedback_id"))
    archive_path = feedback_archive_path(feedback_path.parent, feedback_id)
    state_before = {
        key: current_state.get(key)
        for key in (
            "last_feedback_id",
            "last_feedback_path",
            "last_action",
            "applied_feedback_id",
            "manifest_revision",
        )
    }
    state_patch = {
        "last_feedback_id": feedback_id,
        "last_feedback_path": str(archive_path),
        "last_action": feedback["action"],
        "feedback_submitted_at": feedback["submitted_at"],
        "manifest_revision": manifest_revision,
    }
    journal = {
        "version": 2,
        "manifest": str(manifest_path),
        "feedback": feedback,
        "state_before": state_before,
        "state_patch": state_patch,
    }
    atomic_write_json(journal_path, journal)
    append_only_json(archive_path, feedback)
    atomic_write_json(feedback_path, feedback)
    next_state = dict(current_state)
    next_state.update(state_patch)
    atomic_write_json(state_path, next_state)
    return feedback_event(feedback_path, feedback)


def recover_feedback_commit(
    *,
    journal_path: Path,
    feedback_path: Path,
    state_path: Path,
    manifest_path: Path,
) -> dict | None:
    if not path_entry_exists(journal_path):
        return None
    journal = read_private_json(journal_path)
    journal_version = journal.get("version")
    if (
        not isinstance(journal_version, int)
        or isinstance(journal_version, bool)
        or journal_version not in {1, 2}
        or not isinstance(journal.get("manifest"), str)
    ):
        raise ValueError("Journal feedback non valido")
    if not same_path(journal["manifest"], manifest_path):
        raise ValueError("Il journal feedback appartiene a un manifest diverso")
    feedback = journal.get("feedback")
    state_before = journal.get("state_before")
    state_patch = journal.get("state_patch")
    if not all(isinstance(value, dict) for value in (feedback, state_before, state_patch)):
        raise ValueError("Journal feedback incompleto")
    feedback_id = safe_feedback_id(feedback.get("feedback_id"))
    archive_path = feedback_archive_path(feedback_path.parent, feedback_id)
    feedback_action = feedback.get("action")
    if (
        not isinstance(feedback_action, str)
        or feedback_action not in {"feedback", "approve"}
        or not isinstance(feedback.get("submitted_at"), str)
        or state_patch.get("last_feedback_id") != feedback_id
        or state_patch.get("last_action", feedback.get("action")) != feedback.get("action")
        or state_patch.get("feedback_submitted_at") != feedback.get("submitted_at")
        or not isinstance(state_patch.get("manifest_revision"), int)
        or isinstance(state_patch.get("manifest_revision"), bool)
    ):
        raise ValueError("Journal feedback incoerente")
    state_patch.setdefault("last_action", feedback["action"])
    state_patch.setdefault("last_feedback_path", str(archive_path))

    allowed_patch = {
        "last_feedback_id",
        "last_feedback_path",
        "last_action",
        "feedback_submitted_at",
        "manifest_revision",
    }
    if set(state_patch) - allowed_patch:
        raise ValueError("Journal feedback contiene campi di stato non consentiti")

    current_state = read_private_json(state_path)
    validate_state_manifest(current_state, manifest_path)
    stored_action = current_state.get("last_action")
    before_action = state_before.get("last_action")
    after_action = state_patch["last_action"]
    if stored_action not in (before_action, after_action):
        raise ValueError("last_action non coincide con l'azione del journal feedback")
    if current_state.get("applied_feedback_id") == feedback_id:
        if stored_action != after_action:
            raise ValueError("last_action non coincide con il feedback già applicato")
        append_only_json(archive_path, feedback)
        try:
            journal_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    for key, before_value in state_before.items():
        after_value = state_patch.get(key, before_value)
        if current_state.get(key) not in (before_value, after_value):
            raise ValueError("Lo stato è cambiato dopo l'inizio del commit feedback")

    append_only_json(archive_path, feedback)
    atomic_write_json(feedback_path, feedback)
    next_state = dict(current_state)
    next_state.update(state_patch)
    atomic_write_json(state_path, next_state)
    return feedback_event(feedback_path, feedback)


def _short_string(value: object, *, limit: int = 200) -> str:
    """Return a presentation-safe string without trusting manifest types."""
    return value if isinstance(value, str) and len(value) <= limit else ""


def normalize_typography(manifest: dict) -> dict:
    """Expose documented typography defaults while discarding malformed values."""
    raw = manifest.get("typography")
    values = raw if isinstance(raw, dict) else {}

    def positive_int(key: str) -> int:
        value = values.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1_000:
            return value
        return TYPOGRAPHY_DEFAULTS[key]

    def finite_number(key: str, *, lower: float, upper: float) -> float:
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            converted = float(value)
            if lower <= converted <= upper:
                return converted
        return TYPOGRAPHY_DEFAULTS[key]

    min_auto_scale = finite_number("min_auto_scale", lower=0.0, upper=10.0)
    return {
        "cover_px": positive_int("cover_px"),
        "cover_subtitle_px": positive_int("cover_subtitle_px"),
        "section_title_px": positive_int("section_title_px"),
        "body_px": positive_int("body_px"),
        "cover_weight": positive_int("cover_weight"),
        "cover_subtitle_weight": positive_int("cover_subtitle_weight"),
        "section_title_weight": positive_int("section_title_weight"),
        "body_weight": positive_int("body_weight"),
        "body_line_height": finite_number("body_line_height", lower=0.5, upper=3.0),
        "sentence_gap_em": finite_number("sentence_gap_em", lower=0.2, upper=1.2),
        "cover_subtitle_line_height": finite_number(
            "cover_subtitle_line_height", lower=0.5, upper=3.0
        ),
        "body_tracking_em": finite_number("body_tracking_em", lower=-1.0, upper=1.0),
        "min_auto_scale": max(0.92, min_auto_scale),
        "overflow_policy": (
            values.get("overflow_policy")
            if values.get("overflow_policy") == "error_and_copy_revision"
            else TYPOGRAPHY_DEFAULTS["overflow_policy"]
        ),
    }


def validated_emphasis(value: object, content: str) -> list[str]:
    """Keep every unique, exact, non-empty phrase contained in its text."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for phrase in value:
        if (
            isinstance(phrase, str)
            and phrase
            and phrase in content
            and phrase not in result
        ):
            result.append(phrase)
    return result


def validate_emphasis_overlap(values: dict[str, list[str]], content: str, *, field: str) -> None:
    """Selections for separate visual roles must never share characters."""
    special_roles = {"italic", "serif", "accent", "underline"}
    ranges: list[tuple[int, int, str, str]] = []
    for role, phrases in values.items():
        for phrase in phrases:
            start = content.find(phrase)
            end = start + len(phrase)
            for other_start, other_end, other_role, other_phrase in ranges:
                if start < other_end and other_start < end:
                    if start == other_start and end == other_end:
                        if role in special_roles and other_role in special_roles:
                            raise ValueError(
                                f"{field}: “{phrase}” ha più trattamenti. Scegline uno: corsivo, sottolineatura oppure evidenziatore"
                            )
                        raise ValueError(
                            f"{field}: “{phrase}” ha più stili. Mantienine uno solo"
                        )
                    raise ValueError(
                        f"{field}: i trattamenti su “{other_phrase}” e “{phrase}” si sovrappongono. Correggi le selezioni oppure mantienine uno solo"
                    )
            ranges.append((start, end, role, phrase))


def normalized_cover_mode(manifest: dict, cover_visual: dict) -> str:
    """Expose cover intent without silently replacing a missing requested visual."""
    raw_mode = manifest.get("cover_mode")
    if not isinstance(raw_mode, str):
        legacy_mode = manifest.get("cover_visual_mode")
        if legacy_mode == "generative":
            raw_mode = "generated"
        elif legacy_mode == "technical":
            raw_mode = "provided"
    if raw_mode not in {"generated", "provided", "typographic"}:
        raw_mode = "provided" if cover_visual["available"] else "typographic"
    return raw_mode


def visual_proofs(
    manifest: dict,
    *,
    brand: dict,
    typography: dict,
    cover_visual: dict,
) -> dict:
    """Describe one recommended direction with optional comparison paths."""
    cover = {**cover_visual, "mode": normalized_cover_mode(manifest, cover_visual)}
    selected = resolved_visual_style_system(manifest)
    return {
        "presentation_mode": "recommended",
        "selected_style_system": selected,
        "recommended_style_system": selected,
        "alternate_style_system": VISUAL_STYLE_ALTERNATES[selected],
        "advanced_style_systems": ["editorial-halftone"],
        "identity": {
            "brand": brand,
            "typography": typography,
            "cover": cover,
        },
        "options": [
            {
                "id": style_system,
                "label": label,
                "style_system": style_system,
                "tier": "advanced" if style_system == "editorial-halftone" else "standard",
                "recommended": style_system == selected,
            }
            for style_system, label in VISUAL_STYLE_SYSTEMS.items()
        ],
    }


def _font_asset(manifest: dict, manifest_path: Path, key: str) -> tuple[dict, Path | None]:
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}
    configured = None
    for candidate in FONT_ROLE_FALLBACKS[key]:
        if candidate in fonts:
            configured = fonts[candidate]
            break
    family = ""
    source = "fallback"
    file_name: object = None
    if isinstance(configured, dict):
        family = _short_string(configured.get("family"))
        declared_source = configured.get("source")
        if isinstance(declared_source, str) and declared_source in FONT_SOURCES:
            source = declared_source
        file_name = configured.get("file")
    elif isinstance(configured, str):
        family = _short_string(configured)

    resolved: Path | None = None
    if isinstance(file_name, str) and file_name:
        candidate = Path(file_name)
        if not candidate.is_absolute() and candidate.suffix.lower() in FONT_MIME_TYPES:
            font_root = manifest_path.parent.resolve()
            candidate = (font_root / candidate).resolve()
            try:
                candidate.relative_to(font_root)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                resolved = candidate
                if source == "fallback":
                    source = "uploaded"

    bundled_family, bundled_path = BUNDLED_FONT_ASSETS[key]
    if resolved is None and family.casefold() == bundled_family.casefold() and bundled_path.is_file():
        resolved = bundled_path
        source = "bundled"

    available = resolved is not None
    public = {
        "family": family,
        "source": source,
        "available": available,
        "endpoint": f"/api/font/{key}" if available else "",
    }
    return public, resolved


def _italic_font_asset(manifest: dict, manifest_path: Path) -> tuple[dict, Path | None]:
    """Resolve the italic role without pretending an upright font is italic.

    The explicit brand role wins.  A body/display italic is accepted only when
    it has its own local file; a legacy serif italic may use the bundled
    Playfair italic asset.
    """
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}
    root = manifest_path.parent.resolve()

    for role in ("emphasis_italic", "body_italic", "display_italic", "serif_italic"):
        configured = fonts.get(role)
        if configured is None:
            continue
        family = _short_string(configured.get("family")) if isinstance(configured, dict) else _short_string(configured)
        source = "fallback"
        file_name: object = None
        if isinstance(configured, dict):
            declared_source = configured.get("source")
            if isinstance(declared_source, str) and declared_source in FONT_SOURCES:
                source = declared_source
            file_name = configured.get("file")
        resolved: Path | None = None
        if isinstance(file_name, str) and file_name:
            candidate = Path(file_name)
            if not candidate.is_absolute() and candidate.suffix.lower() in FONT_MIME_TYPES:
                candidate = (root / candidate).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    candidate = None
                if candidate is not None and candidate.is_file():
                    resolved = candidate
                    if source == "fallback":
                        source = "uploaded"
        if (
            resolved is None
            and role == "serif_italic"
            and family.casefold() == BUNDLED_FONT_ASSETS["serif"][0].casefold()
            and BUNDLED_FONT_ASSETS["serif"][1].is_file()
        ):
            resolved = BUNDLED_FONT_ASSETS["serif"][1]
            source = "bundled"
        if resolved is not None:
            return {
                "family": family,
                "source": source,
                "available": True,
                "endpoint": "/api/font/italic",
                "role": role,
            }, resolved

    return {
        "family": "",
        "source": "fallback",
        "available": False,
        "endpoint": "",
        "role": "",
    }, None


def font_assets(manifest: dict, manifest_path: Path) -> tuple[dict, dict[str, Path]]:
    """Build public font metadata and the private, manifest-resolved allowlist."""
    public: dict = {}
    allowed: dict[str, Path] = {}
    for key in ("display", "body", "serif"):
        entry, resolved = _font_asset(manifest, manifest_path, key)
        public[key] = entry
        if resolved is not None:
            allowed[key] = resolved
    italic, resolved_italic = _italic_font_asset(manifest, manifest_path)
    public["italic"] = italic
    if resolved_italic is not None:
        allowed["italic"] = resolved_italic
    # ``sans`` remains a read-only compatibility alias for older editor clients.
    public["sans"] = {**public["body"], "endpoint": "/api/font/sans" if public["body"]["available"] else ""}
    if "body" in allowed:
        allowed["sans"] = allowed["body"]
    return public, allowed


def cover_image_asset(manifest: dict, manifest_path: Path) -> tuple[dict, Path | None]:
    """Resolve a project-local cover image without exposing filesystem paths."""
    value = manifest.get("cover_image")
    resolved: Path | None = None
    if isinstance(value, str) and value:
        candidate = Path(value)
        if not candidate.is_absolute() and candidate.suffix.lower() in IMAGE_MIME_TYPES:
            root = manifest_path.parent.resolve()
            candidate = (root / candidate).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                resolved = candidate
    return {
        "available": resolved is not None,
        "endpoint": "/api/cover-image" if resolved is not None else "",
        "position": _short_string(manifest.get("cover_image_position")) or "50% 50%",
    }, resolved


def logo_assets(manifest: dict, manifest_path: Path) -> tuple[dict, dict[str, Path]]:
    """Resolve safe raster previews for local light/dark logo masters.

    SVG is deliberately never served: an SVG master may contain active content.
    A manifest may nevertheless declare one when an adjacent PNG preview with
    the same basename is available.
    """
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    logos = brand.get("logos") if isinstance(brand.get("logos"), dict) else {}
    root = manifest_path.parent.resolve()
    public: dict = {}
    allowed: dict[str, Path] = {}
    for key, endpoint in (("on_light", "/api/logo/on-light"), ("on_dark", "/api/logo/on-dark")):
        value = logos.get(key)
        resolved: Path | None = None
        source = ""
        master_format = ""
        if isinstance(value, str) and value:
            candidate = Path(value)
            suffix = candidate.suffix.lower()
            master_format = suffix.removeprefix(".")
            if not candidate.is_absolute() and suffix in IMAGE_MIME_TYPES:
                candidate = (root / candidate).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    candidate = None
                if candidate is not None and candidate.is_file():
                    resolved = candidate
                    source = "manifest"
            elif not candidate.is_absolute() and suffix == ".svg":
                svg_candidate = (root / candidate).resolve()
                try:
                    svg_candidate.relative_to(root)
                except ValueError:
                    svg_candidate = None
                if svg_candidate is not None:
                    png_candidate = svg_candidate.with_suffix(".png")
                    if png_candidate.is_file():
                        resolved = png_candidate
                        source = "sibling_png"
        public[key] = {
            "available": resolved is not None,
            "endpoint": endpoint if resolved is not None else "",
            "source": source,
            "master_format": master_format,
        }
        if resolved is not None:
            allowed[key] = resolved
    return public, allowed


def brand_summary(manifest: dict, manifest_path: Path | None = None) -> dict:
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    palette = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}

    def font_name(*keys: str) -> str:
        value = None
        for key in keys:
            if key in fonts:
                value = fonts[key]
                break
        if isinstance(value, dict):
            return _short_string(value.get("family"))
        return _short_string(value)

    italic_role = next(
        (key for key in ("emphasis_italic", "body_italic", "display_italic", "serif_italic") if key in fonts),
        "",
    )
    asset_metadata = {
        "display": {"family": font_name("display", "sans"), "source": "fallback", "available": False, "endpoint": ""},
        "body": {"family": font_name("body", "sans"), "source": "fallback", "available": False, "endpoint": ""},
        "serif": {"family": font_name("serif_italic", "serif"), "source": "fallback", "available": False, "endpoint": ""},
        "italic": {
            "family": font_name(italic_role) if italic_role else "",
            "source": "fallback",
            "available": False,
            "endpoint": "",
            "role": italic_role,
        },
    }
    asset_metadata["sans"] = dict(asset_metadata["body"])
    logo_metadata = {
        "on_light": {"available": False, "endpoint": "", "source": "", "master_format": ""},
        "on_dark": {"available": False, "endpoint": "", "source": "", "master_format": ""},
    }
    if manifest_path is not None:
        asset_metadata, _ = font_assets(manifest, manifest_path)
        logo_metadata, _ = logo_assets(manifest, manifest_path)
    palette_declared = {
        field: isinstance(palette.get(field), str) and bool(palette[field].strip())
        for field in PALETTE_COLOR_FIELDS
    }

    return {
        "name": text(brand.get("name"), field="brand.name", limit=300),
        "website": text(brand.get("website"), field="brand.website", limit=500),
        "signature": text(brand.get("signature"), field="brand.signature", limit=300),
        "display": font_name("display", "sans"),
        "body": font_name("body", "sans"),
        "sans": font_name("body", "sans"),
        "serif": font_name("serif_italic", "serif"),
        "emphasis_italic": asset_metadata["italic"],
        "font_assets": asset_metadata,
        "logos": logo_metadata,
        "palette_declared": palette_declared,
        "palette": {
            "background_light": text(
                palette.get("background_light") or "#F5F1E8",
                field="brand.palette.background_light",
                limit=32,
            ),
            "background_dark": text(
                palette.get("background_dark") or "#172033",
                field="brand.palette.background_dark",
                limit=32,
            ),
            "text_on_light": text(
                palette.get("text_on_light") or "#172033",
                field="brand.palette.text_on_light",
                limit=32,
            ),
            "text_on_dark": text(
                palette.get("text_on_dark") or "#FFFFFF",
                field="brand.palette.text_on_dark",
                limit=32,
            ),
            "accent": text(
                palette.get("accent") or "#FEBD08",
                field="brand.palette.accent",
                limit=32,
            ),
        },
    }


def reusable_brand_profile(manifest: dict) -> dict:
    """Build a portable brand profile without exposing local asset paths.

    The editor can save this JSON for the next carousel.  Fonts and logos stay
    referenced rather than embedded, exactly like the documented profile
    format; a future brand pack can carry the corresponding files when needed.
    """
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}
    palette = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
    direction = brand.get("visual_direction") if isinstance(brand.get("visual_direction"), dict) else {}
    outro = brand.get("outro") if isinstance(brand.get("outro"), dict) else {}

    profile_fonts: dict[str, dict[str, str]] = {}
    for role in ("display", "body", "body_italic", "emphasis_italic"):
        value = fonts.get(role)
        if isinstance(value, dict):
            family = _short_string(value.get("family"))
            source = _short_string(value.get("source"))
        else:
            family = _short_string(value)
            source = "fallback"
        if family:
            profile_fonts[role] = {
                "family": family,
                "source": source if source in FONT_SOURCES else "fallback",
            }

    def strings(value: object, *, limit: int = 12, item_limit: int = 500) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and len(item) <= item_limit][:limit]

    mode = _short_string(direction.get("mode"))
    if mode not in {"editorial-geometric", "photographic", "illustrated-collage", "hand-drawn", "3d", "custom"}:
        mode = "editorial-geometric"
    internal_slides = _short_string(direction.get("internal_slides"))
    if not internal_slides:
        internal_slides = "clean_typographic"
    surface_mode = _short_string(palette.get("surface_mode"))
    if surface_mode not in {"light", "dark", "alternating"}:
        surface_mode = "alternating"
    copy_mode = _short_string(outro.get("copy_mode"))
    if copy_mode not in {"generate_from_source", "fixed"}:
        copy_mode = "generate_from_source"
    summary = brand_summary(manifest)
    return {
        "profile_type": "carousel-brand",
        "schema_version": "1.1",
        "name": summary["name"],
        "website": summary["website"],
        "signature": summary["signature"],
        "tagline": _short_string(brand.get("tagline"), limit=300),
        "logos": {},
        "fonts": profile_fonts,
        "typography": normalize_typography(manifest),
        "palette": {"surface_mode": surface_mode, **summary["palette"]},
        "palette_declared": summary["palette_declared"],
        "visual_direction": {
            "mode": mode,
            "description": _short_string(direction.get("description"), limit=1_200),
            "references": strings(direction.get("references")),
            "avoid": strings(direction.get("avoid")),
            "internal_slides": internal_slides,
        },
        "visual_signature": {"style_system": resolved_visual_style_system(manifest)},
        "outro": {
            "enabled": outro.get("enabled") is not False,
            "goal": _short_string(outro.get("goal"), limit=80) or "comment",
            "copy_mode": copy_mode,
            "eyebrow": _short_string(outro.get("eyebrow"), limit=300),
            "fixed_title": _short_string(outro.get("fixed_title"), limit=1_000),
            "fixed_body": _short_string(outro.get("fixed_body"), limit=2_000),
        },
        "asset_notice": "Logo e font non sono incorporati: allega gli asset o un brand pack per una portabilità completa.",
    }


RENDER_SLIDE_FIELDS = (
    "id",
    "kind",
    "title",
    "summary",
    "title_bold",
    "title_italic",
    "title_serif",
    "title_accent",
    "title_underline",
    "summary_bold",
    "summary_italic",
    "summary_serif",
    "summary_accent",
    "summary_underline",
)


def render_slides(slides: list[dict]) -> list[dict]:
    return [
        {field: slide.get(field, [] if "_" in field else "") for field in RENDER_SLIDE_FIELDS}
        for slide in slides
    ]


def render_asset_digests(manifest: dict, manifest_path: Path) -> dict[str, str]:
    """Hash the exact renderer bundle and local assets used by the editor."""
    _cover, cover_path = cover_image_asset(manifest, manifest_path)
    _logos, logo_paths = logo_assets(manifest, manifest_path)
    _fonts, font_paths = font_assets(manifest, manifest_path)
    paths: dict[str, Path] = {}
    if (
        cover_path is not None
        and normalized_cover_mode(manifest, _cover) in {"generated", "provided"}
    ):
        paths["cover"] = cover_path
    paths.update({f"logo:{role}": path for role, path in logo_paths.items()})
    paths.update({f"font:{role}": path for role, path in font_paths.items()})
    editor_assets = Path(__file__).resolve().parent.parent / "assets" / "review-editor"
    paths.update(
        {
            "renderer:index": editor_assets / "index.html",
            "renderer:script": editor_assets / "app.js",
            "renderer:styles": editor_assets / "styles.css",
        }
    )
    cached: dict[str, str] = {}
    result: dict[str, str] = {}
    for role, path in sorted(paths.items()):
        canonical = str(path.resolve())
        if canonical not in cached:
            cached[canonical] = sha256_file(path)
        result[role] = cached[canonical]
    return result


def fingerprint_for_model(
    model: dict,
    *,
    context_fingerprint: str,
    slides: list[dict] | None = None,
    visual_style_system: str | None = None,
    logo_mode: str | None = None,
) -> str:
    selected_style = visual_style_system or model["visual_proofs"][
        "selected_style_system"
    ]
    return render_snapshot_fingerprint(
        context_fingerprint=context_fingerprint,
        slides=render_slides(slides or model["slides"]),
        visual_style_system=selected_style,
        logo_mode=logo_mode or model["logo_mode"],
    )


def manifest_model(
    manifest_path: Path,
    *,
    manifest: dict | None = None,
    include_internal: bool = False,
) -> dict:
    manifest = read_json(manifest_path) if manifest is None else manifest
    contract = validate_manifest_contract(manifest)
    revision = validated_revision(manifest)

    slides: list[dict] = [
        {
            "id": "cover",
            "kind": "cover",
            "label": "Copertina",
            "title": text(manifest.get("cover_title"), field="cover_title"),
            "summary": sentence_line_breaks(
                text(manifest.get("cover_subtitle"), field="cover_subtitle")
            ),
            "title_serif": validated_emphasis(
                manifest.get("cover_title_serif"), text(manifest.get("cover_title"), field="cover_title")
            ),
            "title_italic": validated_emphasis(
                manifest.get("cover_title_italic"), text(manifest.get("cover_title"), field="cover_title")
            ),
            "title_bold": validated_emphasis(
                manifest.get("cover_title_bold"), text(manifest.get("cover_title"), field="cover_title")
            ),
            "title_accent": validated_emphasis(
                manifest.get("cover_title_accent"), text(manifest.get("cover_title"), field="cover_title")
            ),
            "title_underline": validated_emphasis(
                manifest.get("cover_title_underline"), text(manifest.get("cover_title"), field="cover_title")
            ),
            "summary_bold": validated_emphasis(
                manifest.get("cover_subtitle_bold"), text(manifest.get("cover_subtitle"), field="cover_subtitle")
            ),
            "summary_italic": validated_emphasis(
                manifest.get("cover_subtitle_italic"), text(manifest.get("cover_subtitle"), field="cover_subtitle")
            ),
            "summary_serif": validated_emphasis(
                manifest.get("cover_subtitle_serif"), text(manifest.get("cover_subtitle"), field="cover_subtitle")
            ),
            "summary_accent": validated_emphasis(
                manifest.get("cover_subtitle_accent"), text(manifest.get("cover_subtitle"), field="cover_subtitle")
            ),
            "summary_underline": validated_emphasis(
                manifest.get("cover_subtitle_underline"), text(manifest.get("cover_subtitle"), field="cover_subtitle")
            ),
            "deletable": False,
        }
    ]
    for index, item in enumerate(contract["items"], start=2):
        slides.append(
            {
                "id": item["id"],
                "kind": "item",
                "label": f"Slide {index}",
                "title": text(item.get("title"), field=f"{item['id']}.title"),
                "summary": sentence_line_breaks(
                    text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "title_serif": validated_emphasis(
                    item.get("title_serif"), text(item.get("title"), field=f"{item['id']}.title")
                ),
                "title_italic": validated_emphasis(
                    item.get("title_italic"), text(item.get("title"), field=f"{item['id']}.title")
                ),
                "title_bold": validated_emphasis(
                    item.get("title_bold"), text(item.get("title"), field=f"{item['id']}.title")
                ),
                "title_accent": validated_emphasis(
                    item.get("title_accent"), text(item.get("title"), field=f"{item['id']}.title")
                ),
                "title_underline": validated_emphasis(
                    item.get("title_underline"), text(item.get("title"), field=f"{item['id']}.title")
                ),
                "summary_bold": validated_emphasis(
                    item.get("summary_bold"), text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "summary_serif": validated_emphasis(
                    item.get("summary_serif"), text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "summary_italic": validated_emphasis(
                    item.get("summary_italic"), text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "summary_accent": validated_emphasis(
                    item.get("summary_accent"), text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "summary_underline": validated_emphasis(
                    item.get("summary_underline"), text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "deletable": True,
            }
        )

    outro = contract["outro"]
    if contract["outro_enabled"]:
        slides.append(
            {
                "id": "outro",
                "kind": "outro",
                "label": "Chiusura",
                "title": text(outro.get("title"), field="outro.title"),
                "summary": sentence_line_breaks(
                    text(outro.get("body"), field="outro.body")
                ),
                "title_serif": validated_emphasis(
                    outro.get("title_serif"), text(outro.get("title"), field="outro.title")
                ),
                "title_italic": validated_emphasis(
                    outro.get("title_italic"), text(outro.get("title"), field="outro.title")
                ),
                "title_bold": validated_emphasis(
                    outro.get("title_bold"), text(outro.get("title"), field="outro.title")
                ),
                "title_accent": validated_emphasis(
                    outro.get("title_accent"), text(outro.get("title"), field="outro.title")
                ),
                "title_underline": validated_emphasis(
                    outro.get("title_underline"), text(outro.get("title"), field="outro.title")
                ),
                "summary_bold": validated_emphasis(
                    outro.get("summary_bold"), text(outro.get("body"), field="outro.body")
                ),
                "summary_serif": validated_emphasis(
                    outro.get("summary_serif"), text(outro.get("body"), field="outro.body")
                ),
                "summary_italic": validated_emphasis(
                    outro.get("summary_italic"), text(outro.get("body"), field="outro.body")
                ),
                "summary_accent": validated_emphasis(
                    outro.get("summary_accent"), text(outro.get("body"), field="outro.body")
                ),
                "summary_underline": validated_emphasis(
                    outro.get("summary_underline"), text(outro.get("body"), field="outro.body")
                ),
                "deletable": False,
            }
        )

    sequence_mode = contract["sequence_mode"]
    format_data = manifest.get("format") if isinstance(manifest.get("format"), dict) else {}
    cover_visual, _ = cover_image_asset(manifest, manifest_path)
    cover_visual["mode"] = normalized_cover_mode(manifest, cover_visual)
    typography = normalize_typography(manifest)
    brand = brand_summary(manifest, manifest_path)
    proof = manifest.get("proof") if isinstance(manifest.get("proof"), dict) else {}
    workflow_state = contract["workflow_state"]
    approval_checkpoint = approval_stage_for_workflow(workflow_state)
    model = {
        "editor_version": EDITOR_VERSION,
        "render_contract": RENDER_CONTRACT,
        "schema_version": contract["schema_version"],
        "legacy_manifest": contract["legacy"],
        "revision": revision,
        "workflow_state": workflow_state,
        "approval_checkpoint": approval_checkpoint,
        "sequence_mode": sequence_mode,
        "source_type": manifest.get("source_type", "notes"),
        "format": {
            "ratio": format_data.get("ratio", "4:5"),
            "master_width": format_data.get("master_width", 1080),
            "master_height": format_data.get("master_height", 1350),
            "width": format_data.get("width", 1440),
            "height": format_data.get("height", 1800),
            "preview_width": contract["proof"]["preview_width"],
            "preview_height": format_data.get("preview_height", 600),
        },
        "typography": typography,
        "brand": brand,
        "brand_profile": reusable_brand_profile(manifest),
        "cover_visual": cover_visual,
        "cover_mode": cover_visual["mode"],
        "logo_mode": normalized_logo_mode(manifest.get("logo_mode")) or "auto",
        "visual_proofs": visual_proofs(
            manifest,
            brand=brand,
            typography=typography,
            cover_visual=cover_visual,
        ),
        "proof": contract["proof"],
        "production": contract["production"],
        "slides": slides,
    }
    render_cover_visual = model["cover_visual"]
    if model["cover_mode"] == "typographic":
        render_cover_visual = {
            "available": False,
            "endpoint": "",
            "position": "50% 50%",
            "mode": "typographic",
        }
    context = {
        "editor_version": EDITOR_VERSION,
        "render_contract": RENDER_CONTRACT,
        "format": model["format"],
        "typography": model["typography"],
        "brand": model["brand"],
        "cover_visual": render_cover_visual,
        "cover_mode": model["cover_mode"],
        "sequence_mode": model["sequence_mode"],
        # The approved proof is bound to the exact producer/output contract.
        # Changing delivery targets after approval must invalidate the proof.
        "production": model["production"],
        # Only the coarse approval checkpoint belongs to the render identity:
        # entering visual proof invalidates a stale profile/text approval, while
        # later visual workflow states keep the same approved proof valid.
        "approval_checkpoint": model["approval_checkpoint"],
    }
    context_fingerprint = render_context_fingerprint(
        context, render_asset_digests(manifest, manifest_path)
    )
    model["render_fingerprint"] = fingerprint_for_model(
        model, context_fingerprint=context_fingerprint
    )
    model["proof_approved"] = bool(
        proof.get("approved") is True
        and proof.get("render_fingerprint") == model["render_fingerprint"]
        and contract["proof"]["style_system_verified"]
        and contract["proof"]["slide_ids"] == contract["proof"]["required_slide_ids"]
        and contract["proof"]["browser"] is not None
        and contract["production"]["mode"] in {"renderer", "adapter"}
        and contract["production"]["producer"] == RENDER_CONTRACT
        and contract["production"]["selected_style_supported"]
    )
    if include_internal:
        model["_render_context_fingerprint"] = context_fingerprint
    return model


def validate_feedback(
    payload: object,
    model: dict,
    *,
    request_fingerprint: str | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Il batch deve essere un oggetto JSON")
    action = payload.get("action")
    if not isinstance(action, str) or action not in {"feedback", "approve"}:
        raise ValueError("action deve essere feedback oppure approve")
    base_revision = payload.get("base_revision")
    if not isinstance(base_revision, int) or isinstance(base_revision, bool):
        raise ValueError("base_revision deve essere un intero")
    if base_revision != model["revision"]:
        raise RuntimeError(
            f"La revisione di base {base_revision} non coincide con la revisione corrente {model['revision']}"
        )

    source_by_id = {slide["id"]: slide for slide in model["slides"]}
    slides = payload.get("slides")
    if not isinstance(slides, list) or not (2 <= len(slides) <= MAX_SLIDES):
        raise ValueError(f"Il batch deve contenere tra 2 e {MAX_SLIDES} slide")
    seen: set[str] = set()
    normalized_slides: list[dict] = []
    item_count = 0
    warnings: list[str] = []
    italic_font_available = bool(
        model.get("brand", {}).get("font_assets", {}).get("italic", {}).get("available")
    )
    for position, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError("Ogni slide deve essere un oggetto")
        slide_id = slide.get("id")
        if not isinstance(slide_id, str) or slide_id not in source_by_id or slide_id in seen:
            raise ValueError(f"ID slide non valido o duplicato: {slide_id}")
        seen.add(slide_id)
        source = source_by_id[slide_id]
        if slide.get("kind") != source["kind"]:
            raise ValueError(f"Tipo non valido per {slide_id}")
        if source["kind"] == "item":
            item_count += 1
        title = text(slide.get("title"), field=f"slides[{position}].title")
        summary = sentence_line_breaks(
            text(slide.get("summary"), field=f"slides[{position}].summary")
        )
        emphasis: dict[str, list[str]] = {}
        for field, content in (("title", title), ("summary", summary)):
            values = {
                role: validate_emphasis_values(
                    slide.get(f"{field}_{role}", source.get(f"{field}_{role}", [])),
                    content,
                    field=f"slides[{position}].{field}_{role}",
                )
                for role in EMPHASIS_ROLES
            }
            validate_emphasis_overlap(values, content, field=f"slides[{position}].{field}")
            if (values["italic"] or values["serif"]) and not italic_font_available:
                message = f"{slide_id}.{field} usa il corsivo senza un font corsivo reale disponibile"
                if action == "approve":
                    raise ValueError(message)
                warnings.append(message)
            emphasis.update({f"{field}_{role}": phrases for role, phrases in values.items()})

        normalized_slides.append(
            {
                "id": slide_id,
                "kind": source["kind"],
                "title": title,
                "summary": summary,
                **emphasis,
            }
        )

        if not title.strip() and not summary.strip():
            raise ValueError(f"{slide_id} non può essere vuota")
        if source["kind"] == "cover" and not title.strip():
            raise ValueError("Il titolo della copertina non può essere vuoto")

    if normalized_slides[0]["id"] != "cover":
        raise ValueError("La copertina deve restare la prima slide")
    if "outro" in source_by_id and normalized_slides[-1]["id"] != "outro":
        raise ValueError("La chiusura deve restare l'ultima slide")
    if item_count < 1:
        raise ValueError("Deve restare almeno una slide interna")

    approval_issues = copy_limit_issues(normalized_slides)
    if model.get("sequence_mode") == "narrative":
        approval_issues.extend(
            f"{slide['id']}.title deve essere vuoto in modalità narrative"
            for slide in normalized_slides
            if slide["kind"] == "item" and slide["title"].strip()
        )
    if action == "approve" and approval_issues:
        raise ValueError("Approvazione bloccata: " + "; ".join(approval_issues))
    if action == "feedback":
        warnings.extend(approval_issues)

    comments = payload.get("comments", [])
    if not isinstance(comments, list) or len(comments) > MAX_COMMENTS:
        raise ValueError(f"comments deve contenere al massimo {MAX_COMMENTS} elementi")
    normalized_comments: list[dict] = []
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict):
            raise ValueError(f"comments[{index}] deve essere un oggetto")
        kind = comment.get("kind")
        if not isinstance(kind, str) or kind not in {"selection", "slide", "brand"}:
            raise ValueError(f"Tipo di commento non valido: {kind}")
        slide_id = comment.get("slide_id", "")
        if not isinstance(slide_id, str):
            raise ValueError(f"comments[{index}].slide_id deve essere una stringa")
        if kind != "brand" and slide_id not in source_by_id:
            raise ValueError(f"Commento riferito a una slide sconosciuta: {slide_id}")
        normalized_comments.append(
            {
                "id": text(comment.get("id"), field=f"comments[{index}].id", limit=200),
                "kind": kind,
                "slide_id": slide_id,
                "field": text(
                    comment.get("field"), field=f"comments[{index}].field", limit=100
                ),
                "quote": text(
                    comment.get("quote"), field=f"comments[{index}].quote", limit=5_000
                ),
                "start": comment.get("start") if isinstance(comment.get("start"), int) else None,
                "end": comment.get("end") if isinstance(comment.get("end"), int) else None,
                "feedback": text(
                    comment.get("feedback"),
                    field=f"comments[{index}].feedback",
                    limit=5_000,
                ),
            }
        )

    visual_style_system = None
    for key in ("visual_style_system", "selected_style_system", "style_system"):
        if key in payload:
            visual_style_system = normalized_visual_style_system(payload[key])
            if visual_style_system is None:
                raise ValueError("visual_style_system non valido")
            break

    logo_mode = normalized_logo_mode(payload.get("logo_mode", model.get("logo_mode", "auto")))
    if logo_mode is None:
        raise ValueError("logo_mode deve essere auto oppure hidden")

    cover_mode = payload.get("cover_mode", model.get("cover_mode", "typographic"))
    if not isinstance(cover_mode, str) or cover_mode not in {
        "generated",
        "provided",
        "typographic",
    }:
        raise ValueError(
            "cover_mode deve essere generated, provided oppure typographic"
        )

    approved_render_fingerprint = None
    base_render_fingerprint = None
    approval_stage = None
    base_workflow_state = None
    proof_slide_ids = None
    style_system_verified = None
    proof_browser = None
    if action == "approve":
        approval_stage = approval_stage_for_workflow(model.get("workflow_state"))
        if "approval_stage" in payload:
            raise ValueError(
                "approval_stage è derivato dal server e non deve essere inviato dal client"
            )
        base_workflow_state = payload.get("base_workflow_state")
        if (
            not isinstance(base_workflow_state, str)
            or base_workflow_state != model.get("workflow_state")
        ):
            raise ValueError(
                "base_workflow_state non coincide con lo stato corrente del workflow; ricarica l'editor"
            )
        base_render_fingerprint = valid_sha256(payload.get("render_fingerprint"))
        if base_render_fingerprint != model.get("render_fingerprint"):
            raise ValueError(
                "render_fingerprint non coincide con lo snapshot visuale corrente; ricarica l'editor"
            )
        context_fingerprint = valid_sha256(
            model.get("_render_context_fingerprint")
        )
        if context_fingerprint is None:
            raise ValueError("Contesto del fingerprint visuale non disponibile")
        approved_render_fingerprint = fingerprint_for_model(
            model,
            context_fingerprint=context_fingerprint,
            slides=normalized_slides,
            visual_style_system=visual_style_system,
            logo_mode=logo_mode,
        )
        if approval_stage == "visual_proof":
            if cover_mode != model.get("cover_mode"):
                raise ValueError(
                    "La modalità della copertina deve essere salvata prima di approvare la prova visuale"
                )
            if cover_mode in {"generated", "provided"} and not model.get(
                "cover_visual", {}
            ).get("available"):
                raise ValueError(
                    "La copertina con visuale richiede un'immagine disponibile prima dell'approvazione"
                )
            selected_style = (
                visual_style_system
                or model["visual_proofs"]["selected_style_system"]
            )
            current_slides = []
            for slide in model["slides"]:
                normalized = {
                    "id": slide["id"],
                    "kind": slide["kind"],
                    "title": slide.get("title", ""),
                    "summary": slide.get("summary", ""),
                }
                for field in ("title", "summary"):
                    for role in EMPHASIS_ROLES:
                        normalized[f"{field}_{role}"] = slide.get(
                            f"{field}_{role}", []
                        )
                current_slides.append(normalized)
            if normalized_slides != current_slides:
                raise ValueError(
                    "Le modifiche editoriali devono essere inviate e riapprovate prima della prova visuale"
                )
            proof_slide_ids = payload.get("proof_slide_ids")
            required_ids = required_proof_ids_for_slides(normalized_slides)
            if proof_slide_ids != required_ids:
                raise ValueError(
                    "proof_slide_ids non coincide con il campione visuale richiesto"
                )
            if payload.get("style_system_verified") is not True:
                raise ValueError(
                    "style_system_verified=true è obbligatorio per approvare la prova visuale"
                )
            style_system_verified = True
            proof_browser = normalized_proof_browser(
                payload.get("proof_browser"), required=True
            )
            production = model.get("production", {})
            if production.get("mode") not in {"renderer", "adapter"}:
                raise ValueError(
                    "La prova visuale può essere approvata solo con un renderer o adapter"
                )
            if production.get("producer") != RENDER_CONTRACT:
                raise ValueError(
                    "Il produttore non implementa il contratto renderer locale corrente"
                )
            if selected_style not in production.get("supported_style_systems", []):
                raise ValueError(
                    "Il produttore non supporta il visual_style_system selezionato"
                )

    result = {
        "feedback_id": client_feedback_id(payload.get("feedback_id")) or new_feedback_id(),
        "request_fingerprint": request_fingerprint or feedback_request_fingerprint(payload),
        "submitted_at": now_iso(),
        "action": action,
        "base_revision": base_revision,
        "slides": normalized_slides,
        "comments": normalized_comments,
        "overall_note": text(
            payload.get("overall_note"), field="overall_note", limit=10_000
        ),
        "logo_mode": logo_mode,
        "cover_mode": cover_mode,
        "warnings": warnings,
    }
    if visual_style_system is not None:
        result["visual_style_system"] = visual_style_system
    if approved_render_fingerprint is not None:
        result["approval_stage"] = approval_stage
        result["base_workflow_state"] = base_workflow_state
        result["base_render_fingerprint"] = base_render_fingerprint
        result["render_fingerprint"] = approved_render_fingerprint
    if proof_slide_ids is not None:
        result["proof_slide_ids"] = proof_slide_ids
        result["style_system_verified"] = style_system_verified
        result["proof_browser"] = proof_browser
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    try:
        manifest_path = absolute_input_path(args.manifest)
        session_dir = absolute_input_path(args.session_dir)
        reject_symlink_path(manifest_path, field="Il manifest")
        reject_symlink_path(session_dir, field="La cartella di sessione")
        ensure_private_directory(session_dir)
    except (OSError, ValueError) as exc:
        print(
            json.dumps({"error": f"Impossibile preparare la sessione: {exc}"}),
            file=sys.stderr,
        )
        return 2
    assets_dir = Path(__file__).resolve().parent.parent / "assets" / "review-editor"
    index_path = assets_dir / "index.html"
    if not index_path.is_file():
        print(json.dumps({"error": f"Asset editor mancante: {index_path}"}), file=sys.stderr)
        return 2
    server_lock = InterprocessLock(session_dir / ".review-server.lock")
    manifest_server_lock = InterprocessLock(
        manifest_path.with_name(f".{manifest_path.name}.review-server.lock")
    )
    try:
        server_lock.acquire()
        manifest_server_lock.acquire()
    except (LockUnavailableError, OSError) as exc:
        manifest_server_lock.release()
        server_lock.release()
        print(
            json.dumps(
                {
                    "error": (
                        "La cartella di sessione o il manifest è già servito "
                        f"da un altro editor: {exc}"
                    )
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    state_path = session_dir / "session-state.json"
    feedback_path = session_dir / "feedback.json"
    journal_path = session_dir / "feedback-commit.json"
    transaction_lock_path = session_dir / ".review-transaction.lock"
    manifest_lock_path = manifest_path.with_name(f".{manifest_path.name}.review.lock")
    recovered_event = None
    try:
        startup_locks = [
            InterprocessLock(manifest_lock_path),
            InterprocessLock(transaction_lock_path),
        ]
        try:
            for lock in startup_locks:
                lock.acquire()
            initial_model = manifest_model(manifest_path)
            if path_entry_exists(state_path):
                state = read_private_json(state_path)
                validate_state_manifest(state, manifest_path)
                token = valid_session_token(state.get("token")) or secrets.token_urlsafe(24)
            else:
                token = secrets.token_urlsafe(24)
                state = {"manifest": str(manifest_path)}
            # Recovery must observe exactly the pre-commit state recorded in the
            # journal. Updating revision/start metadata first can make a valid
            # interrupted commit look like unrelated state corruption.
            if path_entry_exists(state_path):
                recovered_event = recover_feedback_commit(
                    journal_path=journal_path,
                    feedback_path=feedback_path,
                    state_path=state_path,
                    manifest_path=manifest_path,
                )
                state = read_private_json(state_path)
            state.update(
                {
                    "token": token,
                    "manifest": str(manifest_path),
                    "manifest_revision": initial_model["revision"],
                    "server_started_at": now_iso(),
                }
            )
            atomic_write_json(state_path, state)
            if recovered_event is None:
                current_state = read_private_json(state_path)
                last_feedback_id = current_state.get("last_feedback_id")
                applied_feedback_id = current_state.get("applied_feedback_id")
                if last_feedback_id:
                    safe_feedback_id(last_feedback_id)
                    archive_path = feedback_archive_path(session_dir, last_feedback_id)
                    persisted_feedback = None
                    for candidate in (archive_path, feedback_path):
                        if not path_entry_exists(candidate):
                            continue
                        candidate_feedback = read_private_json(candidate)
                        if candidate_feedback.get("feedback_id") == last_feedback_id:
                            persisted_feedback = candidate_feedback
                            break
                    if persisted_feedback is None:
                        raise ValueError("Il batch indicato dallo stato della sessione non è disponibile")
                    persisted_action = persisted_feedback.get("action")
                    if (
                        not isinstance(persisted_action, str)
                        or persisted_action not in {"feedback", "approve"}
                    ):
                        raise ValueError("Il feedback persistito contiene un'azione non valida")
                    append_only_json(archive_path, persisted_feedback)
                    state_changed = False
                    if current_state.get("last_feedback_path") != str(archive_path):
                        current_state["last_feedback_path"] = str(archive_path)
                        state_changed = True
                    stored_action = current_state.get("last_action")
                    if stored_action is None:
                        current_state["last_action"] = persisted_feedback["action"]
                        state_changed = True
                    elif stored_action != persisted_feedback["action"]:
                        raise ValueError(
                            "last_action non coincide con l'azione del feedback persistito"
                        )
                    if state_changed:
                        atomic_write_json(state_path, current_state)
                    # feedback.json is the durable alias consumed by retries
                    # and tools. Restore it even for an already-applied batch.
                    atomic_write_json(feedback_path, persisted_feedback)
                    if last_feedback_id != applied_feedback_id:
                        recovered_event = feedback_event(feedback_path, persisted_feedback)
        finally:
            for lock in reversed(locals().get("startup_locks", [])):
                lock.release()
    except (KeyError, LockUnavailableError, OSError, TypeError, ValueError) as exc:
        manifest_server_lock.release()
        server_lock.release()
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    submit_lock = threading.Lock()

    def live_session_snapshot(*, include_model: bool) -> dict:
        """Read manifest and durable feedback state under the shared lock order."""
        locks = [
            InterprocessLock(manifest_lock_path),
            InterprocessLock(transaction_lock_path),
        ]
        with submit_lock:
            try:
                for lock in locks:
                    lock.acquire()
                current_state = read_private_json(state_path)
                validate_state_manifest(current_state, manifest_path)
                value = (
                    manifest_model(manifest_path)
                    if include_model
                    else manifest_status(manifest_path)
                )
                last_id = current_state.get("last_feedback_id")
                applied_id = current_state.get("applied_feedback_id")
                return {
                    **value,
                    "last_feedback_id": last_id,
                    "last_action": current_state.get("last_action"),
                    "applied_feedback_id": applied_id,
                    "feedback_pending": bool(last_id and last_id != applied_id),
                }
            finally:
                for lock in reversed(locks):
                    lock.release()

    class Handler(BaseHTTPRequestHandler):
        server_version = "CarouselReviewLab/0.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_bytes(
            self,
            status: int,
            body: bytes,
            content_type: str,
            *,
            cache_control: str = "no-store",
            etag: str | None = None,
        ) -> None:
            if etag is not None and self.headers.get("If-None-Match") == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("Cache-Control", cache_control)
                self.send_header("ETag", etag)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            if etag is not None:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, value: dict) -> None:
            self.send_bytes(
                status,
                strict_json_text(value).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def authorized(self, query: dict[str, list[str]]) -> bool:
            candidate = query.get("token", [""])[0]
            return secrets.compare_digest(candidate, token)

        def local_host(self) -> bool:
            """Rifiuta le richieste che non nominano l'indirizzo locale.

            Un sito remoto può far risolvere il proprio dominio su 127.0.0.1 e
            diventare così same-origin rispetto a questo server. Il token resta
            la difesa principale, ma il controllo dell'header Host chiude il
            caso senza costi.
            """
            host = self.headers.get("Host", "")
            name = host.rsplit(":", 1)[0].strip("[]") if host else ""
            return name in {"127.0.0.1", "localhost", "::1"}

        def do_GET(self) -> None:  # noqa: N802
            if not self.local_host():
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Host non consentito"})
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/":
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                self.send_bytes(
                    HTTPStatus.OK,
                    index_path.read_bytes(),
                    "text/html; charset=utf-8",
                )
                return
            # Gli asset sono file statici della skill, privi di dati di
            # sessione: restano leggibili senza token perché index.html li
            # referenzia staticamente.
            static_assets = {
                "/assets/styles.css": (assets_dir / "styles.css", "text/css; charset=utf-8"),
                "/assets/app.js": (assets_dir / "app.js", "text/javascript; charset=utf-8"),
                "/styles.css": (assets_dir / "styles.css", "text/css; charset=utf-8"),
                "/app.js": (assets_dir / "app.js", "text/javascript; charset=utf-8"),
                "/assets/vincos-lockup-white.svg": (
                    assets_dir / "vincos-lockup-white.svg",
                    "image/svg+xml; charset=utf-8",
                ),
                "/assets/fonts/Inter-Variable.ttf": (
                    BUNDLED_FONT_ASSETS["display"][1],
                    "font/ttf",
                ),
                "/assets/fonts/PlayfairDisplay-Variable.ttf": (
                    assets_dir.parent / "fonts" / "PlayfairDisplay-Variable.ttf",
                    "font/ttf",
                ),
                "/assets/fonts/PlayfairDisplay-Italic-Variable.ttf": (
                    BUNDLED_FONT_ASSETS["serif"][1],
                    "font/ttf",
                ),
                "/assets/fonts/InstrumentSerif-Regular.ttf": (
                    assets_dir.parent / "fonts" / "InstrumentSerif-Regular.ttf",
                    "font/ttf",
                ),
                "/assets/fonts/Onest-Regular.ttf": (
                    assets_dir.parent / "fonts" / "Onest-Regular.ttf",
                    "font/ttf",
                ),
                "/assets/fonts/Onest-Medium.ttf": (
                    assets_dir.parent / "fonts" / "Onest-Medium.ttf",
                    "font/ttf",
                ),
                "/assets/fonts/Onest-Semibold.ttf": (
                    assets_dir.parent / "fonts" / "Onest-Semibold.ttf",
                    "font/ttf",
                ),
                "/assets/fonts/Onest-Bold.ttf": (
                    assets_dir.parent / "fonts" / "Onest-Bold.ttf",
                    "font/ttf",
                ),
                "/assets/fonts/Orbitron-Variable.ttf": (
                    assets_dir.parent / "fonts" / "Orbitron-Variable.ttf",
                    "font/ttf",
                ),
            }
            static_asset = static_assets.get(parsed.path)
            if static_asset is not None:
                asset_path, content_type = static_asset
                asset_name = asset_path.name
                try:
                    body = asset_path.read_bytes()
                except OSError:
                    self.send_json(
                        HTTPStatus.NOT_FOUND, {"error": f"Asset mancante: {asset_name}"}
                    )
                    return
                digest = hashlib.sha256(body).hexdigest()
                self.send_bytes(
                    HTTPStatus.OK,
                    body,
                    content_type,
                    cache_control="private, no-cache",
                    etag=f'"sha256-{digest}"',
                )
                return
            font_key = {
                "/api/font/display": "display",
                "/api/font/body": "body",
                "/api/font/sans": "sans",
                "/api/font/serif": "serif",
                "/api/font/italic": "italic",
            }.get(parsed.path)
            if font_key is not None:
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                try:
                    _, allowed_fonts = font_assets(read_json(manifest_path), manifest_path)
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                font_path = allowed_fonts.get(font_key)
                if font_path is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Font non disponibile"})
                    return
                try:
                    body = font_path.read_bytes()
                except OSError:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Font non disponibile"})
                    return
                self.send_bytes(
                    HTTPStatus.OK,
                    body,
                    FONT_MIME_TYPES[font_path.suffix.lower()],
                )
                return
            if parsed.path == "/api/cover-image":
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                try:
                    _, image_path = cover_image_asset(read_json(manifest_path), manifest_path)
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                if image_path is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Immagine non disponibile"})
                    return
                try:
                    body = image_path.read_bytes()
                except OSError:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Immagine non disponibile"})
                    return
                self.send_bytes(
                    HTTPStatus.OK,
                    body,
                    IMAGE_MIME_TYPES[image_path.suffix.lower()],
                )
                return
            logo_key = {
                "/api/logo/on-light": "on_light",
                "/api/logo/on-dark": "on_dark",
            }.get(parsed.path)
            if logo_key is not None:
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                try:
                    _, allowed_logos = logo_assets(read_json(manifest_path), manifest_path)
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                logo_path = allowed_logos.get(logo_key)
                if logo_path is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Logo non disponibile"})
                    return
                try:
                    body = logo_path.read_bytes()
                except OSError:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Logo non disponibile"})
                    return
                self.send_bytes(
                    HTTPStatus.OK,
                    body,
                    IMAGE_MIME_TYPES[logo_path.suffix.lower()],
                )
                return
            if parsed.path == "/api/session":
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                try:
                    model = live_session_snapshot(include_model=True)
                except LockUnavailableError as exc:
                    self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                except OSError as exc:
                    self.send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": f"Impossibile leggere la sessione: {exc}"},
                    )
                    return
                self.send_json(HTTPStatus.OK, model)
                return
            if parsed.path == "/api/status":
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                try:
                    current_manifest_status = live_session_snapshot(
                        include_model=False
                    )
                except LockUnavailableError as exc:
                    self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                except OSError as exc:
                    self.send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": f"Impossibile leggere lo stato della sessione: {exc}"},
                    )
                    return
                self.send_json(HTTPStatus.OK, current_manifest_status)
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Risorsa non trovata"})

        def do_POST(self) -> None:  # noqa: N802
            if not self.local_host():
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Host non consentito"})
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/api/submit":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Risorsa non trovata"})
                return
            if not self.authorized(query):
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                return
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";")[0].strip().casefold() != "application/json":
                self.send_json(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    {"error": "Il batch deve essere inviato come application/json"},
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Batch non valido o troppo grande"})
                return
            body = self.rfile.read(length)
            # Il server è multi-thread: senza lock due invii ravvicinati possono
            # superare entrambi il controllo sul batch in attesa e sovrascrivere
            # feedback.json a vicenda.
            with submit_lock:
                pending_event = None
                event = None
                pending_feedback_id = None
                idempotent_replay = False
                try:
                    payload = strict_json_loads(body.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("Il batch deve essere un oggetto JSON")
                    requested_feedback_id = client_feedback_id(payload.get("feedback_id"))
                    request_fingerprint = feedback_request_fingerprint(payload)
                    with InterprocessLock(transaction_lock_path):
                        pending_event = recover_feedback_commit(
                            journal_path=journal_path,
                            feedback_path=feedback_path,
                            state_path=state_path,
                            manifest_path=manifest_path,
                        )
                        current_state = read_private_json(state_path)
                        validate_state_manifest(current_state, manifest_path)
                        last_feedback_id = current_state.get("last_feedback_id")
                        applied_feedback_id = current_state.get("applied_feedback_id")
                        archived_feedback = None
                        if requested_feedback_id is not None:
                            requested_archive = feedback_archive_path(
                                session_dir, requested_feedback_id
                            )
                            if path_entry_exists(requested_archive):
                                archived_feedback = read_private_json(requested_archive)
                                if (
                                    archived_feedback.get("feedback_id") != requested_feedback_id
                                    or archived_feedback.get("request_fingerprint")
                                    != request_fingerprint
                                ):
                                    raise IdempotencyConflictError(
                                        "feedback_id già usato per un batch diverso"
                                    )
                                event = feedback_event(feedback_path, archived_feedback)
                                idempotent_replay = True
                        if event is not None:
                            pass
                        elif last_feedback_id and last_feedback_id != applied_feedback_id:
                            pending_feedback_id = last_feedback_id
                        else:
                            current_model = manifest_model(
                                manifest_path, include_internal=True
                            )
                            feedback = validate_feedback(
                                payload,
                                current_model,
                                request_fingerprint=request_fingerprint,
                            )
                            event = commit_feedback(
                                journal_path=journal_path,
                                feedback_path=feedback_path,
                                state_path=state_path,
                                manifest_path=manifest_path,
                                current_state=current_state,
                                feedback=feedback,
                                manifest_revision=current_model["revision"],
                            )
                except LockUnavailableError as exc:
                    self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (IdempotencyConflictError, RuntimeError) as exc:
                    self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                except OSError as exc:
                    self.send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": f"Impossibile salvare il feedback: {exc}"},
                    )
                    return
                if pending_event is not None:
                    emit_event(pending_event)
                    try:
                        journal_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                if pending_feedback_id is not None:
                    self.send_json(
                        HTTPStatus.CONFLICT,
                        {
                            "error": "Il feedback precedente attende ancora di essere applicato",
                            "feedback_id": pending_feedback_id,
                        },
                    )
                    return
                if event is None:
                    self.send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "Il feedback non è stato registrato"},
                    )
                    return
                if not idempotent_replay:
                    emit_event(event)
                try:
                    journal_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.send_json(HTTPStatus.OK, event)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        manifest_server_lock.release()
        server_lock.release()
        print(
            json.dumps(
                {"error": f"Impossibile avviare il server: {exc}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?token={token}"
    emit_event(
        {
            "status": "ready",
            "url": url,
            "session_dir": str(session_dir),
            "manifest": str(manifest_path),
        }
    )
    if recovered_event is not None:
        emit_event(recovered_event)
        try:
            journal_path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manifest_server_lock.release()
        server_lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Serve a local, dependency-free editorial review session for a carousel manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if os.name == "nt":
    import msvcrt
else:
    import fcntl


MAX_BODY_BYTES = 1_000_000
MAX_SLIDES = 50
MAX_COMMENTS = 200
MAX_TEXT = 20_000
EDITOR_VERSION = "2.8.7"
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
EMPHASIS_MAX_PER_ROLE = 2
LOGO_MODES = {"auto", "hidden"}
VISUAL_STYLE_SYSTEMS = {
    "editorial-frame": "Editoriale",
    "editorial-halftone": "Geometrico",
    "corporate-modular": "Istituzionale",
}
VISUAL_STYLE_ALIASES = {
    "editorial": "editorial-frame",
    "editorial_frame": "editorial-frame",
    "editorialframe": "editorial-frame",
    "halftone": "editorial-halftone",
    "editorial_halftone": "editorial-halftone",
    "campo-cromatico": "editorial-halftone",
    "campo_cromatico": "editorial-halftone",
    "color-field": "editorial-halftone",
    "costellazione": "editorial-halftone",
    "constellation": "editorial-halftone",
    "geometrico": "editorial-halftone",
    "geometric": "editorial-halftone",
    "corporate": "corporate-modular",
    "corporate_modular": "corporate-modular",
    "modulare-quieto": "corporate-modular",
    "modulare_quieto": "corporate-modular",
    "quiet-modular": "corporate-modular",
    "istituzionale": "corporate-modular",
    "institutional": "corporate-modular",
}
SENTENCE_BREAK_ABBREVIATIONS = {
    "ca", "cfr", "dott", "ecc", "es", "n", "pag", "pp", "prof", "sig", "sigg", "vs"
}
SENTENCE_BREAK_RE = re.compile(r'\.(?!\d)([”’"\')\]]*)[ \t]+(?=[A-ZÀÈÉÌÒÙ])')


class LockUnavailableError(RuntimeError):
    """Raised when another process owns a non-blocking review lock."""


class InterprocessLock:
    """Cross-platform, non-blocking advisory lock backed by a persistent file."""

    def __init__(self, path: Path):
        self.path = path
        self._stream = None

    def acquire(self) -> "InterprocessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise LockUnavailableError(f"Risorsa già in uso: {self.path}") from exc
        self._stream = stream
        return self

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
            self._stream = None

    def __enter__(self) -> "InterprocessLock":
        return self.acquire()

    def __exit__(self, *_args: object) -> None:
        self.release()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File non trovato: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON non valido in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Il contenuto di {path} deve essere un oggetto JSON")
    return value


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


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
    return {
        "event": "feedback",
        "feedback_id": feedback["feedback_id"],
        "action": feedback["action"],
        "path": str(feedback_path),
    }


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
    state_before = {
        key: current_state.get(key)
        for key in ("last_feedback_id", "applied_feedback_id", "manifest_revision")
    }
    state_patch = {
        "last_feedback_id": feedback["feedback_id"],
        "feedback_submitted_at": feedback["submitted_at"],
        "manifest_revision": manifest_revision,
    }
    journal = {
        "version": 1,
        "manifest": str(manifest_path),
        "feedback": feedback,
        "state_before": state_before,
        "state_patch": state_patch,
    }
    atomic_write_json(journal_path, journal)
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
    if not journal_path.exists():
        return None
    journal = read_json(journal_path)
    if journal.get("version") != 1 or not isinstance(journal.get("manifest"), str):
        raise ValueError("Journal feedback non valido")
    if not same_path(journal["manifest"], manifest_path):
        raise ValueError("Il journal feedback appartiene a un manifest diverso")
    feedback = journal.get("feedback")
    state_before = journal.get("state_before")
    state_patch = journal.get("state_patch")
    if not all(isinstance(value, dict) for value in (feedback, state_before, state_patch)):
        raise ValueError("Journal feedback incompleto")
    feedback_id = feedback.get("feedback_id")
    if (
        not isinstance(feedback_id, str)
        or not feedback_id
        or feedback.get("action") not in {"feedback", "approve"}
        or not isinstance(feedback.get("submitted_at"), str)
        or state_patch.get("last_feedback_id") != feedback_id
        or state_patch.get("feedback_submitted_at") != feedback.get("submitted_at")
        or not isinstance(state_patch.get("manifest_revision"), int)
    ):
        raise ValueError("Journal feedback incoerente")

    current_state = read_json(state_path)
    validate_state_manifest(current_state, manifest_path)
    if current_state.get("applied_feedback_id") == feedback_id:
        try:
            journal_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    for key, before_value in state_before.items():
        after_value = state_patch.get(key, before_value)
        if current_state.get(key) not in (before_value, after_value):
            raise ValueError("Lo stato è cambiato dopo l'inizio del commit feedback")

    atomic_write_json(feedback_path, feedback)
    next_state = dict(current_state)
    next_state.update(state_patch)
    atomic_write_json(state_path, next_state)
    return feedback_event(feedback_path, feedback)


def text(value: object, *, field: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} deve essere una stringa")
    if len(value) > limit:
        raise ValueError(f"{field} supera il limite di {limit} caratteri")
    return value


def sentence_line_breaks(value: str) -> str:
    """Put each clearly complete sentence on a new line.

    Decimal/version dots such as ``1.2`` never match. A short allowlist avoids
    treating common Italian abbreviations as sentence endings.
    """
    def replace(match: re.Match[str]) -> str:
        prefix = value[: match.start()]
        token = re.search(r"([A-Za-zÀ-ÿ]+)$", prefix)
        if token and token.group(1).casefold() in SENTENCE_BREAK_ABBREVIATIONS:
            return match.group(0)
        return "." + match.group(1) + "\n"

    return SENTENCE_BREAK_RE.sub(replace, value)


def stable_items(manifest: dict) -> list[dict]:
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Il manifest deve contenere almeno una slide in items")
    seen: set[str] = set()
    result: list[dict] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index - 1}] deve essere un oggetto")
        item_id = item.get("id") or f"item-{index}"
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise ValueError("Ogni slide deve avere un ID stabile e univoco")
        seen.add(item_id)
        result.append({**item, "id": item_id})
    return result


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
    """Keep at most two exact, non-empty phrases contained in their text."""
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
            if len(result) == 2:
                break
    return result


def validate_emphasis_values(value: object, content: str, *, field: str) -> list[str]:
    """Validate exact, unambiguous selections made by the review editor."""
    if not isinstance(value, list):
        raise ValueError(f"{field} deve essere una lista")
    if len(value) > EMPHASIS_MAX_PER_ROLE:
        raise ValueError(f"{field} può contenere al massimo {EMPHASIS_MAX_PER_ROLE} enfasi")
    result: list[str] = []
    for index, phrase in enumerate(value):
        if not isinstance(phrase, str) or not phrase:
            raise ValueError(f"{field}[{index}] deve essere una frase non vuota")
        if phrase in result:
            raise ValueError(f"{field} contiene un valore non univoco: {phrase!r}")
        if content.count(phrase) != 1:
            raise ValueError(
                f"{field}[{index}] deve comparire una sola volta nel testo della card"
            )
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


def normalized_logo_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    mode = value.strip().casefold()
    return mode if mode in LOGO_MODES else None


def normalized_visual_style_system(value: object) -> str | None:
    """Return a canonical visual system, accepting a few legacy spellings."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    normalized = VISUAL_STYLE_ALIASES.get(normalized, normalized)
    return normalized if normalized in VISUAL_STYLE_SYSTEMS else None


def resolved_visual_style_system(manifest: dict) -> str:
    """Resolve a carousel override before the brand default, then a safe default."""
    selected = normalized_visual_style_system(manifest.get("visual_style_system"))
    if selected is not None:
        return selected
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    signature = (
        brand.get("visual_signature")
        if isinstance(brand.get("visual_signature"), dict)
        else {}
    )
    for candidate in (
        signature.get("style_system"),
        brand.get("visual_style_system"),
        brand.get("style_system"),
    ):
        selected = normalized_visual_style_system(candidate)
        if selected is not None:
            return selected
    return "editorial-frame"


def normalized_cover_mode(manifest: dict, cover_visual: dict) -> str:
    """Expose the intended cover mode before approval and an executable one after."""
    raw_mode = manifest.get("cover_mode")
    if not isinstance(raw_mode, str):
        legacy_mode = manifest.get("cover_visual_mode")
        if legacy_mode == "generative":
            raw_mode = "generated"
        elif legacy_mode == "technical":
            raw_mode = "provided"
    if raw_mode not in {"generated", "provided", "typographic"}:
        raw_mode = "provided" if cover_visual["available"] else "typographic"
    if raw_mode == "generated" and not cover_visual["available"]:
        if manifest.get("workflow_state", "bozza") in {
            "bozza", "draft", "in_revisione", "in_revisione_editoriale", "in_review", "feedback"
        }:
            return "generated"
        return "typographic"
    if raw_mode == "provided" and not cover_visual["available"]:
        return "typographic"
    return raw_mode


def visual_proofs(
    manifest: dict,
    *,
    brand: dict,
    typography: dict,
    cover_visual: dict,
) -> dict:
    """Describe three renderable proof directions sharing one visual identity."""
    cover = {**cover_visual, "mode": normalized_cover_mode(manifest, cover_visual)}
    return {
        "selected_style_system": resolved_visual_style_system(manifest),
        "identity": {
            "brand": brand,
            "typography": typography,
            "cover": cover,
        },
        "options": [
            {"id": style_system, "label": label, "style_system": style_system}
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


def manifest_model(manifest_path: Path) -> dict:
    manifest = read_json(manifest_path)
    revision = manifest.get("revision", 1)
    if not isinstance(revision, int) or revision < 0:
        raise ValueError("revision deve essere un intero non negativo")

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
    for index, item in enumerate(stable_items(manifest), start=2):
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

    outro = manifest.get("outro") if isinstance(manifest.get("outro"), dict) else {}
    if outro.get("enabled", False):
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

    sequence_mode = manifest.get("sequence_mode", "narrative")
    if sequence_mode not in {"narrative", "sectional"}:
        sequence_mode = "narrative"
    format_data = manifest.get("format") if isinstance(manifest.get("format"), dict) else {}
    cover_visual, _ = cover_image_asset(manifest, manifest_path)
    cover_visual["mode"] = normalized_cover_mode(manifest, cover_visual)
    typography = normalize_typography(manifest)
    brand = brand_summary(manifest, manifest_path)
    return {
        "editor_version": EDITOR_VERSION,
        "revision": revision,
        "workflow_state": manifest.get("workflow_state", "bozza"),
        "sequence_mode": sequence_mode,
        "source_type": manifest.get("source_type", "notes"),
        "format": {
            "ratio": format_data.get("ratio", "4:5"),
            "master_width": format_data.get("master_width", 1080),
            "master_height": format_data.get("master_height", 1350),
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
        "slides": slides,
    }


def validate_feedback(payload: object, model: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Il batch deve essere un oggetto JSON")
    action = payload.get("action")
    if action not in {"feedback", "approve"}:
        raise ValueError("action deve essere feedback oppure approve")
    base_revision = payload.get("base_revision")
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
        if slide_id not in source_by_id or slide_id in seen:
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

        if source["kind"] == "item" and summary:
            italic_count = len(emphasis["summary_italic"]) + len(emphasis["summary_serif"])
            secondary_count = (
                italic_count
                + len(emphasis["summary_accent"])
                + len(emphasis["summary_underline"])
            )
            if action == "approve":
                if secondary_count > 1:
                    raise ValueError(
                        f"{slide_id} può usare un solo trattamento tra corsivo, sottolineatura ed evidenziatore prima dell'approvazione"
                    )
            else:
                if secondary_count > 1:
                    warnings.append(
                        f"{slide_id}: in approvazione sarà ammesso un solo trattamento tra corsivo, sottolineatura ed evidenziatore"
                    )
        normalized_slides.append(
            {
                "id": slide_id,
                "kind": source["kind"],
                "title": title,
                "summary": summary,
                **emphasis,
            }
        )

    if normalized_slides[0]["id"] != "cover":
        raise ValueError("La copertina deve restare la prima slide")
    if "outro" in source_by_id and normalized_slides[-1]["id"] != "outro":
        raise ValueError("La chiusura deve restare l'ultima slide")
    if item_count < 1:
        raise ValueError("Deve restare almeno una slide interna")

    comments = payload.get("comments", [])
    if not isinstance(comments, list) or len(comments) > MAX_COMMENTS:
        raise ValueError(f"comments deve contenere al massimo {MAX_COMMENTS} elementi")
    normalized_comments: list[dict] = []
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict):
            raise ValueError(f"comments[{index}] deve essere un oggetto")
        kind = comment.get("kind")
        if kind not in {"selection", "slide", "brand"}:
            raise ValueError(f"Tipo di commento non valido: {kind}")
        slide_id = comment.get("slide_id", "")
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

    result = {
        "feedback_id": f"feedback-{secrets.token_hex(8)}",
        "submitted_at": now_iso(),
        "action": action,
        "base_revision": base_revision,
        "slides": normalized_slides,
        "comments": normalized_comments,
        "overall_note": text(
            payload.get("overall_note"), field="overall_note", limit=10_000
        ),
        "logo_mode": logo_mode,
        "warnings": warnings,
    }
    if visual_style_system is not None:
        result["visual_style_system"] = visual_style_system
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    try:
        manifest_path = args.manifest.expanduser().resolve()
        session_dir = args.session_dir.expanduser().resolve()
        session_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
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
    try:
        server_lock.acquire()
    except (LockUnavailableError, OSError) as exc:
        print(
            json.dumps(
                {"error": f"La cartella di sessione è già in uso: {exc}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    state_path = session_dir / "session-state.json"
    feedback_path = session_dir / "feedback.json"
    journal_path = session_dir / "feedback-commit.json"
    transaction_lock_path = session_dir / ".review-transaction.lock"
    recovered_event = None
    try:
        initial_model = manifest_model(manifest_path)
        if state_path.exists():
            state = read_json(state_path)
            validate_state_manifest(state, manifest_path)
            token = (
                state.get("token")
                if isinstance(state.get("token"), str)
                else secrets.token_urlsafe(24)
            )
        else:
            token = secrets.token_urlsafe(24)
            state = {"manifest": str(manifest_path)}
        state.update(
            {
                "token": token,
                "manifest": str(manifest_path),
                "manifest_revision": initial_model["revision"],
                "server_started_at": now_iso(),
            }
        )
        atomic_write_json(state_path, state)
        with InterprocessLock(transaction_lock_path):
            recovered_event = recover_feedback_commit(
                journal_path=journal_path,
                feedback_path=feedback_path,
                state_path=state_path,
                manifest_path=manifest_path,
            )
            if recovered_event is None:
                current_state = read_json(state_path)
                last_feedback_id = current_state.get("last_feedback_id")
                applied_feedback_id = current_state.get("applied_feedback_id")
                if last_feedback_id and last_feedback_id != applied_feedback_id:
                    pending_feedback = read_json(feedback_path)
                    if (
                        pending_feedback.get("feedback_id") != last_feedback_id
                        or pending_feedback.get("action") not in {"feedback", "approve"}
                    ):
                        raise ValueError(
                            "Il feedback pendente non coincide con lo stato della sessione"
                        )
                    recovered_event = feedback_event(feedback_path, pending_feedback)
    except (KeyError, LockUnavailableError, OSError, TypeError, ValueError) as exc:
        server_lock.release()
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    submit_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "CarouselReviewLab/0.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
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
                json.dumps(value, ensure_ascii=False).encode("utf-8"),
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
                self.send_bytes(HTTPStatus.OK, body, content_type)
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
                    model = manifest_model(manifest_path)
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                self.send_json(HTTPStatus.OK, model)
                return
            if parsed.path == "/api/status":
                if not self.authorized(query):
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Sessione non autorizzata"})
                    return
                try:
                    current_state = read_json(state_path)
                    validate_state_manifest(current_state, manifest_path)
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                try:
                    revision = manifest_model(manifest_path)["revision"]
                except ValueError:
                    revision = current_state.get("manifest_revision")
                last_id = current_state.get("last_feedback_id")
                applied_id = current_state.get("applied_feedback_id")
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "manifest_revision": revision,
                        "last_feedback_id": last_id,
                        "applied_feedback_id": applied_id,
                        "feedback_pending": bool(last_id and last_id != applied_id),
                    },
                )
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
            if content_type and content_type.split(";")[0].strip() != "application/json":
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
                try:
                    with InterprocessLock(transaction_lock_path):
                        pending_event = recover_feedback_commit(
                            journal_path=journal_path,
                            feedback_path=feedback_path,
                            state_path=state_path,
                            manifest_path=manifest_path,
                        )
                        current_state = read_json(state_path)
                        validate_state_manifest(current_state, manifest_path)
                        last_feedback_id = current_state.get("last_feedback_id")
                        applied_feedback_id = current_state.get("applied_feedback_id")
                        if last_feedback_id and last_feedback_id != applied_feedback_id:
                            pending_feedback_id = last_feedback_id
                        else:
                            payload = json.loads(body.decode("utf-8"))
                            current_model = manifest_model(manifest_path)
                            feedback = validate_feedback(payload, current_model)
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
                except RuntimeError as exc:
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
                    print(json.dumps(pending_event, ensure_ascii=False), flush=True)
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
                print(json.dumps(event, ensure_ascii=False), flush=True)
                try:
                    journal_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.send_json(HTTPStatus.OK, event)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
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
    print(
        json.dumps(
            {
                "status": "ready",
                "url": url,
                "session_dir": str(session_dir),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if recovered_event is not None:
        print(json.dumps(recovered_event, ensure_ascii=False), flush=True)
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
        server_lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

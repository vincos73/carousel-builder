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


MAX_BODY_BYTES = 1_000_000
MAX_SLIDES = 50
MAX_COMMENTS = 200
MAX_TEXT = 20_000
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
    "sans": ("Inter", Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Inter-Variable.ttf"),
    "serif": (
        "Playfair Display",
        Path(__file__).resolve().parent.parent / "assets" / "fonts" / "PlayfairDisplay-Italic-Variable.ttf",
    ),
}
SENTENCE_BREAK_ABBREVIATIONS = {
    "ca", "cfr", "dott", "ecc", "es", "n", "pag", "pp", "prof", "sig", "sigg", "vs"
}
SENTENCE_BREAK_RE = re.compile(r'\.(?!\d)([”’"\')\]]*)[ \t]+(?=[A-ZÀÈÉÌÒÙ])')


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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


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


def _font_asset(manifest: dict, manifest_path: Path, key: str) -> tuple[dict, Path | None]:
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}
    configured = fonts.get(key)
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


def font_assets(manifest: dict, manifest_path: Path) -> tuple[dict, dict[str, Path]]:
    """Build public font metadata and the private, manifest-resolved allowlist."""
    public: dict = {}
    allowed: dict[str, Path] = {}
    for key in ("sans", "serif"):
        entry, resolved = _font_asset(manifest, manifest_path, key)
        public[key] = entry
        if resolved is not None:
            allowed[key] = resolved
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


def brand_summary(manifest: dict, manifest_path: Path | None = None) -> dict:
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    palette = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}

    def font_name(key: str) -> str:
        value = fonts.get(key)
        if isinstance(value, dict):
            return _short_string(value.get("family"))
        return _short_string(value)

    asset_metadata = {
        "sans": {"family": font_name("sans"), "source": "fallback", "available": False, "endpoint": ""},
        "serif": {"family": font_name("serif"), "source": "fallback", "available": False, "endpoint": ""},
    }
    if manifest_path is not None:
        asset_metadata, _ = font_assets(manifest, manifest_path)

    return {
        "name": text(brand.get("name"), field="brand.name", limit=300),
        "website": text(brand.get("website"), field="brand.website", limit=500),
        "signature": text(brand.get("signature"), field="brand.signature", limit=300),
        "sans": font_name("sans"),
        "serif": font_name("serif"),
        "font_assets": asset_metadata,
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
            "title_accent": validated_emphasis(
                manifest.get("cover_title_accent"), text(manifest.get("cover_title"), field="cover_title")
            ),
            "summary_serif": [],
            "summary_accent": [],
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
                "title_accent": validated_emphasis(
                    item.get("title_accent"), text(item.get("title"), field=f"{item['id']}.title")
                ),
                "summary_serif": validated_emphasis(
                    item.get("summary_serif"), text(item.get("summary"), field=f"{item['id']}.summary")
                ),
                "summary_accent": validated_emphasis(
                    item.get("summary_accent"), text(item.get("summary"), field=f"{item['id']}.summary")
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
                "title_accent": validated_emphasis(
                    outro.get("title_accent"), text(outro.get("title"), field="outro.title")
                ),
                "summary_serif": validated_emphasis(
                    outro.get("summary_serif"), text(outro.get("body"), field="outro.body")
                ),
                "summary_accent": validated_emphasis(
                    outro.get("summary_accent"), text(outro.get("body"), field="outro.body")
                ),
                "deletable": False,
            }
        )

    sequence_mode = manifest.get("sequence_mode", "narrative")
    if sequence_mode not in {"narrative", "sectional"}:
        sequence_mode = "narrative"
    format_data = manifest.get("format") if isinstance(manifest.get("format"), dict) else {}
    cover_visual, _ = cover_image_asset(manifest, manifest_path)
    return {
        "revision": revision,
        "workflow_state": manifest.get("workflow_state", "bozza"),
        "sequence_mode": sequence_mode,
        "source_type": manifest.get("source_type", "notes"),
        "format": {
            "ratio": format_data.get("ratio", "4:5"),
            "master_width": format_data.get("master_width", 1080),
            "master_height": format_data.get("master_height", 1350),
        },
        "typography": normalize_typography(manifest),
        "brand": brand_summary(manifest, manifest_path),
        "cover_visual": cover_visual,
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
        normalized_slides.append(
            {
                "id": slide_id,
                "kind": source["kind"],
                "title": text(slide.get("title"), field=f"slides[{position}].title"),
                "summary": sentence_line_breaks(
                    text(slide.get("summary"), field=f"slides[{position}].summary")
                ),
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

    return {
        "feedback_id": f"feedback-{secrets.token_hex(8)}",
        "submitted_at": now_iso(),
        "action": action,
        "base_revision": base_revision,
        "slides": normalized_slides,
        "comments": normalized_comments,
        "overall_note": text(
            payload.get("overall_note"), field="overall_note", limit=10_000
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    session_dir = args.session_dir.expanduser().resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(__file__).resolve().parent.parent / "assets" / "review-editor"
    index_path = assets_dir / "index.html"
    if not index_path.is_file():
        print(json.dumps({"error": f"Asset editor mancante: {index_path}"}), file=sys.stderr)
        return 2
    try:
        initial_model = manifest_model(manifest_path)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    state_path = session_dir / "session-state.json"
    feedback_path = session_dir / "feedback.json"
    if state_path.exists():
        state = read_json(state_path)
        token = state.get("token") if isinstance(state.get("token"), str) else secrets.token_urlsafe(24)
    else:
        token = secrets.token_urlsafe(24)
        state = {}
    state.update(
        {
            "token": token,
            "manifest": str(manifest_path),
            "manifest_revision": initial_model["revision"],
            "server_started_at": now_iso(),
        }
    )
    atomic_write_json(state_path, state)
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
                "/assets/fonts/Inter-Variable.ttf": (
                    BUNDLED_FONT_ASSETS["sans"][1],
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
                "/api/font/sans": "sans",
                "/api/font/serif": "serif",
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
                try:
                    current_state = read_json(state_path)
                except ValueError as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                last_feedback_id = current_state.get("last_feedback_id")
                applied_feedback_id = current_state.get("applied_feedback_id")
                if last_feedback_id and last_feedback_id != applied_feedback_id:
                    self.send_json(
                        HTTPStatus.CONFLICT,
                        {
                            "error": "Il feedback precedente attende ancora di essere applicato",
                            "feedback_id": last_feedback_id,
                        },
                    )
                    return
                try:
                    payload = json.loads(body.decode("utf-8"))
                    current_model = manifest_model(manifest_path)
                    feedback = validate_feedback(payload, current_model)
                except RuntimeError as exc:
                    self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
                    return
                atomic_write_json(feedback_path, feedback)
                current_state.update(
                    {
                        "last_feedback_id": feedback["feedback_id"],
                        "feedback_submitted_at": feedback["submitted_at"],
                        "manifest_revision": current_model["revision"],
                    }
                )
                atomic_write_json(state_path, current_state)
                event = {
                    "event": "feedback",
                    "feedback_id": feedback["feedback_id"],
                    "action": feedback["action"],
                    "path": str(feedback_path),
                }
                print(json.dumps(event, ensure_ascii=False), flush=True)
            self.send_json(HTTPStatus.OK, event)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
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
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

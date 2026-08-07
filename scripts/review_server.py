#!/usr/bin/env python3
"""Serve a local, dependency-free editorial review session for a carousel manifest."""

from __future__ import annotations

import argparse
import json
import os
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


def brand_summary(manifest: dict) -> dict:
    brand = manifest.get("brand") if isinstance(manifest.get("brand"), dict) else {}
    palette = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
    fonts = brand.get("fonts") if isinstance(brand.get("fonts"), dict) else {}

    def font_name(key: str) -> str:
        value = fonts.get(key)
        if isinstance(value, dict):
            return text(value.get("family"), field=f"brand.fonts.{key}.family", limit=200)
        return text(value, field=f"brand.fonts.{key}", limit=200)

    return {
        "name": text(brand.get("name"), field="brand.name", limit=300),
        "website": text(brand.get("website"), field="brand.website", limit=500),
        "signature": text(brand.get("signature"), field="brand.signature", limit=300),
        "sans": font_name("sans"),
        "serif": font_name("serif"),
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
            "summary": "",
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
                "summary": text(item.get("summary"), field=f"{item['id']}.summary"),
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
                "summary": text(outro.get("body"), field="outro.body"),
                "deletable": False,
            }
        )

    sequence_mode = manifest.get("sequence_mode", "narrative")
    if sequence_mode not in {"narrative", "sectional"}:
        sequence_mode = "narrative"
    format_data = manifest.get("format") if isinstance(manifest.get("format"), dict) else {}
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
        "brand": brand_summary(manifest),
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
                "summary": text(
                    slide.get("summary"), field=f"slides[{position}].summary"
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
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
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
            if parsed.path in {"/assets/styles.css", "/assets/app.js"}:
                asset_name = Path(parsed.path).name
                asset_path = assets_dir / asset_name
                content_type = (
                    "text/css; charset=utf-8"
                    if asset_name.endswith(".css")
                    else "text/javascript; charset=utf-8"
                )
                try:
                    body = asset_path.read_bytes()
                except OSError:
                    self.send_json(
                        HTTPStatus.NOT_FOUND, {"error": f"Asset mancante: {asset_name}"}
                    )
                    return
                self.send_bytes(HTTPStatus.OK, body, content_type)
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

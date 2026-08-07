#!/usr/bin/env python3
"""Apply direct editorial edits from a review batch to a carousel manifest."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


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
        raise ValueError(f"{path} deve contenere un oggetto JSON")
    return value


def atomic_write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} deve essere una stringa")
    if len(value) > 20_000:
        raise ValueError(f"{field} supera il limite consentito")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    feedback_path = args.feedback.expanduser().resolve()
    session_dir = args.session_dir.expanduser().resolve()
    state_path = session_dir / "session-state.json"

    try:
        manifest = read_json(manifest_path)
        feedback = read_json(feedback_path)
        state = read_json(state_path)
        revision = manifest.get("revision", 1)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("revision deve essere un intero non negativo")
        if feedback.get("base_revision") != revision:
            raise ValueError(
                f"Il batch parte dalla revisione {feedback.get('base_revision')}, ma il manifest è alla revisione {revision}"
            )
        if feedback.get("feedback_id") != state.get("last_feedback_id"):
            raise ValueError("Il batch non coincide con l'ultimo feedback della sessione")
        if feedback.get("feedback_id") == state.get("applied_feedback_id"):
            print(
                json.dumps(
                    {
                        "status": "already_applied",
                        "feedback_id": feedback["feedback_id"],
                        "manifest_revision": revision,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if feedback.get("action") not in {"feedback", "approve"}:
            raise ValueError("Azione del batch non valida")

        original_items = manifest.get("items")
        if not isinstance(original_items, list) or not original_items:
            raise ValueError("Il manifest deve contenere almeno una slide interna")
        by_id: dict[str, dict] = {}
        for index, item in enumerate(original_items, start=1):
            if not isinstance(item, dict):
                raise ValueError("Ogni elemento di items deve essere un oggetto")
            item_id = item.get("id") or f"item-{index}"
            if not isinstance(item_id, str) or not item_id or item_id in by_id:
                raise ValueError("Gli ID delle slide interne devono essere univoci")
            by_id[item_id] = {**item, "id": item_id}

        slides = feedback.get("slides")
        if not isinstance(slides, list):
            raise ValueError("Il batch non contiene slides valide")
        cover = next((slide for slide in slides if slide.get("id") == "cover"), None)
        if not isinstance(cover, dict):
            raise ValueError("La copertina manca dal batch")
        new_cover = require_text(cover.get("title"), "cover.title")

        new_items: list[dict] = []
        seen: set[str] = set()
        for slide in slides:
            if not isinstance(slide, dict) or slide.get("kind") != "item":
                continue
            item_id = slide.get("id")
            if item_id not in by_id or item_id in seen:
                raise ValueError(f"ID slide interna non valido o duplicato: {item_id}")
            seen.add(item_id)
            updated = dict(by_id[item_id])
            updated["title"] = require_text(slide.get("title"), f"{item_id}.title")
            updated["summary"] = require_text(slide.get("summary"), f"{item_id}.summary")
            new_items.append(updated)
        if not new_items:
            raise ValueError("Deve restare almeno una slide interna")

        new_outro = None
        if isinstance(manifest.get("outro"), dict) and manifest["outro"].get("enabled", False):
            outro_slide = next((slide for slide in slides if slide.get("id") == "outro"), None)
            if not isinstance(outro_slide, dict):
                raise ValueError("La chiusura manca dal batch")
            new_outro = dict(manifest["outro"])
            new_outro["title"] = require_text(outro_slide.get("title"), "outro.title")
            new_outro["body"] = require_text(outro_slide.get("summary"), "outro.body")

        changed: list[str] = []
        if manifest.get("cover_title", "") != new_cover:
            changed.append("cover_title")
        if original_items != new_items:
            changed.append("items")
        if new_outro is not None and manifest.get("outro") != new_outro:
            changed.append("outro")

        existing_review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
        review = dict(existing_review)
        review.update(
            {
                "mode": "visual",
                "last_feedback_id": feedback["feedback_id"],
                "last_action": feedback["action"],
                "approval_requested": feedback["action"] == "approve",
                "comments_pending": len(feedback.get("comments", [])),
                "updated_at": now_iso(),
            }
        )
        if changed or existing_review != review:
            backups_dir = session_dir / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            backup_name = f"manifest-r{revision}-{feedback['feedback_id']}.json"
            shutil.copy2(manifest_path, backups_dir / backup_name)
            if changed:
                manifest["cover_title"] = new_cover
                manifest["items"] = new_items
                if new_outro is not None:
                    manifest["outro"] = new_outro
                manifest["revision"] = revision + 1
            manifest["review"] = review
            atomic_write_json(manifest_path, manifest)

        applied_revision = manifest.get("revision", revision)
        state.update(
            {
                "applied_feedback_id": feedback["feedback_id"],
                "applied_at": now_iso(),
                "manifest_revision": applied_revision,
            }
        )
        atomic_write_json(state_path, state)
        result = {
            "status": "applied",
            "feedback_id": feedback["feedback_id"],
            "action": feedback["action"],
            "changed": changed,
            "manifest_revision": applied_revision,
            "comments": feedback.get("comments", []),
            "overall_note": feedback.get("overall_note", ""),
            "approval_requested": feedback["action"] == "approve",
            "workflow_state_changed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Utility condivise dai test degli script di revisione."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def base_manifest() -> dict:
    return {
        "schema_version": "1.1",
        "source_type": "article",
        "sequence_mode": "narrative",
        "workflow_state": "bozza",
        "revision": 1,
        "proof": {"slide_ids": ["cover", "item-2", "outro"], "approved": False},
        "format": {"ratio": "4:5", "master_width": 1080, "master_height": 1350},
        "cover_title": "La lezione e operativa",
        "cover_title_serif": ["e operativa"],
        "cover_alt_text": "Copertina con metafora",
        "brand": {},
        "items": [
            {
                "id": "item-1",
                "layout": "editorial",
                "title": "",
                "summary": "Prima frase.",
                "summary_serif": ["Prima frase."],
                "alt_text": "Alt originale 1",
            },
            {
                "id": "item-2",
                "layout": "editorial",
                "title": "",
                "summary": "Seconda frase.",
                "summary_accent": ["Seconda frase."],
                "alt_text": "Alt originale 2",
            },
        ],
        "outro": {
            "enabled": True,
            "title": "Chiusura",
            "body": "Corpo della chiusura.",
            "alt_text": "Alt chiusura",
        },
        "accessibility": {
            "reading_order": ["cover", "item-1", "item-2", "outro"],
            "transcript": "Trascrizione precedente",
        },
    }


def slide(slide_id: str, kind: str, title: str = "", summary: str = "") -> dict:
    return {"id": slide_id, "kind": kind, "title": title, "summary": summary}


def base_feedback(slides: list[dict], **overrides: object) -> dict:
    feedback = {
        "feedback_id": "feedback-test",
        "submitted_at": "2026-01-01T00:00:00+00:00",
        "action": "feedback",
        "base_revision": 1,
        "slides": slides,
        "comments": [],
        "overall_note": "",
    }
    feedback.update(overrides)
    return feedback


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run_apply(
    workdir: Path,
    manifest: dict,
    feedback: dict,
    state: dict | None = None,
) -> subprocess.CompletedProcess:
    manifest_path = workdir / "manifest.json"
    session_dir = workdir / "session"
    feedback_path = session_dir / "feedback.json"
    write_json(manifest_path, manifest)
    write_json(feedback_path, feedback)
    default_state = {
        "token": "t",
        "manifest": str(manifest_path.resolve()),
        "last_feedback_id": feedback["feedback_id"],
    }
    if state is not None:
        default_state.update(state)
    write_json(
        session_dir / "session-state.json",
        default_state,
    )
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "apply_review.py"),
            str(manifest_path),
            str(feedback_path),
            "--session-dir",
            str(session_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

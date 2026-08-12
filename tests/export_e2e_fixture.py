#!/usr/bin/env python3
"""Build a current-schema rendering fixture with a live proof fingerprint."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_server  # noqa: E402


def build_fixture(destination: Path, browser_major: int) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    session_dir = destination / "session"
    output_dir = destination / "output"
    session_dir.mkdir(mode=0o700)
    output_dir.mkdir(mode=0o700)
    manifest_path = destination / "manifest.json"
    items = [
        {
            "id": "item-1",
            "layout": "editorial",
            "title": "",
            "summary": "Un contratto esplicito riduce gli errori invisibili.",
            "alt_text": "Prima card sul contratto esplicito",
        },
        {
            "id": "item-2",
            "layout": "editorial",
            "title": "",
            "summary": (
                "La card più densa verifica fit, gerarchia tipografica e parità "
                "esatta tra anteprima e produzione."
            ),
            "alt_text": "Seconda card sul controllo visivo",
        },
    ]
    manifest = {
        "schema_version": "1.4",
        "source_type": "notes",
        "sequence_mode": "narrative",
        "workflow_state": "rendering",
        "revision": 3,
        "visual_style_system": "editorial-frame",
        "logo_mode": "auto",
        "production": {
            "mode": "renderer",
            "producer": "approved-preview-dom-v2",
            "supported_style_systems": [
                "editorial-frame",
                "editorial-halftone",
                "corporate-modular",
            ],
            "expected_outputs": ["pdf", "png", "contact_sheet"],
        },
        "proof": {
            "slide_ids": ["cover", "item-2", "outro"],
            "style_system_verified": True,
            "approved": False,
            "browser": {"engine": "chromium", "major": browser_major},
        },
        "format": {
            "ratio": "4:5",
            "master_width": 1080,
            "master_height": 1350,
            "width": 1440,
            "height": 1800,
            "preview_width": 480,
            "preview_height": 600,
        },
        "cover_title": "Export reale, contratto verificato",
        "cover_subtitle": "PDF, PNG e contact sheet nello stesso test",
        "cover_alt_text": "Copertina tipografica del test export",
        "brand": {
            "name": "Carousel Builder E2E",
            "website": "example.test",
            "signature": "E2E",
            "fonts": {
                "display": {"family": "Inter", "source": "bundled"},
                "body": {"family": "Inter", "source": "bundled"},
                "serif_italic": {
                    "family": "Playfair Display",
                    "source": "bundled",
                },
            },
            "palette": {
                "background_light": "#F5F1E8",
                "background_dark": "#172033",
                "text_on_light": "#172033",
                "text_on_dark": "#FFFFFF",
                "accent": "#FEBD08",
            },
            "palette_declared": {
                "background_light": True,
                "background_dark": True,
                "text_on_light": True,
                "text_on_dark": True,
                "accent": True,
            },
        },
        "items": items,
        "outro": {
            "enabled": True,
            "title": "Consegna verificabile",
            "body": "Quattro slide e quattro artefatti coerenti.",
            "alt_text": "Chiusura del test export",
        },
        "accessibility": {
            "reading_order": ["cover", "item-1", "item-2", "outro"],
            "transcript": "Test completo dell'export reale.",
        },
        "review": {
            "mode": "visual",
            "last_feedback_id": "fixture-visual-approved",
            "last_action": "approve",
            "last_feedback_sha256": hashlib.sha256(
                b"fixture-visual-approved"
            ).hexdigest(),
            "applied_manifest_revision": 3,
            "approval_requested": True,
            "approval_stage": "visual_proof",
            "comments_pending": 0,
        },
        "workflow_receipts": [
            {
                "from": source,
                "to": target,
                "revision": 3,
                "render_fingerprint": "0" * 64,
                "evidence_sha256": hashlib.sha256(
                    f"fixture:{source}:{target}".encode()
                ).hexdigest(),
                "advanced_at": f"2026-08-12T{20 + index:02d}:00:00+00:00",
            }
            for index, (source, target) in enumerate(
                [
                    ("bozza", "testi_approvati"),
                    ("testi_approvati", "prova_visuale_approvata"),
                    ("prova_visuale_approvata", "rendering"),
                ]
            )
        ],
    }
    fingerprint = review_server.manifest_model(
        manifest_path, manifest=manifest
    )["render_fingerprint"]
    manifest["proof"]["render_fingerprint"] = fingerprint
    manifest["proof"]["approved"] = True
    for receipt in manifest["workflow_receipts"]:
        receipt["render_fingerprint"] = fingerprint
    model = review_server.manifest_model(manifest_path, manifest=manifest)
    if model["proof_approved"] is not True:
        raise RuntimeError("La fixture E2E non produce una prova valida")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": str(manifest_path),
        "session_dir": str(session_dir),
        "output_dir": str(output_dir),
        "slides": len(model["slides"]),
        "render_fingerprint": fingerprint,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("uso: export_e2e_fixture.py DESTINATION CHROMIUM_MAJOR")
    print(
        json.dumps(
            build_fixture(Path(sys.argv[1]), int(sys.argv[2])),
            ensure_ascii=False,
        )
    )

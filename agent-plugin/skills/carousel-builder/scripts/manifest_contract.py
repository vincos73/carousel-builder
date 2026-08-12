#!/usr/bin/env python3
"""Pure carousel manifest validation shared by every workflow entry point."""

from __future__ import annotations

import re

from review_core import (
    CANONICAL_WORKFLOW_STATES,
    LEGACY_PROFILE_TEXT_WORKFLOW_STATES,
    LEGACY_VISUAL_PROOF_WORKFLOW_STATES,
    normalized_logo_mode,
    normalized_proof_browser,
    normalized_visual_style_system,
    valid_sha256,
    validate_workflow_receipts,
)


MAX_SLIDES = 50
MAX_TEXT = 20_000
CURRENT_SCHEMA_VERSION = (1, 4)
SUPPORTED_SCHEMA_MAJOR = 1
ITEM_ID_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,63})\Z")
RESERVED_SLIDE_IDS = frozenset({"cover", "outro"})
SOURCE_TYPES = frozenset(
    {"newsletter", "article", "notes", "verbatim", "rework", "social"}
)
SEQUENCE_MODES = frozenset({"narrative", "sectional"})
WORKFLOW_STATES = frozenset(CANONICAL_WORKFLOW_STATES) | (
    LEGACY_PROFILE_TEXT_WORKFLOW_STATES | LEGACY_VISUAL_PROOF_WORKFLOW_STATES
)
PRODUCTION_MODES = frozenset({"renderer", "adapter", "layout"})
PRODUCTION_OUTPUTS = frozenset({"pdf", "png", "contact_sheet"})
PRODUCTION_OUTPUT_ALIASES = {"contact-sheet": "contact_sheet"}


def validated_revision(manifest: dict) -> int:
    revision = manifest.get("revision", 1)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("revision deve essere un intero non negativo")
    return revision


def parsed_schema_version(value: object) -> tuple[int, int] | None:
    """Parse supported manifest versions; a missing value is pre-version legacy."""
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+", value):
        raise ValueError("schema_version deve usare il formato major.minor")
    major, minor = (int(part) for part in value.split(".", 1))
    if major != SUPPORTED_SCHEMA_MAJOR or (major, minor) > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version {value!r} non supportata; la versione massima è "
            f"{CURRENT_SCHEMA_VERSION[0]}.{CURRENT_SCHEMA_VERSION[1]}"
        )
    return major, minor


def is_current_manifest(manifest: dict) -> bool:
    return parsed_schema_version(manifest.get("schema_version")) == CURRENT_SCHEMA_VERSION


def text(value: object, *, field: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} deve essere una stringa")
    if len(value) > limit:
        raise ValueError(f"{field} supera il limite di {limit} caratteri")
    return value


def stable_items(manifest: dict, *, require_explicit_ids: bool = False) -> list[dict]:
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Il manifest deve contenere almeno una slide in items")
    seen: set[str] = set(RESERVED_SLIDE_IDS)
    result: list[dict] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index - 1}] deve essere un oggetto")
        item_id = item.get("id")
        if item_id is None and not require_explicit_ids:
            item_id = f"item-{index}"
        if not isinstance(item_id, str) or not ITEM_ID_RE.fullmatch(item_id):
            raise ValueError(
                "Ogni items[].id deve essere una stringa di 1-64 caratteri "
                "composta da lettere, numeri, trattino o underscore"
            )
        if item_id in seen:
            if item_id in RESERVED_SLIDE_IDS:
                raise ValueError(f"items[].id {item_id!r} è riservato")
            raise ValueError("Ogni slide deve avere un ID stabile e univoco")
        seen.add(item_id)
        result.append({**item, "id": item_id})
    return result


def densest_item_id(items: list[dict]) -> str:
    """Select the proof sample deterministically, keeping current order on ties."""
    return max(
        items,
        key=lambda item: len(item.get("title", "").strip())
        + len(item.get("summary", "").strip()),
    )["id"]


def required_proof_ids_for_slides(slides: list[dict]) -> list[str]:
    items = [slide for slide in slides if slide.get("kind") == "item"]
    return ["cover", densest_item_id(items)] + (
        ["outro"] if any(slide.get("kind") == "outro" for slide in slides) else []
    )


def required_proof_slide_ids(items: list[dict], *, outro_enabled: bool) -> list[str]:
    return ["cover", densest_item_id(items)] + (["outro"] if outro_enabled else [])


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


def validate_manifest_contract(manifest: dict) -> dict:
    """Validate structural and cross-field invariants before model rendering."""
    version = parsed_schema_version(manifest.get("schema_version"))
    current = version == CURRENT_SCHEMA_VERSION
    validated_revision(manifest)

    source_type = manifest.get("source_type", "notes")
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type non valido: {source_type!r}")
    sequence_mode = manifest.get("sequence_mode", "narrative")
    if not isinstance(sequence_mode, str) or sequence_mode not in SEQUENCE_MODES:
        if current:
            raise ValueError(f"sequence_mode non valido: {sequence_mode!r}")
        sequence_mode = "narrative"
    workflow_state = manifest.get("workflow_state", "bozza")
    if not isinstance(workflow_state, str) or workflow_state not in WORKFLOW_STATES:
        raise ValueError(f"workflow_state non valido: {workflow_state!r}")
    if current and workflow_state not in CANONICAL_WORKFLOW_STATES:
        raise ValueError(
            f"workflow_state non valido per schema 1.4: {workflow_state!r}"
        )
    if current or "workflow_receipts" in manifest:
        validate_workflow_receipts(
            manifest.get("workflow_receipts", []),
            current_state=workflow_state,
            require_complete=current,
        )

    cover_title = text(manifest.get("cover_title"), field="cover_title")
    if not cover_title.strip():
        raise ValueError("cover_title non può essere vuoto")
    items = stable_items(manifest, require_explicit_ids=current)
    outro_value = manifest.get("outro")
    if outro_value is not None and not isinstance(outro_value, dict):
        raise ValueError("outro deve essere un oggetto")
    outro = outro_value or {}
    if current and "enabled" in outro and not isinstance(outro.get("enabled"), bool):
        raise ValueError("outro.enabled deve essere booleano")
    outro_enabled = outro.get("enabled", False) is True
    total_slides = 1 + len(items) + int(outro_enabled)
    if total_slides > MAX_SLIDES:
        raise ValueError(f"Il manifest può contenere al massimo {MAX_SLIDES} slide")

    for item in items:
        if "kind" in item and item.get("kind") != "item":
            raise ValueError(f"{item['id']}.kind deve essere item")
        title_value = text(item.get("title"), field=f"{item['id']}.title")
        summary_value = text(item.get("summary"), field=f"{item['id']}.summary")
        if not title_value.strip() and not summary_value.strip():
            raise ValueError(f"{item['id']} non può essere vuota")
        if sequence_mode == "narrative" and title_value.strip() and current:
            raise ValueError(
                f"{item['id']}.title deve essere vuoto in modalità narrative"
            )
    if outro_enabled:
        outro_title = text(outro.get("title"), field="outro.title")
        outro_body = text(outro.get("body"), field="outro.body")
        if not outro_title.strip() and not outro_body.strip():
            raise ValueError("La chiusura non può essere vuota")

    canonical_order = ["cover", *(item["id"] for item in items)]
    if outro_enabled:
        canonical_order.append("outro")
    accessibility_value = manifest.get("accessibility")
    if accessibility_value is not None and not isinstance(accessibility_value, dict):
        raise ValueError("accessibility deve essere un oggetto")
    reading_order = (accessibility_value or {}).get("reading_order")
    if current and reading_order != canonical_order:
        raise ValueError(
            "accessibility.reading_order deve elencare tutte le slide nell'ordine canonico"
        )
    if reading_order is not None and (
        not isinstance(reading_order, list)
        or any(not isinstance(slide_id, str) for slide_id in reading_order)
        or len(reading_order) != len(set(reading_order))
    ):
        raise ValueError("accessibility.reading_order non valido")

    raw_selected_style = manifest.get("visual_style_system")
    if (
        current
        and raw_selected_style is not None
        and normalized_visual_style_system(raw_selected_style) is None
    ):
        raise ValueError("visual_style_system non valido")
    raw_logo_mode = manifest.get("logo_mode")
    if (
        current
        and raw_logo_mode is not None
        and normalized_logo_mode(raw_logo_mode) is None
    ):
        raise ValueError("logo_mode deve essere auto oppure hidden")
    raw_cover_mode = manifest.get("cover_mode")
    if current and raw_cover_mode is not None and (
        not isinstance(raw_cover_mode, str)
        or raw_cover_mode not in {"generated", "provided", "typographic"}
    ):
        raise ValueError("cover_mode non valido")
    for object_field in ("brand", "typography"):
        value = manifest.get(object_field)
        if current and value is not None and not isinstance(value, dict):
            raise ValueError(f"{object_field} deve essere un oggetto")

    selected_style = resolved_visual_style_system(manifest)
    production_value = manifest.get("production")
    if production_value is not None and not isinstance(production_value, dict):
        raise ValueError("production deve essere un oggetto")
    production = production_value or {}
    production_mode = production.get("mode", "layout")
    if not isinstance(production_mode, str) or production_mode not in PRODUCTION_MODES:
        raise ValueError(f"production.mode non valido: {production_mode!r}")
    producer = text(production.get("producer"), field="production.producer", limit=500)
    if current and production_mode in {"renderer", "adapter"} and not producer.strip():
        raise ValueError("production.producer è obbligatorio per renderer o adapter")
    supported_value = production.get("supported_style_systems", [])
    if not isinstance(supported_value, list):
        raise ValueError("production.supported_style_systems deve essere una lista")
    supported_styles: list[str] = []
    for index, style in enumerate(supported_value):
        normalized = normalized_visual_style_system(style)
        if normalized is None:
            raise ValueError(
                f"production.supported_style_systems[{index}] non è un sistema valido"
            )
        if normalized not in supported_styles:
            supported_styles.append(normalized)
    expected_value = production.get("expected_outputs", [])
    if not isinstance(expected_value, list):
        raise ValueError("production.expected_outputs deve essere una lista")
    expected_outputs: list[str] = []
    for index, output in enumerate(expected_value):
        if not isinstance(output, str) or not output.strip():
            raise ValueError(
                f"production.expected_outputs[{index}] deve essere una stringa valida"
            )
        normalized_output = PRODUCTION_OUTPUT_ALIASES.get(output.strip(), output.strip())
        if normalized_output not in PRODUCTION_OUTPUTS:
            raise ValueError(
                f"production.expected_outputs[{index}] non è un output supportato"
            )
        if normalized_output in expected_outputs:
            raise ValueError(
                "production.expected_outputs contiene duplicati dopo la normalizzazione"
            )
        expected_outputs.append(normalized_output)
    if current and production_mode == "renderer" and (
        not expected_outputs or "pdf" not in expected_outputs
    ):
        raise ValueError(
            "production.expected_outputs deve includere almeno pdf per il renderer locale"
        )
    selected_style_supported = selected_style in supported_styles
    if (
        current
        and production_mode in {"renderer", "adapter"}
        and not selected_style_supported
    ):
        raise ValueError(
            "production.supported_style_systems deve includere visual_style_system "
            "per renderer o adapter"
        )

    proof_value = manifest.get("proof")
    if proof_value is not None and not isinstance(proof_value, dict):
        raise ValueError("proof deve essere un oggetto")
    proof = proof_value or {}
    required_ids = required_proof_slide_ids(items, outro_enabled=outro_enabled)
    raw_proof_ids = proof.get("slide_ids", [])
    if not isinstance(raw_proof_ids, list) or any(
        not isinstance(slide_id, str) for slide_id in raw_proof_ids
    ):
        raise ValueError("proof.slide_ids deve essere una lista di ID")
    if current and raw_proof_ids != required_ids:
        raise ValueError(
            "proof.slide_ids deve contenere copertina, card più densa e chiusura "
            "nell'ordine canonico"
        )
    known_ids = {"cover", *(item["id"] for item in items)}
    if outro_enabled:
        known_ids.add("outro")
    if len(raw_proof_ids) != len(set(raw_proof_ids)) or any(
        slide_id not in known_ids for slide_id in raw_proof_ids
    ):
        raise ValueError("proof.slide_ids contiene ID sconosciuti o duplicati")
    raw_style_verified = proof.get("style_system_verified", False)
    style_verified = raw_style_verified is True
    if current and not isinstance(raw_style_verified, bool):
        raise ValueError("proof.style_system_verified deve essere booleano")
    raw_proof_approved = proof.get("approved", False)
    if current and not isinstance(raw_proof_approved, bool):
        raise ValueError("proof.approved deve essere booleano")
    raw_proof_fingerprint = proof.get("render_fingerprint")
    if (
        current
        and raw_proof_fingerprint is not None
        and valid_sha256(raw_proof_fingerprint) is None
    ):
        raise ValueError("proof.render_fingerprint deve essere uno SHA-256 valido")
    proof_browser = normalized_proof_browser(proof.get("browser"))

    format_value = manifest.get("format")
    if format_value is not None and not isinstance(format_value, dict):
        raise ValueError("format deve essere un oggetto")
    format_data = format_value or {}
    required_format = {
        "ratio": "4:5",
        "master_width": 1080,
        "master_height": 1350,
        "width": 1440,
        "height": 1800,
        "preview_width": 480,
        "preview_height": 600,
    }
    if current:
        for field, expected in required_format.items():
            if format_data.get(field) != expected or (
                isinstance(expected, int) and isinstance(format_data.get(field), bool)
            ):
                raise ValueError(
                    f"format.{field} deve essere {expected!r} nello schema 1.4"
                )
    preview_width = format_data.get("preview_width", 480)
    if (
        not isinstance(preview_width, int)
        or isinstance(preview_width, bool)
        or preview_width != 480
    ):
        if current:
            raise ValueError("format.preview_width deve essere 480")
        preview_width = 480

    return {
        "schema_version": manifest.get("schema_version") or "legacy",
        "legacy": not current,
        "sequence_mode": sequence_mode,
        "workflow_state": workflow_state,
        "items": items,
        "outro": outro,
        "outro_enabled": outro_enabled,
        "selected_style": selected_style,
        "production": {
            "mode": production_mode,
            "producer": producer,
            "supported_style_systems": supported_styles,
            "selected_style_supported": selected_style_supported,
            "expected_outputs": expected_outputs,
        },
        "proof": {
            "slide_ids": raw_proof_ids,
            "required_slide_ids": required_ids,
            "style_system_verified": style_verified,
            "browser": proof_browser,
            "preview_width": preview_width,
        },
    }

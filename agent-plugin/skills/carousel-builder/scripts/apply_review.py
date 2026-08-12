#!/usr/bin/env python3
"""Apply direct editorial edits from a review batch to a carousel manifest."""

from __future__ import annotations

import argparse
import copy
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_core import (  # noqa: E402
    CANONICAL_WORKFLOW_STATES,
    InterprocessLock,
    LockUnavailableError,
    approval_stage_for_workflow,
    atomic_write_json as core_atomic_write_json,
    copy_limit_issues,
    ensure_private_directory,
    feedback_archive_path,
    fsync_directory,
    normalized_logo_mode,
    normalized_visual_style_system,
    safe_feedback_id,
    sentence_line_breaks,
    sha256_json,
    strict_json_loads,
    valid_sha256,
    validated_proof_browser,
    validate_emphasis_values,
)

from review_server import (  # noqa: E402
    absolute_input_path,
    manifest_model as server_manifest_model,
    read_private_json,
    reject_symlink_path,
)

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
        raise ValueError(f"{path} deve contenere un oggetto JSON")
    return value


def atomic_write_json(path: Path, value: dict, *, private: bool = False) -> None:
    core_atomic_write_json(
        path,
        value,
        mode=0o600 if private else None,
        private_parent=private,
    )


def atomic_copy(source: Path, destination: Path) -> None:
    ensure_private_directory(destination.parent)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(12)}.tmp")
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with source.open("rb") as source_stream, os.fdopen(
            os.dup(descriptor), "wb"
        ) as target_stream:
            while True:
                chunk = source_stream.read(1024 * 1024)
                if not chunk:
                    break
                target_stream.write(chunk)
            target_stream.flush()
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        verify_temporary_copy(temporary, descriptor)
        # Windows does not allow os.replace while the verified temporary file
        # is still open without delete sharing.  Keep the fd-bound verification
        # on every platform, then close only at the Windows publish boundary.
        if os.name == "nt":
            os.close(descriptor)
            descriptor = None
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def verify_temporary_copy(path: Path, descriptor: int) -> None:
    """Require a publish pathname to remain bound to the open copied file."""
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
    except OSError as exc:
        raise ValueError(f"Copia temporanea cambiata prima della pubblicazione: {path}") from exc
    stable_fields = (
        "st_mode",
        "st_dev",
        "st_ino",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or opened.st_nlink != 1
        or current.st_nlink != 1
        or any(
            getattr(opened, field) != getattr(current, field)
            for field in stable_fields
        )
    ):
        raise ValueError(f"Copia temporanea non sicura: {path}")


def canonical_path(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def same_path(left: Path | str, right: Path | str) -> bool:
    return canonical_path(left) == canonical_path(right)


def same_lexical_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(
        os.path.abspath(os.fspath(right))
    )


def validate_state_manifest(state: dict, manifest_path: Path) -> None:
    bound_manifest = state.get("manifest")
    if not isinstance(bound_manifest, str) or not bound_manifest:
        raise ValueError("session-state.json non contiene un manifest valido")
    if not same_path(bound_manifest, manifest_path):
        raise ValueError("La sessione è associata a un manifest diverso")


def validated_revision(value: object, *, field: str = "revision") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} deve essere un intero non negativo")
    return value


APPLIED_STATE_RECEIPT_FIELDS = {
    "applied_feedback_action",
    "applied_feedback_sha256",
    "applied_manifest_revision",
    "applied_manifest_sha256",
}
MANIFEST_REVIEW_RECEIPT_FIELDS = {
    "last_feedback_sha256",
    "applied_manifest_revision",
}


def verify_applied_manifest(
    *,
    manifest: dict,
    manifest_path: Path,
    state: dict,
    feedback_id: str,
    action: str,
    feedback_sha256: str,
    base_revision: int,
    require_applied_state: bool,
) -> dict:
    """Verify and return a durable receipt for an already committed batch.

    Version 2.8.10 stored only the feedback id/action in ``manifest.review``.
    That legacy receipt remains recoverable when its revision is plausible, but
    a partial modern receipt is treated as corruption rather than guessed.
    """
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise ValueError(
            "Lo stato indica un batch applicato, ma il manifest non contiene la ricevuta review"
        )
    if review.get("last_feedback_id") != feedback_id:
        raise ValueError(
            "Lo stato indica un batch applicato che non coincide con la ricevuta del manifest"
        )
    if review.get("last_action") != action:
        raise ValueError(
            "L'azione applicata non coincide con la ricevuta review del manifest"
        )

    revision = validated_revision(manifest.get("revision", 1))
    review_receipt_fields = MANIFEST_REVIEW_RECEIPT_FIELDS.intersection(review)
    if review_receipt_fields and review_receipt_fields != MANIFEST_REVIEW_RECEIPT_FIELDS:
        raise ValueError("La ricevuta review moderna è incompleta")
    if review_receipt_fields:
        stored_feedback_sha256 = valid_sha256(review.get("last_feedback_sha256"))
        if stored_feedback_sha256 != feedback_sha256:
            raise ValueError("Il digest del feedback non coincide con la ricevuta review")
        if validated_revision(
            review.get("applied_manifest_revision"),
            field="review.applied_manifest_revision",
        ) != revision:
            raise ValueError("La revisione corrente non coincide con la ricevuta review")
    elif revision not in {base_revision, base_revision + 1}:
        raise ValueError(
            "La revisione del manifest non è compatibile con la ricevuta review legacy"
        )

    # Bind semantic JSON, not whitespace: callers may restore the same manifest
    # with different indentation without invalidating an otherwise exact receipt.
    manifest_sha256 = sha256_json(manifest)
    receipt = {
        "applied_feedback_action": action,
        "applied_feedback_sha256": feedback_sha256,
        "applied_manifest_revision": revision,
        "applied_manifest_sha256": manifest_sha256,
    }
    if require_applied_state:
        state_receipt_fields = APPLIED_STATE_RECEIPT_FIELDS.intersection(state)
        if state_receipt_fields and state_receipt_fields != APPLIED_STATE_RECEIPT_FIELDS:
            raise ValueError("La ricevuta applicata nello stato della sessione è incompleta")
        if state_receipt_fields:
            if state.get("applied_feedback_action") != action:
                raise ValueError("applied_feedback_action non coincide con il batch")
            if valid_sha256(state.get("applied_feedback_sha256")) != feedback_sha256:
                raise ValueError("applied_feedback_sha256 non coincide con il batch")
            if validated_revision(
                state.get("applied_manifest_revision"),
                field="applied_manifest_revision",
            ) != revision:
                raise ValueError("applied_manifest_revision non coincide con il manifest")
            if valid_sha256(state.get("applied_manifest_sha256")) != manifest_sha256:
                raise ValueError(
                    "Il manifest è cambiato dopo la registrazione del batch applicato"
                )
        else:
            # Legacy 2.8.10 state always carried the live manifest revision.
            # Requiring it prevents a lone/tampered applied_feedback_id from
            # manufacturing a successful replay while still allowing backfill.
            if validated_revision(
                state.get("manifest_revision"), field="manifest_revision"
            ) != revision:
                raise ValueError(
                    "manifest_revision non coincide con la ricevuta review legacy"
                )
    return receipt


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} deve essere una stringa")
    if len(value) > 20_000:
        raise ValueError(f"{field} supera il limite consentito")
    return value


EMPHASIS_KEYS = {
    "cover_title": ("cover_title_bold", "cover_title_italic", "cover_title_serif", "cover_title_accent", "cover_title_underline"),
    "cover_subtitle": ("cover_subtitle_bold", "cover_subtitle_italic", "cover_subtitle_serif", "cover_subtitle_accent", "cover_subtitle_underline"),
    "title": ("title_bold", "title_italic", "title_serif", "title_accent", "title_underline"),
    "summary": ("summary_bold", "summary_italic", "summary_serif", "summary_accent", "summary_underline"),
}
EMPHASIS_ROLES = ("bold", "italic", "serif", "accent", "underline")
MAX_SLIDES = 50
RESERVED_SLIDE_IDS = {"cover", "outro"}


def emphasis_phrases(container: dict, field: str) -> list[tuple[str, str]]:
    """Elenca le coppie (chiave, frase) di enfasi associate a un campo testuale."""
    pairs: list[tuple[str, str]] = []
    for key in EMPHASIS_KEYS[field]:
        phrases = container.get(key)
        if not isinstance(phrases, list):
            continue
        pairs.extend((key, phrase) for phrase in phrases if isinstance(phrase, str))
    return pairs


def prune_emphasis(container: dict, field: str, new_text: str) -> list[str]:
    """Rimuove le frasi di enfasi che non compaiono più nel testo aggiornato.

    I campi ``*_serif``, ``*_accent`` e ``*_underline`` indicano frasi esatte contenute nel testo.
    Quando l'utente riscrive il testo nell'editor, le frasi precedenti possono non
    esistere più: conservarle produrrebbe un manifest che viola le regole della
    skill e un rendering con enfasi mancanti o sbagliate.
    """
    dropped: list[str] = []
    for key in EMPHASIS_KEYS[field]:
        phrases = container.get(key)
        if not isinstance(phrases, list):
            continue
        kept = [
            phrase
            for phrase in phrases
            if isinstance(phrase, str) and phrase and phrase in new_text
        ]
        if kept != phrases:
            dropped.extend(
                str(phrase) for phrase in phrases if phrase not in kept
            )
            container[key] = kept
    return dropped


def stale_emphasis(container: dict, field: str, text_value: str) -> list[str]:
    """Elenca le frasi di enfasi già incoerenti con un testo rimasto invariato."""
    return [
        phrase
        for _key, phrase in emphasis_phrases(container, field)
        if not phrase or phrase not in text_value
    ]


def sync_emphasis(
    container: dict,
    *,
    manifest_field: str,
    new_text: str,
    slide: dict,
    slide_field: str,
    text_changed: bool,
    warnings: list[str],
) -> list[str]:
    """Persist explicit emphasis, prune stale fragments, retain legacy omissions.

    Missing keys mean an older review client: existing values are retained (and
    only pruned after an associated text change). Present keys are authoritative,
    but an empty default does not materialize a key that was already absent.
    Existing emphasis can still be deliberately cleared with an empty list.
    """
    dropped: list[str] = []
    for role, key in zip(EMPHASIS_ROLES, EMPHASIS_KEYS[manifest_field]):
        feedback_key = f"{slide_field}_{role}"
        if feedback_key in slide:
            received = validate_emphasis_values(
                slide[feedback_key], new_text, field=feedback_key
            )
            kept = received
            if received or key in container:
                container[key] = kept
        elif text_changed:
            phrases = container.get(key)
            if isinstance(phrases, list):
                kept = [
                    phrase
                    for phrase in phrases
                    if isinstance(phrase, str) and phrase and phrase in new_text
                ]
                dropped.extend(str(phrase) for phrase in phrases if phrase not in kept)
                container[key] = kept
        else:
            phrases = container.get(key)
            stale = (
                [
                    phrase
                    for phrase in phrases
                    if isinstance(phrase, str) and (not phrase or phrase not in new_text)
                ]
                if isinstance(phrases, list)
                else []
            )
            if stale:
                warnings.append(
                    f"Enfasi già incoerenti con {manifest_field}.{role}, non modificate: "
                    + ", ".join(repr(phrase) for phrase in stale)
                )
    validate_no_overlap(container, manifest_field, new_text)
    return dropped


def validate_no_overlap(container: dict, field: str, text_value: str) -> None:
    """Reject visual-role selections that would address the same characters."""
    special_roles = {"italic", "serif", "accent", "underline"}
    ranges: list[tuple[int, int, str, str]] = []
    for key in EMPHASIS_KEYS[field]:
        phrases = container.get(key)
        if not isinstance(phrases, list):
            continue
        for phrase in phrases:
            if not isinstance(phrase, str) or not phrase or text_value.count(phrase) != 1:
                continue
            start = text_value.find(phrase)
            end = start + len(phrase)
            role = key.rsplit("_", 1)[-1]
            for other_start, other_end, other_key, other_phrase in ranges:
                if start < other_end and other_start < end:
                    other_role = other_key.rsplit("_", 1)[-1]
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
            ranges.append((start, end, key, phrase))


def approval_warnings(items: list[dict]) -> list[str]:
    """Return publish-time overlap constraints for every body card."""
    issues: list[str] = []
    for item in items:
        summary = item.get("summary")
        if not isinstance(summary, str) or not summary:
            continue
        try:
            validate_no_overlap(item, "summary", summary)
        except ValueError as exc:
            issues.append(str(exc))
    return issues


def validated_batch_slides(
    feedback: dict,
    *,
    item_ids: set[str],
    outro_enabled: bool,
) -> list[dict]:
    """Validate the archived batch as strictly as the HTTP boundary did."""
    slides = feedback.get("slides")
    if not isinstance(slides, list) or not (2 <= len(slides) <= MAX_SLIDES):
        raise ValueError(f"Il batch deve contenere tra 2 e {MAX_SLIDES} slide")
    expected_kinds = {"cover": "cover", **{item_id: "item" for item_id in item_ids}}
    if outro_enabled:
        expected_kinds["outro"] = "outro"

    seen: set[str] = set()
    item_count = 0
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError("Ogni slide del batch deve essere un oggetto")
        slide_id = slide.get("id")
        if not isinstance(slide_id, str) or not slide_id:
            raise ValueError(f"slides[{index}].id deve essere una stringa non vuota")
        if slide_id in seen:
            raise ValueError(f"ID slide duplicato nel batch: {slide_id}")
        seen.add(slide_id)
        expected_kind = expected_kinds.get(slide_id)
        if expected_kind is None:
            raise ValueError(f"ID slide sconosciuto o riservato: {slide_id}")
        if slide.get("kind") != expected_kind:
            raise ValueError(f"Tipo non valido per {slide_id}")
        if expected_kind == "item":
            item_count += 1

    if "cover" not in seen:
        raise ValueError("La copertina manca dal batch")
    if slides[0].get("id") != "cover":
        raise ValueError("La copertina deve restare la prima slide")
    if outro_enabled:
        if "outro" not in seen:
            raise ValueError("La chiusura manca dal batch")
        if slides[-1].get("id") != "outro":
            raise ValueError("La chiusura deve restare l'ultima slide")
    if item_count < 1:
        raise ValueError("Deve restare almeno una slide interna")
    return slides


def canonical_proof_slide_ids(items: list[dict], *, outro_enabled: bool) -> list[str]:
    """Select cover, the densest surviving item (stable tie), and optional outro."""
    if not items:
        raise ValueError("La prova richiede almeno una slide interna")

    def copy_density(item: dict) -> int:
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
        return len(title.strip()) + len(summary.strip())

    dense_item = max(items, key=copy_density)
    return ["cover", str(dense_item["id"])] + (["outro"] if outro_enabled else [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    args = parser.parse_args()

    locks: list[InterprocessLock] = []

    try:
        manifest_path = absolute_input_path(args.manifest)
        feedback_path = absolute_input_path(args.feedback)
        session_dir = absolute_input_path(args.session_dir)
        reject_symlink_path(manifest_path, field="Il manifest")
        reject_symlink_path(session_dir, field="La cartella di sessione")
        reject_symlink_path(feedback_path, field="Il feedback")
        ensure_private_directory(session_dir)
        state_path = session_dir / "session-state.json"
        expected_feedback_path = session_dir / "feedback.json"
        archive_dir = session_dir / "feedback-batches"
        reject_symlink_path(archive_dir, field="La cartella dei batch")
        is_legacy_alias = same_lexical_path(feedback_path, expected_feedback_path)
        is_direct_archive = (
            same_path(feedback_path.parent, archive_dir)
            and feedback_path.suffix == ".json"
        )
        if not (is_legacy_alias or is_direct_archive):
            raise ValueError(
                "Il feedback deve essere <session-dir>/feedback.json oppure un batch diretto in <session-dir>/feedback-batches"
            )
        locks = [
            InterprocessLock(
                manifest_path.with_name(f".{manifest_path.name}.review.lock")
            ),
            InterprocessLock(session_dir / ".review-transaction.lock"),
        ]
        for lock in locks:
            lock.acquire()

        manifest = read_json(manifest_path)
        feedback = read_private_json(feedback_path)
        state = read_private_json(state_path)
        validate_state_manifest(state, manifest_path)
        feedback_id = safe_feedback_id(feedback.get("feedback_id"))
        if is_direct_archive and feedback_path.name != f"{feedback_id}.json":
            raise ValueError("Il nome del batch append-only non coincide con feedback_id")
        action = feedback.get("action")
        if not isinstance(action, str) or action not in {"feedback", "approve"}:
            raise ValueError("Azione del batch non valida")
        bind_approved_proof = False
        approval_stage = None
        stored_action = state.get("last_action")
        if stored_action is None:
            state["last_action"] = action
        elif stored_action != action:
            raise ValueError("last_action non coincide con l'azione del feedback")
        revision = validated_revision(manifest.get("revision", 1))
        if feedback_id != state.get("last_feedback_id"):
            raise ValueError("Il batch non coincide con l'ultimo feedback della sessione")
        expected_archive_path = feedback_archive_path(session_dir, feedback_id)
        if expected_archive_path.is_symlink():
            raise ValueError("Il batch append-only non può essere un collegamento simbolico")
        if is_legacy_alias and expected_archive_path.exists():
            canonical_feedback = read_private_json(expected_archive_path)
            if canonical_feedback != feedback:
                raise ValueError(
                    "feedback.json non coincide con il batch append-only canonico"
                )
            feedback = canonical_feedback
        bound_feedback_path = state.get("last_feedback_path")
        if bound_feedback_path is not None and not same_path(
            bound_feedback_path, expected_archive_path
        ):
            raise ValueError("last_feedback_path non coincide con il batch della sessione")
        if bound_feedback_path is not None and not expected_archive_path.is_file():
            raise ValueError("Il batch append-only canonico indicato dallo stato manca")
        base_revision = validated_revision(
            feedback.get("base_revision"), field="base_revision"
        )
        feedback_sha256 = sha256_json(feedback)
        existing_review = (
            manifest.get("review")
            if isinstance(manifest.get("review"), dict)
            else {}
        )
        if feedback_id == state.get("applied_feedback_id"):
            receipt = verify_applied_manifest(
                manifest=manifest,
                manifest_path=manifest_path,
                state=state,
                feedback_id=feedback_id,
                action=action,
                feedback_sha256=feedback_sha256,
                base_revision=base_revision,
                require_applied_state=True,
            )
            state.update(receipt)
            state["manifest_revision"] = revision
            atomic_write_json(state_path, state, private=True)
            print(
                json.dumps(
                    {
                        "status": "already_applied",
                        "feedback_id": feedback_id,
                        "manifest_revision": revision,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if existing_review.get("last_feedback_id") == feedback_id:
            receipt = verify_applied_manifest(
                manifest=manifest,
                manifest_path=manifest_path,
                state=state,
                feedback_id=feedback_id,
                action=action,
                feedback_sha256=feedback_sha256,
                base_revision=base_revision,
                require_applied_state=False,
            )
            state.update(
                {
                    "applied_feedback_id": feedback_id,
                    "applied_at": now_iso(),
                    "manifest_revision": revision,
                    **receipt,
                }
            )
            atomic_write_json(state_path, state, private=True)
            print(
                json.dumps(
                    {
                        "status": "recovered",
                        "feedback_id": feedback_id,
                        "manifest_revision": revision,
                        "state_repaired": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if base_revision != revision:
            raise ValueError(
                f"Il batch parte dalla revisione {feedback.get('base_revision')}, ma il manifest è alla revisione {revision}"
            )
        if action == "approve":
            workflow_state = manifest.get("workflow_state", "bozza")
            expected_approval_stage = approval_stage_for_workflow(workflow_state)
            received_approval_stage = feedback.get("approval_stage")
            modern_contract = any(
                key in feedback
                for key in (
                    "approval_stage",
                    "base_workflow_state",
                    "base_render_fingerprint",
                    "render_fingerprint",
                )
            )
            if expected_approval_stage == "visual_proof" or modern_contract:
                if received_approval_stage != expected_approval_stage:
                    raise ValueError(
                        "approval_stage non coincide con il checkpoint corrente del workflow"
                    )
                if feedback.get("base_workflow_state") != workflow_state:
                    raise ValueError(
                        "base_workflow_state non coincide con lo stato corrente del workflow"
                    )
                base_render_fingerprint = valid_sha256(
                    feedback.get("base_render_fingerprint")
                )
                approved_render_fingerprint = valid_sha256(
                    feedback.get("render_fingerprint")
                )
                if (
                    base_render_fingerprint is None
                    or approved_render_fingerprint is None
                ):
                    raise ValueError(
                        "Il checkpoint di approvazione richiede entrambi i fingerprint visuali validi"
                    )
                current_model = server_manifest_model(
                    manifest_path, manifest=manifest
                )
                current_render_fingerprint = current_model["render_fingerprint"]
                if (
                    expected_approval_stage == "visual_proof"
                    and current_model.get("production", {}).get("producer")
                    != current_model.get("render_contract")
                ):
                    raise ValueError(
                        "Il produttore non implementa il contratto renderer locale corrente"
                    )
                if base_render_fingerprint != current_render_fingerprint:
                    raise ValueError(
                        "Gli asset, il contenuto o il checkpoint sono cambiati dopo l'approvazione; ricarica l'editor"
                    )
                approval_stage = received_approval_stage
                bind_approved_proof = approval_stage == "visual_proof"
            else:
                # Compatibility for pre-fingerprint batches is deliberately
                # limited to the profile/text checkpoint.  It must never bind a
                # visual proof.
                approval_stage = "profile_text"
        selected_visual_style = None
        if "visual_style_system" in feedback:
            selected_visual_style = normalized_visual_style_system(
                feedback.get("visual_style_system")
            )
            if selected_visual_style is None:
                raise ValueError("visual_style_system non valido")
        selected_logo_mode = None
        if "logo_mode" in feedback:
            selected_logo_mode = normalized_logo_mode(feedback.get("logo_mode"))
            if selected_logo_mode is None:
                raise ValueError("logo_mode deve essere auto oppure hidden")

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
            if item_id in RESERVED_SLIDE_IDS:
                raise ValueError(
                    f"L'ID della slide interna {item_id!r} è riservato"
                )
            by_id[item_id] = {**item, "id": item_id}

        outro_enabled = bool(
            isinstance(manifest.get("outro"), dict)
            and manifest["outro"].get("enabled", False)
        )
        slides = validated_batch_slides(
            feedback,
            item_ids=set(by_id),
            outro_enabled=outro_enabled,
        )
        cover = slides[0]
        new_cover = require_text(cover.get("title"), "cover.title")
        new_cover_subtitle = sentence_line_breaks(
            require_text(cover.get("summary"), "cover.summary")
        )

        emphasis_dropped: dict[str, list[str]] = {}
        warnings: list[str] = []
        stale_alt_text: list[str] = []

        cover_emphasis = {
            key: list(manifest[key])
            for field in ("cover_title", "cover_subtitle")
            for key in EMPHASIS_KEYS[field]
            if isinstance(manifest.get(key), list)
        }
        cover_copy_changed = (
            manifest.get("cover_title", "") != new_cover
            or manifest.get("cover_subtitle", "") != new_cover_subtitle
        )
        cover_dropped = sync_emphasis(
            cover_emphasis,
            manifest_field="cover_title",
            new_text=new_cover,
            slide=cover,
            slide_field="title",
            text_changed=manifest.get("cover_title", "") != new_cover,
            warnings=warnings,
        )
        cover_dropped.extend(
            sync_emphasis(
                cover_emphasis,
                manifest_field="cover_subtitle",
                new_text=new_cover_subtitle,
                slide=cover,
                slide_field="summary",
                text_changed=manifest.get("cover_subtitle", "") != new_cover_subtitle,
                warnings=warnings,
            )
        )
        if cover_dropped:
            emphasis_dropped["cover"] = cover_dropped
        if cover_copy_changed and manifest.get("cover_alt_text"):
            stale_alt_text.append("cover")

        new_items: list[dict] = []
        seen: set[str] = set()
        for slide in slides:
            if not isinstance(slide, dict) or slide.get("kind") != "item":
                continue
            item_id = slide.get("id")
            if item_id not in by_id or item_id in seen:
                raise ValueError(f"ID slide interna non valido o duplicato: {item_id}")
            seen.add(item_id)
            previous = by_id[item_id]
            updated = dict(previous)
            updated["title"] = require_text(slide.get("title"), f"{item_id}.title")
            updated["summary"] = sentence_line_breaks(
                require_text(slide.get("summary"), f"{item_id}.summary")
            )
            dropped = sync_emphasis(
                updated,
                manifest_field="title",
                new_text=updated["title"],
                slide=slide,
                slide_field="title",
                text_changed=previous.get("title", "") != updated["title"],
                warnings=warnings,
            )
            dropped.extend(
                sync_emphasis(
                    updated,
                    manifest_field="summary",
                    new_text=updated["summary"],
                    slide=slide,
                    slide_field="summary",
                    text_changed=previous.get("summary", "") != updated["summary"],
                    warnings=warnings,
                )
            )
            text_changed = (
                previous.get("title", "") != updated["title"]
                or previous.get("summary", "") != updated["summary"]
            )
            if dropped:
                emphasis_dropped[str(item_id)] = dropped
            if text_changed and updated.get("alt_text"):
                stale_alt_text.append(str(item_id))
            new_items.append(updated)
        if not new_items:
            raise ValueError("Deve restare almeno una slide interna")

        new_outro = None
        if outro_enabled:
            outro_slide = slides[-1]
            new_outro = dict(manifest["outro"])
            new_outro["title"] = require_text(outro_slide.get("title"), "outro.title")
            new_outro["body"] = sentence_line_breaks(
                require_text(outro_slide.get("summary"), "outro.body")
            )
            outro_changed = (
                manifest["outro"].get("title", "") != new_outro["title"]
                or manifest["outro"].get("body", "") != new_outro["body"]
            )
            if outro_changed and new_outro.get("alt_text"):
                stale_alt_text.append("outro")
            outro_dropped = sync_emphasis(
                new_outro,
                manifest_field="title",
                new_text=new_outro["title"],
                slide=outro_slide,
                slide_field="title",
                text_changed=manifest["outro"].get("title", "") != new_outro["title"],
                warnings=warnings,
            )
            outro_dropped.extend(
                sync_emphasis(
                    new_outro,
                    manifest_field="summary",
                    new_text=new_outro["body"],
                    slide=outro_slide,
                    slide_field="summary",
                    text_changed=manifest["outro"].get("body", "") != new_outro["body"],
                    warnings=warnings,
                )
            )
            if outro_dropped:
                emphasis_dropped["outro"] = outro_dropped

        changed: list[str] = []
        if manifest.get("cover_title", "") != new_cover:
            changed.append("cover_title")
        if manifest.get("cover_subtitle", "") != new_cover_subtitle:
            changed.append("cover_subtitle")
        if original_items != new_items:
            changed.append("items")
        if new_outro is not None and manifest.get("outro") != new_outro:
            changed.append("outro")
        if cover_emphasis and any(
            manifest.get(key) != value for key, value in cover_emphasis.items()
        ):
            changed.append("cover_emphasis")
        logo_mode_changed = (
            selected_logo_mode is not None
            and (normalized_logo_mode(manifest.get("logo_mode")) or "auto")
            != selected_logo_mode
        )
        if logo_mode_changed:
            changed.append("logo_mode")

        # La sequenza può cambiare per riordino o eliminazione: gli ID derivati
        # dal manifest vanno riallineati, altrimenti restano puntatori a slide
        # che non esistono più.
        slide_ids = (
            ["cover"]
            + [str(item["id"]) for item in new_items]
            + (["outro"] if new_outro is not None else [])
        )
        accessibility = (
            manifest.get("accessibility")
            if isinstance(manifest.get("accessibility"), dict)
            else None
        )
        new_reading_order = None
        if accessibility is not None and isinstance(
            accessibility.get("reading_order"), list
        ):
            if accessibility["reading_order"] != slide_ids:
                new_reading_order = slide_ids
                changed.append("accessibility.reading_order")
        proof = manifest.get("proof") if isinstance(manifest.get("proof"), dict) else None
        pruned_proof_ids: list[str] = []
        new_proof_ids = None
        if proof is not None and isinstance(proof.get("slide_ids"), list):
            canonical_ids = canonical_proof_slide_ids(
                new_items, outro_enabled=new_outro is not None
            )
            if canonical_ids != proof["slide_ids"]:
                known = set(canonical_ids)
                pruned_proof_ids = [
                    str(slide_id)
                    for slide_id in proof["slide_ids"]
                    if slide_id not in known
                ]
                new_proof_ids = canonical_ids
                changed.append("proof.slide_ids")

        editorial_changed = any(field != "logo_mode" for field in changed)
        if (
            selected_visual_style is not None
            and manifest.get("visual_style_system") != selected_visual_style
        ):
            changed.append("visual_style_system")

        visual_selection_changed = bool(
            logo_mode_changed
            or (
                selected_visual_style is not None
                and manifest.get("visual_style_system") != selected_visual_style
            )
        )

        workflow_state = manifest.get("workflow_state", "bozza")
        workflow_index = (
            CANONICAL_WORKFLOW_STATES.index(workflow_state)
            if workflow_state in CANONICAL_WORKFLOW_STATES
            else -1
        )
        at_or_after_text_approval = workflow_index >= 1
        post_visual_approval = workflow_index >= 2
        has_review_note = bool(str(feedback.get("overall_note", "")).strip())
        has_review_comments = bool(feedback.get("comments"))
        substantive_request = bool(
            editorial_changed
            or visual_selection_changed
            or has_review_comments
            or has_review_note
        )
        if action == "feedback" and at_or_after_text_approval and not substantive_request:
            raise ValueError(
                "Un feedback vuoto non può riaprire un checkpoint già approvato"
            )
        if bind_approved_proof and editorial_changed:
            raise ValueError(
                "La prova visuale non può approvare modifiche editoriali: riapri prima il checkpoint testi"
            )

        rewind_target = None
        if action == "feedback" and at_or_after_text_approval and substantive_request:
            rewind_target = (
                "bozza"
                if editorial_changed or has_review_comments or has_review_note
                else "testi_approvati"
            )
        elif bind_approved_proof and post_visual_approval and visual_selection_changed:
            rewind_target = "testi_approvati"
        review_reopened = rewind_target is not None

        stale_transcript = bool(
            editorial_changed
            and accessibility is not None
            and accessibility.get("transcript")
        )
        if stale_alt_text:
            warnings.append(
                "Alt text da rigenerare per: " + ", ".join(stale_alt_text)
            )
        if stale_transcript:
            warnings.append("La trascrizione di accessibilità non riflette più i testi correnti")
        if (
            proof is not None
            and proof.get("approved") is True
            and (changed or review_reopened)
            and (action == "feedback" or not bind_approved_proof)
        ):
            proof["approved"] = False
            changed.append("proof.approved")
            warnings.append(
                "proof.approved è stato invalidato perché il contenuto della prova è cambiato"
            )
        if (
            proof is not None
            and proof.get("style_system_verified") is True
            and (changed or review_reopened)
            and not bind_approved_proof
        ):
            proof["style_system_verified"] = False
            changed.append("proof.style_system_verified")
            warnings.append(
                "proof.style_system_verified è stato invalidato perché la prova è cambiata"
            )
        if (
            proof is not None
            and "browser" in proof
            and (changed or review_reopened)
            and not bind_approved_proof
        ):
            proof.pop("browser")
            changed.append("proof.browser")

        approval_slides = [
            {
                "id": item["id"],
                "kind": "item",
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
            }
            for item in new_items
        ]
        approval_issues = approval_warnings(new_items) + copy_limit_issues(approval_slides)
        if feedback["action"] == "approve" and approval_issues:
            raise ValueError("Approvazione bloccata: " + "; ".join(approval_issues))
        if feedback["action"] == "feedback":
            warnings.extend(approval_issues)

        if bind_approved_proof:
            expected_proof_slide_ids = canonical_proof_slide_ids(
                new_items, outro_enabled=new_outro is not None
            )
            received_proof_slide_ids = feedback.get("proof_slide_ids")
            if received_proof_slide_ids != expected_proof_slide_ids:
                raise ValueError(
                    "proof_slide_ids non coincide con il campione canonico della prova"
                )
            if feedback.get("style_system_verified") is not True:
                raise ValueError(
                    "La prova visuale richiede style_system_verified: true"
                )
            proof_browser = validated_proof_browser(feedback.get("proof_browser"))
            if proof is None:
                proof = {}
                manifest["proof"] = proof
            if proof.get("slide_ids") != expected_proof_slide_ids:
                proof["slide_ids"] = expected_proof_slide_ids
                if "proof.slide_ids" not in changed:
                    changed.append("proof.slide_ids")
            if proof.get("style_system_verified") is not True:
                proof["style_system_verified"] = True
                changed.append("proof.style_system_verified")
            if proof.get("browser") != proof_browser:
                proof["browser"] = proof_browser
                changed.append("proof.browser")
            candidate_manifest = copy.deepcopy(manifest)
            candidate_manifest["cover_title"] = new_cover
            candidate_manifest["cover_subtitle"] = new_cover_subtitle
            candidate_manifest["items"] = new_items
            candidate_manifest.update(cover_emphasis)
            if new_outro is not None:
                candidate_manifest["outro"] = new_outro
            if selected_visual_style is not None:
                candidate_manifest["visual_style_system"] = selected_visual_style
            if logo_mode_changed:
                candidate_manifest["logo_mode"] = selected_logo_mode
            final_render_fingerprint = server_manifest_model(
                manifest_path, manifest=candidate_manifest
            )["render_fingerprint"]
            if final_render_fingerprint != approved_render_fingerprint:
                raise ValueError(
                    "Il fingerprint del batch non coincide con il render finale applicabile"
                )
            if proof.get("render_fingerprint") != final_render_fingerprint:
                proof["render_fingerprint"] = final_render_fingerprint
                changed.append("proof.render_fingerprint")
            if proof.get("approved") is not True:
                proof["approved"] = True
                changed.append("proof.approved")
        elif any(
            key in feedback
            for key in ("proof_slide_ids", "style_system_verified", "proof_browser")
        ):
            raise ValueError(
                "I metadati della prova sono consentiti soltanto per la prova visuale"
            )

        # Corrections never advance the workflow, but they may atomically
        # reopen the last still-valid checkpoint. Editorial requests return to
        # bozza; a purely visual selection preserves the durable text receipt.
        workflow_state_changed = bool(
            rewind_target is not None and rewind_target != workflow_state
        )
        if rewind_target == "bozza":
            if "workflow_receipts" in manifest:
                manifest.pop("workflow_receipts", None)
                changed.append("workflow_receipts")
            if workflow_state_changed:
                manifest["workflow_state"] = "bozza"
                changed.append("workflow_state")
            warnings.append(
                "Il workflow è tornato a bozza: profilo e testi devono essere riapprovati"
            )
        elif rewind_target == "testi_approvati":
            receipts = manifest.get("workflow_receipts")
            if manifest.get("schema_version") == "1.4":
                if (
                    not isinstance(receipts, list)
                    or not receipts
                    or receipts[0].get("from") != "bozza"
                    or receipts[0].get("to") != "testi_approvati"
                ):
                    raise ValueError(
                        "Manca la ricevuta durevole dei testi approvati"
                    )
                preserved_receipts = receipts[:1]
                if receipts != preserved_receipts:
                    manifest["workflow_receipts"] = preserved_receipts
                    changed.append("workflow_receipts")
            elif "workflow_receipts" in manifest:
                manifest.pop("workflow_receipts", None)
                changed.append("workflow_receipts")
            if workflow_state_changed:
                manifest["workflow_state"] = "testi_approvati"
                changed.append("workflow_state")
            warnings.append(
                "Il workflow è tornato ai testi approvati: serve una nuova prova visuale"
            )

        applied_revision = revision + 1 if changed else revision
        review = dict(existing_review)
        review.update(
            {
                "mode": "visual",
                "last_feedback_id": feedback_id,
                "last_action": action,
                "last_feedback_sha256": feedback_sha256,
                "applied_manifest_revision": applied_revision,
                "approval_requested": action == "approve",
                "comments_pending": len(feedback.get("comments", [])),
                "updated_at": now_iso(),
            }
        )
        if approval_stage is not None:
            review["approval_stage"] = approval_stage
        if selected_visual_style is not None:
            review["visual_style_system"] = selected_visual_style
        if changed or existing_review != review:
            # Il backup serve a recuperare i testi precedenti: senza modifiche
            # editoriali non c'è nulla da ripristinare e sarebbe solo una copia
            # identica in più a ogni batch di soli commenti.
            if changed:
                backups_dir = session_dir / "backups"
                backup_name = f"manifest-r{revision}-{feedback_id}.json"
                atomic_copy(manifest_path, backups_dir / backup_name)
                manifest["cover_title"] = new_cover
                manifest["cover_subtitle"] = new_cover_subtitle
                manifest["items"] = new_items
                manifest.update(cover_emphasis)
                if new_outro is not None:
                    manifest["outro"] = new_outro
                if new_reading_order is not None:
                    accessibility["reading_order"] = new_reading_order
                if new_proof_ids is not None:
                    proof["slide_ids"] = new_proof_ids
                if selected_visual_style is not None:
                    manifest["visual_style_system"] = selected_visual_style
                if logo_mode_changed:
                    manifest["logo_mode"] = selected_logo_mode
                manifest["revision"] = revision + 1
            manifest["review"] = review
            server_manifest_model(manifest_path, manifest=manifest)
            atomic_write_json(manifest_path, manifest, private=False)

        applied_revision = validated_revision(manifest.get("revision", revision))
        manifest_sha256 = sha256_json(manifest)
        state.update(
            {
                "applied_feedback_id": feedback_id,
                "applied_at": now_iso(),
                "manifest_revision": applied_revision,
                "applied_feedback_action": action,
                "applied_feedback_sha256": feedback_sha256,
                "applied_manifest_revision": applied_revision,
                "applied_manifest_sha256": manifest_sha256,
            }
        )
        atomic_write_json(state_path, state, private=True)
        result = {
            "status": "applied",
            "feedback_id": feedback_id,
            "action": action,
            "changed": changed,
            "manifest_revision": applied_revision,
            "comments": feedback.get("comments", []),
            "overall_note": feedback.get("overall_note", ""),
            "approval_requested": action == "approve",
            "approval_stage": approval_stage,
            "workflow_state_changed": workflow_state_changed,
            "emphasis_dropped": emphasis_dropped,
            "proof_slide_ids_pruned": pruned_proof_ids,
            "stale_alt_text": stale_alt_text,
            "stale_transcript": stale_transcript,
            "warnings": warnings,
            "visual_style_system": manifest.get("visual_style_system"),
            "logo_mode": normalized_logo_mode(manifest.get("logo_mode")) or "auto",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KeyError, LockUnavailableError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        for lock in reversed(locks):
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

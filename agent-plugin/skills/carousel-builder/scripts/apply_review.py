#!/usr/bin/env python3
"""Apply direct editorial edits from a review batch to a carousel manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class LockUnavailableError(RuntimeError):
    """Raised when another process is updating the same review session."""


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


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.tmp")
    try:
        with source.open("rb") as source_stream, temporary.open("wb") as target_stream:
            while True:
                chunk = source_stream.read(1024 * 1024)
                if not chunk:
                    break
                target_stream.write(chunk)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        os.replace(temporary, destination)
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
        raise ValueError("session-state.json non contiene un manifest valido")
    if not same_path(bound_manifest, manifest_path):
        raise ValueError("La sessione è associata a un manifest diverso")


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
LOGO_MODES = {"auto", "hidden"}
VISUAL_STYLE_SYSTEMS = {
    "editorial-frame",
    "editorial-halftone",
    "corporate-modular",
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


def sentence_line_breaks(value: str) -> str:
    """Separa le frasi complete senza spezzare decimali, versioni o abbreviazioni."""
    def replace(match: re.Match[str]) -> str:
        token = re.search(r"([A-Za-zÀ-ÿ]+)$", value[: match.start()])
        if token and token.group(1).casefold() in SENTENCE_BREAK_ABBREVIATIONS:
            return match.group(0)
        return "." + match.group(1) + "\n"

    return SENTENCE_BREAK_RE.sub(replace, value)


def normalized_visual_style_system(value: object) -> str | None:
    """Validate the persisted carousel override without mutating brand defaults."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    normalized = VISUAL_STYLE_ALIASES.get(normalized, normalized)
    return normalized if normalized in VISUAL_STYLE_SYSTEMS else None


def normalized_logo_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    mode = value.strip().casefold()
    return mode if mode in LOGO_MODES else None


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


def _received_emphasis(value: object, *, field: str) -> list[str]:
    """Validate a client-provided emphasis list before it reaches the manifest."""
    if not isinstance(value, list):
        raise ValueError(f"{field} deve essere una lista")
    result: list[str] = []
    for index, phrase in enumerate(value):
        if not isinstance(phrase, str) or not phrase:
            raise ValueError(f"{field}[{index}] deve essere una frase non vuota")
        if phrase in result:
            raise ValueError(f"{field} contiene un valore non univoco: {phrase!r}")
        result.append(phrase)
    return result


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
            received = _received_emphasis(slide[feedback_key], field=feedback_key)
            kept = [phrase for phrase in received if phrase in new_text]
            dropped.extend(phrase for phrase in received if phrase not in kept)
            for phrase in kept:
                if new_text.count(phrase) != 1:
                    raise ValueError(
                        f"{feedback_key} deve comparire una sola volta nel testo della card"
                    )
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
    expected_feedback_path = (session_dir / "feedback.json").resolve()
    locks: list[InterprocessLock] = []

    try:
        if not same_path(feedback_path, expected_feedback_path):
            raise ValueError("Il feedback deve essere <session-dir>/feedback.json")
        locks = [
            InterprocessLock(
                manifest_path.with_name(f".{manifest_path.name}.review.lock")
            ),
            InterprocessLock(session_dir / ".review-transaction.lock"),
        ]
        for lock in locks:
            lock.acquire()

        manifest = read_json(manifest_path)
        feedback = read_json(feedback_path)
        state = read_json(state_path)
        validate_state_manifest(state, manifest_path)
        revision = manifest.get("revision", 1)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("revision deve essere un intero non negativo")
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
        existing_review = (
            manifest.get("review")
            if isinstance(manifest.get("review"), dict)
            else {}
        )
        if existing_review.get("last_feedback_id") == feedback.get("feedback_id"):
            state.update(
                {
                    "applied_feedback_id": feedback["feedback_id"],
                    "applied_at": now_iso(),
                    "manifest_revision": revision,
                }
            )
            atomic_write_json(state_path, state)
            print(
                json.dumps(
                    {
                        "status": "recovered",
                        "feedback_id": feedback["feedback_id"],
                        "manifest_revision": revision,
                        "state_repaired": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if feedback.get("base_revision") != revision:
            raise ValueError(
                f"Il batch parte dalla revisione {feedback.get('base_revision')}, ma il manifest è alla revisione {revision}"
            )
        if feedback.get("action") not in {"feedback", "approve"}:
            raise ValueError("Azione del batch non valida")
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
            by_id[item_id] = {**item, "id": item_id}

        slides = feedback.get("slides")
        if not isinstance(slides, list):
            raise ValueError("Il batch non contiene slides valide")
        cover = next((slide for slide in slides if slide.get("id") == "cover"), None)
        if not isinstance(cover, dict):
            raise ValueError("La copertina manca dal batch")
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
        if isinstance(manifest.get("outro"), dict) and manifest["outro"].get("enabled", False):
            outro_slide = next((slide for slide in slides if slide.get("id") == "outro"), None)
            if not isinstance(outro_slide, dict):
                raise ValueError("La chiusura manca dal batch")
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
            known = set(slide_ids)
            kept = [
                slide_id
                for slide_id in proof["slide_ids"]
                if isinstance(slide_id, str) and slide_id in known
            ]
            if kept != proof["slide_ids"]:
                pruned_proof_ids = [
                    str(slide_id) for slide_id in proof["slide_ids"] if slide_id not in kept
                ]
                new_proof_ids = kept
                changed.append("proof.slide_ids")

        editorial_changed = bool(changed)
        if (
            selected_visual_style is not None
            and manifest.get("visual_style_system") != selected_visual_style
        ):
            changed.append("visual_style_system")

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
        if proof is not None and proof.get("approved") and changed:
            warnings.append(
                "proof.approved resta true ma il contenuto della prova è cambiato: la prova visuale va riapprovata"
            )

        approval_issues = approval_warnings(new_items)
        if feedback["action"] == "approve" and approval_issues:
            raise ValueError("Approvazione bloccata: " + "; ".join(approval_issues))
        if feedback["action"] == "feedback":
            warnings.extend(approval_issues)

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
        if selected_visual_style is not None:
            review["visual_style_system"] = selected_visual_style
        if changed or existing_review != review:
            # Il backup serve a recuperare i testi precedenti: senza modifiche
            # editoriali non c'è nulla da ripristinare e sarebbe solo una copia
            # identica in più a ogni batch di soli commenti.
            if changed:
                backups_dir = session_dir / "backups"
                backup_name = f"manifest-r{revision}-{feedback['feedback_id']}.json"
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

#!/usr/bin/env python3
"""Attach a cover image after text approval through the durable review channel."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from apply_review import atomic_copy  # noqa: E402
from process_review import process_review  # noqa: E402
from review_core import (  # noqa: E402
    InterprocessLock,
    LockUnavailableError,
    fsync_directory,
    new_feedback_id,
    sha256_file,
)
from review_server import (  # noqa: E402
    RENDER_SLIDE_FIELDS,
    absolute_input_path,
    commit_feedback,
    manifest_model,
    path_entry_exists,
    read_private_json,
    recover_feedback_commit,
    reject_symlink_path,
    validate_feedback,
    validate_state_manifest,
)


IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
COVER_POSITION_RE = re.compile(
    r"(?:left|center|right|\d{1,3}(?:\.\d+)?%)\s+"
    r"(?:top|center|bottom|\d{1,3}(?:\.\d+)?%)\Z"
)


def _validate_metadata(
    *,
    expected_revision: int,
    mode: str,
    position: str,
    alt_text: str,
    concepts: list[str],
    metaphor: str,
    prompt: str,
) -> None:
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
    ):
        raise ValueError("expected_revision deve essere un intero non negativo")
    if mode not in {"generated", "provided"}:
        raise ValueError("mode deve essere generated oppure provided")
    if not isinstance(position, str) or not COVER_POSITION_RE.fullmatch(position):
        raise ValueError("position non è una posizione CSS sicura")
    if not isinstance(alt_text, str) or not alt_text.strip() or len(alt_text) > 2_000:
        raise ValueError("alt_text deve essere una descrizione non vuota")
    if (
        not isinstance(concepts, list)
        or len(concepts) > 3
        or any(
            not isinstance(value, str) or not value.strip() or len(value) > 500
            for value in concepts
        )
    ):
        raise ValueError("Sono ammessi al massimo tre concetti non vuoti")
    for field, value in (("metaphor", metaphor), ("prompt", prompt)):
        if not isinstance(value, str) or len(value) > 10_000:
            raise ValueError(f"{field} non è valido")


def _slide_payload(model: dict) -> list[dict]:
    return [
        {
            field: slide.get(field, [] if "_" in field else "")
            for field in RENDER_SLIDE_FIELDS
        }
        for slide in model["slides"]
    ]


def _copy_asset(source: Path, manifest_path: Path) -> tuple[Path, str]:
    reject_symlink_path(source, field="L'immagine di copertina")
    if source.is_symlink() or not source.is_file():
        raise ValueError("L'immagine di copertina non è un file regolare")
    source_stat = source.stat()
    if source_stat.st_nlink != 1:
        raise ValueError("L'immagine di copertina non può essere un hard link")
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError("Formato immagine non supportato; usare JPG, PNG o WebP")
    digest = sha256_file(source)
    asset_dir = manifest_path.parent / "assets"
    reject_symlink_path(asset_dir, field="La cartella assets")
    asset_dir.mkdir(parents=True, exist_ok=True)
    if asset_dir.is_symlink() or not asset_dir.is_dir():
        raise ValueError("La cartella assets non è una directory regolare")
    destination = asset_dir / f"cover-{digest}{suffix}"
    if path_entry_exists(destination):
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.stat().st_nlink != 1
            or sha256_file(destination) != digest
        ):
            raise ValueError("La destinazione immagine esistente non è sicura")
    else:
        atomic_copy(source, destination)
        if sha256_file(destination) != digest:
            raise ValueError("La copia dell'immagine non coincide con la sorgente")
    return destination, digest


def attach_cover_asset(
    manifest_input: Path,
    image_input: Path,
    *,
    session_dir_input: Path,
    expected_revision: int,
    mode: str,
    position: str,
    alt_text: str,
    concepts: list[str],
    metaphor: str,
    prompt: str,
) -> dict:
    manifest_path = absolute_input_path(manifest_input)
    image_path = absolute_input_path(image_input)
    session_dir = absolute_input_path(session_dir_input)
    reject_symlink_path(manifest_path, field="Il manifest")
    reject_symlink_path(session_dir, field="La cartella di sessione")
    if not session_dir.is_dir():
        raise ValueError(f"La cartella di sessione non esiste: {session_dir}")
    _validate_metadata(
        expected_revision=expected_revision,
        mode=mode,
        position=position,
        alt_text=alt_text,
        concepts=concepts,
        metaphor=metaphor,
        prompt=prompt,
    )

    state_path = session_dir / "session-state.json"
    feedback_path = session_dir / "feedback.json"
    journal_path = session_dir / "feedback-commit.json"
    manifest_lock = InterprocessLock(
        manifest_path.with_name(f".{manifest_path.name}.review.lock")
    )
    transaction_lock = InterprocessLock(session_dir / ".review-transaction.lock")
    archive_path: Path | None = None
    destination: Path | None = None
    digest = ""
    with manifest_lock, transaction_lock:
        state = read_private_json(state_path)
        validate_state_manifest(state, manifest_path)
        recover_feedback_commit(
            journal_path=journal_path,
            feedback_path=feedback_path,
            state_path=state_path,
            manifest_path=manifest_path,
        )
        state = read_private_json(state_path)
        if state.get("last_feedback_id") != state.get("applied_feedback_id"):
            raise ValueError("Un feedback precedente deve essere applicato prima della cover")
        model = manifest_model(manifest_path)
        if model.get("workflow_state") != "testi_approvati":
            raise ValueError(
                "La cover differita può essere collegata soltanto nello stato testi_approvati"
            )
        if model.get("revision") != expected_revision:
            raise ValueError(
                f"La revisione corrente {model.get('revision')} non coincide con "
                f"--expected-revision {expected_revision}"
            )
        destination, digest = _copy_asset(image_path, manifest_path)
        relative_asset = destination.relative_to(manifest_path.parent).as_posix()
        feedback_id = new_feedback_id()
        payload = {
            "feedback_id": feedback_id,
            "action": "feedback",
            "base_revision": expected_revision,
            "slides": _slide_payload(model),
            "comments": [],
            "overall_note": "",
            "visual_style_system": model["visual_proofs"]["selected_style_system"],
            "logo_mode": model["logo_mode"],
            "cover_mode": mode,
            "cover_asset": {
                "path": relative_asset,
                "sha256": digest,
                "position": position,
                "alt_text": alt_text,
                "concepts": concepts,
                "metaphor": metaphor,
                "prompt": prompt,
            },
        }
        feedback = validate_feedback(payload, model)
        feedback["cover_asset"] = payload["cover_asset"]
        event = commit_feedback(
            journal_path=journal_path,
            feedback_path=feedback_path,
            state_path=state_path,
            manifest_path=manifest_path,
            current_state=state,
            feedback=feedback,
            manifest_revision=expected_revision,
        )
        archive_path = Path(event["archive_path"])
        try:
            journal_path.unlink(missing_ok=True)
            fsync_directory(session_dir)
        except OSError:
            # A committed journal is recoverable and must not be guessed away.
            pass

    processed = process_review(
        manifest_path,
        archive_path,
        session_dir_input=session_dir,
    )
    return {
        "status": "attached",
        "manifest": str(manifest_path),
        "asset": str(destination),
        "asset_sha256": digest,
        "cover_mode": mode,
        "review": processed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--mode", choices=("generated", "provided"), required=True)
    parser.add_argument("--position", default="50% 50%")
    parser.add_argument("--alt-text", required=True)
    parser.add_argument("--concept", action="append", default=[])
    parser.add_argument("--metaphor", default="")
    parser.add_argument("--prompt", default="")
    args = parser.parse_args()
    try:
        result = attach_cover_asset(
            args.manifest,
            args.image,
            session_dir_input=args.session_dir,
            expected_revision=args.expected_revision,
            mode=args.mode,
            position=args.position,
            alt_text=args.alt_text,
            concepts=args.concept,
            metaphor=args.metaphor,
            prompt=args.prompt,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LockUnavailableError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

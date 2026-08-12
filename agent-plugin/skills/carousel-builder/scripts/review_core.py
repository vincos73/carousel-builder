#!/usr/bin/env python3
"""Shared, dependency-free invariants for the local carousel review workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import uuid
from pathlib import Path


SUMMARY_WITH_TITLE_MAX = 180
SUMMARY_WITHOUT_TITLE_MAX = 320
SAFE_LEGACY_FEEDBACK_ID_RE = re.compile(r"feedback-[A-Za-z0-9_-]{1,100}\Z")
SENTENCE_BREAK_ABBREVIATIONS = {
    "ca", "cfr", "dott", "ecc", "es", "n", "pag", "pp", "prof", "sig", "sigg", "vs"
}
SENTENCE_BREAK_RE = re.compile(
    r'([.!?…]+)([”’"\')\]]*)[ \t]+(?=[A-ZÀÈÉÌÒÙ0-9])'
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Costante JSON non valida: {value}")


def strict_json_loads(value: str | bytes) -> object:
    """Decode RFC-compatible JSON, rejecting Python's NaN/Infinity extension."""
    return json.loads(value, parse_constant=_reject_json_constant)


def strict_json_text(value: object, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=indent,
        allow_nan=False,
        sort_keys=False,
    )


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: object) -> str:
    """Hash a JSON-compatible value independently from its on-disk formatting."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def fsync_directory(path: Path) -> None:
    """Persist directory-entry changes after replace, link or unlink operations."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_temporary(path: Path) -> None:
    """Remove a temporary entry and persist that removal when it existed."""
    try:
        path.unlink()
    except FileNotFoundError:
        return
    fsync_directory(path.parent)


def render_context_fingerprint(context: dict, asset_digests: dict[str, str]) -> str:
    return hashlib.sha256(
        canonical_json_bytes({"context": context, "assets": asset_digests})
    ).hexdigest()


def render_snapshot_fingerprint(
    *,
    context_fingerprint: str,
    slides: list[dict],
    visual_style_system: str,
    logo_mode: str,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "context_fingerprint": context_fingerprint,
                "slides": slides,
                "visual_style_system": visual_style_system,
                "logo_mode": logo_mode,
            }
        )
    ).hexdigest()


def valid_sha256(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    return None


def approval_stage_for_workflow(workflow_state: object) -> str:
    if not isinstance(workflow_state, str):
        raise ValueError(
            f"workflow_state non valido per l'approvazione: {workflow_state!r}"
        )
    if workflow_state in {
        "bozza",
        "draft",
        "in_revisione",
        "in_revisione_editoriale",
        "in_review",
        "feedback",
    }:
        return "profile_text"
    if workflow_state in {
        "testi_approvati",
        "prova_visuale_approvata",
        "rendering",
        "qa",
        "consegnato",
        "approvato",
        "approved",
        "pubblicato",
        "published",
    }:
        return "visual_proof"
    raise ValueError(f"workflow_state non valido per l'approvazione: {workflow_state!r}")


def feedback_request_fingerprint(payload: dict) -> str:
    """Hash a request independently from its client-generated idempotency key."""
    canonical = dict(payload)
    canonical.pop("feedback_id", None)
    return hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()


def ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(
            f"La directory privata non può essere un collegamento simbolico: {path}"
        )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"Percorso directory privata non valido: {path}")
    try:
        path.chmod(0o700)
    except OSError:
        if os.name != "nt":
            raise


def open_private_lock_file(path: Path):
    """Open a regular lock file without ever following a pre-created symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise OSError(f"Il lock non può essere un collegamento simbolico: {path}")
    flags = os.O_RDWR | os.O_CREAT
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags | nofollow, 0o600)
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise OSError(f"Percorso lock non sicuro: {path}")
        # A regular file can still be an attacker-controlled hard link.  Never
        # chmod it or let the lock implementation write its sentinel unless the
        # directory entry is the file's only link.
        if opened.st_nlink != 1 or current.st_nlink != 1:
            raise OSError(f"Il lock non può essere un hard link: {path}")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:
            path.chmod(0o600)
        stream = os.fdopen(descriptor, "a+b")
        descriptor = None
        return stream
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _existing_mode(path: Path, fallback: int) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return fallback


def atomic_write_json(
    path: Path,
    value: dict,
    *,
    mode: int | None = None,
    default_mode: int = 0o600,
    private_parent: bool = True,
) -> None:
    """Replace a JSON object atomically while preserving or enforcing its mode."""
    if private_parent:
        ensure_private_directory(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = mode if mode is not None else _existing_mode(path, default_mode)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            target_mode,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            stream.write(strict_json_text(value, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, target_mode)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            _unlink_temporary(temporary)
        except OSError:
            pass


def append_only_json(path: Path, value: dict) -> bool:
    """Atomically create one immutable JSON batch; return False for an exact replay."""
    ensure_private_directory(path.parent)
    if path.is_symlink():
        raise ValueError(
            f"Il batch append-only non può essere un collegamento simbolico: {path.name}"
        )
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            stream.write(strict_json_text(value, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, path)
        except FileExistsError:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"Percorso batch append-only non valido: {path.name}")
            existing = strict_json_loads(path.read_text(encoding="utf-8"))
            if existing != value:
                raise ValueError(f"Il batch append-only esiste già con contenuto diverso: {path.name}")
            try:
                path.chmod(0o600)
            except OSError:
                if os.name != "nt":
                    raise
            return False
        fsync_directory(path.parent)
        return True
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            _unlink_temporary(temporary)
        except OSError:
            pass


def client_feedback_id(value: object, *, required: bool = False) -> str | None:
    """Validate a canonical client UUID used as the feedback idempotency key."""
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError("feedback_id deve essere un UUID canonico")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("feedback_id deve essere un UUID canonico") from exc
    canonical = str(parsed)
    if value != canonical:
        raise ValueError("feedback_id deve essere un UUID canonico minuscolo")
    return canonical


def new_feedback_id() -> str:
    return str(uuid.uuid4())


def safe_feedback_id(value: object) -> str:
    """Accept current UUID ids and safe pre-2.8.9 ids, never path fragments."""
    if isinstance(value, str):
        try:
            return client_feedback_id(value, required=True) or ""
        except ValueError:
            if SAFE_LEGACY_FEEDBACK_ID_RE.fullmatch(value):
                return value
    raise ValueError("feedback_id non valido o non sicuro")


def feedback_archive_path(session_dir: Path, feedback_id: object) -> Path:
    safe_id = safe_feedback_id(feedback_id)
    session_root = session_dir.resolve()
    archive_dir = session_root / "feedback-batches"
    if archive_dir.is_symlink():
        raise ValueError(
            "feedback-batches non può essere un collegamento simbolico fuori dalla sessione"
        )
    archive_path = archive_dir / f"{safe_id}.json"
    if archive_path.parent != archive_dir:
        raise ValueError("Percorso batch append-only fuori dalla sessione")
    return archive_path


def sentence_line_breaks(value: str) -> str:
    """Separate complete sentences after .?!… without splitting common abbreviations."""

    def replace(match: re.Match[str]) -> str:
        punctuation = match.group(1)
        if punctuation == ".":
            # Walk only the adjacent token.  Slicing the whole prefix for every
            # sentence made a long, punctuation-heavy card quadratic.
            token_end = match.start()
            token_start = token_end
            while token_start > 0:
                character = value[token_start - 1]
                if not (
                    "A" <= character <= "Z"
                    or "a" <= character <= "z"
                    or "À" <= character <= "ÿ"
                ):
                    break
                token_start -= 1
            if token_start < token_end:
                word = value[token_start:token_end]
                if len(word) == 1 or word.casefold() in SENTENCE_BREAK_ABBREVIATIONS:
                    return match.group(0)
        return punctuation + match.group(2) + "\n"

    return SENTENCE_BREAK_RE.sub(replace, value)


def validate_emphasis_values(value: object, content: str, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} deve essere una lista")
    result: list[str] = []
    for index, phrase in enumerate(value):
        if not isinstance(phrase, str) or not phrase:
            raise ValueError(f"{field}[{index}] deve essere una frase non vuota")
        if phrase in result:
            raise ValueError(f"{field} contiene un valore non univoco: {phrase!r}")
        if content.count(phrase) != 1:
            raise ValueError(f"{field}[{index}] deve comparire una sola volta nel testo della card")
        result.append(phrase)
    return result


def copy_limit_issues(slides: list[dict]) -> list[str]:
    """Return deterministic, documented approval blockers for internal-card copy."""
    issues: list[str] = []
    for slide in slides:
        if slide.get("kind") != "item":
            continue
        slide_id = str(slide.get("id") or "slide interna")
        title = slide.get("title") if isinstance(slide.get("title"), str) else ""
        summary = slide.get("summary") if isinstance(slide.get("summary"), str) else ""
        if not title.strip() and not summary.strip():
            issues.append(f"{slide_id}: la card non può essere vuota")
            continue
        limit = SUMMARY_WITH_TITLE_MAX if title.strip() else SUMMARY_WITHOUT_TITLE_MAX
        if len(summary) > limit:
            qualifier = "con titolo" if title.strip() else "senza titolo"
            issues.append(
                f"{slide_id}: il riassunto {qualifier} contiene {len(summary)} caratteri; massimo {limit}"
            )
    return issues

#!/usr/bin/env python3
"""Shared, dependency-free invariants for the local carousel review workflow."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import stat
import uuid
from datetime import datetime
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


SUMMARY_WITH_TITLE_MAX = 180
SUMMARY_WITHOUT_TITLE_MAX = 320
CANONICAL_WORKFLOW_STATES = (
    "bozza",
    "testi_approvati",
    "prova_visuale_approvata",
    "rendering",
    "qa",
    "consegnato",
)
CANONICAL_WORKFLOW_TRANSITIONS = {
    current: CANONICAL_WORKFLOW_STATES[index + 1]
    for index, current in enumerate(CANONICAL_WORKFLOW_STATES[:-1])
}
LEGACY_PROFILE_TEXT_WORKFLOW_STATES = frozenset(
    {
        "draft",
        "in_revisione",
        "in_revisione_editoriale",
        "in_review",
        "feedback",
    }
)
LEGACY_VISUAL_PROOF_WORKFLOW_STATES = frozenset(
    {"approvato", "approved", "pubblicato", "published"}
)
WORKFLOW_RECEIPT_FIELDS = frozenset(
    {"from", "to", "revision", "render_fingerprint", "evidence_sha256", "advanced_at"}
)
VISUAL_STYLE_IDS = frozenset(
    {"editorial-frame", "editorial-halftone", "corporate-modular"}
)
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
LOGO_MODES = frozenset({"auto", "hidden"})
BROWSER_ENGINES = frozenset({"chromium"})
APPEND_ONLY_TEMP_PREFIX = ".carousel-append-v1-"
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


def normalized_visual_style_system(value: object) -> str | None:
    """Return a canonical visual style ID, accepting documented legacy aliases."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    normalized = VISUAL_STYLE_ALIASES.get(normalized, normalized)
    return normalized if normalized in VISUAL_STYLE_IDS else None


def normalized_logo_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if normalized in LOGO_MODES else None


def normalized_proof_browser(value: object, *, required: bool = False) -> dict | None:
    """Normalize the persisted proof browser using manifest-facing errors."""
    if value is None and not required:
        return None
    if not isinstance(value, dict) or set(value) != {"engine", "major"}:
        raise ValueError("proof.browser deve contenere soltanto engine e major")
    engine = value.get("engine")
    major = value.get("major")
    if engine not in BROWSER_ENGINES:
        raise ValueError("proof.browser.engine deve essere chromium")
    if not isinstance(major, int) or isinstance(major, bool) or not 1 <= major <= 999:
        raise ValueError("proof.browser.major deve essere un intero tra 1 e 999")
    return {"engine": engine, "major": major}


def validated_proof_browser(value: object) -> dict:
    """Validate a feedback proof browser while preserving its public error names."""
    try:
        return normalized_proof_browser(value, required=True) or {}
    except ValueError as exc:
        raise ValueError(str(exc).replace("proof.browser", "proof_browser")) from exc


def validate_canonical_workflow_transition(current: object, target: object) -> None:
    """Require one forward-only transition in the canonical schema 1.4 workflow."""
    if not isinstance(current, str) or current not in CANONICAL_WORKFLOW_STATES:
        raise ValueError(f"workflow_state canonico non valido: {current!r}")
    if not isinstance(target, str) or target not in CANONICAL_WORKFLOW_STATES:
        raise ValueError(f"workflow_state destinazione non valido: {target!r}")
    expected = CANONICAL_WORKFLOW_TRANSITIONS.get(current)
    if expected != target:
        if expected is None:
            raise ValueError(f"Lo stato {current!r} è terminale")
        raise ValueError(
            f"Transizione workflow non valida: {current!r} -> {target!r}; "
            f"la prossima destinazione è {expected!r}"
        )


def validate_workflow_receipts(
    value: object,
    *,
    current_state: object,
    require_complete: bool = False,
) -> list[dict]:
    """Validate and copy the durable, bounded canonical transition ledger.

    Schema 1.4 callers set ``require_complete`` so the ledger starts at
    ``bozza`` and accounts for every transition up to the current state.
    Older manifests remain readable without fabricating historical receipts.
    """
    if not isinstance(current_state, str) or current_state not in CANONICAL_WORKFLOW_STATES:
        raise ValueError(f"workflow_state canonico non valido: {current_state!r}")
    if not isinstance(value, list) or len(value) > len(CANONICAL_WORKFLOW_STATES) - 1:
        raise ValueError("workflow_receipts deve essere una lista di massimo cinque ricevute")
    receipts: list[dict] = []
    for index, receipt in enumerate(value):
        if not isinstance(receipt, dict) or set(receipt) != WORKFLOW_RECEIPT_FIELDS:
            raise ValueError(f"workflow_receipts[{index}] non ha il formato canonico")
        validate_canonical_workflow_transition(receipt.get("from"), receipt.get("to"))
        receipt_revision = receipt.get("revision")
        advanced_at = receipt.get("advanced_at")
        try:
            parsed_advanced_at = datetime.fromisoformat(advanced_at)
        except (TypeError, ValueError):
            parsed_advanced_at = None
        if (
            not isinstance(receipt_revision, int)
            or isinstance(receipt_revision, bool)
            or receipt_revision < 0
            or valid_sha256(receipt.get("render_fingerprint")) is None
            or valid_sha256(receipt.get("evidence_sha256")) is None
            or parsed_advanced_at is None
            or parsed_advanced_at.tzinfo is None
        ):
            raise ValueError(f"workflow_receipts[{index}] contiene valori non validi")
        if receipts and receipts[-1]["to"] != receipt["from"]:
            raise ValueError("workflow_receipts non forma una catena continua")
        receipts.append(dict(receipt))
    expected_count = CANONICAL_WORKFLOW_STATES.index(current_state)
    if require_complete and (
        len(receipts) != expected_count
        or (receipts and receipts[0]["from"] != "bozza")
    ):
        raise ValueError(
            "workflow_receipts deve coprire l'intera catena canonica da bozza "
            "fino a workflow_state"
        )
    if receipts and receipts[-1]["to"] != current_state:
        raise ValueError("L'ultima workflow_receipt non coincide con workflow_state")
    return receipts


def approval_stage_for_workflow(workflow_state: object) -> str:
    if not isinstance(workflow_state, str):
        raise ValueError(
            f"workflow_state non valido per l'approvazione: {workflow_state!r}"
        )
    if workflow_state == "bozza" or workflow_state in LEGACY_PROFILE_TEXT_WORKFLOW_STATES:
        return "profile_text"
    if (
        workflow_state in CANONICAL_WORKFLOW_STATES[1:]
        or workflow_state in LEGACY_VISUAL_PROOF_WORKFLOW_STATES
    ):
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


class LockUnavailableError(RuntimeError):
    """Raised when another process owns a non-blocking review lock."""


class InterprocessLock:
    """Cross-platform, non-blocking advisory lock backed by a persistent file."""

    def __init__(self, path: Path):
        self.path = path
        self._stream = None

    def acquire(self) -> "InterprocessLock":
        stream = open_private_lock_file(self.path)
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

    def __enter__(self) -> "InterprocessLock":
        return self.acquire()

    def __exit__(self, *_args: object) -> None:
        self.release()


def _existing_mode(path: Path, fallback: int) -> int:
    """Read the mode of one stable, uniquely linked regular target."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return fallback
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(
                f"Il target JSON esistente non può essere un collegamento simbolico: {path}"
            ) from exc
        raise
    try:
        before = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
            or before.st_nlink != 1
            or current.st_nlink != 1
        ):
            raise ValueError(f"Target JSON esistente non sicuro: {path}")

        after = os.fstat(descriptor)
        latest = path.lstat()
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            any(
                getattr(before, field) != getattr(after, field)
                for field in stable_fields
            )
            or any(
                getattr(current, field) != getattr(latest, field)
                for field in stable_fields
            )
            or stat.S_ISLNK(latest.st_mode)
            or not stat.S_ISREG(latest.st_mode)
            or (after.st_dev, after.st_ino) != (latest.st_dev, latest.st_ino)
            or after.st_nlink != 1
            or latest.st_nlink != 1
        ):
            raise ValueError(
                f"Il target JSON esistente è cambiato durante la verifica: {path}"
            )
        return stat.S_IMODE(after.st_mode)
    except FileNotFoundError as exc:
        raise ValueError(
            f"Il target JSON esistente è cambiato durante la verifica: {path}"
        ) from exc
    finally:
        os.close(descriptor)


def _verify_open_temporary_entry(
    path: Path, descriptor: int, *, expected_nlink: int
) -> None:
    """Bind a temporary pathname to its still-open regular-file descriptor."""
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
    except OSError as exc:
        raise ValueError(f"Percorso temporaneo cambiato prima della pubblicazione: {path}") from exc
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
        or opened.st_nlink != expected_nlink
        or current.st_nlink != expected_nlink
        or any(
            getattr(opened, field) != getattr(current, field)
            for field in stable_fields
        )
    ):
        raise ValueError(f"Percorso temporaneo non sicuro: {path}")


def _fchmod_open_file(descriptor: int, mode: int) -> None:
    """Set mode through the owned descriptor; pathname chmod is never safe here."""
    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, mode)


def _append_only_payload(value: dict) -> bytes:
    return (strict_json_text(value, indent=2) + "\n").encode("utf-8")


def _append_only_temporary_path(path: Path, value: dict) -> Path:
    """Return the fixed-size recovery name for one target/value operation."""
    operation = hashlib.sha256()
    operation.update(os.fsencode(path.name))
    operation.update(b"\0")
    operation.update(canonical_json_bytes(value))
    return path.with_name(f"{APPEND_ONLY_TEMP_PREFIX}{operation.hexdigest()}.tmp")


def _read_stable_append_entry(
    path: Path, *, expected_nlink: int
) -> tuple[int, os.stat_result, bytes]:
    """Open and read one stable append-only entry without following symlinks."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            or opened.st_nlink != expected_nlink
            or current.st_nlink != expected_nlink
        ):
            raise ValueError(f"Percorso batch append-only non sicuro: {path.name}")

        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(descriptor)
        latest = path.lstat()
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            any(getattr(opened, field) != getattr(after, field) for field in stable_fields)
            or any(getattr(current, field) != getattr(latest, field) for field in stable_fields)
            or stat.S_ISLNK(latest.st_mode)
            or not stat.S_ISREG(latest.st_mode)
            or (after.st_dev, after.st_ino) != (latest.st_dev, latest.st_ino)
            or after.st_nlink != expected_nlink
            or latest.st_nlink != expected_nlink
        ):
            raise ValueError(
                f"Il batch append-only è cambiato durante la verifica: {path.name}"
            )
        result = descriptor, after, b"".join(chunks)
        descriptor = None
        return result
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(
                f"Percorso batch append-only non sicuro: {path.name}"
            ) from exc
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unlink_verified_append_entry(path: Path, metadata: os.stat_result) -> None:
    """Unlink only the directory entry that was just verified."""
    try:
        latest = path.lstat()
    except OSError as exc:
        raise ValueError(
            f"Il batch append-only è cambiato prima della pulizia: {path.name}"
        ) from exc
    if (
        stat.S_ISLNK(latest.st_mode)
        or not stat.S_ISREG(latest.st_mode)
        or (latest.st_dev, latest.st_ino) != (metadata.st_dev, metadata.st_ino)
        or latest.st_nlink != metadata.st_nlink
    ):
        raise ValueError(
            f"Il batch append-only è cambiato prima della pulizia: {path.name}"
        )
    path.unlink()


def _reconcile_append_only_residue(
    path: Path, temporary: Path, payload: bytes
) -> bool:
    """Recover only this operation's exact, securely-bound crash residue.

    Return True when ``path`` was already published as the other link of the
    deterministic temporary entry.  A lone exact temporary is safe to discard
    and recreate; every ambiguous entry or unrelated hard link fails closed.
    """
    try:
        temporary.lstat()
    except FileNotFoundError:
        return False

    try:
        path.lstat()
    except FileNotFoundError:
        descriptor, metadata, content = _read_stable_append_entry(
            temporary, expected_nlink=1
        )
        try:
            if content != payload:
                raise ValueError(
                    "Il temporaneo append-only residuo contiene dati diversi: "
                    f"{temporary.name}"
                )
            _unlink_verified_append_entry(temporary, metadata)
            fsync_directory(path.parent)
        finally:
            os.close(descriptor)
        return False

    target_descriptor = temporary_descriptor = None
    try:
        target_descriptor, target_metadata, target_content = _read_stable_append_entry(
            path, expected_nlink=2
        )
        (
            temporary_descriptor,
            temporary_metadata,
            temporary_content,
        ) = _read_stable_append_entry(temporary, expected_nlink=2)
        if (
            (target_metadata.st_dev, target_metadata.st_ino)
            != (temporary_metadata.st_dev, temporary_metadata.st_ino)
            or target_content != payload
            or temporary_content != payload
        ):
            raise ValueError(
                "Residuo append-only non riconducibile alla stessa operazione: "
                f"{path.name}"
            )

        _unlink_verified_append_entry(temporary, temporary_metadata)
        after = os.fstat(target_descriptor)
        latest = path.lstat()
        if (
            not stat.S_ISREG(after.st_mode)
            or stat.S_ISLNK(latest.st_mode)
            or not stat.S_ISREG(latest.st_mode)
            or (after.st_dev, after.st_ino) != (latest.st_dev, latest.st_ino)
            or after.st_nlink != 1
            or latest.st_nlink != 1
        ):
            raise ValueError(
                f"Il batch append-only è cambiato durante il recupero: {path.name}"
            )
        fsync_directory(path.parent)
        return True
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if target_descriptor is not None:
            os.close(target_descriptor)


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
        with os.fdopen(
            os.dup(descriptor), "w", encoding="utf-8", newline="\n"
        ) as stream:
            stream.write(strict_json_text(value, indent=2) + "\n")
            stream.flush()
        _fchmod_open_file(descriptor, target_mode)
        os.fsync(descriptor)
        _verify_open_temporary_entry(temporary, descriptor, expected_nlink=1)
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
    payload = _append_only_payload(value)
    temporary = _append_only_temporary_path(path, value)
    if _reconcile_append_only_residue(path, temporary, payload):
        return False
    descriptor = None
    try:
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            # Close the check/create race without ever overwriting an unknown
            # entry.  A valid residue is reconciled; anything else is rejected.
            if _reconcile_append_only_residue(path, temporary, payload):
                return False
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(payload)
            stream.flush()
        _fchmod_open_file(descriptor, 0o600)
        os.fsync(descriptor)
        _verify_open_temporary_entry(temporary, descriptor, expected_nlink=1)
        try:
            os.link(temporary, path)
        except FileExistsError:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            existing_descriptor = None
            try:
                existing_descriptor = os.open(path, flags)
                opened = os.fstat(existing_descriptor)
                current = path.lstat()
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or stat.S_ISLNK(current.st_mode)
                    or not stat.S_ISREG(current.st_mode)
                    or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                    or opened.st_nlink != 1
                    or current.st_nlink != 1
                ):
                    raise ValueError(
                        f"Percorso batch append-only non sicuro: {path.name}"
                    )
                with os.fdopen(existing_descriptor, "r", encoding="utf-8") as stream:
                    existing_descriptor = None
                    existing = strict_json_loads(stream.read())
                    after = os.fstat(stream.fileno())
                    latest = path.lstat()
                    stable_fields = (
                        "st_dev",
                        "st_ino",
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                    )
                    if (
                        any(
                            getattr(opened, field) != getattr(after, field)
                            for field in stable_fields
                        )
                        or after.st_nlink != 1
                        or stat.S_ISLNK(latest.st_mode)
                        or not stat.S_ISREG(latest.st_mode)
                        or (after.st_dev, after.st_ino)
                        != (latest.st_dev, latest.st_ino)
                        or latest.st_nlink != 1
                    ):
                        raise ValueError(
                            f"Il batch append-only è cambiato durante la verifica: {path.name}"
                        )
                    if existing != value:
                        raise ValueError(
                            "Il batch append-only esiste già con contenuto diverso: "
                            f"{path.name}"
                        )
                    if hasattr(os, "fchmod"):
                        os.fchmod(stream.fileno(), 0o600)
            finally:
                if existing_descriptor is not None:
                    os.close(existing_descriptor)
            return False
        try:
            _verify_open_temporary_entry(temporary, descriptor, expected_nlink=2)
            _verify_open_temporary_entry(path, descriptor, expected_nlink=2)
        except ValueError:
            try:
                _unlink_verified_append_entry(path, os.fstat(descriptor))
                fsync_directory(path.parent)
            except (OSError, ValueError):
                pass
            raise
        # First persist the publication, then persist cleanup of the owned
        # second link.  A crash between the two leaves a recognizable twin that
        # the next exact replay can safely reconcile.
        fsync_directory(path.parent)
        temporary_metadata = os.fstat(descriptor)
        _unlink_verified_append_entry(temporary, temporary_metadata)
        _verify_open_temporary_entry(path, descriptor, expected_nlink=1)
        fsync_directory(path.parent)
        _verify_open_temporary_entry(path, descriptor, expected_nlink=1)
        return True
    finally:
        if descriptor is not None:
            # Never remove a predictable-name entry unless it is still bound to
            # the file descriptor created by this call.  In particular, leave
            # a raced-in symlink or foreign hard link untouched and fail closed.
            try:
                _unlink_verified_append_entry(temporary, os.fstat(descriptor))
                fsync_directory(path.parent)
            except (OSError, ValueError):
                pass
            os.close(descriptor)


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

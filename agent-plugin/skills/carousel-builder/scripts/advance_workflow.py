#!/usr/bin/env python3
"""Advance one canonical schema 1.4 workflow state after fail-closed gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    atomic_write_json,
    sha256_json,
    strict_json_loads,
    valid_sha256,
    validate_canonical_workflow_transition,
    validate_workflow_receipts,
)
from review_server import (  # noqa: E402
    RENDER_CONTRACT,
    absolute_input_path,
    manifest_model,
    read_private_json,
    reject_symlink_path,
    validate_state_manifest,
)


QA_REQUIRED_CHECKS = frozenset(
    {
        "manifest_content_match",
        "slide_count_order",
        "dimensions",
        "files_open",
        "fonts",
        "preview_production_parity",
        "no_incomplete_outputs",
    }
)
ARTIFACT_KIND_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
EXPORT_RESULT_SCHEMA = "carousel-builder-export-v1"
QA_REPORT_SCHEMA = "carousel-builder-qa-v1"


def read_json_object(path: Path, *, label: str) -> dict:
    if path.is_symlink():
        raise ValueError(f"{label} non può essere un collegamento simbolico")
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} non trovato: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} non è JSON valido: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} deve contenere un oggetto JSON")
    return value


def validated_revision(manifest: dict) -> int:
    revision = manifest.get("revision", 1)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("revision deve essere un intero non negativo")
    return revision


def require_review_approval(manifest: dict, *, stage: str, revision: int) -> None:
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise ValueError(f"Manca la ricevuta di approvazione {stage}")
    if (
        review.get("last_action") != "approve"
        or review.get("approval_requested") is not True
        or review.get("approval_stage") != stage
        or review.get("applied_manifest_revision") != revision
        or review.get("comments_pending") != 0
        or valid_sha256(review.get("last_feedback_sha256")) is None
        or not isinstance(review.get("last_feedback_id"), str)
        or not review["last_feedback_id"]
    ):
        raise ValueError(
            f"La ricevuta di approvazione {stage} non è completa o non appartiene "
            f"alla revisione {revision}"
        )


def require_no_pending_comments(manifest: dict) -> None:
    review = manifest.get("review")
    pending = review.get("comments_pending") if isinstance(review, dict) else None
    if not isinstance(pending, int) or isinstance(pending, bool) or pending != 0:
        raise ValueError(
            "La transizione è bloccata finché review.comments_pending non è zero"
        )


def require_applied_review_binding(
    state: dict,
    manifest: dict,
    *,
    revision: int,
    receipts: list[dict],
) -> None:
    """Bind the workflow gate to the exact review batch applied to the manifest.

    Advancing the workflow intentionally changes only ``workflow_state`` and the
    bounded receipt ledger, so the session's applied-manifest hash becomes a
    historical hash after the first transition.  Reconstruct only canonical
    ledger prefixes to verify that hash without weakening later transitions.
    """
    review = manifest.get("review")
    if not isinstance(review, dict):
        raise ValueError("Manca la ricevuta review applicata al manifest")

    feedback_id = state.get("applied_feedback_id")
    action = state.get("applied_feedback_action")
    feedback_sha256 = valid_sha256(state.get("applied_feedback_sha256"))
    applied_revision = state.get("applied_manifest_revision")
    applied_manifest_sha256 = valid_sha256(state.get("applied_manifest_sha256"))
    if (
        not isinstance(feedback_id, str)
        or not feedback_id
        or state.get("last_feedback_id") != feedback_id
        or review.get("last_feedback_id") != feedback_id
    ):
        raise ValueError("La ricevuta di sessione non coincide con il feedback applicato")
    if (
        action not in {"feedback", "approve"}
        or state.get("last_action") != action
        or review.get("last_action") != action
    ):
        raise ValueError("L'azione applicata non coincide tra sessione e manifest")
    if (
        feedback_sha256 is None
        or valid_sha256(review.get("last_feedback_sha256")) != feedback_sha256
    ):
        raise ValueError("Il digest del feedback applicato non coincide")
    if (
        not isinstance(applied_revision, int)
        or isinstance(applied_revision, bool)
        or applied_revision != revision
        or review.get("applied_manifest_revision") != revision
    ):
        raise ValueError("La revisione applicata non coincide tra sessione e manifest")
    if applied_manifest_sha256 is None:
        raise ValueError("Manca l'hash del manifest applicato nella sessione")

    current_state = manifest.get("workflow_state")
    current_index = CANONICAL_WORKFLOW_STATES.index(current_state)
    candidates: list[dict] = []
    for origin_index in range(current_index + 1):
        candidate = dict(manifest)
        candidate["workflow_state"] = CANONICAL_WORKFLOW_STATES[origin_index]
        if origin_index == 0:
            candidate.pop("workflow_receipts", None)
            candidates.append(candidate)
            explicit_empty = dict(candidate)
            explicit_empty["workflow_receipts"] = []
            candidates.append(explicit_empty)
        else:
            candidate["workflow_receipts"] = receipts[:origin_index]
            candidates.append(candidate)
    if not any(
        sha256_json(candidate) == applied_manifest_sha256 for candidate in candidates
    ):
        raise ValueError(
            "Il manifest corrente non deriva dall'hash del manifest applicato"
        )


def require_current_visual_proof(model: dict) -> None:
    proof = model.get("proof")
    production = model.get("production")
    if (
        not isinstance(production, dict)
        or production.get("mode") != "renderer"
        or production.get("producer") != RENDER_CONTRACT
    ):
        raise ValueError(
            "La CLI local-editor richiede una prova corrente con production.mode=renderer "
            "e il producer locale"
        )
    if model.get("proof_approved") is not True:
        raise ValueError(
            "La prova visuale non è approvata o non coincide con manifest, asset e renderer correnti"
        )
    if (
        not isinstance(proof, dict)
        or valid_sha256(model.get("render_fingerprint")) is None
        or proof.get("browser") is None
    ):
        raise ValueError("Il contratto della prova visuale corrente è incompleto")


def expected_output_kinds(manifest: dict) -> list[str]:
    production = manifest.get("production")
    values = production.get("expected_outputs") if isinstance(production, dict) else None
    if not isinstance(values, list) or not values:
        raise ValueError("production.expected_outputs deve dichiarare almeno un output")
    normalized: list[str] = []
    aliases = {"contact-sheet": "contact_sheet"}
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError("production.expected_outputs contiene un output non valido")
        kind = aliases.get(value, value)
        if kind not in {"pdf", "png", "contact_sheet"}:
            raise ValueError(f"Output atteso non verificabile dalla CLI: {value!r}")
        if kind not in normalized:
            normalized.append(kind)
    if "pdf" not in normalized:
        raise ValueError("Il contratto renderer locale richiede pdf negli output attesi")
    return normalized


def _absolute_regular_file(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} deve essere un percorso assoluto")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{field} non è un file regolare assoluto esistente")
    return path


def _absolute_directory(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} deve essere un percorso assoluto")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError(f"{field} non è una directory assoluta esistente")
    return path


def validated_artifact_records(
    value: object,
    *,
    field: str,
    expected: list[str],
    slide_count: int,
) -> dict[str, list[Path]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} deve contenere gli artefatti e i relativi SHA-256")
    allowed = set(expected)
    grouped: dict[str, list[Path]] = {}
    seen_paths: set[Path] = set()
    seen_files: set[tuple[int, int]] = set()
    for index, artifact in enumerate(value):
        if not isinstance(artifact, dict) or set(artifact) != {"kind", "path", "sha256"}:
            raise ValueError(f"{field}[{index}] deve contenere kind, path e sha256")
        kind = artifact.get("kind")
        if (
            not isinstance(kind, str)
            or not ARTIFACT_KIND_RE.fullmatch(kind)
            or kind not in allowed
        ):
            raise ValueError(f"{field}[{index}].kind non atteso: {kind!r}")
        path = _absolute_regular_file(
            artifact.get("path"), field=f"{field}[{index}].path"
        ).resolve()
        metadata = path.stat()
        identity = (
            (metadata.st_dev, metadata.st_ino) if metadata.st_ino else None
        )
        if path in seen_paths or (identity is not None and identity in seen_files):
            raise ValueError(f"{field} contiene artefatti duplicati")
        seen_paths.add(path)
        if identity is not None:
            seen_files.add(identity)
        suffix = path.suffix.lower()
        if (kind == "pdf" and suffix != ".pdf") or (
            kind in {"png", "contact_sheet"} and suffix != ".png"
        ):
            raise ValueError(f"{field}[{index}] non ha l'estensione prevista per {kind}")
        expected_digest = valid_sha256(artifact.get("sha256"))
        if expected_digest is None or sha256_regular_file(path) != expected_digest:
            raise ValueError(f"Digest artefatto non valido o non coincidente: {path}")
        grouped.setdefault(kind, []).append(path)

    required_counts = {
        "pdf": 1,
        "png": slide_count,
        "contact_sheet": 1,
    }
    if set(grouped) != allowed:
        raise ValueError(f"{field} non copre esattamente gli output attesi")
    for kind in expected:
        if len(grouped[kind]) != required_counts[kind]:
            raise ValueError(
                f"{field} contiene {len(grouped[kind])} artefatti {kind}; "
                f"attesi {required_counts[kind]}"
            )
    return grouped


def validate_render_result(
    result: dict,
    *,
    manifest: dict,
    model: dict,
    revision: int,
) -> None:
    if (
        result.get("result_schema") != EXPORT_RESULT_SCHEMA
        or result.get("status") != "ok"
        or result.get("revision") != revision
        or result.get("workflow_state") != "rendering"
        or result.get("render_fingerprint") != model.get("render_fingerprint")
        or result.get("contract") != RENDER_CONTRACT
        or result.get("proof_browser") != model["proof"].get("browser")
        or result.get("preview_production_parity") != "exact"
        or result.get("live_session_verified") is not True
        or result.get("approval_verified") is not True
        or result.get("slides") != len(model.get("slides", []))
        or result.get("width") != model.get("format", {}).get("width")
        or result.get("height") != model.get("format", {}).get("height")
    ):
        raise ValueError(
            "Il render-result non attesta stato, revisione, contratto, browser e parità correnti"
        )

    expected = expected_output_kinds(manifest)
    artifacts = validated_artifact_records(
        result.get("artifact_sha256"),
        field="render-result.artifact_sha256",
        expected=expected,
        slide_count=len(model.get("slides", [])),
    )
    pdf = _absolute_regular_file(result.get("output"), field="render-result.output").resolve()
    if pdf.suffix.lower() != ".pdf":
        raise ValueError("render-result.output deve essere un PDF")
    if "pdf" not in expected:
        raise ValueError("Il renderer ha prodotto un PDF non dichiarato negli output attesi")
    if artifacts["pdf"] != [pdf]:
        raise ValueError("render-result.output non coincide con l'artefatto PDF attestato")

    if "png" in expected:
        png_dir = _absolute_directory(result.get("png_dir"), field="render-result.png_dir")
        png_entries = list(png_dir.iterdir())
        try:
            png_metadata = [(path, path.lstat()) for path in png_entries]
        except OSError as exc:
            raise ValueError(f"Impossibile verificare la directory PNG: {exc}") from exc
        if any(
            path.suffix.lower() != ".png" or not stat.S_ISREG(metadata.st_mode)
            for path, metadata in png_metadata
        ):
            raise ValueError(
                "La directory PNG deve contenere esclusivamente file regolari .png"
            )
        png_files = sorted(path.resolve() for path in png_entries)
        if (
            result.get("png_files") != len(model.get("slides", []))
            or len(png_files) != result.get("png_files")
            or set(png_files) != set(artifacts["png"])
        ):
            raise ValueError("Il set PNG prodotto non coincide con le slide correnti")
    elif "png_dir" in result or "png_files" in result:
        raise ValueError("Il render-result contiene PNG non dichiarati negli output attesi")

    if "contact_sheet" in expected:
        contact = _absolute_regular_file(
            result.get("contact_sheet"), field="render-result.contact_sheet"
        )
        if contact.suffix.lower() != ".png":
            raise ValueError("render-result.contact_sheet deve essere un PNG")
        if artifacts["contact_sheet"] != [contact.resolve()]:
            raise ValueError("render-result.contact_sheet non coincide con l'artefatto attestato")
    elif "contact_sheet" in result:
        raise ValueError("Il render-result contiene una contact sheet non dichiarata")


def sha256_regular_file(path: Path) -> str:
    """Hash one stable, singly linked regular file without following symlinks."""
    if path.is_symlink():
        raise ValueError(f"L'artefatto non può essere un collegamento simbolico: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"Impossibile aprire l'artefatto {path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        try:
            current = path.lstat()
        except OSError as exc:
            raise ValueError(f"Artefatto sostituito prima della verifica: {path}") from exc
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
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or before.st_nlink != 1
            or current.st_nlink != 1
            or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
            or any(
                getattr(before, field) != getattr(current, field)
                for field in stable_fields
            )
        ):
            raise ValueError(f"Artefatto non regolare o sostituito: {path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        try:
            latest = path.lstat()
        except OSError as exc:
            raise ValueError(f"Artefatto sostituito durante la verifica: {path}") from exc
        if (
            not stat.S_ISREG(after.st_mode)
            or not stat.S_ISREG(latest.st_mode)
            or after.st_nlink != 1
            or latest.st_nlink != 1
            or (after.st_dev, after.st_ino) != (latest.st_dev, latest.st_ino)
            or any(
                getattr(before, field) != getattr(after, field)
                for field in stable_fields
            )
            or any(
                getattr(current, field) != getattr(latest, field)
                for field in stable_fields
            )
        ):
            raise ValueError(f"Artefatto modificato durante la verifica: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def validate_qa_report(
    report: dict,
    *,
    manifest: dict,
    model: dict,
    revision: int,
    render_evidence_sha256: str,
    render_result: dict,
) -> None:
    if (
        report.get("report_schema") != QA_REPORT_SCHEMA
        or report.get("status") != "pass"
        or report.get("revision") != revision
        or report.get("workflow_state") != "qa"
        or report.get("render_fingerprint") != model.get("render_fingerprint")
        or report.get("proof_browser") != model.get("proof", {}).get("browser")
        or report.get("render_evidence_sha256") != render_evidence_sha256
    ):
        raise ValueError(
            "Il qa-report non è pass o non è legato a stato, revisione, fingerprint e browser correnti"
        )
    checks = report.get("checks")
    if (
        not isinstance(checks, dict)
        or not QA_REQUIRED_CHECKS.issubset(checks)
        or any(value is not True for value in checks.values())
    ):
        missing = sorted(QA_REQUIRED_CHECKS - set(checks or {}))
        suffix = f"; mancanti: {', '.join(missing)}" if missing else ""
        raise ValueError(f"Il qa-report non supera tutti i controlli obbligatori{suffix}")

    expected = expected_output_kinds(manifest)
    report_artifacts = validated_artifact_records(
        report.get("artifacts"),
        field="qa-report.artifacts",
        expected=expected,
        slide_count=len(model.get("slides", [])),
    )
    render_artifacts = validated_artifact_records(
        render_result.get("artifact_sha256"),
        field="render-result.artifact_sha256",
        expected=expected,
        slide_count=len(model.get("slides", [])),
    )
    if report.get("artifacts") != render_result.get("artifact_sha256"):
        raise ValueError(
            "Il qa-report non attesta esattamente gli stessi artefatti del render-result"
        )
    if report_artifacts != render_artifacts:
        raise ValueError(
            "Gli artefatti QA non coincidono con quelli verificati durante il render"
        )


def advance_workflow(
    manifest_path: Path,
    *,
    session_dir_path: Path,
    expected_state: str,
    expected_revision: int,
    target: str,
    render_result_path: Path | None = None,
    qa_report_path: Path | None = None,
) -> dict:
    manifest_input = absolute_input_path(manifest_path)
    reject_symlink_path(manifest_input, field="Il manifest")
    session_dir_input = absolute_input_path(session_dir_path)
    reject_symlink_path(session_dir_input, field="La cartella di sessione")
    if not session_dir_input.is_dir():
        raise ValueError(
            f"La cartella di sessione non esiste: {session_dir_input}"
        )
    render_result_input = None
    if render_result_path is not None:
        render_result_input = absolute_input_path(render_result_path)
        reject_symlink_path(render_result_input, field="Il render-result")
    qa_report_input = None
    if qa_report_path is not None:
        qa_report_input = absolute_input_path(qa_report_path)
        reject_symlink_path(qa_report_input, field="Il qa-report")
    manifest_path = manifest_input.resolve()
    session_dir = session_dir_input.resolve()
    lock_path = manifest_path.with_name(f".{manifest_path.name}.review.lock")
    transaction_lock_path = session_dir / ".review-transaction.lock"
    with InterprocessLock(lock_path), InterprocessLock(transaction_lock_path):
        state = read_private_json(session_dir / "session-state.json")
        validate_state_manifest(state, manifest_path)
        last_feedback_id = state.get("last_feedback_id")
        applied_feedback_id = state.get("applied_feedback_id")
        if last_feedback_id and last_feedback_id != applied_feedback_id:
            raise ValueError(
                "La transizione è bloccata: un feedback durevole attende ancora di essere applicato"
            )
        manifest = read_json_object(manifest_path, label="Manifest")
        if manifest.get("schema_version") != "1.4":
            raise ValueError("La CLI avanza soltanto manifest schema 1.4")
        revision = validated_revision(manifest)
        current = manifest.get("workflow_state")
        if current != expected_state:
            raise ValueError(
                f"workflow_state corrente {current!r} non coincide con --expected-state {expected_state!r}"
            )
        if revision != expected_revision:
            raise ValueError(
                f"revision corrente {revision} non coincide con --expected-revision {expected_revision}"
            )
        validate_canonical_workflow_transition(current, target)
        receipts = validate_workflow_receipts(
            manifest.get("workflow_receipts", []),
            current_state=current,
            require_complete=True,
        )
        require_applied_review_binding(
            state,
            manifest,
            revision=revision,
            receipts=receipts,
        )
        model = manifest_model(manifest_path, manifest=manifest)
        evidence: dict

        if render_result_path is not None and target not in {"qa", "consegnato"}:
            raise ValueError(
                "--render-result è consentito soltanto per rendering -> qa o qa -> consegnato"
            )
        if qa_report_path is not None and target != "consegnato":
            raise ValueError("--qa-report è consentito soltanto per qa -> consegnato")

        if current == "bozza":
            require_review_approval(manifest, stage="profile_text", revision=revision)
            evidence = {"kind": "profile_text_approval", "review": manifest["review"]}
        elif current == "testi_approvati":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            evidence = {
                "kind": "visual_proof_approval",
                "review": manifest["review"],
                "proof": manifest.get("proof"),
            }
        elif current == "prova_visuale_approvata":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            expected_output_kinds(manifest)
            evidence = {
                "kind": "production_start",
                "proof": manifest.get("proof"),
                "production": manifest.get("production"),
            }
        elif current == "rendering":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            if render_result_path is None:
                raise ValueError("rendering -> qa richiede --render-result")
            result = read_json_object(render_result_input, label="render-result")
            validate_render_result(result, manifest=manifest, model=model, revision=revision)
            evidence = result
        elif current == "qa":
            require_no_pending_comments(manifest)
            require_review_approval(manifest, stage="visual_proof", revision=revision)
            require_current_visual_proof(model)
            if qa_report_path is None:
                raise ValueError("qa -> consegnato richiede --qa-report")
            if render_result_path is None:
                raise ValueError("qa -> consegnato richiede anche --render-result")
            if not receipts or receipts[-1]["from"] != "rendering":
                raise ValueError(
                    "qa -> consegnato richiede la ricevuta durevole rendering -> qa"
                )
            report = read_json_object(qa_report_input, label="qa-report")
            render_result = read_json_object(render_result_input, label="render-result")
            if sha256_json(render_result) != receipts[-1]["evidence_sha256"]:
                raise ValueError(
                    "Il render-result non coincide con l'evidenza durevole rendering -> qa"
                )
            validate_render_result(
                render_result, manifest=manifest, model=model, revision=revision
            )
            validate_qa_report(
                report,
                manifest=manifest,
                model=model,
                revision=revision,
                render_evidence_sha256=receipts[-1]["evidence_sha256"],
                render_result=render_result,
            )
            evidence = report

        updated = dict(manifest)
        updated["workflow_state"] = target
        receipts.append(
            {
                "from": current,
                "to": target,
                "revision": revision,
                "render_fingerprint": model["render_fingerprint"],
                "evidence_sha256": sha256_json(evidence),
                "advanced_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        updated["workflow_receipts"] = receipts
        atomic_write_json(manifest_path, updated, private_parent=False)
        return {
            "status": "advanced",
            "manifest": str(manifest_path),
            "revision": revision,
            "from": current,
            "to": target,
            "render_fingerprint": model.get("render_fingerprint"),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument(
        "--expected-state", required=True, choices=CANONICAL_WORKFLOW_STATES
    )
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--to", required=True, choices=CANONICAL_WORKFLOW_STATES)
    parser.add_argument("--render-result", type=Path)
    parser.add_argument("--qa-report", type=Path)
    args = parser.parse_args()
    try:
        result = advance_workflow(
            args.manifest,
            session_dir_path=args.session_dir,
            expected_state=args.expected_state,
            expected_revision=args.expected_revision,
            target=args.to,
            render_result_path=args.render_result,
            qa_report_path=args.qa_report,
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

#!/usr/bin/env python3
"""Inspect a carousel manifest and report the next safe workflow action as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from manifest_contract import CURRENT_SCHEMA_VERSION  # noqa: E402
from review_core import (  # noqa: E402
    CANONICAL_WORKFLOW_STATES,
    COMBINED_APPROVAL_SCOPE,
    InterprocessLock,
    LockUnavailableError,
    validate_workflow_receipts,
)
from advance_workflow import require_applied_review_binding  # noqa: E402
from review_server import (  # noqa: E402
    absolute_input_path,
    manifest_model,
    read_private_json,
    reject_symlink_path,
    validate_state_manifest,
)


def _review_is_current(manifest: dict, *, revision: int, stage: str) -> bool:
    review = manifest.get("review")
    stage_matches = isinstance(review, dict) and (
        review.get("approval_stage") == stage
        or (
            review.get("approval_scope") == COMBINED_APPROVAL_SCOPE
            and review.get("approval_stage") == "profile_text"
            and stage in {"profile_text", "visual_proof"}
        )
    )
    return bool(
        isinstance(review, dict)
        and review.get("last_action") == "approve"
        and review.get("approval_requested") is True
        and stage_matches
        and review.get("applied_manifest_revision") == revision
        and review.get("comments_pending", 0) == 0
    )


def _advance_command(
    manifest_path: Path,
    session_dir: Path,
    *,
    state: str,
    revision: int,
    target: str,
) -> list[str]:
    return [
        "python3",
        str(SCRIPT_DIR / "advance_workflow.py"),
        str(manifest_path),
        "--session-dir",
        str(session_dir),
        "--expected-state",
        state,
        "--expected-revision",
        str(revision),
        "--to",
        target,
    ]


def _next_action(
    manifest_path: Path,
    session_dir: Path | None,
    manifest: dict,
    model: dict,
    *,
    feedback_pending: bool | None,
    session_binding_error: str | None,
) -> dict:
    state = model["workflow_state"]
    revision = model["revision"]
    if feedback_pending:
        if session_dir is None:
            return {"kind": "session_required", "reason": "feedback_pending_unknown"}
        return {
            "kind": "apply_feedback",
            "reason": "feedback_pending",
            "command": [
                "python3",
                str(SCRIPT_DIR / "apply_review.py"),
                str(manifest_path),
                str(session_dir / "feedback.json"),
                "--session-dir",
                str(session_dir),
            ],
        }
    if session_dir is None:
        return {
            "kind": "session_required",
            "reason": "passa --session-dir per verificare feedback e avanzamenti",
        }
    if session_binding_error is not None:
        return {
            "kind": "blocked",
            "reason": "session_manifest_binding",
            "error": session_binding_error,
        }
    if state in {"prova_visuale_approvata", "rendering", "qa"} and (
        model.get("proof_approved") is not True
    ):
        return {
            "kind": "blocked",
            "reason": "visual_proof_not_current",
            "error": (
                "La prova visuale non coincide più con manifest, asset, browser "
                "o renderer correnti"
            ),
        }
    if state == "bozza":
        if _review_is_current(manifest, revision=revision, stage="profile_text"):
            return {
                "kind": "advance_workflow",
                "to": "testi_approvati",
                "command": _advance_command(
                    manifest_path,
                    session_dir,
                    state=state,
                    revision=revision,
                    target="testi_approvati",
                ),
            }
        return {"kind": "review", "stage": "profile_text"}
    if state == "testi_approvati":
        if (
            model.get("proof_approved") is True
            and _review_is_current(manifest, revision=revision, stage="visual_proof")
        ):
            return {
                "kind": "advance_workflow",
                "to": "prova_visuale_approvata",
                "command": _advance_command(
                    manifest_path,
                    session_dir,
                    state=state,
                    revision=revision,
                    target="prova_visuale_approvata",
                ),
            }
        return {"kind": "review", "stage": "visual_proof"}
    if state == "prova_visuale_approvata":
        return {
            "kind": "advance_workflow",
            "to": "rendering",
            "command": _advance_command(
                manifest_path,
                session_dir,
                state=state,
                revision=revision,
                target="rendering",
            ),
        }
    if state == "rendering":
        return {
            "kind": "export",
            "expected_outputs": model["production"]["expected_outputs"],
            "requires_result_json": True,
        }
    if state == "qa":
        return {
            "kind": "advance_workflow",
            "to": "consegnato",
            "requires": ["render_result", "qa_report"],
        }
    return {"kind": "complete", "state": "consegnato"}


def build_status(manifest_input: Path, *, session_dir_input: Path | None = None) -> dict:
    manifest_absolute = absolute_input_path(manifest_input)
    reject_symlink_path(manifest_absolute, field="Il manifest")
    manifest_path = manifest_absolute.resolve()
    session_dir = None
    if session_dir_input is not None:
        session_absolute = absolute_input_path(session_dir_input)
        reject_symlink_path(session_absolute, field="La cartella di sessione")
        if not session_absolute.is_dir():
            raise ValueError(f"La cartella di sessione non esiste: {session_absolute}")
        session_dir = session_absolute.resolve()

    lock_paths = [manifest_path.with_name(f".{manifest_path.name}.review.lock")]
    if session_dir is not None:
        lock_paths.append(session_dir / ".review-transaction.lock")
    locks = [InterprocessLock(path) for path in lock_paths]
    try:
        for lock in locks:
            lock.acquire()
        manifest = read_private_json(manifest_path)
        model = manifest_model(manifest_path, manifest=manifest)
        state = None
        feedback_pending = None
        session_binding_error = None
        if session_dir is not None:
            state = read_private_json(session_dir / "session-state.json")
            validate_state_manifest(state, manifest_path)
            last_id = state.get("last_feedback_id")
            applied_id = state.get("applied_feedback_id")
            feedback_pending = bool(last_id and last_id != applied_id)
            if isinstance(manifest.get("review"), dict) and not feedback_pending:
                try:
                    receipts = validate_workflow_receipts(
                        manifest.get("workflow_receipts", []),
                        current_state=model["workflow_state"],
                        require_complete=model["schema_version"] == "1.4",
                    )
                    require_applied_review_binding(
                        state,
                        manifest,
                        revision=model["revision"],
                        receipts=receipts,
                    )
                except ValueError as exc:
                    session_binding_error = str(exc)
        next_action = _next_action(
            manifest_path,
            session_dir,
            manifest,
            model,
            feedback_pending=feedback_pending,
            session_binding_error=session_binding_error,
        )
        return {
            "status": "ok",
            "manifest": str(manifest_path),
            "schema_version": model["schema_version"],
            "current_schema_version": ".".join(map(str, CURRENT_SCHEMA_VERSION)),
            "revision": model["revision"],
            "workflow_state": model["workflow_state"],
            "approval_checkpoint": model["approval_checkpoint"],
            "proof_approved": model["proof_approved"],
            "render_fingerprint": model["render_fingerprint"],
            "feedback_pending": feedback_pending,
            "last_feedback_id": state.get("last_feedback_id") if state else None,
            "applied_feedback_id": state.get("applied_feedback_id") if state else None,
            "session_binding_ok": (
                None if state is None or not isinstance(manifest.get("review"), dict)
                else session_binding_error is None
            ),
            "session_binding_error": session_binding_error,
            "expected_outputs": model["production"]["expected_outputs"],
            "next_action": next_action,
        }
    finally:
        for lock in reversed(locks):
            lock.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path)
    parser.add_argument(
        "--compact", action="store_true", help="Emetti JSON su una sola riga"
    )
    args = parser.parse_args()
    try:
        result = build_status(args.manifest, session_dir_input=args.session_dir)
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=None if args.compact else 2,
                separators=(",", ":") if args.compact else None,
            )
        )
        return 0
    except (LockUnavailableError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

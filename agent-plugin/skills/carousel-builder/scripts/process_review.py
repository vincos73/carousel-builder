#!/usr/bin/env python3
"""Apply one review batch and advance its approval checkpoint when gates pass."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from advance_workflow import advance_workflow  # noqa: E402
from carousel_status import build_status  # noqa: E402
from review_core import (  # noqa: E402
    CANONICAL_WORKFLOW_STATES,
    COMBINED_APPROVAL_SCOPE,
    LockUnavailableError,
    strict_json_loads,
)
from review_server import absolute_input_path, reject_symlink_path  # noqa: E402


APPROVAL_TARGETS = {
    "profile_text": "testi_approvati",
    "visual_proof": "prova_visuale_approvata",
}


def _json_object(value: str, *, label: str) -> dict:
    try:
        parsed = strict_json_loads(value)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} non ha restituito JSON valido: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} deve restituire un oggetto JSON")
    return parsed


def _feedback_stage(feedback_path: Path) -> tuple[str, str | None, str | None]:
    try:
        feedback = strict_json_loads(feedback_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Batch feedback non trovato: {feedback_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Batch feedback non valido: {exc}") from exc
    if not isinstance(feedback, dict):
        raise ValueError("Il batch feedback deve contenere un oggetto JSON")
    action = feedback.get("action")
    stage = feedback.get("approval_stage")
    scope = feedback.get("approval_scope")
    if action not in {"feedback", "approve"}:
        raise ValueError("Il batch feedback non contiene un'azione valida")
    if stage is not None and stage not in APPROVAL_TARGETS:
        raise ValueError("Il batch feedback contiene un approval_stage non valido")
    if scope is not None and scope != COMBINED_APPROVAL_SCOPE:
        raise ValueError("Il batch feedback contiene un approval_scope non valido")
    if scope == COMBINED_APPROVAL_SCOPE and stage != "profile_text":
        raise ValueError("Il batch combinato deve partire dal checkpoint profile_text")
    return action, stage, scope


def process_review(
    manifest_input: Path,
    feedback_input: Path,
    *,
    session_dir_input: Path,
) -> dict:
    manifest_path = absolute_input_path(manifest_input)
    feedback_path = absolute_input_path(feedback_input)
    session_dir = absolute_input_path(session_dir_input)
    reject_symlink_path(manifest_path, field="Il manifest")
    reject_symlink_path(feedback_path, field="Il batch feedback")
    reject_symlink_path(session_dir, field="La cartella di sessione")

    action, approval_stage, approval_scope = _feedback_stage(feedback_path)
    applied = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "apply_review.py"),
            str(manifest_path),
            str(feedback_path),
            "--session-dir",
            str(session_dir),
        ],
        cwd=SCRIPT_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    output = applied.stdout.strip() if applied.returncode == 0 else applied.stderr.strip()
    apply_result = _json_object(output, label="apply_review.py")
    if applied.returncode != 0 or apply_result.get("status") == "error":
        raise ValueError(apply_result.get("error") or "Applicazione del feedback fallita")

    status = build_status(manifest_path, session_dir_input=session_dir)
    result = {
        "status": "processed",
        "action": action,
        "apply": apply_result,
        "workflow": status,
        "advanced": None,
        "transitions": [],
    }
    if action != "approve":
        return result

    resolved_stage = approval_stage or apply_result.get("approval_stage")
    targets = (
        ["testi_approvati", "prova_visuale_approvata"]
        if approval_scope == COMBINED_APPROVAL_SCOPE
        else [APPROVAL_TARGETS.get(resolved_stage)]
    )
    if any(target is None for target in targets):
        raise ValueError("L'approvazione non dichiara il checkpoint da avanzare")
    for target in targets:
        current_state = status.get("workflow_state")
        if (
            current_state in CANONICAL_WORKFLOW_STATES
            and CANONICAL_WORKFLOW_STATES.index(current_state)
            >= CANONICAL_WORKFLOW_STATES.index(target)
        ):
            continue
        next_action = status.get("next_action")
        if not isinstance(next_action, dict) or (
            next_action.get("kind") != "advance_workflow"
            or next_action.get("to") != target
        ):
            result["status"] = "approval_blocked"
            result["workflow"] = status
            return result
        advanced = advance_workflow(
            manifest_path,
            session_dir_path=session_dir,
            expected_state=status["workflow_state"],
            expected_revision=status["revision"],
            target=target,
        )
        result["transitions"].append(advanced)
        result["advanced"] = advanced
        status = build_status(manifest_path, session_dir_input=session_dir)
    result["workflow"] = status
    if not result["transitions"]:
        result["status"] = "already_processed"
        return result
    result["status"] = "advanced"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = process_review(
            args.manifest,
            args.feedback,
            session_dir_input=args.session_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] != "approval_blocked" else 3
    except (LockUnavailableError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

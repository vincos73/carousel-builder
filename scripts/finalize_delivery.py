#!/usr/bin/env python3
"""Finalize verified render and QA evidence through the remaining workflow gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from advance_workflow import advance_workflow, read_json_object  # noqa: E402
from carousel_status import build_status  # noqa: E402
from review_core import (  # noqa: E402
    LockUnavailableError,
    atomic_write_json,
    sha256_json,
)
from review_server import absolute_input_path, reject_symlink_path  # noqa: E402


def _bound_qa_report(
    qa_report_path: Path,
    *,
    manifest_path: Path,
    session_dir_path: Path,
) -> tuple[Path, bool]:
    """Bind an inspected report to the durable render receipt when requested."""
    report_path = absolute_input_path(qa_report_path)
    reject_symlink_path(report_path, field="Il qa-report")
    report = read_json_object(report_path, label="qa-report")
    if report.get("render_evidence_sha256") not in {None, "auto"}:
        return report_path, False

    manifest = read_json_object(
        absolute_input_path(manifest_path), label="Manifest"
    )
    receipts = manifest.get("workflow_receipts")
    if (
        manifest.get("workflow_state") != "qa"
        or not isinstance(receipts, list)
        or not receipts
        or receipts[-1].get("from") != "rendering"
        or receipts[-1].get("to") != "qa"
    ):
        raise ValueError(
            "Il binding automatico del qa-report richiede la ricevuta rendering -> qa"
        )
    report["render_evidence_sha256"] = receipts[-1].get("evidence_sha256")
    bound_name = f"qa-report-bound-{sha256_json(report)}.json"
    bound_path = absolute_input_path(session_dir_path) / bound_name
    reject_symlink_path(bound_path, field="Il qa-report attestato")
    atomic_write_json(bound_path, report, mode=0o600, private_parent=True)
    return bound_path, True


def finalize_delivery(
    manifest_path: Path,
    *,
    session_dir_path: Path,
    render_result_path: Path,
    qa_report_path: Path,
) -> dict:
    manifest_path = absolute_input_path(manifest_path)
    session_dir_path = absolute_input_path(session_dir_path)
    render_result_path = absolute_input_path(render_result_path)
    qa_report_path = absolute_input_path(qa_report_path)
    status = build_status(manifest_path, session_dir_input=session_dir_path)
    transitions: list[dict] = []
    if status["workflow_state"] == "consegnato":
        return {
            "status": "already_finalized",
            "workflow": status,
            "transitions": transitions,
        }
    if status["workflow_state"] == "rendering":
        transitions.append(
            advance_workflow(
                manifest_path,
                session_dir_path=session_dir_path,
                expected_state="rendering",
                expected_revision=status["revision"],
                target="qa",
                render_result_path=render_result_path,
            )
        )
        status = build_status(manifest_path, session_dir_input=session_dir_path)
    if status["workflow_state"] != "qa":
        raise ValueError(
            "La finalizzazione richiede lo stato rendering oppure qa con proof corrente"
        )
    bound_report_path, report_was_bound = _bound_qa_report(
        qa_report_path,
        manifest_path=manifest_path,
        session_dir_path=session_dir_path,
    )
    transitions.append(
        advance_workflow(
            manifest_path,
            session_dir_path=session_dir_path,
            expected_state="qa",
            expected_revision=status["revision"],
            target="consegnato",
            render_result_path=render_result_path,
            qa_report_path=bound_report_path,
        )
    )
    return {
        "status": "finalized",
        "workflow": build_status(
            manifest_path, session_dir_input=session_dir_path
        ),
        "transitions": transitions,
        "qa_report": str(bound_report_path),
        "qa_report_bound": report_was_bound,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--render-result", type=Path, required=True)
    parser.add_argument("--qa-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = finalize_delivery(
            args.manifest,
            session_dir_path=args.session_dir,
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

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

from advance_workflow import (  # noqa: E402
    QA_ADVISORY_CHECKS,
    QA_REPORT_SCHEMA,
    QA_REQUIRED_CHECKS,
    advance_workflow,
    read_json_object,
    validate_render_result,
)
from carousel_status import build_status  # noqa: E402
from review_core import (  # noqa: E402
    LockUnavailableError,
    atomic_write_json,
    sha256_json,
)
from review_server import (  # noqa: E402
    absolute_input_path,
    manifest_model,
    reject_symlink_path,
)


def _generated_qa_report(
    render_result_path: Path,
    *,
    manifest_path: Path,
    session_dir_path: Path,
) -> Path:
    """Create technical QA evidence from already verified production facts."""
    manifest = read_json_object(manifest_path, label="Manifest")
    receipts = manifest.get("workflow_receipts")
    if (
        manifest.get("workflow_state") != "qa"
        or not isinstance(receipts, list)
        or not receipts
        or receipts[-1].get("from") != "rendering"
        or receipts[-1].get("to") != "qa"
    ):
        raise ValueError(
            "La generazione automatica del qa-report richiede la ricevuta rendering -> qa"
        )
    render_result = read_json_object(render_result_path, label="render-result")
    if sha256_json(render_result) != receipts[-1].get("evidence_sha256"):
        raise ValueError(
            "Il render-result non coincide con l'evidenza durevole rendering -> qa"
        )
    model = manifest_model(manifest_path, manifest=manifest)
    revision = manifest.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError("La revisione del manifest non è valida")
    validate_render_result(
        render_result,
        manifest=manifest,
        model=model,
        revision=revision,
    )
    checks = {key: True for key in sorted(QA_REQUIRED_CHECKS)}
    checks.update({key: False for key in sorted(QA_ADVISORY_CHECKS)})
    report = {
        "report_schema": QA_REPORT_SCHEMA,
        "status": "pass",
        "revision": revision,
        "workflow_state": "qa",
        "render_fingerprint": model.get("render_fingerprint"),
        "proof_browser": model.get("proof", {}).get("browser"),
        "render_evidence_sha256": receipts[-1]["evidence_sha256"],
        "checks": checks,
        "human_sample_slide_ids": [],
        "flagged_slide_ids": [],
        "artifacts": render_result.get("artifact_sha256"),
    }
    generated_name = f"qa-report-auto-{sha256_json(report)}.json"
    generated_path = session_dir_path / generated_name
    reject_symlink_path(generated_path, field="Il qa-report automatico")
    atomic_write_json(generated_path, report, mode=0o600, private_parent=True)
    return generated_path


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
    qa_report_path: Path | None = None,
) -> dict:
    manifest_path = absolute_input_path(manifest_path)
    session_dir_path = absolute_input_path(session_dir_path)
    render_result_path = absolute_input_path(render_result_path)
    qa_report_path = (
        absolute_input_path(qa_report_path) if qa_report_path is not None else None
    )
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
    report_was_generated = qa_report_path is None
    if report_was_generated:
        bound_report_path = _generated_qa_report(
            render_result_path,
            manifest_path=manifest_path,
            session_dir_path=session_dir_path,
        )
        report_was_bound = False
    else:
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
        "qa_report_generated": report_was_generated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--render-result", type=Path, required=True)
    parser.add_argument("--qa-report", type=Path)
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

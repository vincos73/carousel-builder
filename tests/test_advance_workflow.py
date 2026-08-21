"""Regression tests for explicit, evidence-bound workflow transitions."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib
from functools import lru_cache
from pathlib import Path
from unittest import mock

from support import SCRIPTS, base_manifest, write_json

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import advance_workflow  # noqa: E402
import finalize_delivery  # noqa: E402
import review_core  # noqa: E402
import review_server  # noqa: E402


def approval_receipt(stage: str, revision: int = 1) -> dict:
    return {
        "mode": "visual",
        "last_feedback_id": "feedback-approved",
        "last_action": "approve",
        "last_feedback_sha256": "a" * 64,
        "applied_manifest_revision": revision,
        "approval_requested": True,
        "approval_stage": stage,
        "comments_pending": 0,
    }


def workflow_receipts(state: str, revision: int = 1) -> list[dict]:
    states = advance_workflow.CANONICAL_WORKFLOW_STATES
    return [
        {
            "from": current,
            "to": states[index + 1],
            "revision": revision,
            "render_fingerprint": "c" * 64,
            "evidence_sha256": hashlib.sha256(
                f"{current}:{states[index + 1]}".encode()
            ).hexdigest(),
            "advanced_at": "2026-01-01T00:00:00+00:00",
        }
        for index, current in enumerate(states[: states.index(state)])
    ]


@lru_cache(maxsize=None)
def valid_png(width: int = 1440, height: int = 1800) -> bytes:
    """A small, fully decodable RGBA PNG fixture at the production geometry."""
    row = bytes((18, 52, 86, 255)) * width
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def valid_pdf(
    page_count: int,
    width: float = 810,
    height: float = 1012.5,
    stream_payload: bytes = b"",
) -> bytes:
    """A minimal xref-backed PDF at export_review_pdf.cjs page geometry."""
    objects: list[bytes] = []
    page_refs = [3 + index * 2 for index in range(page_count)]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(f"{ref} 0 R".encode() for ref in page_refs)
    objects.append(
        b"<< /Type /Pages /Kids [ "
        + kids
        + f" ] /Count {page_count} >>".encode()
    )
    for page_ref in page_refs:
        content_ref = page_ref + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources <<>> /Contents {content_ref} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(stream_payload)} >>\nstream\n".encode()
            + stream_payload
            + b"\nendstream"
        )

    output = bytearray(b"%PDF-1.7\n%\x80\x80\x80\x80\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


class AdvanceWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        # Keep artifact paths unique even if a platform reuses a just-released
        # TemporaryDirectory inode during this short test process.
        self.workdir = Path(self.temporary.name) / uuid.uuid4().hex
        self.workdir.mkdir()
        self.manifest_path = self.workdir / "manifest.json"
        self.session_dir = self.workdir / "session"
        self.session_dir.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read_manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict) -> None:
        write_json(self.manifest_path, manifest)
        review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
        feedback_id = review.get("last_feedback_id", "feedback-approved")
        action = review.get("last_action", "approve")
        feedback_sha256 = review.get("last_feedback_sha256", "a" * 64)
        revision = manifest.get("revision", 1)
        write_json(
            self.session_dir / "session-state.json",
            {
                "manifest": str(self.manifest_path),
                "last_feedback_id": feedback_id,
                "applied_feedback_id": feedback_id,
                "last_action": action,
                "applied_feedback_action": action,
                "applied_feedback_sha256": feedback_sha256,
                "applied_manifest_revision": revision,
                "applied_manifest_sha256": review_core.sha256_json(manifest),
            },
        )

    def write_session_state(self, **overrides: object) -> None:
        manifest = self.read_manifest()
        review = manifest.get("review") if isinstance(manifest.get("review"), dict) else {}
        feedback_id = review.get("last_feedback_id", "feedback-approved")
        action = review.get("last_action", "approve")
        value = {
            "manifest": str(self.manifest_path),
            "last_feedback_id": feedback_id,
            "applied_feedback_id": feedback_id,
            "last_action": action,
            "applied_feedback_action": action,
            "applied_feedback_sha256": review.get("last_feedback_sha256", "a" * 64),
            "applied_manifest_revision": manifest.get("revision", 1),
            "applied_manifest_sha256": review_core.sha256_json(manifest),
        }
        value.update(overrides)
        write_json(self.session_dir / "session-state.json", value)

    def approved_manifest(self, state: str) -> dict:
        manifest = base_manifest()
        manifest["workflow_state"] = state
        manifest["workflow_receipts"] = workflow_receipts(state)
        manifest["review"] = approval_receipt("visual_proof")
        manifest["proof"].update(
            {
                "approved": False,
                "style_system_verified": True,
                "browser": {"engine": "chromium", "major": 140},
            }
        )
        model = review_server.manifest_model(self.manifest_path, manifest=manifest)
        manifest["proof"]["render_fingerprint"] = model["render_fingerprint"]
        manifest["proof"]["approved"] = True
        self.assertTrue(
            review_server.manifest_model(
                self.manifest_path, manifest=manifest
            )["proof_approved"]
        )
        return manifest

    def advance(self, **kwargs: object) -> dict:
        return advance_workflow.advance_workflow(
            self.manifest_path,
            session_dir_path=self.session_dir,
            expected_state=kwargs.pop("expected_state"),
            expected_revision=kwargs.pop("expected_revision", 1),
            target=kwargs.pop("target"),
            **kwargs,
        )

    def test_profile_approval_advances_with_a_receipt_and_never_approves_proof(self) -> None:
        manifest = base_manifest()
        manifest["review"] = approval_receipt("profile_text")
        before = copy.deepcopy(manifest)
        self.write_manifest(manifest)

        result = self.advance(expected_state="bozza", target="testi_approvati")

        written = self.read_manifest()
        self.assertEqual(result["to"], "testi_approvati")
        self.assertEqual(written["workflow_state"], "testi_approvati")
        self.assertEqual(len(written["workflow_receipts"]), 1)
        receipt = written["workflow_receipts"][0]
        self.assertEqual(receipt["from"], "bozza")
        self.assertEqual(receipt["to"], "testi_approvati")
        self.assertEqual(receipt["revision"], 1)
        self.assertEqual(len(receipt["evidence_sha256"]), 64)
        self.assertEqual(len(receipt["render_fingerprint"]), 64)
        before.pop("workflow_state")
        comparable = dict(written)
        comparable.pop("workflow_state")
        comparable.pop("workflow_receipts")
        self.assertEqual(comparable, before)
        self.assertFalse(written["proof"]["approved"])

    def test_pending_durable_feedback_blocks_every_transition(self) -> None:
        manifest = base_manifest()
        manifest["review"] = approval_receipt("profile_text")
        self.write_manifest(manifest)
        self.write_session_state(
            last_feedback_id="feedback-new",
            applied_feedback_id="feedback-approved",
            last_action="feedback",
        )

        with self.assertRaisesRegex(ValueError, "attende ancora"):
            self.advance(expected_state="bozza", target="testi_approvati")

        self.assertEqual(self.read_manifest()["workflow_state"], "bozza")

    def test_session_must_be_bound_to_the_same_manifest(self) -> None:
        manifest = base_manifest()
        manifest["review"] = approval_receipt("profile_text")
        self.write_manifest(manifest)
        self.write_session_state(manifest=str(self.workdir / "other.json"))

        with self.assertRaisesRegex(ValueError, "manifest diverso"):
            self.advance(expected_state="bozza", target="testi_approvati")

        self.assertEqual(self.read_manifest()["workflow_state"], "bozza")

    def test_session_receipt_must_match_review_id_action_digest_revision_and_hash(self) -> None:
        cases = {
            "feedback id": {
                "last_feedback_id": "feedback-other",
                "applied_feedback_id": "feedback-other",
            },
            "azione": {
                "last_action": "feedback",
                "applied_feedback_action": "feedback",
            },
            "digest": {"applied_feedback_sha256": "b" * 64},
            "revisione": {"applied_manifest_revision": 2},
            "hash": {"applied_manifest_sha256": "c" * 64},
        }
        for label, overrides in cases.items():
            manifest = base_manifest()
            manifest["review"] = approval_receipt("profile_text")
            self.write_manifest(manifest)
            self.write_session_state(**overrides)
            original = self.manifest_path.read_bytes()

            with self.subTest(label=label), self.assertRaises(ValueError):
                self.advance(expected_state="bozza", target="testi_approvati")

            self.assertEqual(self.manifest_path.read_bytes(), original)

    def test_applied_manifest_hash_remains_valid_after_canonical_advances(self) -> None:
        manifest = self.approved_manifest("testi_approvati")
        self.write_manifest(manifest)

        self.advance(
            expected_state="testi_approvati", target="prova_visuale_approvata"
        )
        # The state still carries the hash recorded when review was applied at
        # testi_approvati. A canonical receipt append must remain verifiable.
        self.advance(
            expected_state="prova_visuale_approvata", target="rendering"
        )

        written = self.read_manifest()
        self.assertEqual(written["workflow_state"], "rendering")
        self.assertEqual(len(written["workflow_receipts"]), 3)

    def test_rejects_missing_receipt_skip_and_stale_compare_and_swap(self) -> None:
        manifest = base_manifest()
        self.write_manifest(manifest)
        original = self.manifest_path.read_bytes()
        for expected_state, revision, target in (
            ("bozza", 1, "testi_approvati"),
            ("bozza", 1, "prova_visuale_approvata"),
            ("testi_approvati", 1, "prova_visuale_approvata"),
            ("bozza", 2, "testi_approvati"),
        ):
            with self.subTest(
                expected_state=expected_state, revision=revision, target=target
            ), self.assertRaises(ValueError):
                self.advance(
                    expected_state=expected_state,
                    expected_revision=revision,
                    target=target,
                )
            self.assertEqual(self.manifest_path.read_bytes(), original)

    def test_visual_approval_must_be_current_and_bound_to_its_receipt(self) -> None:
        manifest = self.approved_manifest("testi_approvati")
        self.write_manifest(manifest)
        self.advance(
            expected_state="testi_approvati", target="prova_visuale_approvata"
        )
        self.assertEqual(
            self.read_manifest()["workflow_state"], "prova_visuale_approvata"
        )

        stale = self.approved_manifest("testi_approvati")
        stale["proof"]["render_fingerprint"] = "b" * 64
        self.write_manifest(stale)
        with self.assertRaisesRegex(ValueError, "prova visuale"):
            self.advance(
                expected_state="testi_approvati", target="prova_visuale_approvata"
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "testi_approvati")

    def test_pending_comments_block_every_post_text_transition(self) -> None:
        for state, target in (
            ("testi_approvati", "prova_visuale_approvata"),
            ("prova_visuale_approvata", "rendering"),
            ("rendering", "qa"),
            ("qa", "consegnato"),
        ):
            manifest = self.approved_manifest(state)
            manifest["review"]["comments_pending"] = 1
            self.write_manifest(manifest)
            with self.subTest(state=state), self.assertRaisesRegex(
                ValueError, "comments_pending"
            ):
                self.advance(expected_state=state, target=target)
            self.assertEqual(self.read_manifest()["workflow_state"], state)

    def test_a_later_noop_feedback_cannot_override_the_visual_approval(self) -> None:
        manifest = self.approved_manifest("prova_visuale_approvata")
        manifest["review"].update(
            last_action="feedback", approval_requested=False, comments_pending=0
        )
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "approvazione visual_proof"):
            self.advance(
                expected_state="prova_visuale_approvata", target="rendering"
            )
        self.assertEqual(
            self.read_manifest()["workflow_state"], "prova_visuale_approvata"
        )

    def make_render_outputs(self, manifest: dict) -> tuple[Path, Path, dict]:
        pdf = self.workdir / "carousel.pdf"
        model = review_server.manifest_model(self.manifest_path, manifest=manifest)
        pdf.write_bytes(valid_pdf(len(model["slides"])))
        png_dir = self.workdir / "png"
        png_dir.mkdir()
        for index, slide in enumerate(model["slides"], start=1):
            (png_dir / f"{index:02d}-{slide['id']}.png").write_bytes(valid_png())
        result = {
            "result_schema": advance_workflow.EXPORT_RESULT_SCHEMA,
            "status": "ok",
            "output": str(pdf),
            "slides": len(model["slides"]),
            "width": model["format"]["width"],
            "height": model["format"]["height"],
            "contract": review_server.RENDER_CONTRACT,
            "revision": manifest["revision"],
            "workflow_state": "rendering",
            "render_fingerprint": model["render_fingerprint"],
            "proof_browser": manifest["proof"]["browser"],
            "preview_production_parity": "exact",
            "live_session_verified": True,
            "approval_verified": True,
            "png_dir": str(png_dir),
            "png_files": len(model["slides"]),
        }
        result["artifact_sha256"] = [
            {
                "kind": kind,
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for kind, path in [
                ("pdf", pdf),
                *(("png", path) for path in sorted(png_dir.glob("*.png"))),
            ]
        ]
        return pdf, png_dir, result

    def test_render_result_is_required_and_binds_rendering_to_qa(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "--render-result"):
            self.advance(expected_state="rendering", target="qa")

        _pdf, _png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        self.advance(
            expected_state="rendering",
            target="qa",
            render_result_path=result_path,
        )
        self.assertEqual(self.read_manifest()["workflow_state"], "qa")

    def test_local_cli_rejects_layout_and_external_adapter_modes_clearly(self) -> None:
        for mode, producer in (
            ("layout", ""),
            ("adapter", "external-adapter"),
        ):
            manifest = base_manifest()
            manifest["workflow_state"] = "prova_visuale_approvata"
            manifest["workflow_receipts"] = workflow_receipts(
                "prova_visuale_approvata"
            )
            manifest["review"] = approval_receipt("visual_proof")
            manifest["production"].update(mode=mode, producer=producer)
            manifest["proof"].update(
                {
                    "approved": True,
                    "style_system_verified": True,
                    "browser": {"engine": "chromium", "major": 140},
                    "render_fingerprint": "a" * 64,
                }
            )
            self.write_manifest(manifest)
            with self.subTest(mode=mode), self.assertRaisesRegex(
                ValueError, "local-editor"
            ):
                self.advance(
                    expected_state="prova_visuale_approvata", target="rendering"
                )
            self.assertEqual(
                self.read_manifest()["workflow_state"], "prova_visuale_approvata"
            )

    def qa_report(self, manifest: dict, pdf: Path, png_dir: Path) -> dict:
        artifacts = []
        for kind, path in [
            ("pdf", pdf),
            *(("png", path) for path in sorted(png_dir.glob("*.png"))),
        ]:
            artifacts.append(
                {
                    "kind": kind,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        model = review_server.manifest_model(self.manifest_path, manifest=manifest)
        return {
            "report_schema": advance_workflow.QA_REPORT_SCHEMA,
            "status": "pass",
            "revision": manifest["revision"],
            "workflow_state": "qa",
            "render_fingerprint": model["render_fingerprint"],
            "proof_browser": manifest["proof"]["browser"],
            "render_evidence_sha256": manifest["workflow_receipts"][-1][
                "evidence_sha256"
            ],
            "checks": {key: True for key in advance_workflow.QA_REQUIRED_CHECKS},
            "human_sample_slide_ids": model["proof"]["required_slide_ids"],
            "flagged_slide_ids": [],
            "artifacts": artifacts,
        }

    def prepare_qa(self) -> tuple[dict, Path, Path, Path]:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        pdf, png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        self.advance(
            expected_state="rendering",
            target="qa",
            render_result_path=result_path,
        )
        return self.read_manifest(), pdf, png_dir, result_path

    def test_qa_report_hashes_every_expected_artifact_before_delivery(self) -> None:
        manifest, pdf, png_dir, result_path = self.prepare_qa()
        report_path = self.workdir / "qa-report.json"
        write_json(report_path, self.qa_report(manifest, pdf, png_dir))

        self.advance(
            expected_state="qa",
            target="consegnato",
            qa_report_path=report_path,
            render_result_path=result_path,
        )
        self.assertEqual(self.read_manifest()["workflow_state"], "consegnato")
        self.assertEqual(
            self.read_manifest()["workflow_receipts"][-1]["to"], "consegnato"
        )

    def test_finalize_delivery_traverses_both_machine_checked_final_gates(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        pdf, png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        report = self.qa_report(manifest, pdf, png_dir)
        report["render_evidence_sha256"] = "auto"
        report_path = self.workdir / "qa-report.json"
        write_json(report_path, report)

        finalized = finalize_delivery.finalize_delivery(
            self.manifest_path,
            session_dir_path=self.session_dir,
            render_result_path=result_path,
            qa_report_path=report_path,
        )

        self.assertEqual(finalized["status"], "finalized")
        self.assertEqual(
            [transition["to"] for transition in finalized["transitions"]],
            ["qa", "consegnato"],
        )
        self.assertTrue(finalized["qa_report_bound"])
        bound_report = Path(finalized["qa_report"])
        self.assertTrue(bound_report.is_file())
        self.assertEqual(
            json.loads(bound_report.read_text(encoding="utf-8"))[
                "render_evidence_sha256"
            ],
            review_core.sha256_json(result),
        )
        self.assertEqual(self.read_manifest()["workflow_state"], "consegnato")

    def test_finalize_delivery_generates_the_technical_qa_report(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        _pdf, _png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)

        finalized = finalize_delivery.finalize_delivery(
            self.manifest_path,
            session_dir_path=self.session_dir,
            render_result_path=result_path,
        )

        self.assertEqual(finalized["status"], "finalized")
        self.assertTrue(finalized["qa_report_generated"])
        self.assertFalse(finalized["qa_report_bound"])
        generated_report = json.loads(
            Path(finalized["qa_report"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            generated_report["artifacts"], result["artifact_sha256"]
        )
        self.assertTrue(
            all(
                generated_report["checks"][key]
                for key in advance_workflow.QA_REQUIRED_CHECKS
            )
        )
        self.assertFalse(generated_report["checks"]["fonts"])
        self.assertFalse(generated_report["checks"]["human_sample_review"])
        self.assertEqual(generated_report["human_sample_slide_ids"], [])
        self.assertEqual(self.read_manifest()["workflow_state"], "consegnato")

    def test_generated_qa_report_never_masks_a_tampered_artifact(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        pdf, _png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        pdf.write_bytes(b"tampered")

        with self.assertRaisesRegex(ValueError, "Digest artefatto"):
            finalize_delivery.finalize_delivery(
                self.manifest_path,
                session_dir_path=self.session_dir,
                render_result_path=result_path,
            )

        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    def test_render_result_rejects_a_tampered_artifact_before_qa(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        pdf, _png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        pdf.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Digest artefatto"):
            self.advance(
                expected_state="rendering",
                target="qa",
                render_result_path=result_path,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    def _assert_render_artifact_decoder_rejects(
        self, *, kind: str, replacement: bytes, message: str
    ) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        pdf, png_dir, result = self.make_render_outputs(manifest)
        if kind == "pdf":
            artifact = pdf
        else:
            artifact = sorted(png_dir.glob("*.png"))[0]
        artifact.write_bytes(replacement)
        for entry in result["artifact_sha256"]:
            if Path(entry["path"]) == artifact:
                entry["sha256"] = hashlib.sha256(replacement).hexdigest()
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        with self.assertRaisesRegex(ValueError, message):
            self.advance(
                expected_state="rendering", target="qa", render_result_path=result_path
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    def test_render_result_rejects_corrupt_png_after_digest_matches(self) -> None:
        self._assert_render_artifact_decoder_rejects(
            kind="png", replacement=b"not a png", message="PNG non decodificabile"
        )

    def test_render_result_rejects_truncated_png_after_digest_matches(self) -> None:
        self._assert_render_artifact_decoder_rejects(
            kind="png", replacement=valid_png()[:-1], message="PNG troncato|PNG IEND non valido|PNG incompleto"
        )

    def test_render_result_rejects_wrong_png_dimensions_after_digest_matches(self) -> None:
        self._assert_render_artifact_decoder_rejects(
            kind="png", replacement=valid_png(1, 1), message="PNG dimensioni"
        )

    def test_render_result_rejects_corrupt_pdf_after_digest_matches(self) -> None:
        self._assert_render_artifact_decoder_rejects(
            kind="pdf", replacement=b"%PDF-1.7\n%%EOF\n", message="PDF senza oggetti|PDF non parsabile"
        )

    def test_render_result_rejects_truncated_pdf_after_digest_matches(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        pdf, _png_dir, result = self.make_render_outputs(manifest)
        replacement = valid_pdf(len(review_server.manifest_model(
            self.manifest_path, manifest=manifest
        )["slides"]))[:-20]
        pdf.write_bytes(replacement)
        result["artifact_sha256"][0]["sha256"] = hashlib.sha256(replacement).hexdigest()
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        with self.assertRaisesRegex(ValueError, "PDF non parsabile o troncato"):
            self.advance(
                expected_state="rendering", target="qa", render_result_path=result_path
            )

    def test_pdf_ignores_obj_like_bytes_inside_a_valid_stream(self) -> None:
        path = self.workdir / "stream-obj-like.pdf"
        path.write_bytes(
            valid_pdf(
                1,
                stream_payload=b"99 0 obj\n<< /Type /Catalog >>\nendobj\n",
            )
        )
        advance_workflow.validate_pdf_artifact(
            path, expected_width=1440, expected_height=1800, expected_pages=1
        )

    def test_pdf_uses_trailer_root_and_rejects_a_fake_non_root_catalog(self) -> None:
        path = self.workdir / "fake-root.pdf"
        path.write_bytes(valid_pdf(1).replace(b"/Root 1 0 R", b"/Root 3 0 R"))
        with self.assertRaisesRegex(ValueError, "trailer.Root non punta"):
            advance_workflow.validate_pdf_artifact(
                path, expected_width=1440, expected_height=1800, expected_pages=1
            )

    def test_pdf_rejects_missing_or_truncated_xref(self) -> None:
        original = valid_pdf(1)
        for replacement in (
            original.replace(b"startxref", b"startxreF"),
            original[: original.find(b"xref\n") + len(b"xref\n")],
        ):
            path = self.workdir / f"bad-xref-{uuid.uuid4().hex}.pdf"
            path.write_bytes(replacement)
            with self.subTest(size=len(replacement)), self.assertRaisesRegex(
                ValueError, "startxref|xref|troncato"
            ):
                advance_workflow.validate_pdf_artifact(
                    path, expected_width=1440, expected_height=1800, expected_pages=1
                )

    def test_pdf_size_limit_is_a_value_error_before_reading_the_body(self) -> None:
        path = self.workdir / "pdf-bomb.pdf"
        with path.open("wb") as stream:
            stream.truncate(advance_workflow._pdf_byte_limit(1) + 1)
        with self.assertRaisesRegex(ValueError, "oltre il limite"):
            advance_workflow.validate_pdf_artifact(
                path, expected_width=1440, expected_height=1800, expected_pages=1
            )

    def test_png_idat_and_decompressed_raw_limits_are_explicit(self) -> None:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                struct.pack(">I", len(payload))
                + kind
                + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
            )

        idat_path = self.workdir / "png-idat-bomb.png"
        oversized_idat = b"\x00" * 33
        idat_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", oversized_idat)
            + chunk(b"IEND", b"")
        )
        with mock.patch.object(
            advance_workflow, "MAX_PNG_IDAT_BYTES", 32
        ), self.assertRaisesRegex(ValueError, "IDAT oltre il limite"):
            advance_workflow.validate_png_artifact(
                idat_path, expected_width=1, expected_height=1
            )

        raw_path = self.workdir / "png-raw-bomb.png"
        raw_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 10_000, 10_000, 16, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b""))
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(ValueError, "decompressione oltre il limite"):
            advance_workflow.validate_png_artifact(
                raw_path, expected_width=10_000, expected_height=10_000
            )

    def test_render_result_rejects_wrong_pdf_dimensions_after_digest_matches(self) -> None:
        self._assert_render_artifact_decoder_rejects(
            kind="pdf",
            replacement=valid_pdf(4, 1440, 1800),
            message="Page.MediaBox",
        )

    def test_artifact_hash_rejects_a_preexisting_hard_link(self) -> None:
        victim = self.workdir / "victim.pdf"
        victim.write_bytes(b"external-content")
        artifact = self.workdir / "artifact.pdf"
        os.link(victim, artifact)

        with self.assertRaisesRegex(ValueError, "non regolare|sostituito"):
            advance_workflow.sha256_regular_file(artifact)

        self.assertEqual(victim.read_bytes(), b"external-content")

    def test_artifact_hash_opens_the_descriptor_in_binary_mode(self) -> None:
        artifact = self.workdir / "artifact.png"
        payload = b"prefix\r\nsuffix\x1aafter-eof"
        artifact.write_bytes(payload)
        original_open = os.open
        binary_flag = getattr(os, "O_BINARY", 0x8000)
        captured_flags: list[int] = []

        def binary_aware_open(path: Path, flags: int) -> int:
            captured_flags.append(flags)
            return original_open(path, flags & ~binary_flag)

        with mock.patch.object(
            advance_workflow.os, "O_BINARY", binary_flag, create=True
        ), mock.patch.object(
            advance_workflow.os, "open", side_effect=binary_aware_open
        ):
            digest = advance_workflow.sha256_regular_file(artifact)

        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertTrue(captured_flags)
        self.assertTrue(captured_flags[0] & binary_flag)

    @unittest.skipIf(
        os.name == "nt",
        "Windows impedisce già la sostituzione mentre l'artefatto è aperto",
    )
    def test_artifact_hash_rejects_path_replacement_during_read(self) -> None:
        artifact = self.workdir / "artifact.pdf"
        artifact.write_bytes(b"original-content")
        replacement = self.workdir / "replacement.pdf"
        replacement.write_bytes(b"replacement-data")
        original_read = os.read
        replaced = False

        def replace_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            chunk = original_read(descriptor, size)
            if not replaced:
                os.replace(replacement, artifact)
                replaced = True
            return chunk

        with mock.patch.object(
            advance_workflow.os, "read", side_effect=replace_after_first_read
        ), self.assertRaisesRegex(ValueError, "modificato durante"):
            advance_workflow.sha256_regular_file(artifact)

        self.assertTrue(replaced)

    def test_render_result_rejects_foreign_file_in_png_directory(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        _pdf, png_dir, result = self.make_render_outputs(manifest)
        (png_dir / "notes.txt").write_text("foreign", encoding="utf-8")
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)

        with self.assertRaisesRegex(ValueError, "directory PNG"):
            self.advance(
                expected_state="rendering", target="qa", render_result_path=result_path
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    def test_render_result_rejects_subdirectory_in_png_directory(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        _pdf, png_dir, result = self.make_render_outputs(manifest)
        (png_dir / "unexpected").mkdir()
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)

        with self.assertRaisesRegex(ValueError, "directory PNG"):
            self.advance(
                expected_state="rendering", target="qa", render_result_path=result_path
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    def test_render_result_rejects_symlink_in_png_directory(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        _pdf, png_dir, result = self.make_render_outputs(manifest)
        source = next(png_dir.glob("*.png"))
        link = png_dir / "unexpected.png"
        try:
            link.symlink_to(source)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symlink non supportati: {exc}")
        result_path = self.workdir / "render-result.json"
        write_json(result_path, result)

        with self.assertRaisesRegex(ValueError, "directory PNG"):
            self.advance(
                expected_state="rendering", target="qa", render_result_path=result_path
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    def test_render_result_symlink_is_rejected_without_advancing(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        _pdf, _png_dir, result = self.make_render_outputs(manifest)
        result_path = self.workdir / "render-result-real.json"
        link_path = self.workdir / "render-result.json"
        write_json(result_path, result)
        link_path.symlink_to(result_path)
        with self.assertRaisesRegex(ValueError, "collegamento simbolico"):
            self.advance(
                expected_state="rendering",
                target="qa",
                render_result_path=link_path,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibili su Windows")
    def test_manifest_rejects_a_user_controlled_parent_symlink(self) -> None:
        real_parent = self.workdir / "real"
        real_manifest = real_parent / "manifest.json"
        manifest = base_manifest()
        manifest["review"] = approval_receipt("profile_text")
        write_json(real_manifest, manifest)
        alias = self.workdir / "alias"
        alias.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "attraversare un collegamento simbolico"):
            advance_workflow.advance_workflow(
                alias / "manifest.json",
                session_dir_path=self.session_dir,
                expected_state="bozza",
                expected_revision=1,
                target="testi_approvati",
            )

        self.assertEqual(
            json.loads(real_manifest.read_text(encoding="utf-8"))["workflow_state"],
            "bozza",
        )

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibili su Windows")
    def test_render_result_rejects_a_user_controlled_parent_symlink(self) -> None:
        manifest = self.approved_manifest("rendering")
        self.write_manifest(manifest)
        _pdf, _png_dir, result = self.make_render_outputs(manifest)
        real_parent = self.workdir / "render-evidence"
        result_path = real_parent / "render-result.json"
        write_json(result_path, result)
        alias = self.workdir / "render-alias"
        alias.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "attraversare un collegamento simbolico"):
            self.advance(
                expected_state="rendering",
                target="qa",
                render_result_path=alias / result_path.name,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "rendering")

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibili su Windows")
    def test_qa_report_rejects_a_user_controlled_parent_symlink(self) -> None:
        manifest, pdf, png_dir, result_path = self.prepare_qa()
        real_parent = self.workdir / "qa-evidence"
        report_path = real_parent / "qa-report.json"
        write_json(report_path, self.qa_report(manifest, pdf, png_dir))
        alias = self.workdir / "qa-alias"
        alias.symlink_to(real_parent, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "attraversare un collegamento simbolico"):
            self.advance(
                expected_state="qa",
                target="consegnato",
                qa_report_path=alias / report_path.name,
                render_result_path=result_path,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "qa")

    def test_tampered_artifact_or_failed_technical_check_never_delivers(self) -> None:
        manifest, pdf, png_dir, result_path = self.prepare_qa()
        report = self.qa_report(manifest, pdf, png_dir)
        report["checks"]["dimensions"] = False
        report_path = self.workdir / "qa-report.json"
        write_json(report_path, report)
        with self.assertRaisesRegex(ValueError, "controlli obbligatori"):
            self.advance(
                expected_state="qa", target="consegnato",
                qa_report_path=report_path, render_result_path=result_path,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "qa")

        report["checks"]["dimensions"] = True
        write_json(report_path, report)
        pdf.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Digest artefatto"):
            self.advance(
                expected_state="qa", target="consegnato",
                qa_report_path=report_path, render_result_path=result_path,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "qa")

    def test_delivery_rejects_artifacts_different_from_the_render_result(self) -> None:
        manifest, pdf, png_dir, result_path = self.prepare_qa()
        report = self.qa_report(manifest, pdf, png_dir)
        replacement = self.workdir / "replacement.pdf"
        replacement.write_bytes(valid_pdf(len(review_server.manifest_model(
            self.manifest_path, manifest=manifest
        )["slides"])))
        report["artifacts"][0] = {
            "kind": "pdf",
            "path": str(replacement),
            "sha256": hashlib.sha256(replacement.read_bytes()).hexdigest(),
        }
        report_path = self.workdir / "qa-report.json"
        write_json(report_path, report)

        with self.assertRaisesRegex(ValueError, "stessi artefatti"):
            self.advance(
                expected_state="qa", target="consegnato",
                qa_report_path=report_path, render_result_path=result_path,
            )
        self.assertEqual(self.read_manifest()["workflow_state"], "qa")

    def test_atomic_write_fault_preserves_the_previous_manifest(self) -> None:
        manifest = base_manifest()
        manifest["review"] = approval_receipt("profile_text")
        self.write_manifest(manifest)
        original = self.manifest_path.read_bytes()
        with mock.patch.object(
            advance_workflow, "atomic_write_json", side_effect=OSError("write failed")
        ):
            with self.assertRaisesRegex(OSError, "write failed"):
                self.advance(expected_state="bozza", target="testi_approvati")
        self.assertEqual(self.manifest_path.read_bytes(), original)

    def test_cli_refuses_a_concurrent_manifest_writer(self) -> None:
        manifest = base_manifest()
        manifest["review"] = approval_receipt("profile_text")
        self.write_manifest(manifest)
        lock_path = self.manifest_path.with_name(f".{self.manifest_path.name}.review.lock")
        with review_core.InterprocessLock(lock_path):
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS / "advance_workflow.py"),
                    str(self.manifest_path),
                    "--session-dir",
                    str(self.session_dir),
                    "--expected-state",
                    "bozza",
                    "--expected-revision",
                    "1",
                    "--to",
                    "testi_approvati",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("già in uso", json.loads(result.stderr)["error"])
        self.assertEqual(self.read_manifest()["workflow_state"], "bozza")

    def test_legacy_manifest_is_readable_elsewhere_but_not_mutated_by_the_cli(self) -> None:
        manifest = base_manifest()
        manifest["schema_version"] = "1.2"
        manifest["review"] = approval_receipt("profile_text")
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "schema 1.4"):
            self.advance(expected_state="bozza", target="testi_approvati")
        self.assertEqual(self.read_manifest()["workflow_state"], "bozza")


if __name__ == "__main__":
    unittest.main()

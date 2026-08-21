from __future__ import annotations

import base64
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from support import SCRIPTS, base_manifest, write_json

import sys

sys.path.insert(0, str(SCRIPTS))

import attach_cover_asset  # noqa: E402
import process_review  # noqa: E402
import review_server  # noqa: E402


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FastWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest_path = self.root / "manifest.json"
        self.session_dir = self.root / "session"
        self.session_dir.mkdir()
        manifest = base_manifest()
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        manifest["cover_mode"] = "typographic"
        write_json(self.manifest_path, manifest)
        write_json(
            self.session_dir / "session-state.json",
            {
                "manifest": str(self.manifest_path.resolve()),
                "token": "t" * 32,
                "last_feedback_id": None,
                "applied_feedback_id": None,
                "manifest_revision": 1,
            },
        )

    def _submit_profile_approval(
        self,
        *,
        combined: bool = False,
        visual_style: str | None = None,
    ) -> Path:
        model = review_server.manifest_model(
            self.manifest_path, include_internal=True
        )
        feedback_id = str(uuid.uuid4())
        payload = {
            "feedback_id": feedback_id,
            "action": "approve",
            "base_revision": model["revision"],
            "base_workflow_state": model["workflow_state"],
            "render_fingerprint": model["render_fingerprint"],
            "slides": [
                {
                    field: slide.get(field, [] if "_" in field else "")
                    for field in review_server.RENDER_SLIDE_FIELDS
                }
                for slide in model["slides"]
            ],
            "comments": [],
            "overall_note": "",
            "visual_style_system": visual_style or model["visual_proofs"]["selected_style_system"],
            "logo_mode": model["logo_mode"],
            "cover_mode": model["cover_mode"],
        }
        if combined:
            payload.update(
                {
                    "approval_scope": "profile_text_and_visual",
                    "proof_slide_ids": model["proof"]["required_slide_ids"],
                    "style_system_verified": True,
                    "proof_browser": {"engine": "chromium", "major": 140},
                }
            )
        feedback = review_server.validate_feedback(payload, model)
        archive = review_server.feedback_archive_path(self.session_dir, feedback_id)
        write_json(archive, feedback)
        write_json(self.session_dir / "feedback.json", feedback)
        state = json.loads(
            (self.session_dir / "session-state.json").read_text(encoding="utf-8")
        )
        state.update(
            {
                "last_feedback_id": feedback_id,
                "last_feedback_path": str(archive),
                "last_action": "approve",
            }
        )
        write_json(self.session_dir / "session-state.json", state)
        return archive

    def test_process_review_applies_and_advances_one_approval_checkpoint(self) -> None:
        archive = self._submit_profile_approval()

        result = process_review.process_review(
            self.manifest_path,
            archive,
            session_dir_input=self.session_dir,
        )

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "advanced")
        self.assertEqual(result["advanced"]["to"], "testi_approvati")
        self.assertEqual(manifest["workflow_state"], "testi_approvati")
        self.assertEqual(len(manifest["workflow_receipts"]), 1)

    def test_combined_approval_advances_both_durable_checkpoints(self) -> None:
        archive = self._submit_profile_approval(combined=True)

        result = process_review.process_review(
            self.manifest_path,
            archive,
            session_dir_input=self.session_dir,
        )

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "advanced")
        self.assertEqual(
            [transition["to"] for transition in result["transitions"]],
            ["testi_approvati", "prova_visuale_approvata"],
        )
        self.assertEqual(manifest["workflow_state"], "prova_visuale_approvata")
        self.assertEqual(len(manifest["workflow_receipts"]), 2)
        self.assertTrue(manifest["proof"]["approved"])
        self.assertEqual(
            manifest["review"]["approval_scope"],
            "profile_text_and_visual",
        )

    def test_combined_approval_accepts_local_renderer_capability_defaults(self) -> None:
        archive = self._submit_profile_approval(
            combined=True,
            visual_style="corporate-modular",
        )
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        original_fingerprint = review_server.manifest_model(self.manifest_path)[
            "render_fingerprint"
        ]
        manifest["production"]["supported_style_systems"] = ["editorial-frame"]
        write_json(self.manifest_path, manifest)
        self.assertEqual(
            review_server.manifest_model(self.manifest_path)["render_fingerprint"],
            original_fingerprint,
        )

        result = process_review.process_review(
            self.manifest_path,
            archive,
            session_dir_input=self.session_dir,
        )

        applied = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "advanced")
        self.assertEqual(applied["visual_style_system"], "corporate-modular")
        self.assertEqual(applied["workflow_state"], "prova_visuale_approvata")
        self.assertEqual(len(applied["workflow_receipts"]), 2)

    def test_post_approval_cover_attachment_preserves_editorial_receipt(self) -> None:
        archive = self._submit_profile_approval()
        process_review.process_review(
            self.manifest_path,
            archive,
            session_dir_input=self.session_dir,
        )
        source = self.root / "generated.png"
        source.write_bytes(ONE_PIXEL_PNG)

        result = attach_cover_asset.attach_cover_asset(
            self.manifest_path,
            source,
            session_dir_input=self.session_dir,
            expected_revision=1,
            mode="generated",
            position="50% 50%",
            alt_text="Illustrazione verticale di prova.",
            concepts=["prova", "velocità"],
            metaphor="Una corsia libera",
            prompt="Illustrazione editoriale verticale senza testo.",
        )

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "attached")
        self.assertEqual(manifest["workflow_state"], "testi_approvati")
        self.assertEqual(manifest["revision"], 2)
        self.assertEqual(manifest["cover_mode"], "generated")
        self.assertTrue((self.root / manifest["cover_image"]).is_file())
        self.assertEqual(len(manifest["workflow_receipts"]), 1)
        self.assertEqual(manifest["workflow_receipts"][0]["to"], "testi_approvati")
        self.assertFalse(manifest["proof"]["approved"])
        self.assertEqual(manifest["review"]["last_action"], "feedback")
        self.assertTrue(result["review"]["apply"]["cover_asset_attached"])

    def test_cover_attachment_rejects_stale_revision_before_copying(self) -> None:
        archive = self._submit_profile_approval()
        process_review.process_review(
            self.manifest_path,
            archive,
            session_dir_input=self.session_dir,
        )
        source = self.root / "generated.png"
        source.write_bytes(ONE_PIXEL_PNG)

        with self.assertRaisesRegex(ValueError, "expected-revision"):
            attach_cover_asset.attach_cover_asset(
                self.manifest_path,
                source,
                session_dir_input=self.session_dir,
                expected_revision=99,
                mode="generated",
                position="50% 50%",
                alt_text="Illustrazione verticale di prova.",
                concepts=[],
                metaphor="",
                prompt="",
            )

        self.assertFalse((self.root / "assets").exists())

    def test_cover_attachment_rejects_invalid_metadata_before_copying(self) -> None:
        archive = self._submit_profile_approval()
        process_review.process_review(
            self.manifest_path,
            archive,
            session_dir_input=self.session_dir,
        )
        source = self.root / "generated.png"
        source.write_bytes(ONE_PIXEL_PNG)

        with self.assertRaisesRegex(ValueError, "alt_text"):
            attach_cover_asset.attach_cover_asset(
                self.manifest_path,
                source,
                session_dir_input=self.session_dir,
                expected_revision=1,
                mode="generated",
                position="50% 50%",
                alt_text="",
                concepts=[],
                metaphor="",
                prompt="",
            )

        self.assertFalse((self.root / "assets").exists())


if __name__ == "__main__":
    unittest.main()

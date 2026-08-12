import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import SCRIPTS, base_manifest, set_workflow_state, write_json

sys.path.insert(0, str(SCRIPTS))
import carousel_status  # noqa: E402


class CarouselStatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest_path = self.root / "manifest.json"
        self.session_dir = self.root / "session"
        self.state_path = self.session_dir / "session-state.json"
        write_json(self.manifest_path, base_manifest())
        write_json(
            self.state_path,
            {
                "manifest": str(self.manifest_path.resolve()),
                "last_feedback_id": None,
                "applied_feedback_id": None,
            },
        )

    def test_reports_review_as_the_first_safe_action(self):
        result = carousel_status.build_status(
            self.manifest_path, session_dir_input=self.session_dir
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["workflow_state"], "bozza")
        self.assertFalse(result["feedback_pending"])
        self.assertEqual(
            result["next_action"], {"kind": "review", "stage": "profile_text"}
        )

    def test_pending_feedback_takes_priority(self):
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["last_feedback_id"] = "feedback-pending"
        write_json(self.state_path, state)
        result = carousel_status.build_status(
            self.manifest_path, session_dir_input=self.session_dir
        )
        self.assertTrue(result["feedback_pending"])
        self.assertEqual(result["next_action"]["kind"], "apply_feedback")
        self.assertIn("apply_review.py", " ".join(result["next_action"]["command"]))

    def test_without_session_is_a_static_validation(self):
        result = carousel_status.build_status(self.manifest_path)
        self.assertIsNone(result["feedback_pending"])
        self.assertEqual(result["next_action"]["kind"], "session_required")

    def test_incoherent_applied_receipt_is_reported_before_an_advance(self):
        manifest = base_manifest()
        manifest["review"] = {
            "last_feedback_id": "feedback-approved",
            "last_action": "approve",
            "last_feedback_sha256": "a" * 64,
            "applied_manifest_revision": 1,
            "approval_requested": True,
            "approval_stage": "profile_text",
            "comments_pending": 0,
        }
        write_json(self.manifest_path, manifest)
        write_json(
            self.state_path,
            {
                "manifest": str(self.manifest_path.resolve()),
                "last_feedback_id": "feedback-approved",
                "applied_feedback_id": "feedback-approved",
                "last_action": "feedback",
                "applied_feedback_action": "feedback",
                "applied_feedback_sha256": "a" * 64,
                "applied_manifest_revision": 1,
                "applied_manifest_sha256": "b" * 64,
            },
        )
        result = carousel_status.build_status(
            self.manifest_path, session_dir_input=self.session_dir
        )
        self.assertFalse(result["session_binding_ok"])
        self.assertEqual(result["next_action"]["kind"], "blocked")
        self.assertEqual(
            result["next_action"]["reason"], "session_manifest_binding"
        )

    def test_advanced_state_never_recommends_export_with_a_stale_proof(self):
        manifest = base_manifest()
        set_workflow_state(manifest, "rendering")
        write_json(self.manifest_path, manifest)
        result = carousel_status.build_status(self.manifest_path)
        self.assertFalse(result["proof_approved"])
        self.assertEqual(result["next_action"]["kind"], "session_required")

        # With a bound session, stale proof is the actionable blocker rather
        # than an export recommendation.
        result = carousel_status.build_status(
            self.manifest_path, session_dir_input=self.session_dir
        )
        self.assertEqual(result["next_action"]["kind"], "blocked")
        self.assertEqual(
            result["next_action"]["reason"], "visual_proof_not_current"
        )

    def test_cli_fails_closed_with_json(self):
        broken = self.root / "broken.json"
        write_json(broken, {"schema_version": "99.0"})
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "carousel_status.py"), str(broken)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("non supportata", payload["error"])

    def test_cli_emits_machine_readable_success(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "carousel_status.py"),
                str(self.manifest_path),
                "--session-dir",
                str(self.session_dir),
                "--compact",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("\n", completed.stdout.rstrip("\n"))
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["next_action"]["stage"], "profile_text")


if __name__ == "__main__":
    unittest.main()

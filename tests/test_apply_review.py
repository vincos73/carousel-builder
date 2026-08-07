"""Test di apply_review.py: applicazione dei batch e coerenza del manifest."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support import base_feedback, base_manifest, run_apply, slide


class ApplyReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def manifest(self) -> dict:
        return json.loads((self.workdir / "manifest.json").read_text(encoding="utf-8"))

    def apply(self, manifest: dict, feedback: dict, state: dict | None = None):
        result = run_apply(self.workdir, manifest, feedback, state)
        return result

    def full_batch(self, **changes: str) -> list[dict]:
        return [
            slide("cover", "cover", title=changes.get("cover", "La lezione e operativa")),
            slide("item-1", "item", summary=changes.get("item-1", "Prima frase.")),
            slide("item-2", "item", summary=changes.get("item-2", "Seconda frase.")),
            slide(
                "outro",
                "outro",
                title=changes.get("outro_title", "Chiusura"),
                summary=changes.get("outro", "Corpo della chiusura."),
            ),
        ]

    def test_applies_edits_and_bumps_revision(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(**{"item-1": "Prima frase riscritta."})),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "applied")
        self.assertIn("items", payload["changed"])
        self.assertEqual(payload["manifest_revision"], 2)
        manifest = self.manifest()
        self.assertEqual(manifest["revision"], 2)
        self.assertEqual(manifest["items"][0]["summary"], "Prima frase riscritta.")
        backups = list((self.workdir / "session" / "backups").glob("*.json"))
        self.assertEqual(len(backups), 1)

    def test_rejects_stale_base_revision(self) -> None:
        result = self.apply(
            base_manifest(), base_feedback(self.full_batch(), base_revision=7)
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("revisione", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest()["revision"], 1)

    def test_rejects_feedback_not_matching_session(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch()),
            state={"token": "t", "last_feedback_id": "feedback-altro"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.manifest()["revision"], 1)

    def test_is_idempotent_for_an_already_applied_batch(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch()),
            state={
                "token": "t",
                "last_feedback_id": "feedback-test",
                "applied_feedback_id": "feedback-test",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "already_applied")
        self.assertEqual(self.manifest()["revision"], 1)

    def test_requires_the_cover_in_the_batch(self) -> None:
        batch = [entry for entry in self.full_batch() if entry["id"] != "cover"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)
        self.assertIn("copertina", json.loads(result.stderr)["error"].lower())

    def test_requires_at_least_one_item(self) -> None:
        batch = [entry for entry in self.full_batch() if entry["kind"] != "item"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)

    def test_requires_the_outro_when_enabled(self) -> None:
        batch = [entry for entry in self.full_batch() if entry["id"] != "outro"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)
        self.assertIn("chiusura", json.loads(result.stderr)["error"].lower())

    def test_drops_emphasis_that_no_longer_matches_the_new_text(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(
                self.full_batch(
                    cover="Titolo completamente nuovo",
                    **{"item-2": "Testo riscritto da capo."},
                )
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        manifest = self.manifest()
        self.assertEqual(manifest["cover_title_serif"], [])
        self.assertEqual(manifest["items"][1]["summary_accent"], [])
        self.assertEqual(payload["emphasis_dropped"]["cover"], ["e operativa"])
        self.assertEqual(payload["emphasis_dropped"]["item-2"], ["Seconda frase."])

    def test_keeps_emphasis_still_present_in_the_new_text(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(
                self.full_batch(**{"item-1": "Prima frase. E anche una seconda."})
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.manifest()["items"][0]["summary_serif"], ["Prima frase."]
        )
        self.assertEqual(json.loads(result.stdout)["emphasis_dropped"], {})

    def test_reports_but_keeps_emphasis_already_stale_on_unchanged_text(self) -> None:
        manifest = base_manifest()
        manifest["items"][0]["summary_serif"] = ["frase mai esistita"]
        result = self.apply(manifest, base_feedback(self.full_batch()))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            self.manifest()["items"][0]["summary_serif"], ["frase mai esistita"]
        )
        self.assertTrue(
            any("già incoerenti" in warning for warning in payload["warnings"])
        )

    def test_realigns_reading_order_and_proof_after_a_deletion(self) -> None:
        batch = [entry for entry in self.full_batch() if entry["id"] != "item-2"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest()
        self.assertEqual(
            manifest["accessibility"]["reading_order"], ["cover", "item-1", "outro"]
        )
        self.assertEqual(manifest["proof"]["slide_ids"], ["cover", "outro"])
        self.assertEqual(
            json.loads(result.stdout)["proof_slide_ids_pruned"], ["item-2"]
        )

    def test_realigns_reading_order_after_a_reorder(self) -> None:
        batch = self.full_batch()
        batch[1], batch[2] = batch[2], batch[1]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.manifest()["accessibility"]["reading_order"],
            ["cover", "item-2", "item-1", "outro"],
        )

    def test_reports_stale_alt_text_and_transcript(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(**{"item-2": "Testo nuovo."})),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["stale_alt_text"], ["item-2"])
        self.assertTrue(payload["stale_transcript"])

    def test_leaves_a_manifest_without_optional_sections_untouched(self) -> None:
        manifest = base_manifest()
        del manifest["accessibility"]
        del manifest["proof"]
        result = self.apply(
            manifest, base_feedback(self.full_batch(cover="Nuovo titolo"))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.manifest()
        self.assertNotIn("accessibility", written)
        self.assertNotIn("proof", written)
        self.assertEqual(written["cover_title"], "Nuovo titolo")

    def test_warns_when_an_approved_proof_is_invalidated(self) -> None:
        manifest = base_manifest()
        manifest["proof"]["approved"] = True
        result = self.apply(
            manifest, base_feedback(self.full_batch(cover="Nuovo titolo"))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            any(
                "prova visuale va riapprovata" in warning
                for warning in json.loads(result.stdout)["warnings"]
            )
        )

    def test_never_changes_the_workflow_state(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(cover="Nuovo titolo"), action="approve"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["approval_requested"])
        self.assertFalse(payload["workflow_state_changed"])
        self.assertEqual(self.manifest()["workflow_state"], "bozza")


if __name__ == "__main__":
    unittest.main()

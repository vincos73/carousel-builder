"""Test di apply_review.py: applicazione dei batch e coerenza del manifest."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from support import SCRIPTS, base_feedback, base_manifest, run_apply, slide, write_json


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

    def apply_path(self, feedback_path: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(self.workdir / "manifest.json"),
                str(feedback_path),
                "--session-dir",
                str(self.workdir / "session"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def full_batch(self, **changes: str) -> list[dict]:
        return [
            slide(
                "cover",
                "cover",
                title=changes.get("cover", "La lezione e operativa"),
                summary=changes.get("cover_subtitle", ""),
            ),
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
        original_manifest = base_manifest()
        original_bytes = json.dumps(original_manifest, ensure_ascii=False).encode("utf-8")
        result = self.apply(
            original_manifest,
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
        self.assertEqual(backups[0].read_bytes(), original_bytes)

    def test_applies_cover_subtitle_and_marks_accessibility_copy_stale(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(cover_subtitle="Ecco cosa puoi fare")),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        manifest = self.manifest()
        self.assertEqual(manifest["cover_subtitle"], "Ecco cosa puoi fare")
        self.assertIn("cover_subtitle", payload["changed"])
        self.assertEqual(payload["stale_alt_text"], ["cover"])
        self.assertTrue(payload["stale_transcript"])

    def test_enforces_sentence_line_breaks_without_splitting_versions(self) -> None:
        copy = "Usa la versione 1.2. Poi riavvia. Fatto."
        result = self.apply(
            base_manifest(), base_feedback(self.full_batch(**{"item-1": copy}))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.manifest()["items"][0]["summary"],
            "Usa la versione 1.2.\nPoi riavvia.\nFatto.",
        )

    def test_enforces_all_sentence_endings_without_splitting_abbreviations_or_urls(self) -> None:
        copy = (
            "Dott. Rossi usa la versione 1.2. Funziona? Sì! Certo… "
            "Visita https://example.com. Fine."
        )
        result = self.apply(
            base_manifest(), base_feedback(self.full_batch(**{"item-1": copy}))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.manifest()["items"][0]["summary"],
            "Dott. Rossi usa la versione 1.2.\nFunziona?\nSì!\nCerto…\n"
            "Visita https://example.com.\nFine.",
        )

    def test_rejects_stale_base_revision(self) -> None:
        result = self.apply(
            base_manifest(), base_feedback(self.full_batch(), base_revision=7)
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("revisione", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest()["revision"], 1)

    def test_rejects_a_session_bound_to_another_manifest(self) -> None:
        other_manifest = self.workdir / "other" / "manifest.json"
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch()),
            state={"manifest": str(other_manifest.resolve())},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("manifest diverso", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest()["revision"], 1)

    def test_recovers_state_when_the_manifest_commit_already_succeeded(self) -> None:
        manifest = base_manifest()
        manifest["revision"] = 2
        manifest["review"] = {"last_feedback_id": "feedback-test"}
        result = self.apply(
            manifest,
            base_feedback(self.full_batch(), base_revision=1),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "recovered")
        self.assertEqual(payload["manifest_revision"], 2)
        state = json.loads(
            (self.workdir / "session" / "session-state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["applied_feedback_id"], "feedback-test")
        self.assertEqual(self.manifest()["revision"], 2)

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

    def test_backfills_a_missing_last_action_and_rejects_a_conflict(self) -> None:
        result = self.apply(base_manifest(), base_feedback(self.full_batch()))
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(
            (self.workdir / "session" / "session-state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["last_action"], "feedback")

        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch()),
            state={"last_action": "approve"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("last_action", json.loads(result.stderr)["error"])

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

    def test_malformed_slide_and_non_finite_json_return_structured_errors(self) -> None:
        feedback = base_feedback(self.full_batch())
        feedback["slides"][1] = 7
        result = self.apply(base_manifest(), feedback)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Ogni slide", json.loads(result.stderr)["error"])
        self.assertNotIn("Traceback", result.stderr)

        manifest_path = self.workdir / "manifest.json"
        feedback_path = self.workdir / "session" / "feedback.json"
        state_path = self.workdir / "session" / "session-state.json"
        write_json(manifest_path, base_manifest())
        feedback_path.write_text('{"feedback_id":"feedback-test","action":NaN}', encoding="utf-8")
        write_json(
            state_path,
            {
                "manifest": str(manifest_path.resolve()),
                "last_feedback_id": "feedback-test",
            },
        )
        result = self.apply_path(feedback_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Costante JSON", json.loads(result.stderr)["error"])

    def test_accepts_only_the_legacy_alias_or_a_matching_direct_archive(self) -> None:
        manifest_path = self.workdir / "manifest.json"
        session_dir = self.workdir / "session"
        archive_dir = session_dir / "feedback-batches"
        feedback_id = str(uuid.uuid4())
        archive_path = archive_dir / f"{feedback_id}.json"
        feedback = base_feedback(self.full_batch(), feedback_id=feedback_id)
        write_json(manifest_path, base_manifest())
        write_json(archive_path, feedback)
        write_json(
            session_dir / "session-state.json",
            {
                "manifest": str(manifest_path.resolve()),
                "last_feedback_id": feedback_id,
                "last_feedback_path": str(archive_path.resolve()),
                "last_action": "feedback",
            },
        )
        result = self.apply_path(archive_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        write_json(manifest_path, base_manifest())
        write_json(archive_dir / "nome-diverso.json", feedback)
        result = self.apply_path(archive_dir / "nome-diverso.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("nome del batch", json.loads(result.stderr)["error"])

    def test_rejects_a_tampered_alias_when_the_canonical_archive_exists(self) -> None:
        manifest_path = self.workdir / "manifest.json"
        session_dir = self.workdir / "session"
        feedback_id = str(uuid.uuid4())
        canonical = base_feedback(self.full_batch(), feedback_id=feedback_id)
        tampered = json.loads(json.dumps(canonical))
        tampered["slides"][1]["summary"] = "Testo alterato nell'alias."
        archive_path = session_dir / "feedback-batches" / f"{feedback_id}.json"
        write_json(manifest_path, base_manifest())
        write_json(archive_path, canonical)
        write_json(session_dir / "feedback.json", tampered)
        write_json(
            session_dir / "session-state.json",
            {
                "manifest": str(manifest_path.resolve()),
                "last_feedback_id": feedback_id,
                "last_feedback_path": str(archive_path.resolve()),
                "last_action": "feedback",
            },
        )
        before = manifest_path.read_bytes()
        result = self.apply_path(session_dir / "feedback.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("batch append-only canonico", json.loads(result.stderr)["error"])
        self.assertEqual(manifest_path.read_bytes(), before)

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_rejects_symlinked_or_unsafe_feedback_paths(self) -> None:
        manifest_path = self.workdir / "manifest.json"
        session_dir = self.workdir / "session"
        archive_dir = session_dir / "feedback-batches"
        feedback_id = str(uuid.uuid4())
        real_path = archive_dir / f"{feedback_id}.json"
        linked_path = archive_dir / "linked.json"
        feedback = base_feedback(self.full_batch(), feedback_id=feedback_id)
        write_json(manifest_path, base_manifest())
        write_json(real_path, feedback)
        linked_path.symlink_to(real_path)
        write_json(
            session_dir / "session-state.json",
            {
                "manifest": str(manifest_path.resolve()),
                "last_feedback_id": feedback_id,
                "last_action": "feedback",
            },
        )
        result = self.apply_path(linked_path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("collegamento simbolico", json.loads(result.stderr)["error"])

        unsafe = base_feedback(self.full_batch(), feedback_id="../../escape")
        result = self.apply(base_manifest(), unsafe)
        self.assertEqual(result.returncode, 2)
        self.assertIn("non valido o non sicuro", json.loads(result.stderr)["error"])

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_transaction_lock_symlink_never_touches_its_target(self) -> None:
        manifest_path = self.workdir / "manifest.json"
        session_dir = self.workdir / "session"
        feedback = base_feedback(self.full_batch())
        write_json(manifest_path, base_manifest())
        write_json(session_dir / "feedback.json", feedback)
        write_json(
            session_dir / "session-state.json",
            {
                "manifest": str(manifest_path.resolve()),
                "last_feedback_id": feedback["feedback_id"],
            },
        )
        victim = self.workdir / "victim.lock-target"
        victim.write_bytes(b"")
        victim.chmod(0o644)
        before_mode = victim.stat().st_mode
        (session_dir / ".review-transaction.lock").symlink_to(victim)

        result = self.apply_path(session_dir / "feedback.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("collegamento simbolico", json.loads(result.stderr)["error"])
        self.assertEqual(victim.read_bytes(), b"")
        self.assertEqual(victim.stat().st_mode, before_mode)

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_transaction_lock_hardlink_never_touches_its_target(self) -> None:
        manifest_path = self.workdir / "manifest.json"
        session_dir = self.workdir / "session"
        feedback = base_feedback(self.full_batch())
        write_json(manifest_path, base_manifest())
        write_json(session_dir / "feedback.json", feedback)
        write_json(
            session_dir / "session-state.json",
            {
                "manifest": str(manifest_path.resolve()),
                "last_feedback_id": feedback["feedback_id"],
            },
        )
        victim = self.workdir / "victim.lock-target"
        victim.write_bytes(b"")
        victim.chmod(0o644)
        before_mode = victim.stat().st_mode
        os.link(victim, session_dir / ".review-transaction.lock")

        result = self.apply_path(session_dir / "feedback.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("hard link", json.loads(result.stderr)["error"])
        self.assertEqual(victim.read_bytes(), b"")
        self.assertEqual(victim.stat().st_mode, before_mode)

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

    def test_prunes_bold_emphasis_with_the_same_rules_as_other_emphasis(self) -> None:
        manifest = base_manifest()
        manifest["items"][0]["summary_bold"] = ["Prima frase."]
        result = self.apply(
            manifest,
            base_feedback(self.full_batch(**{"item-1": "Testo completamente nuovo."})),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["items"][0]["summary_bold"], [])
        self.assertEqual(
            json.loads(result.stdout)["emphasis_dropped"]["item-1"],
            ["Prima frase.", "Prima frase."],
        )

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
        written = self.manifest()
        self.assertFalse(written["proof"]["approved"])
        self.assertIn("proof.approved", json.loads(result.stdout)["changed"])

    def test_never_changes_the_workflow_state(self) -> None:
        batch = self.full_batch(cover="Nuovo titolo")
        batch[1]["summary_bold"] = ["Prima frase."]
        batch[1]["summary_serif"] = []
        batch[2]["summary_bold"] = ["Seconda frase."]
        batch[2]["summary_accent"] = []
        result = self.apply(
            base_manifest(),
            base_feedback(batch, action="approve"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["approval_requested"])
        self.assertFalse(payload["workflow_state_changed"])
        self.assertEqual(self.manifest()["workflow_state"], "bozza")

    def test_visual_checkpoint_rejects_legacy_or_incomplete_approval_batches(self) -> None:
        manifest = base_manifest()
        manifest["workflow_state"] = "testi_approvati"
        batch = self.full_batch()
        batch[1]["summary_serif"] = []

        legacy = self.apply(manifest, base_feedback(batch, action="approve"))
        self.assertEqual(legacy.returncode, 2)
        self.assertIn("approval_stage", json.loads(legacy.stderr)["error"])
        self.assertFalse(self.manifest()["proof"]["approved"])

        incomplete = self.apply(
            manifest,
            base_feedback(
                batch,
                action="approve",
                approval_stage="visual_proof",
                base_workflow_state="testi_approvati",
            ),
        )
        self.assertEqual(incomplete.returncode, 2)
        self.assertIn("fingerprint", json.loads(incomplete.stderr)["error"])
        self.assertFalse(self.manifest()["proof"]["approved"])

    def test_persists_explicit_italic_and_removes_legacy_serif(self) -> None:
        batch = self.full_batch()
        batch[1]["summary_bold"] = ["Prima"]
        batch[1]["summary_italic"] = ["frase."]
        batch[1]["summary_serif"] = []
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.manifest()["items"][0]
        self.assertEqual(item["summary_bold"], ["Prima"])
        self.assertEqual(item["summary_italic"], ["frase."])
        self.assertEqual(item["summary_serif"], [])

    def test_persists_underline_and_adaptive_highlighter_roles(self) -> None:
        batch = self.full_batch()
        batch[1]["summary_bold"] = ["Prima"]
        batch[1]["summary_underline"] = ["frase."]
        batch[1]["summary_accent"] = []
        batch[1]["summary_serif"] = []
        batch[2]["summary_bold"] = ["Seconda"]
        batch[2]["summary_accent"] = ["frase."]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = self.manifest()["items"]
        self.assertEqual(first["summary_underline"], ["frase."])
        self.assertEqual(second["summary_accent"], ["frase."])

    def test_persists_three_distinct_phrases_for_the_same_emphasis_role(self) -> None:
        batch = self.full_batch(**{"item-1": "Uno due tre."})
        batch[1]["summary_serif"] = []
        batch[1]["summary_accent"] = ["Uno", "due", "tre"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.manifest()["items"][0]["summary_accent"], ["Uno", "due", "tre"]
        )

    def test_rejects_received_emphasis_that_no_longer_exists(self) -> None:
        batch = self.full_batch(**{"item-1": "Testo nuovo."})
        batch[1]["summary_bold"] = ["Prima"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)
        self.assertIn("una sola volta", json.loads(result.stderr)["error"])

    def test_rejects_overlapping_or_ambiguous_received_emphasis(self) -> None:
        batch = self.full_batch()
        batch[1]["summary_bold"] = ["Prima"]
        batch[1]["summary_italic"] = ["Prima frase."]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)
        self.assertIn("sovrappongono", json.loads(result.stderr)["error"])

        batch = self.full_batch()
        batch[1]["summary_bold"] = ["a"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)
        self.assertIn("una sola volta", json.loads(result.stderr)["error"])

    def test_same_selection_with_two_treatments_has_one_actionable_error(self) -> None:
        batch = self.full_batch()
        batch[1]["summary_serif"] = []
        batch[1]["summary_underline"] = ["Prima"]
        batch[1]["summary_accent"] = ["Prima"]
        result = self.apply(base_manifest(), base_feedback(batch))
        self.assertEqual(result.returncode, 2)
        error = json.loads(result.stderr)["error"]
        self.assertIn("“Prima” ha più trattamenti", error)
        self.assertIn("Scegline uno", error)
        self.assertNotIn("sovrappongono", error)

    def test_feedback_without_bold_does_not_return_a_bold_warning(self) -> None:
        result = self.apply(base_manifest(), base_feedback(self.full_batch()))
        self.assertEqual(result.returncode, 0, result.stderr)
        warnings = json.loads(result.stdout)["warnings"]
        self.assertFalse(any("summary_bold" in warning for warning in warnings))

    def test_approve_allows_no_bold_and_multiple_non_overlapping_styles(self) -> None:
        batch = self.full_batch()
        batch[1]["summary_serif"] = []
        batch[2]["summary_accent"] = []
        result = self.apply(base_manifest(), base_feedback(batch, action="approve"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_approval_enforces_internal_copy_limits_server_side(self) -> None:
        batch = self.full_batch()
        batch[1]["title"] = "Titolo"
        batch[1]["summary"] = "x" * 181
        batch[1]["summary_serif"] = []
        result = self.apply(
            base_manifest(), base_feedback(batch, action="approve")
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("massimo 180", json.loads(result.stderr)["error"])

        batch[1]["summary"] = "Uno due tre."
        batch[1]["summary_bold"] = ["Uno"]
        batch[1]["summary_italic"] = ["due"]
        batch[1]["summary_serif"] = ["tre."]
        result = self.apply(base_manifest(), base_feedback(batch, action="approve"))
        self.assertEqual(result.returncode, 0, result.stderr)

        batch = self.full_batch(**{"item-1": "Uno due tre."})
        batch[1]["summary_bold"] = ["Uno"]
        batch[1]["summary_underline"] = ["due"]
        batch[1]["summary_accent"] = ["tre."]
        batch[2]["summary_bold"] = ["Seconda"]
        batch[2]["summary_accent"] = []
        result = self.apply(base_manifest(), base_feedback(batch, action="approve"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_persists_logo_mode_and_rejects_invalid_values(self) -> None:
        result = self.apply(
            base_manifest(), base_feedback(self.full_batch(), logo_mode="hidden")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(self.manifest()["logo_mode"], "hidden")
        self.assertIn("logo_mode", payload["changed"])

        result = self.apply(
            base_manifest(), base_feedback(self.full_batch(), logo_mode="always")
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("logo_mode", json.loads(result.stderr)["error"])

    def test_persists_only_the_selected_visual_style_override(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "visual_signature": {"style_system": "editorial-frame"},
        }
        feedback = base_feedback(
            self.full_batch(), visual_style_system="corporate-modular"
        )
        result = self.apply(manifest, feedback)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        written = self.manifest()
        self.assertEqual(written["visual_style_system"], "corporate-modular")
        self.assertEqual(
            written["brand"]["visual_signature"]["style_system"], "editorial-frame"
        )
        self.assertEqual(written["revision"], 2)
        self.assertIn("visual_style_system", payload["changed"])
        self.assertFalse(payload["stale_transcript"])

    def test_rejects_an_invalid_visual_style_selection(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(), visual_style_system="inventato"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("visual_style_system", json.loads(result.stderr)["error"])

    def test_accepts_new_visual_system_aliases(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(), visual_style_system="campo-cromatico"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["visual_style_system"], "editorial-halftone")

        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(), visual_style_system="geometrico"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["visual_style_system"], "editorial-halftone")

        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(), visual_style_system="istituzionale"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["visual_style_system"], "corporate-modular")

        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(), visual_style_system="costellazione"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["visual_style_system"], "editorial-halftone")


if __name__ == "__main__":
    unittest.main()

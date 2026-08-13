"""Test di apply_review.py: applicazione dei batch e coerenza del manifest."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from support import (
    SCRIPTS,
    base_feedback,
    base_manifest,
    run_apply,
    set_workflow_state,
    slide,
    write_json,
)

APPLY_SPEC = importlib.util.spec_from_file_location(
    "apply_review", SCRIPTS / "apply_review.py"
)
apply_review = importlib.util.module_from_spec(APPLY_SPEC)
assert APPLY_SPEC.loader is not None
APPLY_SPEC.loader.exec_module(apply_review)


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
        return self.apply_cli(
            self.workdir / "manifest.json",
            feedback_path,
            self.workdir / "session",
        )

    def apply_cli(
        self, manifest_path: Path, feedback_path: Path, session_dir: Path
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(manifest_path),
                str(feedback_path),
                "--session-dir",
                str(session_dir),
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

    @unittest.skipUnless(
        hasattr(os, "fchmod") and os.name != "nt",
        "fchmod e symlink POSIX richiesti",
    )
    def test_atomic_copy_rejects_a_swapped_temporary_symlink(self) -> None:
        source = self.workdir / "source.json"
        source.write_bytes(b"backup-content")
        destination = self.workdir / "backups" / "backup.json"
        victim = self.workdir / "victim.json"
        victim.write_bytes(b"external-content")
        victim.chmod(0o644)
        before_content = victim.read_bytes()
        before_mode = stat.S_IMODE(victim.stat().st_mode)
        displaced = self.workdir / "displaced.tmp"
        real_fchmod = apply_review.os.fchmod

        def inject_symlink(descriptor: int, mode: int) -> None:
            real_fchmod(descriptor, mode)
            generated = next(destination.parent.glob(".backup.json.*.tmp"))
            generated.rename(displaced)
            generated.symlink_to(victim)

        with mock.patch.object(
            apply_review.os, "fchmod", side_effect=inject_symlink
        ), self.assertRaisesRegex(ValueError, "temporanea non sicura"):
            apply_review.atomic_copy(source, destination)

        self.assertFalse(destination.exists())
        self.assertFalse(destination.is_symlink())
        self.assertEqual(victim.read_bytes(), before_content)
        self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)
        self.assertEqual(displaced.read_bytes(), source.read_bytes())

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

    def test_rejects_a_non_string_action_without_a_traceback(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch(), action=["feedback"]),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Azione del batch non valida", json.loads(result.stderr)["error"])
        self.assertNotIn("Traceback", result.stderr)

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
        manifest["review"] = {
            "last_feedback_id": "feedback-test",
            "last_action": "feedback",
        }
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
        self.assertEqual(state["applied_feedback_action"], "feedback")
        self.assertEqual(len(state["applied_feedback_sha256"]), 64)
        self.assertEqual(state["applied_manifest_revision"], 2)
        self.assertEqual(len(state["applied_manifest_sha256"]), 64)
        self.assertEqual(self.manifest()["revision"], 2)

    def test_rejects_feedback_not_matching_session(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch()),
            state={"token": "t", "last_feedback_id": "feedback-altro"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.manifest()["revision"], 1)

    def test_rejects_a_false_already_applied_state_without_a_manifest_receipt(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(self.full_batch()),
            state={
                "token": "t",
                "last_feedback_id": "feedback-test",
                "applied_feedback_id": "feedback-test",
            },
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("ricevuta review", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest()["revision"], 1)

    def test_modern_receipt_is_idempotent_and_detects_later_manifest_tampering(self) -> None:
        feedback = base_feedback(
            self.full_batch(**{"item-1": "Prima frase aggiornata."})
        )
        first = self.apply(base_manifest(), feedback)
        self.assertEqual(first.returncode, 0, first.stderr)
        manifest = self.manifest()
        state = json.loads(
            (self.workdir / "session" / "session-state.json").read_text(
                encoding="utf-8"
            )
        )

        replay = self.apply(manifest, feedback, state=state)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(json.loads(replay.stdout)["status"], "already_applied")

        tampered = self.manifest()
        tampered["items"][0]["summary"] = "Alterazione successiva."
        rejected = self.apply(tampered, feedback, state=state)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("cambiato", json.loads(rejected.stderr)["error"])

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

    def test_rejects_kind_changes_unknown_ids_duplicates_and_invalid_order(self) -> None:
        cases: list[tuple[list[dict], str]] = []
        wrong_kind = self.full_batch()
        wrong_kind[1]["kind"] = "cover"
        cases.append((wrong_kind, "Tipo non valido"))

        unknown = self.full_batch()
        unknown.insert(2, slide("item-unknown", "item", summary="Intrusa"))
        cases.append((unknown, "sconosciuto"))

        duplicate_cover = self.full_batch()
        duplicate_cover.insert(1, slide("cover", "cover", title="Duplicata"))
        cases.append((duplicate_cover, "duplicato"))

        duplicate_outro = self.full_batch()
        duplicate_outro.append(slide("outro", "outro", title="Duplicata"))
        cases.append((duplicate_outro, "duplicato"))

        cover_not_first = self.full_batch()
        cover_not_first[0], cover_not_first[1] = cover_not_first[1], cover_not_first[0]
        cases.append((cover_not_first, "prima slide"))

        outro_not_last = self.full_batch()
        outro_not_last[-1], outro_not_last[-2] = outro_not_last[-2], outro_not_last[-1]
        cases.append((outro_not_last, "ultima slide"))

        for batch, message in cases:
            with self.subTest(message=message):
                result = self.apply(base_manifest(), base_feedback(batch))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, json.loads(result.stderr)["error"])
                self.assertEqual(self.manifest()["revision"], 1)

    def test_rejects_reserved_ids_in_manifest_items(self) -> None:
        for reserved in ("cover", "outro"):
            with self.subTest(reserved=reserved):
                manifest = base_manifest()
                manifest["items"][0]["id"] = reserved
                result = self.apply(manifest, base_feedback(self.full_batch()))
                self.assertEqual(result.returncode, 2)
                self.assertIn("riservato", json.loads(result.stderr)["error"])

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
    def test_cli_rejects_manifest_and_session_symlinks_without_touching_targets(self) -> None:
        manifest_target = self.workdir / "manifest-target.json"
        write_json(manifest_target, base_manifest())
        manifest_target.chmod(0o644)
        manifest_before = manifest_target.read_bytes()
        manifest_mode = stat.S_IMODE(manifest_target.stat().st_mode)
        manifest_link = self.workdir / "manifest.json"
        manifest_link.symlink_to(manifest_target)

        result = self.apply_cli(
            manifest_link,
            self.workdir / "session" / "feedback.json",
            self.workdir / "session",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("collegamento simbolico", json.loads(result.stderr)["error"])
        self.assertEqual(manifest_target.read_bytes(), manifest_before)
        self.assertEqual(stat.S_IMODE(manifest_target.stat().st_mode), manifest_mode)
        self.assertFalse((self.workdir / "session").exists())

        manifest_link.unlink()
        write_json(manifest_link, base_manifest())
        session_target = self.workdir / "session-target"
        session_target.mkdir()
        sentinel = session_target / "sentinel.txt"
        sentinel.write_text("immutato", encoding="utf-8")
        session_target.chmod(0o755)
        target_mode = stat.S_IMODE(session_target.stat().st_mode)
        target_entries = sorted(path.name for path in session_target.iterdir())
        session_link = self.workdir / "session"
        session_link.symlink_to(session_target, target_is_directory=True)

        result = self.apply_cli(
            manifest_link,
            session_link / "feedback.json",
            session_link,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("collegamento simbolico", json.loads(result.stderr)["error"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutato")
        self.assertEqual(stat.S_IMODE(session_target.stat().st_mode), target_mode)
        self.assertEqual(
            sorted(path.name for path in session_target.iterdir()), target_entries
        )

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_cli_rejects_symlinked_parent_components_before_creating_session(self) -> None:
        manifest_path = self.workdir / "manifest.json"
        write_json(manifest_path, base_manifest())
        target_parent = self.workdir / "target-parent"
        target_parent.mkdir()
        sentinel = target_parent / "sentinel.txt"
        sentinel.write_text("immutato", encoding="utf-8")
        target_parent.chmod(0o755)
        before_mode = stat.S_IMODE(target_parent.stat().st_mode)
        alias = self.workdir / "alias"
        alias.symlink_to(target_parent, target_is_directory=True)

        result = self.apply_cli(
            manifest_path,
            alias / "session" / "feedback.json",
            alias / "session",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("collegamento simbolico", json.loads(result.stderr)["error"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutato")
        self.assertEqual(stat.S_IMODE(target_parent.stat().st_mode), before_mode)
        self.assertFalse((target_parent / "session").exists())

        manifest_target_dir = self.workdir / "manifest-target-parent"
        manifest_target = manifest_target_dir / "manifest.json"
        write_json(manifest_target, base_manifest())
        manifest_target.chmod(0o644)
        manifest_before = manifest_target.read_bytes()
        manifest_mode = stat.S_IMODE(manifest_target.stat().st_mode)
        manifest_alias = self.workdir / "manifest-alias"
        manifest_alias.symlink_to(manifest_target_dir, target_is_directory=True)
        clean_session = self.workdir / "clean-session"

        result = self.apply_cli(
            manifest_alias / "manifest.json",
            clean_session / "feedback.json",
            clean_session,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("collegamento simbolico", json.loads(result.stderr)["error"])
        self.assertEqual(manifest_target.read_bytes(), manifest_before)
        self.assertEqual(stat.S_IMODE(manifest_target.stat().st_mode), manifest_mode)
        self.assertFalse(clean_session.exists())

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_private_json_hardlinks_never_touch_their_targets(self) -> None:
        for private_name in ("feedback", "state", "archive"):
            with self.subTest(private_name=private_name):
                case_root = self.workdir / private_name
                manifest_path = case_root / "manifest.json"
                session_dir = case_root / "session"
                feedback_path = session_dir / "feedback.json"
                state_path = session_dir / "session-state.json"
                feedback_id = str(uuid.uuid4())
                archive_path = session_dir / "feedback-batches" / f"{feedback_id}.json"
                feedback = base_feedback(self.full_batch(), feedback_id=feedback_id)
                state = {
                    "manifest": str(manifest_path.resolve()),
                    "last_feedback_id": feedback_id,
                    "last_feedback_path": str(archive_path.resolve()),
                    "last_action": "feedback",
                }
                write_json(manifest_path, base_manifest())

                victim = case_root / f"{private_name}-victim.json"
                if private_name == "feedback":
                    write_json(state_path, state)
                    write_json(victim, feedback)
                    feedback_path.parent.mkdir(parents=True, exist_ok=True)
                    os.link(victim, feedback_path)
                elif private_name == "state":
                    write_json(feedback_path, feedback)
                    write_json(victim, state)
                    os.link(victim, state_path)
                else:
                    write_json(feedback_path, feedback)
                    write_json(state_path, state)
                    write_json(victim, feedback)
                    archive_path.parent.mkdir(parents=True, exist_ok=True)
                    os.link(victim, archive_path)

                victim.chmod(0o644)
                before = victim.read_bytes()
                before_mode = stat.S_IMODE(victim.stat().st_mode)
                result = self.apply_cli(manifest_path, feedback_path, session_dir)

                self.assertEqual(result.returncode, 2)
                self.assertIn("hard link", json.loads(result.stderr)["error"])
                self.assertEqual(victim.read_bytes(), before)
                self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)

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
        self.assertEqual(manifest["proof"]["slide_ids"], ["cover", "item-1", "outro"])
        self.assertEqual(
            json.loads(result.stdout)["proof_slide_ids_pruned"], ["item-2"]
        )

    def test_proof_uses_the_densest_remaining_item_with_stable_order_ties(self) -> None:
        manifest = base_manifest()
        manifest["proof"]["slide_ids"] = ["cover", "item-1", "outro"]
        batch = self.full_batch(
            **{
                "item-1": "breve",
                "item-2": "Questa è la card più densa della prova.",
            }
        )
        result = self.apply(manifest, base_feedback(batch))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.manifest()["proof"]["slide_ids"],
            ["cover", "item-2", "outro"],
        )

        tied_manifest = self.manifest()
        tied_feedback = base_feedback(
            [
                slide("cover", "cover", title="La lezione e operativa"),
                slide("item-2", "item", summary="12345"),
                slide("item-1", "item", summary="abcde"),
                slide(
                    "outro",
                    "outro",
                    title="Chiusura",
                    summary="Corpo della chiusura.",
                ),
            ],
            feedback_id="feedback-tie",
            base_revision=tied_manifest["revision"],
        )
        tied = self.apply(tied_manifest, tied_feedback)
        self.assertEqual(tied.returncode, 0, tied.stderr)
        self.assertEqual(
            self.manifest()["proof"]["slide_ids"],
            ["cover", "item-2", "outro"],
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
        manifest["schema_version"] = "1.3"
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
        manifest["proof"]["style_system_verified"] = True
        manifest["proof"]["browser"] = {"engine": "chromium", "major": 140}
        result = self.apply(
            manifest, base_feedback(self.full_batch(cover="Nuovo titolo"))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.manifest()
        self.assertFalse(written["proof"]["approved"])
        self.assertFalse(written["proof"]["style_system_verified"])
        self.assertNotIn("browser", written["proof"])
        self.assertIn("proof.approved", json.loads(result.stdout)["changed"])
        self.assertIn(
            "proof.style_system_verified", json.loads(result.stdout)["changed"]
        )

    def test_profile_text_cannot_persist_visual_proof_metadata(self) -> None:
        result = self.apply(
            base_manifest(),
            base_feedback(
                self.full_batch(),
                action="approve",
                proof_slide_ids=["cover", "item-2", "outro"],
                style_system_verified=True,
                proof_browser={"engine": "chromium", "major": 140},
            ),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("metadati della prova", json.loads(result.stderr)["error"])

    def test_proof_browser_contract_is_chromium_only(self) -> None:
        self.assertEqual(
            apply_review.validated_proof_browser(
                {"engine": "chromium", "major": 140}
            ),
            {"engine": "chromium", "major": 140},
        )
        for engine in ("firefox", "webkit"):
            with self.subTest(engine=engine), self.assertRaisesRegex(
                ValueError, "proof_browser.engine"
            ):
                apply_review.validated_proof_browser(
                    {"engine": engine, "major": 140}
                )

    def test_visual_approval_rejects_a_non_chromium_browser_without_writing(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest_path = self.workdir / "manifest-for-fingerprint.json"
        write_json(manifest_path, manifest)
        fingerprint = apply_review.server_manifest_model(manifest_path)[
            "render_fingerprint"
        ]
        feedback = base_feedback(
            self.full_batch(),
            action="approve",
            approval_stage="visual_proof",
            base_workflow_state="testi_approvati",
            base_render_fingerprint=fingerprint,
            render_fingerprint=fingerprint,
            proof_slide_ids=["cover", "item-2", "outro"],
            style_system_verified=True,
            proof_browser={"engine": "firefox", "major": 140},
        )

        result = self.apply(manifest, feedback)

        self.assertEqual(result.returncode, 2)
        self.assertIn("proof_browser.engine", json.loads(result.stderr)["error"])
        written = self.manifest()
        self.assertEqual(written["revision"], 1)
        self.assertFalse(written["proof"]["approved"])
        state = json.loads(
            (self.workdir / "session" / "session-state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("applied_feedback_id", state)

    def test_visual_approval_rejects_an_incompatible_local_producer_without_writing(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest["production"]["producer"] = "unrelated-renderer"
        manifest_path = self.workdir / "manifest-for-fingerprint.json"
        write_json(manifest_path, manifest)
        fingerprint = apply_review.server_manifest_model(manifest_path)[
            "render_fingerprint"
        ]
        feedback = base_feedback(
            self.full_batch(),
            action="approve",
            approval_stage="visual_proof",
            base_workflow_state="testi_approvati",
            base_render_fingerprint=fingerprint,
            render_fingerprint=fingerprint,
            proof_slide_ids=["cover", "item-2", "outro"],
            style_system_verified=True,
            proof_browser={"engine": "chromium", "major": 140},
        )

        result = self.apply(manifest, feedback)

        self.assertEqual(result.returncode, 2)
        self.assertIn("contratto renderer locale", json.loads(result.stderr)["error"])
        written = self.manifest()
        self.assertEqual(written["revision"], 1)
        self.assertFalse(written["proof"]["approved"])

    def test_never_advances_the_workflow_state(self) -> None:
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

    def test_post_visual_edit_rewinds_atomically_to_the_reapproval_checkpoint(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "qa")
        manifest["proof"].update(
            {
                "approved": True,
                "style_system_verified": True,
                "browser": {"engine": "chromium", "major": 140},
                "render_fingerprint": "c" * 64,
            }
        )

        result = self.apply(
            manifest,
            base_feedback(self.full_batch(cover="Titolo corretto dopo la prova")),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        written = self.manifest()
        self.assertTrue(payload["workflow_state_changed"])
        self.assertIn("workflow_state", payload["changed"])
        self.assertEqual(written["workflow_state"], "bozza")
        self.assertFalse(written["proof"]["approved"])
        self.assertFalse(written["proof"]["style_system_verified"])
        self.assertNotIn("browser", written["proof"])
        self.assertNotIn("workflow_receipts", written)

    def test_post_visual_note_or_comment_reopens_review_even_without_slide_edits(self) -> None:
        for changes in (
            {"overall_note": "Non produrre: cambia la direzione visuale."},
            {
                "comments": [
                    {
                        "id": "comment-1", "kind": "brand", "slide_id": "",
                        "field": "", "quote": "", "start": None, "end": None,
                        "feedback": "Rivedere la composizione.",
                    }
                ]
            },
        ):
            manifest = base_manifest()
            set_workflow_state(manifest, "prova_visuale_approvata")
            manifest["proof"].update(
                {
                    "approved": True,
                    "style_system_verified": True,
                    "browser": {"engine": "chromium", "major": 140},
                    "render_fingerprint": "c" * 64,
                }
            )
            feedback = base_feedback(self.full_batch(), **changes)
            with self.subTest(changes=changes):
                result = self.apply(manifest, feedback)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertTrue(payload["workflow_state_changed"])
                written = self.manifest()
                self.assertEqual(written["workflow_state"], "bozza")
                self.assertFalse(written["proof"]["approved"])
                self.assertFalse(written["proof"]["style_system_verified"])
                self.assertNotIn("browser", written["proof"])
                self.assertNotIn("workflow_receipts", written)

    def test_editorial_changes_clear_stale_workflow_receipts(self) -> None:
        manifest = base_manifest()
        manifest["workflow_receipts"] = [
            {
                "from": "bozza",
                "to": "testi_approvati",
                "revision": 1,
                "render_fingerprint": "a" * 64,
                "evidence_sha256": "b" * 64,
                "advanced_at": "2026-08-12T12:00:00+00:00",
            }
        ]
        set_workflow_state(manifest, "testi_approvati")
        feedback = base_feedback(
            self.full_batch(**{"item-1": "Testo aggiornato."})
        )

        result = self.apply(manifest, feedback)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("workflow_receipts", payload["changed"])
        self.assertNotIn("workflow_receipts", self.manifest())
        self.assertTrue(payload["workflow_state_changed"])
        self.assertEqual(self.manifest()["workflow_state"], "bozza")

    def test_emphasis_only_change_preserves_text_approval_and_accessibility(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        original_receipt = copy.deepcopy(manifest["workflow_receipts"][0])
        batch = self.full_batch()
        batch[1]["summary_serif"] = []

        result = self.apply(manifest, base_feedback(batch))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        written = self.manifest()
        self.assertFalse(payload["workflow_state_changed"])
        self.assertEqual(written["workflow_state"], "testi_approvati")
        self.assertEqual(written["workflow_receipts"], [original_receipt])
        self.assertEqual(written["items"][0]["summary_serif"], [])
        self.assertEqual(payload["stale_alt_text"], [])
        self.assertFalse(payload["stale_transcript"])
        self.assertFalse(written["proof"]["approved"])

    def test_visual_approval_requires_saving_an_emphasis_change_first(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest_path = self.workdir / "emphasis-fingerprint-source.json"
        write_json(manifest_path, manifest)
        base_model = apply_review.server_manifest_model(manifest_path)
        candidate = copy.deepcopy(manifest)
        candidate["items"][0]["summary_serif"] = []
        candidate_model = apply_review.server_manifest_model(
            manifest_path, manifest=candidate
        )
        batch = self.full_batch()
        batch[1]["summary_serif"] = []
        feedback = base_feedback(
            batch,
            action="approve",
            approval_stage="visual_proof",
            base_workflow_state="testi_approvati",
            base_render_fingerprint=base_model["render_fingerprint"],
            render_fingerprint=candidate_model["render_fingerprint"],
            proof_slide_ids=candidate_model["proof"]["required_slide_ids"],
            style_system_verified=True,
            proof_browser={"engine": "chromium", "major": 140},
        )

        result = self.apply(manifest, feedback)

        self.assertEqual(result.returncode, 2)
        self.assertIn("modifiche ancora locali", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest(), manifest)

    def test_visual_checkpoint_rejects_legacy_or_incomplete_approval_batches(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
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

    def visual_approval_feedback(
        self,
        manifest: dict,
        *,
        slides: list[dict] | None = None,
        style: str | None = None,
        logo_mode: str | None = None,
    ) -> dict:
        manifest_path = self.workdir / "fingerprint-source.json"
        write_json(manifest_path, manifest)
        base_model = apply_review.server_manifest_model(manifest_path)
        candidate = copy.deepcopy(manifest)
        if style is not None:
            candidate["visual_style_system"] = style
        if logo_mode is not None:
            candidate["logo_mode"] = logo_mode
        candidate_slides = slides or self.full_batch()
        candidate_manifest = copy.deepcopy(candidate)
        candidate_manifest["cover_title"] = candidate_slides[0]["title"]
        candidate_manifest["cover_subtitle"] = candidate_slides[0]["summary"]
        by_id = {item["id"]: item for item in candidate_manifest["items"]}
        candidate_manifest["items"] = [
            {
                **by_id[slide_value["id"]],
                "title": slide_value["title"],
                "summary": slide_value["summary"],
            }
            for slide_value in candidate_slides
            if slide_value["kind"] == "item"
        ]
        candidate_manifest["outro"] = {
            **candidate_manifest["outro"],
            "title": candidate_slides[-1]["title"],
            "body": candidate_slides[-1]["summary"],
        }
        densest = max(
            candidate_manifest["items"],
            key=lambda item: len(item.get("title", "").strip())
            + len(item.get("summary", "").strip()),
        )["id"]
        candidate_manifest["proof"]["slide_ids"] = ["cover", densest, "outro"]
        candidate_model = apply_review.server_manifest_model(
            manifest_path, manifest=candidate_manifest
        )
        return base_feedback(
            candidate_slides,
            action="approve",
            approval_stage="visual_proof",
            base_workflow_state=manifest["workflow_state"],
            base_render_fingerprint=base_model["render_fingerprint"],
            render_fingerprint=candidate_model["render_fingerprint"],
            proof_slide_ids=candidate_model["proof"]["required_slide_ids"],
            style_system_verified=True,
            proof_browser={"engine": "chromium", "major": 140},
            **({"visual_style_system": style} if style is not None else {}),
            **({"logo_mode": logo_mode} if logo_mode is not None else {}),
        )

    def test_visual_proof_binding_preserves_the_complete_text_receipt(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        original_receipt = copy.deepcopy(manifest["workflow_receipts"][0])

        result = self.apply(manifest, self.visual_approval_feedback(manifest))

        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.manifest()
        self.assertEqual(written["workflow_state"], "testi_approvati")
        self.assertEqual(written["workflow_receipts"], [original_receipt])
        self.assertTrue(written["proof"]["approved"])
        self.assertTrue(written["proof"]["style_system_verified"])

    def test_visual_only_reapproval_rewinds_to_texts_and_preserves_its_receipt(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "qa")
        original_receipt = copy.deepcopy(manifest["workflow_receipts"][0])
        feedback = self.visual_approval_feedback(
            manifest,
            style="corporate-modular",
            logo_mode="hidden",
        )

        result = self.apply(manifest, feedback)

        self.assertEqual(result.returncode, 0, result.stderr)
        written = self.manifest()
        self.assertEqual(written["workflow_state"], "testi_approvati")
        self.assertEqual(written["workflow_receipts"], [original_receipt])
        self.assertEqual(written["visual_style_system"], "corporate-modular")
        self.assertEqual(written["logo_mode"], "hidden")
        self.assertTrue(written["proof"]["approved"])

    def test_visual_approval_cannot_smuggle_editorial_changes(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        slides = self.full_batch(**{"item-1": "Testo editoriale cambiato."})
        feedback = self.visual_approval_feedback(manifest, slides=slides)

        result = self.apply(manifest, feedback)

        self.assertEqual(result.returncode, 2)
        self.assertIn("modifiche ancora locali", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest(), manifest)

    def test_empty_feedback_cannot_reopen_an_approved_checkpoint(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")

        result = self.apply(manifest, base_feedback(self.full_batch()))

        self.assertEqual(result.returncode, 2)
        self.assertIn("feedback vuoto", json.loads(result.stderr)["error"])
        self.assertEqual(self.manifest(), manifest)

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

        batch[1]["title"] = ""
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

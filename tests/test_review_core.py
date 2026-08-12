"""Regression tests for shared persistence and text-normalization primitives."""

from __future__ import annotations

import json
import multiprocessing
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import SCRIPTS

import sys

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import review_core  # noqa: E402


def _append_then_die_after_link(path: str) -> None:
    real_link = review_core.os.link

    def link_and_die(source: str, target: str) -> None:
        real_link(source, target)
        os._exit(73)

    with mock.patch.object(review_core.os, "link", side_effect=link_and_die):
        review_core.append_only_json(Path(path), {"value": 1})


class TrackingString(str):
    def __new__(cls, value: str):
        instance = super().__new__(cls, value)
        instance.slice_widths = []
        return instance

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step == 1:
                self.slice_widths.append(max(0, stop - start))
        return super().__getitem__(key)


class SentenceLineBreaksTest(unittest.TestCase):
    def test_preserves_output_without_copying_every_preceding_prefix(self) -> None:
        value = TrackingString("Dott. Rossi usa la versione 1.2. Funziona? Sì! Fine. " * 250)

        rendered = review_core.sentence_line_breaks(value)

        self.assertIn("Dott. Rossi usa la versione 1.2.\nFunziona?\nSì!\nFine.", rendered)
        self.assertTrue(value.slice_widths)
        self.assertLessEqual(max(value.slice_widths), len("versione"))


class WorkflowContractTest(unittest.TestCase):
    def test_shared_style_logo_and_browser_normalizers_match_public_contracts(self) -> None:
        for alias, expected in (
            (" Editorial ", "editorial-frame"),
            ("geometrico", "editorial-halftone"),
            ("ISTITUZIONALE", "corporate-modular"),
        ):
            with self.subTest(alias=alias):
                self.assertEqual(
                    review_core.normalized_visual_style_system(alias), expected
                )
        self.assertIsNone(review_core.normalized_visual_style_system("sconosciuto"))
        self.assertEqual(review_core.normalized_logo_mode(" Hidden "), "hidden")
        self.assertIsNone(review_core.normalized_logo_mode(["auto"]))
        browser = {"engine": "chromium", "major": 140}
        self.assertEqual(review_core.normalized_proof_browser(browser), browser)
        self.assertEqual(review_core.validated_proof_browser(browser), browser)
        with self.assertRaisesRegex(ValueError, "proof.browser.engine"):
            review_core.normalized_proof_browser(
                {"engine": "firefox", "major": 140}, required=True
            )
        with self.assertRaisesRegex(ValueError, "proof_browser.engine"):
            review_core.validated_proof_browser(
                {"engine": "firefox", "major": 140}
            )

    def test_canonical_transition_table_is_forward_only(self) -> None:
        states = review_core.CANONICAL_WORKFLOW_STATES
        for current, target in zip(states, states[1:]):
            with self.subTest(current=current, target=target):
                review_core.validate_canonical_workflow_transition(current, target)

        for current, target in (
            ("bozza", "prova_visuale_approvata"),
            ("qa", "rendering"),
            ("consegnato", "consegnato"),
            ("draft", "testi_approvati"),
        ):
            with self.subTest(current=current, target=target), self.assertRaises(
                ValueError
            ):
                review_core.validate_canonical_workflow_transition(current, target)

    def test_legacy_states_remain_readable_but_not_canonical(self) -> None:
        self.assertEqual(review_core.approval_stage_for_workflow("draft"), "profile_text")
        self.assertEqual(review_core.approval_stage_for_workflow("approved"), "visual_proof")
        self.assertNotIn("draft", review_core.CANONICAL_WORKFLOW_STATES)

    def test_workflow_receipt_ledger_is_bounded_continuous_and_state_bound(self) -> None:
        first = {
            "from": "bozza",
            "to": "testi_approvati",
            "revision": 1,
            "render_fingerprint": "a" * 64,
            "evidence_sha256": "b" * 64,
            "advanced_at": "2026-08-12T12:00:00+00:00",
        }
        second = {
            **first,
            "from": "testi_approvati",
            "to": "prova_visuale_approvata",
        }
        self.assertEqual(
            review_core.validate_workflow_receipts(
                [first, second], current_state="prova_visuale_approvata"
            ),
            [first, second],
        )
        self.assertEqual(
            review_core.validate_workflow_receipts([], current_state="qa"), []
        )
        with self.assertRaisesRegex(ValueError, "workflow_state"):
            review_core.validate_workflow_receipts(
                [first, second], current_state="testi_approvati"
            )
        broken = {**second, "from": "rendering", "to": "qa"}
        with self.assertRaisesRegex(ValueError, "catena"):
            review_core.validate_workflow_receipts(
                [first, broken], current_state="qa"
            )

    def test_unhashable_workflow_values_fail_as_validation_errors(self) -> None:
        for value in ([], {}, ["bozza"]):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "workflow_state"
            ):
                review_core.approval_stage_for_workflow(value)


class AtomicPersistenceTest(unittest.TestCase):
    def test_atomic_replace_fsyncs_the_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            with mock.patch.object(
                review_core, "fsync_directory", wraps=review_core.fsync_directory
            ) as sync:
                review_core.atomic_write_json(path, {"value": 1}, private_parent=False)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})
            sync.assert_any_call(path.parent)

    @unittest.skipIf(os.name == "nt", "i mode POSIX non sono disponibili su Windows")
    def test_atomic_replace_preserves_a_safe_existing_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            path.write_text('{"value": 0}', encoding="utf-8")
            path.chmod(0o640)

            review_core.atomic_write_json(path, {"value": 1}, private_parent=False)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_atomic_replace_rejects_a_symlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            victim = root / "victim.json"
            victim.write_text('{"secret": true}', encoding="utf-8")
            victim.chmod(0o644)
            before_content = victim.read_bytes()
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            target = root / "state.json"
            target.symlink_to(victim)

            with self.assertRaisesRegex(ValueError, "collegamento simbolico"):
                review_core.atomic_write_json(
                    target, {"value": 1}, private_parent=False
                )

            self.assertTrue(target.is_symlink())
            self.assertEqual(victim.read_bytes(), before_content)
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_atomic_replace_rejects_a_hardlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            victim = root / "victim.json"
            victim.write_text('{"secret": true}', encoding="utf-8")
            victim.chmod(0o644)
            before_content = victim.read_bytes()
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            target = root / "state.json"
            os.link(victim, target)

            with self.assertRaisesRegex(ValueError, "Target JSON esistente non sicuro"):
                review_core.atomic_write_json(
                    target, {"value": 1}, private_parent=False
                )

            self.assertEqual(victim.read_bytes(), before_content)
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)

    def test_atomic_replace_rejects_a_non_regular_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "state.json"
            target.mkdir()

            with self.assertRaisesRegex(ValueError, "Target JSON esistente non sicuro"):
                review_core.atomic_write_json(
                    target, {"value": 1}, private_parent=False
                )

    @unittest.skipUnless(
        hasattr(os, "fchmod") and os.name != "nt",
        "fchmod e symlink POSIX richiesti",
    )
    def test_atomic_replace_rejects_a_swapped_temporary_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "state.json"
            victim = root / "victim.json"
            victim.write_text('{"secret": true}', encoding="utf-8")
            victim.chmod(0o644)
            before_content = victim.read_bytes()
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            displaced = root / "displaced.tmp"
            real_fchmod = review_core.os.fchmod

            def inject_symlink(descriptor: int, mode: int) -> None:
                real_fchmod(descriptor, mode)
                generated = next(root.glob(".state.json.*.tmp"))
                generated.rename(displaced)
                generated.symlink_to(victim)

            with mock.patch.object(
                review_core.os, "fchmod", side_effect=inject_symlink
            ), self.assertRaisesRegex(ValueError, "temporaneo non sicuro"):
                review_core.atomic_write_json(
                    target, {"value": 1}, private_parent=False
                )

            self.assertFalse(target.exists())
            self.assertFalse(target.is_symlink())
            self.assertEqual(victim.read_bytes(), before_content)
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)
            self.assertTrue(displaced.is_file())

    def test_append_only_link_fsyncs_the_archive_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            with mock.patch.object(
                review_core, "fsync_directory", wraps=review_core.fsync_directory
            ) as sync:
                self.assertTrue(review_core.append_only_json(path, {"value": 1}))

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})
            sync.assert_any_call(path.parent)

    def test_append_only_exact_replay_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            self.assertTrue(review_core.append_only_json(path, {"value": 1}))

            self.assertFalse(review_core.append_only_json(path, {"value": 1}))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_append_only_reconciles_a_process_killed_immediately_after_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            process = multiprocessing.Process(
                target=_append_then_die_after_link, args=(str(path),)
            )
            process.start()
            process.join(timeout=5)

            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 73)
            residue = review_core._append_only_temporary_path(path, {"value": 1})
            self.assertTrue(path.is_file())
            self.assertTrue(residue.is_file())
            self.assertEqual(path.stat().st_ino, residue.stat().st_ino)
            self.assertEqual(path.stat().st_nlink, 2)

            self.assertFalse(review_core.append_only_json(path, {"value": 1}))
            self.assertFalse(residue.exists())
            self.assertEqual(path.stat().st_nlink, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_append_only_reconciles_a_durable_power_loss_twin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            path.parent.mkdir(mode=0o700)
            residue = review_core._append_only_temporary_path(path, {"value": 1})
            residue.write_bytes(review_core._append_only_payload({"value": 1}))
            with residue.open("rb") as stream:
                os.fsync(stream.fileno())
            os.link(residue, path)
            review_core.fsync_directory(path.parent)

            with mock.patch.object(
                review_core, "fsync_directory", wraps=review_core.fsync_directory
            ) as sync:
                self.assertFalse(review_core.append_only_json(path, {"value": 1}))

            self.assertFalse(residue.exists())
            self.assertEqual(path.stat().st_nlink, 1)
            sync.assert_any_call(path.parent)

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_append_only_does_not_reconcile_a_same_inode_twin_with_other_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            path.parent.mkdir(mode=0o700)
            residue = review_core._append_only_temporary_path(path, {"value": 1})
            residue.write_bytes(review_core._append_only_payload({"value": 2}))
            os.link(residue, path)

            with self.assertRaisesRegex(ValueError, "stessa operazione"):
                review_core.append_only_json(path, {"value": 1})

            self.assertTrue(residue.exists())
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_ino, residue.stat().st_ino)
            self.assertEqual(path.stat().st_nlink, 2)

    def test_append_only_reuses_an_exact_lone_power_loss_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            path.parent.mkdir(mode=0o700)
            residue = review_core._append_only_temporary_path(path, {"value": 1})
            residue.write_bytes(review_core._append_only_payload({"value": 1}))
            residue.chmod(0o600)

            self.assertTrue(review_core.append_only_json(path, {"value": 1}))
            self.assertFalse(residue.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_append_only_rejects_a_foreign_hardlink_at_the_recovery_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "archive" / "batch.json"
            path.parent.mkdir(mode=0o700)
            victim = root / "victim.json"
            victim.write_bytes(review_core._append_only_payload({"value": 1}))
            residue = review_core._append_only_temporary_path(path, {"value": 1})
            os.link(victim, residue)

            with self.assertRaisesRegex(ValueError, "append-only non sicuro"):
                review_core.append_only_json(path, {"value": 1})

            self.assertFalse(path.exists())
            self.assertTrue(victim.exists())
            self.assertTrue(residue.exists())

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_append_only_rejects_a_hardlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "archive" / "batch.json"
            path.parent.mkdir()
            victim = root / "victim.json"
            victim.write_text('{"value": 1}', encoding="utf-8")
            victim.chmod(0o644)
            before_content = victim.read_bytes()
            before_mode = victim.stat().st_mode
            os.link(victim, path)

            with self.assertRaisesRegex(ValueError, "append-only non sicuro"):
                review_core.append_only_json(path, {"value": 1})

            self.assertEqual(victim.read_bytes(), before_content)
            self.assertEqual(victim.stat().st_mode, before_mode)

    @unittest.skipUnless(
        hasattr(os, "fchmod") and os.name != "nt",
        "fchmod e symlink POSIX richiesti",
    )
    def test_append_only_rejects_a_swapped_temporary_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "archive" / "batch.json"
            victim = root / "victim.json"
            victim.write_text('{"secret": true}', encoding="utf-8")
            victim.chmod(0o644)
            before_content = victim.read_bytes()
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            displaced = root / "displaced.tmp"
            real_fchmod = review_core.os.fchmod

            def inject_symlink(descriptor: int, mode: int) -> None:
                real_fchmod(descriptor, mode)
                generated = review_core._append_only_temporary_path(
                    path, {"value": 1}
                )
                generated.rename(displaced)
                generated.symlink_to(victim)

            with mock.patch.object(
                review_core.os, "fchmod", side_effect=inject_symlink
            ), self.assertRaisesRegex(ValueError, "temporaneo non sicuro"):
                review_core.append_only_json(path, {"value": 1})

            self.assertFalse(path.exists())
            self.assertFalse(path.is_symlink())
            self.assertEqual(victim.read_bytes(), before_content)
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)
            self.assertTrue(displaced.is_file())

    def test_a_directory_fsync_failure_is_not_reported_as_a_durable_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            with mock.patch.object(
                review_core, "fsync_directory", side_effect=OSError("sync failed")
            ):
                with self.assertRaisesRegex(OSError, "sync failed"):
                    review_core.atomic_write_json(
                        path, {"value": 1}, private_parent=False
                    )

            # The rename may already have happened, but callers are correctly
            # told that crash durability was not established.
            self.assertTrue(path.is_file())


def _try_lock(path: str, queue: multiprocessing.Queue) -> None:
    try:
        with review_core.InterprocessLock(Path(path)):
            queue.put("acquired")
    except review_core.LockUnavailableError:
        queue.put("unavailable")


class InterprocessLockTest(unittest.TestCase):
    def test_a_second_process_cannot_acquire_the_same_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "review.lock"
            queue: multiprocessing.Queue = multiprocessing.Queue()
            with review_core.InterprocessLock(path):
                process = multiprocessing.Process(
                    target=_try_lock, args=(str(path), queue)
                )
                process.start()
                process.join(timeout=5)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(queue.get(timeout=1), "unavailable")


if __name__ == "__main__":
    unittest.main()

"""Regression tests for shared persistence and text-normalization primitives."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import SCRIPTS

import sys

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import review_core  # noqa: E402


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

    def test_append_only_link_fsyncs_the_archive_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive" / "batch.json"
            with mock.patch.object(
                review_core, "fsync_directory", wraps=review_core.fsync_directory
            ) as sync:
                self.assertTrue(review_core.append_only_json(path, {"value": 1}))

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"value": 1})
            sync.assert_any_call(path.parent)

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


if __name__ == "__main__":
    unittest.main()

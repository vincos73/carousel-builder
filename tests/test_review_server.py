"""Test di review_server.py: modello editoriale e validazione dei batch."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from support import base_manifest, slide

SPEC = importlib.util.spec_from_file_location(
    "review_server", Path(__file__).resolve().parent.parent / "scripts" / "review_server.py"
)
review_server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(review_server)


class ManifestModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def model(self, manifest: dict | None = None) -> dict:
        path = self.workdir / "manifest.json"
        path.write_text(
            json.dumps(manifest if manifest is not None else base_manifest()),
            encoding="utf-8",
        )
        return review_server.manifest_model(path)

    def test_builds_cover_items_and_outro(self) -> None:
        model = self.model()
        self.assertEqual(
            [entry["id"] for entry in model["slides"]],
            ["cover", "item-1", "item-2", "outro"],
        )
        self.assertFalse(model["slides"][0]["deletable"])
        self.assertTrue(model["slides"][1]["deletable"])
        self.assertFalse(model["slides"][-1]["deletable"])

    def test_omits_a_disabled_outro(self) -> None:
        manifest = base_manifest()
        manifest["outro"]["enabled"] = False
        self.assertNotIn("outro", [entry["id"] for entry in self.model(manifest)["slides"]])

    def test_rejects_a_manifest_without_items(self) -> None:
        manifest = base_manifest()
        manifest["items"] = []
        with self.assertRaises(ValueError):
            self.model(manifest)

    def test_rejects_duplicate_item_ids(self) -> None:
        manifest = base_manifest()
        manifest["items"][1]["id"] = "item-1"
        with self.assertRaises(ValueError):
            self.model(manifest)

    def test_falls_back_to_a_known_sequence_mode(self) -> None:
        manifest = base_manifest()
        manifest["sequence_mode"] = "qualcosa"
        self.assertEqual(self.model(manifest)["sequence_mode"], "narrative")

    def test_exposes_only_the_brand_summary(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "name": "Studio",
            "fonts": {"sans": {"family": "Brand Sans"}},
            "palette": {"accent": "#C65A3A"},
            "logos": {"on_light": "assets/logo.svg"},
        }
        brand = self.model(manifest)["brand"]
        self.assertEqual(brand["name"], "Studio")
        self.assertEqual(brand["sans"], "Brand Sans")
        self.assertEqual(brand["palette"]["accent"], "#C65A3A")
        self.assertNotIn("logos", brand)


class ValidateFeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        path = self.workdir / "manifest.json"
        path.write_text(json.dumps(base_manifest()), encoding="utf-8")
        self.model = review_server.manifest_model(path)

    def payload(self, slides: list[dict] | None = None, **overrides: object) -> dict:
        value = {
            "action": "feedback",
            "base_revision": 1,
            "slides": slides
            if slides is not None
            else [
                slide("cover", "cover", title="La lezione e operativa"),
                slide("item-1", "item", summary="Prima frase."),
                slide("item-2", "item", summary="Seconda frase."),
                slide("outro", "outro", title="Chiusura", summary="Corpo della chiusura."),
            ],
            "comments": [],
            "overall_note": "",
        }
        value.update(overrides)
        return value

    def test_accepts_a_well_formed_batch(self) -> None:
        result = review_server.validate_feedback(self.payload(), self.model)
        self.assertEqual(result["action"], "feedback")
        self.assertTrue(result["feedback_id"].startswith("feedback-"))
        self.assertEqual(len(result["slides"]), 4)

    def test_accepts_deletion_and_reorder(self) -> None:
        slides = [
            slide("cover", "cover", title="La lezione e operativa"),
            slide("item-2", "item", summary="Seconda frase."),
            slide("outro", "outro", title="Chiusura", summary="Corpo."),
        ]
        result = review_server.validate_feedback(self.payload(slides), self.model)
        self.assertEqual(
            [entry["id"] for entry in result["slides"]], ["cover", "item-2", "outro"]
        )

    def test_rejects_a_stale_base_revision(self) -> None:
        with self.assertRaises(RuntimeError):
            review_server.validate_feedback(self.payload(base_revision=9), self.model)

    def test_rejects_an_unknown_slide(self) -> None:
        slides = self.payload()["slides"]
        slides[1] = slide("item-99", "item", summary="Testo.")
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_duplicated_slide(self) -> None:
        slides = self.payload()["slides"]
        slides[2] = dict(slides[1])
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_changed_slide_kind(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["kind"] = "cover"
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_cover_that_is_not_first(self) -> None:
        slides = self.payload()["slides"]
        slides[0], slides[1] = slides[1], slides[0]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_an_outro_that_is_not_last(self) -> None:
        slides = self.payload()["slides"]
        slides[2], slides[3] = slides[3], slides[2]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_batch_without_items(self) -> None:
        slides = [
            slide("cover", "cover", title="La lezione e operativa"),
            slide("outro", "outro", title="Chiusura", summary="Corpo."),
        ]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_an_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(action="delete"), self.model)

    def test_rejects_an_unknown_comment_kind(self) -> None:
        comment = {"kind": "altro", "slide_id": "item-1", "feedback": "x"}
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(comments=[comment]), self.model
            )

    def test_rejects_a_comment_on_an_unknown_slide(self) -> None:
        comment = {"kind": "slide", "slide_id": "item-99", "feedback": "x"}
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(comments=[comment]), self.model
            )

    def test_accepts_a_brand_comment_without_a_slide(self) -> None:
        comment = {"kind": "brand", "slide_id": "", "feedback": "Fondo più chiaro"}
        result = review_server.validate_feedback(
            self.payload(comments=[comment]), self.model
        )
        self.assertEqual(result["comments"][0]["kind"], "brand")

    def test_rejects_text_over_the_limit(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "x" * (review_server.MAX_TEXT + 1)
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_too_many_comments(self) -> None:
        comment = {"kind": "brand", "slide_id": "", "feedback": "x"}
        comments = [dict(comment) for _ in range(review_server.MAX_COMMENTS + 1)]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(comments=comments), self.model
            )


if __name__ == "__main__":
    unittest.main()

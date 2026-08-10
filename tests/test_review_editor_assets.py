"""Regression guards for the mirrored local review editor assets."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "assets" / "review-editor" / "app.js"
PLUGIN_EDITOR = (
    ROOT
    / "agent-plugin"
    / "skills"
    / "carousel-builder"
    / "assets"
    / "review-editor"
    / "app.js"
)


class ReviewEditorAssetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = EDITOR.read_text(encoding="utf-8")

    def test_root_and_agent_plugin_editors_match(self) -> None:
        self.assertEqual(
            self.source,
            PLUGIN_EDITOR.read_text(encoding="utf-8"),
        )

    def test_cover_fields_are_multiline_for_visible_text_selection(self) -> None:
        self.assertIn(
            'makeField(slide, "title", titleLabel, slide.kind === "cover"',
            self.source,
        )
        self.assertIn(
            'makeField(slide, "summary", summaryLabel, true',
            self.source,
        )

    def test_unavailable_italic_can_still_be_removed(self) -> None:
        self.assertIn(
            'button.disabled = !hasSelection || (!available && !active);',
            self.source,
        )
        self.assertIn(
            'if (kind === "italic" && !hasRealItalicFont() && existingIndex < 0) return;',
            self.source,
        )
        self.assertIn(
            'Rimuovi il corsivo non disponibile dalla selezione',
            self.source,
        )

    def test_stale_emphasis_is_pruned_from_saved_and_edited_text(self) -> None:
        self.assertIn(
            "pruneStaleEmphasis(draftSlides);",
            self.source,
        )
        self.assertIn(
            "pruneStaleEmphasis([slide]);",
            self.source,
        )
        self.assertIn(
            "text.includes(segment)",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()

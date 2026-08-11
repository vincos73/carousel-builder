"""Regression guards for the mirrored local review editor assets."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EDITOR_DIR = ROOT / "assets" / "review-editor"
PLUGIN_EDITOR_DIR = (
    ROOT
    / "agent-plugin"
    / "skills"
    / "carousel-builder"
    / "assets"
    / "review-editor"
)
EDITOR = EDITOR_DIR / "app.js"
PLUGIN_EDITOR = PLUGIN_EDITOR_DIR / "app.js"
EXPORTER = ROOT / "scripts" / "export_review_pdf.cjs"
PLUGIN_EXPORTER = (
    ROOT
    / "agent-plugin"
    / "skills"
    / "carousel-builder"
    / "scripts"
    / "export_review_pdf.cjs"
)


class ReviewEditorAssetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = EDITOR.read_text(encoding="utf-8")

    def test_root_and_agent_plugin_editors_match(self) -> None:
        for name in ("app.js", "index.html", "styles.css", "vincos-lockup-white.svg"):
            with self.subTest(name=name):
                self.assertEqual(
                    (EDITOR_DIR / name).read_bytes(),
                    (PLUGIN_EDITOR_DIR / name).read_bytes(),
                )

    def test_root_and_agent_plugin_exporters_match(self) -> None:
        self.assertEqual(EXPORTER.read_bytes(), PLUGIN_EXPORTER.read_bytes())

    def test_pdf_export_reuses_approved_preview_renderer(self) -> None:
        stylesheet = (EDITOR_DIR / "styles.css").read_text(encoding="utf-8")
        exporter = EXPORTER.read_text(encoding="utf-8")
        self.assertIn("productionRender", self.source)
        self.assertIn("approved-preview-dom-v1", self.source)
        self.assertIn("getSlideFrames", self.source)
        self.assertIn("getSlideGeometry", self.source)
        self.assertIn('preview.dataset.productionSource = "approved-preview"', self.source)
        self.assertIn("html.production-render .slide-preview", stylesheet)
        self.assertNotIn("production-render .preview-sphere", stylesheet)
        self.assertIn("window.carouselBuilderPreview", exporter)
        self.assertIn('searchParams.set("render", "production")', exporter)
        self.assertIn("Preview/production geometry mismatch", exporter)
        self.assertIn('row.style.display = previewIndex === targetIndex ? "block" : "none"', exporter)
        self.assertIn("targetPreview.screenshot", exporter)
        self.assertIn('externalRequire("sharp")', exporter)
        self.assertIn('externalRequire("pdf-lib")', exporter)
        self.assertNotIn("preview-sphere-primary", exporter)

    def test_review_copy_is_actionable_and_product_is_branded(self) -> None:
        html = (EDITOR_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="product-byline"', html)
        self.assertIn('/assets/vincos-lockup-white.svg', html)
        self.assertIn('class="workflow-status"', html)
        self.assertIn('id="builder-version"', html)
        self.assertIn("Commenta lo stile", html)
        self.assertIn("Stile riutilizzabile", html)
        self.assertIn('id="export-style-button"', html)
        self.assertIn('id="brand-typography"', html)
        self.assertIn("Correggi i testi nell’editor accanto all’anteprima", html)
        self.assertIn("Indicazione per l’intero carosello", html)
        self.assertNotIn("Commento sul profilo", html)
        self.assertNotIn("Un'osservazione sull'intera sequenza", html)
        self.assertNotIn('id="brand-details"', html)
        self.assertNotIn('id="change-label"', html)

    def test_status_is_consolidated_and_style_can_be_saved(self) -> None:
        html = (EDITOR_DIR / "index.html").read_text(encoding="utf-8")
        stylesheet = (EDITOR_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("exportedStyleProfile", self.source)
        self.assertIn("brand_profile", self.source)
        self.assertIn("Stile JSON salvato", self.source)
        self.assertIn("Ti aggiorno qui appena", self.source)
        self.assertIn("Prova visiva · copertina tipografica", self.source)
        self.assertIn(".style-transfer", stylesheet)
        self.assertIn(".builder-version", stylesheet)
        self.assertIn(".actionbar {\n  justify-content: flex-end;", stylesheet)
        self.assertIn("background: var(--editor-navy);", stylesheet)
        self.assertIn("color: #e4bfd5;", stylesheet)
        self.assertIn("color: var(--editor-plum-on-dark);", stylesheet)
        self.assertNotIn("background: var(--vincos-navy);", stylesheet)
        self.assertNotIn('id="change-label"', html)

    def test_applied_formats_are_compact_visible_and_directly_removable(self) -> None:
        stylesheet = (EDITOR_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn('active ? "true" : mixed ? "mixed" : "false"', self.source)
        self.assertIn('"Formato nel testo"', self.source)
        self.assertNotIn('"Stili applicati"', self.source)
        self.assertIn('class="workflow-status"', (EDITOR_DIR / "index.html").read_text(encoding="utf-8"))
        self.assertIn(".applied-style-chip", stylesheet)
        self.assertIn("border-radius: 999px", stylesheet)
        self.assertIn("renderAppliedStyles();", self.source)
        self.assertIn("value !== segment", self.source)

    def test_existing_format_is_recognized_and_overlap_is_prevented(self) -> None:
        self.assertIn("const selectionState = (kind, start, end) =>", self.source)
        self.assertIn("start >= range.start && end <= range.end", self.source)
        self.assertIn("const conflict = firstStyleOverlap(start, end);", self.source)
        self.assertIn("Rimuovi prima il formato dalla riga sotto il testo.", self.source)
        self.assertIn('button.setAttribute("aria-pressed", active ? "true" : mixed ? "mixed" : "false");', self.source)

    def test_preview_grids_do_not_split_words_arbitrarily(self) -> None:
        stylesheet = (EDITOR_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("overflow-wrap: anywhere", stylesheet)
        self.assertIn(".slide-preview.visual-system-editorial-frame .preview-copy", stylesheet)
        self.assertIn('visual-system-editorial-halftone[data-kind="cover"] .preview-copy', stylesheet)
        self.assertGreaterEqual(stylesheet.count("width: 88%;"), 3)
        self.assertIn("hyphens: none", stylesheet)

    def test_local_editor_requires_clean_initial_fit(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow = (ROOT / "references" / "editorial-workflow.md").read_text(encoding="utf-8")
        visual_review = (ROOT / "references" / "visual-review.md").read_text(encoding="utf-8")
        self.assertIn("nessuna slide iniziale deve mostrare avvisi di densità o overflow", skill)
        self.assertIn("`local-editor` è obbligatorio", skill)
        self.assertIn("al massimo 180 caratteri", skill)
        self.assertIn("al massimo 320 caratteri", skill)
        self.assertIn("una prima proposta già impaginabile", workflow)
        self.assertIn("trattare le soglie come limiti rigidi", workflow)
        self.assertIn("ciascuno dei tre sistemi visivi", visual_review)
        self.assertIn("l'apertura dell'editor è obbligatoria", visual_review)

    def test_vincos_logo_is_the_approved_outlined_lockup(self) -> None:
        logo = (EDITOR_DIR / "vincos-lockup-white.svg").read_text(encoding="utf-8")
        self.assertIn('viewBox="0 0 2659.620 250.000"', logo)
        self.assertIn("Tamrin wordmark", logo)
        self.assertNotIn("<script", logo.casefold())

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
            'if (kind === "italic" && !hasRealItalicFont() && !removableSegment) return;',
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

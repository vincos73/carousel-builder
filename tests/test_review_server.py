"""Test di review_server.py: modello editoriale e validazione dei batch."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from support import base_manifest, slide, write_json

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

    def test_exposes_optional_cover_subtitle(self) -> None:
        manifest = base_manifest()
        manifest["cover_subtitle"] = "Ecco cosa puoi fare"
        cover = self.model(manifest)["slides"][0]
        self.assertEqual(cover["summary"], "Ecco cosa puoi fare")

    def test_exposes_a_safe_cover_image_endpoint_without_a_local_path(self) -> None:
        image = self.workdir / "cover.png"
        image.write_bytes(b"png")
        manifest = base_manifest()
        manifest["cover_image"] = "cover.png"
        manifest["cover_image_position"] = "40% 60%"
        model = self.model(manifest)
        self.assertEqual(
            model["cover_visual"],
            {
                "available": True,
                "endpoint": "/api/cover-image",
                "position": "40% 60%",
                "mode": "provided",
            },
        )
        self.assertNotIn(str(image), json.dumps(model))
        self.assertEqual(model["cover_mode"], "provided")

    def test_exposes_three_same_identity_visual_proofs_and_brand_default(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "name": "Studio",
            "visual_signature": {"style_system": "corporate_modular"},
        }
        proofs = self.model(manifest)["visual_proofs"]
        self.assertEqual(proofs["selected_style_system"], "corporate-modular")
        self.assertEqual(
            [option["id"] for option in proofs["options"]],
            ["editorial-frame", "editorial-halftone", "corporate-modular"],
        )
        self.assertEqual(
            [option["label"] for option in proofs["options"]],
            ["Editoriale", "Geometrico", "Istituzionale"],
        )
        self.assertEqual(proofs["identity"]["brand"]["name"], "Studio")
        self.assertEqual(proofs["identity"]["cover"]["mode"], "typographic")

    def test_visual_style_override_is_validated_and_cover_modes_fall_back_safely(self) -> None:
        image = self.workdir / "cover.png"
        image.write_bytes(b"png")
        manifest = base_manifest()
        manifest.update(
            {
                "visual_style_system": "editorial-halftone",
                "cover_mode": "generated",
                "cover_image": "cover.png",
            }
        )
        proofs = self.model(manifest)["visual_proofs"]
        self.assertEqual(proofs["selected_style_system"], "editorial-halftone")
        self.assertEqual(proofs["identity"]["cover"]["mode"], "generated")

        del manifest["cover_mode"]
        manifest["cover_visual_mode"] = "generative"
        self.assertEqual(self.model(manifest)["cover_mode"], "generated")

        manifest["visual_style_system"] = "non-esiste"
        manifest["cover_image"] = "manca.png"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-frame",
        )
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["identity"]["cover"]["mode"],
            "generated",
        )
        manifest["workflow_state"] = "testi_approvati"
        self.assertEqual(self.model(manifest)["cover_mode"], "typographic")

    def test_accepts_new_visual_system_aliases_without_breaking_canonical_ids(self) -> None:
        manifest = base_manifest()
        manifest["visual_style_system"] = "campo-cromatico"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-halftone",
        )
        manifest["visual_style_system"] = "costellazione"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-halftone",
        )
        manifest["visual_style_system"] = "geometrico"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-halftone",
        )
        manifest["visual_style_system"] = "istituzionale"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "corporate-modular",
        )

    def test_puts_complete_sentences_on_new_lines_but_preserves_versions(self) -> None:
        manifest = base_manifest()
        manifest["items"][0]["summary"] = (
            "È disponibile la versione 1.2. Ora puoi aggiornare. Ultima frase."
        )
        summary = self.model(manifest)["slides"][1]["summary"]
        self.assertEqual(
            summary,
            "È disponibile la versione 1.2.\nOra puoi aggiornare.\nUltima frase.",
        )

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
        self.assertFalse(brand["logos"]["on_light"]["available"])
        self.assertNotIn("assets/logo.svg", json.dumps(brand))

    def test_exposes_a_portable_brand_profile_without_local_asset_paths(self) -> None:
        manifest = base_manifest()
        manifest.update({"visual_style_system": "editorial-halftone"})
        manifest["brand"] = {
            "name": "Studio",
            "website": "https://studio.example",
            "logos": {"on_light": "assets/logo-dark.svg", "on_dark": "assets/logo-light.svg"},
            "fonts": {
                "display": {"family": "Studio Display", "file": "assets/display.ttf", "source": "uploaded"},
                "body": {"family": "Studio Text", "file": "assets/body.ttf", "source": "uploaded"},
            },
            "visual_direction": {"mode": "custom", "description": "Pulito", "internal_slides": "clean_typographic"},
        }
        model = self.model(manifest)
        profile = model["brand_profile"]
        self.assertEqual(model["editor_version"], "2.8.8")
        self.assertEqual(profile["profile_type"], "carousel-brand")
        self.assertEqual(profile["visual_signature"]["style_system"], "editorial-halftone")
        self.assertEqual(profile["fonts"]["display"], {"family": "Studio Display", "source": "uploaded"})
        self.assertEqual(profile["logos"], {})
        self.assertNotIn("assets/", json.dumps(profile))

    def test_exposes_safe_logo_metadata_without_local_paths(self) -> None:
        logo_path = self.workdir / "logo.png"
        logo_path.write_bytes(b"logo")
        manifest = base_manifest()
        manifest["brand"] = {
            "name": "Studio",
            "logos": {"on_light": "logo.png", "on_dark": "missing.png"},
        }
        brand = self.model(manifest)["brand"]
        self.assertEqual(
            brand["logos"]["on_light"],
            {
                "available": True,
                "endpoint": "/api/logo/on-light",
                "source": "manifest",
                "master_format": "png",
            },
        )
        self.assertEqual(
            brand["logos"]["on_dark"],
            {
                "available": False,
                "endpoint": "",
                "source": "",
                "master_format": "png",
            },
        )
        self.assertNotIn(str(logo_path), json.dumps(brand))

    def test_uses_a_sibling_png_preview_for_an_svg_logo_master(self) -> None:
        (self.workdir / "logo.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
        (self.workdir / "logo.png").write_bytes(b"safe preview")
        manifest = base_manifest()
        manifest["brand"] = {"logos": {"on_light": "logo.svg"}}
        logo = self.model(manifest)["brand"]["logos"]["on_light"]
        self.assertEqual(
            logo,
            {
                "available": True,
                "endpoint": "/api/logo/on-light",
                "source": "sibling_png",
                "master_format": "svg",
            },
        )

    def test_exposes_default_logo_mode_and_an_resolved_italic_role(self) -> None:
        italic_path = self.workdir / "body-italic.ttf"
        italic_path.write_bytes(b"italic")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "body_italic": {
                    "family": "Studio Body Italic",
                    "file": "body-italic.ttf",
                    "source": "uploaded",
                },
                "serif_italic": "Playfair Display",
            }
        }
        model = self.model(manifest)
        self.assertEqual(model["logo_mode"], "auto")
        self.assertEqual(model["brand"]["emphasis_italic"]["role"], "body_italic")
        self.assertEqual(model["brand"]["emphasis_italic"]["endpoint"], "/api/font/italic")

    def test_prefers_an_explicit_italic_role_over_body_or_legacy_serif(self) -> None:
        for name in ("explicit.ttf", "body-italic.ttf"):
            (self.workdir / name).write_bytes(name.encode("utf-8"))
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "emphasis_italic": {"family": "Explicit", "file": "explicit.ttf"},
                "body_italic": {"family": "Body", "file": "body-italic.ttf"},
                "serif_italic": "Playfair Display",
            }
        }
        italic = self.model(manifest)["brand"]["font_assets"]["italic"]
        self.assertEqual(italic["role"], "emphasis_italic")
        self.assertEqual(italic["family"], "Explicit")

    def test_exposes_distinct_display_and_body_roles(self) -> None:
        display_path = self.workdir / "display.ttf"
        body_path = self.workdir / "body.ttf"
        display_path.write_bytes(b"display")
        body_path.write_bytes(b"body")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "display": {
                    "family": "Studio Display",
                    "file": "display.ttf",
                    "source": "uploaded",
                },
                "body": {
                    "family": "Studio Body",
                    "file": "body.ttf",
                    "source": "uploaded",
                },
            }
        }
        brand = self.model(manifest)["brand"]
        self.assertEqual(brand["display"], "Studio Display")
        self.assertEqual(brand["body"], "Studio Body")
        self.assertEqual(brand["sans"], "Studio Body")
        self.assertEqual(brand["font_assets"]["display"]["endpoint"], "/api/font/display")
        self.assertEqual(brand["font_assets"]["body"]["endpoint"], "/api/font/body")
        self.assertEqual(brand["font_assets"]["sans"]["endpoint"], "/api/font/sans")

    def test_maps_legacy_sans_to_display_and_body(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {"fonts": {"sans": "Inter"}}
        brand = self.model(manifest)["brand"]
        self.assertEqual(brand["display"], "Inter")
        self.assertEqual(brand["body"], "Inter")
        self.assertTrue(brand["font_assets"]["display"]["available"])
        self.assertTrue(brand["font_assets"]["body"]["available"])

    def test_normalizes_typography_and_never_scales_below_documented_floor(self) -> None:
        manifest = base_manifest()
        manifest["typography"] = {
            "cover_px": "large",
            "section_title_px": 88,
            "body_px": True,
            "cover_weight": 700,
            "section_title_weight": None,
            "body_weight": 630,
            "body_line_height": "dense",
            "sentence_gap_em": "tight",
            "body_tracking_em": 2,
            "min_auto_scale": 0.4,
            "overflow_policy": "shrink_forever",
        }
        typography = self.model(manifest)["typography"]
        self.assertEqual(typography["cover_px"], 112)
        self.assertEqual(typography["cover_subtitle_px"], 56)
        self.assertEqual(typography["section_title_px"], 88)
        self.assertEqual(typography["body_px"], 64)
        self.assertEqual(typography["cover_weight"], 700)
        self.assertEqual(typography["cover_subtitle_weight"], 500)
        self.assertEqual(typography["section_title_weight"], 800)
        self.assertEqual(typography["body_weight"], 630)
        self.assertEqual(typography["body_line_height"], 1.12)
        self.assertEqual(typography["sentence_gap_em"], 0.6)
        self.assertEqual(typography["cover_subtitle_line_height"], 1.08)
        self.assertEqual(typography["body_tracking_em"], -0.025)
        self.assertEqual(typography["min_auto_scale"], 0.92)
        self.assertEqual(typography["overflow_policy"], "error_and_copy_revision")

    def test_exposes_only_exact_emphasis_for_each_slide_field(self) -> None:
        manifest = base_manifest()
        manifest["cover_title_bold"] = ["La lezione", "assente"]
        manifest["cover_title_accent"] = ["La lezione", "assente", "operativa"]
        manifest["cover_title_underline"] = ["operativa", "assente"]
        manifest["items"][0].update(
            {
                "title": "Titolo da evidenziare",
                "title_bold": ["evidenziare"],
                "title_serif": ["Titolo", "da evidenziare", "non presente"],
                "title_accent": "non e una lista",
                "title_underline": ["da"],
                "summary_bold": ["Prima frase."],
                "summary_serif": ["Prima frase.", "Prima frase.", 4],
                "summary_accent": ["assente"],
                "summary_underline": ["frase."],
            }
        )
        manifest["outro"].update(
            {"title_serif": ["Chiusura"], "summary_bold": ["Corpo"]}
        )
        slides = {entry["id"]: entry for entry in self.model(manifest)["slides"]}
        self.assertEqual(slides["cover"]["title_bold"], ["La lezione"])
        self.assertEqual(slides["cover"]["title_serif"], ["e operativa"])
        self.assertEqual(slides["cover"]["title_accent"], ["La lezione", "operativa"])
        self.assertEqual(slides["cover"]["title_underline"], ["operativa"])
        self.assertEqual(slides["cover"]["summary_serif"], [])
        self.assertEqual(slides["item-1"]["title_bold"], ["evidenziare"])
        self.assertEqual(slides["item-1"]["title_serif"], ["Titolo", "da evidenziare"])
        self.assertEqual(slides["item-1"]["title_accent"], [])
        self.assertEqual(slides["item-1"]["title_underline"], ["da"])
        self.assertEqual(slides["item-1"]["summary_bold"], ["Prima frase."])
        self.assertEqual(slides["item-1"]["summary_serif"], ["Prima frase."])
        self.assertEqual(slides["item-1"]["summary_accent"], [])
        self.assertEqual(slides["item-1"]["summary_underline"], ["frase."])
        self.assertEqual(slides["outro"]["title_serif"], ["Chiusura"])
        self.assertEqual(slides["outro"]["summary_bold"], ["Corpo"])
        self.assertEqual(slides["outro"]["summary_serif"], [])

    def test_exposes_font_metadata_without_local_paths(self) -> None:
        font_path = self.workdir / "brand.woff2"
        font_path.write_bytes(b"fake font")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "sans": {
                    "family": "Studio Sans",
                    "file": "brand.woff2",
                    "source": "uploaded",
                },
                "serif": {"family": "Studio Serif", "file": "missing.ttf"},
            }
        }
        model = self.model(manifest)
        fonts = model["brand"]["font_assets"]
        self.assertEqual(model["brand"]["sans"], "Studio Sans")
        self.assertEqual(fonts["sans"], {
            "family": "Studio Sans",
            "source": "uploaded",
            "available": True,
            "endpoint": "/api/font/sans",
        })
        self.assertFalse(fonts["serif"]["available"])
        self.assertEqual(fonts["serif"]["endpoint"], "")
        self.assertNotIn(str(font_path), json.dumps(model))

    def test_uses_bundled_assets_for_legacy_neutral_families(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {"fonts": {"sans": "Inter", "serif": "Playfair Display"}}
        fonts = self.model(manifest)["brand"]["font_assets"]
        self.assertEqual(fonts["sans"]["source"], "bundled")
        self.assertTrue(fonts["sans"]["available"])
        self.assertEqual(fonts["serif"]["source"], "bundled")
        self.assertTrue(fonts["serif"]["available"])
        self.assertEqual(
            review_server.BUNDLED_FONT_ASSETS["serif"][1].name,
            "PlayfairDisplay-Italic-Variable.ttf",
        )

    def test_rejects_a_font_path_outside_the_manifest_directory(self) -> None:
        outside = self.workdir.parent / f"{self.workdir.name}-outside-font.woff2"
        outside.write_bytes(b"private bytes")
        self.addCleanup(outside.unlink, missing_ok=True)
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "sans": {
                    "family": "Outside Sans",
                    "file": f"../{outside.name}",
                    "source": "uploaded",
                }
            }
        }
        font = self.model(manifest)["brand"]["font_assets"]["sans"]
        self.assertFalse(font["available"])
        self.assertEqual(font["endpoint"], "")

    def test_rejects_a_logo_path_outside_the_manifest_directory(self) -> None:
        outside = self.workdir.parent / f"{self.workdir.name}-outside-logo.png"
        outside.write_bytes(b"private logo")
        self.addCleanup(outside.unlink, missing_ok=True)
        manifest = base_manifest()
        manifest["brand"] = {"logos": {"on_light": f"../{outside.name}"}}
        logo = self.model(manifest)["brand"]["logos"]["on_light"]
        self.assertFalse(logo["available"])
        self.assertEqual(logo["endpoint"], "")


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

    def test_transports_all_emphasis_roles_and_preserves_legacy_serif(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "Prima frase utile."
        slides[1].update(
            {
                "summary_bold": ["Prima"],
                "summary_italic": [],
                "summary_serif": ["frase"],
                "summary_accent": [],
                "summary_underline": ["utile"],
                "title_bold": [],
                "title_italic": [],
                "title_serif": [],
                "title_accent": [],
                "title_underline": [],
            }
        )
        result = review_server.validate_feedback(self.payload(slides), self.model)
        item = result["slides"][1]
        self.assertEqual(item["summary_bold"], ["Prima"])
        self.assertEqual(item["summary_serif"], ["frase"])
        self.assertIn("summary_italic", item)
        self.assertEqual(item["summary_underline"], ["utile"])

    def test_rejects_ambiguous_or_overlapping_emphasis(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary_bold"] = ["a"]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

        slides = self.payload()["slides"]
        slides[1]["summary_bold"] = ["Prima"]
        slides[1]["summary_italic"] = ["Prima frase."]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_same_selection_with_two_treatments_has_one_actionable_error(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary_serif"] = []
        slides[1]["summary_underline"] = ["Prima"]
        slides[1]["summary_accent"] = ["Prima"]
        with self.assertRaisesRegex(
            ValueError,
            "“Prima” ha più trattamenti.*Scegline uno",
        ):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_missing_bold_neither_warns_nor_blocks_approval(self) -> None:
        feedback = review_server.validate_feedback(self.payload(), self.model)
        self.assertFalse(any("summary_bold" in warning for warning in feedback["warnings"]))
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertEqual(approved["action"], "approve")

    def test_approve_allows_multiple_non_overlapping_emphasis_styles(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "Prima seconda terza."
        slides[1]["summary_bold"] = ["Prima"]
        slides[1]["summary_underline"] = ["seconda"]
        slides[1]["summary_accent"] = ["terza."]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        slides[2]["summary_accent"] = []
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertEqual(approved["slides"][1]["summary_bold"], ["Prima"])
        self.assertEqual(approved["slides"][1]["summary_underline"], ["seconda"])
        self.assertEqual(approved["slides"][1]["summary_accent"], ["terza."])

    def test_approve_rejects_italic_when_no_real_italic_font_is_available(self) -> None:
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1].update({"summary_bold": ["Prima"], "summary_serif": ["frase."]})
        slides[2]["summary_bold"] = ["Seconda"]
        with self.assertRaisesRegex(ValueError, "font corsivo reale"):
            review_server.validate_feedback(
                self.payload(slides, action="approve"), self.model
            )

    def test_validates_and_transports_logo_mode(self) -> None:
        result = review_server.validate_feedback(self.payload(logo_mode="hidden"), self.model)
        self.assertEqual(result["logo_mode"], "hidden")
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(logo_mode="always"), self.model)

    def test_accepts_a_visual_style_choice_and_rejects_unknown_ones(self) -> None:
        result = review_server.validate_feedback(
            self.payload(visual_style_system="corporate_modular"), self.model
        )
        self.assertEqual(result["visual_style_system"], "corporate-modular")
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(visual_style_system="non-esiste"), self.model
            )

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


class FeedbackTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.manifest_path = (self.workdir / "manifest.json").resolve()
        self.session_dir = self.workdir / "session"
        self.state_path = self.session_dir / "session-state.json"
        self.feedback_path = self.session_dir / "feedback.json"
        self.journal_path = self.session_dir / "feedback-commit.json"
        self.state = {
            "manifest": str(self.manifest_path),
            "manifest_revision": 1,
            "last_feedback_id": None,
            "applied_feedback_id": None,
        }
        self.feedback = {
            "feedback_id": "feedback-transaction",
            "submitted_at": "2026-01-01T00:00:00+00:00",
            "action": "feedback",
        }
        write_json(self.manifest_path, base_manifest())
        write_json(self.state_path, self.state)

    def commit(self) -> dict:
        return review_server.commit_feedback(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
            current_state=self.state,
            feedback=self.feedback,
            manifest_revision=1,
        )

    def test_recovers_an_interrupted_feedback_commit(self) -> None:
        self.commit()
        self.feedback_path.unlink()
        write_json(self.state_path, self.state)

        event = review_server.recover_feedback_commit(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
        )

        self.assertEqual(event["feedback_id"], "feedback-transaction")
        recovered_feedback = json.loads(self.feedback_path.read_text(encoding="utf-8"))
        recovered_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered_feedback, self.feedback)
        self.assertEqual(recovered_state["last_feedback_id"], "feedback-transaction")
        self.assertEqual(recovered_state["last_action"], "feedback")

    def test_recovers_a_legacy_journal_without_last_action(self) -> None:
        self.commit()
        journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
        journal["state_patch"].pop("last_action")
        journal["state_before"].pop("last_action")
        write_json(self.journal_path, journal)
        self.feedback_path.unlink()
        write_json(self.state_path, self.state)

        event = review_server.recover_feedback_commit(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
        )

        self.assertEqual(event["action"], "feedback")
        recovered_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered_state["last_action"], "feedback")

    def test_rejects_recovery_after_an_unrelated_state_change(self) -> None:
        self.commit()
        conflicting = dict(self.state)
        conflicting["last_feedback_id"] = "feedback-unrelated"
        write_json(self.state_path, conflicting)

        with self.assertRaisesRegex(ValueError, "stato è cambiato"):
            review_server.recover_feedback_commit(
                journal_path=self.journal_path,
                feedback_path=self.feedback_path,
                state_path=self.state_path,
                manifest_path=self.manifest_path,
            )


if __name__ == "__main__":
    unittest.main()

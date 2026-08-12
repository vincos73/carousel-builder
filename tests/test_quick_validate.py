import tempfile
import unittest
from pathlib import Path

from quick_validate import validate_skill


class QuickValidateTests(unittest.TestCase):
    def write_skill(self, text: str) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "SKILL.md").write_text(text, encoding="utf-8")
        return root

    def test_accepts_the_project_skill(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(validate_skill(root), [])

    def test_rejects_invalid_frontmatter(self):
        root = self.write_skill("# no frontmatter\n")
        self.assertIn("frontmatter", validate_skill(root)[0])

    def test_rejects_invalid_name_and_long_description(self):
        root = self.write_skill(
            "---\nname: Not Valid\ndescription: " + "x" * 1025 + "\n---\n"
        )
        errors = validate_skill(root)
        self.assertTrue(any("kebab-case" in error for error in errors))
        self.assertTrue(any("1024" in error for error in errors))

    def test_rejects_a_missing_packaged_reference(self):
        root = self.write_skill(
            "---\nname: valid-skill\ndescription: Valida.\n---\n"
            "Leggi [il contratto](references/missing.md).\n"
        )
        self.assertTrue(any("link locale mancante" in error for error in validate_skill(root)))

    def test_rejects_a_link_that_escapes_the_skill(self):
        root = self.write_skill(
            "---\nname: valid-skill\ndescription: Valida.\n---\n"
            "Leggi [un file esterno](../outside.md).\n"
        )
        self.assertTrue(any("fuori dalla skill" in error for error in validate_skill(root)))

    def test_project_skill_keeps_heavy_guidance_progressive(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        visual_review = (root / "references" / "visual-review.md").read_text(
            encoding="utf-8"
        )
        self.assertLessEqual(len(skill.split()), 1_800)
        self.assertLessEqual(len(visual_review.split()), 1_400)
        self.assertIn("Caricare solo ciò che serve alla fase corrente", skill)
        self.assertIn(
            "soltanto dopo un'interruzione o conflitto",
            skill,
        )
        self.assertIn("editor-capabilities.md", visual_review)
        self.assertIn("review-recovery.md", visual_review)
        workflow = (root / "references" / "workflow-state.md").read_text(
            encoding="utf-8"
        )
        delivery = workflow.split("--expected-state qa", 1)[1].split("```", 1)[0]
        self.assertIn("--render-result", delivery)
        self.assertIn("--qa-report", delivery)

    def test_current_manifest_schema_is_bound_across_runtime_and_docs(self):
        root = Path(__file__).resolve().parents[1]
        contract = (root / "scripts" / "manifest_contract.py").read_text(
            encoding="utf-8"
        )
        exporter = (root / "scripts" / "export_review_pdf.cjs").read_text(
            encoding="utf-8"
        )
        schema = (root / "references" / "carousel-schema.md").read_text(
            encoding="utf-8"
        )
        self.assertRegex(contract, r"(?m)^CURRENT_SCHEMA_VERSION = \(1, 4\)$")
        self.assertRegex(
            exporter,
            r'(?m)^const CURRENT_SCHEMA_VERSION = "1\.4";$',
        )
        self.assertRegex(schema, r'"schema_version": "1\.4"')


if __name__ == "__main__":
    unittest.main()

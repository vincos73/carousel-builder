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


if __name__ == "__main__":
    unittest.main()

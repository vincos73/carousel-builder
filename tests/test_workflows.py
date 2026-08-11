import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
TESTS = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_is_bound_to_the_checked_out_tag_commit(self):
        self.assertIn("persist-credentials: false", RELEASE)
        self.assertIn('if [ "$GITHUB_REF_TYPE" != "tag" ]', RELEASE)
        self.assertIn('refs/tags/$tag', RELEASE)
        self.assertIn('$tag_ref^{commit}', RELEASE)
        self.assertIn('$GITHUB_SHA^{commit}', RELEASE)
        self.assertIn("checkout_commit=$(git rev-parse HEAD)", RELEASE)
        self.assertIn('"$tag_commit" != "$event_commit"', RELEASE)
        self.assertIn('"$tag_commit" != "$checkout_commit"', RELEASE)

    def test_release_never_silently_clobbers_existing_assets(self):
        self.assertNotIn("--clobber", RELEASE)
        self.assertNotIn("gh release upload", RELEASE)
        self.assertIn('gh release view "$TAG"', RELEASE)
        self.assertIn("gli asset non vengono sovrascritti", RELEASE)
        self.assertIn("--verify-tag", RELEASE)

    def test_release_runs_all_gates_before_publish(self):
        gates = [
            "python -B -m unittest discover",
            "tests/quick_validate.py .",
            "tests/quick_validate.py agent-plugin/skills/carousel-builder",
            "node --check scripts/export_review_pdf.cjs",
            "node --test tests/test_export_review_pdf.cjs",
            "Verifica il mirror Agent Plugin",
            "unzip -t dist/carousel-builder.zip",
            "unzip -t dist/carousel-builder-agent-plugin.zip",
            'diff -r "$root_stage" "$root_extract/carousel-builder"',
            'diff -r "$plugin_stage" "$plugin_extract"',
        ]
        publish = RELEASE.index('gh release create "$TAG"')
        for gate in gates:
            with self.subTest(gate=gate):
                self.assertIn(gate, RELEASE)
                self.assertLess(RELEASE.index(gate), publish)

    def test_packaging_uses_explicit_top_level_allowlists(self):
        self.assertIn(
            "for package_path in SKILL.md README.md LICENSE agents assets references scripts",
            RELEASE,
        )
        self.assertIn(
            "for package_path in plugin.json README.md LICENSE skills",
            RELEASE,
        )
        self.assertNotIn("tar --exclude", RELEASE)
        self.assertIn("zip -X -qr", RELEASE)


class TestsWorkflowTests(unittest.TestCase):
    def test_ci_cancels_superseded_branch_runs(self):
        self.assertIn("concurrency:", TESTS)
        self.assertIn("github.event.pull_request.number || github.ref", TESTS)
        self.assertIn("cancel-in-progress: true", TESTS)

    def test_ci_checks_and_tests_the_exporter_without_installing_packages(self):
        self.assertIn("node-export:", TESTS)
        self.assertIn("actions/setup-node@v4", TESTS)
        self.assertIn("node --check scripts/export_review_pdf.cjs", TESTS)
        self.assertIn("node --check assets/review-editor/app.js", TESTS)
        self.assertIn("node --test tests/test_export_review_pdf.cjs", TESTS)
        self.assertNotIn("npm install", TESTS)
        self.assertNotIn("npm ci", TESTS)

    def test_ci_validates_both_skill_copies(self):
        self.assertIn("tests/quick_validate.py .", TESTS)
        self.assertIn("tests/quick_validate.py agent-plugin/skills/carousel-builder", TESTS)
        self.assertIn("for shared_path in SKILL.md references scripts assets agents", TESTS)


if __name__ == "__main__":
    unittest.main()

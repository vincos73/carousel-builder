import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
TESTS = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


class WorkflowSyntaxGuardTests(unittest.TestCase):
    def test_runner_context_is_not_used_before_steps_exist(self):
        for name, workflow in (("tests", TESTS), ("release", RELEASE)):
            with self.subTest(workflow=name):
                self.assertNotIn("${{ runner.temp }}", workflow)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_repository_public_and_runtime_versions_are_identical(self):
        skill_pattern = re.compile(r"^Versione: \*\*([^*]+)\*\*$", re.MULTILINE)
        editor_pattern = re.compile(r'^EDITOR_VERSION = ["\']([^"\']+)["\']$', re.MULTILINE)

        root_skill = skill_pattern.search((ROOT / "SKILL.md").read_text(encoding="utf-8"))
        plugin_skill = skill_pattern.search(
            (ROOT / "agent-plugin/skills/carousel-builder/SKILL.md").read_text(
                encoding="utf-8"
            )
        )
        root_editor = editor_pattern.search(
            (ROOT / "scripts/review_server.py").read_text(encoding="utf-8")
        )
        plugin_editor = editor_pattern.search(
            (
                ROOT
                / "agent-plugin/skills/carousel-builder/scripts/review_server.py"
            ).read_text(encoding="utf-8")
        )
        self.assertIsNotNone(root_skill)
        self.assertIsNotNone(plugin_skill)
        self.assertIsNotNone(root_editor)
        self.assertIsNotNone(plugin_editor)
        versions = {
            root_skill.group(1),
            plugin_skill.group(1),
            root_editor.group(1),
            plugin_editor.group(1),
            json.loads(
                (ROOT / "agent-plugin/plugin.json").read_text(encoding="utf-8")
            )["version"],
        }
        self.assertEqual(len(versions), 1, versions)

    def test_release_is_bound_to_the_checked_out_tag_commit(self):
        self.assertIn("persist-credentials: false", RELEASE)
        self.assertIn('if [ "$GITHUB_REF_TYPE" != "tag" ]', RELEASE)
        self.assertIn('refs/tags/$tag', RELEASE)
        self.assertIn('$tag_ref^{commit}', RELEASE)
        self.assertIn('$GITHUB_SHA^{commit}', RELEASE)
        self.assertIn("checkout_commit=$(git rev-parse HEAD)", RELEASE)
        self.assertIn('"$tag_commit" != "$event_commit"', RELEASE)
        self.assertIn('"$tag_commit" != "$checkout_commit"', RELEASE)

    def test_release_requires_public_and_runtime_versions_to_match(self):
        self.assertIn("agent-plugin/skills/carousel-builder/SKILL.md", RELEASE)
        self.assertIn("scripts/review_server.py", RELEASE)
        self.assertIn(
            "agent-plugin/skills/carousel-builder/scripts/review_server.py",
            RELEASE,
        )
        self.assertIn('test "$skill_version" = "$plugin_skill_version"', RELEASE)
        self.assertIn('test "$skill_version" = "$plugin_version"', RELEASE)
        self.assertIn('test "$skill_version" = "$editor_version"', RELEASE)
        self.assertIn('test "$skill_version" = "$plugin_editor_version"', RELEASE)
        self.assertIn('test "${tag#v}" = "$skill_version"', RELEASE)

    def test_release_never_silently_clobbers_existing_assets(self):
        self.assertNotIn("--clobber", RELEASE)
        self.assertNotIn("gh release upload", RELEASE)
        self.assertIn('gh release create "$TAG"', RELEASE)
        self.assertIn('gh release edit "$TAG" --draft=false --latest', RELEASE)
        self.assertIn("gli asset non vengono sovrascritti", RELEASE)
        self.assertIn('select(.tag_name == \\"$TAG\\") | .id', RELEASE)
        self.assertIn('matching_release_ids', RELEASE)
        self.assertIn('"/repos/$GITHUB_REPOSITORY/releases/$release_id"', RELEASE)
        self.assertIn('if [ "$(jq -r \'.draft\'', RELEASE)
        self.assertNotIn('gh release view "$TAG" >/dev/null', RELEASE)
        self.assertNotIn("--clobber", RELEASE)
        self.assertIn("--verify-tag", RELEASE)

    def test_release_is_verified_as_a_draft_before_publication(self):
        create = RELEASE.index('gh release create "$TAG"')
        publish = RELEASE.index('gh release edit "$TAG" --draft=false --latest')
        self.assertLess(create, publish)
        between = RELEASE[create:publish]
        self.assertIn("--draft", between)
        self.assertIn('"/repos/$GITHUB_REPOSITORY/releases"', between)
        self.assertIn("select(.tag_name", between)
        self.assertIn('if [ "$(jq -r \'.draft\'', between)
        self.assertIn('"/repos/$GITHUB_REPOSITORY/releases/assets/$asset_id"', between)
        self.assertIn('Accept: application/octet-stream', between)
        self.assertIn("sha256sum --check SHA256SUMS", between)
        self.assertIn('unzip -t "$download_dir/carousel-builder.zip"', between)
        self.assertIn('test "$(jq -r \'.prerelease\'', between)
        self.assertIn("Riprendo la release draft", RELEASE)

    def test_existing_draft_is_resumed_only_when_its_contract_is_exact(self):
        resume = RELEASE.index('if [ "${#matching_release_ids[@]}" -eq 1 ]')
        publish = RELEASE.index('gh release edit "$TAG" --draft=false --latest')
        guarded = RELEASE[resume:publish]
        self.assertIn('release_id="${matching_release_ids[0]}"', guarded)
        self.assertIn('test "$(jq -r \'.tag_name\'', guarded)
        self.assertIn('test "$(jq -r \'.target_commitish\'', guarded)
        self.assertIn("expected_assets=", RELEASE)
        self.assertIn('= "$expected_assets"', guarded)
        self.assertIn("[.assets[].name] | sort | join", guarded)
        self.assertIn("all(.assets[]; .state == \"uploaded\" and .size > 0)", guarded)
        self.assertIn('resume_draft=true', guarded)
        self.assertNotIn("gh release upload", guarded)
        self.assertNotIn("--clobber", guarded)

    def test_release_publishes_checksums_with_both_packages(self):
        self.assertIn("Genera checksum pubblici", RELEASE)
        self.assertIn("> SHA256SUMS", RELEASE)
        self.assertIn("dist/SHA256SUMS", RELEASE)
        self.assertIn(
            '"SHA256SUMS,carousel-builder-agent-plugin.zip,carousel-builder.zip"',
            RELEASE,
        )
        downloaded_compare = 'cmp dist/SHA256SUMS "$download_dir/SHA256SUMS"'
        self.assertIn(downloaded_compare, RELEASE)
        self.assertLess(
            RELEASE.index(downloaded_compare),
            RELEASE.index('(cd "$download_dir" && sha256sum --check SHA256SUMS)'),
        )
        self.assertIn("source_date_epoch=$(git show -s --format=%ct HEAD)", RELEASE)
        self.assertIn('touch -h -d "@$source_date_epoch"', RELEASE)

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
        publish = RELEASE.index('gh release edit "$TAG" --draft=false --latest')
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

    def test_ci_covers_linux_windows_and_macos(self):
        self.assertIn("runs-on: ubuntu-latest", TESTS)
        self.assertIn("windows-unittest:", TESTS)
        self.assertIn("runs-on: windows-latest", TESTS)
        self.assertIn("macos-unittest:", TESTS)
        self.assertIn("runs-on: macos-latest", TESTS)

    def test_ci_validates_both_skill_copies(self):
        self.assertIn("tests/quick_validate.py .", TESTS)
        self.assertIn("tests/quick_validate.py agent-plugin/skills/carousel-builder", TESTS)
        self.assertIn("for shared_path in SKILL.md references scripts assets agents", TESTS)

    def test_ci_checks_skill_plugin_and_editor_version_parity(self):
        self.assertIn("plugin_skill_version", TESTS)
        self.assertIn("plugin_version", TESTS)
        self.assertIn("editor_version", TESTS)
        self.assertIn("plugin_editor_version", TESTS)
        self.assertIn('test "$skill_version" = "$plugin_skill_version"', TESTS)
        self.assertIn('test "$skill_version" = "$plugin_version"', TESTS)
        self.assertIn('test "$skill_version" = "$editor_version"', TESTS)
        self.assertIn('test "$skill_version" = "$plugin_editor_version"', TESTS)


if __name__ == "__main__":
    unittest.main()

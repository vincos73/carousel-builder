import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
TESTS = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


def workflow_jobs(source: str) -> dict[str, str]:
    """Return top-level job blocks without treating matches in run scripts as jobs."""
    lines = source.splitlines()
    try:
        jobs_line = lines.index("jobs:")
    except ValueError as error:
        raise AssertionError("workflow privo della mappa jobs") from error
    starts: list[tuple[str, int]] = []
    for index in range(jobs_line + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith((" ", "#")):
            break
        match = re.fullmatch(r"  ([a-zA-Z0-9_-]+):", line)
        if match:
            starts.append((match.group(1), index))
    if not starts:
        raise AssertionError("workflow privo di job strutturali")
    jobs: dict[str, str] = {}
    for position, (name, start) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else len(lines)
        jobs[name] = "\n".join(lines[start:end])
    return jobs


def workflow_steps(job: str) -> dict[str, str]:
    """Return named step blocks from one already-scoped job block."""
    lines = job.splitlines()
    starts = [
        (match.group(1).strip(), index)
        for index, line in enumerate(lines)
        if (match := re.fullmatch(r"      - name: (.+)", line))
    ]
    steps: dict[str, str] = {}
    for position, (name, start) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else len(lines)
        steps[name] = "\n".join(lines[start:end])
    return steps


class WorkflowSyntaxGuardTests(unittest.TestCase):
    def test_runner_context_is_not_used_before_steps_exist(self):
        for name, workflow in (("tests", TESTS), ("release", RELEASE)):
            with self.subTest(workflow=name):
                self.assertNotIn("${{ runner.temp }}", workflow)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_uses_the_same_pinned_browser_smoke_runtime_as_ci(self):
        publish_job = workflow_jobs(RELEASE)["publish"]
        self.assertIn("runs-on: ubuntu-24.04", publish_job)
        self.assertIn('node-version: "22.23.1"', publish_job)
        self.assertIn("test -x /usr/bin/google-chrome", publish_job)
        self.assertIn("node --test tests/test_browser_smoke.cjs", publish_job)

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
            json.loads((ROOT / "package.json").read_text(encoding="utf-8"))[
                "version"
            ],
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
        self.assertIn('test "$skill_version" = "$ci_package_version"', RELEASE)
        self.assertIn('test "$skill_version" = "$editor_version"', RELEASE)
        self.assertIn('test "$skill_version" = "$plugin_editor_version"', RELEASE)
        self.assertIn('test "${tag#v}" = "$skill_version"', RELEASE)

    def test_release_never_silently_clobbers_existing_assets(self):
        self.assertNotIn("--clobber", RELEASE)
        self.assertIn('gh release create "$TAG"', RELEASE)
        self.assertIn('gh release upload "$TAG" "dist/$asset_name"', RELEASE)
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
        self.assertIn("load_matching_release_ids", between)
        self.assertIn('"/repos/$GITHUB_REPOSITORY/releases"', RELEASE)
        self.assertIn("select(.tag_name", RELEASE)
        self.assertIn('if [ "$(jq -r \'.draft\'', between)
        self.assertIn('"/repos/$GITHUB_REPOSITORY/releases/assets/$asset_id"', between)
        self.assertIn('Accept: application/octet-stream', between)
        self.assertIn("sha256sum --check SHA256SUMS", between)
        self.assertIn('unzip -t "$download_dir/$root_archive"', between)
        self.assertIn('test "$(jq -r \'.prerelease\'', between)
        self.assertIn("Riprendo la release draft", RELEASE)

    def test_new_draft_resolution_retries_eventual_consistency(self):
        create = RELEASE.index('gh release create "$TAG"')
        verify = RELEASE.index(
            'if [ "${#matching_release_ids[@]}" -ne 1 ]', create
        )
        guarded = RELEASE[create:verify]
        self.assertIn("for attempt in {1..10}", guarded)
        self.assertIn("load_matching_release_ids", guarded)
        self.assertIn('if [ "$attempt" -lt 10 ]', guarded)
        self.assertIn("sleep 2", guarded)
        self.assertNotIn('gh release create "$TAG"', guarded.split("\n", 1)[1])

    def test_existing_partial_draft_is_resumed_only_after_byte_verification(self):
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
        self.assertIn("declare -A verified_assets=()", guarded)
        self.assertIn("La draft contiene un asset inatteso", guarded)
        self.assertIn("La draft contiene due asset", guarded)
        self.assertIn('cmp "dist/$asset_name" "$download_dir/$asset_name"', guarded)
        self.assertIn(
            'if [ -z "${verified_assets[$asset_name]+present}" ]',
            guarded,
        )
        self.assertIn('gh release upload "$TAG" "dist/$asset_name"', guarded)
        self.assertLess(
            guarded.index('cmp "dist/$asset_name" "$download_dir/$asset_name"'),
            guarded.index('gh release upload "$TAG" "dist/$asset_name"'),
        )
        self.assertNotIn("--clobber", guarded)

    def test_release_publishes_checksums_with_both_packages(self):
        self.assertIn("Genera checksum pubblici", RELEASE)
        self.assertIn("> SHA256SUMS", RELEASE)
        self.assertIn("dist/SHA256SUMS", RELEASE)
        self.assertIn('root_archive="carousel-builder-${TAG}.zip"', RELEASE)
        self.assertIn('plugin_archive="carousel-builder-agent-plugin-${TAG}.zip"', RELEASE)
        self.assertIn('expected_assets="SHA256SUMS,$plugin_archive,$root_archive"', RELEASE)
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
            "node --test tests/test_browser_smoke.cjs",
            "npm ci --ignore-scripts",
            "npm audit --audit-level=high",
            "node --test tests/test_export_review_pdf_e2e.cjs",
            "Verifica il mirror Agent Plugin",
            'unzip -t "dist/$root_archive"',
            'unzip -t "dist/$plugin_archive"',
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
    def setUp(self):
        self.jobs = workflow_jobs(TESTS)

    def test_ci_cancels_superseded_branch_runs(self):
        self.assertIn("concurrency:", TESTS)
        self.assertIn("github.event.pull_request.number || github.ref", TESTS)
        self.assertIn("cancel-in-progress: true", TESTS)

    def test_ci_checks_and_tests_the_exporter_without_installing_packages(self):
        node_export = self.jobs["node-export"]
        self.assertIn("actions/setup-node@v6", node_export)
        self.assertIn("node --check scripts/export_review_pdf.cjs", node_export)
        self.assertIn("node --check assets/review-editor/app.js", node_export)
        self.assertIn("node --test tests/test_export_review_pdf.cjs", node_export)
        self.assertNotIn("npm install", node_export)
        self.assertNotIn("npm ci", node_export)

    def test_ci_covers_linux_windows_and_macos(self):
        self.assertIn("runs-on: ubuntu-latest", self.jobs["unittest"])
        self.assertIn("runs-on: windows-latest", self.jobs["windows-unittest"])
        self.assertIn("runs-on: macos-latest", self.jobs["macos-unittest"])

    def test_macos_runs_all_unit_modules_and_one_real_http_smoke(self):
        macos_job = self.jobs["macos-unittest"]
        for module in (
            "test_advance_workflow",
            "test_apply_review",
            "test_quick_validate",
            "test_review_core",
            "test_review_editor_assets",
            "test_review_server",
            "test_workflows",
        ):
            self.assertIn(module, macos_job)
        self.assertIn(
            "test_review_server_http.ReviewServerHTTPTest."
            "test_accepts_a_batch_and_writes_the_session_files",
            macos_job,
        )
        self.assertNotIn("unittest discover", macos_job)

    def test_real_browser_smoke_is_mandatory_and_dependency_free(self):
        browser_job = self.jobs["browser-smoke"]
        steps = workflow_steps(browser_job)
        self.assertIn("runs-on: ubuntu-24.04", browser_job)
        self.assertIn("timeout-minutes: 5", browser_job)
        self.assertIn("CHROME_PATH: /usr/bin/google-chrome", browser_job)
        self.assertIn('node-version: "22.23.1"', browser_job)
        self.assertIn("Verify hosted browser-smoke runtimes", steps)
        self.assertIn("Check browser smoke syntax", steps)
        self.assertIn("Run mandatory real-browser contract smoke", steps)
        self.assertIn('test -x "$CHROME_PATH"', steps["Verify hosted browser-smoke runtimes"])
        self.assertIn('"$CHROME_PATH" --version', steps["Verify hosted browser-smoke runtimes"])
        self.assertIn(
            "node --check tests/test_browser_smoke.cjs",
            steps["Check browser smoke syntax"],
        )
        self.assertIn(
            "node --test tests/test_browser_smoke.cjs",
            steps["Run mandatory real-browser contract smoke"],
        )
        self.assertNotIn("continue-on-error", browser_job)
        for forbidden in ("npm install", "npm ci", "npx ", "playwright install", "curl ", "wget "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, browser_job)

    def test_real_export_e2e_uses_pinned_dependencies_and_hosted_chrome(self):
        export_job = self.jobs["export-e2e"]
        steps = workflow_steps(export_job)
        self.assertIn("runs-on: ubuntu-24.04", export_job)
        self.assertIn("timeout-minutes: 5", export_job)
        self.assertIn("CHROME_PATH: /usr/bin/google-chrome", export_job)
        self.assertIn('node-version: "22.23.1"', export_job)
        self.assertIn("cache: npm", export_job)
        self.assertIn("Install pinned exporter dependencies", steps)
        self.assertIn(
            "npm ci --ignore-scripts",
            steps["Install pinned exporter dependencies"],
        )
        self.assertIn("Verify hosted export runtimes", steps)
        self.assertIn(
            "npm audit --audit-level=high",
            steps["Verify hosted export runtimes"],
        )
        self.assertIn("Run mandatory real export E2E", steps)
        self.assertIn(
            "node --test tests/test_export_review_pdf_e2e.cjs",
            steps["Run mandatory real export E2E"],
        )
        self.assertNotIn("continue-on-error", export_job)

    def test_every_ci_job_has_a_timeout_and_checkout(self):
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertRegex(job, r"(?m)^    timeout-minutes: [1-9][0-9]*$")
                self.assertIn("uses: actions/checkout@v5", job)

    def test_ci_validates_both_skill_copies(self):
        package_sync = self.jobs["package-sync"]
        self.assertIn("tests/quick_validate.py .", package_sync)
        self.assertIn("tests/quick_validate.py agent-plugin/skills/carousel-builder", package_sync)
        self.assertIn("for shared_path in SKILL.md references scripts assets agents", package_sync)

    def test_ci_checks_skill_plugin_and_editor_version_parity(self):
        package_sync = self.jobs["package-sync"]
        self.assertIn("plugin_skill_version", package_sync)
        self.assertIn("plugin_version", package_sync)
        self.assertIn("ci_package_version", package_sync)
        self.assertIn("editor_version", package_sync)
        self.assertIn("plugin_editor_version", package_sync)
        self.assertIn('test "$skill_version" = "$plugin_skill_version"', package_sync)
        self.assertIn('test "$skill_version" = "$plugin_version"', package_sync)
        self.assertIn('test "$skill_version" = "$ci_package_version"', package_sync)
        self.assertIn('test "$skill_version" = "$editor_version"', package_sync)
        self.assertIn('test "$skill_version" = "$plugin_editor_version"', package_sync)


if __name__ == "__main__":
    unittest.main()

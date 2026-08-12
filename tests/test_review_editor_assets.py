"""Regression guards for the mirrored local review editor assets."""

from __future__ import annotations

import shutil
import subprocess
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
        self.html = (EDITOR_DIR / "index.html").read_text(encoding="utf-8")
        self.stylesheet = (EDITOR_DIR / "styles.css").read_text(encoding="utf-8")

    def test_feedback_batch_is_client_identified_and_persisted_before_post(self) -> None:
        submit_start = self.source.index("async function sendPendingSubmission()")
        persist_at = self.source.index("persistDraft({ immediate: true });", submit_start)
        post_at = self.source.index('fetchJson("/api/submit"', submit_start)
        self.assertLess(persist_at, post_at)
        self.assertIn("feedback_id: feedbackId", self.source)
        self.assertIn("pending_submission: pendingSubmission", self.source)
        self.assertIn("if (data.feedback_id !== pendingSubmission.feedback_id)", self.source)
        backup_at = self.source.index('preservePendingSubmission("pre-post-backup"', submit_start)
        self.assertLess(backup_at, post_at)
        self.assertIn("markRecoveryApplied(appliedFeedbackId)", self.source)

    def test_stale_pending_is_recovered_and_never_retried_against_a_new_base(self) -> None:
        hydrate = self.source.split("function hydrateDraft()", 1)[1].split("function fontStack", 1)[0]
        retry = self.source.split("async function sendPendingSubmission()", 1)[1].split("async function submit", 1)[0]
        self.assertIn('recoveryFromPending(savedPending, reason, saved)', hydrate)
        self.assertIn('const sameFingerprint', hydrate)
        self.assertIn('base-revision-mismatch-before-retry', retry)
        self.assertIn('base-workflow-mismatch-before-retry', retry)
        self.assertIn('render-fingerprint-mismatch-before-retry', retry)
        self.assertLess(retry.index("if (!baseMatches || !fingerprintMatches || !workflowMatches)"), retry.index('fetchJson("/api/submit"'))
        self.assertIn("recovery_submissions: recoverySubmissions", self.source)
        self.assertIn('id="export-recovery-button"', self.html)

    def test_stale_plain_draft_and_recoveries_have_dedicated_storage(self) -> None:
        hydrate = self.source.split("function hydrateDraft()", 1)[1].split("function fontStack", 1)[0]
        self.assertIn('recoveryDraftFromSaved(saved, reason)', hydrate)
        self.assertIn('editable_draft !== false', hydrate)
        self.assertIn('recoveryStorageKey(kind, identifier)', self.source)
        self.assertIn('if (safeStorageGet(key) !== null) return true', self.source)
        self.assertIn('loadDedicatedRecoveries()', hydrate)
        self.assertIn('drafts: clone(recoveryDrafts)', self.source)

    @unittest.skipUnless(shutil.which("node"), "Node.js non disponibile")
    def test_tab_scoped_primary_storage_preserves_two_tabs_and_pending_reload(self) -> None:
        script = r'''
const assert = require("node:assert/strict");
const { tabDraftStorageKey } = require(process.argv[1]);
const shared = "carousel-builder:session-token";
const keyA = tabDraftStorageKey(shared, "tab-a");
const keyB = tabDraftStorageKey(shared, "tab-b");
assert.notEqual(keyA, keyB);
const storage = new Map();
storage.set(keyA, JSON.stringify({ slides: [{ id: "a" }], pending_submission: { feedback_id: "pending-a" } }));
storage.set(keyB, JSON.stringify({ slides: [{ id: "b" }], pending_submission: null }));
const reloadA = JSON.parse(storage.get(keyA));
assert.equal(reloadA.slides[0].id, "a");
assert.equal(reloadA.pending_submission.feedback_id, "pending-a");
assert.equal(JSON.parse(storage.get(keyB)).slides[0].id, "b");
'''
        result = subprocess.run(
            ["node", "-e", script, str(EDITOR)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("const tabId = productionRender ? \"production\" : getOrCreateTabId(tabSessionKey)", self.source)
        self.assertIn("const storageKey = tabDraftStorageKey(sharedStorageKey, tabId)", self.source)
        self.assertIn('return `${sharedStorageKey}:recovery:${kind}:${identifier}`', self.source)
        self.assertIn("navigator.locks?.request", self.source)
        self.assertIn(".then(() => loadSession())", self.source)
        self.assertIn("productionRender ? Promise.resolve() : migrateLegacyStorage()", self.source)

    @unittest.skipUnless(shutil.which("node"), "Node.js non disponibile")
    def test_static_font_roles_expose_non_overlapping_weight_ranges(self) -> None:
        script = r'''
const assert = require("node:assert/strict");
const { fontAssetDescriptors, fontAssetRequiresVerifiedLoad } = require(process.argv[1]);
assert.deepEqual(fontAssetDescriptors("body"), { style: "normal", weight: "100 699" });
assert.deepEqual(fontAssetDescriptors("display"), { style: "normal", weight: "700 900" });
assert.deepEqual(fontAssetDescriptors("italic", "italic"), { style: "italic", weight: "100 900" });
assert.equal(fontAssetRequiresVerifiedLoad(), false);
assert.equal(fontAssetRequiresVerifiedLoad({ available: false, family: "Fallback" }), false);
assert.equal(fontAssetRequiresVerifiedLoad({ available: true }), true);
'''
        result = subprocess.run(
            ["node", "-e", script, str(EDITOR)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("new FontFace(", self.source)
        self.assertIn("fontAssetDescriptors(kind, style)", self.source)
        self.assertIn("fontLoadCache.get(key) === pending", self.source)

    def test_foreign_pending_locks_without_claiming_or_discarding_local_draft(self) -> None:
        poll = self.source.split("async function pollStatus()", 1)[1].split("function clearPendingSelection", 1)[0]
        self.assertIn("const ownPending", poll)
        self.assertIn('preserveCurrentDraft("foreign-feedback-pending"', poll)
        self.assertIn("foreignFeedbackId = serverFeedbackId", poll)
        foreign_branch = poll.split("if (ownPending)", 1)[1].split("persistDraft({ immediate: true });", 1)[0]
        self.assertNotIn("awaitingFeedbackId = serverFeedbackId", foreign_branch.split("} else {", 1)[1])
        self.assertIn('preserveCurrentDraft("foreign-feedback-applied"', poll)
        self.assertIn("La bozza locale non è stata ricaricata", poll)

    def test_approve_payload_echoes_server_fingerprint_without_client_stage(self) -> None:
        submit = self.source.split("async function submit(action)", 1)[1].split("function schedulePoll", 1)[0]
        self.assertIn('payload.render_fingerprint = model.render_fingerprint', submit)
        self.assertIn('payload.base_workflow_state = model.workflow_state', submit)
        self.assertIn('pendingSubmission.action !== "approve"', self.source)
        self.assertNotIn("function approvalStage()", self.source)
        self.assertNotIn("approval_stage", self.source)
        self.assertIn('response.status === 422 && rejectedAction === "approve"', self.source)
        self.assertIn("await loadSession()", self.source)

    def test_visual_approval_binds_viewed_proof_sample_and_browser(self) -> None:
        submit = self.source.split("async function submit(action)", 1)[1].split("function schedulePoll", 1)[0]
        gate = self.source.split("function collectApprovalIssues(", 1)[1].split("function validationTarget", 1)[0]
        snapshot = self.source.split("function canonicalContentSnapshot()", 1)[1].split("function getRenderContract", 1)[0]
        self.assertIn("requiredProofSlideIds()", gate)
        self.assertIn("viewedSlideIds.has(slideId)", gate)
        self.assertIn("model?.proof_approved !== true", gate)
        self.assertIn("!productionRender", gate)
        self.assertIn('model?.proof?.preview_width !== 480', gate)
        self.assertIn("Math.abs(bounds.width - expectedWidth) > 0.5", gate)
        self.assertIn("Math.abs(bounds.height - expectedHeight) > 0.5", gate)
        self.assertIn("payload.proof_slide_ids = requiredProofSlideIds()", submit)
        self.assertIn("payload.style_system_verified = true", submit)
        self.assertIn("payload.proof_browser = browserProofDescriptor()", submit)
        self.assertIn("proof: clone(model?.proof || {})", snapshot)
        self.assertIn("production: clone(model?.production || {})", snapshot)
        self.assertIn("proof-draft-changed", gate)
        self.assertIn("normalizedSlides(draftSlides)", gate)
        self.assertIn('engine, major', self.source)
        self.assertNotIn('["firefox",', self.source)
        self.assertNotIn('["webkit",', self.source)

    def test_slide_is_seen_only_after_half_of_the_preview_is_observed(self) -> None:
        jump = self.source.split("function jumpToSlide(slideId)", 1)[1].split(
            "function renderSequenceNav", 1
        )[0]
        observer = self.source.split("function setupObserver()", 1)[1].split(
            "function measurePreviews", 1
        )[0]
        self.assertNotIn("markSlideSeen", jump)
        self.assertIn('row.scrollIntoView({ behavior: "smooth", block: "start" })', jump)
        self.assertIn("entry.intersectionRatio < 0.5", observer)
        self.assertIn('entry.target.closest(".slide-row")?.dataset.slideId', observer)
        self.assertIn('.querySelectorAll(".slide-row > .slide-preview")', observer)
        self.assertIn("observer.observe(preview)", observer)
        self.assertIn("{ threshold: [0.5] }", observer)

    @unittest.skipUnless(shutil.which("node"), "Node.js non disponibile")
    def test_approval_is_fail_closed_until_the_current_preview_is_ready(self) -> None:
        script = r'''
const assert = require("node:assert/strict");
const { previewReadyForApproval } = require(process.argv[1]);
assert.equal(previewReadyForApproval({}), false);
assert.equal(previewReadyForApproval({ previewReady: "true" }), true);
assert.equal(previewReadyForApproval({ previewReady: "true", productionError: "errore" }), false);
assert.equal(previewReadyForApproval({ previewReady: "false" }), false);
'''
        result = subprocess.run(
            ["node", "-e", script, str(EDITOR)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        gate = self.source.split("function collectApprovalIssues(", 1)[1].split(
            "function validationTarget", 1
        )[0]
        publisher = self.source.split("async function publishPreviewContract", 1)[1].split(
            "function renderComments", 1
        )[0]
        typography = self.source.split("async function configurePreviewTypography(run)", 1)[1].split(
            "function typography", 1
        )[0]
        renderer = self.source.split("function renderSlides(", 1)[1].split(
            "function roundedMetric", 1
        )[0]
        self.assertIn('key: "preview-not-ready"', gate)
        self.assertIn("previewReadyForApproval(document.documentElement.dataset)", gate)
        self.assertIn("includeProofInteraction: false", publisher)
        self.assertIn("requirePreviewReady: false", publisher)
        self.assertIn("if (!(await configurePreviewTypography(run))) return;", publisher)
        self.assertIn("if (!fontAssetRequiresVerifiedLoad(asset))", typography)
        self.assertIn('failure.code = "FONT_ASSET_LOAD_FAILED"', typography)
        self.assertNotIn("fallback dichiarato (caricamento non riuscito)", typography)
        self.assertLess(
            typography.index("if (run !== previewContractRun) return false;"),
            typography.index('document.documentElement.style.setProperty("--preview-display"'),
        )
        self.assertLess(
            typography.index("if (run !== previewContractRun) return false;"),
            typography.index("renderSlides({ publishContract: false })"),
        )
        self.assertIn("invalidatePreviewContract({ cancelPending: publishContract })", renderer)
        self.assertIn("if (publishContract) publishPreviewContract()", renderer)
        self.assertIn(
            "!previewReadyForApproval(document.documentElement.dataset)",
            self.source.split("function updateChangeSummary()", 1)[1].split("function lockEditing", 1)[0],
        )

    def test_viewed_proof_state_is_bound_to_checkpoint_fingerprint_and_style(self) -> None:
        key = self.source.split("function viewedStorageKey()", 1)[1].split("function visualSystemStorageKey", 1)[0]
        self.assertIn("model?.approval_checkpoint", key)
        self.assertIn("model?.render_fingerprint", key)
        self.assertIn("selectedVisualSystem", key)
        setter = self.source.split("function setVisualSystem", 1)[1].split("function loadViewState", 1)[0]
        self.assertIn("loadViewState()", setter)

    def test_status_checkpoint_change_reloads_clean_and_preserves_dirty_or_pending(self) -> None:
        poll = self.source.split("async function pollStatus()", 1)[1].split("function clearPendingSelection", 1)[0]
        self.assertIn("statusBaseChange(status)", poll)
        self.assertIn("status.workflow_state", poll)
        self.assertIn("status.approval_checkpoint", poll)
        self.assertIn("if (!hasLocalRisk)", poll)
        self.assertIn("await loadSession()", poll)
        self.assertIn('preservePendingSubmission("workflow-checkpoint-changed"', poll)
        self.assertIn('preserveCurrentDraft("workflow-checkpoint-changed"', poll)
        self.assertIn("if (baseChange.workflowChanged || baseChange.checkpointChanged)", poll)
        self.assertIn("base_workflow_state: model.workflow_state", self.source)
        self.assertIn("base_approval_checkpoint: model.approval_checkpoint", self.source)

    def test_status_poll_is_serial_timed_backed_off_and_visibility_aware(self) -> None:
        self.assertIn("pollInFlight", self.source)
        self.assertIn("POLL_MAX_DELAY", self.source)
        self.assertIn("REQUEST_TIMEOUT", self.source)
        self.assertIn('document.addEventListener("visibilitychange"', self.source)
        self.assertIn("pollAbortController?.abort()", self.source)
        self.assertIn("status.feedback_pending === true", self.source)
        self.assertIn("awaitingFeedbackId = serverFeedbackId", self.source)
        self.assertNotIn("setInterval(pollStatus", self.source)

    def test_approval_uses_one_blocking_gate_with_inline_focusable_errors(self) -> None:
        self.assertIn("function runApprovalGate", self.source)
        self.assertGreaterEqual(self.source.count("runApprovalGate()"), 2)
        self.assertIn("collectPaletteContrastIssues", self.source)
        self.assertIn("warning.schema", self.source)
        self.assertIn("warning.overflow", self.source)
        self.assertIn("warning.emphasis", self.source)
        self.assertIn('target.setAttribute("aria-invalid", "true")', self.source)
        self.assertIn('id="validation-summary"', self.html)
        self.assertIn('id="validation-list"', self.html)

    def test_palette_gate_uses_backend_provenance_before_contrast(self) -> None:
        gate = self.source.split("function collectPaletteContrastIssues()", 1)[1].split("function collectApprovalIssues(", 1)[0]
        self.assertIn("collectPaletteDeclarationIssues(brand)", gate)
        self.assertIn("const palette = brand.palette || {}", gate)

    @unittest.skipUnless(shutil.which("node"), "Node.js non disponibile")
    def test_palette_provenance_gate_and_preview_merge_execute_fail_closed(self) -> None:
        script = r'''
const assert = require("node:assert/strict");
const { collectPaletteDeclarationIssues, mergePreviewBrand } = require(process.argv[1]);
const palette = {
  background_light: "#F5F1E8",
  background_dark: "#172033",
  text_on_light: "#172033",
  text_on_dark: "#FFFFFF",
  accent: "#FEBD08",
};
const fields = Object.keys(palette);
assert.equal(collectPaletteDeclarationIssues({ palette }).length, 5);
assert.equal(collectPaletteDeclarationIssues({
  palette,
  palette_declared: Object.fromEntries(fields.map((field) => [field, true])),
}).length, 0);
assert.equal(collectPaletteDeclarationIssues({
  palette: { ...palette, accent: "gold" },
  palette_declared: Object.fromEntries(fields.map((field) => [field, true])),
}).length, 1);

const profile = {
  palette,
  palette_declared: Object.fromEntries(fields.map((field) => [field, true])),
};
const unprovenOverride = mergePreviewBrand(profile, { palette: { accent: "#C65A3A" } });
assert.equal(unprovenOverride.palette.accent, "#C65A3A");
assert.equal(unprovenOverride.palette_declared.accent, false);
assert.equal(collectPaletteDeclarationIssues(unprovenOverride).length, 1);
const provenOverride = mergePreviewBrand(profile, {
  palette: { accent: "#C65A3A" },
  palette_declared: { accent: true },
});
assert.equal(provenOverride.palette_declared.accent, true);
assert.equal(collectPaletteDeclarationIssues(provenOverride).length, 0);
'''
        result = subprocess.run(
            ["node", "-e", script, str(EDITOR)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_radiogroups_use_roving_tabindex_and_apg_navigation(self) -> None:
        self.assertIn("button.tabIndex = selected ? 0 : -1", self.source)
        self.assertIn('event.key === "Home"', self.source)
        self.assertIn('event.key === "End"', self.source)
        self.assertIn('"ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"', self.source)
        self.assertIn('data-logo-mode="hidden" role="radio" aria-checked="false" tabindex="-1"', self.html)
        self.assertIn("captureFocus(elements.slides)", self.source)
        self.assertIn("restoreFocus(focusSnapshot, elements.slides)", self.source)

    def test_preview_measurement_and_draft_storage_are_coalesced(self) -> None:
        self.assertIn("function schedulePreviewMeasure", self.source)
        self.assertIn("schedulePreviewMeasure(slide.id);", self.source)
        self.assertIn("storageTimer = window.setTimeout(flushDraft, 220)", self.source)
        self.assertNotIn("requestAnimationFrame(measurePreviews", self.source)

    def test_real_italic_and_render_contract_are_fail_closed(self) -> None:
        self.assertIn(
            'loadedFontKeys.has(fontAssetKey(asset, fontAssetDescriptors("italic", "italic")))',
            self.source,
        )
        self.assertIn("il sottotitolo richiede una vera variante corsiva", self.source)
        self.assertIn("const realItalic = slide.kind === \"cover\" && hasRealItalicFont()", self.source)
        self.assertIn(".slide-preview.has-real-italic .preview-cover-subtitle", self.stylesheet)
        self.assertIn("getRenderContract", self.source)
        self.assertIn("proofApproved: model?.proof_approved === true", self.source)
        for field in ("revision", "workflowState", "styleSystem", "contentSnapshot", "frames", "geometry"):
            with self.subTest(field=field):
                self.assertIn(f"{field}:", self.source)

    @unittest.skipUnless(shutil.which("node"), "Node.js non disponibile")
    def test_geometry_treats_zero_layout_descendants_as_hidden(self) -> None:
        script = r'''
const assert = require("node:assert/strict");
const { geometryPartIsHidden } = require(process.argv[1]);
const node = (rectCount = 1, hidden = false) => ({
  hidden,
  getClientRects() { return Array.from({ length: rectCount }, () => ({})); },
});
assert.equal(geometryPartIsHidden(node(), { display: "block", visibility: "visible" }), false);
assert.equal(geometryPartIsHidden(node(0), { display: "block", visibility: "visible" }), true);
assert.equal(geometryPartIsHidden(node(), { display: "none", visibility: "visible" }), true);
assert.equal(geometryPartIsHidden(node(), { display: "block", visibility: "hidden" }), true);
assert.equal(geometryPartIsHidden(node(), { display: "block", visibility: "collapse" }), true);
assert.equal(geometryPartIsHidden(node(1, true), { display: "block", visibility: "visible" }), true);
'''
        result = subprocess.run(
            ["node", "-e", script, str(EDITOR)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        geometry_part = self.source.split("function geometryPart(node, previewBounds)", 1)[1].split(
            "function previewGeometrySnapshot", 1
        )[0]
        self.assertLess(
            geometry_part.index("geometryPartIsHidden(node, style)"),
            geometry_part.index("node.getBoundingClientRect()"),
        )

    def test_preview_ready_waits_for_backgrounds_and_parity_capture_box(self) -> None:
        wait = self.source.split("async function waitForPreviewImages()", 1)[1].split("async function publishPreviewContract", 1)[0]
        self.assertIn("window.getComputedStyle(preview).backgroundImage", wait)
        self.assertIn("const probe = new Image()", wait)
        self.assertIn("await probe.decode()", wait)
        self.assertIn('queryParams.get("capture") === "parity"', self.source)
        self.assertIn('html[data-capture-target="true"] .slide-preview', self.stylesheet)
        for selector in (
            'html[data-capture-target="true"] body',
            'html[data-capture-target="true"] .topbar',
            'html[data-capture-target="true"] .shell',
            'html[data-capture-target="true"] .slide-row',
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.stylesheet)
        for declaration in ("width: 480px;", "border: 10px solid", "border-radius: 0;", "box-shadow: none;"):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.stylesheet.split('html[data-capture-target="true"] .slide-preview', 1)[1])

    def test_editor_tokens_targets_and_reduced_motion_meet_hardening_floor(self) -> None:
        self.assertIn('content="light"', self.html)
        self.assertIn("--muted: #696a69;", self.stylesheet)
        self.assertIn("color: #6b6c6b;", self.stylesheet)
        self.assertIn(".visual-system-option {\n  min-height: 44px;", self.stylesheet)
        self.assertIn(".applied-style-chip", self.stylesheet)
        self.assertIn("min-height: 44px;", self.stylesheet)
        reduced_motion = self.stylesheet.split("@media (prefers-reduced-motion: reduce)", 1)[1].split("}", 4)[0]
        self.assertNotIn("*::before", reduced_motion)

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
        self.assertIn("model?.render_contract", self.source)
        self.assertIn('if (!renderContractId()) throw new Error("Contratto renderer non disponibile.")', self.source)
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
        self.assertNotIn("La card interna può usare un solo trattamento", self.source)

    def test_cover_comment_suggests_a_title_coherent_drawing(self) -> None:
        self.assertIn('slide.kind === "cover"', self.source)
        self.assertIn("Per esempio: aggiungi un disegno coerente col titolo", self.source)
        self.assertIn("Per esempio: questa slide ripete la precedente", self.source)

    def test_agent_recovers_durable_editor_events_at_every_checkpoint(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        visual_review = (ROOT / "references" / "visual-review.md").read_text(encoding="utf-8")
        self.assertIn("anche in questo checkpoint e in ogni prova successiva", skill)
        self.assertIn("in ogni checkpoint dell'editor", visual_review)
        self.assertIn("session-state.json", visual_review)
        self.assertIn("last_feedback_id", visual_review)
        self.assertIn("last_action", visual_review)

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

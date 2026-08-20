(() => {
  "use strict";

  const REQUIRED_PALETTE_COLORS = [
    ["background_light", "sfondo chiaro"],
    ["background_dark", "sfondo scuro"],
    ["text_on_light", "testo su fondo chiaro"],
    ["text_on_dark", "testo su fondo scuro"],
    ["accent", "accento"],
  ];

  function isHexColor(value) {
    return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
  }

  function mergePreviewBrand(profileValue, proofValue) {
    const profile = profileValue && typeof profileValue === "object" ? profileValue : {};
    const proof = proofValue && typeof proofValue === "object" ? proofValue : {};
    const profilePalette = profile.palette && typeof profile.palette === "object" ? profile.palette : {};
    const proofPalette = proof.palette && typeof proof.palette === "object" ? proof.palette : {};
    const profileDeclared = profile.palette_declared && typeof profile.palette_declared === "object" ? profile.palette_declared : {};
    const proofDeclared = proof.palette_declared && typeof proof.palette_declared === "object" ? proof.palette_declared : {};
    const paletteDeclared = { ...profileDeclared };
    for (const [field, declared] of Object.entries(proofDeclared)) paletteDeclared[field] = declared === true;
    for (const field of Object.keys(proofPalette)) {
      if (!Object.prototype.hasOwnProperty.call(proofDeclared, field)) paletteDeclared[field] = false;
    }
    return {
      ...profile,
      ...proof,
      palette: { ...profilePalette, ...proofPalette },
      palette_declared: paletteDeclared,
      font_assets: { ...(profile.font_assets || {}), ...(proof.font_assets || {}) },
      logos: { ...(profile.logos || {}), ...(proof.logos || {}) },
    };
  }

  function collectPaletteDeclarationIssues(brandValue) {
    const brand = brandValue && typeof brandValue === "object" ? brandValue : {};
    const palette = brand.palette && typeof brand.palette === "object" ? brand.palette : {};
    const declared = brand.palette_declared && typeof brand.palette_declared === "object" ? brand.palette_declared : {};
    const issues = [];
    for (const [field, label] of REQUIRED_PALETTE_COLORS) {
      if (declared[field] === true && isHexColor(palette[field])) continue;
      const reason = declared[field] === true
        ? `${label} deve usare il formato #RRGGBB`
        : `${label} deve essere dichiarato esplicitamente nel brand kit`;
      issues.push({
        key: `palette-${field}`,
        message: `Palette non valida: ${reason}. Il fallback dell’anteprima non può essere approvato.`,
        targetId: "visual-system-picker",
      });
    }
    return issues;
  }

  function geometryPartIsHidden(node, style) {
    return Boolean(
      node?.hidden
      || style?.display === "none"
      || style?.visibility === "hidden"
      || style?.visibility === "collapse"
      || (typeof node?.getClientRects === "function" && node.getClientRects().length === 0)
    );
  }

  function tabDraftStorageKey(sharedKey, tabId) {
    return `${sharedKey}:tab:${tabId}`;
  }

  function previewReadyForApproval(dataset) {
    return dataset?.previewReady === "true" && !dataset.productionError;
  }

  function fontAssetRequiresVerifiedLoad(asset) {
    return Boolean(asset && asset.available === true);
  }

  const FONT_ROLE_WEIGHT_RANGES = Object.freeze({
    display: "700 900",
    body: "100 699",
    serif: "100 900",
    italic: "100 900",
  });

  function fontAssetDescriptors(role, style = "normal") {
    return {
      style: style === "italic" ? "italic" : "normal",
      weight: FONT_ROLE_WEIGHT_RANGES[role] || "100 900",
    };
  }

  if (typeof module === "object" && module.exports) {
    module.exports = {
      collectPaletteDeclarationIssues,
      fontAssetRequiresVerifiedLoad,
      fontAssetDescriptors,
      geometryPartIsHidden,
      mergePreviewBrand,
      previewReadyForApproval,
      tabDraftStorageKey,
    };
    return;
  }

  if (window.location.protocol === "file:") {
    const loading = document.querySelector("#loading");
    const badge = document.querySelector("#workflow-badge");
    if (badge) badge.textContent = "Sessione non avviata";
    if (loading) {
      const panel = document.createElement("div");
      panel.className = "file-launcher-panel";
      const title = document.createElement("h2");
      title.textContent = "Apri l’editor dalla sessione locale";
      const copy = document.createElement("p");
      copy.textContent = "Questo file è soltanto il sorgente dell’interfaccia. Per caricare slide, font e commenti, usa il link 127.0.0.1 generato da Carousel Builder nel task.";
      const hint = document.createElement("p");
      hint.className = "file-launcher-hint";
      hint.textContent = "Se la sessione è terminata, chiedi di riaprire l’editor: verrà fornito un nuovo indirizzo locale autorizzato.";
      panel.append(title, copy, hint);
      loading.replaceChildren(panel);
      loading.classList.add("file-launcher");
    }
    return;
  }

  const queryParams = new URLSearchParams(window.location.search);
  const token = queryParams.get("token") || "";
  const productionRender = queryParams.get("render") === "production";
  const parityCapture = queryParams.get("capture") === "parity";
  const validReturnUrl = (value) => (
    typeof value === "string"
    && /^codex:\/\/threads\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  );
  if (productionRender) document.documentElement.classList.add("production-render");
  if (parityCapture) document.documentElement.dataset.captureTarget = "true";
  const api = (path) => {
    const url = new URL(path, window.location.origin);
    if (token) url.searchParams.set("token", token);
    return url.toString();
  };
  const sharedStorageKey = `carousel-builder:${token}`;
  const tabSessionKey = `${sharedStorageKey}:tab-id`;
  const tabId = productionRender ? "production" : getOrCreateTabId(tabSessionKey);
  const storageKey = tabDraftStorageKey(sharedStorageKey, tabId);
  const legacyClaimKey = `${sharedStorageKey}:legacy-claim`;
  const legacyVisualSystemStorageKey = `${sharedStorageKey}:visual-system`;

  const elements = {
    loading: document.querySelector("#loading"),
    editor: document.querySelector("#editor"),
    actionbar: document.querySelector("#actionbar"),
    workflowBadge: document.querySelector("#workflow-badge"),
    revisionLabel: document.querySelector("#revision-label"),
    builderVersion: document.querySelector("#builder-version"),
    brandName: document.querySelector("#brand-name"),
    brandTypography: document.querySelector("#brand-typography"),
    palette: document.querySelector("#palette"),
    logoPreference: document.querySelector("#logo-preference"),
    logoPreferenceStatus: document.querySelector("#logo-preference-status"),
    logoVariants: document.querySelector("#logo-variants"),
    logoWarning: document.querySelector("#logo-warning"),
    styleExportButton: document.querySelector("#export-style-button"),
    brandNote: document.querySelector("#brand-note"),
    slides: document.querySelector("#slides"),
    overallNote: document.querySelector("#overall-note"),
    commentsList: document.querySelector("#comments-list"),
    commentCount: document.querySelector("#comment-count"),
    undoButton: document.querySelector("#undo-button"),
    resetButton: document.querySelector("#reset-button"),
    sendButton: document.querySelector("#send-button"),
    approveButton: document.querySelector("#approve-button"),
    dialog: document.querySelector("#comment-dialog"),
    approvalDialog: document.querySelector("#approval-dialog"),
    commentQuote: document.querySelector("#comment-quote"),
    commentFeedback: document.querySelector("#comment-feedback"),
    saveComment: document.querySelector("#save-comment"),
    confirmApproval: document.querySelector("#confirm-approval"),
    toast: document.querySelector("#toast"),
    // Optional during the HTML/CSS integration of the enhanced review UI.
    sequenceNav: document.querySelector("#sequence-nav"),
    fontStatus: document.querySelector("#font-status"),
    mobileActionsButton: document.querySelector("#mobile-actions-button"),
    mobileActionsDialog: document.querySelector("#mobile-actions-dialog"),
    mobileUndoButton: document.querySelector("#mobile-undo-button"),
    mobileResetButton: document.querySelector("#mobile-reset-button"),
    mobileSendButton: document.querySelector("#mobile-send-button"),
    mobileApproveButton: document.querySelector("#mobile-approve-button"),
    closeMobileActions: document.querySelector("#close-mobile-actions"),
    cancelComment: document.querySelector("#cancel-comment"),
    approvalSummary: document.querySelector("#approval-summary"),
    approvalDialogTitle: document.querySelector("#approval-dialog-title"),
    approvalDialogCopy: document.querySelector("#approval-dialog-copy"),
    visualSystemPicker: document.querySelector("#visual-system-picker"),
    visualSystemDescription: document.querySelector("#visual-system-description"),
    compareVisualSystems: document.querySelector("#compare-visual-systems"),
    showAdvancedVisualSystem: document.querySelector("#show-advanced-visual-system"),
    coverChoice: document.querySelector("#cover-choice"),
    coverChoiceDescription: document.querySelector("#cover-choice-description"),
    validationSummary: document.querySelector("#validation-summary"),
    validationSummaryCopy: document.querySelector("#validation-summary-copy"),
    validationList: document.querySelector("#validation-list"),
    retrySubmitButton: document.querySelector("#retry-submit-button"),
    exportRecoveryButton: document.querySelector("#export-recovery-button"),
    workflowJourney: document.querySelector("#workflow-journey"),
    workflowJourneyTitle: document.querySelector("#workflow-journey-title"),
    workflowJourneyCopy: document.querySelector("#workflow-journey-copy"),
    workflowSteps: document.querySelector("#workflow-steps"),
    agentStatusCard: document.querySelector("#agent-status-card"),
    agentStatusLabel: document.querySelector("#agent-status-label"),
    agentStatusDetail: document.querySelector("#agent-status-detail"),
    returnChatButton: document.querySelector("#return-chat-button"),
    toggleProofEditing: document.querySelector("#toggle-proof-editing"),
    proofEditingNote: document.querySelector("#proof-editing-note"),
    guidancePanel: document.querySelector("#guidance-panel"),
    guidanceTitle: document.querySelector("#guidance-title"),
    guidanceList: document.querySelector("#guidance-list"),
  };

  let model = null;
  let returnUrl = "";
  let baselineSlides = [];
  let draftSlides = [];
  let selectionComments = [];
  let slideNotes = {};
  let brandNote = "";
  let overallNote = "";
  let pendingSelection = null;
  let awaitingFeedbackId = null;
  let pendingSubmission = null;
  let recoverySubmissions = [];
  let recoveryDrafts = [];
  let foreignFeedbackId = null;
  let submissionError = "";
  let staleRevision = null;
  let staleWorkflowState = null;
  let staleApprovalCheckpoint = null;
  let toastTimer = null;
  let observer = null;
  let resizeTimer = null;
  let storageTimer = null;
  let previewMeasureFrame = null;
  let measureAllPreviews = false;
  let pollTimer = null;
  let pollInFlight = false;
  let pollFailures = 0;
  let pollAbortController = null;
  let currentSlideId = null;
  let viewedSlideIds = new Set();
  let pointerDrag = null;
  let selectedVisualSystem = "editorial-frame";
  let logoMode = "auto";
  let selectedCoverMode = "typographic";
  let visualAlternativeExpanded = false;
  let advancedVisualExpanded = false;
  let undoState = null;
  let previewContractRun = 0;
  let validationMode = false;
  let activeValidationIssues = [];
  let proofEditingExpanded = true;
  let fontAdvisories = [];
  const fitWarnings = new Map();
  const pendingPreviewIds = new Set();
  const fontLoadCache = new Map();
  const loadedFontKeys = new Set();

  const POLL_BASE_DELAY = 2000;
  const POLL_MAX_DELAY = 30000;
  const REQUEST_TIMEOUT = 8000;

  const visualSystems = [
    {
      id: "editorial-frame",
      label: "A · Editoriale",
      description: "Sistema editoriale: una cornice netta guida la lettura, con il testo al centro della scena.",
    },
    {
      id: "editorial-halftone",
      label: "B · Geometrico",
      description: "Sistema geometrico: cinque corpi di scale diverse danno ritmo alla fascia laterale senza competere con il testo.",
    },
    {
      id: "corporate-modular",
      label: "C · Istituzionale",
      description: "Sistema istituzionale: un indice compatto ordina metodo, dati e processi senza sottrarre spazio al testo.",
    },
  ];

  const workflowLabels = {
    bozza: "Bozza",
    draft: "Bozza",
    in_revisione: "In revisione",
    in_revisione_editoriale: "In revisione editoriale",
    in_review: "In revisione",
    feedback: "In attesa di correzioni",
    testi_approvati: "Testi approvati",
    prova_visuale_approvata: "Prova visuale approvata",
    rendering: "Rendering",
    qa: "Controllo qualità",
    consegnato: "Consegnato",
    approvato: "Approvato",
    approved: "Approvato",
    pubblicato: "Pubblicato",
    published: "Pubblicato",
  };

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function create(tag, className, textValue) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textValue !== undefined) node.textContent = textValue;
    return node;
  }

  function createIcon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      name === "up"
        ? "m6 15 6-6 6 6"
        : name === "down"
          ? "m6 9 6 6 6-6"
          : name === "grip"
            ? "M9 5h.01M9 12h.01M9 19h.01M15 5h.01M15 12h.01M15 19h.01"
            : "m6 6 12 12M18 6 6 18",
    );
    if (name === "grip") path.setAttribute("stroke-width", "3");
    svg.append(path);
    return svg;
  }

  function createIconButton(className, icon, title, label) {
    const button = create("button", className);
    button.type = "button";
    button.title = title;
    button.setAttribute("aria-label", label);
    button.append(createIcon(icon));
    return button;
  }

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  }

  function safeStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (_error) {
      // Editing remains usable when browser storage is unavailable.
      return false;
    }
  }

  function safeStorageRemove(key) {
    try {
      localStorage.removeItem(key);
    } catch (_error) {
      // A stale local draft is less harmful than interrupting a review.
    }
  }

  function getOrCreateTabId(key) {
    try {
      const saved = sessionStorage.getItem(key);
      if (isFeedbackId(saved)) return saved;
      const created = createFeedbackId();
      sessionStorage.setItem(key, created);
      return created;
    } catch (_error) {
      // The in-memory id still isolates this page even when sessionStorage is disabled.
      return createFeedbackId();
    }
  }

  function createFeedbackId() {
    if (typeof crypto?.randomUUID === "function") return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }

  function isFeedbackId(value) {
    return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  }

  function isPendingSubmission(value) {
    return Boolean(
      value
      && isFeedbackId(value.feedback_id)
      && value.payload?.feedback_id === value.feedback_id
      && value.payload?.action === value.action
      && ["feedback", "approve"].includes(value.action),
    );
  }

  function isRecoverySubmission(value) {
    return Boolean(
      value
      && value.schema === "carousel-builder-feedback-recovery-v1"
      && isFeedbackId(value.feedback_id)
      && value.payload?.feedback_id === value.feedback_id
      && ["feedback", "approve"].includes(value.action)
      && value.payload?.action === value.action,
    );
  }

  function isRecoveryDraft(value) {
    return Boolean(
      value
      && value.schema === "carousel-builder-draft-recovery-v1"
      && typeof value.recovery_id === "string"
      && value.recovery_id
      && Number.isInteger(value.base_revision)
      && Array.isArray(value.draft?.slides),
    );
  }

  function isAppliedRecovery(value) {
    return Boolean(
      value
      && value.schema === "carousel-builder-feedback-applied-v1"
      && isFeedbackId(value.feedback_id),
    );
  }

  function recoveryStorageKey(kind, identifier) {
    return `${sharedStorageKey}:recovery:${kind}:${identifier}`;
  }

  function persistDedicatedRecovery(kind, identifier, recovery) {
    const key = recoveryStorageKey(kind, identifier);
    if (safeStorageGet(key) !== null) return true;
    return safeStorageSet(key, JSON.stringify(recovery));
  }

  function recoveryWasApplied(feedbackId) {
    if (!isFeedbackId(feedbackId)) return false;
    try {
      return isAppliedRecovery(JSON.parse(safeStorageGet(recoveryStorageKey("applied", feedbackId)) || "null"));
    } catch (_error) {
      return false;
    }
  }

  function markRecoveryApplied(feedbackId) {
    if (!isFeedbackId(feedbackId)) return;
    persistDedicatedRecovery("applied", feedbackId, {
      schema: "carousel-builder-feedback-applied-v1",
      feedback_id: feedbackId,
      applied_at: new Date().toISOString(),
    });
    recoverySubmissions = recoverySubmissions.filter((item) => item.feedback_id !== feedbackId);
    safeStorageRemove(recoveryStorageKey("submission", feedbackId));
  }

  function loadDedicatedRecoveries() {
    const prefix = `${sharedStorageKey}:recovery:`;
    try {
      const records = [];
      const appliedIds = new Set();
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index);
        if (!key?.startsWith(prefix)) continue;
        const recovery = JSON.parse(localStorage.getItem(key) || "null");
        if (isAppliedRecovery(recovery)) appliedIds.add(recovery.feedback_id);
        else records.push(recovery);
      }
      recoverySubmissions = recoverySubmissions.filter((item) => !appliedIds.has(item.feedback_id));
      for (const recovery of records) {
        if (isRecoverySubmission(recovery) && !appliedIds.has(recovery.feedback_id)) addRecoverySubmission(recovery, { persist: false });
        else if (isRecoveryDraft(recovery)) addRecoveryDraft(recovery, { persist: false });
      }
    } catch (_error) {
      // The shared draft still retains recovery records when storage enumeration is unavailable.
    }
  }

  function recoveryFromPending(pending, reason, savedDraft = null, serverError = "") {
    const source = savedDraft && typeof savedDraft === "object" ? savedDraft : {};
    return {
      schema: "carousel-builder-feedback-recovery-v1",
      reason,
      feedback_id: pending.feedback_id,
      action: pending.action,
      base_revision: pending.payload.base_revision,
      base_workflow_state: pending.payload.base_workflow_state || source.base_workflow_state || "",
      base_approval_checkpoint: source.base_approval_checkpoint || "",
      detected_revision: model?.revision ?? null,
      preserved_at: new Date().toISOString(),
      server_error: serverError,
      payload: clone(pending.payload),
      draft: {
        base_revision: source.base_revision ?? pending.payload.base_revision,
        slides: clone(source.slides || pending.payload.slides || []),
        comments: clone(source.comments || []),
        slide_notes: clone(source.slide_notes || {}),
        brand_note: typeof source.brand_note === "string" ? source.brand_note : "",
        overall_note: typeof source.overall_note === "string" ? source.overall_note : pending.payload.overall_note || "",
        logo_mode: source.logo_mode || pending.payload.logo_mode || "auto",
        cover_mode: source.cover_mode || pending.payload.cover_mode || "typographic",
        visual_style_system: source.visual_style_system || pending.payload.visual_style_system || "",
        saved_at: source.saved_at || "",
      },
    };
  }

  function addRecoverySubmission(recovery, { persist = true } = {}) {
    if (!isRecoverySubmission(recovery)) return;
    if (recoveryWasApplied(recovery.feedback_id)) return;
    if (recoverySubmissions.some((item) => item.feedback_id === recovery.feedback_id)) return;
    recoverySubmissions.push(recovery);
    if (persist) persistDedicatedRecovery("submission", recovery.feedback_id, recovery);
  }

  function addRecoveryDraft(recovery, { persist = true } = {}) {
    if (!isRecoveryDraft(recovery)) return;
    const duplicate = recoveryDrafts.some((item) => (
      item.base_revision === recovery.base_revision
      && item.related_feedback_id === recovery.related_feedback_id
      && JSON.stringify(item.draft) === JSON.stringify(recovery.draft)
    ));
    if (duplicate) return;
    recoveryDrafts.push(recovery);
    if (persist) persistDedicatedRecovery("draft", recovery.recovery_id, recovery);
  }

  function preserveCurrentDraft(reason, relatedFeedbackId = "") {
    if (!model || computeChangeCount() === 0) return;
    addRecoveryDraft({
      schema: "carousel-builder-draft-recovery-v1",
      recovery_id: createFeedbackId(),
      reason,
      related_feedback_id: relatedFeedbackId,
      base_revision: model.revision,
      base_workflow_state: model.workflow_state || "",
      base_approval_checkpoint: model.approval_checkpoint || "",
      detected_revision: model.revision,
      preserved_at: new Date().toISOString(),
      draft: {
        slides: normalizedSlides(draftSlides),
        comments: clone(selectionComments),
        slide_notes: clone(slideNotes),
        brand_note: brandNote,
        overall_note: overallNote,
        logo_mode: logoMode,
        cover_mode: selectedCoverMode,
        visual_style_system: selectedVisualSystem,
      },
    });
  }

  function recoveryDraftFromSaved(saved, reason) {
    return {
      schema: "carousel-builder-draft-recovery-v1",
      recovery_id: createFeedbackId(),
      reason,
      related_feedback_id: "",
      base_revision: saved.base_revision,
      base_workflow_state: saved.base_workflow_state || "",
      base_approval_checkpoint: saved.base_approval_checkpoint || "",
      detected_revision: model?.revision ?? null,
      preserved_at: new Date().toISOString(),
      draft: {
        slides: clone(Array.isArray(saved.slides) ? saved.slides : []),
        comments: clone(Array.isArray(saved.comments) ? saved.comments : []),
        slide_notes: clone(saved.slide_notes && typeof saved.slide_notes === "object" ? saved.slide_notes : {}),
        brand_note: typeof saved.brand_note === "string" ? saved.brand_note : "",
        overall_note: typeof saved.overall_note === "string" ? saved.overall_note : "",
        logo_mode: saved.logo_mode || saved.logo_preference || "auto",
        cover_mode: saved.cover_mode || "typographic",
        visual_style_system: saved.visual_style_system || supportedVisualSystem(safeStorageGet(visualSystemStorageKey())) || "",
      },
    };
  }

  function preservePendingSubmission(reason, serverError = "", savedDraft = null) {
    if (!isPendingSubmission(pendingSubmission)) return;
    addRecoverySubmission(recoveryFromPending(pendingSubmission, reason, savedDraft, serverError));
  }

  function currentDraftRecoverySource() {
    return {
      base_revision: model?.revision ?? null,
      base_workflow_state: model?.workflow_state || "",
      base_approval_checkpoint: model?.approval_checkpoint || "",
      slides: normalizedSlides(draftSlides),
      comments: clone(selectionComments),
      slide_notes: clone(slideNotes),
      brand_note: brandNote,
      overall_note: overallNote,
      logo_mode: logoMode,
      cover_mode: selectedCoverMode,
      visual_style_system: selectedVisualSystem,
      saved_at: new Date().toISOString(),
    };
  }

  function migrateLegacyStorageLocked() {
    const raw = safeStorageGet(sharedStorageKey);
    if (raw === null) return;
    let saved;
    try {
      saved = JSON.parse(raw);
    } catch (_error) {
      // Keep an unreadable legacy value in place rather than deleting the only copy.
      return;
    }
    if (!saved || typeof saved !== "object") return;

    const legacyVisualSystem = supportedVisualSystem(safeStorageGet(legacyVisualSystemStorageKey));
    if (legacyVisualSystem && !saved.visual_style_system) saved.visual_style_system = legacyVisualSystem;
    let recoveriesReady = true;
    const legacyPending = isPendingSubmission(saved.pending_submission) ? saved.pending_submission : null;
    if (legacyPending && !recoveryWasApplied(legacyPending.feedback_id)) {
      const recovery = recoveryFromPending(legacyPending, "legacy-primary-migration", saved);
      recoveriesReady = persistDedicatedRecovery("submission", legacyPending.feedback_id, recovery) && recoveriesReady;
    }
    if (saved.editable_draft !== false && Number.isInteger(saved.base_revision) && Array.isArray(saved.slides)) {
      const recovery = recoveryDraftFromSaved(saved, "legacy-primary-migration");
      recoveriesReady = persistDedicatedRecovery("draft", recovery.recovery_id, recovery) && recoveriesReady;
    }

    let claim = null;
    try {
      claim = JSON.parse(safeStorageGet(legacyClaimKey) || "null");
    } catch (_error) {
      claim = null;
    }
    const claimedPrimaryExists = typeof claim?.primary_storage_key === "string" && safeStorageGet(claim.primary_storage_key) !== null;
    if (!isFeedbackId(claim?.tab_id) || !claimedPrimaryExists) {
      claim = {
        schema: "carousel-builder-legacy-claim-v1",
        tab_id: tabId,
        primary_storage_key: storageKey,
        claimed_at: new Date().toISOString(),
      };
      if (!safeStorageSet(legacyClaimKey, JSON.stringify(claim))) return;
    }
    const ownsLegacyDraft = claim.tab_id === tabId && claim.primary_storage_key === storageKey;
    const primaryReady = !ownsLegacyDraft || safeStorageGet(storageKey) !== null || safeStorageSet(storageKey, raw);
    const claimedVisualSystemKey = `${claim.primary_storage_key}:visual-system`;
    const visualSystemReady = !legacyVisualSystem
      || safeStorageGet(claimedVisualSystemKey) !== null
      || safeStorageSet(claimedVisualSystemKey, legacyVisualSystem);
    if (recoveriesReady && primaryReady && visualSystemReady) {
      safeStorageRemove(sharedStorageKey);
      safeStorageRemove(legacyVisualSystemStorageKey);
    }
  }

  async function migrateLegacyStorage() {
    const lockName = `${sharedStorageKey}:legacy-migration`;
    if (navigator.locks?.request) {
      await navigator.locks.request(lockName, () => migrateLegacyStorageLocked());
      return;
    }
    migrateLegacyStorageLocked();
  }

  async function fetchJson(path, options = {}, timeout = REQUEST_TIMEOUT) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeout);
    const externalSignal = options.signal;
    const abortFromExternal = () => controller.abort();
    externalSignal?.addEventListener("abort", abortFromExternal, { once: true });
    try {
      const response = await fetch(api(path), { ...options, signal: controller.signal });
      let data = {};
      try {
        data = await response.json();
      } catch (_error) {
        data = {};
      }
      return { response, data };
    } finally {
      window.clearTimeout(timeoutId);
      externalSignal?.removeEventListener("abort", abortFromExternal);
    }
  }

  function captureFocus(container) {
    const node = document.activeElement;
    if (!node || !container?.contains(node)) return null;
    return {
      id: node.id || "",
      slideId: node.closest?.(".slide-row")?.dataset.slideId || "",
      action: node.dataset?.action || "",
      sequenceSlide: node.dataset?.sequenceSlide || "",
      visualSystem: node.dataset?.visualSystem || "",
      selectionStart: typeof node.selectionStart === "number" ? node.selectionStart : null,
      selectionEnd: typeof node.selectionEnd === "number" ? node.selectionEnd : null,
    };
  }

  function restoreFocus(snapshot, container = document) {
    if (!snapshot) return;
    let target = snapshot.id ? document.getElementById(snapshot.id) : null;
    if (!target && snapshot.slideId && snapshot.action) {
      target = container.querySelector?.(`[data-slide-id="${selectorValue(snapshot.slideId)}"] [data-action="${selectorValue(snapshot.action)}"]`);
    }
    if (!target && snapshot.sequenceSlide) {
      target = container.querySelector?.(`[data-sequence-slide="${selectorValue(snapshot.sequenceSlide)}"]`);
    }
    if (!target && snapshot.visualSystem) {
      target = container.querySelector?.(`[data-visual-system="${selectorValue(snapshot.visualSystem)}"]`);
    }
    if (!target || target.disabled) return;
    target.focus({ preventScroll: true });
    if (snapshot.selectionStart !== null && typeof target.setSelectionRange === "function") {
      target.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
    }
  }

  function schedulePreviewMeasure(slideId = null) {
    if (slideId) pendingPreviewIds.add(slideId);
    else measureAllPreviews = true;
    if (previewMeasureFrame !== null) return;
    previewMeasureFrame = window.requestAnimationFrame(() => {
      previewMeasureFrame = null;
      const targets = measureAllPreviews ? null : new Set(pendingPreviewIds);
      measureAllPreviews = false;
      pendingPreviewIds.clear();
      measurePreviews(targets);
    });
  }

  function flushPreviewMeasurements() {
    if (previewMeasureFrame !== null) window.cancelAnimationFrame(previewMeasureFrame);
    previewMeasureFrame = null;
    measureAllPreviews = false;
    pendingPreviewIds.clear();
    measurePreviews();
  }

  function showToast(message, error = false) {
    if (!elements.toast) return;
    window.clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("error", error);
    elements.toast.setAttribute("role", error ? "alert" : "status");
    elements.toast.setAttribute("aria-live", error ? "assertive" : "polite");
    elements.toast.classList.add("visible");
    toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 4200);
  }

  function safeColor(value, fallback) {
    return isHexColor(value) ? value : fallback;
  }

  function relativeLuminance(hex) {
    const channels = [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255);
    const linear = channels.map((channel) => channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  }

  function contrastRatio(first, second) {
    const lighter = Math.max(relativeLuminance(first), relativeLuminance(second));
    const darker = Math.min(relativeLuminance(first), relativeLuminance(second));
    return (lighter + 0.05) / (darker + 0.05);
  }

  function mixHexColor(source, target, amount) {
    const channels = (hex) => [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
    const mixed = channels(source).map((value, index) => Math.round(value + (channels(target)[index] - value) * amount));
    return `#${mixed.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
  }

  function adaptiveHighlightBackground(colors) {
    const candidates = [{ color: colors.accent, distance: 0 }];
    for (const target of ["#000000", "#ffffff"]) {
      for (let step = 1; step <= 20; step += 1) {
        candidates.push({ color: mixHexColor(colors.accent, target, step / 20), distance: step / 20 });
      }
    }
    for (const color of [colors.backgroundDark, colors.backgroundLight]) {
      candidates.push({ color, distance: 0.35 });
    }
    const eligible = candidates.filter(({ color }) => (
      contrastRatio(color, colors.text) >= 4.5
      && contrastRatio(color, colors.bg) >= 1.08
    ));
    eligible.sort((first, second) => (
      first.distance - second.distance
      || contrastRatio(second.color, colors.bg) - contrastRatio(first.color, colors.bg)
    ));
    if (eligible.length) return eligible[0].color;
    return relativeLuminance(colors.text) > 0.5 ? "#000000" : "#ffffff";
  }

  function selectorValue(value) {
    if (window.CSS?.escape) return window.CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function normalizedSlides(slides) {
    const knownEmphasisFields = [
      "title_bold", "title_italic", "title_serif", "title_accent", "title_underline",
      "summary_bold", "summary_italic", "summary_serif", "summary_accent", "summary_underline",
      "cover_title_bold", "cover_title_italic", "cover_title_serif", "cover_title_accent", "cover_title_underline",
    ];
    return slides.map((slide) => {
      const normalized = {
        id: slide.id,
        kind: slide.kind,
        title: slide.title,
        summary: slide.summary,
      };
      const emphasisFields = new Set([
        ...knownEmphasisFields,
        ...Object.keys(slide).filter((key) => /_(bold|italic|serif|accent|underline)$/.test(key)),
      ]);
      for (const key of emphasisFields) normalized[key] = Array.isArray(slide[key]) ? slide[key].filter((value) => typeof value === "string" && value) : [];
      return normalized;
    });
  }

  function initialLogoMode() {
    return model?.logo_mode === "hidden" ? "hidden" : "auto";
  }

  function logoRoleForSlide(slide, index) {
    const colors = previewColors(index, slide.kind);
    return colors.surface === "dark" ? "on_dark" : "on_light";
  }

  function logoMetadata(role) {
    const logos = previewBrand().logos && typeof previewBrand().logos === "object" ? previewBrand().logos : {};
    const value = logos[role];
    if (value && typeof value === "object") return value;
    if (typeof value === "string" && value.trim()) return { declared: true, available: false, endpoint: "", master_format: value.split(".").pop() || "" };
    return { declared: false, available: false, endpoint: "" };
  }

  function logoAvailabilityWarning() {
    if (logoMode === "hidden") return "";
    const required = new Set(draftSlides.map((slide, index) => logoRoleForSlide(slide, index)));
    const missing = [...required].filter((role) => logoMetadata(role).available !== true);
    if (!missing.length) return "";
    const labels = { on_light: "fondo chiaro", on_dark: "fondo scuro" };
    return `Logo automatico: manca una variante raster sicura per ${missing.map((role) => labels[role]).join(" e ")}. Le anteprime useranno la firma testuale dove possibile.`;
  }

  function displayLabel(slide, index) {
    if (slide.kind === "cover") return "Copertina";
    if (slide.kind === "outro") return "Chiusura";
    return `Slide ${index + 1}`;
  }

  function labelForValue(map, value, fallback) {
    return map[value] || fallback;
  }

  function viewedStorageKey() {
    return [
      storageKey,
      "viewed",
      model?.revision ?? "",
      model?.approval_checkpoint || "",
      model?.render_fingerprint || "",
      selectedVisualSystem || "",
    ].join(":");
  }

  function visualSystemStorageKey() {
    return `${storageKey}:visual-system`;
  }

  function supportedVisualSystem(value) {
    return visualSystems.some((system) => system.id === value) ? value : "";
  }

  function visualProofOptions() {
    const options = model?.visual_proofs?.options;
    return Array.isArray(options) ? options : [];
  }

  function alternateVisualSystem() {
    const supplied = model?.visual_proofs?.alternate_style_system;
    if (supportedVisualSystem(supplied) && supplied !== selectedVisualSystem) return supplied;
    return selectedVisualSystem === "corporate-modular"
      ? "editorial-frame"
      : "corporate-modular";
  }

  function selectedVisualProof() {
    return visualProofOptions().find((option) => option?.id === selectedVisualSystem) || null;
  }

  function requiredProofSlideIds() {
    const values = model?.proof?.required_slide_ids;
    return Array.isArray(values) ? values.filter((id) => typeof id === "string") : [];
  }

  function browserProofDescriptor() {
    const userAgent = navigator.userAgent || "";
    const candidates = [
      ["chromium", /(?:Chrome|Chromium|CriOS|Edg|OPR)\/(\d+)/],
    ];
    for (const [engine, pattern] of candidates) {
      const match = userAgent.match(pattern);
      const major = match ? Number.parseInt(match[1], 10) : 0;
      if (major >= 1 && major <= 999) return { engine, major };
    }
    return null;
  }

  const combinedApprovalScope = "profile_text_and_visual";

  function proofSlidesAtCanonicalSize() {
    const expectedWidth = model?.proof?.preview_width;
    const expectedHeight = model?.format?.preview_height;
    if (expectedWidth !== 480 || expectedHeight !== 600) return false;
    return requiredProofSlideIds().every((slideId) => {
      const preview = elements.slides?.querySelector(`[data-slide-id="${selectorValue(slideId)}"] .slide-preview`);
      const bounds = preview?.getBoundingClientRect();
      return Boolean(
        bounds
        && Math.abs(bounds.width - expectedWidth) <= 0.5
        && Math.abs(bounds.height - expectedHeight) <= 0.5
      );
    });
  }

  function modelCoverMode() {
    const mode = model?.cover_mode || model?.visual_proofs?.identity?.cover?.mode;
    if (["generated", "provided", "typographic"].includes(mode)) return mode;
    return model?.cover_visual?.available ? "provided" : "typographic";
  }

  function resolvedCoverMode() {
    return ["generated", "provided", "typographic"].includes(selectedCoverMode)
      ? selectedCoverMode
      : modelCoverMode();
  }

  function visualSystemDefinition(system) {
    const fallback = visualSystems.find((candidate) => candidate.id === system.id) || system;
    const supplied = visualProofOptions().find((option) => option?.id === system.id);
    return {
      ...fallback,
      label: typeof supplied?.label === "string" && supplied.label.trim() ? supplied.label.trim() : fallback.label,
    };
  }

  function previewBrand() {
    const profile = model?.brand && typeof model.brand === "object" ? model.brand : {};
    const proofBrand = selectedVisualProof()?.brand;
    return mergePreviewBrand(profile, proofBrand);
  }

  function resolveVisualSystem() {
    if (productionRender) return modelVisualSystem();
    return supportedVisualSystem(safeStorageGet(visualSystemStorageKey())) || modelVisualSystem();
  }

  function modelVisualSystem() {
    const modelValue = model?.visual_proofs?.selected_style_system || model?.visual_style_system || model?.visual_system || model?.visual_style || model?.brand?.visual_system;
    return supportedVisualSystem(modelValue) || "editorial-frame";
  }

  function renderVisualSystemPicker({ focusSystem = "" } = {}) {
    if (!elements.visualSystemPicker) return;
    const focusSnapshot = captureFocus(elements.visualSystemPicker);
    const active = visualSystemDefinition(visualSystems.find((system) => system.id === selectedVisualSystem) || visualSystems[0]);
    elements.visualSystemPicker.replaceChildren();
    elements.visualSystemPicker.dataset.activeSystem = active.id;
    if (elements.visualSystemDescription) elements.visualSystemDescription.textContent = active.description;
    const visibleSystems = visualSystems;
    for (const system of visibleSystems) {
      const definition = visualSystemDefinition(system);
      const button = create("button", "visual-system-option", definition.label);
      const selected = definition.id === active.id;
      button.type = "button";
      button.dataset.visualSystem = definition.id;
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(selected));
      button.tabIndex = selected ? 0 : -1;
      button.setAttribute("aria-label", `${definition.label}. ${definition.description}`);
      button.addEventListener("click", () => setVisualSystem(definition.id));
      button.addEventListener("keydown", (event) => {
        const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
        if (!keys.includes(event.key)) return;
        event.preventDefault();
        const currentIndex = visibleSystems.findIndex((candidate) => candidate.id === definition.id);
        const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
        const nextIndex = event.key === "Home"
          ? 0
          : event.key === "End"
            ? visibleSystems.length - 1
            : (currentIndex + delta + visibleSystems.length) % visibleSystems.length;
        setVisualSystem(visibleSystems[nextIndex].id, { focus: true });
      });
      elements.visualSystemPicker.append(button);
    }
    const requestedFocus = focusSystem || focusSnapshot?.visualSystem;
    if (requestedFocus) {
      elements.visualSystemPicker.querySelector(`[data-visual-system="${selectorValue(requestedFocus)}"]`)?.focus({ preventScroll: true });
    }
  }

  function setVisualSystem(systemId, { focus = false } = {}) {
    const next = supportedVisualSystem(systemId);
    if (!next) return;
    if (next === selectedVisualSystem) {
      if (focus) elements.visualSystemPicker?.querySelector(`[data-visual-system="${selectorValue(next)}"]`)?.focus();
      return;
    }
    recordUndo("sistema visivo");
    selectedVisualSystem = next;
    safeStorageSet(visualSystemStorageKey(), next);
    loadViewState();
    renderVisualSystemPicker({ focusSystem: focus ? next : "" });
    renderBrand();
    renderSlides();
    persistDraft();
    schedulePreviewMeasure();
  }

  function renderCoverChoice() {
    if (!elements.coverChoice) return;
    const visualSelected = resolvedCoverMode() !== "typographic";
    for (const button of elements.coverChoice.querySelectorAll("[data-cover-choice]")) {
      const selected = (button.dataset.coverChoice === "visual") === visualSelected;
      button.setAttribute("aria-checked", String(selected));
      button.tabIndex = selected ? 0 : -1;
      button.classList.toggle("is-selected", selected);
    }
    const available = model?.cover_visual?.available === true;
    if (elements.coverChoiceDescription) {
      elements.coverChoiceDescription.textContent = visualSelected
        ? available
          ? "Titolo a sinistra, immagine verticale a destra. Nessuna sovrapposizione."
          : "Titolo a sinistra; il visuale verticale verrà creato dopo l’approvazione dei testi."
        : "Copertina tipografica a tutta larghezza. Potrai aggiungere un visuale anche dopo l’approvazione dei testi.";
    }
  }

  function setCoverChoice(choice, { focus = false } = {}) {
    if (!["typographic", "visual"].includes(choice)) return;
    const currentMode = modelCoverMode();
    const next = choice === "typographic"
      ? "typographic"
      : ["generated", "provided"].includes(currentMode)
        ? currentMode
        : model?.cover_visual?.available === true
          ? "provided"
          : "generated";
    if (next === selectedCoverMode) {
      if (focus) elements.coverChoice?.querySelector(`[data-cover-choice="${choice}"]`)?.focus();
      return;
    }
    recordUndo("tipo di copertina");
    selectedCoverMode = next;
    renderCoverChoice();
    renderSlides();
    persistDraft();
    if (focus) elements.coverChoice?.querySelector(`[data-cover-choice="${choice}"]`)?.focus({ preventScroll: true });
  }

  function loadViewState() {
    const saved = safeStorageGet(viewedStorageKey());
    try {
      const values = JSON.parse(saved || "[]");
      const known = new Set((model?.slides || []).map((slide) => slide.id));
      viewedSlideIds = new Set(Array.isArray(values) ? values.filter((id) => known.has(id)) : []);
    } catch (_error) {
      viewedSlideIds = new Set();
    }
  }

  function persistViewState() {
    if (productionRender) return;
    safeStorageSet(viewedStorageKey(), JSON.stringify([...viewedSlideIds]));
  }

  function computeChangeCount() {
    let count = 0;
    const beforeById = new Map(baselineSlides.map((slide) => [slide.id, slide]));
    if (baselineSlides.map((slide) => slide.id).join("|") !== draftSlides.map((slide) => slide.id).join("|")) count += 1;
    for (const slide of draftSlides) {
      const before = beforeById.get(slide.id);
      if (!before || before.title !== slide.title || before.summary !== slide.summary || JSON.stringify(normalizedSlides([before])) !== JSON.stringify(normalizedSlides([slide]))) count += 1;
    }
    if (logoMode !== initialLogoMode()) count += 1;
    if (selectedCoverMode !== modelCoverMode()) count += 1;
    if (selectedVisualSystem !== modelVisualSystem()) count += 1;
    count += selectionComments.length;
    count += Object.values(slideNotes).filter((value) => typeof value === "string" && value.trim()).length;
    if (brandNote.trim()) count += 1;
    if (overallNote.trim()) count += 1;
    return count;
  }

  function hasAgentCorrections() {
    return Boolean(
      selectionComments.length
      || Object.values(slideNotes).some((value) => typeof value === "string" && value.trim())
      || brandNote.trim()
      || overallNote.trim()
    );
  }

  function hasPendingLock() {
    return Boolean(awaitingFeedbackId || foreignFeedbackId);
  }

  function hasStaleBase() {
    return staleRevision !== null || staleWorkflowState !== null || staleApprovalCheckpoint !== null;
  }

  function workflowPhase() {
    const state = model?.workflow_state || "bozza";
    if (state === "testi_approvati") return "visual";
    if (["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(state)) return "production";
    return "content";
  }

  function renderProofMode() {
    const proofStage = model?.workflow_state === "testi_approvati" && !productionRender;
    elements.editor?.classList.toggle("proof-mode", proofStage);
    elements.editor?.classList.toggle("proof-editing", proofStage && proofEditingExpanded);
    if (elements.toggleProofEditing) {
      elements.toggleProofEditing.hidden = !proofStage;
      elements.toggleProofEditing.setAttribute("aria-expanded", String(proofEditingExpanded));
      elements.toggleProofEditing.textContent = proofEditingExpanded
        ? "Torna alla prova visiva"
        : "Modifica contenuti o grafica";
    }
    if (elements.proofEditingNote) elements.proofEditingNote.hidden = !proofStage;
  }

  function renderGuidance(phase) {
    if (!elements.guidancePanel || !elements.guidanceList || !elements.guidanceTitle) return;
    elements.guidancePanel.hidden = phase === "production";
    if (phase === "production") return;
    const guidance = phase === "visual"
      ? {
          title: "Come controllare la prova",
          items: [
            "Apri le slide richieste e controlla composizione, gerarchia e leggibilità.",
            "Verifica copertina, logo o firma e sistema visivo.",
            "Per correggere qualcosa, seleziona Modifica contenuti o grafica.",
            "Approva la prova visiva: è il secondo consenso, distinto da quello sui testi.",
          ],
        }
      : {
          title: "Come revisionare",
          items: [
            "Correggi i testi nell’editor accanto all’anteprima.",
            "Seleziona una parola o una frase per applicare uno stile o aggiungere un commento.",
            "Sposta o elimina le slide interne con i comandi della slide.",
            "Approva i testi per dare il primo consenso e chiedere la prova visiva.",
          ],
        };
    elements.guidanceTitle.textContent = guidance.title;
    elements.guidanceList.replaceChildren(...guidance.items.map((item) => create("li", "", item)));
  }

  function returnToChat() {
    if (!returnUrl) return;
    elements.returnChatButton?.setAttribute("aria-busy", "true");
    window.location.assign(returnUrl);
  }

  function renderWorkflowJourney() {
    if (!model || !elements.workflowJourney) return;
    const phase = workflowPhase();
    const fast = fastApprovalEligible();
    const waiting = hasPendingLock();
    const workflowState = model.workflow_state;
    const productionReady = workflowState === "prova_visuale_approvata";
    const rendering = workflowState === "rendering";
    const qualityAssurance = workflowState === "qa";
    const delivered = workflowState === "consegnato";
    const titles = {
      content: "Revisione di profilo e testi",
      visual: "Controlla la prova visiva",
      production: delivered
        ? "Carosello consegnato"
        : qualityAssurance
          ? "Controlli finali"
          : rendering
            ? "Produzione del carosello"
            : "Pronto per la produzione",
    };
    const copies = {
      content: fast
        ? "La prova tipografica è già definitiva: il prossimo consenso approverà insieme testi e grafica."
        : "Questo è il primo checkpoint: approva profilo e testi per richiedere una prova visiva separata.",
      visual: "Questo è il secondo checkpoint: controlla la resa grafica prima di autorizzare la produzione.",
      production: delivered
        ? "Rendering e controlli sono completati. Trovi i file finali nella chat."
        : qualityAssurance
          ? "Gli artefatti sono pronti e i controlli finali sono in corso."
          : rendering
            ? "Il rendering è stato avviato. Produzione e controlli proseguono nella chat."
            : "I due consensi sono registrati. Il rendering non è ancora iniziato.",
    };
    elements.workflowJourneyTitle.textContent = titles[phase];
    elements.workflowJourneyCopy.textContent = copies[phase];
    const order = ["content", "visual", "production"];
    const currentIndex = order.indexOf(phase);
    for (const step of elements.workflowSteps?.querySelectorAll("[data-workflow-step]") || []) {
      const index = order.indexOf(step.dataset.workflowStep);
      const complete = delivered || index < currentIndex || (phase === "production" && index < 2);
      step.classList.toggle("is-complete", complete);
      step.classList.toggle("is-current", !delivered && index === currentIndex);
      if (!delivered && index === currentIndex) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    }

    let statusLabel = "Ora tocca a te";
    let statusDetail = phase === "visual"
      ? "Esamina la prova; quando sei pronto, approvala oppure riapri le modifiche."
      : "Rivedi il carosello e scegli come proseguire.";
    let status = "review";
    if (submissionError) {
      status = "error";
      statusLabel = "Invio da controllare";
      statusDetail = "La bozza è al sicuro. Segui le indicazioni mostrate per ritentare o recuperarla.";
    } else if (waiting) {
      status = "working";
      statusLabel = foreignFeedbackId ? "Aggiornamento in corso in un’altra scheda" : "Richiesta ricevuta";
      statusDetail = returnUrl
        ? "L’agente sta elaborando la richiesta. Il batch è salvato; puoi tornare alla chat dal pulsante qui sotto."
        : "L’agente sta elaborando la richiesta. Il batch è salvato e la nuova revisione comparirà automaticamente.";
    } else if (phase === "production") {
      status = delivered ? "complete" : productionReady ? "ready" : "working";
      statusLabel = delivered
        ? "Consegna completata"
        : qualityAssurance
          ? "Controlli in corso"
          : rendering
            ? "Produzione in corso"
            : "Pronto per la produzione";
      statusDetail = delivered
        ? returnUrl
          ? "La consegna è completa. Torna alla chat per usare i file finali."
          : "La consegna è completa. Usa i file finali ricevuti nella chat."
        : qualityAssurance
          ? "Gli artefatti sono pronti; il QA finale deve ancora concludersi."
          : rendering
            ? "Il rendering è iniziato; controlli e consegna proseguono nella chat."
            : returnUrl
              ? "L’approvazione è registrata. Torna alla chat per avviare rendering e controlli."
              : "L’approvazione è registrata; rendering e controlli devono ancora iniziare.";
    } else if (fast) {
      status = "ready";
      statusLabel = "Consenso unico disponibile";
      statusDetail = "Il pulsante approverà esplicitamente sia i testi sia la prova grafica definitiva.";
    }
    elements.agentStatusCard.dataset.state = status;
    elements.agentStatusLabel.textContent = statusLabel;
    elements.agentStatusDetail.textContent = statusDetail;
    if (elements.returnChatButton) {
      const canReturn = Boolean(returnUrl && (waiting || phase === "production"));
      elements.returnChatButton.hidden = !canReturn;
      elements.returnChatButton.disabled = !canReturn;
      elements.returnChatButton.setAttribute("aria-hidden", String(!canReturn));
    }
    renderProofMode();
    renderGuidance(phase);
  }

  function syncMobileActions() {
    const pairs = [
      [elements.mobileUndoButton, elements.undoButton],
      [elements.mobileResetButton, elements.resetButton],
      [elements.mobileSendButton, elements.sendButton],
      [elements.mobileApproveButton, elements.approveButton],
    ];
    for (const [mobile, desktop] of pairs) {
      if (!mobile || !desktop) continue;
      mobile.disabled = desktop.disabled;
      mobile.hidden = desktop.hidden;
      mobile.setAttribute("aria-hidden", String(desktop.hidden));
      mobile.setAttribute("aria-disabled", String(desktop.disabled));
    }
  }

  function updateChangeSummary() {
    if (!model) return;
    const count = computeChangeCount();
    const waiting = hasPendingLock();
    const contentAlreadyApproved = model.workflow_state !== "bozza";
    const sendVisible = hasAgentCorrections() || (contentAlreadyApproved && count > 0);
    if (elements.sendButton) {
      elements.sendButton.hidden = !sendVisible;
      elements.sendButton.setAttribute("aria-hidden", String(!sendVisible));
    }
    if (hasStaleBase()) {
      if (elements.resetButton) elements.resetButton.disabled = false;
      if (elements.undoButton) elements.undoButton.disabled = true;
      if (elements.sendButton) elements.sendButton.disabled = true;
      if (elements.approveButton) elements.approveButton.disabled = true;
      syncMobileActions();
      updateApprovalCopy();
      return;
    }
    if (elements.resetButton) elements.resetButton.disabled = count === 0 || waiting;
    if (elements.undoButton) elements.undoButton.disabled = !undoState || waiting;
    if (elements.sendButton) elements.sendButton.disabled = count === 0 || waiting;
    if (elements.approveButton) {
      const approvalComplete = ["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(model.workflow_state);
      elements.approveButton.disabled = waiting
        || approvalComplete
        || !previewReadyForApproval(document.documentElement.dataset);
    }
    const approvedContentHasChanges = contentAlreadyApproved && count > 0;
    const sendLabel = waiting
      ? "Correzioni inviate"
      : approvedContentHasChanges
        ? "Invia correzioni · poi riapprova"
        : "Invia correzioni";
    if (elements.sendButton) elements.sendButton.textContent = sendLabel;
    if (elements.mobileSendButton) elements.mobileSendButton.textContent = sendLabel;
    if (elements.workflowBadge) {
      elements.workflowBadge.textContent = waiting ? "Inviato · in attesa dell’agente" : labelForValue(workflowLabels, model.workflow_state, "Stato non definito");
      elements.workflowBadge.toggleAttribute("aria-busy", waiting);
    }
    elements.editor?.setAttribute("aria-busy", String(waiting));
    syncMobileActions();
    updateApprovalCopy();
  }

  function lockEditing() {
    if (!elements.editor) return;
    elements.editor.classList.add("locked");
    elements.editor.setAttribute("aria-busy", "true");
    for (const node of elements.editor.querySelectorAll("input, textarea, button")) {
      if (!node.matches("[data-pending-control]")) node.disabled = true;
    }
    syncMobileActions();
  }

  function unlockPersistentEditing() {
    // Slide controls are rebuilt on every revision, while these textareas are
    // persistent DOM nodes. Re-enable them after an applied batch; otherwise
    // the disabled state set by lockEditing survives loadSession().
    for (const node of [
      elements.brandNote,
      elements.overallNote,
      ...elements.logoPreference?.querySelectorAll("button") || [],
      ...elements.visualSystemPicker?.querySelectorAll("button") || [],
      ...elements.coverChoice?.querySelectorAll("button") || [],
      elements.compareVisualSystems,
      elements.showAdvancedVisualSystem,
      elements.toggleProofEditing,
    ]) {
      if (node) node.disabled = false;
    }
    if (elements.styleExportButton) elements.styleExportButton.disabled = model?.brand_profile?.profile_type !== "carousel-brand";
  }

  function draftStorageValue() {
    return JSON.stringify({
      base_revision: model.revision,
      base_workflow_state: model.workflow_state || "",
      base_approval_checkpoint: model.approval_checkpoint || "",
      slides: normalizedSlides(draftSlides),
      comments: selectionComments,
      slide_notes: slideNotes,
      brand_note: brandNote,
      overall_note: overallNote,
      logo_mode: logoMode,
      cover_mode: selectedCoverMode,
      visual_style_system: selectedVisualSystem,
      awaiting_feedback_id: awaitingFeedbackId,
      pending_submission: pendingSubmission,
      recovery_submissions: recoverySubmissions,
      recovery_drafts: recoveryDrafts,
      foreign_feedback_id: foreignFeedbackId,
      editable_draft: true,
      saved_at: new Date().toISOString(),
    });
  }

  function flushDraft() {
    if (!model || productionRender) return;
    window.clearTimeout(storageTimer);
    storageTimer = null;
    safeStorageSet(storageKey, draftStorageValue());
  }

  function persistDraft({ immediate = false } = {}) {
    if (!model || productionRender) return;
    updateChangeSummary();
    window.clearTimeout(storageTimer);
    if (immediate) flushDraft();
    else storageTimer = window.setTimeout(flushDraft, 220);
  }

  function exportRecoverySubmissions() {
    loadDedicatedRecoveries();
    if (!recoverySubmissions.length && !recoveryDrafts.length) return;
    const artifact = {
      schema: "carousel-builder-feedback-recovery-export-v1",
      exported_at: new Date().toISOString(),
      current_revision: model?.revision ?? null,
      submissions: clone(recoverySubmissions),
      drafts: clone(recoveryDrafts),
    };
    const blob = new Blob([`${JSON.stringify(artifact, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const revision = recoverySubmissions[0]?.base_revision ?? recoveryDrafts[0]?.base_revision ?? "precedente";
    link.href = url;
    link.download = `carousel-feedback-recovery-rev-${revision}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showToast("Copia delle modifiche scaricata.");
  }

  function removeDraftPreservingRecovery() {
    window.clearTimeout(storageTimer);
    storageTimer = null;
    if ((!recoverySubmissions.length && !recoveryDrafts.length) || !model) {
      safeStorageRemove(storageKey);
      return;
    }
    safeStorageSet(storageKey, JSON.stringify({
      base_revision: model.revision,
      base_workflow_state: model.workflow_state || "",
      base_approval_checkpoint: model.approval_checkpoint || "",
      slides: normalizedSlides(model.slides),
      comments: [],
      slide_notes: {},
      brand_note: "",
      overall_note: "",
      logo_mode: initialLogoMode(),
      cover_mode: modelCoverMode(),
      visual_style_system: modelVisualSystem(),
      awaiting_feedback_id: null,
      pending_submission: null,
      recovery_submissions: recoverySubmissions,
      recovery_drafts: recoveryDrafts,
      foreign_feedback_id: null,
      editable_draft: false,
      saved_at: new Date().toISOString(),
    }));
  }

  function hydrateDraft() {
    baselineSlides = clone(model.slides);
    draftSlides = clone(model.slides);
    selectionComments = [];
    slideNotes = {};
    brandNote = "";
    overallNote = "";
    logoMode = initialLogoMode();
    selectedCoverMode = modelCoverMode();
    undoState = null;
    awaitingFeedbackId = null;
    pendingSubmission = null;
    recoverySubmissions = [];
    recoveryDrafts = [];
    foreignFeedbackId = null;
    submissionError = "";
    staleWorkflowState = null;
    staleApprovalCheckpoint = null;
    validationMode = false;
    activeValidationIssues = [];
    if (productionRender) return;
    try {
      loadDedicatedRecoveries();
      const saved = JSON.parse(safeStorageGet(storageKey) || "null");
      for (const recovery of Array.isArray(saved?.recovery_submissions) ? saved.recovery_submissions : []) addRecoverySubmission(recovery);
      for (const recovery of Array.isArray(saved?.recovery_drafts) ? saved.recovery_drafts : []) addRecoveryDraft(recovery);
      if (isRecoverySubmission(saved?.recovery_submission)) addRecoverySubmission(saved.recovery_submission);
      const sameRevision = Boolean(saved && saved.base_revision === model.revision);
      const sameWorkflow = Boolean(saved && (
        !saved.base_workflow_state
        || saved.base_workflow_state === model.workflow_state
      ));
      const sameCheckpoint = Boolean(saved && (
        !saved.base_approval_checkpoint
        || saved.base_approval_checkpoint === (model.approval_checkpoint || "")
      ));
      const sameBase = sameRevision && sameWorkflow && sameCheckpoint;
      if (saved && !sameBase && saved.editable_draft !== false && Array.isArray(saved.slides)) {
        const reason = !sameRevision ? "base-revision-mismatch" : "base-workflow-mismatch";
        addRecoveryDraft(recoveryDraftFromSaved(saved, reason));
      }
      const savedPending = isPendingSubmission(saved?.pending_submission) ? saved.pending_submission : null;
      const sameFingerprint = Boolean(savedPending && (
        savedPending.action !== "approve"
        || savedPending.payload.render_fingerprint === (model.render_fingerprint || "")
      ));
      if (savedPending && sameBase && sameFingerprint) {
        pendingSubmission = savedPending;
        awaitingFeedbackId = savedPending.feedback_id;
      } else if (savedPending) {
        const reason = !sameRevision
          ? "base-revision-mismatch"
          : !sameWorkflow || !sameCheckpoint
            ? "base-workflow-mismatch"
            : "render-fingerprint-mismatch";
        addRecoverySubmission(recoveryFromPending(savedPending, reason, saved));
        submissionError = `La pagina è stata aggiornata dopo la revisione ${saved.base_revision}. Le modifiche sono al sicuro: scaricane una copia prima di ricaricare.`;
      } else if (sameBase && isFeedbackId(saved?.awaiting_feedback_id)) {
        awaitingFeedbackId = saved.awaiting_feedback_id;
      }
      if (sameBase && typeof saved?.foreign_feedback_id === "string" && saved.foreign_feedback_id) foreignFeedbackId = saved.foreign_feedback_id;
      if (!saved || !sameBase || !Array.isArray(saved.slides)) return;
      const knownIds = new Set(model.slides.map((slide) => slide.id));
      const validSlides = saved.slides.every((slide) => slide && knownIds.has(slide.id) && typeof slide.title === "string" && typeof slide.summary === "string");
      if (!validSlides) return;
      const metadata = new Map(model.slides.map((slide) => [slide.id, slide]));
      draftSlides = saved.slides.map((slide) => ({ ...metadata.get(slide.id), ...slide }));
      pruneStaleEmphasis(draftSlides);
      selectionComments = Array.isArray(saved.comments) ? saved.comments : [];
      slideNotes = saved.slide_notes && typeof saved.slide_notes === "object" ? saved.slide_notes : {};
      brandNote = typeof saved.brand_note === "string" ? saved.brand_note : "";
      overallNote = typeof saved.overall_note === "string" ? saved.overall_note : "";
      const savedLogoMode = saved.logo_mode || saved.logo_preference;
      logoMode = savedLogoMode === "hidden" ? "hidden" : initialLogoMode();
      if (["generated", "provided", "typographic"].includes(saved.cover_mode)) {
        selectedCoverMode = saved.cover_mode;
      }
    } catch (_error) {
      safeStorageRemove(storageKey);
    }
  }

  function fontStack(family, fallback) {
    const safeFamily = String(family || "").replace(/["\\]/g, "").trim();
    return safeFamily ? `"${safeFamily}", ${fallback}` : fallback;
  }

  function italicFontAsset() {
    const assets = previewBrand().font_assets && typeof previewBrand().font_assets === "object" ? previewBrand().font_assets : {};
    const candidates = [assets.italic, assets.emphasis_italic, assets.body_italic, assets.display_italic, assets.serif_italic];
    return candidates.find((asset) => asset?.available === true && asset.family && asset.endpoint) || null;
  }

  function italicFontLabel() {
    return italicFontAsset()?.family || "corsivo reale disponibile";
  }

  function fontAssetKey(asset, descriptors = {}) {
    return `${asset?.family || ""}|${asset?.endpoint || ""}|${descriptors.style || "normal"}|${descriptors.weight || "100 900"}`;
  }

  function hasRealItalicFont() {
    const asset = italicFontAsset();
    return Boolean(asset && loadedFontKeys.has(fontAssetKey(asset, fontAssetDescriptors("italic", "italic"))));
  }

  function loadFontAsset(asset, descriptors) {
    const key = fontAssetKey(asset, descriptors);
    if (!fontLoadCache.has(key)) {
      const pending = (async () => {
        const face = new FontFace(
          asset.family,
          `url("${api(asset.endpoint).replace(/"/g, "%22")}")`,
          descriptors,
        );
        await face.load();
        document.fonts.add(face);
        loadedFontKeys.add(key);
        return asset.family;
      })();
      fontLoadCache.set(key, pending);
      // A rejected load is not a durable cache entry: a fixed/replaced local
      // asset must be retryable on the next preview publication.
      pending.catch(() => {
        if (fontLoadCache.get(key) === pending) fontLoadCache.delete(key);
      });
    }
    return fontLoadCache.get(key);
  }

  function setFontStatus(message, warning = false) {
    if (!elements.fontStatus) return;
    elements.fontStatus.hidden = !message;
    elements.fontStatus.textContent = message || "";
    elements.fontStatus.classList.toggle("is-warning", warning);
    elements.fontStatus.setAttribute("role", "status");
    elements.fontStatus.setAttribute("aria-live", "polite");
  }

  async function configurePreviewTypography(run) {
    const brand = previewBrand();
    const assets = brand.font_assets && typeof brand.font_assets === "object" ? brand.font_assets : {};
    const sansFallback = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const fallbacks = { display: sansFallback, body: sansFallback, serif: "Georgia, 'Times New Roman', serif" };
    const labels = { display: "Titoli", body: "Testi", serif: "Secondario corsivo", italic: "Corsivo" };
    const loaded = {};
    fontAdvisories = [];
    const resolvedItalic = italicFontAsset();
    const italicAvailableBefore = hasRealItalicFont();
    for (const kind of ["display", "body", "serif", "italic"]) {
      const asset = kind === "italic" ? resolvedItalic : assets[kind] || (kind === "body" ? assets.sans : null);
      if (!fontAssetRequiresVerifiedLoad(asset)) {
        const declaredFamily = String(asset?.family || "").trim();
        if (declaredFamily) {
          const message = `${labels[kind]}: ${declaredFamily} non è disponibile; l’anteprima usa un fallback dichiarato.`;
          fontAdvisories.push({ key: `font-${kind}-unavailable`, message });
        }
        continue;
      }
      try {
        if (!asset.family || !asset.endpoint || typeof FontFace === "undefined") {
          throw new Error("metadati o API FontFace non disponibili");
        }
        const style = kind === "serif" || kind === "italic" ? "italic" : "normal";
        loaded[kind] = await loadFontAsset(asset, fontAssetDescriptors(kind, style));
      } catch (_error) {
        if (run !== previewContractRun) return false;
        const message = `${labels[kind]}: ${asset.family || "font dichiarato"} non si è caricato; l’anteprima usa un fallback.`;
        fontAdvisories.push({ key: `font-${kind}-load`, message });
      }
    }
    // Font loads are shared and cannot be cancelled. A superseded publisher may
    // populate the cache, but it must never mutate or rebuild the current DOM.
    if (run !== previewContractRun) return false;
    document.documentElement.style.setProperty("--preview-display", fontStack(loaded.display, fallbacks.display));
    document.documentElement.style.setProperty("--preview-body", fontStack(loaded.body, fallbacks.body));
    document.documentElement.style.setProperty("--preview-sans", fontStack(loaded.body, fallbacks.body));
    document.documentElement.style.setProperty("--preview-serif", fontStack(loaded.serif, fallbacks.serif));
    document.documentElement.style.setProperty("--preview-italic", fontStack(loaded.italic, loaded.serif || fallbacks.serif));
    setFontStatus(
      fontAdvisories.length
        ? `Avviso tipografia — ${fontAdvisories.map((item) => item.message).join(" · ")} Puoi comunque generare.`
        : "",
      fontAdvisories.length > 0,
    );
    if (italicAvailableBefore !== hasRealItalicFont() && elements.slides?.childElementCount) {
      // The publisher awaiting this typography pass will certify the rebuilt DOM.
      renderSlides({ publishContract: false });
    }
    schedulePreviewMeasure();
    return true;
  }

  function typography() {
    const defaultTypography = model?.typography && typeof model.typography === "object" ? model.typography : {};
    const proofTypography = selectedVisualProof()?.typography;
    return proofTypography && typeof proofTypography === "object" ? { ...defaultTypography, ...proofTypography } : defaultTypography;
  }

  function numberValue(value, fallback) {
    return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
  }

  function previewFontBase(slide, field, preview) {
    const type = typography();
    const masterWidth = numberValue(model?.format?.master_width, 1080);
    const previewWidth = preview.clientWidth || 320;
    const factor = previewWidth / masterWidth;
    const isTitle = field === "title";
    const px = slide.kind === "cover"
      ? isTitle
        ? numberValue(type.cover_px, 112)
        : numberValue(type.cover_subtitle_px, 56)
      : isTitle
        ? numberValue(type.section_title_px, 72)
        : numberValue(type.body_px, 64);
    return Math.max(12, px * factor);
  }

  function applyPreviewScale(preview, slide, scale) {
    const title = preview.querySelector(".preview-title");
    const summary = preview.querySelector(".preview-summary");
    const type = typography();
    preview.style.setProperty("--preview-scale", String(scale));
    if (title) {
      title.style.fontSize = `${previewFontBase(slide, "title", preview) * scale}px`;
      title.style.fontWeight = String(numberValue(slide.kind === "cover" ? type.cover_weight : type.section_title_weight, 800));
      title.style.fontFamily = "var(--preview-display)";
    }
    if (summary) {
      summary.style.fontSize = `${previewFontBase(slide, "summary", preview) * scale}px`;
      summary.style.fontWeight = String(numberValue(slide.kind === "cover" ? type.cover_subtitle_weight : type.body_weight, slide.kind === "cover" ? 500 : 620));
      summary.style.lineHeight = String(numberValue(slide.kind === "cover" ? type.cover_subtitle_line_height : type.body_line_height, slide.kind === "cover" ? 1.08 : 1.12));
      summary.style.setProperty("--sentence-gap", `${numberValue(type.sentence_gap_em, 0.6)}em`);
      summary.style.letterSpacing = slide.kind === "cover"
        ? "0em"
        : `${numberValue(Math.abs(type.body_tracking_em), 0.025) * -1}em`;
      const realItalic = slide.kind === "cover" && hasRealItalicFont();
      summary.style.fontFamily = realItalic ? "var(--preview-italic)" : "var(--preview-body)";
      summary.style.fontStyle = realItalic ? "italic" : "normal";
      preview.classList.toggle("has-real-italic", hasRealItalicFont());
    }
  }

  function emphasisFor(slide, field) {
    const legacyPrefix = slide.kind === "cover" && field === "title" ? "cover_title" : field;
    const bold = slide[`${field}_bold`] ?? slide[`${legacyPrefix}_bold`];
    const canonicalItalic = slide[`${field}_italic`] ?? slide[`${legacyPrefix}_italic`];
    const legacyItalic = slide[`${field}_serif`] ?? slide[`${legacyPrefix}_serif`];
    const italic = Array.isArray(canonicalItalic) && canonicalItalic.length ? canonicalItalic : legacyItalic;
    const accent = slide[`${field}_accent`] ?? slide[`${legacyPrefix}_accent`];
    const underline = slide[`${field}_underline`] ?? slide[`${legacyPrefix}_underline`];
    return {
      bold: Array.isArray(bold) ? bold : [],
      italic: Array.isArray(italic) ? italic : [],
      accent: Array.isArray(accent) ? accent : [],
      underline: Array.isArray(underline) ? underline : [],
    };
  }

  function emphasisKey(slide, field, kind) {
    return `${field}_${kind}`;
  }

  function legacyEmphasisKey(slide, field) {
    return `${field}_serif`;
  }

  function emphasisSegments(slide, field, kind) {
    const key = emphasisKey(slide, field, kind);
    const legacy = kind === "italic" ? legacyEmphasisKey(slide, field) : "";
    const canonical = slide[key];
    const value = kind === "italic" && Array.isArray(canonical) && canonical.length === 0
      ? slide[legacy]
      : canonical ?? (legacy ? slide[legacy] : undefined);
    return Array.isArray(value) ? value : [];
  }

  function setEmphasisSegments(slide, field, kind, segments) {
    const key = emphasisKey(slide, field, kind);
    slide[key] = [...segments];
    if (kind === "italic") {
      const legacy = legacyEmphasisKey(slide, field);
      if (legacy !== key) slide[legacy] = [];
    }
  }

  function pruneStaleEmphasis(slides) {
    let dropped = 0;
    for (const slide of slides) {
      for (const field of ["title", "summary"]) {
        const text = typeof slide[field] === "string" ? slide[field] : "";
        for (const kind of ["bold", "italic", "accent", "underline"]) {
          const segments = emphasisSegments(slide, field, kind);
          const kept = segments.filter((segment) => typeof segment === "string" && segment && text.includes(segment));
          if (kept.length === segments.length) continue;
          dropped += segments.length - kept.length;
          setEmphasisSegments(slide, field, kind, kept);
        }
      }
    }
    return dropped;
  }

  function textRanges(text, segment) {
    if (typeof text !== "string" || typeof segment !== "string" || !segment) return [];
    const ranges = [];
    let start = text.indexOf(segment);
    while (start !== -1) {
      ranges.push({ start, end: start + segment.length });
      start = text.indexOf(segment, start + 1);
    }
    return ranges;
  }

  function emphasisWarningsFor(slide, field) {
    const text = typeof slide[field] === "string" ? slide[field] : "";
    const warnings = [];
    const ranges = [];
    const specialKinds = new Set(["italic", "accent", "underline"]);
    for (const kind of ["bold", "italic", "accent", "underline"]) {
      for (const segment of emphasisSegments(slide, field, kind)) {
        const occurrences = textRanges(text, segment);
        if (!occurrences.length) {
          warnings.push({ kind: "ambiguous", message: `La selezione “${segment}” non è più presente nel testo.` });
          continue;
        }
        if (occurrences.length > 1) warnings.push({ kind: "ambiguous", message: `La selezione “${segment}” compare ${occurrences.length} volte: rendila univoca.` });
        for (const range of occurrences) ranges.push({ ...range, kind, segment });
      }
    }
    ranges.sort((a, b) => a.start - b.start || a.end - b.end);
    for (let index = 1; index < ranges.length; index += 1) {
      const previous = ranges[index - 1];
      const current = ranges[index];
      if (current.start < previous.end) {
        const bothSpecial = specialKinds.has(previous.kind) && specialKinds.has(current.kind);
        if (previous.start === current.start && previous.end === current.end) {
          warnings.push({
            kind: bothSpecial ? "secondary" : "overlap",
            message: bothSpecial
              ? `“${current.segment}” ha più trattamenti. Scegline uno: corsivo, sottolineatura oppure evidenziatore.`
              : `“${current.segment}” ha più stili. Mantienine uno solo.`,
          });
        } else {
          warnings.push({
            kind: "overlap",
            message: `I trattamenti su “${previous.segment}” e “${current.segment}” si sovrappongono. Correggi le selezioni oppure mantienine uno solo.`,
          });
        }
      }
    }
    const fieldItalicCount = emphasisSegments(slide, field, "italic").length;
    if (fieldItalicCount && !hasRealItalicFont()) warnings.push({
      kind: "italic",
      message: "Il corsivo selezionato non ha un font reale disponibile.",
    });
    return warnings;
  }

  function renderEmphasizedText(node, text, emphasis) {
    const safeText = typeof text === "string" ? text : "";
    const matches = [];
    for (const [kind, segments] of Object.entries(emphasis)) {
      for (const segment of segments) {
        if (typeof segment !== "string" || !segment) continue;
        let start = safeText.indexOf(segment);
        while (start !== -1) {
          matches.push({ start, end: start + segment.length, kind });
          start = safeText.indexOf(segment, start + segment.length);
        }
      }
    }
    const priority = { italic: 0, bold: 1, underline: 2, accent: 3 };
    matches.sort((a, b) => a.start - b.start || b.end - a.end || priority[a.kind] - priority[b.kind]);
    const accepted = [];
    let cursor = 0;
    for (const match of matches) {
      if (match.start < cursor) continue;
      accepted.push(match);
      cursor = match.end;
    }
    const appendRange = (parent, start, end) => {
      let rangeCursor = start;
      for (const match of accepted) {
        if (match.end <= start || match.start >= end) continue;
        const matchStart = Math.max(start, match.start);
        const matchEnd = Math.min(end, match.end);
        if (matchStart > rangeCursor) parent.append(document.createTextNode(safeText.slice(rangeCursor, matchStart)));
        parent.append(create("span", `preview-emphasis preview-${match.kind}`, safeText.slice(matchStart, matchEnd)));
        rangeCursor = matchEnd;
      }
      if (rangeCursor < end) parent.append(document.createTextNode(safeText.slice(rangeCursor, end)));
    };
    const fragment = document.createDocumentFragment();
    const separateSentences = node.classList.contains("preview-summary") && safeText.includes("\n");
    node.classList.toggle("has-sentence-breaks", separateSentences);
    if (separateSentences) {
      let lineStart = 0;
      for (let index = 0; index <= safeText.length; index += 1) {
        if (index !== safeText.length && safeText[index] !== "\n") continue;
        const sentence = create("span", "preview-sentence");
        appendRange(sentence, lineStart, index);
        fragment.append(sentence);
        lineStart = index + 1;
      }
    } else {
      appendRange(fragment, 0, safeText.length);
    }
    node.replaceChildren(fragment);
  }

  function renderBrand() {
    const brand = previewBrand();
    elements.brandName.textContent = brand.name || "Profilo senza nome";
    renderLogoControls();
    elements.palette.replaceChildren();
    const palette = brand.palette || {};
    const colors = [["Sfondo chiaro", palette.background_light], ["Sfondo scuro", palette.background_dark], ["Testo", palette.text_on_light], ["Accento", palette.accent]];
    for (const [name, value] of colors) {
      const swatch = create("span", "swatch");
      const color = safeColor(value, "#d0d5dd");
      swatch.style.backgroundColor = color;
      swatch.title = `${name}: ${value || "non dichiarato"}`;
      swatch.setAttribute("role", "img");
      swatch.setAttribute("aria-label", `${name}: ${value || "colore non dichiarato"}`);
      elements.palette.append(swatch);
    }
    if (elements.brandTypography) {
      elements.brandTypography.replaceChildren();
      const display = brand.display || brand.font_assets?.display?.family || brand.sans || "Non dichiarato";
      const body = brand.body || brand.font_assets?.body?.family || brand.sans || "Non dichiarato";
      const rows = display === body
        ? [["Titoli e testi", display]]
        : [["Titoli", display], ["Testi", body]];
      const italic = italicFontAsset()?.family;
      if (italic && italic !== display && italic !== body) rows.push(["Corsivo", italic]);
      for (const [role, family] of rows) {
        elements.brandTypography.append(
          create("dt", "brand-typography-role", role),
          create("dd", "brand-typography-family", family),
        );
      }
    }
    elements.brandNote.value = brandNote;
    if (elements.styleExportButton) {
      elements.styleExportButton.disabled = model?.brand_profile?.profile_type !== "carousel-brand";
    }
  }

  function exportedStyleProfile() {
    const source = model?.brand_profile;
    if (!source || typeof source !== "object" || source.profile_type !== "carousel-brand") return null;
    const profile = clone(source);
    profile.visual_signature = {
      ...(profile.visual_signature || {}),
      style_system: selectedVisualSystem,
    };
    return profile;
  }

  function styleExportFilename(profile) {
    const stem = String(profile?.name || "stile-carousel")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase() || "stile-carousel";
    return `${stem}-carousel-brand.json`;
  }

  function exportStyleProfile() {
    const profile = exportedStyleProfile();
    if (!profile) return showToast("Lo stile non è ancora pronto per il salvataggio.", true);
    const blob = new Blob([`${JSON.stringify(profile, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = styleExportFilename(profile);
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showToast("Stile JSON salvato. Allegalo alla prossima richiesta per riutilizzarlo.");
  }

  function renderLogoControls() {
    if (!elements.logoPreference) return;
    for (const button of elements.logoPreference.querySelectorAll("[data-logo-mode]")) {
      const selected = button.dataset.logoMode === logoMode;
      button.setAttribute("aria-checked", String(selected));
      button.tabIndex = selected ? 0 : -1;
      button.classList.toggle("is-selected", selected);
    }
    const automatic = logoMode === "auto";
    if (elements.logoPreferenceStatus) elements.logoPreferenceStatus.textContent = automatic ? "attivo" : "disattivato";
    if (elements.logoVariants) {
      elements.logoVariants.replaceChildren();
      const labels = { on_light: "Su fondo chiaro", on_dark: "Su fondo scuro" };
      for (const role of ["on_light", "on_dark"]) {
        const metadata = logoMetadata(role);
        const card = create("article", `logo-variant logo-variant-${role}`);
        const heading = create("div", "logo-variant-heading");
        heading.append(create("strong", "", labels[role]), create("span", metadata.available ? "asset-status is-ready" : "asset-status", metadata.available ? "Disponibile" : metadata.declared ? "Dichiarata, preview assente" : "Manca"));
        const stage = create("div", "logo-variant-stage");
        if (metadata.available && metadata.endpoint) {
          const image = document.createElement("img");
          image.src = api(metadata.endpoint);
          image.alt = `${labels[role]}: logo ${previewBrand().name || "brand"}`;
          stage.append(image);
        } else {
          stage.append(create("span", "logo-variant-placeholder", metadata.declared ? "Anteprima non disponibile" : "Nessuna variante"));
        }
        card.append(heading, stage);
        elements.logoVariants.append(card);
      }
    }
    const warning = logoAvailabilityWarning();
    if (elements.logoWarning) {
      elements.logoWarning.hidden = !warning;
      elements.logoWarning.textContent = warning;
    }
  }

  function setLogoMode(value, { focus = false } = {}) {
    if (value !== "auto" && value !== "hidden") return;
    if (logoMode === value) {
      if (focus) elements.logoPreference?.querySelector(`[data-logo-mode="${value}"]`)?.focus();
      return;
    }
    recordUndo("modalità logo");
    logoMode = value;
    renderLogoControls();
    renderSlides();
    persistDraft();
    if (focus) elements.logoPreference?.querySelector(`[data-logo-mode="${value}"]`)?.focus({ preventScroll: true });
  }

  function renderFieldWarning(node, slide, field) {
    const warnings = emphasisWarningsFor(slide, field);
    node.hidden = !warnings.length;
    node.textContent = warnings.map((warning) => warning.message).join(" ");
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
  }

  function makeField(slide, field, label, multiline, onPreview) {
    const group = create("div", "field-group");
    const heading = create("div", "field-heading");
    const fieldId = `field-${slide.id}-${field}`;
    const fieldLabel = create("label", "field-label", label);
    fieldLabel.htmlFor = fieldId;
    heading.append(fieldLabel);
    const tools = create("div", "field-tools");
    const count = create("span", "char-count");
    count.dataset.countFor = `${slide.id}:${field}`;
    updateCharacterCount(count, slide, field);
    const selectionToolbar = create("div", "selection-toolbar");
    selectionToolbar.setAttribute("aria-label", "Strumenti di enfasi della selezione");
    const makeFormatButton = (kind, text, label) => {
      const button = create("button", `format-button format-${kind}`, text);
      button.type = "button";
      button.title = label;
      button.setAttribute("aria-label", label);
      button.setAttribute("aria-pressed", "false");
      button.disabled = true;
      return button;
    };
    const boldButton = makeFormatButton("bold", "B", "Applica o rimuovi il grassetto dalla selezione");
    const italicButton = makeFormatButton("italic", "I", `Applica o rimuovi il corsivo ${italicFontLabel()} dalla selezione`);
    const underlineButton = makeFormatButton("underline", "U", "Applica o rimuovi la sottolineatura dalla selezione");
    const accentButton = makeFormatButton("accent", "A", "Applica o rimuovi l’evidenziatore adattivo del brand dalla selezione");
    const commentButton = create("button", "comment-selection", "Commenta");
    commentButton.type = "button";
    commentButton.setAttribute("aria-label", "Commenta la selezione");
    commentButton.disabled = true;
    selectionToolbar.append(boldButton, italicButton, underlineButton, accentButton, commentButton);
    tools.append(count, selectionToolbar);
    heading.append(tools);
    group.append(heading);
    const input = document.createElement(multiline ? "textarea" : "input");
    input.id = fieldId;
    input.value = slide[field];
    input.dataset.slideId = slide.id;
    input.dataset.field = field;
    if (multiline) input.rows = slide.kind === "cover" ? 3 : field === "summary" ? 6 : 3;
    else input.type = "text";
    const warning = create("p", "inline-warning emphasis-warning");
    warning.hidden = true;
    const appliedStyles = create("section", "applied-styles");
    appliedStyles.setAttribute("aria-label", "Formato applicato a questo testo");
    const appliedStylesHeading = create("div", "applied-styles-heading");
    appliedStylesHeading.append(
      create("span", "applied-styles-title", "Formato nel testo"),
      create("span", "applied-styles-hint", "Clicca una voce per rimuoverla"),
    );
    const appliedStylesList = create("div", "applied-styles-list");
    appliedStyles.append(appliedStylesHeading, appliedStylesList);
    const styleLabels = {
      bold: "Grassetto",
      italic: "Corsivo",
      underline: "Sottolineato",
      accent: "Evidenziato",
    };
    const styleMarks = { bold: "B", italic: "I", underline: "U", accent: "A" };
    const selectionState = (kind, start, end) => {
      let containing = "";
      let overlapping = "";
      for (const segment of emphasisSegments(slide, field, kind)) {
        for (const range of textRanges(input.value, segment)) {
          const overlaps = start < range.end && range.start < end;
          if (!overlaps) continue;
          if (!overlapping) overlapping = segment;
          if (start >= range.start && end <= range.end && !containing) containing = segment;
        }
      }
      return { containing, overlapping };
    };
    const firstStyleOverlap = (start, end) => {
      for (const kind of ["bold", "italic", "underline", "accent"]) {
        const state = selectionState(kind, start, end);
        if (state.overlapping) return { kind, segment: state.overlapping };
      }
      return null;
    };
    const renderAppliedStyles = () => {
      appliedStylesList.replaceChildren();
      const entries = [];
      for (const kind of ["bold", "italic", "underline", "accent"]) {
        for (const segment of emphasisSegments(slide, field, kind)) entries.push({ kind, segment });
      }
      appliedStyles.hidden = entries.length === 0;
      for (const { kind, segment } of entries) {
        const remove = create("button", `applied-style-chip applied-style-${kind}`);
        remove.type = "button";
        remove.disabled = hasPendingLock();
        remove.setAttribute("aria-label", `Rimuovi ${styleLabels[kind].toLowerCase()} da “${segment}”`);
        remove.title = `Rimuovi ${styleLabels[kind].toLowerCase()} da “${segment}”`;
        remove.append(
          create("span", "applied-style-kind", styleMarks[kind]),
          create("span", "applied-style-quote", `“${segment}”`),
          create("span", "applied-style-remove", "×"),
        );
        remove.addEventListener("click", () => {
          recordUndo("rimozione enfasi tipografica");
          setEmphasisSegments(
            slide,
            field,
            kind,
            emphasisSegments(slide, field, kind).filter((value) => value !== segment),
          );
          onPreview(slide[field]);
          refreshEmphasisUi();
          renderAppliedStyles();
          renderFieldWarning(warning, slide, field);
          persistDraft();
          input.focus();
          schedulePreviewMeasure(slide.id);
        });
        appliedStylesList.append(remove);
      }
    };
    const refreshEmphasisUi = () => {
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      const quote = end > start ? input.value.slice(start, end) : "";
      const hasSelection = Boolean(quote) && !hasPendingLock();
      const setButton = (button, kind, available = true) => {
        const state = hasSelection ? selectionState(kind, start, end) : { containing: "", overlapping: "" };
        const active = Boolean(state.containing);
        const mixed = Boolean(!active && state.overlapping);
        button.disabled = !hasSelection || (!available && !active);
        button.setAttribute("aria-pressed", active ? "true" : mixed ? "mixed" : "false");
        button.classList.toggle("is-mixed", mixed);
        button.dataset.appliedSegment = state.containing;
      };
      setButton(boldButton, "bold");
      setButton(italicButton, "italic", hasRealItalicFont());
      setButton(underlineButton, "underline");
      setButton(accentButton, "accent");
      const italicActive = Boolean(italicButton.dataset.appliedSegment);
      italicButton.title = !hasRealItalicFont() && italicActive
        ? "Rimuovi il corsivo non disponibile dalla selezione"
        : `Applica o rimuovi il corsivo ${italicFontLabel()} dalla selezione${hasRealItalicFont() ? "" : " (non disponibile)"}`;
      italicButton.setAttribute("aria-label", italicButton.title);
      commentButton.disabled = !hasSelection;
    };
    const refreshSelection = () => {
      refreshEmphasisUi();
    };
    input.addEventListener("select", refreshSelection);
    input.addEventListener("keyup", refreshSelection);
    input.addEventListener("mouseup", refreshSelection);
    input.addEventListener("focus", () => { input._undoCaptured = false; });
    input.addEventListener("blur", () => { input._undoCaptured = false; });
    input.addEventListener("input", () => {
      if (!input._undoCaptured) {
        recordUndo("modifica testo");
        input._undoCaptured = true;
      }
      slide[field] = input.value;
      pruneStaleEmphasis([slide]);
      refreshCharacterCounts();
      onPreview(input.value);
      refreshSelection();
      renderAppliedStyles();
      renderFieldWarning(warning, slide, field);
      persistDraft();
      schedulePreviewMeasure(slide.id);
    });
    const toggleSelectionEmphasis = (kind) => {
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      if (end <= start) return;
      const quote = input.value.slice(start, end);
      const segments = emphasisSegments(slide, field, kind).slice();
      const state = selectionState(kind, start, end);
      const removableSegment = state.containing;
      if (kind === "italic" && !hasRealItalicFont() && !removableSegment) return;
      if (!removableSegment) {
        const conflict = firstStyleOverlap(start, end);
        if (conflict) {
          showToast(`La selezione include “${conflict.segment}”, già ${styleLabels[conflict.kind].toLowerCase()}. Rimuovi prima il formato dalla riga sotto il testo.`, true);
          input.focus();
          input.setSelectionRange(start, end);
          return;
        }
      }
      recordUndo("enfasi tipografica");
      if (removableSegment) {
        const existingIndex = segments.indexOf(removableSegment);
        if (existingIndex >= 0) segments.splice(existingIndex, 1);
      } else {
        segments.push(quote);
      }
      setEmphasisSegments(slide, field, kind, segments);
      onPreview(slide[field]);
      refreshEmphasisUi();
      renderAppliedStyles();
      renderFieldWarning(warning, slide, field);
      persistDraft();
      input.focus();
      input.setSelectionRange(start, end);
      schedulePreviewMeasure(slide.id);
    };
    boldButton.addEventListener("mousedown", (event) => event.preventDefault());
    italicButton.addEventListener("mousedown", (event) => event.preventDefault());
    underlineButton.addEventListener("mousedown", (event) => event.preventDefault());
    accentButton.addEventListener("mousedown", (event) => event.preventDefault());
    commentButton.addEventListener("mousedown", (event) => event.preventDefault());
    boldButton.addEventListener("click", () => toggleSelectionEmphasis("bold"));
    italicButton.addEventListener("click", () => toggleSelectionEmphasis("italic"));
    underlineButton.addEventListener("click", () => toggleSelectionEmphasis("underline"));
    accentButton.addEventListener("click", () => toggleSelectionEmphasis("accent"));
    input.addEventListener("keydown", (event) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      const key = event.key.toLowerCase();
      if (!["b", "i", "u", "h"].includes(key) || (key === "h" && !event.shiftKey)) return;
      event.preventDefault();
      const shortcutKinds = { b: "bold", i: "italic", u: "underline", h: "accent" };
      toggleSelectionEmphasis(shortcutKinds[key]);
    });
    commentButton.addEventListener("click", () => {
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      if (end <= start || !elements.dialog) return;
      pendingSelection = { slide_id: slide.id, field, quote: input.value.slice(start, end), start, end, focusTarget: input };
      elements.commentQuote.textContent = pendingSelection.quote;
      elements.commentFeedback.value = "";
      elements.dialog.showModal();
      elements.commentFeedback.focus();
    });
    group.append(input, appliedStyles, warning);
    refreshEmphasisUi();
    renderAppliedStyles();
    renderFieldWarning(warning, slide, field);
    return group;
  }

  function itemPositions() {
    return draftSlides.map((slide, index) => ({ slide, index })).filter(({ slide }) => slide.kind === "item");
  }

  function editorialLimit(slide, field) {
    if (slide.kind !== "item" || field !== "summary") return null;
    return slide.title.trim() ? 180 : 320;
  }

  function updateCharacterCount(node, slide, field) {
    const length = slide[field].length;
    const limit = editorialLimit(slide, field);
    node.textContent = limit ? `${length}/${limit} caratteri` : `${length} caratteri`;
    node.classList.toggle("is-warning", Boolean(limit && length > limit));
    node.setAttribute(
      "aria-label",
      limit ? `${length} caratteri su una soglia editoriale di ${limit}` : `${length} caratteri`,
    );
  }

  function refreshCharacterCounts() {
    for (const node of elements.slides?.querySelectorAll("[data-count-for]") || []) {
      const separator = node.dataset.countFor.lastIndexOf(":");
      const slideId = node.dataset.countFor.slice(0, separator);
      const field = node.dataset.countFor.slice(separator + 1);
      const slide = draftSlides.find((candidate) => candidate.id === slideId);
      if (slide && (field === "title" || field === "summary")) updateCharacterCount(node, slide, field);
    }
  }

  function moveItem(slideId, direction) {
    const positions = itemPositions();
    const itemPosition = positions.findIndex(({ slide }) => slide.id === slideId);
    const targetPosition = itemPosition + direction;
    if (itemPosition < 0 || targetPosition < 0 || targetPosition >= positions.length) return;
    recordUndo("ordine delle slide");
    const from = positions[itemPosition].index;
    const to = positions[targetPosition].index;
    [draftSlides[from], draftSlides[to]] = [draftSlides[to], draftSlides[from]];
    renderSlides();
    persistDraft();
  }

  function clearDropTargets() {
    for (const row of elements.slides?.querySelectorAll(".slide-row") || []) {
      row.classList.remove("drop-before", "drop-after");
    }
  }

  function updateDirectDragTarget(clientX, clientY) {
    if (!pointerDrag) return;
    clearDropTargets();
    const targetRow = document.elementFromPoint(clientX, clientY)?.closest(".slide-row");
    const target = draftSlides.find((candidate) => candidate.id === targetRow?.dataset.slideId);
    if (!targetRow || target?.kind !== "item" || target.id === pointerDrag.slideId) {
      pointerDrag.targetId = null;
      return;
    }
    const placeAfter = clientY >= targetRow.getBoundingClientRect().top + targetRow.offsetHeight / 2;
    pointerDrag.targetId = target.id;
    pointerDrag.placeAfter = placeAfter;
    targetRow.classList.add(placeAfter ? "drop-after" : "drop-before");
  }

  function finishDirectDrag(cancelled = false) {
    if (!pointerDrag) return;
    const { slideId, targetId, placeAfter } = pointerDrag;
    pointerDrag = null;
    elements.slides?.querySelector(`[data-slide-id="${selectorValue(slideId)}"]`)?.classList.remove("is-dragging");
    clearDropTargets();
    if (!cancelled && targetId) moveItemRelative(slideId, targetId, placeAfter);
  }

  function moveItemRelative(draggedId, targetId, placeAfter) {
    if (draggedId === targetId) return;
    const dragged = draftSlides.find((slide) => slide.id === draggedId);
    const target = draftSlides.find((slide) => slide.id === targetId);
    if (dragged?.kind !== "item" || target?.kind !== "item") return;
    recordUndo("ordine delle slide");
    const reordered = draftSlides.filter((slide) => slide.id !== draggedId);
    const targetIndex = reordered.findIndex((slide) => slide.id === targetId);
    reordered.splice(targetIndex + (placeAfter ? 1 : 0), 0, dragged);
    draftSlides = reordered;
    currentSlideId = draggedId;
    renderSlides();
    persistDraft();
    showToast("Sequenza aggiornata.");
  }

  function annotationCountForSlide(slideId) {
    return selectionComments.filter((comment) => comment.slide_id === slideId).length + (slideNotes[slideId]?.trim() ? 1 : 0);
  }

  function deleteItem(slideId) {
    if (itemPositions().length <= 1) {
      showToast("Deve restare almeno una slide interna.", true);
      return;
    }
    const index = draftSlides.findIndex((slide) => slide.id === slideId);
    const annotations = annotationCountForSlide(slideId);
    const suffix = annotations === 1 ? "Sarà rimossa 1 annotazione." : `Saranno rimosse ${annotations} annotazioni.`;
    if (!window.confirm(`Eliminare ${displayLabel(draftSlides[index], index)} dalla sequenza? ${suffix}`)) return;
    recordUndo("eliminazione slide");
    draftSlides = draftSlides.filter((slide) => slide.id !== slideId);
    selectionComments = selectionComments.filter((comment) => comment.slide_id !== slideId);
    delete slideNotes[slideId];
    viewedSlideIds.delete(slideId);
    persistViewState();
    renderSlides();
    renderComments();
    persistDraft();
  }

  function previewColors(index, kind) {
    const palette = previewBrand().palette || {};
    const useDark = kind === "cover" || kind === "outro" || index % 2 === 0;
    const accent = safeColor(palette.accent || palette.primary || palette.accent_primary, "#febd08");
    const backgroundDark = safeColor(palette.background_dark, "#172033");
    const backgroundLight = safeColor(palette.background_light, "#f5f1e8");
    const textOnDark = safeColor(palette.text_on_dark, "#ffffff");
    const textOnLight = safeColor(palette.text_on_light, "#172033");
    const accentUsesLightText = contrastRatio(accent, textOnDark) >= contrastRatio(accent, textOnLight);
    const accentText = accentUsesLightText ? textOnDark : textOnLight;
    const accentLogoRole = accentUsesLightText ? "on_dark" : "on_light";
    const shared = { accent, backgroundDark, backgroundLight, textOnDark, textOnLight, accentText, accentLogoRole, surface: useDark ? "dark" : "light" };
    const resolved = useDark
      ? { bg: backgroundDark, text: textOnDark, ...shared }
      : { bg: backgroundLight, text: textOnLight, ...shared };
    return { ...resolved, highlight: adaptiveHighlightBackground(resolved) };
  }

  function schemaWarning(slide) {
    if (slide.kind !== "item") return "";
    const limit = slide.title.trim() ? 180 : 320;
    const count = slide.summary.length;
    return count > limit ? `Testo oltre il limite editoriale: ${count}/${limit} caratteri. Riduci o dividi la slide.` : "";
  }

  function updateFitNotice(slideId, notice) {
    const node = elements.slides?.querySelector(`[data-fit-warning-for="${selectorValue(slideId)}"]`);
    if (!node) return;
    const parts = [notice.schema, notice.overflow, ...(notice.emphasis || []).map((warning) => warning.message)].filter(Boolean);
    node.hidden = parts.length === 0;
    node.textContent = parts.join(" ");
    const assertive = Boolean(notice.overflow);
    node.setAttribute("role", assertive ? "alert" : "status");
    node.setAttribute("aria-live", assertive ? "assertive" : "polite");
  }

  function applyViewedClasses() {
    if (!elements.slides) return;
    for (const row of elements.slides.querySelectorAll(".slide-row")) {
      const viewed = viewedSlideIds.has(row.dataset.slideId);
      row.classList.toggle("is-viewed", viewed);
    }
  }

  function markSlideSeen(slideId) {
    if (!slideId || viewedSlideIds.has(slideId)) return;
    viewedSlideIds.add(slideId);
    persistViewState();
    applyViewedClasses();
    renderSequenceNav();
    updateApprovalCopy();
  }

  function commentsForSlide(slideId) {
    return selectionComments.some((comment) => comment.slide_id === slideId) || Boolean(slideNotes[slideId]?.trim());
  }

  function jumpToSlide(slideId) {
    const row = elements.slides?.querySelector(`[data-slide-id="${selectorValue(slideId)}"]`);
    if (!row) return;
    currentSlideId = slideId;
    row.scrollIntoView({ behavior: "smooth", block: "start" });
    renderSequenceNav();
  }

  function renderSequenceNav() {
    if (!elements.sequenceNav) return;
    const focusSnapshot = captureFocus(elements.sequenceNav);
    elements.sequenceNav.replaceChildren();
    elements.sequenceNav.setAttribute("aria-label", "Percorso delle slide");
    const total = draftSlides.length;
    const progress = create("p", "sequence-progress", `Viste ${viewedSlideIds.size} di ${total} slide`);
    progress.setAttribute("role", "status");
    elements.sequenceNav.append(progress);
    const list = create("div", "sequence-nav-list");
    draftSlides.forEach((slide, index) => {
      const label = displayLabel(slide, index);
      const button = create("button", "sequence-nav-item", label);
      button.type = "button";
      button.dataset.sequenceSlide = slide.id;
      if (currentSlideId === slide.id) button.setAttribute("aria-current", "step");
      const warning = fitWarnings.get(slide.id);
      const seen = viewedSlideIds.has(slide.id);
      const commented = commentsForSlide(slide.id);
      button.classList.toggle("is-viewed", seen);
      button.classList.toggle("has-warning", Boolean(warning?.schema || warning?.overflow || warning?.emphasis?.length));
      button.classList.toggle("has-comments", commented);
      button.setAttribute("aria-label", `${label}${seen ? ", vista" : ", non ancora vista"}${commented ? ", con commenti" : ""}${warning?.schema || warning?.overflow || warning?.emphasis?.length ? ", richiede revisione" : ""}`);
      button.addEventListener("click", () => jumpToSlide(slide.id));
      list.append(button);
    });
    elements.sequenceNav.append(list);
    restoreFocus(focusSnapshot, elements.sequenceNav);
  }

  function setupObserver() {
    observer?.disconnect();
    if (!elements.slides || typeof IntersectionObserver === "undefined") return;
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting || entry.intersectionRatio < 0.5) continue;
        currentSlideId = entry.target.closest(".slide-row")?.dataset.slideId || "";
        markSlideSeen(currentSlideId);
      }
    }, { threshold: [0.5] });
    for (const preview of elements.slides.querySelectorAll(".slide-row > .slide-preview")) {
      observer.observe(preview);
    }
  }

  function measurePreviews(slideIds = null) {
    if (!elements.slides) return;
    const minScale = Math.max(0.92, Math.min(1, numberValue(typography().min_auto_scale, 0.92)));
    for (const row of elements.slides.querySelectorAll(".slide-row")) {
      if (slideIds && !slideIds.has(row.dataset.slideId)) continue;
      const slide = draftSlides.find((candidate) => candidate.id === row.dataset.slideId);
      const preview = row.querySelector(".slide-preview");
      const copy = row.querySelector(".preview-copy");
      if (!slide || !preview || !copy) continue;
      let scale = 1;
      applyPreviewScale(preview, slide, scale);
      const style = window.getComputedStyle(preview);
      const copyFits = () => {
        const previewBounds = preview.getBoundingClientRect();
        const copyBounds = copy.getBoundingClientRect();
        const brand = preview.querySelector(".preview-brand");
        const brandBounds = brand && !brand.hidden ? brand.getBoundingClientRect() : null;
        const topLimit = previewBounds.top + parseFloat(style.paddingTop);
        const bottomLimit = brandBounds
          ? brandBounds.top - 4
          : previewBounds.bottom - parseFloat(style.paddingBottom);
        return copyBounds.top >= topLimit - 1
          && copyBounds.bottom <= bottomLimit + 1
          && copy.scrollWidth <= copy.clientWidth + 1;
      };
      while (!copyFits() && scale > minScale) {
        scale = Math.max(minScale, Number((scale - 0.01).toFixed(2)));
        applyPreviewScale(preview, slide, scale);
      }
      const overflow = !copyFits();
      const notice = {
        schema: schemaWarning(slide),
        overflow: overflow ? "Testo ancora troppo denso nell’anteprima dopo la riduzione massima dell’8%. Riduci o dividi il testo." : "",
        emphasis: ["title", "summary"].flatMap((field) => emphasisWarningsFor(slide, field).map((warning) => ({ field, ...warning }))),
      };
      fitWarnings.set(slide.id, notice);
      updateFitNotice(slide.id, notice);
      preview.toggleAttribute("data-fit-warning", Boolean(notice.schema || notice.overflow || notice.emphasis.length));
    }
    renderSequenceNav();
    if (validationMode) refreshApprovalValidation();
  }

  function invalidatePreviewContract({ cancelPending = true } = {}) {
    if (cancelPending) previewContractRun += 1;
    delete document.documentElement.dataset.previewReady;
    delete document.documentElement.dataset.productionReady;
    delete document.documentElement.dataset.productionError;
    delete window.carouselBuilderPreview;
    if (elements.approveButton) elements.approveButton.disabled = true;
    syncMobileActions();
  }

  function renderSlides({ publishContract = true } = {}) {
    if (!elements.slides) return;
    invalidatePreviewContract({ cancelPending: publishContract });
    const focusSnapshot = captureFocus(elements.slides);
    fitWarnings.clear();
    elements.slides.replaceChildren();
    elements.slides.dataset.visualSystem = selectedVisualSystem;
    const items = itemPositions();
    draftSlides.forEach((slide, index) => {
      const visibleLabel = displayLabel(slide, index);
      const row = create("article", "slide-row");
      row.dataset.slideId = slide.id;
      const preview = create("div", "slide-preview");
      preview.dataset.label = visibleLabel;
      const colors = previewColors(index, slide.kind);
      preview.style.setProperty("--preview-bg", colors.bg);
      preview.style.setProperty("--preview-text", colors.text);
      preview.style.setProperty("--preview-accent", colors.accent);
      preview.style.setProperty("--preview-highlight", colors.highlight);
      preview.style.setProperty("--preview-highlight-text", colors.text);
      preview.style.setProperty("--preview-dark-bg", colors.backgroundDark);
      preview.style.setProperty("--preview-light-bg", colors.backgroundLight);
      preview.style.setProperty("--preview-dark-text", colors.textOnDark);
      preview.style.setProperty("--preview-light-text", colors.textOnLight);
      preview.style.setProperty("--preview-accent-text", colors.accentText);
      preview.dataset.kind = slide.kind;
      preview.dataset.surface = colors.surface;
      preview.dataset.constellationPosition = index % 2 === 0 ? "high" : "low";
      preview.dataset.productionSource = "approved-preview";
      preview.classList.add(`visual-system-${selectedVisualSystem}`);
      preview.classList.toggle("has-real-italic", hasRealItalicFont());
      const coverVisual = selectedVisualProof()?.cover_visual || model.cover_visual;
      let coverMedia = null;
      if (slide.kind === "cover" && resolvedCoverMode() !== "typographic") {
        preview.classList.add("cover-split");
        if (coverVisual?.available && coverVisual.endpoint) {
          preview.classList.add("has-cover-image");
          coverMedia = document.createElement("img");
          coverMedia.className = "preview-cover-media";
          coverMedia.src = api(coverVisual.endpoint);
          coverMedia.alt = "";
          coverMedia.setAttribute("aria-hidden", "true");
          coverMedia.style.objectPosition = coverVisual.position || "50% 50%";
        } else {
          preview.classList.add("cover-visual-planned");
          coverMedia = create("div", "preview-cover-placeholder", "Visuale verticale dopo l’approvazione dei testi");
          coverMedia.setAttribute("aria-hidden", "true");
        }
      }
      const previewCopy = create("div", "preview-copy");
      const previewTitle = create("h3", "preview-title");
      const previewSummary = create("p", "preview-summary");
      renderEmphasizedText(previewTitle, slide.title, emphasisFor(slide, "title"));
      renderEmphasizedText(previewSummary, slide.summary, emphasisFor(slide, "summary"));
      if (slide.kind === "cover") {
        previewSummary.classList.add("preview-cover-subtitle");
        previewSummary.hidden = !slide.summary.trim();
      }
      if (slide.kind === "item" && model.sequence_mode === "narrative" && !slide.title.trim()) previewTitle.hidden = true;
      previewCopy.append(previewTitle, previewSummary);
      const pageCurrent = String(index + 1).padStart(2, "0");
      const pageTotal = String(draftSlides.length).padStart(2, "0");
      const pageNumber = create("span", "preview-page", `${pageCurrent} / ${pageTotal}`);
      pageNumber.setAttribute("aria-label", `Pagina ${index + 1} di ${draftSlides.length}`);
      const constellation = create("div", "preview-constellation");
      constellation.setAttribute("aria-hidden", "true");
      if (slide.kind !== "cover") {
        for (const role of ["primary", "core", "ring", "moon", "satellite"]) {
          constellation.append(create("span", `preview-sphere preview-sphere-${role}`));
        }
      }
      const previewBrandNode = create("div", "preview-brand");
      const brand = previewBrand();
      const signature = String(brand.signature || "").trim();
      const website = String(brand.website || "").trim();
      const logoRole = logoRoleForSlide(slide, index);
      const logo = brand.logos?.[logoRole];
      const hasLogo = logo?.available === true && typeof logo.endpoint === "string" && logo.endpoint;
      if (logoMode === "auto" && hasLogo) {
        const image = document.createElement("img");
        image.className = "preview-logo";
        image.src = api(logo.endpoint);
        image.alt = brand.name ? `Logo ${brand.name}` : "Logo del brand";
        previewBrandNode.append(image);
      } else if (signature) previewBrandNode.append(create("span", "preview-signature", signature));
      if (website) previewBrandNode.append(create("span", "preview-website", website));
      previewBrandNode.hidden = logoMode === "hidden" ? !signature && !website : !hasLogo && !signature && !website;
      if (slide.kind !== "cover") preview.append(constellation);
      if (coverMedia) preview.append(coverMedia);
      preview.append(pageNumber, previewCopy, previewBrandNode);
      const form = create("div", "slide-form");
      const toolbar = create("div", "slide-toolbar");
      const identity = create("div", "slide-identity");
      identity.append(create("span", "slide-number", String(index + 1)));
      identity.append(create("span", "slide-name", visibleLabel));
      toolbar.append(identity);
      const toolbarActions = create("div", "toolbar-actions");
      if (slide.kind === "item") {
        const position = items.findIndex(({ slide: item }) => item.id === slide.id);
        const drag = createIconButton("icon-button drag-handle", "grip", "Trascina per riordinare", `Trascina ${visibleLabel} per riordinarla`);
        drag.dataset.action = "drag";
        drag.addEventListener("pointerdown", (event) => {
          if (event.button !== 0 || hasPendingLock()) return;
          event.preventDefault();
          pointerDrag = { slideId: slide.id, pointerId: event.pointerId, targetId: null, placeAfter: false };
          row.classList.add("is-dragging");
        });
        const up = createIconButton("icon-button", "up", "Sposta in alto", `Sposta ${visibleLabel} in alto`);
        up.dataset.action = "move-up";
        up.disabled = position === 0 || hasPendingLock();
        up.addEventListener("click", () => moveItem(slide.id, -1));
        const down = createIconButton("icon-button", "down", "Sposta in basso", `Sposta ${visibleLabel} in basso`);
        down.dataset.action = "move-down";
        down.disabled = position === items.length - 1 || hasPendingLock();
        down.addEventListener("click", () => moveItem(slide.id, 1));
        const remove = createIconButton("icon-button danger", "close", "Elimina slide", `Elimina ${visibleLabel}`);
        remove.dataset.action = "delete";
        remove.disabled = items.length <= 1 || hasPendingLock();
        remove.addEventListener("click", () => deleteItem(slide.id));
        toolbarActions.append(drag, up, down, remove);
      }
      toolbar.append(toolbarActions);
      form.append(toolbar);
      const notice = create("p", "fit-warning");
      notice.dataset.fitWarningFor = slide.id;
      notice.hidden = true;
      form.append(notice);
      if (slide.kind === "cover") {
        const copyApproved = model.workflow_state === "testi_approvati";
        const visualApproved = ["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(model.workflow_state);
        const delivered = model.workflow_state === "consegnato";
        const coverMode = resolvedCoverMode();
        const coverAvailable = model?.cover_visual?.available === true;
        const proofReady = copyApproved || visualApproved;
        const coverMessage = coverMode === "generated"
          ? (coverAvailable
              ? "Prova visiva · immagine generata"
              : proofReady
                ? "Visuale richiesto · in attesa di generazione"
                : "Visuale verticale previsto dopo l’approvazione dei testi.")
          : coverMode === "provided"
            ? (coverAvailable
                ? "Prova visiva · immagine fornita"
                : "Visuale fornito non ancora disponibile.")
            : (proofReady
                ? "Prova visiva · copertina tipografica"
                : "Copertina tipografica prevista dopo l’approvazione dei testi.");
        form.append(create(
          "p",
          "cover-visual-note",
          delivered
            ? "La prova visuale è approvata e il layout dettagliato è stato consegnato."
            : visualApproved
              ? "La prova visuale è approvata. Il rendering completo può iniziare."
              : coverMessage,
        ));
      }
      const showTitle = slide.kind !== "item" || model.sequence_mode === "sectional" || slide.title;
      if (showTitle) {
        const titleLabel = slide.kind === "cover" ? "Titolo della copertina" : "Titolo";
        form.append(makeField(slide, "title", titleLabel, slide.kind === "cover", (value) => {
          renderEmphasizedText(previewTitle, value, emphasisFor(slide, "title"));
        }));
      }
      {
        const summaryLabel = slide.kind === "cover"
          ? "Sottotitolo della copertina (opzionale)"
          : slide.kind === "outro" ? "Testo della chiusura" : "Testo della slide";
        form.append(makeField(slide, "summary", summaryLabel, true, (value) => {
          renderEmphasizedText(previewSummary, value, emphasisFor(slide, "summary"));
          if (slide.kind === "cover") previewSummary.hidden = !value.trim();
        }));
      }
      const noteGroup = create("div", "field-group");
      const noteId = `note-${slide.id}`;
      const noteLabel = create("label", "field-label", "Commento sull'intera slide");
      noteLabel.htmlFor = noteId;
      noteGroup.append(noteLabel);
      const note = document.createElement("textarea");
      note.id = noteId;
      note.className = "slide-note";
      note.rows = 2;
      note.placeholder = slide.kind === "cover"
        ? "Per esempio: aggiungi un disegno coerente col titolo"
        : "Per esempio: questa slide ripete la precedente";
      note.value = slideNotes[slide.id] || "";
      note.addEventListener("input", () => {
        slideNotes[slide.id] = note.value;
        persistDraft();
        renderSequenceNav();
      });
      noteGroup.append(note);
      form.append(noteGroup);
      row.append(preview, form);
      elements.slides.append(row);
    });
    applyViewedClasses();
    setupObserver();
    restoreFocus(focusSnapshot, elements.slides);
    schedulePreviewMeasure();
    if (publishContract) publishPreviewContract();
  }

  function roundedMetric(value) {
    return Number(Number(value || 0).toFixed(6));
  }

  function productionSlideFrames() {
    return [...(elements.slides?.querySelectorAll('.slide-preview[data-production-source="approved-preview"]') || [])].map((preview) => {
      const row = preview.closest(".slide-row");
      const bounds = preview.getBoundingClientRect();
      return {
        id: row?.dataset.slideId || "",
        kind: preview.dataset.kind || "",
        x: roundedMetric(bounds.left + window.scrollX),
        y: roundedMetric(bounds.top + window.scrollY),
        width: roundedMetric(bounds.width),
        height: roundedMetric(bounds.height),
      };
    });
  }

  function geometryPart(node, previewBounds) {
    if (!node) return null;
    const style = window.getComputedStyle(node);
    if (geometryPartIsHidden(node, style)) return { hidden: true };
    const bounds = node.getBoundingClientRect();
    const width = previewBounds.width || 1;
    const height = previewBounds.height || 1;
    return {
      x: roundedMetric((bounds.left - previewBounds.left) / width),
      y: roundedMetric((bounds.top - previewBounds.top) / height),
      width: roundedMetric(bounds.width / width),
      height: roundedMetric(bounds.height / height),
      font_family: style.fontFamily,
      font_size: roundedMetric(Number.parseFloat(style.fontSize) / width),
      font_weight: style.fontWeight,
      line_height: style.lineHeight,
    };
  }

  function previewGeometrySnapshot() {
    const parts = [
      "preview-copy",
      "preview-title",
      "preview-summary",
      "preview-page",
      "preview-brand",
      "preview-logo",
      "preview-website",
      "preview-sphere-primary",
      "preview-sphere-core",
      "preview-sphere-ring",
      "preview-sphere-moon",
      "preview-sphere-satellite",
    ];
    return [...(elements.slides?.querySelectorAll('.slide-preview[data-production-source="approved-preview"]') || [])].map((preview) => {
      const bounds = preview.getBoundingClientRect();
      return {
        id: preview.closest(".slide-row")?.dataset.slideId || "",
        kind: preview.dataset.kind || "",
        surface: preview.dataset.surface || "",
        constellation_position: preview.dataset.constellationPosition || "",
        visual_system: selectedVisualSystem,
        aspect_ratio: roundedMetric(bounds.width / (bounds.height || 1)),
        parts: Object.fromEntries(parts.map((name) => [name, geometryPart(preview.querySelector(`.${name}`), bounds)])),
      };
    });
  }

  function canonicalContentSnapshot() {
    return {
      revision: model?.revision ?? null,
      render_fingerprint: model?.render_fingerprint || "",
      workflow_state: model?.workflow_state || "",
      approval_checkpoint: model?.approval_checkpoint || "",
      visual_style_system: selectedVisualSystem,
      logo_mode: logoMode,
      cover_mode: resolvedCoverMode(),
      slides: normalizedSlides(draftSlides),
      format: clone(model?.format || {}),
      typography: clone(typography()),
      brand: clone(previewBrand()),
      cover_visual: clone(selectedVisualProof()?.cover_visual || model?.cover_visual || {}),
      proof: clone(model?.proof || {}),
      production: clone(model?.production || {}),
    };
  }

  function renderContractId() {
    const value = model?.render_contract;
    return typeof value === "string" && value.trim() ? value.trim() : "";
  }

  function getRenderContract() {
    return {
      contract: renderContractId(),
      production: productionRender,
      revision: model?.revision ?? null,
      workflowState: model?.workflow_state || "",
      proofApproved: model?.proof_approved === true,
      styleSystem: selectedVisualSystem,
      contentSnapshot: canonicalContentSnapshot(),
      frames: productionSlideFrames(),
      geometry: previewGeometrySnapshot(),
    };
  }

  function nextPaint() {
    return new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
  }

  async function waitForPreviewImages() {
    const images = [...(elements.slides?.querySelectorAll(".slide-preview img") || [])];
    await Promise.all(images.map((image) => {
      if (image.complete) return Promise.resolve();
      return new Promise((resolve) => {
        image.addEventListener("load", resolve, { once: true });
        image.addEventListener("error", resolve, { once: true });
      });
    }));
    const broken = images.find((image) => !image.complete || image.naturalWidth < 1);
    if (broken) throw new Error("Un asset dell’anteprima approvata non si è caricato.");
    const backgroundUrls = new Set();
    for (const preview of elements.slides?.querySelectorAll(".slide-preview") || []) {
      const backgroundImage = window.getComputedStyle(preview).backgroundImage || "";
      const pattern = /url\((?:"([^"]*)"|'([^']*)'|([^)]*))\)/g;
      let match = pattern.exec(backgroundImage);
      while (match) {
        const url = (match[1] || match[2] || match[3] || "").trim();
        if (url) backgroundUrls.add(url);
        match = pattern.exec(backgroundImage);
      }
    }
    await Promise.all([...backgroundUrls].map((url) => new Promise((resolve, reject) => {
      const probe = new Image();
      probe.addEventListener("load", async () => {
        try {
          if (typeof probe.decode === "function") await probe.decode();
          resolve();
        } catch (_error) {
          reject(new Error(`L’immagine di sfondo approvata non è decodificabile: ${url}`));
        }
      }, { once: true });
      probe.addEventListener("error", () => reject(new Error(`L’immagine di sfondo approvata non si è caricata: ${url}`)), { once: true });
      probe.src = url;
    })));
  }

  async function publishPreviewContract() {
    const run = ++previewContractRun;
    invalidatePreviewContract({ cancelPending: false });
    try {
      if (!(await configurePreviewTypography(run))) return;
      if (run !== previewContractRun) return;
      if (document.fonts?.ready) await document.fonts.ready;
      await waitForPreviewImages();
      await nextPaint();
      flushPreviewMeasurements();
      await nextPaint();
      if (run !== previewContractRun) return;
      const blocking = collectApprovalIssues({
        requirePreviewReady: false,
        includeProofInteraction: false,
      });
      if (blocking.length) throw new Error(`Produzione bloccata: ${blocking.map((issue) => issue.slideId || issue.key).join(", ")}.`);
      if (!renderContractId()) throw new Error("Contratto renderer non disponibile.");
      window.carouselBuilderPreview = Object.freeze({
        contract: renderContractId(),
        production: productionRender,
        styleSystem: selectedVisualSystem,
        getRenderContract,
        getSlideFrames: productionSlideFrames,
        getSlideGeometry: previewGeometrySnapshot,
      });
      document.documentElement.dataset.previewReady = "true";
      if (productionRender) document.documentElement.dataset.productionReady = "true";
      updateChangeSummary();
      refreshApprovalValidation();
    } catch (error) {
      if (run !== previewContractRun) return;
      document.documentElement.dataset.productionError = error?.message || "Anteprima non pronta";
      updateChangeSummary();
      refreshApprovalValidation();
    }
  }

  function renderComments() {
    elements.commentsList.replaceChildren();
    elements.commentCount.textContent = String(selectionComments.length);
    if (!selectionComments.length) {
      elements.commentsList.append(create("p", "empty-state", "Nessun commento su una selezione."));
      renderSequenceNav();
      return;
    }
    for (const comment of selectionComments) {
      const chip = create("div", "comment-chip");
      const title = create("strong", "", `“${comment.quote}”`);
      const body = create("span", "", comment.feedback);
      const remove = createIconButton("comment-remove", "close", "Rimuovi commento", "Rimuovi commento");
      remove.addEventListener("click", () => {
        recordUndo("commento su selezione");
        selectionComments = selectionComments.filter((item) => item.id !== comment.id);
        renderComments();
        persistDraft();
      });
      chip.append(title, body, remove);
      elements.commentsList.append(chip);
    }
    renderSequenceNav();
  }

  function renderAll() {
    if (elements.revisionLabel) elements.revisionLabel.textContent = `Revisione ${model.revision}`;
    if (elements.builderVersion) elements.builderVersion.textContent = model.editor_version ? `v${model.editor_version}` : "";
    selectedVisualSystem = resolveVisualSystem();
    loadViewState();
    renderVisualSystemPicker();
    renderCoverChoice();
    currentSlideId = currentSlideId && draftSlides.some((slide) => slide.id === currentSlideId) ? currentSlideId : draftSlides[0]?.id || null;
    renderBrand();
    renderSlides();
    renderComments();
    if (!hasPendingLock()) unlockPersistentEditing();
    elements.overallNote.value = overallNote;
    elements.editor.classList.toggle("locked", hasPendingLock());
    elements.loading.classList.add("hidden");
    elements.editor.classList.remove("hidden");
    elements.actionbar.classList.remove("hidden");
    if (hasPendingLock()) lockEditing();
    updateChangeSummary();
    renderValidationState();
  }

  async function loadSession() {
    const { response, data } = await fetchJson("/api/session", { cache: "no-store" });
    if (!response.ok) throw new Error(data.error || "Impossibile caricare la sessione");
    model = data;
    returnUrl = validReturnUrl(model.return_url) ? model.return_url : "";
    staleRevision = null;
    staleWorkflowState = null;
    staleApprovalCheckpoint = null;
    hydrateDraft();
    proofEditingExpanded = model.workflow_state !== "testi_approvati" || computeChangeCount() > 0;
    renderAll();
  }

  function collectStructureIssues() {
    const issues = [];
    const cover = draftSlides.find((slide) => slide.kind === "cover");
    if (!cover || !cover.title.trim()) issues.push({
      key: "cover-title",
      message: "Il titolo della copertina non può essere vuoto.",
      slideId: cover?.id || "",
      targetId: cover ? `field-${cover.id}-title` : "slides",
    });
    const items = draftSlides.filter((slide) => slide.kind === "item");
    if (!items.length) issues.push({ key: "missing-item", message: "Deve restare almeno una slide interna.", targetId: "slides" });
    for (const slide of items) {
      const index = draftSlides.findIndex((candidate) => candidate.id === slide.id);
      if (!slide.title.trim() && !slide.summary.trim()) issues.push({
        key: `empty-${slide.id}`,
        message: `${displayLabel(slide, index)} non può essere vuota.`,
        slideId: slide.id,
        targetId: `field-${slide.id}-summary`,
      });
    }
    const outro = draftSlides.find((slide) => slide.kind === "outro");
    if (outro && !outro.title.trim() && !outro.summary.trim()) issues.push({
      key: "empty-outro",
      message: "La chiusura non può essere vuota.",
      slideId: outro.id,
      targetId: `field-${outro.id}-summary`,
    });
    return issues;
  }

  function collectPaletteContrastIssues() {
    const brand = previewBrand();
    const issues = collectPaletteDeclarationIssues(brand);
    const palette = brand.palette || {};
    const checked = new Set();
    draftSlides.forEach((slide, index) => {
      const colors = previewColors(index, slide.kind);
      const pairs = [
        { key: `surface-${colors.surface}`, foreground: colors.text, background: colors.bg, label: `testo su fondo ${colors.surface === "dark" ? "scuro" : "chiaro"}` },
        { key: "accent", foreground: colors.accentText, background: colors.accent, label: "testo su accento" },
      ];
      for (const pair of pairs) {
        if (checked.has(pair.key)) continue;
        checked.add(pair.key);
        const ratio = contrastRatio(pair.foreground, pair.background);
        if (ratio >= 4.5) continue;
        issues.push({
          key: `contrast-${pair.key}`,
          message: `Contrasto palette insufficiente per ${pair.label}: ${ratio.toFixed(2)}:1, minimo 4.5:1.`,
          targetId: "visual-system-picker",
        });
      }
    });
    return issues;
  }

  function collectApprovalIssues({
    requirePreviewReady = true,
    includeProofInteraction = true,
  } = {}) {
    const issues = collectStructureIssues();
    if (
      requirePreviewReady
      && !previewReadyForApproval(document.documentElement.dataset)
    ) {
      issues.push({
        key: "preview-not-ready",
        message: document.documentElement.dataset.productionError
          ? "L’anteprima non è pronta: correggi l’errore di rendering prima di approvare."
          : "Attendi che font, immagini e misure dell’anteprima siano pronti prima di approvare.",
        targetId: "visual-system-picker",
      });
    }
    const requiresFreshVisualProof = model?.approval_checkpoint === "visual_proof"
      && model?.proof_approved !== true
      && !productionRender;
    if (includeProofInteraction && requiresFreshVisualProof) {
      if (
        selectedCoverMode !== "typographic"
        && model?.cover_visual?.available !== true
      ) issues.push({
        key: "cover-visual-missing",
        message: "La copertina con visuale richiede l’immagine verticale prima di approvare la prova.",
        slideId: "cover",
        targetId: "cover-choice",
      });
      const draftChanged = JSON.stringify(normalizedSlides(draftSlides)) !== JSON.stringify(normalizedSlides(baselineSlides));
      if (
        draftChanged
        || selectedVisualSystem !== modelVisualSystem()
        || logoMode !== initialLogoMode()
        || selectedCoverMode !== modelCoverMode()
      ) issues.push({
        key: "proof-draft-changed",
        message: "Invia prima le correzioni grafiche o testuali, poi riapri e visualizza la nuova prova prima di approvarla.",
        targetId: "visual-system-picker",
      });
      if (!browserProofDescriptor()) issues.push({
        key: "proof-browser",
        message: "Apri la prova in un browser Chromium con versione verificabile prima di approvarla.",
        targetId: "visual-system-picker",
      });
      if (model?.proof?.preview_width !== 480) issues.push({
        key: "proof-preview-width",
        message: "La prova visuale deve dichiarare una verifica a 480 px.",
        targetId: "visual-system-picker",
      });
    }
    const unique = new Map();
    for (const issue of issues) if (!unique.has(issue.key)) unique.set(issue.key, issue);
    return [...unique.values()];
  }

  function collectApprovalAdvisories() {
    const advisories = [];
    for (const slide of draftSlides) {
      const warning = fitWarnings.get(slide.id) || {
        schema: schemaWarning(slide),
        overflow: "",
        emphasis: ["title", "summary"].flatMap((field) => emphasisWarningsFor(slide, field).map((entry) => ({ field, ...entry }))),
      };
      const index = draftSlides.indexOf(slide);
      const label = displayLabel(slide, index);
      if (warning.schema) advisories.push({ key: `schema-${slide.id}`, message: `${label}: ${warning.schema}` });
      if (warning.overflow) advisories.push({ key: `overflow-${slide.id}`, message: `${label}: ${warning.overflow}` });
      for (const [warningIndex, emphasis] of (warning.emphasis || []).entries()) {
        advisories.push({ key: `emphasis-${slide.id}-${warningIndex}`, message: `${label}: ${emphasis.message}` });
      }
    }
    const cover = draftSlides.find((slide) => slide.kind === "cover");
    if (cover?.summary.trim() && !hasRealItalicFont()) advisories.push({
      key: "cover-real-italic",
      message: "Copertina: il sottotitolo richiede una vera variante corsiva. L’anteprima non simula il corsivo.",
    });
    if (model?.approval_checkpoint === "visual_proof" && model?.proof_approved !== true && !productionRender) {
      for (const slideId of requiredProofSlideIds().filter((id) => !viewedSlideIds.has(id))) {
        const slide = draftSlides.find((candidate) => candidate.id === slideId);
        advisories.push({
          key: `proof-unseen-${slideId}`,
          message: `${displayLabel(slide || { id: slideId, kind: "item" }, draftSlides.indexOf(slide))}: slide campione non ancora vista.`,
        });
      }
      const expectedWidth = model?.proof?.preview_width;
      const expectedHeight = model?.format?.preview_height;
      for (const slideId of requiredProofSlideIds()) {
        const preview = elements.slides?.querySelector(`[data-slide-id="${selectorValue(slideId)}"] .slide-preview`);
        const bounds = preview?.getBoundingClientRect();
        if (!bounds || Math.abs(bounds.width - expectedWidth) > 0.5 || Math.abs(bounds.height - expectedHeight) > 0.5) {
          advisories.push({ key: `proof-size-${slideId}`, message: "La finestra sta mostrando la prova in scala ridotta rispetto a 480×600 px." });
        }
      }
    }
    advisories.push(...fontAdvisories);
    advisories.push(...collectPaletteContrastIssues());
    return advisories;
  }

  function fastApprovalEligible() {
    if (
      productionRender
      || model?.workflow_state !== "bozza"
      || model?.approval_checkpoint !== "profile_text"
      || modelCoverMode() !== "typographic"
      || resolvedCoverMode() !== "typographic"
      || model?.production?.mode !== "renderer"
      || model?.production?.producer !== renderContractId()
      || !model?.production?.supported_style_systems?.includes(selectedVisualSystem)
      || !browserProofDescriptor()
      || hasPendingLock()
      || hasStaleBase()
    ) return false;
    if (
      selectionComments.length
      || Object.values(slideNotes).some((value) => typeof value === "string" && value.trim())
      || brandNote.trim()
      || overallNote.trim()
    ) return false;
    return requiredProofSlideIds().length > 0
      && collectApprovalIssues({ includeProofInteraction: false }).length === 0;
  }

  function updateApprovalCopy() {
    if (!model) return;
    const visualProofStage = model.workflow_state === "testi_approvati";
    const visualApproved = ["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(model.workflow_state);
    const delivered = model.workflow_state === "consegnato";
    const fast = fastApprovalEligible();
    const approvalLabel = delivered
      ? "Layout consegnato"
      : visualApproved
        ? "Prova visuale approvata"
        : visualProofStage
          ? "Genera"
          : fast ? "Genera" : "Approva i testi";
    if (elements.approveButton) elements.approveButton.textContent = approvalLabel;
    if (elements.mobileApproveButton) elements.mobileApproveButton.textContent = approvalLabel;
    if (elements.confirmApproval) {
      elements.confirmApproval.textContent = approvalLabel;
    }
    if (elements.approvalDialogTitle) {
      elements.approvalDialogTitle.textContent = fast
        ? "Generare il carosello?"
        : visualProofStage ? "Generare il carosello?" : "Confermi profilo e testi?";
    }
    if (elements.approvalDialogCopy) {
      const coverMode = resolvedCoverMode();
      const coverLabel = coverMode === "generated"
        ? "immagine generata"
        : coverMode === "provided" ? "immagine fornita" : "copertina tipografica";
      elements.approvalDialogCopy.textContent = fast
        ? `Genera ciò che vedi con ${coverLabel}. Gli avvisi visuali ed editoriali restano consultivi: confermando, accetti le scelte correnti e ne assumi la responsabilità finale.`
        : visualProofStage
          ? `Genera ciò che vedi con ${coverLabel}. Gli avvisi visuali ed editoriali non bloccano la produzione: confermando, accetti le scelte correnti e ne assumi la responsabilità finale.`
          : `Questo è il primo consenso. Confermi profilo, sequenza e testi; modifiche e commenti saranno inviati insieme. L’agente preparerà poi una prova visiva separata con ${coverLabel}, che richiederà un secondo consenso.`;
    }
    renderWorkflowJourney();
  }

  function approvalBrandSummary(metrics) {
    const brand = previewBrand();
    const hasTextSignature = Boolean(String(brand.signature || "").trim() || String(brand.website || "").trim());
    const logoCount = logoMode === "auto" ? metrics.logoSlides : 0;
    const fallbackCount = hasTextSignature ? metrics.logoTotal - logoCount : 0;
    if (logoMode === "hidden") {
      return hasTextSignature
        ? `Logo nascosto; firma testuale applicata su ${metrics.logoTotal}/${metrics.logoTotal} slide`
        : "Logo nascosto; nessuna firma testuale disponibile";
    }
    if (logoCount === metrics.logoTotal) return `Logo applicato su ${logoCount}/${metrics.logoTotal} slide`;
    if (logoCount > 0 && fallbackCount > 0) return `Logo applicato su ${logoCount}/${metrics.logoTotal} slide; firma testuale sulle altre ${fallbackCount}`;
    if (logoCount > 0) return `Logo applicato su ${logoCount}/${metrics.logoTotal} slide; ${metrics.logoTotal - logoCount} senza identificazione del brand`;
    if (fallbackCount > 0) return `Firma testuale applicata su ${fallbackCount}/${metrics.logoTotal} slide`;
    return "Nessun logo o firma disponibile nelle slide";
  }

  function validationTarget(issue) {
    const target = issue?.targetId ? document.getElementById(issue.targetId) : null;
    if (target?.matches?.("[role='radiogroup']")) return target.querySelector("[tabindex='0']") || target;
    return target;
  }

  function clearInlineValidation() {
    for (const node of document.querySelectorAll(".approval-field-error")) node.remove();
    for (const node of document.querySelectorAll("[data-approval-invalid]")) {
      node.removeAttribute("data-approval-invalid");
      node.removeAttribute("aria-invalid");
      const describedBy = (node.getAttribute("aria-describedby") || "")
        .split(/\s+/)
        .filter((id) => id && !id.startsWith("approval-error-"));
      if (describedBy.length) node.setAttribute("aria-describedby", describedBy.join(" "));
      else node.removeAttribute("aria-describedby");
    }
  }

  function focusValidationIssue(issue) {
    const target = validationTarget(issue);
    if (issue?.slideId) {
      const row = elements.slides?.querySelector(`[data-slide-id="${selectorValue(issue.slideId)}"]`);
      row?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
    if (target && typeof target.focus === "function") target.focus({ preventScroll: true });
    else elements.validationSummary?.focus({ preventScroll: true });
  }

  function renderValidationState({ focus = false } = {}) {
    if (!elements.validationSummary || !elements.validationList) return;
    clearInlineValidation();
    const issues = activeValidationIssues;
    const recoveryCount = recoverySubmissions.length + recoveryDrafts.length;
    const visible = Boolean(issues.length || submissionError);
    elements.validationSummary.hidden = !visible;
    if (visible) elements.validationSummary.setAttribute("role", "alert");
    else elements.validationSummary.removeAttribute("role");
    elements.validationSummary.setAttribute("aria-live", visible ? "assertive" : "off");
    if (elements.validationSummaryCopy) {
      elements.validationSummaryCopy.textContent = submissionError
        ? submissionError
        : "Risolvi i problemi indicati per approvare la revisione.";
    }
    elements.validationList.replaceChildren();
    const groupedByTarget = new Map();
    for (const issue of issues) {
      const item = create("li", "validation-item");
      const button = create("button", "validation-link", issue.message);
      button.type = "button";
      button.addEventListener("click", () => focusValidationIssue(issue));
      item.append(button);
      elements.validationList.append(item);
      if (issue.targetId) {
        if (!groupedByTarget.has(issue.targetId)) groupedByTarget.set(issue.targetId, []);
        groupedByTarget.get(issue.targetId).push(issue.message);
      }
    }
    for (const [targetId, messages] of groupedByTarget) {
      const target = document.getElementById(targetId);
      const group = target?.closest?.(".field-group");
      if (!target || !group) continue;
      const error = create("p", "approval-field-error", messages.join(" "));
      error.id = `approval-error-${targetId}`;
      group.append(error);
      target.dataset.approvalInvalid = "true";
      target.setAttribute("aria-invalid", "true");
      const describedBy = new Set((target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
      describedBy.add(error.id);
      target.setAttribute("aria-describedby", [...describedBy].join(" "));
    }
    if (elements.retrySubmitButton) {
      const retryable = Boolean(submissionError && pendingSubmission);
      elements.retrySubmitButton.hidden = !retryable;
      elements.retrySubmitButton.disabled = false;
      elements.retrySubmitButton.dataset.pendingControl = "true";
    }
    if (elements.exportRecoveryButton) {
      elements.exportRecoveryButton.hidden = !(submissionError && recoveryCount > 0);
      elements.exportRecoveryButton.disabled = false;
      elements.exportRecoveryButton.dataset.pendingControl = "true";
    }
    if (focus && visible) window.requestAnimationFrame(() => focusValidationIssue(issues[0]));
  }

  function refreshApprovalValidation() {
    if (!validationMode) return;
    activeValidationIssues = validationMode === "approve" ? collectApprovalIssues() : collectStructureIssues();
    if (!activeValidationIssues.length) validationMode = false;
    renderValidationState();
  }

  function runApprovalGate({ focus = true } = {}) {
    flushPreviewMeasurements();
    validationMode = "approve";
    activeValidationIssues = collectApprovalIssues();
    if (!activeValidationIssues.length) validationMode = false;
    renderValidationState({ focus: focus && activeValidationIssues.length > 0 });
    return activeValidationIssues.length === 0;
  }

  function runStructureGate({ focus = true } = {}) {
    validationMode = "structure";
    activeValidationIssues = collectStructureIssues();
    if (!activeValidationIssues.length) validationMode = false;
    renderValidationState({ focus: focus && activeValidationIssues.length > 0 });
    return activeValidationIssues.length === 0;
  }

  function collectedComments() {
    const comments = clone(selectionComments);
    for (const [slideId, feedback] of Object.entries(slideNotes)) {
      if (!feedback.trim()) continue;
      comments.push({ id: `slide-${createFeedbackId()}`, kind: "slide", slide_id: slideId, field: "", quote: "", start: null, end: null, feedback: feedback.trim() });
    }
    if (brandNote.trim()) comments.push({ id: `brand-${createFeedbackId()}`, kind: "brand", slide_id: "", field: "brand", quote: "", start: null, end: null, feedback: brandNote.trim() });
    return comments;
  }

  function approvalMetrics() {
    const fields = ["title", "summary"];
    let bold = 0;
    let italic = 0;
    let underline = 0;
    let accent = 0;
    for (const slide of draftSlides) {
      for (const field of fields) {
        bold += emphasisSegments(slide, field, "bold").length;
        italic += emphasisSegments(slide, field, "italic").length;
        underline += emphasisSegments(slide, field, "underline").length;
        accent += emphasisSegments(slide, field, "accent").length;
      }
    }
    const logoSlides = logoMode === "hidden"
      ? 0
      : draftSlides.filter((slide, index) => logoMetadata(logoRoleForSlide(slide, index)).available === true).length;
    const logoTotal = logoMode === "hidden" ? 0 : draftSlides.length;
    return { bold, italic, underline, accent, logoSlides, logoTotal };
  }

  function releaseEditingLock() {
    if (hasPendingLock()) {
      lockEditing();
      updateChangeSummary();
      return;
    }
    elements.editor?.classList.remove("locked");
    elements.editor?.setAttribute("aria-busy", "false");
    unlockPersistentEditing();
    renderSlides();
    renderComments();
    updateChangeSummary();
  }

  function clearPendingSubmission({ keepError = true } = {}) {
    awaitingFeedbackId = null;
    pendingSubmission = null;
    if (!keepError) submissionError = "";
    persistDraft({ immediate: true });
    releaseEditingLock();
    renderValidationState();
  }

  async function sendPendingSubmission() {
    if (!isPendingSubmission(pendingSubmission)) return;
    const baseMatches = pendingSubmission.payload.base_revision === model?.revision;
    const fingerprintMatches = pendingSubmission.action !== "approve"
      || pendingSubmission.payload.render_fingerprint === (model?.render_fingerprint || "");
    const workflowMatches = pendingSubmission.action !== "approve"
      || pendingSubmission.payload.base_workflow_state === (model?.workflow_state || "");
    if (!baseMatches || !fingerprintMatches || !workflowMatches) {
      const reason = !baseMatches
        ? "base-revision-mismatch-before-retry"
        : !workflowMatches
          ? "base-workflow-mismatch-before-retry"
          : "render-fingerprint-mismatch-before-retry";
      preservePendingSubmission(reason);
      submissionError = `La pagina è stata aggiornata dopo la revisione ${pendingSubmission.payload.base_revision}. Le modifiche sono al sicuro: scaricane una copia prima di ricaricare.`;
      clearPendingSubmission();
      renderValidationState({ focus: true });
      return;
    }
    preservePendingSubmission("pre-post-backup", "", currentDraftRecoverySource());
    awaitingFeedbackId = pendingSubmission.feedback_id;
    submissionError = "";
    persistDraft({ immediate: true });
    lockEditing();
    renderValidationState();
    try {
      const { response, data } = await fetchJson("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pendingSubmission.payload),
      });
      if (!response.ok) {
        const message = data.error || "Invio non riuscito";
        if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
          const rejectedAction = pendingSubmission.action;
          preservePendingSubmission(`http-${response.status}`, message);
          submissionError = `${message}. Le modifiche non sono state perse: scaricane una copia prima di ricaricare.`;
          clearPendingSubmission();
          if (response.status === 422 && rejectedAction === "approve") await loadSession();
          showToast(message, true);
          return;
        }
        throw new Error(message);
      }
      if (data.feedback_id !== pendingSubmission.feedback_id) throw new Error("Il server ha restituito un identificativo di feedback inatteso.");
      awaitingFeedbackId = pendingSubmission.feedback_id;
      submissionError = "";
      persistDraft({ immediate: true });
      lockEditing();
      renderValidationState();
      showToast(pendingSubmission.action === "approve"
        ? "Richiesta di approvazione inviata. Ti aggiorno qui appena viene elaborata."
        : "Correzioni inviate. Ti aggiorno qui appena vengono elaborate.");
      updateChangeSummary();
      schedulePoll(0);
    } catch (error) {
      submissionError = error?.name === "AbortError"
        ? "L’invio non ha ricevuto conferma entro il tempo previsto. La richiesta è salvata e può essere ritentata senza duplicarla."
        : `${error.message || "Invio non riuscito"}. La richiesta è salvata e può essere ritentata senza duplicarla.`;
      persistDraft({ immediate: true });
      lockEditing();
      renderValidationState({ focus: true });
      showToast("Stato dell’invio non confermato. La bozza è al sicuro.", true);
      updateChangeSummary();
      schedulePoll(0);
    }
  }

  async function submit(action) {
    if (foreignFeedbackId) {
      submissionError = "Un altro feedback è in elaborazione. Le modifiche locali restano salvate e non verranno inviate finché il batch esterno non è stato riconciliato.";
      renderValidationState({ focus: true });
      return;
    }
    const valid = action === "approve" ? runApprovalGate() : runStructureGate();
    if (!valid) {
      showToast(action === "approve"
        ? "L’approvazione è bloccata finché i problemi indicati non sono risolti. Puoi comunque inviare una correzione."
        : activeValidationIssues[0]?.message || "Controlla la bozza prima dell’invio.", true);
      return;
    }
    if (pendingSubmission) return sendPendingSubmission();
    const combinedApproval = action === "approve" && fastApprovalEligible();
    const feedbackId = createFeedbackId();
    const payload = {
      feedback_id: feedbackId,
      action,
      base_revision: model.revision,
      slides: normalizedSlides(draftSlides),
      comments: collectedComments(),
      overall_note: overallNote.trim(),
      visual_style_system: selectedVisualSystem,
      logo_mode: logoMode,
      cover_mode: selectedCoverMode,
    };
    if (action === "approve") {
      payload.render_fingerprint = model.render_fingerprint || "";
      payload.base_workflow_state = model.workflow_state || "";
      if (model.approval_checkpoint === "visual_proof") {
        payload.proof_slide_ids = requiredProofSlideIds();
        payload.proof_browser = browserProofDescriptor();
      } else if (combinedApproval) {
        payload.approval_scope = combinedApprovalScope;
        payload.proof_slide_ids = requiredProofSlideIds();
        payload.proof_browser = browserProofDescriptor();
      }
    }
    pendingSubmission = { feedback_id: feedbackId, action, payload };
    awaitingFeedbackId = feedbackId;
    submissionError = "";
    persistDraft({ immediate: true });
    await sendPendingSubmission();
  }

  function schedulePoll(delay = null) {
    // A pending submission is a durable handoff to the agent. Keep polling it
    // even when the in-app browser moves this tab to the background; otherwise
    // the server receives the batch but the editor never observes its outcome.
    if (productionRender || (document.hidden && !hasPendingLock())) return;
    window.clearTimeout(pollTimer);
    const backoff = Math.min(POLL_MAX_DELAY, POLL_BASE_DELAY * (2 ** Math.min(pollFailures, 4)));
    pollTimer = window.setTimeout(pollStatus, delay ?? backoff);
  }

  function statusBaseChange(status) {
    const workflowChanged = typeof status?.workflow_state === "string"
      && status.workflow_state
      && status.workflow_state !== (model?.workflow_state || "");
    const checkpointChanged = typeof status?.approval_checkpoint === "string"
      && status.approval_checkpoint
      && status.approval_checkpoint !== (model?.approval_checkpoint || "");
    return { workflowChanged: Boolean(workflowChanged), checkpointChanged: Boolean(checkpointChanged) };
  }

  async function pollStatus() {
    if (pollInFlight || productionRender || (document.hidden && !hasPendingLock())) return;
    pollInFlight = true;
    pollAbortController = new AbortController();
    try {
      const { response, data: status } = await fetchJson("/api/status", { cache: "no-store", signal: pollAbortController.signal });
      if (!response.ok) throw new Error(status.error || "Stato non disponibile");
      pollFailures = 0;
      const baseChange = statusBaseChange(status);
      if (awaitingFeedbackId && status.applied_feedback_id === awaitingFeedbackId) {
        const appliedFeedbackId = awaitingFeedbackId;
        const submittedAction = pendingSubmission?.action || "feedback";
        const submittedVisualSystem = pendingSubmission?.payload?.visual_style_system || "";
        awaitingFeedbackId = null;
        pendingSubmission = null;
        markRecoveryApplied(appliedFeedbackId);
        submissionError = "";
        validationMode = false;
        activeValidationIssues = [];
        removeDraftPreservingRecovery();
        await loadSession();
        if (submittedAction === "feedback" && submittedVisualSystem === modelVisualSystem()) {
          const definition = visualSystemDefinition(
            visualSystems.find((system) => system.id === submittedVisualSystem) || visualSystems[0],
          );
          const styleName = definition.label.replace(/^[A-Z] · /, "");
          showToast(`Bozza inviata e applicata. Sistema visivo: ${styleName}. Revisione ${model.revision}.`);
        } else if (submittedAction === "approve" && model.workflow_state === "testi_approvati") {
          showToast("Testi approvati. Ora controlla la prova visiva.");
        } else if (submittedAction === "approve" && ["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(model.workflow_state)) {
          showToast("Prova visiva approvata. La produzione può iniziare.");
        } else {
          showToast("Le modifiche dirette sono state applicate. Controlla la nuova revisione.");
        }
        return;
      }
      if (foreignFeedbackId && status.applied_feedback_id === foreignFeedbackId) {
        if (computeChangeCount() > 0) {
          preserveCurrentDraft("foreign-feedback-applied", foreignFeedbackId);
          submissionError = "Un’altra scheda ha applicato nuove modifiche. Le modifiche di questa scheda sono al sicuro: scaricane una copia prima di ricaricare.";
          if (Number.isInteger(status.manifest_revision) && status.manifest_revision !== model?.revision) {
            staleRevision = status.manifest_revision;
          }
          if (baseChange.workflowChanged) staleWorkflowState = status.workflow_state;
          if (baseChange.checkpointChanged) staleApprovalCheckpoint = status.approval_checkpoint;
          if (staleRevision !== null || baseChange.workflowChanged || baseChange.checkpointChanged) foreignFeedbackId = null;
          persistDraft({ immediate: true });
          lockEditing();
          renderValidationState({ focus: true });
          showToast("Nuova base rilevata. La bozza di questo tab è stata preservata.", true);
          return;
        }
        if (baseChange.workflowChanged || baseChange.checkpointChanged) {
          foreignFeedbackId = null;
          submissionError = "";
          removeDraftPreservingRecovery();
          await loadSession();
          showToast("Il feedback esterno è stato applicato. Controlla il checkpoint aggiornato.");
          return;
        }
        if (!Number.isInteger(status.manifest_revision) || status.manifest_revision === model?.revision) {
          submissionError = "Il feedback esterno è stato applicato. Attendo la nuova revisione senza ricaricare la pagina.";
          persistDraft({ immediate: true });
          lockEditing();
          renderValidationState();
          return;
        }
        foreignFeedbackId = null;
        submissionError = "";
        removeDraftPreservingRecovery();
        await loadSession();
        showToast("Il feedback esterno è stato applicato. Controlla la nuova revisione.");
        return;
      }
      if (baseChange.workflowChanged || baseChange.checkpointChanged) {
        const hasLocalRisk = hasPendingLock() || isPendingSubmission(pendingSubmission) || computeChangeCount() > 0;
        if (!hasLocalRisk) {
          removeDraftPreservingRecovery();
          await loadSession();
          showToast("Il checkpoint di approvazione è stato aggiornato.");
          return;
        }
        if (isPendingSubmission(pendingSubmission)) {
          preservePendingSubmission("workflow-checkpoint-changed", "", currentDraftRecoverySource());
        }
        preserveCurrentDraft("workflow-checkpoint-changed", awaitingFeedbackId || foreignFeedbackId || "");
        if (Number.isInteger(status.manifest_revision) && status.manifest_revision !== model?.revision) staleRevision = status.manifest_revision;
        if (baseChange.workflowChanged) staleWorkflowState = status.workflow_state;
        if (baseChange.checkpointChanged) staleApprovalCheckpoint = status.approval_checkpoint;
        submissionError = "La revisione è avanzata mentre questa scheda conteneva modifiche. Scaricane una copia prima di ricaricare.";
        persistDraft({ immediate: true });
        lockEditing();
        renderValidationState({ focus: true });
        showToast("Checkpoint aggiornato: la base locale è stata bloccata e preservata.", true);
        return;
      }
      if (status.feedback_pending === true) {
        const serverFeedbackId = typeof status.last_feedback_id === "string" && status.last_feedback_id ? status.last_feedback_id : awaitingFeedbackId;
        const ownPending = Boolean(serverFeedbackId && (
          awaitingFeedbackId === serverFeedbackId
          || pendingSubmission?.feedback_id === serverFeedbackId
        ));
        if (ownPending) {
          foreignFeedbackId = null;
          awaitingFeedbackId = serverFeedbackId;
          submissionError = "";
        } else {
          if (isPendingSubmission(pendingSubmission)) preservePendingSubmission("foreign-feedback-pending");
          preserveCurrentDraft("foreign-feedback-pending", serverFeedbackId || "");
          pendingSubmission = null;
          awaitingFeedbackId = null;
          foreignFeedbackId = serverFeedbackId || "feedback-esterno";
          submissionError = "Un’altra scheda sta inviando modifiche. Questa bozza resta salvata e tornerà modificabile al termine dell’invio.";
        }
        persistDraft({ immediate: true });
        lockEditing();
        renderValidationState();
      } else {
        if (foreignFeedbackId) {
          foreignFeedbackId = null;
          submissionError = recoveryDrafts.length || recoverySubmissions.length
            ? "L’invio dell’altra scheda non è più in coda. Le modifiche di questa scheda restano salvate."
            : "";
          persistDraft({ immediate: true });
          if (status.manifest_revision === model?.revision) releaseEditingLock();
          renderValidationState();
        }
        if (awaitingFeedbackId) {
          if (pendingSubmission?.feedback_id === awaitingFeedbackId) {
            submissionError = "L’invio salvato non risulta ancora in coda. Puoi ritentarlo con lo stesso identificativo senza creare duplicati.";
            persistDraft({ immediate: true });
            lockEditing();
            renderValidationState();
          } else {
            submissionError = "L’invio precedente non risulta più in coda. La bozza locale è intatta: inviala di nuovo quando sei pronto.";
            clearPendingSubmission();
          }
        }
      }
      if (!model || !Number.isInteger(status.manifest_revision)) return;
      if (status.manifest_revision === model.revision) {
        if (hasStaleBase()) {
          staleRevision = null;
          staleWorkflowState = null;
          staleApprovalCheckpoint = null;
          if (!hasPendingLock()) releaseEditingLock();
          updateChangeSummary();
        }
        return;
      }
      if (!hasPendingLock() && computeChangeCount() === 0) {
        removeDraftPreservingRecovery();
        await loadSession();
        showToast(`Aggiornato alla revisione ${model.revision}.`);
        return;
      }
      if (staleRevision !== status.manifest_revision) {
        staleRevision = status.manifest_revision;
        lockEditing();
        updateChangeSummary();
        showToast("L'agente ha aggiornato i testi. Ricarica per vedere la revisione corrente.", true);
      }
    } catch (error) {
      if (error?.name !== "AbortError" || !document.hidden) pollFailures += 1;
    } finally {
      pollAbortController = null;
      pollInFlight = false;
      schedulePoll();
    }
  }

  function clearPendingSelection({ focus = true } = {}) {
    const focusTarget = pendingSelection?.focusTarget;
    pendingSelection = null;
    if (elements.commentQuote) elements.commentQuote.textContent = "";
    if (elements.commentFeedback) elements.commentFeedback.value = "";
    if (focus && focusTarget?.isConnected) window.requestAnimationFrame(() => focusTarget.focus());
  }

  async function resetDraft() {
    clearPendingSelection({ focus: false });
    if (elements.dialog?.open) elements.dialog.close();
    if (hasStaleBase()) {
      const target = staleRevision !== null && staleRevision !== model?.revision
        ? `la revisione ${staleRevision}`
        : "il checkpoint corrente";
      if (!window.confirm(`Caricare ${target}? Le modifiche locali restano salvate.`)) return;
      removeDraftPreservingRecovery();
      try {
        await loadSession();
        showToast(`Aggiornato alla revisione ${model.revision}.`);
      } catch (error) {
        showToast(error.message || "Ricarica non riuscita", true);
      }
      return;
    }
    if (!window.confirm("Ripristinare i testi della revisione corrente e rimuovere i commenti non inviati?")) return;
    removeDraftPreservingRecovery();
    hydrateDraft();
    renderAll();
    elements.resetButton?.focus();
    showToast("Bozza locale ripristinata.");
  }

  function currentDraftState(label = "modifica") {
    return {
      label,
      slides: clone(draftSlides),
      comments: clone(selectionComments),
      slideNotes: clone(slideNotes),
      brandNote,
      overallNote,
      logoMode,
      coverMode: selectedCoverMode,
      visualSystem: selectedVisualSystem,
    };
  }

  function recordUndo(label) {
    if (!model || hasPendingLock() || hasStaleBase()) return;
    undoState = currentDraftState(label);
    if (elements.undoButton) elements.undoButton.disabled = false;
    syncMobileActions();
  }

  function undoLastChange() {
    if (!undoState || hasPendingLock() || hasStaleBase()) return;
    const previous = undoState;
    undoState = null;
    draftSlides = clone(previous.slides);
    selectionComments = clone(previous.comments);
    slideNotes = clone(previous.slideNotes);
    brandNote = previous.brandNote;
    overallNote = previous.overallNote;
    logoMode = previous.logoMode;
    selectedCoverMode = previous.coverMode;
    selectedVisualSystem = previous.visualSystem;
    safeStorageSet(visualSystemStorageKey(), selectedVisualSystem);
    renderAll();
    persistDraft();
    showToast(`Annullata: ${previous.label}.`);
  }

  elements.brandNote?.addEventListener("input", () => {
    if (!elements.brandNote._undoCaptured) {
      recordUndo("commento sul profilo");
      elements.brandNote._undoCaptured = true;
    }
    brandNote = elements.brandNote.value;
    persistDraft();
  });
  elements.overallNote?.addEventListener("input", () => {
    if (!elements.overallNote._undoCaptured) {
      recordUndo("nota generale");
      elements.overallNote._undoCaptured = true;
    }
    overallNote = elements.overallNote.value;
    persistDraft();
  });
  for (const node of [elements.brandNote, elements.overallNote]) {
    node?.addEventListener("focus", () => { node._undoCaptured = false; });
    node?.addEventListener("blur", () => { node._undoCaptured = false; });
  }
  elements.logoPreference?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-logo-mode]");
    if (button) setLogoMode(button.dataset.logoMode);
  });
  elements.logoPreference?.addEventListener("keydown", (event) => {
    const button = event.target.closest("[data-logo-mode]");
    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
    if (!button || !keys.includes(event.key)) return;
    event.preventDefault();
    const values = ["auto", "hidden"];
    const currentIndex = values.indexOf(button.dataset.logoMode);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? values.length - 1
        : (currentIndex + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + values.length) % values.length;
    setLogoMode(values[nextIndex], { focus: true });
  });
  elements.compareVisualSystems?.addEventListener("click", () => {
    visualAlternativeExpanded = true;
    renderVisualSystemPicker({ focusSystem: alternateVisualSystem() });
  });
  elements.showAdvancedVisualSystem?.addEventListener("click", () => {
    advancedVisualExpanded = true;
    renderVisualSystemPicker({ focusSystem: "editorial-halftone" });
  });
  elements.coverChoice?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-cover-choice]");
    if (button) setCoverChoice(button.dataset.coverChoice);
  });
  elements.coverChoice?.addEventListener("keydown", (event) => {
    const button = event.target.closest("[data-cover-choice]");
    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
    if (!button || !keys.includes(event.key)) return;
    event.preventDefault();
    const values = ["typographic", "visual"];
    const currentIndex = values.indexOf(button.dataset.coverChoice);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? values.length - 1
        : (currentIndex + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + values.length) % values.length;
    setCoverChoice(values[nextIndex], { focus: true });
  });
  elements.styleExportButton?.addEventListener("click", exportStyleProfile);
  elements.toggleProofEditing?.addEventListener("click", () => {
    proofEditingExpanded = !proofEditingExpanded;
    renderProofMode();
    if (proofEditingExpanded) {
      elements.visualSystemPicker?.querySelector("[tabindex='0']")?.focus({ preventScroll: true });
    } else {
      elements.workflowJourney?.scrollIntoView({ block: "start", behavior: "smooth" });
      elements.toggleProofEditing.focus({ preventScroll: true });
    }
  });
  elements.undoButton?.addEventListener("click", undoLastChange);
  elements.resetButton?.addEventListener("click", resetDraft);
  elements.sendButton?.addEventListener("click", () => submit("feedback"));
  elements.approveButton?.addEventListener("click", () => {
    if (!runApprovalGate()) {
      showToast("L’approvazione è bloccata finché i problemi indicati non sono risolti. Puoi comunque inviare una correzione.", true);
      return;
    }
    const combinedApproval = fastApprovalEligible();
    if (elements.approvalDialog) {
      elements.approvalDialog.dataset.approvalScope = combinedApproval
        ? combinedApprovalScope
        : "";
    }
    if (elements.approvalSummary) {
      const warnings = [...fitWarnings.values()].filter((warning) => warning.schema || warning.overflow).length;
      const advisoryCount = collectApprovalAdvisories().length;
      const metrics = approvalMetrics();
      const logoSummary = approvalBrandSummary(metrics);
      const densitySummary = warnings === 0 ? "Nessun avviso di densità." : `${warnings} ${warnings === 1 ? "avviso" : "avvisi"} di densità da considerare.`;
      const advisorySummary = advisoryCount === 0 ? "Nessun altro avviso." : `${advisoryCount} ${advisoryCount === 1 ? "avviso informativo" : "avvisi informativi"}.`;
      const scopeSummary = combinedApproval
        ? "Genera ciò che vedi: gli avvisi restano consultivi e la decisione finale è tua."
        : model.workflow_state === "testi_approvati"
          ? "Questo è il secondo consenso e autorizza la produzione."
          : "Questo è il primo consenso e riguarda profilo, sequenza e testi.";
      elements.approvalSummary.textContent = `Hai visualizzato ${viewedSlideIds.size} di ${draftSlides.length} slide. ${logoSummary}. Enfasi applicate: ${metrics.bold} ${metrics.bold === 1 ? "grassetto" : "grassetti"}, ${metrics.italic} ${metrics.italic === 1 ? "corsivo" : "corsivi"}, ${metrics.underline} ${metrics.underline === 1 ? "sottolineatura" : "sottolineature"}, ${metrics.accent} ${metrics.accent === 1 ? "evidenziazione" : "evidenziazioni"}. ${densitySummary} ${advisorySummary} ${scopeSummary}`;
    }
    elements.approvalDialog?.showModal();
  });
  elements.confirmApproval?.addEventListener("click", () => {
    if (!runApprovalGate()) {
      elements.approvalDialog?.close();
      showToast("La bozza è cambiata: risolvi i problemi indicati prima di approvare.", true);
      return;
    }
    if (
      elements.approvalDialog?.dataset.approvalScope === combinedApprovalScope
      && !fastApprovalEligible()
    ) {
      elements.approvalDialog?.close();
      showToast("La base tecnica della preview è cambiata: riaprila prima di generare.", true);
      updateApprovalCopy();
      return;
    }
    elements.approvalDialog?.close();
    submit("approve");
  });
  elements.retrySubmitButton?.addEventListener("click", () => sendPendingSubmission());
  elements.exportRecoveryButton?.addEventListener("click", exportRecoverySubmissions);
  elements.saveComment?.addEventListener("click", (event) => {
    event.preventDefault();
    const feedback = elements.commentFeedback?.value.trim() || "";
    if (!pendingSelection || !feedback) return showToast("Scrivi il commento prima di aggiungerlo.", true);
    recordUndo("commento su selezione");
    const { focusTarget, ...selection } = pendingSelection;
    selectionComments.push({ id: `selection-${createFeedbackId()}`, kind: "selection", ...selection, feedback });
    clearPendingSelection({ focus: true });
    elements.dialog?.close();
    renderComments();
    persistDraft();
  });
  elements.cancelComment?.addEventListener("click", (event) => {
    event.preventDefault();
    clearPendingSelection();
    elements.dialog?.close();
  });
  elements.dialog?.addEventListener("cancel", () => clearPendingSelection());
  elements.dialog?.addEventListener("close", () => {
    if (pendingSelection) clearPendingSelection();
  });
  elements.mobileActionsButton?.addEventListener("click", () => elements.mobileActionsDialog?.showModal());
  elements.closeMobileActions?.addEventListener("click", () => elements.mobileActionsDialog?.close());
  elements.mobileActionsDialog?.addEventListener("cancel", () => elements.mobileActionsDialog.close());
  elements.mobileResetButton?.addEventListener("click", () => {
    elements.mobileActionsDialog?.close();
    elements.resetButton?.click();
  });
  elements.mobileUndoButton?.addEventListener("click", () => {
    elements.mobileActionsDialog?.close();
    elements.undoButton?.click();
  });
  elements.mobileSendButton?.addEventListener("click", () => {
    elements.mobileActionsDialog?.close();
    elements.sendButton?.click();
  });
  elements.mobileApproveButton?.addEventListener("click", () => {
    elements.mobileActionsDialog?.close();
    elements.approveButton?.click();
  });
  elements.returnChatButton?.addEventListener("click", returnToChat);
  document.addEventListener("keydown", (event) => {
    if (!event.altKey || event.ctrlKey || event.metaKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    const index = draftSlides.findIndex((slide) => slide.id === currentSlideId);
    const target = draftSlides[index + (event.key === "ArrowUp" ? -1 : 1)];
    if (!target) return;
    event.preventDefault();
    jumpToSlide(target.id);
  });
  document.addEventListener("pointermove", (event) => {
    if (!pointerDrag || event.pointerId !== pointerDrag.pointerId) return;
    event.preventDefault();
    updateDirectDragTarget(event.clientX, event.clientY);
  }, { passive: false });
  document.addEventListener("pointerup", (event) => {
    if (!pointerDrag || event.pointerId !== pointerDrag.pointerId) return;
    finishDirectDrag();
  });
  document.addEventListener("pointercancel", (event) => {
    if (!pointerDrag || event.pointerId !== pointerDrag.pointerId) return;
    finishDirectDrag(true);
  });
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => schedulePreviewMeasure(), 120);
  });
  window.addEventListener("pagehide", flushDraft);
  window.addEventListener("storage", (event) => {
    if (!event.key?.startsWith(`${sharedStorageKey}:recovery:`)) return;
    const before = recoverySubmissions.length + recoveryDrafts.length;
    loadDedicatedRecoveries();
    const after = recoverySubmissions.length + recoveryDrafts.length;
    if (after === before) return;
    if (model && !productionRender) persistDraft({ immediate: true });
    if (after > before && !submissionError) submissionError = "Sono state salvate modifiche da un’altra scheda. Scaricane una copia prima di ricaricare.";
    renderValidationState();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (!hasPendingLock()) {
        window.clearTimeout(pollTimer);
        pollAbortController?.abort();
      }
      return;
    }
    schedulePoll(0);
  });

  (productionRender ? Promise.resolve() : migrateLegacyStorage())
    .catch(() => undefined)
    .then(() => loadSession())
    .then(() => schedulePoll(0))
    .catch((error) => {
      elements.loading?.replaceChildren(create("p", "", error.message || "Impossibile aprire l'editor."));
      showToast(error.message || "Impossibile aprire l'editor", true);
    });
})();

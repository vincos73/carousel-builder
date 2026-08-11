(() => {
  "use strict";

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
  if (productionRender) document.documentElement.classList.add("production-render");
  const api = (path) => {
    const url = new URL(path, window.location.origin);
    if (token) url.searchParams.set("token", token);
    return url.toString();
  };
  const storageKey = `carousel-builder:${token}`;

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
    slideCount: document.querySelector("#slide-count"),
    slides: document.querySelector("#slides"),
    overallNote: document.querySelector("#overall-note"),
    commentsList: document.querySelector("#comments-list"),
    commentCount: document.querySelector("#comment-count"),
    dirtyDot: document.querySelector("#dirty-dot"),
    changeLabel: document.querySelector("#change-label"),
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
  };

  let model = null;
  let baselineSlides = [];
  let draftSlides = [];
  let selectionComments = [];
  let slideNotes = {};
  let brandNote = "";
  let overallNote = "";
  let pendingSelection = null;
  let awaitingFeedbackId = null;
  let staleRevision = null;
  let toastTimer = null;
  let observer = null;
  let resizeTimer = null;
  let currentSlideId = null;
  let viewedSlideIds = new Set();
  let pointerDrag = null;
  let selectedVisualSystem = "editorial-frame";
  let logoMode = "auto";
  let undoState = null;
  let previewContractRun = 0;
  const fitWarnings = new Map();

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
    } catch (_error) {
      // Editing remains usable when browser storage is unavailable.
    }
  }

  function safeStorageRemove(key) {
    try {
      localStorage.removeItem(key);
    } catch (_error) {
      // A stale local draft is less harmful than interrupting a review.
    }
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
    return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
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
    return `${storageKey}:viewed:${model?.revision ?? ""}`;
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

  function selectedVisualProof() {
    return visualProofOptions().find((option) => option?.id === selectedVisualSystem) || null;
  }

  function resolvedCoverMode() {
    const mode = model?.cover_mode || model?.visual_proofs?.identity?.cover?.mode;
    if (["generated", "provided", "typographic"].includes(mode)) return mode;
    return model?.cover_visual?.available ? "provided" : "typographic";
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
    if (!proofBrand || typeof proofBrand !== "object") return profile;
    return {
      ...profile,
      ...proofBrand,
      palette: { ...(profile.palette || {}), ...(proofBrand.palette || {}) },
      font_assets: { ...(profile.font_assets || {}), ...(proofBrand.font_assets || {}) },
      logos: { ...(profile.logos || {}), ...(proofBrand.logos || {}) },
    };
  }

  function resolveVisualSystem() {
    if (productionRender) return modelVisualSystem();
    return supportedVisualSystem(safeStorageGet(visualSystemStorageKey())) || modelVisualSystem();
  }

  function modelVisualSystem() {
    const modelValue = model?.visual_proofs?.selected_style_system || model?.visual_style_system || model?.visual_system || model?.visual_style || model?.brand?.visual_system;
    return supportedVisualSystem(modelValue) || "editorial-frame";
  }

  function renderVisualSystemPicker() {
    if (!elements.visualSystemPicker) return;
    const active = visualSystemDefinition(visualSystems.find((system) => system.id === selectedVisualSystem) || visualSystems[0]);
    elements.visualSystemPicker.replaceChildren();
    elements.visualSystemPicker.dataset.activeSystem = active.id;
    if (elements.visualSystemDescription) elements.visualSystemDescription.textContent = active.description;
    for (const system of visualSystems) {
      const definition = visualSystemDefinition(system);
      const button = create("button", "visual-system-option", definition.label);
      const selected = definition.id === active.id;
      button.type = "button";
      button.dataset.visualSystem = definition.id;
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(selected));
      button.setAttribute("aria-label", `${definition.label}. ${definition.description}`);
      button.addEventListener("click", () => setVisualSystem(definition.id));
      elements.visualSystemPicker.append(button);
    }
  }

  function setVisualSystem(systemId) {
    const next = supportedVisualSystem(systemId);
    if (!next || next === selectedVisualSystem) return;
    recordUndo("sistema visivo");
    selectedVisualSystem = next;
    safeStorageSet(visualSystemStorageKey(), next);
    renderVisualSystemPicker();
    if (elements.slides) elements.slides.dataset.visualSystem = next;
    for (const preview of elements.slides?.querySelectorAll(".slide-preview") || []) {
      for (const system of visualSystems) preview.classList.toggle(`visual-system-${system.id}`, system.id === next);
    }
    renderBrand();
    publishPreviewContract(configurePreviewTypography());
    persistDraft();
    window.requestAnimationFrame(measurePreviews);
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
    if (selectedVisualSystem !== modelVisualSystem()) count += 1;
    count += selectionComments.length;
    count += Object.values(slideNotes).filter((value) => typeof value === "string" && value.trim()).length;
    if (brandNote.trim()) count += 1;
    if (overallNote.trim()) count += 1;
    return count;
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
      mobile.setAttribute("aria-disabled", String(desktop.disabled));
    }
  }

  function updateChangeSummary() {
    if (!model) return;
    const count = computeChangeCount();
    const waiting = Boolean(awaitingFeedbackId);
    if (staleRevision !== null) {
      elements.dirtyDot?.classList.add("active");
      if (elements.changeLabel) elements.changeLabel.textContent = `L'agente ha pubblicato la revisione ${staleRevision}. Ricarica per continuare.`;
      if (elements.resetButton) elements.resetButton.disabled = false;
      if (elements.undoButton) elements.undoButton.disabled = true;
      if (elements.sendButton) elements.sendButton.disabled = true;
      if (elements.approveButton) elements.approveButton.disabled = true;
      syncMobileActions();
      return;
    }
    elements.dirtyDot?.classList.toggle("active", count > 0 || waiting);
    if (elements.changeLabel) {
      elements.changeLabel.textContent = waiting
        ? `Inviato · ${count} ${count === 1 ? "intervento" : "interventi"} in elaborazione · bozza salvata nel browser`
        : count === 0
          ? "Nessuna modifica · bozza salvata nel browser"
          : `${count} ${count === 1 ? "intervento" : "interventi"} · bozza salvata nel browser`;
    }
    if (elements.resetButton) elements.resetButton.disabled = count === 0 || waiting;
    if (elements.undoButton) elements.undoButton.disabled = !undoState || waiting;
    if (elements.sendButton) elements.sendButton.disabled = count === 0 || waiting;
    if (elements.approveButton) {
      const approvalComplete = ["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(model.workflow_state);
      elements.approveButton.disabled = waiting || approvalComplete;
    }
    if (elements.sendButton) elements.sendButton.textContent = waiting ? "Correzioni inviate" : "Invia correzioni";
    if (elements.workflowBadge) {
      elements.workflowBadge.textContent = waiting ? "Inviato · in attesa dell’agente" : labelForValue(workflowLabels, model.workflow_state, "Stato non definito");
      elements.workflowBadge.toggleAttribute("aria-busy", waiting);
    }
    elements.editor?.setAttribute("aria-busy", String(waiting));
    syncMobileActions();
  }

  function lockEditing() {
    if (!elements.editor) return;
    elements.editor.classList.add("locked");
    elements.editor.setAttribute("aria-busy", "true");
    for (const node of elements.editor.querySelectorAll("input, textarea, button")) node.disabled = true;
    syncMobileActions();
  }

  function unlockPersistentEditing() {
    // Slide controls are rebuilt on every revision, while these textareas are
    // persistent DOM nodes. Re-enable them after an applied batch; otherwise
    // the disabled state set by lockEditing survives loadSession().
    for (const node of [elements.brandNote, elements.overallNote]) {
      if (node) node.disabled = false;
    }
  }

  function persistDraft() {
    if (!model || productionRender) return;
    safeStorageSet(storageKey, JSON.stringify({
      base_revision: model.revision,
      slides: normalizedSlides(draftSlides),
      comments: selectionComments,
      slide_notes: slideNotes,
      brand_note: brandNote,
      overall_note: overallNote,
      logo_mode: logoMode,
      awaiting_feedback_id: awaitingFeedbackId,
      saved_at: new Date().toISOString(),
    }));
    updateChangeSummary();
  }

  function hydrateDraft() {
    baselineSlides = clone(model.slides);
    draftSlides = clone(model.slides);
    selectionComments = [];
    slideNotes = {};
    brandNote = "";
    overallNote = "";
    logoMode = initialLogoMode();
    undoState = null;
    awaitingFeedbackId = null;
    if (productionRender) return;
    try {
      const saved = JSON.parse(safeStorageGet(storageKey) || "null");
      if (!saved || saved.base_revision !== model.revision || !Array.isArray(saved.slides)) return;
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
      awaitingFeedbackId = typeof saved.awaiting_feedback_id === "string" && saved.awaiting_feedback_id ? saved.awaiting_feedback_id : null;
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

  function hasRealItalicFont() {
    return Boolean(italicFontAsset());
  }

  function setFontStatus(_message, error = false) {
    if (!elements.fontStatus) return;
    elements.fontStatus.hidden = !error;
    elements.fontStatus.textContent = error
      ? "Un carattere non si è caricato: l’anteprima sta usando un’alternativa."
      : "";
    elements.fontStatus.setAttribute("role", error ? "alert" : "status");
    elements.fontStatus.setAttribute("aria-live", error ? "assertive" : "polite");
  }

  async function configurePreviewTypography() {
    const brand = previewBrand();
    const assets = brand.font_assets && typeof brand.font_assets === "object" ? brand.font_assets : {};
    const sansFallback = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const fallbacks = { display: sansFallback, body: sansFallback, serif: "Georgia, 'Times New Roman', serif" };
    const labels = { display: "Titoli", body: "Testi", serif: "Secondario corsivo", italic: "Corsivo" };
    const loaded = {};
    const outcomes = [];
    const resolvedItalic = italicFontAsset();
    for (const kind of ["display", "body", "serif", "italic"]) {
      const asset = kind === "italic" ? resolvedItalic : assets[kind] || (kind === "body" ? assets.sans : null);
      if (!asset || asset.available !== true || !asset.family || !asset.endpoint || typeof FontFace === "undefined") {
        outcomes.push(`${labels[kind]}: fallback dichiarato`);
        continue;
      }
      try {
        const face = new FontFace(
          asset.family,
          `url("${api(asset.endpoint).replace(/"/g, "%22")}")`,
          kind === "serif" || kind === "italic" ? { style: "italic" } : {},
        );
        await face.load();
        document.fonts.add(face);
        loaded[kind] = asset.family;
        outcomes.push(`${labels[kind]}: ${asset.family}`);
      } catch (_error) {
        outcomes.push(`${labels[kind]}: fallback dichiarato (caricamento non riuscito)`);
      }
    }
    document.documentElement.style.setProperty("--preview-display", fontStack(loaded.display, fallbacks.display));
    document.documentElement.style.setProperty("--preview-body", fontStack(loaded.body, fallbacks.body));
    document.documentElement.style.setProperty("--preview-sans", fontStack(loaded.body, fallbacks.body));
    document.documentElement.style.setProperty("--preview-serif", fontStack(loaded.serif, fallbacks.serif));
    document.documentElement.style.setProperty("--preview-italic", fontStack(loaded.italic, loaded.serif || fallbacks.serif));
    setFontStatus(
      `Tipografia anteprima — ${outcomes.join(" · ")} · Non verifica immagini o crop finali.`,
      outcomes.some((outcome) => outcome.includes("non riuscito")),
    );
    window.requestAnimationFrame(measurePreviews);
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
      summary.style.fontFamily = slide.kind === "cover" ? "var(--preview-serif)" : "var(--preview-body)";
      summary.style.fontStyle = slide.kind === "cover" ? "italic" : "normal";
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
    let hasSpecialOverlap = false;
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
        if (bothSpecial) hasSpecialOverlap = true;
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
    if (slide.kind === "item" && field === "summary" && text.trim()) {
      const italicCount = fieldItalicCount;
      const secondaryCount = italicCount
        + emphasisSegments(slide, field, "accent").length
        + emphasisSegments(slide, field, "underline").length;
      if (secondaryCount > 1 && !hasSpecialOverlap) warnings.push({
        kind: "secondary",
        message: "La card interna può usare un solo trattamento tra corsivo, sottolineatura ed evidenziatore.",
      });
    }
    return warnings;
  }

  function allEmphasisWarnings() {
    return draftSlides.flatMap((slide) => ["title", "summary"].flatMap((field) => {
      if (typeof slide[field] !== "string") return [];
      return emphasisWarningsFor(slide, field).map((warning) => ({ slide, field, ...warning }));
    }));
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

  function setLogoMode(value) {
    if (value !== "auto" && value !== "hidden") return;
    if (logoMode === value) return;
    recordUndo("modalità logo");
    logoMode = value;
    renderLogoControls();
    renderSlides();
    persistDraft();
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
        remove.disabled = Boolean(awaitingFeedbackId);
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
          window.requestAnimationFrame(measurePreviews);
        });
        appliedStylesList.append(remove);
      }
    };
    const refreshEmphasisUi = () => {
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      const quote = end > start ? input.value.slice(start, end) : "";
      const hasSelection = Boolean(quote) && !awaitingFeedbackId;
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
      window.requestAnimationFrame(measurePreviews);
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
      window.requestAnimationFrame(measurePreviews);
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
  }

  function commentsForSlide(slideId) {
    return selectionComments.some((comment) => comment.slide_id === slideId) || Boolean(slideNotes[slideId]?.trim());
  }

  function jumpToSlide(slideId) {
    const row = elements.slides?.querySelector(`[data-slide-id="${selectorValue(slideId)}"]`);
    if (!row) return;
    currentSlideId = slideId;
    markSlideSeen(slideId);
    applyViewedClasses();
    row.scrollIntoView({ behavior: "smooth", block: "start" });
    renderSequenceNav();
  }

  function renderSequenceNav() {
    if (!elements.sequenceNav) return;
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
  }

  function setupObserver() {
    observer?.disconnect();
    if (!elements.slides || typeof IntersectionObserver === "undefined") return;
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting || entry.intersectionRatio < 0.5) continue;
        currentSlideId = entry.target.dataset.slideId;
        markSlideSeen(currentSlideId);
        applyViewedClasses();
        renderSequenceNav();
      }
    }, { threshold: [0.5] });
    for (const row of elements.slides.querySelectorAll(".slide-row")) observer.observe(row);
  }

  function measurePreviews() {
    if (!elements.slides) return;
    const minScale = Math.max(0.92, Math.min(1, numberValue(typography().min_auto_scale, 0.92)));
    for (const row of elements.slides.querySelectorAll(".slide-row")) {
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
        emphasis: ["title", "summary"].flatMap((field) => emphasisWarningsFor(slide, field)),
      };
      fitWarnings.set(slide.id, notice);
      updateFitNotice(slide.id, notice);
      preview.toggleAttribute("data-fit-warning", Boolean(notice.schema || notice.overflow || notice.emphasis.length));
    }
    renderSequenceNav();
  }

  function renderSlides() {
    if (!elements.slides) return;
    fitWarnings.clear();
    elements.slides.replaceChildren();
    elements.slides.dataset.visualSystem = selectedVisualSystem;
    if (elements.slideCount) elements.slideCount.textContent = `${draftSlides.length} slide totali`;
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
      const coverVisual = selectedVisualProof()?.cover_visual || model.cover_visual;
      if (slide.kind === "cover" && coverVisual?.available && coverVisual.endpoint) {
        preview.classList.add("has-cover-image");
        preview.style.setProperty("--preview-image", `url("${api(coverVisual.endpoint).replace(/"/g, "%22")}")`);
        preview.style.setProperty("--preview-image-position", coverVisual.position || "50% 50%");
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
        drag.addEventListener("pointerdown", (event) => {
          if (event.button !== 0 || awaitingFeedbackId) return;
          event.preventDefault();
          pointerDrag = { slideId: slide.id, pointerId: event.pointerId, targetId: null, placeAfter: false };
          row.classList.add("is-dragging");
        });
        const up = createIconButton("icon-button", "up", "Sposta in alto", `Sposta ${visibleLabel} in alto`);
        up.disabled = position === 0 || Boolean(awaitingFeedbackId);
        up.addEventListener("click", () => moveItem(slide.id, -1));
        const down = createIconButton("icon-button", "down", "Sposta in basso", `Sposta ${visibleLabel} in basso`);
        down.disabled = position === items.length - 1 || Boolean(awaitingFeedbackId);
        down.addEventListener("click", () => moveItem(slide.id, 1));
        const remove = createIconButton("icon-button danger", "close", "Elimina slide", `Elimina ${visibleLabel}`);
        remove.disabled = items.length <= 1 || Boolean(awaitingFeedbackId);
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
        const proofReady = copyApproved || visualApproved;
        const coverMessage = coverMode === "generated"
          ? (proofReady
                ? "Prova visiva · immagine generata"
              : "Immagine generata prevista dopo l’approvazione dei testi.")
          : coverMode === "provided"
            ? (proofReady
                ? "Prova visiva · immagine fornita"
                : "Immagine fornita prevista dopo l’approvazione dei testi.")
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
      note.placeholder = "Per esempio: questa slide ripete la precedente";
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
    window.requestAnimationFrame(measurePreviews);
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
    if (style.display === "none" || node.hidden) return { hidden: true };
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
  }

  async function publishPreviewContract(typographyReady) {
    const run = ++previewContractRun;
    delete document.documentElement.dataset.previewReady;
    delete document.documentElement.dataset.productionReady;
    delete document.documentElement.dataset.productionError;
    try {
      await typographyReady;
      if (document.fonts?.ready) await document.fonts.ready;
      await waitForPreviewImages();
      await nextPaint();
      measurePreviews();
      await nextPaint();
      if (run !== previewContractRun) return;
      const blocking = [...fitWarnings.entries()].filter(([, warning]) => warning.schema || warning.overflow || warning.emphasis?.length);
      if (blocking.length) throw new Error(`Produzione bloccata: ${blocking.map(([id]) => id).join(", ")}.`);
      window.carouselBuilderPreview = Object.freeze({
        contract: "approved-preview-dom-v1",
        production: productionRender,
        styleSystem: selectedVisualSystem,
        getSlideFrames: productionSlideFrames,
        getSlideGeometry: previewGeometrySnapshot,
      });
      document.documentElement.dataset.previewReady = "true";
      if (productionRender) document.documentElement.dataset.productionReady = "true";
    } catch (error) {
      if (run !== previewContractRun) return;
      document.documentElement.dataset.productionError = error?.message || "Anteprima non pronta";
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
    const visualProofStage = model.workflow_state === "testi_approvati";
    const visualApproved = ["prova_visuale_approvata", "rendering", "qa", "consegnato"].includes(model.workflow_state);
    const delivered = model.workflow_state === "consegnato";
    const approvalLabel = delivered
      ? "Layout consegnato"
      : visualApproved
        ? "Prova visuale approvata"
        : visualProofStage ? "Approva prova visuale" : "Approva profilo e testi";
    if (elements.approveButton) elements.approveButton.textContent = approvalLabel;
    if (elements.mobileApproveButton) elements.mobileApproveButton.textContent = approvalLabel;
    if (elements.approvalDialogTitle) {
      elements.approvalDialogTitle.textContent = visualProofStage
        ? "Confermi la prova visuale?"
        : "Confermi profilo e testi?";
    }
    if (elements.approvalDialogCopy) {
      const coverMode = resolvedCoverMode();
      const coverLabel = coverMode === "generated"
        ? "immagine generata"
        : coverMode === "provided" ? "immagine fornita" : "copertina tipografica";
      elements.approvalDialogCopy.textContent = visualProofStage
        ? `Confermi composizione, ${coverLabel}, gerarchia tipografica, sito e firma. Il rendering completo inizierà soltanto dopo questa approvazione.`
        : `Le modifiche e i commenti saranno inviati insieme. L’agente eseguirà ancora i controlli editoriali prima di avanzare lo stato. Dopo l’approvazione dei testi verrà mostrata una prova visuale separata con ${coverLabel}.`;
    }
    loadViewState();
    selectedVisualSystem = resolveVisualSystem();
    renderVisualSystemPicker();
    currentSlideId = currentSlideId && draftSlides.some((slide) => slide.id === currentSlideId) ? currentSlideId : draftSlides[0]?.id || null;
    renderBrand();
    renderSlides();
    renderComments();
    if (!awaitingFeedbackId) unlockPersistentEditing();
    elements.overallNote.value = overallNote;
    elements.editor.classList.toggle("locked", Boolean(awaitingFeedbackId));
    elements.loading.classList.add("hidden");
    elements.editor.classList.remove("hidden");
    elements.actionbar.classList.remove("hidden");
    if (awaitingFeedbackId) lockEditing();
    updateChangeSummary();
    publishPreviewContract(configurePreviewTypography());
  }

  async function loadSession() {
    const response = await fetch(api("/api/session"), { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Impossibile caricare la sessione");
    model = data;
    staleRevision = null;
    hydrateDraft();
    renderAll();
  }

  function validateDraft(action = "feedback") {
    const cover = draftSlides.find((slide) => slide.kind === "cover");
    if (!cover || !cover.title.trim()) return "Il titolo della copertina non può essere vuoto.";
    const items = draftSlides.filter((slide) => slide.kind === "item");
    if (!items.length) return "Deve restare almeno una slide interna.";
    for (const slide of items) {
      const index = draftSlides.findIndex((candidate) => candidate.id === slide.id);
      if (!slide.title.trim() && !slide.summary.trim()) return `${displayLabel(slide, index)} non può essere vuota.`;
    }
    const outro = draftSlides.find((slide) => slide.kind === "outro");
    if (outro && !outro.title.trim() && !outro.summary.trim()) return "La chiusura non può essere vuota.";
    if (action === "approve") {
      const emphasisWarning = allEmphasisWarnings()[0];
      if (emphasisWarning) return `${displayLabel(emphasisWarning.slide, draftSlides.indexOf(emphasisWarning.slide))}: ${emphasisWarning.message}`;
    }
    return "";
  }

  function collectedComments() {
    const comments = clone(selectionComments);
    for (const [slideId, feedback] of Object.entries(slideNotes)) {
      if (!feedback.trim()) continue;
      comments.push({ id: `slide-${crypto.randomUUID()}`, kind: "slide", slide_id: slideId, field: "", quote: "", start: null, end: null, feedback: feedback.trim() });
    }
    if (brandNote.trim()) comments.push({ id: `brand-${crypto.randomUUID()}`, kind: "brand", slide_id: "", field: "brand", quote: "", start: null, end: null, feedback: brandNote.trim() });
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
    return { bold, italic, underline, accent, logoSlides, logoTotal, warningCount: allEmphasisWarnings().length };
  }

  async function submit(action) {
    const validationError = validateDraft(action);
    if (validationError) return showToast(validationError, true);
    if (elements.sendButton) elements.sendButton.disabled = true;
    if (elements.approveButton) elements.approveButton.disabled = true;
    const payload = { action, base_revision: model.revision, slides: normalizedSlides(draftSlides), comments: collectedComments(), overall_note: overallNote.trim(), visual_style_system: selectedVisualSystem, logo_mode: logoMode };
    try {
      const response = await fetch(api("/api/submit"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Invio non riuscito");
      awaitingFeedbackId = data.feedback_id;
      persistDraft();
      lockEditing();
      showToast(action === "approve"
        ? "Richiesta di approvazione inviata. Ti aggiorno qui appena viene elaborata."
        : "Correzioni inviate. Ti aggiorno qui appena vengono elaborate.");
      updateChangeSummary();
    } catch (error) {
      showToast(error.message || "Invio non riuscito", true);
      updateChangeSummary();
    }
  }

  async function pollStatus() {
    try {
      const response = await fetch(api("/api/status"), { cache: "no-store" });
      if (!response.ok) return;
      const status = await response.json();
      if (awaitingFeedbackId && status.applied_feedback_id === awaitingFeedbackId) {
        safeStorageRemove(storageKey);
        awaitingFeedbackId = null;
        await loadSession();
        showToast("Le modifiche dirette sono state applicate. Controlla la nuova revisione.");
        return;
      }
      if (!model || !Number.isInteger(status.manifest_revision)) return;
      if (status.manifest_revision === model.revision) {
        if (staleRevision !== null) {
          staleRevision = null;
          updateChangeSummary();
        }
        return;
      }
      if (!awaitingFeedbackId && computeChangeCount() === 0) {
        safeStorageRemove(storageKey);
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
    } catch (_error) {
      // The next poll retries without discarding the local browser draft.
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
    if (staleRevision !== null) {
      if (!window.confirm(`Caricare la revisione ${staleRevision}? Le modifiche non inviate andranno perse.`)) return;
      safeStorageRemove(storageKey);
      try {
        await loadSession();
        showToast(`Aggiornato alla revisione ${model.revision}.`);
      } catch (error) {
        showToast(error.message || "Ricarica non riuscita", true);
      }
      return;
    }
    if (!window.confirm("Ripristinare i testi della revisione corrente e rimuovere i commenti non inviati?")) return;
    safeStorageRemove(storageKey);
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
      visualSystem: selectedVisualSystem,
    };
  }

  function recordUndo(label) {
    if (!model || awaitingFeedbackId || staleRevision !== null) return;
    undoState = currentDraftState(label);
    if (elements.undoButton) elements.undoButton.disabled = false;
    syncMobileActions();
  }

  function undoLastChange() {
    if (!undoState || awaitingFeedbackId || staleRevision !== null) return;
    const previous = undoState;
    undoState = null;
    draftSlides = clone(previous.slides);
    selectionComments = clone(previous.comments);
    slideNotes = clone(previous.slideNotes);
    brandNote = previous.brandNote;
    overallNote = previous.overallNote;
    logoMode = previous.logoMode;
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
  elements.styleExportButton?.addEventListener("click", exportStyleProfile);
  elements.undoButton?.addEventListener("click", undoLastChange);
  elements.resetButton?.addEventListener("click", resetDraft);
  elements.sendButton?.addEventListener("click", () => submit("feedback"));
  elements.approveButton?.addEventListener("click", () => {
    const validationError = validateDraft("approve");
    if (validationError) return showToast(`${validationError} Puoi comunque inviare una correzione.`, true);
    if (elements.approvalSummary) {
      const warnings = [...fitWarnings.values()].filter((warning) => warning.schema || warning.overflow).length;
      const metrics = approvalMetrics();
      const logoSummary = logoMode === "hidden" ? "Logo nascosto" : `Logo disponibile su ${metrics.logoSlides}/${metrics.logoTotal} slide`;
      const densitySummary = warnings === 0 ? "Nessun avviso di densità." : `${warnings} ${warnings === 1 ? "avviso" : "avvisi"} di densità da considerare.`;
      elements.approvalSummary.textContent = `Hai visualizzato ${viewedSlideIds.size} di ${draftSlides.length} slide. ${logoSummary}. Enfasi applicate: ${metrics.bold} ${metrics.bold === 1 ? "grassetto" : "grassetti"}, ${metrics.italic} ${metrics.italic === 1 ? "corsivo" : "corsivi"}, ${metrics.underline} ${metrics.underline === 1 ? "sottolineatura" : "sottolineature"}, ${metrics.accent} ${metrics.accent === 1 ? "evidenziazione" : "evidenziazioni"}. ${densitySummary}`;
    }
    elements.approvalDialog?.showModal();
  });
  elements.confirmApproval?.addEventListener("click", () => {
    elements.approvalDialog?.close();
    submit("approve");
  });
  elements.saveComment?.addEventListener("click", (event) => {
    event.preventDefault();
    const feedback = elements.commentFeedback?.value.trim() || "";
    if (!pendingSelection || !feedback) return showToast("Scrivi il commento prima di aggiungerlo.", true);
    recordUndo("commento su selezione");
    const { focusTarget, ...selection } = pendingSelection;
    selectionComments.push({ id: `selection-${crypto.randomUUID()}`, kind: "selection", ...selection, feedback });
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
    resizeTimer = window.setTimeout(measurePreviews, 120);
  });

  loadSession().catch((error) => {
    elements.loading?.replaceChildren(create("p", "", error.message || "Impossibile aprire l'editor."));
    showToast(error.message || "Impossibile aprire l'editor", true);
  });
  if (!productionRender) window.setInterval(pollStatus, 2000);
})();

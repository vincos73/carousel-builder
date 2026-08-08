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

  const token = new URLSearchParams(window.location.search).get("token") || "";
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
    brandName: document.querySelector("#brand-name"),
    brandDetails: document.querySelector("#brand-details"),
    palette: document.querySelector("#palette"),
    brandNote: document.querySelector("#brand-note"),
    slideCount: document.querySelector("#slide-count"),
    slides: document.querySelector("#slides"),
    overallNote: document.querySelector("#overall-note"),
    commentsList: document.querySelector("#comments-list"),
    commentCount: document.querySelector("#comment-count"),
    dirtyDot: document.querySelector("#dirty-dot"),
    changeLabel: document.querySelector("#change-label"),
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
  const fitWarnings = new Map();

  const visualSystems = [
    {
      id: "editorial-frame",
      label: "A · Cornice",
      description: "Sistema editoriale: una cornice netta guida la lettura, con il testo al centro della scena.",
    },
    {
      id: "editorial-halftone",
      label: "B · Costellazione",
      description: "Sistema espressivo: cinque corpi geometrici di scale diverse danno ritmo alla fascia laterale senza competere con il testo.",
    },
    {
      id: "corporate-modular",
      label: "C · Modulare quieto",
      description: "Sistema corporate: un indice compatto ordina metodo, dati e processi senza sottrarre spazio al testo.",
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

  function selectorValue(value) {
    if (window.CSS?.escape) return window.CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function normalizedSlides(slides) {
    return slides.map(({ id, kind, title, summary }) => ({ id, kind, title, summary }));
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
    const modelValue = model?.visual_proofs?.selected_style_system || model?.visual_style_system || model?.visual_system || model?.visual_style || model?.brand?.visual_system;
    return supportedVisualSystem(safeStorageGet(visualSystemStorageKey())) || supportedVisualSystem(modelValue) || "editorial-frame";
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
    selectedVisualSystem = next;
    safeStorageSet(visualSystemStorageKey(), next);
    renderVisualSystemPicker();
    if (elements.slides) elements.slides.dataset.visualSystem = next;
    for (const preview of elements.slides?.querySelectorAll(".slide-preview") || []) {
      for (const system of visualSystems) preview.classList.toggle(`visual-system-${system.id}`, system.id === next);
    }
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
      if (!before || before.title !== slide.title || before.summary !== slide.summary) count += 1;
    }
    count += selectionComments.length;
    count += Object.values(slideNotes).filter((value) => typeof value === "string" && value.trim()).length;
    if (brandNote.trim()) count += 1;
    if (overallNote.trim()) count += 1;
    return count;
  }

  function syncMobileActions() {
    const pairs = [
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
    if (!model) return;
    safeStorageSet(storageKey, JSON.stringify({
      base_revision: model.revision,
      slides: normalizedSlides(draftSlides),
      comments: selectionComments,
      slide_notes: slideNotes,
      brand_note: brandNote,
      overall_note: overallNote,
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
    awaitingFeedbackId = null;
    try {
      const saved = JSON.parse(safeStorageGet(storageKey) || "null");
      if (!saved || saved.base_revision !== model.revision || !Array.isArray(saved.slides)) return;
      const knownIds = new Set(model.slides.map((slide) => slide.id));
      const validSlides = saved.slides.every((slide) => slide && knownIds.has(slide.id) && typeof slide.title === "string" && typeof slide.summary === "string");
      if (!validSlides) return;
      const metadata = new Map(model.slides.map((slide) => [slide.id, slide]));
      draftSlides = saved.slides.map((slide) => ({ ...metadata.get(slide.id), ...slide }));
      selectionComments = Array.isArray(saved.comments) ? saved.comments : [];
      slideNotes = saved.slide_notes && typeof saved.slide_notes === "object" ? saved.slide_notes : {};
      brandNote = typeof saved.brand_note === "string" ? saved.brand_note : "";
      overallNote = typeof saved.overall_note === "string" ? saved.overall_note : "";
      awaitingFeedbackId = typeof saved.awaiting_feedback_id === "string" && saved.awaiting_feedback_id ? saved.awaiting_feedback_id : null;
    } catch (_error) {
      safeStorageRemove(storageKey);
    }
  }

  function fontStack(family, fallback) {
    const safeFamily = String(family || "").replace(/["\\]/g, "").trim();
    return safeFamily ? `"${safeFamily}", ${fallback}` : fallback;
  }

  function setFontStatus(message, error = false) {
    if (!elements.fontStatus) return;
    elements.fontStatus.textContent = message;
    elements.fontStatus.setAttribute("role", error ? "alert" : "status");
    elements.fontStatus.setAttribute("aria-live", error ? "assertive" : "polite");
  }

  async function configurePreviewTypography() {
    const brand = previewBrand();
    const assets = brand.font_assets && typeof brand.font_assets === "object" ? brand.font_assets : {};
    const sansFallback = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const fallbacks = { display: sansFallback, body: sansFallback, serif: "Georgia, 'Times New Roman', serif" };
    const labels = { display: "Titoli", body: "Testi", serif: "Secondario corsivo" };
    const loaded = {};
    const outcomes = [];
    for (const kind of ["display", "body", "serif"]) {
      const asset = assets[kind] || (kind === "body" ? assets.sans : null);
      if (!asset || asset.available !== true || !asset.family || !asset.endpoint || typeof FontFace === "undefined") {
        outcomes.push(`${labels[kind]}: fallback dichiarato`);
        continue;
      }
      try {
        const face = new FontFace(
          asset.family,
          `url("${api(asset.endpoint).replace(/"/g, "%22")}")`,
          kind === "serif" ? { style: "italic" } : {},
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
    const serif = slide[`${field}_serif`] ?? slide[`${legacyPrefix}_serif`];
    const accent = slide[`${field}_accent`] ?? slide[`${legacyPrefix}_accent`];
    return {
      bold: Array.isArray(bold) ? bold : [],
      serif: Array.isArray(serif) ? serif : [],
      accent: Array.isArray(accent) ? accent : [],
    };
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
    const priority = { serif: 0, bold: 1, accent: 2 };
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
    const brand = model.brand || {};
    elements.brandName.textContent = brand.name || "Profilo senza nome";
    elements.brandDetails.replaceChildren();
    const logoCount = Object.values(brand.logos || {}).filter((logo) => logo?.available).length;
    const logoLabel = logoCount === 1 ? "1 variante disponibile" : logoCount > 1 ? `${logoCount} varianti disponibili` : "Non previsto";
    const rows = [["Sito", brand.website || "Non mostrato"], ["Firma", brand.signature || "Non mostrata"], ["Logo", logoLabel], ["Titoli", brand.display || brand.sans || "Non dichiarato"], ["Testi", brand.body || brand.sans || "Non dichiarato"], ["Secondario corsivo", brand.serif || "Non previsto"]];
    for (const [label, value] of rows) elements.brandDetails.append(create("dt", "", label), create("dd", "", value));
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
    elements.brandNote.value = brandNote;
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
    const commentButton = create("button", "comment-selection", "Commenta selezione");
    commentButton.type = "button";
    commentButton.disabled = true;
    tools.append(count, commentButton);
    heading.append(tools);
    group.append(heading);
    const input = document.createElement(multiline ? "textarea" : "input");
    input.id = fieldId;
    input.value = slide[field];
    input.dataset.slideId = slide.id;
    input.dataset.field = field;
    if (multiline) input.rows = field === "summary" ? 6 : 3;
    else input.type = "text";
    const refreshSelection = () => {
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      commentButton.disabled = end <= start || Boolean(awaitingFeedbackId);
    };
    input.addEventListener("select", refreshSelection);
    input.addEventListener("keyup", refreshSelection);
    input.addEventListener("mouseup", refreshSelection);
    input.addEventListener("input", () => {
      slide[field] = input.value;
      refreshCharacterCounts();
      onPreview(input.value);
      refreshSelection();
      persistDraft();
      window.requestAnimationFrame(measurePreviews);
    });
    commentButton.addEventListener("mousedown", (event) => event.preventDefault());
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
    group.append(input);
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
    return useDark
      ? { bg: backgroundDark, text: textOnDark, ...shared }
      : { bg: backgroundLight, text: textOnLight, ...shared };
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
    const parts = [notice.schema, notice.overflow].filter(Boolean);
    node.hidden = parts.length === 0;
    node.textContent = parts.join(" ");
    node.setAttribute("role", notice.overflow ? "alert" : "status");
    node.setAttribute("aria-live", notice.overflow ? "assertive" : "polite");
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
      button.classList.toggle("has-warning", Boolean(warning?.schema || warning?.overflow));
      button.classList.toggle("has-comments", commented);
      button.setAttribute("aria-label", `${label}${seen ? ", vista" : ", non ancora vista"}${commented ? ", con commenti" : ""}${warning?.schema || warning?.overflow ? ", richiede revisione della densità" : ""}`);
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
      };
      fitWarnings.set(slide.id, notice);
      updateFitNotice(slide.id, notice);
      preview.toggleAttribute("data-fit-warning", Boolean(notice.schema || notice.overflow));
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
      preview.style.setProperty("--preview-dark-bg", colors.backgroundDark);
      preview.style.setProperty("--preview-light-bg", colors.backgroundLight);
      preview.style.setProperty("--preview-dark-text", colors.textOnDark);
      preview.style.setProperty("--preview-light-text", colors.textOnLight);
      preview.style.setProperty("--preview-accent-text", colors.accentText);
      preview.dataset.kind = slide.kind;
      preview.dataset.surface = colors.surface;
      preview.dataset.constellationPosition = index % 2 === 0 ? "high" : "low";
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
      for (const role of ["primary", "core", "ring", "moon", "satellite"]) {
        constellation.append(create("span", `preview-sphere preview-sphere-${role}`));
      }
      const previewBrandNode = create("div", "preview-brand");
      const brand = previewBrand();
      const signature = String(brand.signature || "").trim();
      const website = String(brand.website || "").trim();
      const logoRole = slide.kind === "cover" || slide.kind === "outro" || colors.surface === "dark" ? "on_dark" : "on_light";
      const logo = brand.logos?.[logoRole];
      const hasLogo = logo?.available === true && typeof logo.endpoint === "string" && logo.endpoint;
      if (hasLogo) {
        const image = document.createElement("img");
        image.className = "preview-logo";
        image.src = api(logo.endpoint);
        image.alt = brand.name ? `Logo ${brand.name}` : "Logo del brand";
        previewBrandNode.append(image);
      } else if (signature) previewBrandNode.append(create("span", "preview-signature", signature));
      if (website) previewBrandNode.append(create("span", "preview-website", website));
      previewBrandNode.hidden = !hasLogo && !signature && !website;
      preview.append(constellation, pageNumber, previewCopy, previewBrandNode);
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
              ? "Questa prova usa l’immagine generata: controlla crop, composizione, sito e firma."
              : "Dopo l’approvazione dei testi verrà mostrata una prova con l’immagine generata.")
          : coverMode === "provided"
            ? (proofReady
                ? "Questa prova usa l’immagine fornita: controlla crop, composizione, sito e firma."
                : "Dopo l’approvazione dei testi verrà mostrata una prova con l’immagine fornita.")
            : (proofReady
                ? "Questa prova usa una copertina tipografica completa: controlla composizione, gerarchia, sito e firma."
                : "Dopo l’approvazione dei testi verrà mostrata una copertina tipografica completa, senza dipendere dalla generazione di immagini.");
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
        form.append(makeField(slide, "title", titleLabel, false, (value) => {
          renderEmphasizedText(previewTitle, value, emphasisFor(slide, "title"));
        }));
      }
      {
        const summaryLabel = slide.kind === "cover"
          ? "Sottotitolo della copertina (opzionale)"
          : slide.kind === "outro" ? "Testo della chiusura" : "Testo della slide";
        form.append(makeField(slide, "summary", summaryLabel, slide.kind !== "cover", (value) => {
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
    configurePreviewTypography();
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

  function validateDraft() {
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

  async function submit(action) {
    const validationError = validateDraft();
    if (validationError) return showToast(validationError, true);
    if (elements.sendButton) elements.sendButton.disabled = true;
    if (elements.approveButton) elements.approveButton.disabled = true;
    const payload = { action, base_revision: model.revision, slides: normalizedSlides(draftSlides), comments: collectedComments(), overall_note: overallNote.trim(), visual_style_system: selectedVisualSystem };
    try {
      const response = await fetch(api("/api/submit"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Invio non riuscito");
      awaitingFeedbackId = data.feedback_id;
      persistDraft();
      lockEditing();
      showToast(action === "approve" ? "Richiesta di approvazione inviata." : "Correzioni inviate all'agente.");
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

  elements.brandNote?.addEventListener("input", () => {
    brandNote = elements.brandNote.value;
    persistDraft();
  });
  elements.overallNote?.addEventListener("input", () => {
    overallNote = elements.overallNote.value;
    persistDraft();
  });
  elements.resetButton?.addEventListener("click", resetDraft);
  elements.sendButton?.addEventListener("click", () => submit("feedback"));
  elements.approveButton?.addEventListener("click", () => {
    if (elements.approvalSummary) {
      const warnings = [...fitWarnings.values()].filter((warning) => warning.schema || warning.overflow).length;
      elements.approvalSummary.textContent = `Hai visualizzato ${viewedSlideIds.size} di ${draftSlides.length} slide. ${warnings === 0 ? "Nessun avviso di densità." : `${warnings} ${warnings === 1 ? "avviso" : "avvisi"} di densità da considerare.`}`;
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
  window.setInterval(pollStatus, 2000);
})();

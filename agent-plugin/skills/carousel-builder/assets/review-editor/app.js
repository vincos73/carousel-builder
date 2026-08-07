(() => {
  "use strict";

  const token = new URLSearchParams(window.location.search).get("token") || "";
  const api = (path) => `${path}?token=${encodeURIComponent(token)}`;
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
    sequenceLabel: document.querySelector("#sequence-label"),
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

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function create(tag, className, textValue) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textValue !== undefined) node.textContent = textValue;
    return node;
  }

  function showToast(message, error = false) {
    window.clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("error", error);
    elements.toast.classList.add("visible");
    toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 4200);
  }

  function safeColor(value, fallback) {
    return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
  }

  function normalizedSlides(slides) {
    return slides.map(({ id, kind, title, summary }) => ({ id, kind, title, summary }));
  }

  function computeChangeCount() {
    let count = 0;
    const beforeById = new Map(baselineSlides.map((slide) => [slide.id, slide]));
    if (baselineSlides.map((slide) => slide.id).join("|") !== draftSlides.map((slide) => slide.id).join("|")) {
      count += 1;
    }
    for (const slide of draftSlides) {
      const before = beforeById.get(slide.id);
      if (!before) {
        count += 1;
        continue;
      }
      if (before.title !== slide.title) count += 1;
      if (before.summary !== slide.summary) count += 1;
    }
    count += selectionComments.length;
    count += Object.values(slideNotes).filter((value) => value.trim()).length;
    if (brandNote.trim()) count += 1;
    if (overallNote.trim()) count += 1;
    return count;
  }

  function updateChangeSummary() {
    const count = computeChangeCount();
    if (staleRevision !== null) {
      // L'agente ha pubblicato una revisione più recente: un invio basato su
      // questa copia verrebbe rifiutato dal server, quindi resta solo il ricarico.
      elements.dirtyDot.classList.add("active");
      elements.changeLabel.textContent = `L'agente ha pubblicato la revisione ${staleRevision}. Ricarica per continuare.`;
      elements.resetButton.disabled = false;
      elements.sendButton.disabled = true;
      elements.approveButton.disabled = true;
      return;
    }
    elements.dirtyDot.classList.toggle("active", count > 0);
    elements.changeLabel.textContent = count === 0
      ? "Nessuna modifica"
      : `${count} ${count === 1 ? "intervento" : "interventi"} da inviare`;
    elements.resetButton.disabled = count === 0 || Boolean(awaitingFeedbackId);
    elements.sendButton.disabled = count === 0 || Boolean(awaitingFeedbackId);
    elements.approveButton.disabled = Boolean(awaitingFeedbackId);
  }

  function persistDraft() {
    if (!model) return;
    const value = {
      base_revision: model.revision,
      slides: normalizedSlides(draftSlides),
      comments: selectionComments,
      slide_notes: slideNotes,
      brand_note: brandNote,
      overall_note: overallNote,
      saved_at: new Date().toISOString(),
    };
    localStorage.setItem(storageKey, JSON.stringify(value));
    updateChangeSummary();
  }

  function hydrateDraft() {
    baselineSlides = clone(model.slides);
    draftSlides = clone(model.slides);
    selectionComments = [];
    slideNotes = {};
    brandNote = "";
    overallNote = "";
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (!saved || saved.base_revision !== model.revision || !Array.isArray(saved.slides)) return;
      const knownIds = new Set(model.slides.map((slide) => slide.id));
      const validSlides = saved.slides.every(
        (slide) => slide && knownIds.has(slide.id) && typeof slide.title === "string" && typeof slide.summary === "string"
      );
      if (!validSlides) return;
      const metadata = new Map(model.slides.map((slide) => [slide.id, slide]));
      draftSlides = saved.slides.map((slide) => ({ ...metadata.get(slide.id), ...slide }));
      selectionComments = Array.isArray(saved.comments) ? saved.comments : [];
      slideNotes = saved.slide_notes && typeof saved.slide_notes === "object" ? saved.slide_notes : {};
      brandNote = typeof saved.brand_note === "string" ? saved.brand_note : "";
      overallNote = typeof saved.overall_note === "string" ? saved.overall_note : "";
    } catch (_error) {
      localStorage.removeItem(storageKey);
    }
  }

  function renderBrand() {
    const brand = model.brand || {};
    elements.brandName.textContent = brand.name || "Profilo senza nome";
    elements.brandDetails.replaceChildren();
    const rows = [
      ["Sito", brand.website || "Non mostrato"],
      ["Firma", brand.signature || "Non mostrata"],
      ["Primario", brand.sans || "Non dichiarato"],
      ["Secondario", brand.serif || "Non previsto"],
    ];
    for (const [label, value] of rows) {
      elements.brandDetails.append(create("dt", "", label), create("dd", "", value));
    }
    elements.palette.replaceChildren();
    const palette = brand.palette || {};
    for (const value of [
      palette.background_light,
      palette.background_dark,
      palette.text_on_light,
      palette.accent,
    ]) {
      const swatch = create("span", "swatch");
      swatch.style.backgroundColor = safeColor(value, "#d0d5dd");
      swatch.title = value || "Colore non dichiarato";
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
    const count = create("span", "char-count", `${slide[field].length} caratteri`);
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
    if (multiline) {
      input.rows = field === "summary" ? 6 : 3;
    } else {
      input.type = "text";
    }

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
      count.textContent = `${input.value.length} caratteri`;
      onPreview(input.value);
      refreshSelection();
      persistDraft();
    });
    commentButton.addEventListener("mousedown", (event) => event.preventDefault());
    commentButton.addEventListener("click", () => {
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      if (end <= start) return;
      pendingSelection = {
        slide_id: slide.id,
        field,
        quote: input.value.slice(start, end),
        start,
        end,
      };
      elements.commentQuote.textContent = pendingSelection.quote;
      elements.commentFeedback.value = "";
      elements.dialog.showModal();
      elements.commentFeedback.focus();
    });

    group.append(input);
    return group;
  }

  function itemPositions() {
    return draftSlides
      .map((slide, index) => ({ slide, index }))
      .filter(({ slide }) => slide.kind === "item");
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

  function deleteItem(slideId) {
    if (itemPositions().length <= 1) {
      showToast("Deve restare almeno una slide interna.", true);
      return;
    }
    if (!window.confirm("Eliminare questa slide dalla sequenza?")) return;
    draftSlides = draftSlides.filter((slide) => slide.id !== slideId);
    selectionComments = selectionComments.filter((comment) => comment.slide_id !== slideId);
    delete slideNotes[slideId];
    renderSlides();
    renderComments();
    persistDraft();
  }

  function previewColors(index, kind) {
    const palette = model.brand.palette || {};
    const useDark = kind === "cover" || kind === "outro" || index % 2 === 0;
    return useDark
      ? {
          bg: safeColor(palette.background_dark, "#172033"),
          text: safeColor(palette.text_on_dark, "#ffffff"),
        }
      : {
          bg: safeColor(palette.background_light, "#f5f1e8"),
          text: safeColor(palette.text_on_light, "#172033"),
        };
  }

  function displayLabel(slide, index) {
    if (slide.kind === "cover") return "Copertina";
    if (slide.kind === "outro") return "Chiusura";
    return `Slide ${index + 1}`;
  }

  function renderSlides() {
    elements.slides.replaceChildren();
    elements.slideCount.textContent = `${draftSlides.length} slide totali`;
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
      const previewCopy = create("div", "preview-copy");
      const previewTitle = create("h3", "preview-title", slide.title);
      const previewSummary = create("p", "preview-summary", slide.summary);
      if (slide.kind === "item" && model.sequence_mode === "narrative") {
        previewTitle.hidden = true;
      }
      previewCopy.append(previewTitle, previewSummary);
      preview.append(previewCopy);

      const form = create("div", "slide-form");
      const toolbar = create("div", "slide-toolbar");
      const identity = create("div", "slide-identity");
      identity.append(create("span", "slide-number", String(index + 1)));
      const identityCopy = create("div");
      identityCopy.append(create("span", "slide-name", visibleLabel), create("span", "slide-id", slide.id));
      identity.append(identityCopy);
      toolbar.append(identity);

      const toolbarActions = create("div", "toolbar-actions");
      if (slide.kind === "item") {
        const position = items.findIndex(({ slide: item }) => item.id === slide.id);
        const up = create("button", "icon-button", "↑");
        up.type = "button";
        up.title = "Sposta in alto";
        up.setAttribute("aria-label", `Sposta ${visibleLabel} in alto`);
        up.disabled = position === 0 || Boolean(awaitingFeedbackId);
        up.addEventListener("click", () => moveItem(slide.id, -1));
        const down = create("button", "icon-button", "↓");
        down.type = "button";
        down.title = "Sposta in basso";
        down.setAttribute("aria-label", `Sposta ${visibleLabel} in basso`);
        down.disabled = position === items.length - 1 || Boolean(awaitingFeedbackId);
        down.addEventListener("click", () => moveItem(slide.id, 1));
        const remove = create("button", "icon-button danger", "×");
        remove.type = "button";
        remove.title = "Elimina slide";
        remove.setAttribute("aria-label", `Elimina ${visibleLabel}`);
        remove.disabled = items.length <= 1 || Boolean(awaitingFeedbackId);
        remove.addEventListener("click", () => deleteItem(slide.id));
        toolbarActions.append(up, down, remove);
      }
      toolbar.append(toolbarActions);
      form.append(toolbar);

      const showTitle = slide.kind !== "item" || model.sequence_mode === "sectional" || slide.title;
      if (showTitle) {
        const titleLabel = slide.kind === "cover" ? "Titolo della copertina" : "Titolo";
        form.append(makeField(slide, "title", titleLabel, false, (value) => {
          previewTitle.textContent = value;
        }));
      }
      if (slide.kind !== "cover") {
        const summaryLabel = slide.kind === "outro" ? "Testo della chiusura" : "Testo della slide";
        form.append(makeField(slide, "summary", summaryLabel, true, (value) => {
          previewSummary.textContent = value;
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
      });
      noteGroup.append(note);
      form.append(noteGroup);
      row.append(preview, form);
      elements.slides.append(row);
    });
  }

  function renderComments() {
    elements.commentsList.replaceChildren();
    elements.commentCount.textContent = String(selectionComments.length);
    if (!selectionComments.length) {
      elements.commentsList.append(create("p", "empty-state", "Nessun commento su una selezione."));
      return;
    }
    for (const comment of selectionComments) {
      const chip = create("div", "comment-chip");
      const title = create("strong", "", `“${comment.quote}”`);
      const body = create("span", "", comment.feedback);
      const remove = create("button", "comment-remove", "×");
      remove.type = "button";
      remove.title = "Rimuovi commento";
      remove.setAttribute("aria-label", "Rimuovi commento");
      remove.addEventListener("click", () => {
        selectionComments = selectionComments.filter((item) => item.id !== comment.id);
        renderComments();
        persistDraft();
      });
      chip.append(title, body, remove);
      elements.commentsList.append(chip);
    }
  }

  function renderAll() {
    elements.workflowBadge.textContent = model.workflow_state || "bozza";
    elements.revisionLabel.textContent = `Revisione ${model.revision}`;
    elements.sequenceLabel.textContent = `${model.sequence_mode} · ${model.source_type} · ${model.format.ratio}`.toUpperCase();
    renderBrand();
    renderSlides();
    renderComments();
    elements.overallNote.value = overallNote;
    elements.loading.classList.add("hidden");
    elements.editor.classList.remove("hidden");
    elements.actionbar.classList.remove("hidden");
    updateChangeSummary();
  }

  async function loadSession({ preserveAwaiting = false } = {}) {
    const response = await fetch(api("/api/session"), { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Impossibile caricare la sessione");
    model = data;
    staleRevision = null;
    hydrateDraft();
    if (!preserveAwaiting) awaitingFeedbackId = null;
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
      comments.push({
        id: `slide-${crypto.randomUUID()}`,
        kind: "slide",
        slide_id: slideId,
        field: "",
        quote: "",
        start: null,
        end: null,
        feedback: feedback.trim(),
      });
    }
    if (brandNote.trim()) {
      comments.push({
        id: `brand-${crypto.randomUUID()}`,
        kind: "brand",
        slide_id: "",
        field: "brand",
        quote: "",
        start: null,
        end: null,
        feedback: brandNote.trim(),
      });
    }
    return comments;
  }

  async function submit(action) {
    const validationError = validateDraft();
    if (validationError) {
      showToast(validationError, true);
      return;
    }
    elements.sendButton.disabled = true;
    elements.approveButton.disabled = true;
    const payload = {
      action,
      base_revision: model.revision,
      slides: normalizedSlides(draftSlides),
      comments: collectedComments(),
      overall_note: overallNote.trim(),
    };
    try {
      const response = await fetch(api("/api/submit"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Invio non riuscito");
      awaitingFeedbackId = data.feedback_id;
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
        localStorage.removeItem(storageKey);
        awaitingFeedbackId = null;
        await loadSession();
        showToast("Le modifiche dirette sono state applicate. Controlla la nuova revisione.");
        return;
      }
      // L'agente aggiorna il manifest anche per risolvere i commenti: senza
      // questo controllo l'editor resterebbe su una revisione superata e ogni
      // invio successivo verrebbe rifiutato con un conflitto senza via d'uscita.
      if (!model || !Number.isInteger(status.manifest_revision)) return;
      if (status.manifest_revision === model.revision) {
        if (staleRevision !== null) {
          staleRevision = null;
          updateChangeSummary();
        }
        return;
      }
      if (!awaitingFeedbackId && computeChangeCount() === 0) {
        localStorage.removeItem(storageKey);
        await loadSession();
        showToast(`Aggiornato alla revisione ${model.revision}.`);
        return;
      }
      if (staleRevision !== status.manifest_revision) {
        staleRevision = status.manifest_revision;
        updateChangeSummary();
        showToast(
          "L'agente ha aggiornato i testi. Ricarica per vedere la revisione corrente.",
          true
        );
      }
    } catch (_error) {
      // Il polling riprova senza interrompere la bozza locale.
    }
  }

  elements.brandNote.addEventListener("input", () => {
    brandNote = elements.brandNote.value;
    persistDraft();
  });
  elements.overallNote.addEventListener("input", () => {
    overallNote = elements.overallNote.value;
    persistDraft();
  });
  elements.resetButton.addEventListener("click", async () => {
    if (staleRevision !== null) {
      if (!window.confirm(`Caricare la revisione ${staleRevision}? Le modifiche non inviate andranno perse.`)) return;
      localStorage.removeItem(storageKey);
      try {
        await loadSession();
        showToast(`Aggiornato alla revisione ${model.revision}.`);
      } catch (error) {
        showToast(error.message || "Ricarica non riuscita", true);
      }
      return;
    }
    if (!window.confirm("Ripristinare i testi della revisione corrente e rimuovere i commenti non inviati?")) return;
    localStorage.removeItem(storageKey);
    hydrateDraft();
    renderAll();
    showToast("Bozza locale ripristinata.");
  });
  elements.sendButton.addEventListener("click", () => submit("feedback"));
  elements.approveButton.addEventListener("click", () => elements.approvalDialog.showModal());
  elements.confirmApproval.addEventListener("click", () => {
    elements.approvalDialog.close();
    submit("approve");
  });
  elements.saveComment.addEventListener("click", (event) => {
    event.preventDefault();
    const feedback = elements.commentFeedback.value.trim();
    if (!pendingSelection || !feedback) {
      showToast("Scrivi il commento prima di aggiungerlo.", true);
      return;
    }
    selectionComments.push({
      id: `selection-${crypto.randomUUID()}`,
      kind: "selection",
      ...pendingSelection,
      feedback,
    });
    pendingSelection = null;
    elements.dialog.close();
    renderComments();
    persistDraft();
  });

  loadSession()
    .catch((error) => {
      elements.loading.replaceChildren(create("p", "", error.message || "Impossibile aprire l'editor."));
      showToast(error.message || "Impossibile aprire l'editor", true);
    });
  window.setInterval(pollStatus, 2000);
})();

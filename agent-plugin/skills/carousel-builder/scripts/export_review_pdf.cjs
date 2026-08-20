#!/usr/bin/env node
"use strict";

const fs = require("node:fs/promises");
const fsNative = require("node:fs");
const { constants: fsConstants } = fsNative;
const os = require("node:os");
const path = require("node:path");
const { createHash, randomUUID } = require("node:crypto");
const { createRequire } = require("node:module");

const CONTRACT = "approved-preview-dom-v2";
const EXPORT_WIDTH = 1440;
const EXPORT_HEIGHT = 1800;
const CONTACT_SHEET_COLUMNS = 4;
const CONTACT_SHEET_GAP = 24;
const CONTACT_SHEET_MARGIN = 24;
const CONTACT_SHEET_THUMB_WIDTH = 360;
const CONTACT_SHEET_THUMB_HEIGHT = 450;
const DETERMINISTIC_PDF_DATE = new Date("2000-01-01T00:00:00.000Z");
const CURRENT_SCHEMA_VERSION = "1.4";
const EXPORT_WORKFLOW_STATE = "rendering";
const LIVE_SESSION_TIMEOUT_MS = 10_000;
const MAX_SIDECAR_BYTES = 64 * 1024;
const ACTIVE_EXPORT_RUN_IDS = new Set();
const ALLOWED_ARGS = new Set([
  "url",
  "output",
  "node-modules",
  "chrome",
  "png-dir",
  "contact-sheet",
  "result-json",
]);
const APPROVED_WORKFLOW_STATES = new Set([EXPORT_WORKFLOW_STATE]);
const CONTENT_SNAPSHOT_KEYS = [
  "revision",
  "workflow_state",
  "visual_style_system",
  "logo_mode",
  "slides",
  "format",
  "typography",
  "brand",
  "cover_visual",
  "proof",
  "production",
  "render_fingerprint",
];

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) throw new Error(`Argomento inatteso: ${key}`);
    const name = key.slice(2);
    if (!ALLOWED_ARGS.has(name)) throw new Error(`Argomento non supportato: ${key}`);
    if (Object.prototype.hasOwnProperty.call(result, name)) throw new Error(`Argomento duplicato: ${key}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Valore mancante per ${key}`);
    result[name] = value;
    index += 1;
  }
  for (const required of ["url", "output", "node-modules", "result-json"]) {
    if (!result[required]) throw new Error(`Argomento obbligatorio mancante: --${required}`);
  }
  return result;
}

function pathApi(platform = process.platform) {
  return platform === "win32" ? path.win32 : path.posix;
}

function unicodeCaseFold(value) {
  return String(value).normalize("NFC").toUpperCase().toLowerCase().normalize("NFC");
}

function normalizedPathIdentity(value, platform = process.platform) {
  if (!value) return "";
  let normalized = pathApi(platform).normalize(String(value)).normalize("NFC");
  if (["darwin", "win32"].includes(platform)) normalized = unicodeCaseFold(normalized);
  return normalized;
}

function samePath(left, right, platform = process.platform) {
  if (!left || !right) return false;
  return normalizedPathIdentity(left, platform) === normalizedPathIdentity(right, platform);
}

function pathContains(parent, child, platform = process.platform) {
  if (!parent || !child || samePath(parent, child, platform)) return false;
  const platformPath = pathApi(platform);
  const relative = platformPath.relative(
    normalizedPathIdentity(parent, platform),
    normalizedPathIdentity(child, platform),
  );
  return Boolean(
    relative
    && relative !== ".."
    && !relative.startsWith(`..${platformPath.sep}`)
    && !platformPath.isAbsolute(relative)
  );
}

function canonicalTargetPath(
  target,
  {
    platform = process.platform,
    realpathSync = fsNative.realpathSync.native || fsNative.realpathSync,
  } = {},
) {
  const platformPath = pathApi(platform);
  const absolute = platformPath.resolve(target);
  if (platform !== process.platform) return absolute.normalize("NFC");
  const basename = platformPath.basename(absolute);
  let parent = platformPath.dirname(absolute);
  const missing = [];
  while (true) {
    try {
      const realParent = realpathSync(parent);
      return platformPath.join(realParent, ...missing, basename).normalize("NFC");
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const next = platformPath.dirname(parent);
      if (samePath(next, parent, platform)) throw error;
      missing.unshift(platformPath.basename(parent));
      parent = next;
    }
  }
}

function existingTargetIdentity(target, platform = process.platform) {
  if (platform !== process.platform) return null;
  try {
    const metadata = fsNative.statSync(target);
    const realpath = (fsNative.realpathSync.native || fsNative.realpathSync)(target);
    return {
      dev: metadata.dev,
      ino: metadata.ino,
      realpath: normalizedPathIdentity(realpath, platform),
    };
  } catch (error) {
    if (["ENOENT", "ENOTDIR"].includes(error?.code)) return null;
    throw error;
  }
}

function sameCanonicalTarget(left, right, platform = process.platform) {
  if (!left || !right) return false;
  const leftCanonical = canonicalTargetPath(left, { platform });
  const rightCanonical = canonicalTargetPath(right, { platform });
  if (platform === "darwin") {
    const leftExisting = existingTargetIdentity(leftCanonical, platform);
    const rightExisting = existingTargetIdentity(rightCanonical, platform);
    if (leftExisting && rightExisting) {
      return (
        (leftExisting.dev === rightExisting.dev && leftExisting.ino === rightExisting.ino)
        || leftExisting.realpath === rightExisting.realpath
      );
    }
  }
  return samePath(leftCanonical, rightCanonical, platform);
}

function assertNoAmbiguousDarwinTarget(target, platform = process.platform) {
  if (platform !== "darwin" || platform !== process.platform) return;
  if (existingTargetIdentity(target, platform)) return;
  const parent = path.dirname(target);
  let entries;
  try {
    entries = fsNative.readdirSync(parent);
  } catch (error) {
    if (["ENOENT", "ENOTDIR"].includes(error?.code)) return;
    throw error;
  }
  const requested = normalizedPathIdentity(path.basename(target), platform);
  const ambiguous = entries.find(
    (entry) => normalizedPathIdentity(entry, platform) === requested,
  );
  if (ambiguous) {
    throw new Error(
      `Target Darwin ambiguo per case-fold o normalizzazione Unicode: ${target} collide con ${ambiguous}.`,
    );
  }
}

function isReservedSidecarComponent(component) {
  const normalized = String(component).normalize("NFC").toLowerCase();
  return (
    /^\..+\.export-staging\.json$/.test(normalized)
    || /^\..+\.export-transaction\.json$/.test(normalized)
    || /^\..+\.export-claim\.json$/.test(normalized)
    || normalized.endsWith(".committed")
  );
}

function usesReservedSidecarNamespace(target, platform = process.platform) {
  return pathApi(platform).normalize(target).split(/[\\/]+/u).some(isReservedSidecarComponent);
}

function resolveOutputTargets(
  args,
  {
    cwd = process.cwd(),
    home = os.homedir(),
    platform = process.platform,
  } = {},
) {
  const canonical = (value) => canonicalTargetPath(pathApi(platform).resolve(cwd, value), { platform });
  const output = canonical(args.output);
  const pngDir = args["png-dir"] ? canonical(args["png-dir"]) : null;
  const contactSheet = args["contact-sheet"] ? canonical(args["contact-sheet"]) : null;
  const resultJson = args["result-json"] ? canonical(args["result-json"]) : null;
  if (path.extname(output).toLowerCase() !== ".pdf") {
    throw new Error("Il percorso --output deve terminare con .pdf.");
  }
  if (contactSheet && path.extname(contactSheet).toLowerCase() !== ".png") {
    throw new Error("Il percorso --contact-sheet deve terminare con .png.");
  }
  if (resultJson && path.extname(resultJson).toLowerCase() !== ".json") {
    throw new Error("Il percorso --result-json deve terminare con .json.");
  }
  const fileTargets = [output, contactSheet, resultJson].filter(Boolean);
  const allTargets = [output, pngDir, contactSheet, resultJson].filter(Boolean);
  for (const target of allTargets) {
    if (usesReservedSidecarNamespace(target, platform)) {
      throw new Error(
        "I target di export non possono usare il namespace globale dei sidecar di staging, recovery o claim.",
      );
    }
    assertNoAmbiguousDarwinTarget(target, platform);
  }
  for (let left = 0; left < fileTargets.length; left += 1) {
    for (let right = left + 1; right < fileTargets.length; right += 1) {
      if (
        sameCanonicalTarget(fileTargets[left], fileTargets[right], platform)
        || pathContains(fileTargets[left], fileTargets[right], platform)
        || pathContains(fileTargets[right], fileTargets[left], platform)
      ) {
        throw new Error("PDF, contact sheet e result JSON devono usare percorsi distinti e non annidati.");
      }
    }
  }
  if (pngDir) {
    const protectedDirectories = [
      pathApi(platform).parse(pngDir).root,
      canonicalTargetPath(cwd, { platform }),
      home ? canonicalTargetPath(home, { platform }) : null,
    ].filter(Boolean);
    if (protectedDirectories.some((candidate) => samePath(pngDir, candidate, platform))) {
      throw new Error("La directory --png-dir non può essere la radice, la home o la directory di lavoro corrente.");
    }
    if (
      sameCanonicalTarget(pngDir, output, platform)
      || sameCanonicalTarget(pngDir, contactSheet, platform)
      || sameCanonicalTarget(pngDir, resultJson, platform)
      || pathContains(pngDir, output, platform)
      || pathContains(pngDir, contactSheet, platform)
      || pathContains(pngDir, resultJson, platform)
      || pathContains(output, pngDir, platform)
      || pathContains(contactSheet, pngDir, platform)
      || pathContains(resultJson, pngDir, platform)
    ) {
      throw new Error("PDF, contact sheet e --png-dir devono usare target separati e non annidati.");
    }
  }
  return { output, pngDir, contactSheet, resultJson };
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function exportArtifactDigests({ output, pdfBytes, pngDir, pngSlides = [], contactSheet, contactSheetBytes }) {
  return [
    { kind: "pdf", path: output, sha256: sha256(pdfBytes) },
    ...(pngDir ? pngSlides.map((slide) => ({
      kind: "png",
      path: path.join(pngDir, slide.filename),
      sha256: sha256(slide.bytes),
    })) : []),
    ...(contactSheet && contactSheetBytes ? [{
      kind: "contact_sheet",
      path: contactSheet,
      sha256: sha256(contactSheetBytes),
    }] : []),
  ];
}

function buildExportResult({
  output,
  pngDir,
  contactSheet,
  resultJson,
  contract,
  browserLabel,
  browser,
  artifactSha256,
}) {
  return {
    result_schema: "carousel-builder-export-v1",
    status: "ok",
    output,
    slides: contract.frames.length,
    width: EXPORT_WIDTH,
    height: EXPORT_HEIGHT,
    contract: CONTRACT,
    revision: contract.revision,
    workflow_state: contract.workflowState,
    style_system: contract.styleSystem,
    render_fingerprint: contract.contentSnapshot.render_fingerprint,
    browser: browserLabel,
    proof_browser: browser,
    preview_production_parity: "exact",
    pixel_comparison: "raw-rgba-1440x1800",
    final_pixel_recheck: "production-digest-against-initial-parity",
    live_session_verified: true,
    approval_verified: true,
    artifact_sha256: artifactSha256,
    ...(pngDir ? { png_dir: pngDir, png_files: artifactSha256.filter(({ kind }) => kind === "png").length } : {}),
    ...(contactSheet ? { contact_sheet: contactSheet } : {}),
    ...(resultJson ? { result_json: resultJson } : {}),
  };
}

function slidePngFilename(frame, index, total) {
  const normalized = String(frame?.id || "slide")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72) || "slide";
  const width = Math.max(2, String(total).length);
  return `${String(index + 1).padStart(width, "0")}-${normalized}.png`;
}

function safeLocalUrl(rawUrl) {
  const url = new URL(rawUrl);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
    throw new Error("L’export accetta soltanto un editor locale su http://127.0.0.1 o localhost.");
  }
  if (url.username || url.password) throw new Error("L’URL dell’editor non può contenere credenziali.");
  if (!url.searchParams.get("token")) throw new Error("L’URL dell’editor non contiene il token di sessione.");
  return url;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalJson(value[key])]),
    );
  }
  return value;
}

function stableJson(value) {
  return JSON.stringify(canonicalJson(value));
}

function sameJson(left, right) {
  return stableJson(left) === stableJson(right);
}

function browserDescriptor(version) {
  if (typeof version !== "string") {
    throw new Error("La versione del browser di export non è disponibile.");
  }
  const match = version.match(/(?:^|[^0-9])(\d{1,3})(?=\.)/);
  const major = match ? Number.parseInt(match[1], 10) : NaN;
  if (!Number.isInteger(major) || major < 1 || major > 999) {
    throw new Error(`Versione browser di export non riconosciuta: ${version || "mancante"}.`);
  }
  return { engine: "chromium", major };
}

function validBrowserDescriptor(value) {
  return Boolean(
    value
    && typeof value === "object"
    && !Array.isArray(value)
    && Object.keys(value).length === 2
    && value.engine === "chromium"
    && Number.isInteger(value.major)
    && value.major >= 1
    && value.major <= 999
  );
}

function assertRenderContract(value, expectedProduction, label, currentBrowser = null) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Il contratto ${label} non è un oggetto valido.`);
  }
  if (value.contract !== CONTRACT) {
    throw new Error(`Contratto renderer ${label} non supportato; atteso ${CONTRACT}.`);
  }
  if (value.production !== expectedProduction) {
    throw new Error(`La modalità ${label} non dichiara correttamente production=${expectedProduction}.`);
  }
  if (!Number.isInteger(value.revision) || value.revision < 0) {
    throw new Error(`La revisione del contratto ${label} non è valida.`);
  }
  if (value.workflowState !== EXPORT_WORKFLOW_STATE) {
    throw new Error(
      `L’export attestante schema ${CURRENT_SCHEMA_VERSION} richiede workflow_state=${EXPORT_WORKFLOW_STATE}; `
      + `stato ricevuto: ${value.workflowState || "mancante"}.`,
    );
  }
  if (value.proofApproved !== true) {
    throw new Error(`L’export richiede proof.approved=true nel contratto ${label}.`);
  }
  if (typeof value.styleSystem !== "string" || !value.styleSystem) {
    throw new Error(`Il sistema visivo del contratto ${label} non è valido.`);
  }
  if (!value.contentSnapshot || typeof value.contentSnapshot !== "object" || Array.isArray(value.contentSnapshot)) {
    throw new Error(`Lo snapshot editoriale del contratto ${label} non è disponibile.`);
  }
  for (const key of CONTENT_SNAPSHOT_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(value.contentSnapshot, key)) {
      throw new Error(`Lo snapshot editoriale ${label} non contiene ${key}.`);
    }
  }
  if (
    value.contentSnapshot.revision !== value.revision
    || value.contentSnapshot.workflow_state !== value.workflowState
    || value.contentSnapshot.visual_style_system !== value.styleSystem
  ) {
    throw new Error(`Metadati e snapshot editoriale ${label} non coincidono.`);
  }
  if (!/^[0-9a-f]{64}$/i.test(value.contentSnapshot.render_fingerprint)) {
    throw new Error(`Il render_fingerprint dello snapshot ${label} non è uno SHA-256 valido.`);
  }
  const proof = value.contentSnapshot.proof;
  if (
    !proof
    || typeof proof !== "object"
    || Array.isArray(proof)
    || proof.preview_width !== 480
    || !Array.isArray(proof.slide_ids)
    || !Array.isArray(proof.required_slide_ids)
    || !validBrowserDescriptor(proof.browser)
  ) {
    throw new Error(`Il contratto di prova visuale ${label} non è valido o verificato.`);
  }
  if (currentBrowser && !sameJson(proof.browser, currentBrowser)) {
    throw new Error(
      `Il browser della prova visuale ${label} (${proof.browser.engine} ${proof.browser.major}) `
      + `non coincide con il browser di export (${currentBrowser.engine} ${currentBrowser.major}).`,
    );
  }
  const proofIds = new Set(proof.slide_ids);
  if (proofIds.size !== proof.slide_ids.length || proof.slide_ids.some((id) => typeof id !== "string" || !id)) {
    throw new Error(`Gli ID della prova visuale ${label} non sono validi o univoci.`);
  }
  if (!proof.required_slide_ids.length || !sameJson(proof.slide_ids, proof.required_slide_ids)) {
    throw new Error(`La prova visuale ${label} non include tutte le slide canoniche richieste.`);
  }
  const production = value.contentSnapshot.production;
  if (
    !production
    || typeof production !== "object"
    || Array.isArray(production)
    || production.mode !== "renderer"
    || production.producer !== CONTRACT
    || !Array.isArray(production.supported_style_systems)
    || !production.supported_style_systems.includes(value.styleSystem)
    || production.selected_style_supported !== true
  ) {
    throw new Error(`Il contratto di produzione ${label} non supporta il sistema visivo selezionato.`);
  }
  if (!Array.isArray(value.frames) || !value.frames.length) {
    throw new Error(`Il contratto ${label} non contiene slide catturabili.`);
  }
  if (!Array.isArray(value.geometry) || value.geometry.length !== value.frames.length) {
    throw new Error(`La geometria del contratto ${label} non coincide con il numero di slide.`);
  }
  const frameIds = new Set();
  for (const frame of value.frames) {
    if (
      !frame
      || typeof frame.id !== "string"
      || !frame.id
      || !Number.isFinite(frame.width)
      || !Number.isFinite(frame.height)
      || frame.width <= 0
      || frame.height <= 0
    ) {
      throw new Error(`Il contratto ${label} contiene una slide non catturabile.`);
    }
    if (frameIds.has(frame.id)) {
      throw new Error(`Il contratto ${label} contiene un ID slide duplicato: ${frame.id}.`);
    }
    frameIds.add(frame.id);
  }
  if ([...proofIds].some((id) => !frameIds.has(id))) {
    throw new Error(`Gli ID della prova visuale ${label} non appartengono alle slide renderizzate.`);
  }
  const canonicalProofIds = value.frames
    .map(({ id }) => id)
    .filter((id) => proofIds.has(id));
  if (!sameJson(canonicalProofIds, proof.slide_ids)) {
    throw new Error(`Gli ID della prova visuale ${label} non rispettano l’ordine canonico delle slide.`);
  }
}

function validateContract(reference, production, currentBrowser = null) {
  assertRenderContract(reference, false, "anteprima", currentBrowser);
  assertRenderContract(production, true, "produzione", currentBrowser);
  if (reference.revision !== production.revision) {
    throw new Error("La revisione dell’anteprima non coincide con quella di produzione.");
  }
  if (reference.workflowState !== production.workflowState) {
    throw new Error("Lo stato approvato dell’anteprima non coincide con quello di produzione.");
  }
  if (reference.styleSystem !== production.styleSystem) {
    throw new Error("Il sistema visivo dell’anteprima non coincide con quello di produzione.");
  }
  if (!sameJson(reference.contentSnapshot, production.contentSnapshot)) {
    throw new Error("Lo snapshot editoriale dell’anteprima non coincide con quello di produzione.");
  }
  if (reference.frames.length !== production.frames.length) {
    throw new Error("Il numero di slide dell’anteprima non coincide con quello di produzione.");
  }
  const referenceIds = reference.frames.map(({ id }) => id);
  const productionIds = production.frames.map(({ id }) => id);
  if (!sameJson(referenceIds, productionIds)) {
    throw new Error("L’ordine delle slide dell’anteprima non coincide con quello di produzione.");
  }
  for (const frame of production.frames) {
    const ratio = frame.width / frame.height;
    if (Math.abs(ratio - 0.8) > 0.0005) {
      throw new Error(`La slide ${frame.id || "senza id"} non rispetta il rapporto 4:5.`);
    }
  }
  if (!sameJson(reference.geometry, production.geometry)) {
    throw new Error("Preview/production geometry mismatch: il PDF non replicherebbe l’anteprima approvata.");
  }
}

function validateStableContract(initial, current, label) {
  if (!sameJson(initial, current)) {
    throw new Error(`Il contratto ${label} è cambiato durante l’export; il PDF non viene pubblicato.`);
  }
}

async function waitForContract(page, production) {
  await page.waitForFunction(
    ({ expectedProduction }) => {
      const root = document.documentElement;
      return Boolean(
        root.dataset.productionError
        || (root.dataset.previewReady === "true"
          && (!expectedProduction || root.dataset.productionReady === "true")),
      );
    },
    { expectedProduction: production },
    { timeout: 30_000 },
  );
  const error = await page.evaluate(() => document.documentElement.dataset.productionError || "");
  if (error) throw new Error(error);
  return page.evaluate(() => {
    const api = window.carouselBuilderPreview;
    if (!api || typeof api.getRenderContract !== "function") {
      throw new Error("Contratto getRenderContract dell’anteprima non disponibile.");
    }
    return api.getRenderContract();
  });
}

async function fetchLiveSession(
  baseUrl,
  fetchImpl = globalThis.fetch,
  {
    timeoutMs = LIVE_SESSION_TIMEOUT_MS,
    AbortControllerImpl = globalThis.AbortController,
  } = {},
) {
  if (typeof fetchImpl !== "function") {
    throw new Error("Il runtime Node non espone fetch per la verifica live della sessione.");
  }
  if (typeof AbortControllerImpl !== "function") {
    throw new Error("Il runtime Node non espone AbortController per la verifica live della sessione.");
  }
  const authenticatedUrl = (pathname) => {
    const value = new URL(pathname, baseUrl);
    value.searchParams.set("token", baseUrl.searchParams.get("token"));
    return value;
  };
  const sessionUrl = authenticatedUrl("/api/session");
  const statusUrl = authenticatedUrl("/api/status");
  const controller = new AbortControllerImpl();
  let timeoutId;
  let timedOut = false;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new Error(`timeout totale di ${timeoutMs} ms`));
    }, timeoutMs);
  });
  let phase = "request";
  try {
    const request = (url) => fetchImpl(url, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-store",
        Pragma: "no-cache",
      },
    });
    const responses = await Promise.race([
      Promise.all([request(sessionUrl), request(statusUrl)]),
      timeout,
    ]);
    for (const response of responses) {
      if (!response?.ok) {
        throw new Error(
          `Verifica live della sessione rifiutata con HTTP ${response?.status || "sconosciuto"}.`,
        );
      }
    }
    phase = "body";
    const [session, status] = await Promise.race([
      Promise.all(responses.map((response) => response.json())),
      timeout,
    ]);
    if (
      !status
      || typeof status !== "object"
      || Array.isArray(status)
      || status.workflow_state !== session?.workflow_state
      || status.manifest_revision !== session?.revision
    ) {
      throw new Error("Sessione e stato live non coincidono.");
    }
    return { ...session, feedback_pending: status.feedback_pending };
  } catch (error) {
    if (timedOut || error?.name === "AbortError") {
      throw new Error(
        `Verifica live della sessione scaduta dopo ${timeoutMs} ms (richiesta e body JSON).`,
      );
    }
    if (String(error?.message || "").startsWith("Verifica live della sessione rifiutata")) {
      throw error;
    }
    throw new Error(
      phase === "body"
        ? `Risposta live della sessione non valida: ${conciseError(error)}.`
        : `Verifica live della sessione non riuscita: ${conciseError(error)}.`,
    );
  } finally {
    clearTimeout(timeoutId);
    controller.abort();
  }
}

function expectedOutputsForTargets({ pngDir = null, contactSheet = null } = {}) {
  return [
    "pdf",
    ...(pngDir ? ["png"] : []),
    ...(contactSheet ? ["contact_sheet"] : []),
  ].sort();
}

function assertExportPreflight(live, targets, label = "prima del browser") {
  if (!live || typeof live !== "object" || Array.isArray(live)) {
    throw new Error(`La sessione live ${label} non è valida.`);
  }
  if (live.schema_version !== CURRENT_SCHEMA_VERSION) {
    throw new Error(
      `L’export attestante richiede schema_version=${CURRENT_SCHEMA_VERSION} ${label}.`,
    );
  }
  if (live.workflow_state !== EXPORT_WORKFLOW_STATE) {
    throw new Error(
      `L’export attestante richiede workflow_state=${EXPORT_WORKFLOW_STATE} ${label}.`,
    );
  }
  if (live.feedback_pending !== false) {
    throw new Error(`La sessione live ${label} deve dichiarare feedback_pending=false.`);
  }
  if (live.proof_approved !== true) {
    throw new Error(`La sessione live ${label} non conferma proof.approved=true.`);
  }
  const production = live.production;
  if (
    !production
    || typeof production !== "object"
    || Array.isArray(production)
    || production.mode !== "renderer"
    || production.producer !== CONTRACT
  ) {
    throw new Error(`La sessione live ${label} non usa il renderer locale ${CONTRACT}.`);
  }
  const expected = expectedOutputsForTargets(targets);
  const declared = Array.isArray(production.expected_outputs)
    ? [...production.expected_outputs].sort()
    : null;
  if (!declared || !sameJson(declared, expected)) {
    throw new Error(
      `production.expected_outputs ${label} deve coincidere esattamente con ${expected.join(", ")}.`,
    );
  }
}

function assertLiveSession(live, reference, production, label) {
  if (!live || typeof live !== "object" || Array.isArray(live)) {
    throw new Error(`La sessione live ${label} non è valida.`);
  }
  if (live.proof_approved !== true) {
    throw new Error(`La sessione live ${label} non conferma proof.approved=true.`);
  }
  if (live.schema_version !== CURRENT_SCHEMA_VERSION) {
    throw new Error(`La sessione live ${label} non usa schema_version=${CURRENT_SCHEMA_VERSION}.`);
  }
  if (live.feedback_pending !== false) {
    throw new Error(`La sessione live ${label} deve dichiarare feedback_pending=false.`);
  }
  if (live.workflow_state !== EXPORT_WORKFLOW_STATE) {
    throw new Error(`La sessione live ${label} non è nello stato ${EXPORT_WORKFLOW_STATE}.`);
  }
  if (
    live.workflow_state !== reference.contentSnapshot.workflow_state
    || live.workflow_state !== production.contentSnapshot.workflow_state
  ) {
    throw new Error(`Lo stato della sessione live ${label} non coincide con gli snapshot approvati.`);
  }
  if (
    live.revision !== reference.contentSnapshot.revision
    || live.revision !== production.contentSnapshot.revision
  ) {
    throw new Error(`La revisione della sessione live ${label} non coincide con gli snapshot approvati.`);
  }
  if (!/^[0-9a-f]{64}$/i.test(live.render_fingerprint || "")) {
    throw new Error(`Il render_fingerprint della sessione live ${label} non è uno SHA-256 valido.`);
  }
  if (
    live.render_fingerprint !== reference.contentSnapshot.render_fingerprint
    || live.render_fingerprint !== production.contentSnapshot.render_fingerprint
  ) {
    throw new Error(`Il render_fingerprint della sessione live ${label} non coincide con gli snapshot approvati.`);
  }
  if (
    !sameJson(live.proof, reference.contentSnapshot.proof)
    || !sameJson(live.proof, production.contentSnapshot.proof)
  ) {
    throw new Error(`Il contratto di prova della sessione live ${label} non coincide con gli snapshot approvati.`);
  }
  if (
    !sameJson(live.production, reference.contentSnapshot.production)
    || !sameJson(live.production, production.contentSnapshot.production)
  ) {
    throw new Error(`Il contratto di produzione della sessione live ${label} non coincide con gli snapshot approvati.`);
  }
}

function uniqueCandidates(candidates, platform) {
  const seen = new Set();
  return candidates.filter((candidate) => {
    const key = candidate.executablePath
      ? (platform === "win32" ? candidate.executablePath.toLowerCase() : candidate.executablePath)
      : "<playwright-managed>";
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function browserCandidates({ explicitPath, platform = process.platform, env = process.env } = {}) {
  if (explicitPath) {
    return [{ label: "percorso --chrome", executablePath: path.resolve(explicitPath), explicit: true }];
  }
  const candidates = [];
  if (platform === "darwin") {
    candidates.push(
      { label: "Google Chrome", executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" },
      { label: "Chromium", executablePath: "/Applications/Chromium.app/Contents/MacOS/Chromium" },
      { label: "Microsoft Edge", executablePath: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" },
    );
  } else if (platform === "win32") {
    const roots = [env.PROGRAMFILES, env["PROGRAMFILES(X86)"], env.LOCALAPPDATA].filter(Boolean);
    for (const root of roots) {
      candidates.push(
        { label: "Google Chrome", executablePath: path.win32.join(root, "Google", "Chrome", "Application", "chrome.exe") },
        { label: "Microsoft Edge", executablePath: path.win32.join(root, "Microsoft", "Edge", "Application", "msedge.exe") },
      );
    }
  } else {
    candidates.push(
      { label: "Google Chrome", executablePath: "/usr/bin/google-chrome" },
      { label: "Google Chrome Stable", executablePath: "/usr/bin/google-chrome-stable" },
      { label: "Chromium", executablePath: "/usr/bin/chromium" },
      { label: "Chromium Browser", executablePath: "/usr/bin/chromium-browser" },
      { label: "Microsoft Edge", executablePath: "/usr/bin/microsoft-edge" },
    );
  }
  candidates.push({ label: "browser gestito da Playwright", executablePath: null });
  return uniqueCandidates(candidates, platform);
}

function conciseError(error) {
  return String(error?.message || error || "errore sconosciuto").split("\n")[0];
}

async function launchBrowser(
  chromium,
  {
    explicitPath,
    platform = process.platform,
    env = process.env,
    access = fs.access,
    expectedBrowser = null,
  } = {},
) {
  if (expectedBrowser && !validBrowserDescriptor(expectedBrowser)) {
    throw new Error("Il browser associato alla prova visuale non è valido.");
  }
  const failures = [];
  for (const candidate of browserCandidates({ explicitPath, platform, env })) {
    let browser = null;
    if (candidate.executablePath) {
      try {
        await access(candidate.executablePath, platform === "win32" ? fsConstants.F_OK : fsConstants.X_OK);
      } catch (error) {
        failures.push(`${candidate.label}: non trovato o non eseguibile (${candidate.executablePath})`);
        if (candidate.explicit) break;
        continue;
      }
    }
    try {
      browser = await chromium.launch({
        ...(candidate.executablePath ? { executablePath: candidate.executablePath } : {}),
        headless: true,
        args: ["--disable-gpu", "--font-render-hinting=none"],
      });
      if (expectedBrowser) {
        const actualBrowser = browserDescriptor(await browser.version());
        if (!sameJson(actualBrowser, expectedBrowser)) {
          failures.push(
            `${candidate.label}: versione ${actualBrowser.major}, `
            + `ma la prova richiede Chromium ${expectedBrowser.major}`,
          );
          await browser.close().catch(() => {});
          browser = null;
          if (candidate.explicit) break;
          continue;
        }
      }
      return { browser, browserLabel: candidate.label };
    } catch (error) {
      if (browser) await browser.close().catch(() => {});
      failures.push(`${candidate.label}: ${conciseError(error)}`);
      if (candidate.explicit) break;
    }
  }
  throw new Error(
    `Impossibile avviare un browser compatibile. ${failures.join("; ")}. `
    + "Indica un eseguibile esistente con --chrome oppure configura il browser di Playwright.",
  );
}

async function createExclusiveTemporaryOutput(
  output,
  { fsApi = fs, randomId = randomUUID } = {},
) {
  const outputDir = path.dirname(output);
  const basename = path.basename(output);
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const temporaryPath = path.join(outputDir, `.${basename}.${process.pid}.${randomId()}.tmp`);
    try {
      const handle = await fsApi.open(temporaryPath, "wx", 0o600);
      return { handle, temporaryPath };
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
    }
  }
  throw new Error("Impossibile riservare un file PDF temporaneo esclusivo.");
}

async function moveExistingOutputToBackup(
  output,
  { fsApi = fs, randomId = randomUUID } = {},
) {
  const outputDir = path.dirname(output);
  const basename = path.basename(output);
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const backupPath = path.join(outputDir, `.${basename}.${randomId()}.previous`);
    try {
      await fsApi.rename(output, backupPath);
      return backupPath;
    } catch (error) {
      if (error?.code === "ENOENT") return null;
      if (error?.code === "EEXIST") continue;
      throw error;
    }
  }
  throw new Error("Impossibile riservare il backup temporaneo del PDF precedente.");
}

async function fsyncDirectory(
  directory,
  { fsApi = fs, platform = process.platform } = {},
) {
  if (platform === "win32") return;
  const handle = await fsApi.open(directory, "r");
  try {
    if (typeof handle.sync !== "function") {
      throw new Error(`Il runtime non consente di sincronizzare la directory ${directory}.`);
    }
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function replaceFilePortable(
  temporaryPath,
  output,
  { fsApi = fs, platform = process.platform, randomId = randomUUID } = {},
) {
  if (platform !== "win32") {
    await fsApi.rename(temporaryPath, output);
    await fsyncDirectory(path.dirname(output), { fsApi, platform });
    return;
  }

  const backupPath = await moveExistingOutputToBackup(output, { fsApi, randomId });
  try {
    await fsApi.rename(temporaryPath, output);
  } catch (error) {
    if (backupPath) {
      try {
        await fsApi.rename(backupPath, output);
      } catch (rollbackError) {
        throw new Error(
          `Sostituzione PDF fallita (${conciseError(error)}); anche il ripristino è fallito `
          + `(${conciseError(rollbackError)}). Il PDF precedente resta in ${backupPath}.`,
        );
      }
    }
    throw error;
  }
  if (backupPath) await fsApi.rm(backupPath, { force: true });
}

async function writePdfAtomically(
  output,
  bytes,
  {
    fsApi = fs,
    platform = process.platform,
    randomId = randomUUID,
    beforeReplace,
  } = {},
) {
  await fsApi.mkdir(path.dirname(output), { recursive: true });
  let handle;
  let temporaryPath;
  try {
    ({ handle, temporaryPath } = await createExclusiveTemporaryOutput(output, { fsApi, randomId }));
    await handle.writeFile(bytes);
    if (typeof handle.sync === "function") await handle.sync();
    await handle.close();
    handle = null;
    if (beforeReplace) await beforeReplace();
    await replaceFilePortable(temporaryPath, output, { fsApi, platform, randomId });
    temporaryPath = null;
  } finally {
    if (handle) await handle.close().catch(() => {});
    if (temporaryPath) {
      await fsApi.rm(temporaryPath, { force: true }).catch(() => {});
      await fsyncDirectory(path.dirname(temporaryPath), { fsApi, platform }).catch(() => {});
    }
  }
}

async function createExclusiveTemporaryDirectory(
  target,
  { fsApi = fs, randomId = randomUUID } = {},
) {
  const parent = path.dirname(target);
  const basename = path.basename(target);
  await fsApi.mkdir(parent, { recursive: true });
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const temporaryPath = path.join(parent, `.${basename}.${process.pid}.${randomId()}.tmp`);
    try {
      await fsApi.mkdir(temporaryPath, { mode: 0o700 });
      return temporaryPath;
    } catch (error) {
      if (error?.code !== "EEXIST") throw error;
    }
  }
  throw new Error("Impossibile riservare una directory temporanea esclusiva per i PNG.");
}

async function writeDurableFile(target, bytes, { fsApi = fs } = {}) {
  const handle = await fsApi.open(target, "wx", 0o600);
  try {
    await handle.writeFile(bytes);
    if (typeof handle.sync === "function") await handle.sync();
  } finally {
    await handle.close();
  }
}

async function assertCompatibleExistingTarget(target, kind, { fsApi = fs } = {}) {
  let stat;
  try {
    stat = await fsApi.lstat(target);
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
  if (stat.isSymbolicLink()) {
    throw new Error(`Il target di export non può essere un link simbolico: ${target}`);
  }
  const compatible = kind === "directory" ? stat.isDirectory() : stat.isFile();
  if (!compatible) {
    throw new Error(
      kind === "directory"
        ? `La destinazione PNG esistente non è una directory: ${target}`
        : `La destinazione file esistente non è un file regolare: ${target}`,
    );
  }
  if (kind === "directory") {
    const entries = await fsApi.readdir(target, { withFileTypes: true });
    const unsafeEntry = entries.find((entry) => !entry.isFile() || !entry.name.toLowerCase().endsWith(".png"));
    if (unsafeEntry) {
      throw new Error(
        `La destinazione --png-dir contiene elementi non gestiti (${unsafeEntry.name}); usa una directory dedicata ai soli PNG.`,
      );
    }
  }
  return true;
}

async function removeKnownArtifact(
  target,
  kind,
  { fsApi = fs, platform = process.platform } = {},
) {
  await fsApi.rm(target, { recursive: kind === "directory", force: true });
  await fsyncDirectory(path.dirname(target), { fsApi, platform });
}

function exportTransactionPaths(primaryOutput) {
  const journalPath = path.join(
    path.dirname(primaryOutput),
    `.${path.basename(primaryOutput)}.export-transaction.json`,
  );
  return { journalPath, commitPath: `${journalPath}.committed` };
}

function exportStagingPath(primaryOutput) {
  return path.join(
    path.dirname(primaryOutput),
    `.${path.basename(primaryOutput)}.export-staging.json`,
  );
}

function exportClaimPath(finalTarget) {
  return path.join(
    path.dirname(finalTarget),
    `.${path.basename(finalTarget)}.export-claim.json`,
  );
}

function stableStatSignature(metadata) {
  return [
    metadata.dev,
    metadata.ino,
    metadata.size,
    metadata.mtimeMs,
    metadata.ctimeMs,
    metadata.nlink,
  ];
}

function assertSecureSidecarMetadata(metadata, label, maxBytes) {
  if (
    !metadata
    || !metadata.isFile()
    || metadata.isSymbolicLink()
    || metadata.nlink !== 1
    || metadata.size < 1
    || metadata.size > maxBytes
  ) {
    throw new Error(`${label} non sicuro.`);
  }
}

function assertLinkedSidecarMetadata(metadata, label, maxBytes) {
  if (
    !metadata
    || !metadata.isFile()
    || metadata.isSymbolicLink()
    || metadata.nlink !== 2
    || metadata.size < 1
    || metadata.size > maxBytes
  ) {
    throw new Error(`${label}: twin di publish non sicuro.`);
  }
}

function sidecarOwnershipId(target, bytes, label) {
  const basename = path.basename(target).normalize("NFC").toLowerCase();
  let ownershipId = null;
  if (basename.endsWith(".export-transaction.json.committed")) {
    const value = bytes.toString("utf8");
    if (/^[A-Za-z0-9_-]{1,128}\n$/.test(value)) ownershipId = value.slice(0, -1);
  } else if (
    basename.endsWith(".export-claim.json")
    || basename.endsWith(".export-staging.json")
    || basename.endsWith(".export-transaction.json")
  ) {
    try {
      const value = JSON.parse(bytes.toString("utf8"));
      ownershipId = basename.endsWith(".export-transaction.json")
        ? value?.transaction_id
        : value?.run_id;
    } catch {
      ownershipId = null;
    }
  }
  if (typeof ownershipId !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(ownershipId)) {
    throw new Error(`${label} non sicuro: twin di publish privo di ownership valida.`);
  }
  return ownershipId;
}

function escapedRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function recoverDurablePublishTwin(
  target,
  {
    fsApi = fs,
    platform = process.platform,
    label = "Sidecar export",
    maxBytes = MAX_SIDECAR_BYTES,
    expectedOwnershipId = null,
  } = {},
) {
  let initial;
  try {
    initial = await fsApi.lstat(target);
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
  if (initial.nlink === 1) return false;
  assertLinkedSidecarMetadata(initial, label, maxBytes);

  const flags = fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW || 0);
  let targetHandle;
  let twinHandle;
  try {
    targetHandle = await fsApi.open(target, flags);
    const opened = await targetHandle.stat();
    assertLinkedSidecarMetadata(opened, label, maxBytes);
    if (opened.dev !== initial.dev || opened.ino !== initial.ino) {
      throw new Error(`${label}: target cambiato durante il recupero del twin.`);
    }
    const targetBytes = await targetHandle.readFile();
    const afterRead = await targetHandle.stat();
    const afterPath = await fsApi.lstat(target);
    for (const metadata of [opened, afterRead, afterPath]) {
      assertLinkedSidecarMetadata(metadata, label, maxBytes);
      if (!sameJson(stableStatSignature(metadata), stableStatSignature(initial))) {
        throw new Error(`${label}: target instabile durante il recupero del twin.`);
      }
    }
    if (targetBytes.length !== initial.size) {
      throw new Error(`${label}: dimensione incoerente durante il recupero del twin.`);
    }
    const ownershipId = sidecarOwnershipId(target, targetBytes, label);
    if (expectedOwnershipId !== null && ownershipId !== expectedOwnershipId) {
      throw new Error(`${label}: ownership del twin non coincide con il run atteso.`);
    }

    const parent = path.dirname(target);
    const basename = path.basename(target);
    const candidatePattern = new RegExp(
      `^${escapedRegExp(basename)}\\.[1-9][0-9]{0,9}\\.${escapedRegExp(ownershipId)}\\.tmp$`,
    );
    const candidates = (await fsApi.readdir(parent)).filter((entry) => candidatePattern.test(entry));
    if (candidates.length !== 1) {
      throw new Error(`${label}: ownership twin ambigua o mancante.`);
    }
    const twinPath = path.join(parent, candidates[0]);
    twinHandle = await fsApi.open(twinPath, flags);
    const twinOpened = await twinHandle.stat();
    const twinPathStat = await fsApi.lstat(twinPath);
    for (const metadata of [twinOpened, twinPathStat]) {
      assertLinkedSidecarMetadata(metadata, label, maxBytes);
      if (
        metadata.dev !== initial.dev
        || metadata.ino !== initial.ino
        || !sameJson(stableStatSignature(metadata), stableStatSignature(initial))
      ) {
        throw new Error(`${label}: twin non appartiene al target pubblicato.`);
      }
    }
    const twinBytes = await twinHandle.readFile();
    const twinAfterRead = await twinHandle.stat();
    assertLinkedSidecarMetadata(twinAfterRead, label, maxBytes);
    if (
      !sameJson(stableStatSignature(twinAfterRead), stableStatSignature(initial))
      || !twinBytes.equals(targetBytes)
    ) {
      throw new Error(`${label}: contenuto o metadati del twin non coincidono.`);
    }
    await twinHandle.close();
    twinHandle = null;
    await targetHandle.close();
    targetHandle = null;

    const [beforeUnlinkTarget, beforeUnlinkTwin] = await Promise.all([
      fsApi.lstat(target),
      fsApi.lstat(twinPath),
    ]);
    for (const metadata of [beforeUnlinkTarget, beforeUnlinkTwin]) {
      assertLinkedSidecarMetadata(metadata, label, maxBytes);
      if (metadata.dev !== initial.dev || metadata.ino !== initial.ino) {
        throw new Error(`${label}: twin cambiato prima della pulizia.`);
      }
    }
    await fsApi.unlink(twinPath);
    await fsyncDirectory(parent, { fsApi, platform });
    const recovered = await fsApi.lstat(target);
    assertSecureSidecarMetadata(recovered, label, maxBytes);
    if (
      recovered.dev !== initial.dev
      || recovered.ino !== initial.ino
      || recovered.size !== initial.size
    ) {
      throw new Error(`${label}: target incoerente dopo il recupero del twin.`);
    }
    return true;
  } finally {
    if (twinHandle) await twinHandle.close().catch(() => {});
    if (targetHandle) await targetHandle.close().catch(() => {});
  }
}

async function readStableSidecar(
  target,
  {
    fsApi = fs,
    label = "Sidecar export",
    maxBytes = MAX_SIDECAR_BYTES,
    withMetadata = false,
  } = {},
) {
  let handle;
  try {
    await recoverDurablePublishTwin(target, {
      fsApi,
      label,
      maxBytes,
    });
    const before = await fsApi.lstat(target);
    assertSecureSidecarMetadata(before, label, maxBytes);
    const flags = fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW || 0);
    handle = await fsApi.open(target, flags);
    const opened = await handle.stat();
    assertSecureSidecarMetadata(opened, label, maxBytes);
    if (before.dev !== opened.dev || before.ino !== opened.ino) {
      throw new Error(`${label} è cambiato durante l’apertura.`);
    }
    const bytes = await handle.readFile();
    const afterHandle = await handle.stat();
    const afterPath = await fsApi.lstat(target);
    assertSecureSidecarMetadata(afterHandle, label, maxBytes);
    assertSecureSidecarMetadata(afterPath, label, maxBytes);
    const expected = stableStatSignature(before);
    for (const metadata of [opened, afterHandle, afterPath]) {
      if (!sameJson(stableStatSignature(metadata), expected)) {
        throw new Error(`${label} è cambiato durante la lettura.`);
      }
    }
    if (bytes.length !== before.size) {
      throw new Error(`${label} ha una dimensione incoerente.`);
    }
    return withMetadata ? { bytes, metadata: afterHandle } : bytes;
  } finally {
    if (handle) await handle.close().catch(() => {});
  }
}

async function readStableJsonSidecar(target, options = {}) {
  const label = options.label || "Sidecar JSON export";
  try {
    const result = await readStableSidecar(target, { ...options, label });
    if (options.withMetadata) {
      return {
        value: JSON.parse(result.bytes.toString("utf8")),
        metadata: result.metadata,
      };
    }
    return JSON.parse(result.toString("utf8"));
  } catch (error) {
    if (String(error?.message || "").startsWith(label)) throw error;
    throw new Error(`${label} non leggibile: ${conciseError(error)}.`);
  }
}

function validateExportStagingOwnership(
  marker,
  primaryOutput,
  expectedArtifacts,
  platform = process.platform,
) {
  if (
    !marker
    || typeof marker !== "object"
    || Array.isArray(marker)
    || marker.version !== 1
    || !sameCanonicalTarget(marker.primary_output, primaryOutput, platform)
    || !Number.isSafeInteger(marker.pid)
    || marker.pid < 1
    || typeof marker.run_id !== "string"
    || !/^[A-Za-z0-9_-]{1,128}$/.test(marker.run_id)
    || !Array.isArray(marker.artifacts)
    || marker.artifacts.length !== expectedArtifacts.length
  ) {
    throw new Error("Marker di staging export non valido.");
  }
  for (const [index, artifact] of marker.artifacts.entries()) {
    const expected = expectedArtifacts[index];
    const expectedTemporaryPath = path.join(
      path.dirname(expected.finalPath),
      `.${path.basename(expected.finalPath)}.${marker.pid}.${marker.run_id}.${index}.tmp`,
    );
    if (
      !artifact
      || artifact.kind !== expected.kind
      || !sameCanonicalTarget(artifact.finalPath, expected.finalPath, platform)
      || !sameCanonicalTarget(artifact.temporaryPath, expectedTemporaryPath, platform)
    ) {
      throw new Error(`Marker di staging export: artefatto ${index + 1} non valido.`);
    }
  }
  return marker;
}

function processIsRunning(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    if (error?.code === "EPERM") return true;
    throw error;
  }
}

async function readExportStagingOwnership(
  markerPath,
  primaryOutput,
  expectedArtifacts,
  { fsApi = fs, platform = process.platform } = {},
) {
  let marker;
  try {
    marker = await readStableJsonSidecar(markerPath, {
      fsApi,
      label: "Marker di staging export",
    });
  } catch (error) {
    throw new Error(`Marker di staging export non leggibile: ${conciseError(error)}.`);
  }
  return validateExportStagingOwnership(marker, primaryOutput, expectedArtifacts, platform);
}

async function recoverExportStagingOwnership(
  primaryOutput,
  {
    expectedArtifacts,
    fsApi = fs,
    platform = process.platform,
    isProcessRunning = processIsRunning,
    currentPid = process.pid,
    recoverableRunIds = new Set(),
    cleanup = true,
  } = {},
) {
  const markerPath = exportStagingPath(primaryOutput);
  if (!(await pathExists(markerPath, { fsApi }))) return false;
  const marker = await readExportStagingOwnership(
    markerPath,
    primaryOutput,
    expectedArtifacts,
    { fsApi, platform },
  );
  const markerIsActive = marker.pid === currentPid
    ? (
      ACTIVE_EXPORT_RUN_IDS.has(marker.run_id)
      || !recoverableRunIds.has(marker.run_id)
    )
    : isProcessRunning(marker.pid);
  if (markerIsActive) {
    throw new Error(`Un altro export è ancora attivo (PID ${marker.pid}).`);
  }
  if (!cleanup) return true;
  for (const artifact of marker.artifacts) {
    if (await pathExists(artifact.temporaryPath, { fsApi })) {
      await assertCompatibleExistingTarget(artifact.temporaryPath, artifact.kind, { fsApi });
      await removeKnownArtifact(artifact.temporaryPath, artifact.kind, { fsApi, platform });
    }
  }
  await removeDurableEntry(markerPath, { fsApi, platform });
  return true;
}

async function createExportStagingOwnership(
  primaryOutput,
  expectedArtifacts,
  {
    fsApi = fs,
    randomId = randomUUID,
    platform = process.platform,
    pid = process.pid,
    runId: requestedRunId = null,
  } = {},
) {
  const runId = String(requestedRunId || randomId());
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(runId)) {
    throw new Error("Identificatore dello staging export non valido.");
  }
  const marker = {
    version: 1,
    pid,
    run_id: runId,
    primary_output: primaryOutput,
    artifacts: expectedArtifacts.map((artifact, index) => ({
      ...artifact,
      temporaryPath: path.join(
        path.dirname(artifact.finalPath),
        `.${path.basename(artifact.finalPath)}.${pid}.${runId}.${index}.tmp`,
      ),
    })),
  };
  validateExportStagingOwnership(marker, primaryOutput, expectedArtifacts, platform);
  for (const artifact of marker.artifacts) {
    if (await pathExists(artifact.temporaryPath, { fsApi })) {
      throw new Error(`Il percorso riservato allo staging export esiste già: ${artifact.temporaryPath}`);
    }
  }
  const markerPath = exportStagingPath(primaryOutput);
  await writeDurableJsonExclusive(markerPath, marker, {
    fsApi,
    randomId,
    platform,
    ownershipId: runId,
  });
  return { marker, markerPath };
}

async function pathExists(target, { fsApi = fs } = {}) {
  try {
    await fsApi.lstat(target);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

function exportClaimBinding(primaryOutput, expectedArtifacts, platform = process.platform) {
  if (!Array.isArray(expectedArtifacts) || !expectedArtifacts.length || expectedArtifacts.length > 4) {
    throw new Error("Set degli artefatti del claim export non valido.");
  }
  const primary = canonicalTargetPath(primaryOutput, { platform });
  const artifacts = expectedArtifacts.map((artifact) => {
    if (
      !artifact
      || !["file", "directory"].includes(artifact.kind)
      || typeof artifact.finalPath !== "string"
    ) {
      throw new Error("Artefatto del claim export non valido.");
    }
    return {
      kind: artifact.kind,
      finalPath: canonicalTargetPath(artifact.finalPath, { platform }),
    };
  }).sort((left, right) => {
    const byPath = normalizedPathIdentity(left.finalPath, platform)
      .localeCompare(normalizedPathIdentity(right.finalPath, platform));
    return byPath || left.kind.localeCompare(right.kind);
  });
  for (let left = 0; left < artifacts.length; left += 1) {
    for (let right = left + 1; right < artifacts.length; right += 1) {
      if (sameCanonicalTarget(artifacts[left].finalPath, artifacts[right].finalPath, platform)) {
        throw new Error("Il set del claim export contiene target duplicati.");
      }
    }
  }
  if (!artifacts.some(
    (artifact) => artifact.kind === "file" && sameCanonicalTarget(artifact.finalPath, primary, platform),
  )) {
    throw new Error("Il primary output non appartiene al set del claim export.");
  }
  const digestPayload = {
    primary_output: normalizedPathIdentity(primary, platform),
    artifacts: artifacts.map((artifact) => ({
      kind: artifact.kind,
      final_path: normalizedPathIdentity(artifact.finalPath, platform),
    })),
  };
  return {
    primaryOutput: primary,
    artifacts,
    digest: sha256(Buffer.from(JSON.stringify(digestPayload))),
  };
}

function claimMatchesBinding(marker, binding, platform = process.platform) {
  if (
    !sameCanonicalTarget(marker.primary_output, binding.primaryOutput, platform)
    || marker.artifact_set_sha256 !== binding.digest
    || marker.artifacts.length !== binding.artifacts.length
  ) {
    return false;
  }
  return marker.artifacts.every((artifact, index) => (
    artifact.kind === binding.artifacts[index].kind
    && sameCanonicalTarget(artifact.final_path, binding.artifacts[index].finalPath, platform)
  ));
}

function validateExportClaim(marker, finalTarget, platform = process.platform) {
  if (
    !marker
    || typeof marker !== "object"
    || Array.isArray(marker)
    || marker.version !== 2
    || !Number.isSafeInteger(marker.pid)
    || marker.pid < 1
    || typeof marker.run_id !== "string"
    || !/^[A-Za-z0-9_-]{1,128}$/.test(marker.run_id)
    || typeof marker.primary_output !== "string"
    || !pathApi(platform).isAbsolute(marker.primary_output)
    || typeof marker.target !== "string"
    || !sameCanonicalTarget(marker.target, finalTarget, platform)
    || !Array.isArray(marker.artifacts)
    || !marker.artifacts.length
    || marker.artifacts.length > 4
    || typeof marker.artifact_set_sha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(marker.artifact_set_sha256)
  ) {
    throw new Error(`Claim export non valido per ${finalTarget}.`);
  }
  const artifacts = marker.artifacts.map((artifact) => {
    if (
      !artifact
      || typeof artifact !== "object"
      || Array.isArray(artifact)
      || !["file", "directory"].includes(artifact.kind)
      || typeof artifact.final_path !== "string"
      || !pathApi(platform).isAbsolute(artifact.final_path)
    ) {
      throw new Error(`Claim export non valido per ${finalTarget}.`);
    }
    return { kind: artifact.kind, finalPath: artifact.final_path };
  });
  const binding = exportClaimBinding(marker.primary_output, artifacts, platform);
  if (
    !claimMatchesBinding(marker, binding, platform)
    || !binding.artifacts.some((artifact) => sameCanonicalTarget(artifact.finalPath, finalTarget, platform))
  ) {
    throw new Error(`Claim export non valido per ${finalTarget}.`);
  }
  return marker;
}

async function readExportClaim(
  claimPath,
  finalTarget,
  { fsApi = fs, platform = process.platform } = {},
) {
  const marker = await readStableJsonSidecar(claimPath, {
    fsApi,
    label: "Claim export",
  });
  return validateExportClaim(marker, finalTarget, platform);
}

async function readExportClaimRecord(
  claimPath,
  finalTarget,
  { fsApi = fs, platform = process.platform } = {},
) {
  const record = await readStableJsonSidecar(claimPath, {
    fsApi,
    label: "Claim export",
    withMetadata: true,
  });
  return {
    marker: validateExportClaim(record.value, finalTarget, platform),
    metadata: record.metadata,
  };
}

async function restoreClaimReapFence(
  claim,
  { fsApi = fs, platform = process.platform } = {},
) {
  const parent = path.dirname(claim.claimPath);
  const fencePattern = new RegExp(
    `^${escapedRegExp(path.basename(claim.claimPath))}\\.[1-9][0-9]{0,9}\\.[A-Za-z0-9_-]{1,128}\\.reap$`,
  );
  const fences = (await fsApi.readdir(parent)).filter((entry) => fencePattern.test(entry));
  if (!fences.length) return false;
  if (fences.length !== 1) {
    throw new Error(`Fence di recovery claim ambiguo per ${claim.finalTarget}.`);
  }
  const fencePath = path.join(parent, fences[0]);
  const claimExists = await pathExists(claim.claimPath, { fsApi });
  if (claimExists) {
    const [current, fence] = await Promise.all([
      fsApi.lstat(claim.claimPath),
      fsApi.lstat(fencePath),
    ]);
    if (
      current.isSymbolicLink()
      || fence.isSymbolicLink()
      || !current.isFile()
      || !fence.isFile()
    ) {
      throw new Error(`Fence di recovery claim non sicuro per ${claim.finalTarget}.`);
    }
    if (current.dev === fence.dev && current.ino === fence.ino) {
      if (current.nlink !== 2 || fence.nlink !== 2) {
        throw new Error(`Fence di recovery claim incoerente per ${claim.finalTarget}.`);
      }
    } else {
      if (current.nlink !== 1 || fence.nlink !== 1) {
        throw new Error(`Fence di recovery claim incoerente per ${claim.finalTarget}.`);
      }
      const [currentMarker, fenceMarker] = await Promise.all([
        readExportClaim(claim.claimPath, claim.finalTarget, { fsApi, platform }),
        readExportClaim(fencePath, claim.finalTarget, { fsApi, platform }),
      ]);
      const currentBinding = bindingFromClaim(currentMarker, platform);
      if (!claimMatchesBinding(fenceMarker, currentBinding, platform)) {
        throw new Error(
          `Fence di recovery claim associato a un set diverso per ${claim.finalTarget}.`,
        );
      }
    }
    const fenceBeforeRemove = await fsApi.lstat(fencePath);
    if (fenceBeforeRemove.dev !== fence.dev || fenceBeforeRemove.ino !== fence.ino) {
      throw new Error(`Fence di recovery claim cambiato per ${claim.finalTarget}.`);
    }
    await fsApi.unlink(fencePath);
    await fsyncDirectory(parent, { fsApi, platform });
    return true;
  }

  const marker = await readExportClaim(fencePath, claim.finalTarget, { fsApi, platform });
  if (!marker) throw new Error(`Fence di recovery claim non valido per ${claim.finalTarget}.`);
  const fenceBefore = await fsApi.lstat(fencePath);
  if (
    !fenceBefore.isFile()
    || fenceBefore.isSymbolicLink()
    || fenceBefore.nlink !== 1
  ) {
    throw new Error(`Fence di recovery claim non sicuro per ${claim.finalTarget}.`);
  }
  try {
    await fsApi.link(fencePath, claim.claimPath);
  } catch (error) {
    if (error?.code === "EEXIST") return false;
    throw error;
  }
  const [restored, fence] = await Promise.all([
    fsApi.lstat(claim.claimPath),
    fsApi.lstat(fencePath),
  ]);
  if (
    restored.dev !== fence.dev
    || restored.ino !== fence.ino
    || restored.nlink !== 2
    || fence.nlink !== 2
  ) {
    throw new Error(`Fence di recovery claim cambiato durante il ripristino per ${claim.finalTarget}.`);
  }
  await fsApi.unlink(fencePath);
  await fsyncDirectory(parent, { fsApi, platform });
  return true;
}

async function fenceStaleExportClaim(
  claim,
  record,
  runId,
  { fsApi = fs, platform = process.platform, pid = process.pid } = {},
) {
  const fencePath = `${claim.claimPath}.${pid}.${runId}.reap`;
  await fsApi.link(claim.claimPath, fencePath);
  let claimUnlinked = false;
  try {
    const [current, fence] = await Promise.all([
      fsApi.lstat(claim.claimPath),
      fsApi.lstat(fencePath),
    ]);
    if (
      current.dev !== record.metadata.dev
      || current.ino !== record.metadata.ino
      || fence.dev !== record.metadata.dev
      || fence.ino !== record.metadata.ino
      || current.nlink !== 2
      || fence.nlink !== 2
    ) {
      throw new Error(`Il claim export è cambiato durante il recupero: ${claim.finalTarget}.`);
    }
    await fsApi.unlink(claim.claimPath);
    claimUnlinked = true;
    await fsyncDirectory(path.dirname(claim.claimPath), { fsApi, platform });
    return fencePath;
  } catch (error) {
    if (!claimUnlinked) {
      await removeDurableEntry(fencePath, { fsApi, platform }).catch(() => {});
    }
    throw error;
  }
}

function claimMarkerForTarget(binding, finalTarget, runId, pid) {
  return {
    version: 2,
    pid,
    run_id: runId,
    target: finalTarget,
    primary_output: binding.primaryOutput,
    artifact_set_sha256: binding.digest,
    artifacts: binding.artifacts.map((artifact) => ({
      kind: artifact.kind,
      final_path: artifact.finalPath,
    })),
  };
}

function bindingFromClaim(marker, platform = process.platform) {
  return exportClaimBinding(
    marker.primary_output,
    marker.artifacts.map((artifact) => ({
      kind: artifact.kind,
      finalPath: artifact.final_path,
    })),
    platform,
  );
}

async function claimRecoveryPending(
  marker,
  {
    fsApi = fs,
    platform = process.platform,
    isProcessRunning = processIsRunning,
  } = {},
) {
  const binding = bindingFromClaim(marker, platform);
  const { journalPath, commitPath } = exportTransactionPaths(binding.primaryOutput);
  if (await pathExists(journalPath, { fsApi })) return true;
  if (await pathExists(commitPath, { fsApi })) return true;
  const stagingPath = exportStagingPath(binding.primaryOutput);
  if (!(await pathExists(stagingPath, { fsApi }))) return false;
  try {
    const staging = await readExportStagingOwnership(
      stagingPath,
      binding.primaryOutput,
      binding.artifacts,
      { fsApi, platform },
    );
    if (staging.run_id === marker.run_id) return true;
    return !isProcessRunning(staging.pid);
  } catch {
    return true;
  }
}

async function releaseExportClaims(
  ownership,
  {
    fsApi = fs,
    platform = process.platform,
    isProcessRunning = processIsRunning,
  } = {},
) {
  if (!ownership) return;
  ACTIVE_EXPORT_RUN_IDS.delete(ownership.runId);
  const probeMarker = claimMarkerForTarget(
    ownership.binding,
    ownership.binding.primaryOutput,
    ownership.runId,
    ownership.pid,
  );
  if (await claimRecoveryPending(probeMarker, { fsApi, platform, isProcessRunning })) {
    return { released: false, pending: true };
  }
  for (const claim of [...ownership.claims].reverse()) {
    if (!(await pathExists(claim.claimPath, { fsApi }))) continue;
    const marker = await readExportClaim(claim.claimPath, claim.finalTarget, {
      fsApi,
      platform,
    });
    if (marker.run_id !== ownership.runId) {
      throw new Error(`Claim export fenced da un altro run per ${claim.finalTarget}.`);
    }
    if (!claimMatchesBinding(marker, ownership.binding, platform)) {
      throw new Error(`Claim export associato a un set diverso per ${claim.finalTarget}.`);
    }
    await removeDurableEntry(claim.claimPath, { fsApi, platform });
  }
  return { released: true, pending: false };
}

async function acquireExportClaims(
  expectedArtifacts,
  {
    fsApi = fs,
    randomId = randomUUID,
    platform = process.platform,
    pid = process.pid,
    isProcessRunning = processIsRunning,
  } = {},
) {
  const runId = String(randomId());
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(runId)) {
    throw new Error("Identificatore del claim export non valido.");
  }
  const primaryOutput = expectedArtifacts?.[0]?.finalPath;
  const binding = exportClaimBinding(primaryOutput, expectedArtifacts, platform);
  const ordered = binding.artifacts
    .map(({ finalPath }) => ({
      finalTarget: finalPath,
      claimPath: exportClaimPath(finalPath),
    }))
    .sort((left, right) => normalizedPathIdentity(left.finalTarget, platform)
      .localeCompare(normalizedPathIdentity(right.finalTarget, platform)));
  const ownership = {
    runId,
    pid,
    binding,
    claims: [],
    recoveredRunIds: new Set(),
  };
  ACTIVE_EXPORT_RUN_IDS.add(runId);
  try {
    for (const claim of ordered) {
      let staleFence = null;
      await restoreClaimReapFence(claim, { fsApi, platform });
      if (await pathExists(claim.claimPath, { fsApi })) {
        const existing = await readExportClaimRecord(claim.claimPath, claim.finalTarget, {
          fsApi,
          platform,
        });
        const activeInThisProcess = (
          existing.marker.pid === pid
          && ACTIVE_EXPORT_RUN_IDS.has(existing.marker.run_id)
        );
        const activeInAnotherProcess = (
          existing.marker.pid !== pid
          && isProcessRunning(existing.marker.pid)
        );
        const existingBinding = bindingFromClaim(existing.marker, platform);
        const sameBinding = claimMatchesBinding(existing.marker, binding, platform);
        const pendingRecovery = await claimRecoveryPending(existing.marker, {
          fsApi,
          platform,
          isProcessRunning,
        });
        if (activeInThisProcess || activeInAnotherProcess) {
          throw new Error(`Il target export è già in uso: ${claim.finalTarget}.`);
        }
        if (
          !sameBinding
          && pendingRecovery
        ) {
          throw new Error(
            `Il target export è vincolato al recovery pending di ${existingBinding.primaryOutput}: `
            + claim.finalTarget,
          );
        }
        ownership.recoveredRunIds.add(existing.marker.run_id);
        staleFence = await fenceStaleExportClaim(claim, existing, runId, {
          fsApi,
          platform,
          pid,
        });
      }
      const marker = claimMarkerForTarget(binding, claim.finalTarget, runId, pid);
      let claimPublished = false;
      try {
        await writeDurableJsonExclusive(claim.claimPath, marker, {
          fsApi,
          randomId,
          platform,
          ownershipId: runId,
        });
        claimPublished = true;
      } finally {
        if (staleFence && claimPublished) {
          await removeDurableEntry(staleFence, { fsApi, platform });
        }
      }
      ownership.claims.push(claim);
    }
    return ownership;
  } catch (error) {
    try {
      await releaseExportClaims(ownership, {
        fsApi,
        platform,
        isProcessRunning,
      });
    } catch (releaseError) {
      throw new Error(
        `Acquisizione claim export fallita (${conciseError(error)}); rilascio incompleto: `
        + conciseError(releaseError),
      );
    }
    throw error;
  }
}

async function removeDurableEntry(target, { fsApi = fs, platform = process.platform } = {}) {
  await fsApi.rm(target, { force: true });
  await fsyncDirectory(path.dirname(target), { fsApi, platform });
}

async function writeDurableBytesExclusive(
  target,
  bytes,
  {
    fsApi = fs,
    randomId = randomUUID,
    platform = process.platform,
    ownershipId: requestedOwnershipId = null,
  } = {},
) {
  if (!bytes || !Number.isSafeInteger(bytes.length) || bytes.length < 1 || bytes.length > MAX_SIDECAR_BYTES) {
    throw new Error("Payload del publish durevole non valido o troppo grande.");
  }
  if (requestedOwnershipId === null) {
    throw new Error("Il publish durevole richiede un ownership id esplicito.");
  }
  const ownershipId = String(requestedOwnershipId);
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(ownershipId)) {
    throw new Error("Identificatore del publish durevole non valido.");
  }
  await recoverDurablePublishTwin(target, {
    fsApi,
    platform,
    expectedOwnershipId: ownershipId,
  });
  const temporaryPath = `${target}.${process.pid}.${ownershipId}.tmp`;
  let handle;
  let targetPublished = false;
  try {
    handle = await fsApi.open(temporaryPath, "wx", 0o600);
    if (typeof handle.chmod === "function") await handle.chmod(0o600);
    await handle.writeFile(bytes);
    if (typeof handle.sync === "function") await handle.sync();
    const [beforeLinkHandle, beforeLinkPath] = await Promise.all([
      handle.stat(),
      fsApi.lstat(temporaryPath),
    ]);
    for (const metadata of [beforeLinkHandle, beforeLinkPath]) {
      if (
        !metadata.isFile()
        || metadata.isSymbolicLink()
        || metadata.nlink !== 1
        || metadata.size !== bytes.length
      ) {
        throw new Error("File temporaneo del publish durevole non sicuro.");
      }
    }
    if (
      beforeLinkHandle.dev !== beforeLinkPath.dev
      || beforeLinkHandle.ino !== beforeLinkPath.ino
      || !sameJson(stableStatSignature(beforeLinkHandle), stableStatSignature(beforeLinkPath))
    ) {
      throw new Error("File temporaneo del publish durevole instabile prima del link.");
    }
    // A hard-link publish is atomic and exclusive: unlike a check-then-rename,
    // two exporters can never overwrite each other's durable journal.
    await fsApi.link(temporaryPath, target);
    targetPublished = true;
    const [linkedHandle, linkedTemporary, linkedTarget] = await Promise.all([
      handle.stat(),
      fsApi.lstat(temporaryPath),
      fsApi.lstat(target),
    ]);
    for (const metadata of [linkedHandle, linkedTemporary, linkedTarget]) {
      assertLinkedSidecarMetadata(metadata, "Publish durevole", MAX_SIDECAR_BYTES);
      if (
        metadata.dev !== beforeLinkHandle.dev
        || metadata.ino !== beforeLinkHandle.ino
        || metadata.size !== bytes.length
      ) {
        throw new Error("Target e twin del publish durevole non coincidono.");
      }
    }
    if (
      !sameJson(stableStatSignature(linkedHandle), stableStatSignature(linkedTemporary))
      || !sameJson(stableStatSignature(linkedHandle), stableStatSignature(linkedTarget))
    ) {
      throw new Error("Target e twin del publish durevole sono instabili.");
    }
    await fsApi.unlink(temporaryPath);
    await fsyncDirectory(path.dirname(target), { fsApi, platform });
    const published = await fsApi.lstat(target);
    assertSecureSidecarMetadata(published, "Publish durevole", MAX_SIDECAR_BYTES);
    if (
      published.dev !== beforeLinkHandle.dev
      || published.ino !== beforeLinkHandle.ino
      || published.size !== bytes.length
    ) {
      throw new Error("Target del publish durevole incoerente dopo la pulizia del twin.");
    }
  } finally {
    if (handle) await handle.close().catch(() => {});
    if (await pathExists(temporaryPath, { fsApi }).catch(() => false)) {
      if (targetPublished) {
        await recoverDurablePublishTwin(target, {
          fsApi,
          platform,
          expectedOwnershipId: ownershipId,
        }).catch(() => {});
      } else {
        await removeDurableEntry(temporaryPath, { fsApi, platform }).catch(() => {});
      }
    }
  }
}


async function writeDurableJsonExclusive(target, value, options = {}) {
  await writeDurableBytesExclusive(target, Buffer.from(`${JSON.stringify(value)}\n`), options);
}

function validateExportTransaction(
  journal,
  expectedPrimaryOutput,
  expectedArtifacts = null,
  platform = process.platform,
) {
  if (
    !journal
    || typeof journal !== "object"
    || Array.isArray(journal)
    || journal.version !== 1
    || typeof journal.transaction_id !== "string"
    || !/^[A-Za-z0-9_-]{1,128}$/.test(journal.transaction_id)
    || !sameCanonicalTarget(journal.primary_output, expectedPrimaryOutput, platform)
    || !Array.isArray(journal.artifacts)
    || !journal.artifacts.length
    || journal.artifacts.length > 4
  ) {
    throw new Error("Journal della pubblicazione export non valido.");
  }
  const paths = new Set();
  if (
    expectedArtifacts !== null
    && (!Array.isArray(expectedArtifacts) || expectedArtifacts.length !== journal.artifacts.length)
  ) {
    throw new Error("Journal export: set degli artefatti inatteso.");
  }
  for (const [index, artifact] of journal.artifacts.entries()) {
    if (
      !artifact
      || typeof artifact !== "object"
      || Array.isArray(artifact)
      || !["file", "directory"].includes(artifact.kind)
      || typeof artifact.finalPath !== "string"
      || typeof artifact.temporaryPath !== "string"
      || !pathApi(platform).isAbsolute(artifact.finalPath)
      || !pathApi(platform).isAbsolute(artifact.temporaryPath)
      || typeof artifact.hadOriginal !== "boolean"
      || (artifact.hadOriginal && typeof artifact.backupPath !== "string")
      || (artifact.hadOriginal && !pathApi(platform).isAbsolute(artifact.backupPath))
      || (!artifact.hadOriginal && artifact.backupPath !== null)
    ) {
      throw new Error(`Journal export: artefatto ${index + 1} non valido.`);
    }
    const platformPath = pathApi(platform);
    const finalPath = canonicalTargetPath(artifact.finalPath, { platform });
    const temporaryPath = canonicalTargetPath(artifact.temporaryPath, { platform });
    const expectedBackup = platformPath.join(
      path.dirname(finalPath),
      `.${path.basename(finalPath)}.${journal.transaction_id}.previous`,
    );
    if (
      !sameCanonicalTarget(finalPath, artifact.finalPath, platform)
      || !sameCanonicalTarget(temporaryPath, artifact.temporaryPath, platform)
      || !samePath(path.dirname(temporaryPath), path.dirname(finalPath), platform)
      || !path.basename(temporaryPath).startsWith(`.${path.basename(finalPath)}.`)
      || !path.basename(temporaryPath).endsWith(".tmp")
      || (artifact.hadOriginal && !sameCanonicalTarget(artifact.backupPath, expectedBackup, platform))
      || (index === 0 && !sameCanonicalTarget(finalPath, expectedPrimaryOutput, platform))
      || (
        expectedArtifacts !== null
        && (
          !sameCanonicalTarget(finalPath, expectedArtifacts[index].finalPath, platform)
          || artifact.kind !== expectedArtifacts[index].kind
        )
      )
    ) {
      throw new Error(`Journal export: percorsi dell'artefatto ${index + 1} non validi.`);
    }
    for (const candidate of [finalPath, temporaryPath, artifact.backupPath].filter(Boolean)) {
      const identity = normalizedPathIdentity(candidate, platform);
      if (paths.has(identity)) throw new Error("Journal export: percorsi duplicati.");
      paths.add(identity);
    }
  }
  return journal;
}

async function readExportTransaction(
  journalPath,
  expectedPrimaryOutput,
  expectedArtifacts,
  { fsApi = fs, platform = process.platform } = {},
) {
  let journal;
  try {
    journal = await readStableJsonSidecar(journalPath, {
      fsApi,
      label: "Journal della pubblicazione export",
    });
  } catch (error) {
    throw new Error(`Journal della pubblicazione export non leggibile: ${conciseError(error)}.`);
  }
  return validateExportTransaction(journal, expectedPrimaryOutput, expectedArtifacts, platform);
}

async function recoverExportTransaction(
  primaryOutput,
  { fsApi = fs, platform = process.platform, expectedArtifacts = null } = {},
) {
  const { journalPath, commitPath } = exportTransactionPaths(primaryOutput);
  const journalExists = await pathExists(journalPath, { fsApi });
  if (!journalExists) {
    if (await pathExists(commitPath, { fsApi })) {
      await removeDurableEntry(commitPath, { fsApi, platform });
    }
    return false;
  }
  const journal = await readExportTransaction(
    journalPath,
    primaryOutput,
    expectedArtifacts,
    { fsApi, platform },
  );
  const markerExists = await pathExists(commitPath, { fsApi });
  let committed = false;
  if (markerExists) {
    const marker = await readStableSidecar(commitPath, {
      fsApi,
      label: "Marker di commit export",
      maxBytes: 129,
    });
    const markerText = marker.toString("utf8");
    if (!/^[A-Za-z0-9_-]{1,128}\n$/.test(markerText)) {
      throw new Error("Il marker di commit export ha formato non valido.");
    }
    if (markerText !== `${journal.transaction_id}\n`) {
      throw new Error("Il marker di commit export non coincide con il journal.");
    }
    committed = true;
  }

  if (committed) {
    for (const artifact of journal.artifacts) {
      if (!(await assertCompatibleExistingTarget(artifact.finalPath, artifact.kind, { fsApi }))) {
        throw new Error(`Output export committed mancante: ${artifact.finalPath}`);
      }
      if (artifact.backupPath && await pathExists(artifact.backupPath, { fsApi })) {
        await assertCompatibleExistingTarget(artifact.backupPath, artifact.kind, { fsApi });
        await removeKnownArtifact(artifact.backupPath, artifact.kind, { fsApi, platform });
      }
      if (await pathExists(artifact.temporaryPath, { fsApi })) {
        await assertCompatibleExistingTarget(artifact.temporaryPath, artifact.kind, { fsApi });
        await removeKnownArtifact(artifact.temporaryPath, artifact.kind, { fsApi, platform });
      }
    }
  } else {
    for (const artifact of [...journal.artifacts].reverse()) {
      const temporaryExists = await pathExists(artifact.temporaryPath, { fsApi });
      const finalExists = await pathExists(artifact.finalPath, { fsApi });
      const backupExists = artifact.backupPath
        ? await pathExists(artifact.backupPath, { fsApi })
        : false;
      if (temporaryExists) {
        await assertCompatibleExistingTarget(artifact.temporaryPath, artifact.kind, { fsApi });
      }
      if (finalExists) {
        await assertCompatibleExistingTarget(artifact.finalPath, artifact.kind, { fsApi });
      }
      if (backupExists) {
        await assertCompatibleExistingTarget(artifact.backupPath, artifact.kind, { fsApi });
      }
      if (artifact.hadOriginal) {
        if (backupExists) {
          if (finalExists) {
            await removeKnownArtifact(artifact.finalPath, artifact.kind, { fsApi, platform });
          }
          await fsApi.rename(artifact.backupPath, artifact.finalPath);
          await fsyncDirectory(path.dirname(artifact.finalPath), { fsApi, platform });
        } else if (!finalExists) {
          throw new Error(`Recovery export impossibile: backup precedente mancante per ${artifact.finalPath}.`);
        }
      } else if (temporaryExists && finalExists) {
        throw new Error(`Recovery export ambiguo per il nuovo target ${artifact.finalPath}.`);
      } else if (!temporaryExists && finalExists) {
        await removeKnownArtifact(artifact.finalPath, artifact.kind, { fsApi, platform });
      } else if (!temporaryExists && !finalExists) {
        // Una precedente recovery può aver già rimosso il nuovo target prima
        // di fallire sulla pulizia del journal. Questo stato è già rollbackato.
      }
      if (temporaryExists && await pathExists(artifact.temporaryPath, { fsApi })) {
        await removeKnownArtifact(artifact.temporaryPath, artifact.kind, { fsApi, platform });
      }
    }
  }
  await removeDurableEntry(journalPath, { fsApi, platform });
  if (await pathExists(commitPath, { fsApi })) {
    await removeDurableEntry(commitPath, { fsApi, platform });
  }
  return true;
}

async function publishStagedArtifactsAtomically(
  stagedArtifacts,
  { fsApi = fs, randomId = randomUUID, platform = process.platform } = {},
) {
  if (!Array.isArray(stagedArtifacts) || !stagedArtifacts.length) {
    throw new Error("La pubblicazione richiede almeno un artefatto in staging.");
  }
  const primaryOutput = stagedArtifacts[0].finalPath;
  const expectedArtifacts = stagedArtifacts.map(({ kind, finalPath }) => ({ kind, finalPath }));
  await recoverExportTransaction(primaryOutput, { fsApi, platform, expectedArtifacts });
  const transactionId = String(randomId());
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(transactionId)) {
    throw new Error("Identificatore della transazione export non valido.");
  }
  const artifacts = [];
  for (const artifact of stagedArtifacts) {
    const hadOriginal = await assertCompatibleExistingTarget(artifact.finalPath, artifact.kind, { fsApi });
    if (!(await assertCompatibleExistingTarget(artifact.temporaryPath, artifact.kind, { fsApi }))) {
      throw new Error(`Artefatto di staging mancante: ${artifact.temporaryPath}`);
    }
    const backupPath = hadOriginal
      ? path.join(
        path.dirname(artifact.finalPath),
        `.${path.basename(artifact.finalPath)}.${transactionId}.previous`,
      )
      : null;
    if (backupPath && await pathExists(backupPath, { fsApi })) {
      throw new Error(`Il backup della transazione export esiste già: ${backupPath}`);
    }
    artifacts.push({ ...artifact, hadOriginal, backupPath });
  }
  const { journalPath, commitPath } = exportTransactionPaths(primaryOutput);
  const journal = {
    version: 1,
    transaction_id: transactionId,
    primary_output: primaryOutput,
    artifacts: artifacts.map(({ kind, finalPath, temporaryPath, backupPath, hadOriginal }) => ({
      kind,
      finalPath,
      temporaryPath,
      backupPath,
      hadOriginal,
    })),
  };
  await writeDurableJsonExclusive(journalPath, journal, {
    fsApi,
    randomId,
    platform,
    ownershipId: transactionId,
  });
  try {
    for (const artifact of artifacts) {
      if (artifact.backupPath) {
        await fsApi.rename(artifact.finalPath, artifact.backupPath);
        await fsyncDirectory(path.dirname(artifact.finalPath), { fsApi, platform });
      }
    }
    for (const artifact of artifacts) {
      await fsApi.rename(artifact.temporaryPath, artifact.finalPath);
      await fsyncDirectory(path.dirname(artifact.finalPath), { fsApi, platform });
    }
    await writeDurableBytesExclusive(commitPath, Buffer.from(`${transactionId}\n`), {
      fsApi,
      randomId,
      platform,
      ownershipId: transactionId,
    });
  } catch (error) {
    try {
      await recoverExportTransaction(primaryOutput, { fsApi, platform, expectedArtifacts });
    } catch (rollbackError) {
      throw new Error(
        `Pubblicazione degli artefatti fallita (${conciseError(error)}); anche il ripristino ha fallito: `
        + conciseError(rollbackError),
      );
    }
    throw error;
  }
  await recoverExportTransaction(primaryOutput, { fsApi, platform, expectedArtifacts });
}

async function writeExportArtifactsAtomically({
  output,
  pdfBytes,
  pngDir = null,
  pngSlides = [],
  contactSheet = null,
  contactSheetBytes = null,
  resultJson = null,
  resultJsonBytes = null,
  beforeReplace,
  fsApi = fs,
  randomId = randomUUID,
  platform = process.platform,
  pid = process.pid,
  isProcessRunning = processIsRunning,
}) {
  output = canonicalTargetPath(output, { platform });
  pngDir = pngDir ? canonicalTargetPath(pngDir, { platform }) : null;
  contactSheet = contactSheet ? canonicalTargetPath(contactSheet, { platform }) : null;
  resultJson = resultJson ? canonicalTargetPath(resultJson, { platform }) : null;
  const expectedArtifacts = [
    { kind: "file", finalPath: output },
    ...(pngDir ? [{ kind: "directory", finalPath: pngDir }] : []),
    ...(contactSheet ? [{ kind: "file", finalPath: contactSheet }] : []),
    ...(resultJson ? [{ kind: "file", finalPath: resultJson }] : []),
  ];
  const staged = [];
  let openHandle = null;
  let ownership = null;
  let claimOwnership = null;
  try {
    for (const artifact of expectedArtifacts) {
      await fsApi.mkdir(path.dirname(artifact.finalPath), { recursive: true });
    }
    claimOwnership = await acquireExportClaims(expectedArtifacts, {
      fsApi,
      randomId,
      platform,
      pid,
      isProcessRunning,
    });
    await recoverExportStagingOwnership(output, {
      fsApi,
      platform,
      expectedArtifacts,
      isProcessRunning,
      currentPid: pid,
      recoverableRunIds: claimOwnership.recoveredRunIds,
      cleanup: false,
    });
    await recoverExportTransaction(output, { fsApi, platform, expectedArtifacts });
    await recoverExportStagingOwnership(output, {
      fsApi,
      platform,
      expectedArtifacts,
      isProcessRunning,
      currentPid: pid,
      recoverableRunIds: claimOwnership.recoveredRunIds,
    });
    ownership = await createExportStagingOwnership(output, expectedArtifacts, {
      fsApi,
      randomId,
      platform,
      pid,
      runId: claimOwnership.runId,
    });

    let artifactIndex = 0;
    const pdfArtifact = ownership.marker.artifacts[artifactIndex++];
    const pngArtifact = pngDir ? ownership.marker.artifacts[artifactIndex++] : null;
    const contactArtifact = contactSheet ? ownership.marker.artifacts[artifactIndex++] : null;
    const resultArtifact = resultJson ? ownership.marker.artifacts[artifactIndex++] : null;
    openHandle = await fsApi.open(pdfArtifact.temporaryPath, "wx", 0o600);
    staged.push(pdfArtifact);
    await openHandle.writeFile(pdfBytes);
    if (typeof openHandle.sync === "function") await openHandle.sync();
    await openHandle.close();
    openHandle = null;
    await fsyncDirectory(path.dirname(pdfArtifact.temporaryPath), { fsApi, platform });

    if (pngDir) {
      if (!pngSlides.length) throw new Error("Nessun PNG disponibile per --png-dir.");
      await fsApi.mkdir(pngArtifact.temporaryPath, { mode: 0o700 });
      staged.push(pngArtifact);
      const filenames = new Set();
      for (const slide of pngSlides) {
        if (
          !slide
          || typeof slide.filename !== "string"
          || path.basename(slide.filename) !== slide.filename
          || !slide.filename.toLowerCase().endsWith(".png")
          || filenames.has(slide.filename)
        ) {
          throw new Error("Nome PNG non sicuro o duplicato nella sequenza di export.");
        }
        filenames.add(slide.filename);
        await writeDurableFile(path.join(pngArtifact.temporaryPath, slide.filename), slide.bytes, { fsApi });
      }
      await fsyncDirectory(pngArtifact.temporaryPath, { fsApi, platform });
      await fsyncDirectory(path.dirname(pngArtifact.temporaryPath), { fsApi, platform });
    }

    if (contactSheet) {
      if (!contactSheetBytes) throw new Error("Contact sheet non disponibile per la pubblicazione.");
      openHandle = await fsApi.open(contactArtifact.temporaryPath, "wx", 0o600);
      staged.push(contactArtifact);
      await openHandle.writeFile(contactSheetBytes);
      if (typeof openHandle.sync === "function") await openHandle.sync();
      await openHandle.close();
      openHandle = null;
      await fsyncDirectory(path.dirname(contactArtifact.temporaryPath), { fsApi, platform });
    }

    if (resultJson) {
      if (!resultJsonBytes) throw new Error("Result JSON non disponibile per la pubblicazione.");
      openHandle = await fsApi.open(resultArtifact.temporaryPath, "wx", 0o600);
      staged.push(resultArtifact);
      await openHandle.writeFile(resultJsonBytes);
      if (typeof openHandle.sync === "function") await openHandle.sync();
      await openHandle.close();
      openHandle = null;
      await fsyncDirectory(path.dirname(resultArtifact.temporaryPath), { fsApi, platform });
    }

    if (beforeReplace) await beforeReplace();
    await publishStagedArtifactsAtomically(staged, { fsApi, randomId, platform });
    staged.length = 0;
    await removeDurableEntry(ownership.markerPath, { fsApi, platform });
    ownership = null;
  } finally {
    if (openHandle) await openHandle.close().catch(() => {});
    for (const artifact of staged) {
      await removeKnownArtifact(artifact.temporaryPath, artifact.kind, { fsApi, platform }).catch(() => {});
    }
    if (ownership) {
      await removeDurableEntry(ownership.markerPath, { fsApi, platform }).catch(() => {});
    }
    if (claimOwnership) {
      await releaseExportClaims(claimOwnership, {
        fsApi,
        platform,
        isProcessRunning,
      });
    }
  }
}

async function buildContactSheet(sharp, pngSlides) {
  if (!Array.isArray(pngSlides) || !pngSlides.length) {
    throw new Error("La contact sheet richiede almeno un PNG.");
  }
  const columns = Math.min(CONTACT_SHEET_COLUMNS, pngSlides.length);
  const rows = Math.ceil(pngSlides.length / columns);
  const width = CONTACT_SHEET_MARGIN * 2
    + columns * CONTACT_SHEET_THUMB_WIDTH
    + (columns - 1) * CONTACT_SHEET_GAP;
  const height = CONTACT_SHEET_MARGIN * 2
    + rows * CONTACT_SHEET_THUMB_HEIGHT
    + (rows - 1) * CONTACT_SHEET_GAP;
  const thumbnails = await Promise.all(pngSlides.map(async (slide, index) => ({
    input: await sharp(slide.bytes)
      .resize(CONTACT_SHEET_THUMB_WIDTH, CONTACT_SHEET_THUMB_HEIGHT, { fit: "fill" })
      .png()
      .toBuffer(),
    left: CONTACT_SHEET_MARGIN + (index % columns) * (CONTACT_SHEET_THUMB_WIDTH + CONTACT_SHEET_GAP),
    top: CONTACT_SHEET_MARGIN + Math.floor(index / columns) * (CONTACT_SHEET_THUMB_HEIGHT + CONTACT_SHEET_GAP),
  })));
  return sharp({
    create: {
      width,
      height,
      channels: 4,
      background: { r: 245, g: 241, b: 232, alpha: 1 },
    },
  }).composite(thumbnails).png().toBuffer();
}

function loadDependencies(nodeModules) {
  const externalRequire = createRequire(path.join(nodeModules, "package.json"));
  const load = (name, loader) => {
    try {
      return loader();
    } catch (error) {
      throw new Error(`Dipendenza Node ${name} non disponibile in ${nodeModules}: ${conciseError(error)}`);
    }
  };
  const playwright = load("playwright", () => externalRequire("playwright"));
  const sharp = load("sharp", () => externalRequire("sharp"));
  const pdfLib = load("pdf-lib", () => externalRequire("pdf-lib"));
  if (!playwright?.chromium || typeof sharp !== "function" || typeof pdfLib?.PDFDocument?.create !== "function") {
    throw new Error("Le dipendenze Node dell’esportatore non espongono le API richieste.");
  }
  return { chromium: playwright.chromium, sharp, PDFDocument: pdfLib.PDFDocument };
}

async function isolateSlide(page, targetIndex) {
  await page.evaluate(async (targetIndex) => {
    const previews = [...document.querySelectorAll('.slide-preview[data-production-source="approved-preview"]')];
    if (!previews[targetIndex]) throw new Error(`Slide ${targetIndex + 1} non disponibile per la cattura.`);
    previews.forEach((preview, previewIndex) => {
      const row = preview.closest(".slide-row");
      if (row) row.style.display = previewIndex === targetIndex ? "block" : "none";
    });
    window.scrollTo(0, 0);
    await new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
  }, targetIndex);
}

async function restoreSlideRows(page) {
  await page.evaluate(async () => {
    const previews = [...document.querySelectorAll('.slide-preview[data-production-source="approved-preview"]')];
    previews.forEach((preview) => {
      const row = preview.closest(".slide-row");
      if (row) row.style.removeProperty("display");
    });
    await new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
  });
}

async function normalizedRgba(sharp, source) {
  const { data, info } = await sharp(source)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  if (info.width !== EXPORT_WIDTH || info.height !== EXPORT_HEIGHT || info.channels !== 4) {
    throw new Error(
      `Normalizzazione pixel non valida: ${info.width}x${info.height}, ${info.channels} canali.`,
    );
  }
  return data;
}

function pixelDigest(pixels) {
  return createHash("sha256").update(pixels).digest("hex");
}

function assertPixelParity(referencePixels, productionPixels, slideId) {
  if (referencePixels.equals(productionPixels)) return;
  const limit = Math.min(referencePixels.length, productionPixels.length);
  let difference = 0;
  while (difference < limit && referencePixels[difference] === productionPixels[difference]) difference += 1;
  if (difference === limit) {
    throw new Error(
      `Parità pixel fallita per la slide ${slideId}: buffer RGBA di lunghezza diversa `
      + `(${referencePixels.length} vs ${productionPixels.length}).`,
    );
  }
  const pixel = Math.floor(difference / 4);
  const x = pixel % EXPORT_WIDTH;
  const y = Math.floor(pixel / EXPORT_WIDTH);
  const channel = ["R", "G", "B", "A"][difference % 4];
  throw new Error(
    `Parità pixel fallita per la slide ${slideId}: differenza ${channel} in (${x}, ${y}), `
    + `anteprima=${referencePixels[difference]}, produzione=${productionPixels[difference]}.`,
  );
}

async function captureNormalizedSlide(previews, index, sharp, slideId, label) {
  const targetPreview = previews.nth(index);
  const captureBounds = await targetPreview.boundingBox();
  if (
    !captureBounds
    || Math.abs(captureBounds.width - 480) > 0.01
    || Math.abs(captureBounds.height - 600) > 0.01
  ) {
    throw new Error(
      `La slide ${slideId} ${label} non coincide con la prova approvata 480×600 `
      + `(ricevuta ${captureBounds ? `${captureBounds.width}×${captureBounds.height}` : "nessuna geometria"}).`,
    );
  }
  const source = await targetPreview.screenshot({
    type: "png",
    scale: "device",
    animations: "disabled",
    caret: "hide",
  });
  return normalizedRgba(sharp, source);
}

async function capturePixelParity({
  referencePage,
  productionPage,
  contract,
  sharp,
  expectedDigests,
  productionRecheck = false,
  onSlide,
}) {
  const selector = '.slide-preview[data-production-source="approved-preview"]';
  if (productionRecheck && !expectedDigests) {
    throw new Error("Il ricontrollo production richiede i digest della parità iniziale.");
  }
  if (expectedDigests && expectedDigests.length !== contract.frames.length) {
    throw new Error("Il numero di digest pixel non coincide con il contratto approvato.");
  }
  const referencePreviews = productionRecheck ? null : referencePage.locator(selector);
  const productionPreviews = productionPage.locator(selector);
  const [referenceCount, productionCount] = await Promise.all([
    productionRecheck ? Promise.resolve(contract.frames.length) : referencePreviews.count(),
    productionPreviews.count(),
  ]);
  if (referenceCount !== contract.frames.length || productionCount !== contract.frames.length) {
    throw new Error(
      `Il numero di elementi catturabili non coincide con il contratto `
      + `(anteprima=${referenceCount}, produzione=${productionCount}, contratto=${contract.frames.length}).`,
    );
  }

  const digests = [];
  try {
    for (let index = 0; index < contract.frames.length; index += 1) {
      const slideId = contract.frames[index].id || String(index + 1);
      if (productionRecheck) {
        await isolateSlide(productionPage, index);
      } else {
        await Promise.all([
          isolateSlide(referencePage, index),
          isolateSlide(productionPage, index),
        ]);
      }
      let referencePixels = null;
      let productionPixels;
      if (productionRecheck) {
        productionPixels = await captureNormalizedSlide(
          productionPreviews,
          index,
          sharp,
          slideId,
          "nel ricontrollo di produzione",
        );
      } else {
        [referencePixels, productionPixels] = await Promise.all([
          captureNormalizedSlide(referencePreviews, index, sharp, slideId, "in anteprima"),
          captureNormalizedSlide(productionPreviews, index, sharp, slideId, "in produzione"),
        ]);
        assertPixelParity(referencePixels, productionPixels, slideId);
      }
      const digest = pixelDigest(productionRecheck ? productionPixels : referencePixels);
      if (expectedDigests && expectedDigests[index] !== digest) {
        throw new Error(
          `La slide ${slideId} di produzione è cambiata dopo la parità iniziale; il PDF non viene pubblicato.`,
        );
      }
      digests.push(digest);
      if (onSlide) await onSlide(referencePixels, contract.frames[index], index);
    }
    return digests;
  } finally {
    await Promise.all([
      ...(productionRecheck ? [] : [restoreSlideRows(referencePage)]),
      restoreSlideRows(productionPage),
    ]).catch(() => {});
  }
}

async function readStableContracts({
  referencePage,
  productionPage,
  initialReference,
  initialProduction,
  currentBrowser,
  label,
}) {
  const [reference, production] = await Promise.all([
    waitForContract(referencePage, false),
    waitForContract(productionPage, true),
  ]);
  validateContract(reference, production, currentBrowser);
  validateStableContract(initialReference, reference, `dell’anteprima ${label}`);
  validateStableContract(initialProduction, production, `di produzione ${label}`);
  return { reference, production };
}

async function buildPdf({
  baseUrl,
  browser,
  sharp,
  PDFDocument,
  commitPdf,
  fetchImpl = globalThis.fetch,
}) {
  const currentBrowser = browserDescriptor(await browser.version());
  const context = await browser.newContext({
    viewport: { width: 1800, height: 1200 },
    // The approved proof is exactly 480×600 CSS px; 3× reaches the final
    // 1440×1800 raster natively without supersampling and downscaling.
    deviceScaleFactor: 3,
    colorScheme: "light",
  });
  try {
    const referenceUrl = new URL(baseUrl);
    referenceUrl.searchParams.delete("render");
    referenceUrl.searchParams.set("capture", "parity");
    const productionUrl = new URL(baseUrl);
    productionUrl.searchParams.set("render", "production");
    productionUrl.searchParams.set("capture", "parity");

    const [referencePage, productionPage] = await Promise.all([
      context.newPage(),
      context.newPage(),
    ]);
    await Promise.all([
      referencePage.goto(referenceUrl.toString(), { waitUntil: "domcontentloaded" }),
      productionPage.goto(productionUrl.toString(), { waitUntil: "domcontentloaded" }),
    ]);
    const [initialReference, initialProduction] = await Promise.all([
      waitForContract(referencePage, false),
      waitForContract(productionPage, true),
    ]);
    validateContract(initialReference, initialProduction, currentBrowser);
    assertLiveSession(
      await fetchLiveSession(baseUrl, fetchImpl),
      initialReference,
      initialProduction,
      "prima della cattura",
    );

    const pdf = await PDFDocument.create();
    pdf.setTitle("Carousel Builder export");
    pdf.setProducer(`Carousel Builder ${CONTRACT}`);
    pdf.setCreationDate(DETERMINISTIC_PDF_DATE);
    pdf.setModificationDate(DETERMINISTIC_PDF_DATE);
    const pngSlides = [];
    const pixelDigests = await capturePixelParity({
      referencePage,
      productionPage,
      contract: initialProduction,
      sharp,
      onSlide: async (referencePixels, frame, index) => {
        const png = await sharp(referencePixels, {
          raw: { width: EXPORT_WIDTH, height: EXPORT_HEIGHT, channels: 4 },
        }).png().toBuffer();
        pngSlides.push({
          id: frame.id,
          kind: frame.kind || "",
          filename: slidePngFilename(frame, index, initialProduction.frames.length),
          bytes: png,
        });
        const image = await pdf.embedPng(png);
        const page = pdf.addPage([810, 1012.5]);
        page.drawImage(image, { x: 0, y: 0, width: 810, height: 1012.5 });
      },
    });

    await readStableContracts({
      referencePage,
      productionPage,
      initialReference,
      initialProduction,
      currentBrowser,
      label: "dopo la cattura",
    });

    const bytes = await pdf.save({ useObjectStreams: false });
    const resultContracts = await readStableContracts({
      referencePage,
      productionPage,
      initialReference,
      initialProduction,
      currentBrowser,
      label: "prima del risultato",
    });

    let publication = null;
    if (commitPdf) {
      publication = await commitPdf(bytes, async () => {
        const beforeReplaceContracts = await readStableContracts({
          referencePage,
          productionPage,
          initialReference,
          initialProduction,
          currentBrowser,
          label: "prima della sostituzione atomica",
        });
        assertLiveSession(
          await fetchLiveSession(baseUrl, fetchImpl),
          beforeReplaceContracts.reference,
          beforeReplaceContracts.production,
          "prima del ricontrollo pixel",
        );
        await capturePixelParity({
          referencePage,
          productionPage,
          contract: initialProduction,
          sharp,
          expectedDigests: pixelDigests,
          productionRecheck: true,
        });
        const afterPixelsContracts = await readStableContracts({
          referencePage,
          productionPage,
          initialReference,
          initialProduction,
          currentBrowser,
          label: "dopo il ricontrollo pixel",
        });
        assertLiveSession(
          await fetchLiveSession(baseUrl, fetchImpl),
          afterPixelsContracts.reference,
          afterPixelsContracts.production,
          "immediatamente prima della sostituzione atomica",
        );
      }, pngSlides, {
        contract: resultContracts.production,
        browserDescriptor: currentBrowser,
      });
    }

    return {
      bytes,
      contract: resultContracts.production,
      pngSlides,
      browserDescriptor: currentBrowser,
      publication,
    };
  } finally {
    await context.close().catch(() => {});
  }
}

async function main({
  argv = process.argv.slice(2),
  fetchImpl = globalThis.fetch,
  loadDependenciesImpl = loadDependencies,
  launchBrowserImpl = launchBrowser,
  stdout = process.stdout,
} = {}) {
  const args = parseArgs(argv);
  const baseUrl = safeLocalUrl(args.url);
  const nodeModules = path.resolve(args["node-modules"]);
  const targets = resolveOutputTargets(args);
  const { output, pngDir, contactSheet, resultJson } = targets;
  const launchSession = await fetchLiveSession(baseUrl, fetchImpl);
  assertExportPreflight(launchSession, targets);
  const { chromium, sharp, PDFDocument } = loadDependenciesImpl(nodeModules);
  const expectedBrowser = launchSession?.proof?.browser;
  if (!validBrowserDescriptor(expectedBrowser)) {
    throw new Error("La sessione live non contiene un browser valido associato alla prova visuale.");
  }
  const { browser, browserLabel } = await launchBrowserImpl(chromium, {
    explicitPath: args.chrome,
    expectedBrowser,
  });
  let result;
  try {
    result = await buildPdf({
      baseUrl,
      browser,
      sharp,
      PDFDocument,
      fetchImpl,
      commitPdf: async (bytes, beforeReplace, pngSlides, metadata) => {
        const contactSheetBytes = contactSheet ? await buildContactSheet(sharp, pngSlides) : null;
        const artifactSha256 = exportArtifactDigests({
          output,
          pdfBytes: bytes,
          pngDir,
          pngSlides,
          contactSheet,
          contactSheetBytes,
        });
        const resultPayload = buildExportResult({
          output,
          pngDir,
          contactSheet,
          resultJson,
          contract: metadata.contract,
          browserLabel,
          browser: metadata.browserDescriptor,
          artifactSha256,
        });
        await writeExportArtifactsAtomically({
          output,
          pdfBytes: bytes,
          pngDir,
          pngSlides,
          contactSheet,
          contactSheetBytes,
          resultJson,
          resultJsonBytes: resultJson ? Buffer.from(`${JSON.stringify(resultPayload)}\n`) : null,
          beforeReplace,
        });
        return { artifactSha256, resultPayload };
      },
    });
  } finally {
    await browser.close().catch(() => {});
  }
  stdout.write(`${JSON.stringify(result.publication.resultPayload)}\n`);
}

module.exports = {
  APPROVED_WORKFLOW_STATES,
  CONTENT_SNAPSHOT_KEYS,
  CONTRACT,
  acquireExportClaims,
  assertExportPreflight,
  browserDescriptor,
  browserCandidates,
  buildExportResult,
  buildContactSheet,
  buildPdf,
  canonicalTargetPath,
  createExclusiveTemporaryDirectory,
  createExclusiveTemporaryOutput,
  exportClaimBinding,
  exportArtifactDigests,
  fetchLiveSession,
  fsyncDirectory,
  launchBrowser,
  main,
  parseArgs,
  publishStagedArtifactsAtomically,
  readStableSidecar,
  recoverDurablePublishTwin,
  replaceFilePortable,
  resolveOutputTargets,
  safeLocalUrl,
  sameCanonicalTarget,
  samePath,
  pathContains,
  sameJson,
  slidePngFilename,
  validateContract,
  validateStableContract,
  writeExportArtifactsAtomically,
  writeDurableBytesExclusive,
  writePdfAtomically,
};

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error?.message || error}\n`);
    process.exitCode = 1;
  });
}

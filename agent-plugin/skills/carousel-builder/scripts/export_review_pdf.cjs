#!/usr/bin/env node
"use strict";

const fs = require("node:fs/promises");
const { constants: fsConstants } = require("node:fs");
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
const ALLOWED_ARGS = new Set([
  "url",
  "output",
  "node-modules",
  "chrome",
  "png-dir",
  "contact-sheet",
]);
const APPROVED_WORKFLOW_STATES = new Set([
  "prova_visuale_approvata",
  "rendering",
  "qa",
  "consegnato",
  "approvato",
  "approved",
  "pubblicato",
  "published",
]);
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
  for (const required of ["url", "output", "node-modules"]) {
    if (!result[required]) throw new Error(`Argomento obbligatorio mancante: --${required}`);
  }
  return result;
}

function samePath(left, right, platform = process.platform) {
  if (!left || !right) return false;
  return platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}

function pathContains(parent, child, platform = process.platform) {
  if (!parent || !child || samePath(parent, child, platform)) return false;
  const relative = path.relative(parent, child);
  return Boolean(relative && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

function resolveOutputTargets(
  args,
  {
    cwd = process.cwd(),
    home = os.homedir(),
    platform = process.platform,
  } = {},
) {
  const output = path.resolve(cwd, args.output);
  const pngDir = args["png-dir"] ? path.resolve(cwd, args["png-dir"]) : null;
  const contactSheet = args["contact-sheet"] ? path.resolve(cwd, args["contact-sheet"]) : null;
  if (path.extname(output).toLowerCase() !== ".pdf") {
    throw new Error("Il percorso --output deve terminare con .pdf.");
  }
  if (contactSheet && path.extname(contactSheet).toLowerCase() !== ".png") {
    throw new Error("Il percorso --contact-sheet deve terminare con .png.");
  }
  if (contactSheet && samePath(output, contactSheet, platform)) {
    throw new Error("PDF e contact sheet devono usare percorsi distinti.");
  }
  if (
    contactSheet
    && (pathContains(output, contactSheet, platform) || pathContains(contactSheet, output, platform))
  ) {
    throw new Error("PDF e contact sheet non possono contenersi reciprocamente nel percorso.");
  }
  if (pngDir) {
    const protectedDirectories = [path.parse(pngDir).root, path.resolve(cwd), home ? path.resolve(home) : null].filter(Boolean);
    if (protectedDirectories.some((candidate) => samePath(pngDir, candidate, platform))) {
      throw new Error("La directory --png-dir non può essere la radice, la home o la directory di lavoro corrente.");
    }
    if (
      samePath(pngDir, output, platform)
      || samePath(pngDir, contactSheet, platform)
      || pathContains(pngDir, output, platform)
      || pathContains(pngDir, contactSheet, platform)
      || pathContains(output, pngDir, platform)
      || pathContains(contactSheet, pngDir, platform)
    ) {
      throw new Error("PDF, contact sheet e --png-dir devono usare target separati e non annidati.");
    }
  }
  return { output, pngDir, contactSheet };
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
  if (!APPROVED_WORKFLOW_STATES.has(value.workflowState)) {
    throw new Error(`L’export richiede una prova visuale approvata; stato ricevuto: ${value.workflowState || "mancante"}.`);
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
    || proof.style_system_verified !== true
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
    || !["renderer", "adapter"].includes(production.mode)
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

async function fetchLiveSession(baseUrl, fetchImpl = globalThis.fetch) {
  if (typeof fetchImpl !== "function") {
    throw new Error("Il runtime Node non espone fetch per la verifica live della sessione.");
  }
  const sessionUrl = new URL("/api/session", baseUrl);
  sessionUrl.searchParams.set("token", baseUrl.searchParams.get("token"));
  let response;
  try {
    response = await fetchImpl(sessionUrl, {
      method: "GET",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-store",
        Pragma: "no-cache",
      },
    });
  } catch (error) {
    throw new Error(`Verifica live della sessione non riuscita: ${conciseError(error)}.`);
  }
  if (!response?.ok) {
    throw new Error(`Verifica live della sessione rifiutata con HTTP ${response?.status || "sconosciuto"}.`);
  }
  try {
    return await response.json();
  } catch (error) {
    throw new Error(`Risposta live della sessione non valida: ${conciseError(error)}.`);
  }
}

function assertLiveSession(live, reference, production, label) {
  if (!live || typeof live !== "object" || Array.isArray(live)) {
    throw new Error(`La sessione live ${label} non è valida.`);
  }
  if (live.proof_approved !== true) {
    throw new Error(`La sessione live ${label} non conferma proof.approved=true.`);
  }
  if (!APPROVED_WORKFLOW_STATES.has(live.workflow_state)) {
    throw new Error(`La sessione live ${label} non è in uno stato esportabile.`);
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

async function pathExists(target, { fsApi = fs } = {}) {
  try {
    await fsApi.lstat(target);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

async function removeDurableEntry(target, { fsApi = fs, platform = process.platform } = {}) {
  await fsApi.rm(target, { force: true });
  await fsyncDirectory(path.dirname(target), { fsApi, platform });
}

async function writeDurableJsonExclusive(
  target,
  value,
  { fsApi = fs, randomId = randomUUID, platform = process.platform } = {},
) {
  const temporaryPath = `${target}.${process.pid}.${randomId()}.tmp`;
  let handle;
  try {
    handle = await fsApi.open(temporaryPath, "wx", 0o600);
    await handle.writeFile(`${JSON.stringify(value)}\n`);
    if (typeof handle.sync === "function") await handle.sync();
    await handle.close();
    handle = null;
    // A hard-link publish is atomic and exclusive: unlike a check-then-rename,
    // two exporters can never overwrite each other's durable journal.
    await fsApi.link(temporaryPath, target);
    await fsApi.rm(temporaryPath, { force: true });
    await fsyncDirectory(path.dirname(target), { fsApi, platform });
  } finally {
    if (handle) await handle.close().catch(() => {});
    if (await pathExists(temporaryPath, { fsApi }).catch(() => false)) {
      await removeDurableEntry(temporaryPath, { fsApi, platform }).catch(() => {});
    }
  }
}

function validateExportTransaction(journal, expectedPrimaryOutput, expectedArtifacts = null) {
  if (
    !journal
    || typeof journal !== "object"
    || Array.isArray(journal)
    || journal.version !== 1
    || typeof journal.transaction_id !== "string"
    || !/^[A-Za-z0-9_-]{1,128}$/.test(journal.transaction_id)
    || journal.primary_output !== expectedPrimaryOutput
    || !Array.isArray(journal.artifacts)
    || !journal.artifacts.length
    || journal.artifacts.length > 3
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
      || typeof artifact.hadOriginal !== "boolean"
      || (artifact.hadOriginal && typeof artifact.backupPath !== "string")
      || (!artifact.hadOriginal && artifact.backupPath !== null)
    ) {
      throw new Error(`Journal export: artefatto ${index + 1} non valido.`);
    }
    const finalPath = path.resolve(artifact.finalPath);
    const temporaryPath = path.resolve(artifact.temporaryPath);
    const expectedBackup = path.join(
      path.dirname(finalPath),
      `.${path.basename(finalPath)}.${journal.transaction_id}.previous`,
    );
    if (
      finalPath !== artifact.finalPath
      || temporaryPath !== artifact.temporaryPath
      || path.dirname(temporaryPath) !== path.dirname(finalPath)
      || !path.basename(temporaryPath).startsWith(`.${path.basename(finalPath)}.`)
      || !path.basename(temporaryPath).endsWith(".tmp")
      || (artifact.hadOriginal && artifact.backupPath !== expectedBackup)
      || (index === 0 && finalPath !== expectedPrimaryOutput)
      || (
        expectedArtifacts !== null
        && (
          finalPath !== path.resolve(expectedArtifacts[index].finalPath)
          || artifact.kind !== expectedArtifacts[index].kind
        )
      )
    ) {
      throw new Error(`Journal export: percorsi dell'artefatto ${index + 1} non validi.`);
    }
    for (const candidate of [finalPath, temporaryPath, artifact.backupPath].filter(Boolean)) {
      if (paths.has(candidate)) throw new Error("Journal export: percorsi duplicati.");
      paths.add(candidate);
    }
  }
  return journal;
}

async function readExportTransaction(
  journalPath,
  expectedPrimaryOutput,
  expectedArtifacts,
  { fsApi = fs } = {},
) {
  const metadata = await fsApi.lstat(journalPath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > 64 * 1024) {
    throw new Error("Journal della pubblicazione export non sicuro.");
  }
  let journal;
  try {
    journal = JSON.parse(await fsApi.readFile(journalPath, "utf8"));
  } catch (error) {
    throw new Error(`Journal della pubblicazione export non leggibile: ${conciseError(error)}.`);
  }
  return validateExportTransaction(journal, expectedPrimaryOutput, expectedArtifacts);
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
    { fsApi },
  );
  const markerExists = await pathExists(commitPath, { fsApi });
  let committed = false;
  if (markerExists) {
    const marker = (await fsApi.readFile(commitPath, "utf8")).trim();
    if (marker !== journal.transaction_id) {
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
        } else if (!finalExists || !temporaryExists) {
          throw new Error(`Recovery export impossibile: backup precedente mancante per ${artifact.finalPath}.`);
        }
      } else if (temporaryExists && finalExists) {
        throw new Error(`Recovery export ambiguo per il nuovo target ${artifact.finalPath}.`);
      } else if (!temporaryExists && finalExists) {
        await removeKnownArtifact(artifact.finalPath, artifact.kind, { fsApi, platform });
      } else if (!temporaryExists && !finalExists) {
        throw new Error(`Recovery export impossibile: target e staging mancanti per ${artifact.finalPath}.`);
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
  await writeDurableJsonExclusive(journalPath, journal, { fsApi, randomId, platform });
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
    await writeDurableFile(commitPath, Buffer.from(`${transactionId}\n`), { fsApi });
    await fsyncDirectory(path.dirname(commitPath), { fsApi, platform });
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
  beforeReplace,
  fsApi = fs,
  randomId = randomUUID,
  platform = process.platform,
}) {
  const staged = [];
  let openHandle = null;
  try {
    await fsApi.mkdir(path.dirname(output), { recursive: true });
    const pdfReservation = await createExclusiveTemporaryOutput(output, { fsApi, randomId });
    openHandle = pdfReservation.handle;
    await openHandle.writeFile(pdfBytes);
    if (typeof openHandle.sync === "function") await openHandle.sync();
    await openHandle.close();
    openHandle = null;
    staged.push({ kind: "file", finalPath: output, temporaryPath: pdfReservation.temporaryPath });
    await fsyncDirectory(path.dirname(pdfReservation.temporaryPath), { fsApi, platform });

    if (pngDir) {
      if (!pngSlides.length) throw new Error("Nessun PNG disponibile per --png-dir.");
      const temporaryDirectory = await createExclusiveTemporaryDirectory(pngDir, { fsApi, randomId });
      staged.push({ kind: "directory", finalPath: pngDir, temporaryPath: temporaryDirectory });
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
        await writeDurableFile(path.join(temporaryDirectory, slide.filename), slide.bytes, { fsApi });
      }
      await fsyncDirectory(temporaryDirectory, { fsApi, platform });
      await fsyncDirectory(path.dirname(temporaryDirectory), { fsApi, platform });
    }

    if (contactSheet) {
      if (!contactSheetBytes) throw new Error("Contact sheet non disponibile per la pubblicazione.");
      await fsApi.mkdir(path.dirname(contactSheet), { recursive: true });
      const reservation = await createExclusiveTemporaryOutput(contactSheet, { fsApi, randomId });
      openHandle = reservation.handle;
      await openHandle.writeFile(contactSheetBytes);
      if (typeof openHandle.sync === "function") await openHandle.sync();
      await openHandle.close();
      openHandle = null;
      staged.push({ kind: "file", finalPath: contactSheet, temporaryPath: reservation.temporaryPath });
      await fsyncDirectory(path.dirname(reservation.temporaryPath), { fsApi, platform });
    }

    if (beforeReplace) await beforeReplace();
    await publishStagedArtifactsAtomically(staged, { fsApi, randomId, platform });
    staged.length = 0;
  } finally {
    if (openHandle) await openHandle.close().catch(() => {});
    for (const artifact of staged) {
      await removeKnownArtifact(artifact.temporaryPath, artifact.kind, { fsApi, platform }).catch(() => {});
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
    .resize(EXPORT_WIDTH, EXPORT_HEIGHT, { fit: "fill", kernel: sharp.kernel.lanczos3 })
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

    if (commitPdf) {
      await commitPdf(bytes, async () => {
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
      }, pngSlides);
    }

    return {
      bytes,
      contract: resultContracts.production,
      pngSlides,
      browserDescriptor: currentBrowser,
    };
  } finally {
    await context.close().catch(() => {});
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const baseUrl = safeLocalUrl(args.url);
  const nodeModules = path.resolve(args["node-modules"]);
  const { output, pngDir, contactSheet } = resolveOutputTargets(args);
  const { chromium, sharp, PDFDocument } = loadDependencies(nodeModules);
  const launchSession = await fetchLiveSession(baseUrl);
  const expectedBrowser = launchSession?.proof?.browser;
  if (!validBrowserDescriptor(expectedBrowser)) {
    throw new Error("La sessione live non contiene un browser valido associato alla prova visuale.");
  }
  const { browser, browserLabel } = await launchBrowser(chromium, {
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
      commitPdf: async (bytes, beforeReplace, pngSlides) => {
        const contactSheetBytes = contactSheet ? await buildContactSheet(sharp, pngSlides) : null;
        await writeExportArtifactsAtomically({
          output,
          pdfBytes: bytes,
          pngDir,
          pngSlides,
          contactSheet,
          contactSheetBytes,
          beforeReplace,
        });
      },
    });
  } finally {
    await browser.close().catch(() => {});
  }
  process.stdout.write(`${JSON.stringify({
    status: "ok",
    output,
    slides: result.contract.frames.length,
    width: EXPORT_WIDTH,
    height: EXPORT_HEIGHT,
    contract: CONTRACT,
    revision: result.contract.revision,
    workflow_state: result.contract.workflowState,
    style_system: result.contract.styleSystem,
    browser: browserLabel,
    proof_browser: result.browserDescriptor,
    preview_production_parity: "exact",
    pixel_comparison: "raw-rgba-1440x1800",
    final_pixel_recheck: "production-digest-against-initial-parity",
    live_session_verified: true,
    approval_verified: true,
    ...(pngDir ? { png_dir: pngDir, png_files: result.pngSlides.length } : {}),
    ...(contactSheet ? { contact_sheet: contactSheet } : {}),
  })}\n`);
}

module.exports = {
  APPROVED_WORKFLOW_STATES,
  CONTENT_SNAPSHOT_KEYS,
  CONTRACT,
  browserDescriptor,
  browserCandidates,
  buildContactSheet,
  buildPdf,
  createExclusiveTemporaryDirectory,
  createExclusiveTemporaryOutput,
  fsyncDirectory,
  launchBrowser,
  parseArgs,
  publishStagedArtifactsAtomically,
  replaceFilePortable,
  resolveOutputTargets,
  safeLocalUrl,
  sameJson,
  slidePngFilename,
  validateContract,
  validateStableContract,
  writeExportArtifactsAtomically,
  writePdfAtomically,
};

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error?.message || error}\n`);
    process.exitCode = 1;
  });
}

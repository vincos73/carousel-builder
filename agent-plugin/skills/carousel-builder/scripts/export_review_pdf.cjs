#!/usr/bin/env node
"use strict";

const fs = require("node:fs/promises");
const { constants: fsConstants } = require("node:fs");
const path = require("node:path");
const { createHash, randomUUID } = require("node:crypto");
const { createRequire } = require("node:module");

const CONTRACT = "approved-preview-dom-v1";
const EXPORT_WIDTH = 1440;
const EXPORT_HEIGHT = 1800;
const APPROVED_WORKFLOW_STATES = new Set([
  "prova_visuale_approvata",
  "rendering",
  "qa",
  "consegnato",
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
  "render_fingerprint",
];

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) throw new Error(`Argomento inatteso: ${key}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Valore mancante per ${key}`);
    result[key.slice(2)] = value;
    index += 1;
  }
  for (const required of ["url", "output", "node-modules"]) {
    if (!result[required]) throw new Error(`Argomento obbligatorio mancante: --${required}`);
  }
  return result;
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

function assertRenderContract(value, expectedProduction, label) {
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
  if (!Array.isArray(value.frames) || !value.frames.length) {
    throw new Error(`Il contratto ${label} non contiene slide catturabili.`);
  }
  if (!Array.isArray(value.geometry) || value.geometry.length !== value.frames.length) {
    throw new Error(`La geometria del contratto ${label} non coincide con il numero di slide.`);
  }
  for (const frame of value.frames) {
    if (
      !frame
      || typeof frame.id !== "string"
      || !Number.isFinite(frame.width)
      || !Number.isFinite(frame.height)
      || frame.width <= 0
      || frame.height <= 0
    ) {
      throw new Error(`Il contratto ${label} contiene una slide non catturabile.`);
    }
  }
}

function validateContract(reference, production) {
  assertRenderContract(reference, false, "anteprima");
  assertRenderContract(production, true, "produzione");
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
  } = {},
) {
  const failures = [];
  for (const candidate of browserCandidates({ explicitPath, platform, env })) {
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
      const browser = await chromium.launch({
        ...(candidate.executablePath ? { executablePath: candidate.executablePath } : {}),
        headless: true,
        args: ["--disable-gpu", "--font-render-hinting=none"],
      });
      return { browser, browserLabel: candidate.label };
    } catch (error) {
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

async function replaceFilePortable(
  temporaryPath,
  output,
  { fsApi = fs, platform = process.platform, randomId = randomUUID } = {},
) {
  if (platform !== "win32") {
    await fsApi.rename(temporaryPath, output);
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
    if (temporaryPath) await fsApi.rm(temporaryPath, { force: true }).catch(() => {});
  }
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
  if (!captureBounds || Math.abs(captureBounds.width / captureBounds.height - 0.8) > 0.0005) {
    throw new Error(`La slide ${slideId} ${label} non è catturabile in rapporto 4:5.`);
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
  onSlide,
}) {
  const selector = '.slide-preview[data-production-source="approved-preview"]';
  const referencePreviews = referencePage.locator(selector);
  const productionPreviews = productionPage.locator(selector);
  const [referenceCount, productionCount] = await Promise.all([
    referencePreviews.count(),
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
      await Promise.all([
        isolateSlide(referencePage, index),
        isolateSlide(productionPage, index),
      ]);
      const [referencePixels, productionPixels] = await Promise.all([
        captureNormalizedSlide(referencePreviews, index, sharp, slideId, "in anteprima"),
        captureNormalizedSlide(productionPreviews, index, sharp, slideId, "in produzione"),
      ]);
      assertPixelParity(referencePixels, productionPixels, slideId);
      const digest = pixelDigest(referencePixels);
      if (expectedDigests && expectedDigests[index] !== digest) {
        throw new Error(
          `La slide ${slideId} è cambiata dopo la prima cattura; il PDF non viene pubblicato.`,
        );
      }
      digests.push(digest);
      if (onSlide) await onSlide(referencePixels, contract.frames[index], index);
    }
    return digests;
  } finally {
    await Promise.all([
      restoreSlideRows(referencePage),
      restoreSlideRows(productionPage),
    ]).catch(() => {});
  }
}

async function readStableContracts({
  referencePage,
  productionPage,
  initialReference,
  initialProduction,
  label,
}) {
  const reference = await waitForContract(referencePage, false);
  const production = await waitForContract(productionPage, true);
  validateContract(reference, production);
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
  const context = await browser.newContext({
    viewport: { width: 1800, height: 1200 },
    deviceScaleFactor: 4,
    colorScheme: "light",
  });
  try {
    const referenceUrl = new URL(baseUrl);
    referenceUrl.searchParams.delete("render");
    referenceUrl.searchParams.set("capture", "parity");
    const productionUrl = new URL(baseUrl);
    productionUrl.searchParams.set("render", "production");
    productionUrl.searchParams.set("capture", "parity");

    const referencePage = await context.newPage();
    await referencePage.goto(referenceUrl.toString(), { waitUntil: "networkidle" });
    const initialReference = await waitForContract(referencePage, false);

    const productionPage = await context.newPage();
    await productionPage.goto(productionUrl.toString(), { waitUntil: "networkidle" });
    const initialProduction = await waitForContract(productionPage, true);
    validateContract(initialReference, initialProduction);
    assertLiveSession(
      await fetchLiveSession(baseUrl, fetchImpl),
      initialReference,
      initialProduction,
      "prima della cattura",
    );

    const pdf = await PDFDocument.create();
    pdf.setTitle("Carousel Builder export");
    pdf.setProducer(`Carousel Builder ${CONTRACT}`);
    const pixelDigests = await capturePixelParity({
      referencePage,
      productionPage,
      contract: initialProduction,
      sharp,
      onSlide: async (referencePixels) => {
        const png = await sharp(referencePixels, {
          raw: { width: EXPORT_WIDTH, height: EXPORT_HEIGHT, channels: 4 },
        }).png().toBuffer();
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
      label: "dopo la cattura",
    });

    const bytes = await pdf.save({ useObjectStreams: false });
    const resultContracts = await readStableContracts({
      referencePage,
      productionPage,
      initialReference,
      initialProduction,
      label: "prima del risultato",
    });

    if (commitPdf) {
      await commitPdf(bytes, async () => {
        const beforeReplaceContracts = await readStableContracts({
          referencePage,
          productionPage,
          initialReference,
          initialProduction,
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
        });
        const afterPixelsContracts = await readStableContracts({
          referencePage,
          productionPage,
          initialReference,
          initialProduction,
          label: "dopo il ricontrollo pixel",
        });
        assertLiveSession(
          await fetchLiveSession(baseUrl, fetchImpl),
          afterPixelsContracts.reference,
          afterPixelsContracts.production,
          "immediatamente prima della sostituzione atomica",
        );
      });
    }

    return { bytes, contract: resultContracts.production };
  } finally {
    await context.close().catch(() => {});
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const baseUrl = safeLocalUrl(args.url);
  const nodeModules = path.resolve(args["node-modules"]);
  const output = path.resolve(args.output);
  const { chromium, sharp, PDFDocument } = loadDependencies(nodeModules);
  const { browser, browserLabel } = await launchBrowser(chromium, { explicitPath: args.chrome });
  let result;
  try {
    result = await buildPdf({
      baseUrl,
      browser,
      sharp,
      PDFDocument,
      commitPdf: (bytes, beforeReplace) => writePdfAtomically(output, bytes, { beforeReplace }),
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
    preview_production_parity: "exact",
    pixel_comparison: "raw-rgba-1440x1800",
    live_session_verified: true,
    approval_verified: true,
  })}\n`);
}

module.exports = {
  APPROVED_WORKFLOW_STATES,
  CONTENT_SNAPSHOT_KEYS,
  CONTRACT,
  browserCandidates,
  buildPdf,
  createExclusiveTemporaryOutput,
  launchBrowser,
  parseArgs,
  replaceFilePortable,
  safeLocalUrl,
  sameJson,
  validateContract,
  validateStableContract,
  writePdfAtomically,
};

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error?.message || error}\n`);
    process.exitCode = 1;
  });
}

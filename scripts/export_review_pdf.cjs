#!/usr/bin/env node
"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
const { createRequire } = require("node:module");

const CONTRACT = "approved-preview-dom-v1";
const EXPORT_WIDTH = 1440;
const EXPORT_HEIGHT = 1800;

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
  if (!url.searchParams.get("token")) throw new Error("L’URL dell’editor non contiene il token di sessione.");
  return url;
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
    if (!api) throw new Error("Contratto dell’anteprima non disponibile.");
    return {
      contract: api.contract,
      production: api.production,
      styleSystem: api.styleSystem,
      frames: api.getSlideFrames(),
      geometry: api.getSlideGeometry(),
    };
  });
}

function validateContract(reference, production) {
  if (reference.contract !== CONTRACT || production.contract !== CONTRACT) {
    throw new Error(`Contratto renderer non supportato; atteso ${CONTRACT}.`);
  }
  if (reference.production || !production.production) {
    throw new Error("Le modalità anteprima e produzione non sono distinguibili correttamente.");
  }
  if (!reference.frames.length || reference.frames.length !== production.frames.length) {
    throw new Error("Il numero di slide dell’anteprima non coincide con quello di produzione.");
  }
  if (reference.styleSystem !== production.styleSystem) {
    throw new Error("Il sistema visivo dell’anteprima non coincide con quello di produzione.");
  }
  const referenceIds = reference.frames.map(({ id }) => id);
  const productionIds = production.frames.map(({ id }) => id);
  if (JSON.stringify(referenceIds) !== JSON.stringify(productionIds)) {
    throw new Error("L’ordine delle slide dell’anteprima non coincide con quello di produzione.");
  }
  for (const frame of production.frames) {
    const ratio = frame.width / frame.height;
    if (Math.abs(ratio - 0.8) > 0.0005) {
      throw new Error(`La slide ${frame.id || "senza id"} non rispetta il rapporto 4:5.`);
    }
  }
  if (JSON.stringify(reference.geometry) !== JSON.stringify(production.geometry)) {
    throw new Error("Preview/production geometry mismatch: il PDF non replicherebbe l’anteprima approvata.");
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const baseUrl = safeLocalUrl(args.url);
  const nodeModules = path.resolve(args["node-modules"]);
  const externalRequire = createRequire(path.join(nodeModules, "package.json"));
  const { chromium } = externalRequire("playwright");
  const sharp = externalRequire("sharp");
  const { PDFDocument } = externalRequire("pdf-lib");
  const chromePath = args.chrome || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const output = path.resolve(args.output);
  const outputDir = path.dirname(output);
  const temporaryOutput = path.join(outputDir, `.${path.basename(output)}.${process.pid}.tmp`);

  await fs.mkdir(outputDir, { recursive: true });
  const browser = await chromium.launch({
    executablePath: chromePath,
    headless: true,
    args: ["--disable-gpu", "--font-render-hinting=none"],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1800, height: 1200 },
      deviceScaleFactor: 4,
      colorScheme: "light",
    });
    const referenceUrl = new URL(baseUrl);
    referenceUrl.searchParams.delete("render");
    const productionUrl = new URL(baseUrl);
    productionUrl.searchParams.set("render", "production");

    const referencePage = await context.newPage();
    await referencePage.goto(referenceUrl.toString(), { waitUntil: "networkidle" });
    const reference = await waitForContract(referencePage, false);

    const productionPage = await context.newPage();
    await productionPage.goto(productionUrl.toString(), { waitUntil: "networkidle" });
    const production = await waitForContract(productionPage, true);
    validateContract(reference, production);

    const pdf = await PDFDocument.create();
    pdf.setTitle("Carousel Builder export");
    pdf.setProducer(`Carousel Builder ${CONTRACT}`);
    const productionPreviews = productionPage.locator('.slide-preview[data-production-source="approved-preview"]');
    if (await productionPreviews.count() !== production.frames.length) {
      throw new Error("Il numero di elementi catturabili non coincide con il contratto di produzione.");
    }
    for (let index = 0; index < production.frames.length; index += 1) {
      await productionPage.evaluate((targetIndex) => {
        const previews = [...document.querySelectorAll('.slide-preview[data-production-source="approved-preview"]')];
        previews.forEach((preview, previewIndex) => {
          const row = preview.closest(".slide-row");
          if (row) row.style.display = previewIndex === targetIndex ? "block" : "none";
        });
        window.scrollTo(0, 0);
      }, index);
      const targetPreview = productionPreviews.nth(index);
      const captureBounds = await targetPreview.boundingBox();
      if (!captureBounds || Math.abs(captureBounds.width / captureBounds.height - 0.8) > 0.0005) {
        throw new Error(`La slide ${production.frames[index].id || index + 1} non è catturabile in rapporto 4:5.`);
      }
      const source = await targetPreview.screenshot({
        type: "png",
        scale: "device",
        animations: "disabled",
        caret: "hide",
      });
      const png = await sharp(source)
        .resize(EXPORT_WIDTH, EXPORT_HEIGHT, { fit: "fill", kernel: sharp.kernel.lanczos3 })
        .png()
        .toBuffer();
      const image = await pdf.embedPng(png);
      const page = pdf.addPage([810, 1012.5]);
      page.drawImage(image, { x: 0, y: 0, width: 810, height: 1012.5 });
    }
    const bytes = await pdf.save({ useObjectStreams: false });
    await fs.writeFile(temporaryOutput, bytes);
    await fs.rename(temporaryOutput, output);
    process.stdout.write(`${JSON.stringify({
      status: "ok",
      output,
      slides: production.frames.length,
      width: EXPORT_WIDTH,
      height: EXPORT_HEIGHT,
      contract: CONTRACT,
      style_system: production.styleSystem,
      preview_production_parity: "exact",
    })}\n`);
    await context.close();
  } finally {
    await browser.close();
    await fs.rm(temporaryOutput, { force: true }).catch(() => {});
  }
}

main().catch((error) => {
  process.stderr.write(`${error?.message || error}\n`);
  process.exitCode = 1;
});

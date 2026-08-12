"use strict";

const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  APPROVED_WORKFLOW_STATES,
  CONTRACT,
  browserDescriptor,
  browserCandidates,
  buildContactSheet,
  buildPdf,
  createExclusiveTemporaryOutput,
  fsyncDirectory,
  launchBrowser,
  parseArgs,
  resolveOutputTargets,
  safeLocalUrl,
  slidePngFilename,
  validateContract,
  validateStableContract,
  writeExportArtifactsAtomically,
  writePdfAtomically,
} = require("../scripts/export_review_pdf.cjs");

function sampleContract({
  production = false,
  revision = 9,
  workflowState = "prova_visuale_approvata",
  proofApproved = true,
  styleSystem = "editorial-frame",
  renderFingerprint = "a".repeat(64),
  snapshotOverrides = {},
  frames,
  geometry,
} = {}) {
  const resolvedFrames = frames || [
    { id: "cover", kind: "cover", x: 12, y: 24, width: 480, height: 600 },
    { id: "item-1", kind: "item", x: 12, y: 648, width: 480, height: 600 },
  ];
  const resolvedGeometry = geometry || resolvedFrames.map(({ id, kind }) => ({
    id,
    kind,
    aspect_ratio: 0.8,
    parts: { title: { x: 0.1, y: 0.1, width: 0.8, height: 0.2 } },
  }));
  return {
    contract: CONTRACT,
    production,
    revision,
    workflowState,
    proofApproved,
    styleSystem,
    contentSnapshot: {
      revision,
      workflow_state: workflowState,
      visual_style_system: styleSystem,
      logo_mode: "auto",
      slides: [
        { id: "cover", title: "Titolo" },
        { id: "item-1", kind: "item", title: "", summary: "Testo" },
      ],
      format: { ratio: "4:5", master_width: 1080, master_height: 1350 },
      typography: { cover_px: 112, body_px: 64 },
      brand: { name: "Test" },
      cover_visual: { mode: "typographic" },
      proof: {
        slide_ids: resolvedFrames.map(({ id }) => id),
        required_slide_ids: resolvedFrames.map(({ id }) => id),
        style_system_verified: true,
        preview_width: 480,
        browser: { engine: "chromium", major: 123 },
      },
      production: {
        mode: "adapter",
        producer: CONTRACT,
        supported_style_systems: [styleSystem],
        selected_style_supported: true,
      },
      render_fingerprint: renderFingerprint,
      ...snapshotOverrides,
    },
    frames: resolvedFrames,
    geometry: resolvedGeometry,
  };
}

function mockPage(
  contracts,
  pixels = ["cover-pixels", "slide-pixels"],
  bounds = { width: 480, height: 600 },
) {
  const contractQueue = [...contracts];
  const pixelQueues = pixels.map((value) => (Array.isArray(value) ? [...value] : [value]));
  const visitedUrls = [];
  const gotoOptions = [];
  let screenshotCount = 0;
  return {
    visitedUrls,
    gotoOptions,
    get screenshotCount() {
      return screenshotCount;
    },
    async goto(url, options) {
      visitedUrls.push(url);
      gotoOptions.push(options);
    },
    async waitForFunction() {},
    async evaluate(callback, argument) {
      if (argument !== undefined) return undefined;
      const source = String(callback);
      if (source.includes('productionError || ""')) return "";
      if (source.includes("getRenderContract")) {
        const contract = contractQueue.length > 1 ? contractQueue.shift() : contractQueue[0];
        return structuredClone(contract);
      }
      return undefined;
    },
    locator() {
      return {
        async count() {
          return 2;
        },
        nth(index) {
          return {
            async boundingBox() {
              return { ...bounds };
            },
            async screenshot() {
              screenshotCount += 1;
              const queue = pixelQueues[index];
              const value = queue.length > 1 ? queue.shift() : queue[0];
              return Buffer.isBuffer(value) ? Buffer.from(value) : Buffer.from(String(value));
            },
          };
        },
      };
    },
  };
}

function mockExportRuntime({
  resultProduction,
  referencePixels = ["cover-pixels", "slide-pixels"],
  productionPixels = referencePixels,
  liveSessions,
} = {}) {
  const reference = sampleContract();
  const production = sampleContract({ production: true });
  const referencePage = mockPage([reference, reference, reference], referencePixels);
  const productionPage = mockPage(
    [production, production, resultProduction || production],
    productionPixels,
  );
  const pages = [referencePage, productionPage];
  const context = {
    async newPage() {
      return pages.shift();
    },
    async close() {},
  };
  const browser = {
    async version() {
      return "123.0.6312.4";
    },
    async newContext() {
      return context;
    },
  };
  const sharp = (source) => {
    let mode = "encoded";
    const pipeline = {
      resize() {
        return pipeline;
      },
      ensureAlpha() {
        return pipeline;
      },
      raw() {
        mode = "raw";
        return pipeline;
      },
      png() {
        mode = "png";
        return pipeline;
      },
      async toBuffer(options = {}) {
        const data = Buffer.isBuffer(source) ? Buffer.from(source) : Buffer.from(String(source));
        if (mode === "raw" && options.resolveWithObject) {
          return {
            data,
            info: { width: 1440, height: 1800, channels: 4 },
          };
        }
        return Buffer.from(`normalized-png:${data.toString("hex")}`);
      },
    };
    return pipeline;
  };
  sharp.kernel = { lanczos3: "lanczos3" };
  const pdf = {
    setTitle() {},
    setProducer() {},
    async embedPng() {
      return {};
    },
    addPage() {
      return { drawImage() {} };
    },
    async save() {
      return Buffer.from("mock-pdf");
    },
  };
  const PDFDocument = { async create() { return pdf; } };
  const liveQueue = [...(liveSessions || [{
    proof_approved: true,
    workflow_state: production.workflowState,
    revision: production.revision,
    render_fingerprint: production.contentSnapshot.render_fingerprint,
    proof: production.contentSnapshot.proof,
    production: production.contentSnapshot.production,
  }])];
  const liveRequests = [];
  const fetchImpl = async (url, options) => {
    liveRequests.push({ url: String(url), options });
    const value = liveQueue.length > 1 ? liveQueue.shift() : liveQueue[0];
    return {
      ok: true,
      status: 200,
      async json() {
        return structuredClone(value);
      },
    };
  };
  return {
    browser,
    sharp,
    PDFDocument,
    fetchImpl,
    liveRequests,
    pagesForAssertions: [referencePage, productionPage],
  };
}

test("parseArgs richiede i tre argomenti obbligatori", () => {
  assert.deepEqual(
    parseArgs([
      "--url", "http://127.0.0.1:8765/?token=secret",
      "--output", "review.pdf",
      "--node-modules", "/tmp/node_modules",
    ]),
    {
      url: "http://127.0.0.1:8765/?token=secret",
      output: "review.pdf",
      "node-modules": "/tmp/node_modules",
    },
  );
  assert.throws(() => parseArgs(["--url", "http://localhost/?token=x"]), /--output/);
  assert.throws(() => parseArgs(["unexpected"]), /Argomento inatteso/);
  assert.throws(
    () => parseArgs([
      "--url", "http://127.0.0.1/?token=x",
      "--output", "review.pdf",
      "--node-modules", "/tmp/node_modules",
      "--unknown", "value",
    ]),
    /non supportato/,
  );
  assert.throws(
    () => parseArgs([
      "--url", "http://127.0.0.1/?token=x",
      "--output", "first.pdf",
      "--output", "second.pdf",
      "--node-modules", "/tmp/node_modules",
    ]),
    /duplicato/,
  );
});

test("resolveOutputTargets mantiene separati PDF, PNG e contact sheet da directory pericolose", () => {
  const cwd = path.join(path.parse(process.cwd()).root, "safe", "project");
  const home = path.join(path.parse(cwd).root, "users", "test");
  assert.deepEqual(
    resolveOutputTargets({
      output: "output/carousel.pdf",
      "png-dir": "output/png",
      "contact-sheet": "output/contact-sheet.png",
    }, { cwd, home, platform: "linux" }),
    {
      output: path.join(cwd, "output", "carousel.pdf"),
      pngDir: path.join(cwd, "output", "png"),
      contactSheet: path.join(cwd, "output", "contact-sheet.png"),
    },
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.txt" }, { cwd, home, platform: "linux" }),
    /terminare con .pdf/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "contact-sheet": "sheet.jpg" }, { cwd, home, platform: "linux" }),
    /terminare con .png/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "png-dir": cwd }, { cwd, home, platform: "linux" }),
    /directory di lavoro corrente/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "png/review.pdf", "png-dir": "png" }, { cwd, home, platform: "linux" }),
    /separati e non annidati/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "png-dir": "review.pdf/png" }, { cwd, home, platform: "linux" }),
    /separati e non annidati/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "contact-sheet": "review.pdf/sheet.png" }, { cwd, home, platform: "linux" }),
    /contenersi reciprocamente/,
  );
});

test("slidePngFilename produce nomi ordinati, portabili e confinati", () => {
  assert.equal(slidePngFilename({ id: "Còver / Estate" }, 0, 12), "01-cover-estate.png");
  assert.equal(slidePngFilename({ id: "../" }, 1, 12), "02-slide.png");
});

test("safeLocalUrl accetta solo editor loopback con token e senza credenziali", () => {
  assert.equal(safeLocalUrl("http://127.0.0.1:8765/?token=abc").hostname, "127.0.0.1");
  assert.equal(safeLocalUrl("http://localhost:8765/?token=abc").hostname, "localhost");
  assert.throws(() => safeLocalUrl("https://localhost/?token=abc"), /soltanto un editor locale/);
  assert.throws(() => safeLocalUrl("http://example.com/?token=abc"), /soltanto un editor locale/);
  assert.throws(() => safeLocalUrl("http://localhost/"), /token di sessione/);
  assert.throws(() => safeLocalUrl("http://user@localhost/?token=abc"), /credenziali/);
});

test("tutti e soli gli stati post-prova sono esportabili con proofApproved", () => {
  assert.deepEqual(
    [...APPROVED_WORKFLOW_STATES],
    [
      "prova_visuale_approvata",
      "rendering",
      "qa",
      "consegnato",
      "approvato",
      "approved",
      "pubblicato",
      "published",
    ],
  );
  for (const workflowState of APPROVED_WORKFLOW_STATES) {
    assert.doesNotThrow(() => validateContract(
      sampleContract({ workflowState }),
      sampleContract({ production: true, workflowState }),
    ));
  }
  for (const workflowState of ["bozza", "testi_approvati"]) {
    assert.throws(
      () => validateContract(
        sampleContract({ workflowState }),
        sampleContract({ production: true, workflowState }),
      ),
      /prova visuale approvata/,
    );
  }
  assert.throws(
    () => validateContract(
      sampleContract({ proofApproved: false }),
      sampleContract({ production: true, proofApproved: false }),
    ),
    /proof\.approved=true/,
  );
});

test("preview e production devono avere revisione, snapshot e geometria identici", () => {
  const reference = sampleContract();
  assert.throws(
    () => validateContract(reference, sampleContract({ production: true, revision: 10 })),
    /revisione/,
  );
  assert.throws(
    () => validateContract(
      reference,
      sampleContract({
        production: true,
        snapshotOverrides: { slides: [{ id: "cover", title: "Bozza divergente" }] },
      }),
    ),
    /snapshot editoriale/,
  );
  assert.throws(
    () => validateContract(
      reference,
      sampleContract({
        production: true,
        geometry: [
          { ...reference.geometry[0], parts: { title: { x: 0.2 } } },
          reference.geometry[1],
        ],
      }),
    ),
    /geometry mismatch/,
  );
});

test("l'export richiede prova canonica e producer compatibile fail-closed", () => {
  const reference = sampleContract();
  assert.throws(
    () => validateContract(
      sampleContract({ snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, style_system_verified: false } } }),
      sampleContract({ production: true, snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, style_system_verified: false } } }),
    ),
    /prova visuale.*non è valido o verificato/,
  );
  assert.throws(
    () => validateContract(
      sampleContract({ snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, required_slide_ids: ["missing"] } } }),
      sampleContract({ production: true, snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, required_slide_ids: ["missing"] } } }),
    ),
    /slide canoniche richieste/,
  );
  assert.throws(
    () => validateContract(
      sampleContract({ snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, browser: null } } }),
      sampleContract({ production: true, snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, browser: null } } }),
    ),
    /prova visuale.*non è valido o verificato/,
  );
  assert.throws(
    () => validateContract(
      sampleContract(),
      sampleContract({ production: true }),
      { engine: "chromium", major: 124 },
    ),
    /browser della prova visuale.*non coincide.*browser di export/,
  );
  const layoutProduction = { ...reference.contentSnapshot.production, mode: "layout" };
  assert.throws(
    () => validateContract(
      sampleContract({ snapshotOverrides: { production: layoutProduction } }),
      sampleContract({ production: true, snapshotOverrides: { production: layoutProduction } }),
    ),
    /contratto di produzione.*non supporta/,
  );
  const unsupported = {
    ...reference.contentSnapshot.production,
    selected_style_supported: false,
  };
  assert.throws(
    () => validateContract(
      sampleContract({ snapshotOverrides: { production: unsupported } }),
      sampleContract({ production: true, snapshotOverrides: { production: unsupported } }),
    ),
    /contratto di produzione.*non supporta/,
  );
  const incompatibleProducer = {
    ...reference.contentSnapshot.production,
    producer: "unrelated-renderer",
  };
  assert.throws(
    () => validateContract(
      sampleContract({ snapshotOverrides: { production: incompatibleProducer } }),
      sampleContract({ production: true, snapshotOverrides: { production: incompatibleProducer } }),
    ),
    /contratto di produzione.*non supporta/,
  );
});

test("la prova può essere un sottoinsieme canonico delle slide renderizzate", () => {
  const frames = [
    { id: "cover", kind: "cover", width: 480, height: 600 },
    { id: "item-1", kind: "item", width: 480, height: 600 },
    { id: "item-2", kind: "item", width: 480, height: 600 },
    { id: "outro", kind: "outro", width: 480, height: 600 },
  ];
  const proof = {
    slide_ids: ["cover", "item-2", "outro"],
    required_slide_ids: ["cover", "item-2", "outro"],
    style_system_verified: true,
    preview_width: 480,
    browser: { engine: "chromium", major: 123 },
  };
  assert.doesNotThrow(() => validateContract(
    sampleContract({ frames, snapshotOverrides: { proof } }),
    sampleContract({ production: true, frames, snapshotOverrides: { proof } }),
    { engine: "chromium", major: 123 },
  ));
  const wrongOrder = { ...proof, slide_ids: ["item-2", "cover", "outro"], required_slide_ids: ["item-2", "cover", "outro"] };
  assert.throws(
    () => validateContract(
      sampleContract({ frames, snapshotOverrides: { proof: wrongOrder } }),
      sampleContract({ production: true, frames, snapshotOverrides: { proof: wrongOrder } }),
    ),
    /ordine canonico/,
  );
});

test("browserDescriptor normalizza la major Chromium e rifiuta versioni ambigue", () => {
  assert.deepEqual(browserDescriptor("123.0.6312.4"), { engine: "chromium", major: 123 });
  assert.deepEqual(browserDescriptor("HeadlessChrome/140.0.0.0"), { engine: "chromium", major: 140 });
  assert.throws(() => browserDescriptor("unknown"), /non riconosciuta/);
});

test("la cattura usa il proof 480×600 a scala nativa 3×", async () => {
  const runtime = mockExportRuntime();
  const contexts = [];
  const originalNewContext = runtime.browser.newContext;
  runtime.browser.newContext = async (options) => {
    contexts.push(options);
    return originalNewContext.call(runtime.browser, options);
  };
  await buildPdf({
    baseUrl: new URL("http://127.0.0.1:1234/?token=test"),
    browser: runtime.browser,
    sharp: runtime.sharp,
    PDFDocument: runtime.PDFDocument,
    fetchImpl: runtime.fetchImpl,
  });
  assert.equal(contexts[0].deviceScaleFactor, 3);
});

test("la cattura rifiuta un box 4:5 che non sia la prova esatta 480×600", async () => {
  const runtime = mockExportRuntime();
  for (const page of runtime.pagesForAssertions) {
    const originalLocator = page.locator;
    page.locator = () => {
      const locator = originalLocator();
      const originalNth = locator.nth;
      locator.nth = (index) => ({
        ...originalNth(index),
        async boundingBox() { return { width: 440, height: 550 }; },
      });
      return locator;
    };
  }
  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:1234/?token=test"),
      browser: runtime.browser,
      sharp: runtime.sharp,
      PDFDocument: runtime.PDFDocument,
      fetchImpl: runtime.fetchImpl,
    }),
    /prova approvata 480×600.*440×550/,
  );
});

test("il contratto viene ricontrollato integralmente dopo la cattura", () => {
  const initial = sampleContract({ production: true });
  assert.doesNotThrow(() => validateStableContract(initial, structuredClone(initial), "di produzione"));
  const changed = structuredClone(initial);
  changed.contentSnapshot.slides[1].body = "Mutato durante l’export";
  assert.throws(
    () => validateStableContract(initial, changed, "di produzione"),
    /cambiato durante l’export/,
  );
});

test("buildPdf ricontrolla preview e production anche dopo la serializzazione", async () => {
  const runtime = mockExportRuntime();
  const result = await buildPdf({
    baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
    ...runtime,
  });
  assert.equal(result.bytes.toString(), "mock-pdf");
  assert.equal(result.contract.workflowState, "prova_visuale_approvata");
  const referenceUrl = new URL(runtime.pagesForAssertions[0].visitedUrls[0]);
  const productionUrl = new URL(runtime.pagesForAssertions[1].visitedUrls[0]);
  assert.equal(referenceUrl.searchParams.get("capture"), "parity");
  assert.equal(productionUrl.searchParams.get("capture"), "parity");
  assert.equal(referenceUrl.searchParams.has("render"), false);
  assert.equal(productionUrl.searchParams.get("render"), "production");
  assert.equal(runtime.pagesForAssertions[0].gotoOptions[0].waitUntil, "domcontentloaded");
  assert.equal(runtime.pagesForAssertions[1].gotoOptions[0].waitUntil, "domcontentloaded");
  assert.equal(runtime.liveRequests[0].url, "http://127.0.0.1:8765/api/session?token=secret");
  assert.equal(runtime.liveRequests[0].options.cache, "no-store");
  assert.equal(runtime.liveRequests[0].options.headers["Cache-Control"], "no-store");

  const changed = sampleContract({ production: true });
  changed.contentSnapshot.slides[1].body = "Mutato dopo pdf.save";
  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
      ...mockExportRuntime({ resultProduction: changed }),
    }),
    /snapshot editoriale|prima del risultato/,
  );
});

test("buildPdf accetta pixel raw normalizzati identici e blocca divergenze visuali", async () => {
  await assert.doesNotReject(buildPdf({
    baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
    ...mockExportRuntime({
      referencePixels: ["same-cover-rgba", "same-slide-rgba"],
      productionPixels: ["same-cover-rgba", "same-slide-rgba"],
    }),
  }));

  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
      ...mockExportRuntime({
        referencePixels: ["same-cover-rgba", "reference-slide-rgba"],
        productionPixels: ["same-cover-rgba", "production-slide-rgba"],
      }),
    }),
    /Parità pixel fallita per la slide item-1/,
  );
});

test("il ricontrollo pixel immediatamente prima del replace chiude il TOCTOU", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-toctou-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "previous-pdf");
  const runtime = mockExportRuntime({
    referencePixels: [
      ["approved-cover-rgba", "mutated-cover-rgba"],
      ["approved-slide-rgba", "approved-slide-rgba"],
    ],
    productionPixels: [
      ["approved-cover-rgba", "mutated-cover-rgba"],
      ["approved-slide-rgba", "approved-slide-rgba"],
    ],
  });

  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
      ...runtime,
      commitPdf: (bytes, beforeReplace) => writePdfAtomically(output, bytes, { beforeReplace }),
    }),
    /cover di produzione è cambiata dopo la parità iniziale/,
  );
  assert.equal(runtime.pagesForAssertions[0].screenshotCount, 2, "l’anteprima viene catturata una sola volta per slide");
  assert.equal(runtime.pagesForAssertions[1].screenshotCount, 3, "il ricontrollo si ferma fail-closed alla prima slide mutata");
  assert.equal(await fs.readFile(output, "utf8"), "previous-pdf");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);
});

test("writeExportArtifactsAtomically pubblica insieme PDF, PNG e contact sheet", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-bundle-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  const contactSheet = path.join(directory, "contact-sheet.png");
  await fs.writeFile(output, "old-pdf");
  await fs.mkdir(pngDir);
  await fs.writeFile(path.join(pngDir, "stale.png"), "stale");
  await fs.writeFile(contactSheet, "old-sheet");

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("new-pdf"),
    pngDir,
    pngSlides: [
      { filename: "01-cover.png", bytes: Buffer.from("cover") },
      { filename: "02-slide.png", bytes: Buffer.from("slide") },
    ],
    contactSheet,
    contactSheetBytes: Buffer.from("new-sheet"),
    beforeReplace: async () => {},
  });

  assert.equal(await fs.readFile(output, "utf8"), "new-pdf");
  assert.equal(await fs.readFile(contactSheet, "utf8"), "new-sheet");
  assert.deepEqual(await fs.readdir(pngDir), ["01-cover.png", "02-slide.png"]);
  assert.equal(await fs.readFile(path.join(pngDir, "01-cover.png"), "utf8"), "cover");
  assert.deepEqual((await fs.readdir(directory)).sort(), ["carousel.pdf", "contact-sheet.png", "png"]);
});

test("writeExportArtifactsAtomically sincronizza directory di staging e publish su POSIX", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-fsync-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  const syncedDirectories = [];
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "open") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (targetPath, ...args) => {
        const handle = await target.open(targetPath, ...args);
        if (args[0] === "r") syncedDirectories.push(String(targetPath));
        return handle;
      };
    },
  });

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("new-pdf"),
    pngDir,
    pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("cover") }],
    fsApi,
    platform: "linux",
    beforeReplace: async () => {},
  });

  assert.ok(syncedDirectories.includes(directory), "il parent degli output deve essere fsyncato");
  assert.ok(
    syncedDirectories.some((entry) => path.dirname(entry) === directory && path.basename(entry).endsWith(".tmp")),
    "la directory temporanea dei PNG deve essere fsyncata dopo i file",
  );
  assert.ok(syncedDirectories.filter((entry) => entry === directory).length >= 4);
  await assert.doesNotReject(fsyncDirectory(directory, {
    platform: "win32",
    fsApi: { async open() { throw new Error("non deve essere chiamato"); } },
  }));
});

test("writeExportArtifactsAtomically non pubblica output parziali quando il gate finale fallisce", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-gate-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  const contactSheet = path.join(directory, "contact-sheet.png");
  await fs.writeFile(output, "old-pdf");
  await fs.mkdir(pngDir);
  await fs.writeFile(path.join(pngDir, "old.png"), "old-png");
  await fs.writeFile(contactSheet, "old-sheet");

  await assert.rejects(
    writeExportArtifactsAtomically({
      output,
      pdfBytes: Buffer.from("new-pdf"),
      pngDir,
      pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("cover") }],
      contactSheet,
      contactSheetBytes: Buffer.from("new-sheet"),
      beforeReplace: async () => { throw new Error("drift finale"); },
    }),
    /drift finale/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "old-pdf");
  assert.equal(await fs.readFile(contactSheet, "utf8"), "old-sheet");
  assert.deepEqual(await fs.readdir(pngDir), ["old.png"]);
  assert.deepEqual((await fs.readdir(directory)).sort(), ["carousel.pdf", "contact-sheet.png", "png"]);
});

test("writeExportArtifactsAtomically ripristina tutti gli output se una rename di pubblicazione fallisce", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-rollback-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  const contactSheet = path.join(directory, "contact-sheet.png");
  await fs.writeFile(output, "old-pdf");
  await fs.mkdir(pngDir);
  await fs.writeFile(path.join(pngDir, "old.png"), "old-png");
  await fs.writeFile(contactSheet, "old-sheet");
  let injected = false;
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "rename") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (source, destination) => {
        if (!injected && destination === pngDir && source.includes(".tmp")) {
          injected = true;
          const error = new Error("rename simulata fallita");
          error.code = "EIO";
          throw error;
        }
        return target.rename(source, destination);
      };
    },
  });

  await assert.rejects(
    writeExportArtifactsAtomically({
      output,
      pdfBytes: Buffer.from("new-pdf"),
      pngDir,
      pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("cover") }],
      contactSheet,
      contactSheetBytes: Buffer.from("new-sheet"),
      fsApi,
      beforeReplace: async () => {},
    }),
    /rename simulata fallita/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "old-pdf");
  assert.equal(await fs.readFile(contactSheet, "utf8"), "old-sheet");
  assert.equal(await fs.readFile(path.join(pngDir, "old.png"), "utf8"), "old-png");
  assert.deepEqual((await fs.readdir(directory)).sort(), ["carousel.pdf", "contact-sheet.png", "png"]);
});

test("writeExportArtifactsAtomically recupera una pubblicazione interrotta da un process kill", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-crash-recovery-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  const contactSheet = path.join(directory, "contact-sheet.png");
  await fs.writeFile(output, "old-pdf");
  await fs.mkdir(pngDir);
  await fs.writeFile(path.join(pngDir, "old.png"), "old-png");
  await fs.writeFile(contactSheet, "old-sheet");

  const exporterPath = path.resolve(__dirname, "../scripts/export_review_pdf.cjs");
  const childScript = String.raw`
    const fs = require("node:fs/promises");
    const path = require("node:path");
    const { writeExportArtifactsAtomically } = require(process.argv[1]);
    const directory = process.argv[2];
    const output = path.join(directory, "carousel.pdf");
    const pngDir = path.join(directory, "png");
    const contactSheet = path.join(directory, "contact-sheet.png");
    let killed = false;
    const fsApi = new Proxy(fs, {
      get(target, property) {
        if (property !== "rename") {
          const value = target[property];
          return typeof value === "function" ? value.bind(target) : value;
        }
        return async (source, destination) => {
          if (!killed && destination === pngDir && path.basename(source).endsWith(".tmp")) {
            killed = true;
            process.exit(77);
          }
          return target.rename(source, destination);
        };
      },
    });
    writeExportArtifactsAtomically({
      output,
      pdfBytes: Buffer.from("interrupted-pdf"),
      pngDir,
      pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("interrupted-png") }],
      contactSheet,
      contactSheetBytes: Buffer.from("interrupted-sheet"),
      fsApi,
      beforeReplace: async () => {},
    }).then(
      () => process.exit(0),
      (error) => {
        process.stderr.write(String(error?.stack || error));
        process.exit(2);
      },
    );
  `;
  const crashed = spawnSync(process.execPath, ["-e", childScript, exporterPath, directory], {
    encoding: "utf8",
    timeout: 10_000,
  });
  assert.equal(crashed.error, undefined);
  assert.equal(crashed.status, 77, crashed.stderr);
  assert.equal(await fs.readFile(output, "utf8"), "interrupted-pdf");
  assert.equal(
    (await fs.readdir(directory)).some((entry) => entry === ".carousel.pdf.export-transaction.json"),
    true,
    "il journal durevole deve sopravvivere al processo interrotto",
  );

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("recovered-pdf"),
    pngDir,
    pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("recovered-png") }],
    contactSheet,
    contactSheetBytes: Buffer.from("recovered-sheet"),
    beforeReplace: async () => {},
  });

  assert.equal(await fs.readFile(output, "utf8"), "recovered-pdf");
  assert.equal(await fs.readFile(contactSheet, "utf8"), "recovered-sheet");
  assert.equal(await fs.readFile(path.join(pngDir, "01-cover.png"), "utf8"), "recovered-png");
  assert.deepEqual((await fs.readdir(directory)).sort(), ["carousel.pdf", "contact-sheet.png", "png"]);
});

test("due export concorrenti non possono sovrascrivere lo stesso journal", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-concurrent-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  let arrived = 0;
  let releaseLinks;
  const linksReady = new Promise((resolve) => { releaseLinks = resolve; });
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "link") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (...args) => {
        arrived += 1;
        if (arrived === 2) releaseLinks();
        await linksReady;
        return target.link(...args);
      };
    },
  });
  const run = (value) => writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from(value),
    fsApi,
    beforeReplace: async () => {},
  });

  const results = await Promise.allSettled([run("first"), run("second")]);

  assert.equal(results.filter(({ status }) => status === "fulfilled").length, 1);
  assert.equal(results.filter(({ status }) => status === "rejected").length, 1);
  assert.match(String(results.find(({ status }) => status === "rejected").reason), /EEXIST|exist/i);
  assert.ok(["first", "second"].includes(await fs.readFile(output, "utf8")));
  assert.deepEqual(await fs.readdir(directory), ["carousel.pdf"]);
});

test("un journal preesistente non può indirizzare il recovery verso target secondari arbitrari", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-hostile-journal-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  const contactSheet = path.join(directory, "contact-sheet.png");
  const victim = path.join(directory, "victim.txt");
  const transactionId = "hostile";
  await fs.writeFile(output, "old-pdf");
  await fs.mkdir(pngDir);
  await fs.writeFile(path.join(pngDir, "old.png"), "old-png");
  await fs.writeFile(contactSheet, "old-sheet");
  await fs.writeFile(victim, "preserve");
  const artifact = (kind, finalPath) => ({
    kind,
    finalPath,
    temporaryPath: path.join(path.dirname(finalPath), `.${path.basename(finalPath)}.hostile.tmp`),
    backupPath: path.join(path.dirname(finalPath), `.${path.basename(finalPath)}.${transactionId}.previous`),
    hadOriginal: true,
  });
  const journal = {
    version: 1,
    transaction_id: transactionId,
    primary_output: output,
    artifacts: [artifact("file", output), artifact("directory", pngDir), artifact("file", victim)],
  };
  await fs.writeFile(
    path.join(directory, ".carousel.pdf.export-transaction.json"),
    `${JSON.stringify(journal)}\n`,
  );

  await assert.rejects(
    writeExportArtifactsAtomically({
      output,
      pdfBytes: Buffer.from("new-pdf"),
      pngDir,
      pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("new-png") }],
      contactSheet,
      contactSheetBytes: Buffer.from("new-sheet"),
      beforeReplace: async () => {},
    }),
    /percorsi dell'artefatto 3 non validi|set degli artefatti inatteso/,
  );
  assert.equal(await fs.readFile(victim, "utf8"), "preserve");
  assert.equal(await fs.readFile(output, "utf8"), "old-pdf");
  assert.equal(await fs.readFile(contactSheet, "utf8"), "old-sheet");
});

test("writeExportArtifactsAtomically rifiuta una png-dir con file estranei senza modificarla", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-safe-dir-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const pngDir = path.join(directory, "png");
  await fs.mkdir(pngDir);
  await fs.writeFile(path.join(pngDir, "notes.txt"), "preserva");
  await assert.rejects(
    writeExportArtifactsAtomically({
      output,
      pdfBytes: Buffer.from("new-pdf"),
      pngDir,
      pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("cover") }],
      beforeReplace: async () => {},
    }),
    /elementi non gestiti.*notes.txt/,
  );
  assert.equal(await fs.readFile(path.join(pngDir, "notes.txt"), "utf8"), "preserva");
  assert.deepEqual(await fs.readdir(directory), ["png"]);
});

test("buildContactSheet usa tutti i PNG in una griglia 4:5", async () => {
  const calls = [];
  const sharp = (source) => {
    const pipeline = {
      resize(width, height) { calls.push(["resize", width, height]); return pipeline; },
      composite(items) { calls.push(["composite", items.length]); return pipeline; },
      png() { return pipeline; },
      async toBuffer() { return Buffer.from(source?.create ? "sheet" : "thumb"); },
    };
    if (source?.create) calls.push(["create", source.create.width, source.create.height]);
    return pipeline;
  };
  const result = await buildContactSheet(sharp, [
    { bytes: Buffer.from("one") },
    { bytes: Buffer.from("two") },
    { bytes: Buffer.from("three") },
    { bytes: Buffer.from("four") },
    { bytes: Buffer.from("five") },
  ]);
  assert.equal(result.toString(), "sheet");
  assert.equal(calls.filter(([name]) => name === "resize").length, 5);
  assert.deepEqual(calls.find(([name]) => name === "composite"), ["composite", 5]);
  const [, width, height] = calls.find(([name]) => name === "create");
  assert.ok(width > height && height > 0);
});

test("un render_fingerprint live divergente blocca il replace atomico", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-live-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "previous-pdf");
  const approvedLive = {
    proof_approved: true,
    workflow_state: "prova_visuale_approvata",
    revision: 9,
    render_fingerprint: "a".repeat(64),
    proof: sampleContract().contentSnapshot.proof,
    production: sampleContract().contentSnapshot.production,
  };
  const runtime = mockExportRuntime({
    liveSessions: [
      approvedLive,
      { ...approvedLive, render_fingerprint: "b".repeat(64) },
    ],
  });

  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
      ...runtime,
      commitPdf: (bytes, beforeReplace) => writePdfAtomically(output, bytes, { beforeReplace }),
    }),
    /render_fingerprint della sessione live .* non coincide/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "previous-pdf");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);
  assert.equal(runtime.liveRequests.length, 2);
});

test("un proof.browser live divergente blocca il replace atomico", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-live-browser-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "previous-pdf");
  const contract = sampleContract();
  const approvedLive = {
    proof_approved: true,
    workflow_state: contract.workflowState,
    revision: contract.revision,
    render_fingerprint: contract.contentSnapshot.render_fingerprint,
    proof: contract.contentSnapshot.proof,
    production: contract.contentSnapshot.production,
  };
  const runtime = mockExportRuntime({
    liveSessions: [
      approvedLive,
      {
        ...approvedLive,
        proof: { ...approvedLive.proof, browser: { engine: "chromium", major: 124 } },
      },
    ],
  });

  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
      ...runtime,
      commitPdf: (bytes, beforeReplace) => writePdfAtomically(output, bytes, { beforeReplace }),
    }),
    /contratto di prova della sessione live .* non coincide/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "previous-pdf");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);
});

test("browserCandidates include installazioni Windows/Linux e fallback Playwright", () => {
  const windows = browserCandidates({
    platform: "win32",
    env: { PROGRAMFILES: "C:\\Program Files", LOCALAPPDATA: "C:\\Users\\test\\AppData\\Local" },
  });
  assert.ok(windows.some(({ executablePath }) => executablePath === "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"));
  assert.ok(windows.some(({ executablePath }) => executablePath?.endsWith("Microsoft\\Edge\\Application\\msedge.exe")));
  assert.equal(windows.at(-1).executablePath, null);

  const linux = browserCandidates({ platform: "linux", env: {} });
  assert.ok(linux.some(({ executablePath }) => executablePath === "/usr/bin/google-chrome"));
  assert.equal(linux.at(-1).executablePath, null);
});

test("launchBrowser usa il fallback gestito e produce diagnostica per --chrome invalido", async () => {
  const launches = [];
  const managedBrowser = { close() {} };
  const chromium = {
    async launch(options) {
      launches.push(options);
      return managedBrowser;
    },
  };
  const result = await launchBrowser(chromium, {
    platform: "linux",
    env: {},
    access: async () => {
      const error = new Error("missing");
      error.code = "ENOENT";
      throw error;
    },
  });
  assert.equal(result.browser, managedBrowser);
  assert.equal(result.browserLabel, "browser gestito da Playwright");
  assert.equal(launches.length, 1);
  assert.equal(Object.hasOwn(launches[0], "executablePath"), false);

  await assert.rejects(
    launchBrowser(chromium, {
      explicitPath: "/definitely/missing/browser",
      platform: "linux",
      env: {},
      access: async () => {
        const error = new Error("missing");
        error.code = "ENOENT";
        throw error;
      },
    }),
    /--chrome/,
  );
  assert.equal(launches.length, 1, "un percorso esplicito mancante non deve avviare altri browser");
});

test("launchBrowser salta candidati Chromium con major diversa dalla prova", async () => {
  const launched = [];
  const closed = [];
  const chromium = {
    async launch(options) {
      const executablePath = options.executablePath || "managed";
      launched.push(executablePath);
      const major = executablePath === "/usr/bin/google-chrome" ? 122 : 123;
      return {
        async version() { return `${major}.0.0.0`; },
        async close() { closed.push(executablePath); },
      };
    },
  };
  const result = await launchBrowser(chromium, {
    platform: "linux",
    env: {},
    access: async () => {},
    expectedBrowser: { engine: "chromium", major: 123 },
  });
  assert.equal(result.browserLabel, "Google Chrome Stable");
  assert.deepEqual(launched, ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]);
  assert.deepEqual(closed, ["/usr/bin/google-chrome"]);
  await assert.rejects(
    launchBrowser(chromium, {
      platform: "linux",
      env: {},
      expectedBrowser: { engine: "firefox", major: 123 },
    }),
    /browser associato alla prova visuale non è valido/,
  );
});

test("launchBrowser chiude un candidato se la lettura della versione fallisce", async () => {
  let closed = 0;
  const chromium = {
    async launch() {
      return {
        async version() { throw new Error("versione non disponibile"); },
        async close() { closed += 1; },
      };
    },
  };
  await assert.rejects(
    launchBrowser(chromium, {
      explicitPath: "/browser",
      platform: "linux",
      access: async () => {},
      expectedBrowser: { engine: "chromium", major: 123 },
    }),
    /versione non disponibile/,
  );
  assert.equal(closed, 1);
});

test("il file temporaneo è esclusivo e la sostituzione Windows non lascia residui", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-test-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "old-pdf");

  const ids = ["exclusive-temp", "previous-backup"];
  await writePdfAtomically(output, Buffer.from("new-pdf"), {
    platform: "win32",
    randomId: () => ids.shift(),
  });

  assert.equal(await fs.readFile(output, "utf8"), "new-pdf");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);

  const reservation = await createExclusiveTemporaryOutput(output, { randomId: () => "reserved" });
  await assert.rejects(fs.open(reservation.temporaryPath, "wx"), { code: "EEXIST" });
  await reservation.handle.close();
  await fs.rm(reservation.temporaryPath);
});

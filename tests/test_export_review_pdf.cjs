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
  acquireExportClaims,
  assertExportPreflight,
  browserDescriptor,
  browserCandidates,
  buildContactSheet,
  buildPdf,
  buildExportResult,
  createExclusiveTemporaryOutput,
  exportClaimBinding,
  exportArtifactDigests,
  fetchLiveSession,
  fsyncDirectory,
  launchBrowser,
  main,
  parseArgs,
  pathContains,
  readStableSidecar,
  recoverDurablePublishTwin,
  resolveOutputTargets,
  safeLocalUrl,
  sameCanonicalTarget,
  samePath,
  slidePngFilename,
  validateContract,
  validateStableContract,
  writeExportArtifactsAtomically,
  writeDurableBytesExclusive,
  writePdfAtomically,
} = require("../scripts/export_review_pdf.cjs");

function sampleContract({
  production = false,
  revision = 9,
  workflowState = "rendering",
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
        mode: "renderer",
        producer: CONTRACT,
        supported_style_systems: [styleSystem],
        selected_style_supported: true,
        expected_outputs: ["pdf"],
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
  const sharpStats = { resizeCalls: 0 };
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
        sharpStats.resizeCalls += 1;
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
    metadata: {},
    setTitle(value) { this.metadata.title = value; },
    setProducer(value) { this.metadata.producer = value; },
    setCreationDate(value) { this.metadata.creationDate = value; },
    setModificationDate(value) { this.metadata.modificationDate = value; },
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
    schema_version: "1.4",
    proof_approved: true,
    feedback_pending: false,
    workflow_state: production.workflowState,
    revision: production.revision,
    render_fingerprint: production.contentSnapshot.render_fingerprint,
    proof: production.contentSnapshot.proof,
    production: production.contentSnapshot.production,
  }])];
  const liveRequests = [];
  const fetchImpl = async (url, options) => {
    liveRequests.push({ url: String(url), options });
    const requestIndex = Math.floor((liveRequests.length - 1) / 2);
    const value = liveQueue[Math.min(requestIndex, liveQueue.length - 1)];
    const isStatus = new URL(url).pathname === "/api/status";
    return {
      ok: true,
      status: 200,
      async json() {
        return structuredClone(isStatus ? {
          manifest_revision: value.revision,
          workflow_state: value.workflow_state,
          feedback_pending: value.feedback_pending,
        } : value);
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
    sharpStats,
    pdf,
  };
}

test("parseArgs richiede URL, output, dipendenze e result JSON", () => {
  assert.deepEqual(
    parseArgs([
      "--url", "http://127.0.0.1:8765/?token=secret",
      "--output", "review.pdf",
      "--node-modules", "/tmp/node_modules",
      "--result-json", "result.json",
    ]),
    {
      url: "http://127.0.0.1:8765/?token=secret",
      output: "review.pdf",
      "node-modules": "/tmp/node_modules",
      "result-json": "result.json",
    },
  );
  assert.throws(() => parseArgs(["--url", "http://localhost/?token=x"]), /--output/);
  assert.throws(
    () => parseArgs([
      "--url", "http://localhost/?token=x",
      "--output", "review.pdf",
      "--node-modules", "/tmp/node_modules",
    ]),
    /--result-json/,
  );
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
      "result-json": "output/result.json",
    }, { cwd, home, platform: "linux" }),
    {
      output: path.join(cwd, "output", "carousel.pdf"),
      pngDir: path.join(cwd, "output", "png"),
      contactSheet: path.join(cwd, "output", "contact-sheet.png"),
      resultJson: path.join(cwd, "output", "result.json"),
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
    () => resolveOutputTargets({ output: "review.pdf", "result-json": "result.txt" }, { cwd, home, platform: "linux" }),
    /terminare con .json/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "result-json": "review.pdf/result.json" }, { cwd, home, platform: "linux" }),
    /distinti e non annidati/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "png-dir": cwd }, { cwd, home, platform: "linux" }),
    /directory di lavoro corrente|sidecar riservati/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "png/review.pdf", "png-dir": "png" }, { cwd, home, platform: "linux" }),
    /separati e non annidati|sidecar riservati/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "png-dir": "review.pdf/png" }, { cwd, home, platform: "linux" }),
    /separati e non annidati/,
  );
  assert.throws(
    () => resolveOutputTargets({ output: "review.pdf", "contact-sheet": "review.pdf/sheet.png" }, { cwd, home, platform: "linux" }),
    /contenersi reciprocamente|distinti e non annidati/,
  );
  for (const target of [
    ".review.pdf.export-staging.json",
    ".review.pdf.export-transaction.json",
    ".review.pdf.export-transaction.json.committed",
    ".review.pdf.export-claim.json",
    ".other.pdf.export-staging.json",
    ".other.pdf.export-transaction.json",
    ".other.pdf.export-claim.json",
  ]) {
    assert.throws(
      () => resolveOutputTargets(
        { output: "review.pdf", "result-json": target },
        { cwd, home, platform: "linux" },
      ),
      /sidecar riservati|namespace globale|terminare con \.json/,
    );
    assert.throws(
      () => resolveOutputTargets(
        { output: "review.pdf", "png-dir": target },
        { cwd, home, platform: "linux" },
      ),
      /sidecar riservati|namespace globale/,
    );
  }
});

test("slidePngFilename produce nomi ordinati, portabili e confinati", () => {
  assert.equal(slidePngFilename({ id: "Còver / Estate" }, 0, 12), "01-cover-estate.png");
  assert.equal(slidePngFilename({ id: "../" }, 1, 12), "02-slide.png");
});

test("il risultato machine-readable include schema, fingerprint e digest degli artefatti", () => {
  const contract = sampleContract({ production: true });
  const digests = exportArtifactDigests({
    output: "/tmp/carousel.pdf",
    pdfBytes: Buffer.from("pdf"),
    pngDir: "/tmp/png",
    pngSlides: [{ filename: "01-cover.png", bytes: Buffer.from("png") }],
    contactSheet: "/tmp/sheet.png",
    contactSheetBytes: Buffer.from("sheet"),
  });
  const result = buildExportResult({
    output: "/tmp/carousel.pdf",
    pngDir: "/tmp/png",
    contactSheet: "/tmp/sheet.png",
    resultJson: "/tmp/result.json",
    contract,
    browserLabel: "Chrome",
    browser: { engine: "chromium", major: 123 },
    artifactSha256: digests,
  });
  assert.equal(result.result_schema, "carousel-builder-export-v1");
  assert.equal(result.render_fingerprint, "a".repeat(64));
  assert.deepEqual(
    result.artifact_sha256.map(({ kind, path: artifactPath }) => ({ kind, path: artifactPath })),
    [
      { kind: "pdf", path: "/tmp/carousel.pdf" },
      { kind: "png", path: "/tmp/png/01-cover.png" },
      { kind: "contact_sheet", path: "/tmp/sheet.png" },
    ],
  );
  assert.ok(result.artifact_sha256.every(({ sha256: digest }) => /^[a-f0-9]{64}$/.test(digest)));
  assert.equal(result.png_files, 1);
  assert.equal(result.result_json, "/tmp/result.json");
});

test("safeLocalUrl accetta solo editor loopback con token e senza credenziali", () => {
  assert.equal(safeLocalUrl("http://127.0.0.1:8765/?token=abc").hostname, "127.0.0.1");
  assert.equal(safeLocalUrl("http://localhost:8765/?token=abc").hostname, "localhost");
  assert.throws(() => safeLocalUrl("https://localhost/?token=abc"), /soltanto un editor locale/);
  assert.throws(() => safeLocalUrl("http://example.com/?token=abc"), /soltanto un editor locale/);
  assert.throws(() => safeLocalUrl("http://localhost/"), /token di sessione/);
  assert.throws(() => safeLocalUrl("http://user@localhost/?token=abc"), /credenziali/);
});

test("fetchLiveSession applica un timeout totale anche al body JSON", async () => {
  const baseUrl = new URL("http://127.0.0.1:8765/?token=secret");
  let requestSignal;
  await assert.rejects(
    fetchLiveSession(
      baseUrl,
      async (_url, options) => {
        requestSignal = options.signal;
        return new Promise(() => {});
      },
      { timeoutMs: 20 },
    ),
    /scaduta.*richiesta e body JSON/,
  );
  assert.equal(requestSignal.aborted, true);

  let bodySignal;
  await assert.rejects(
    fetchLiveSession(
      baseUrl,
      async (_url, options) => {
        bodySignal = options.signal;
        return { ok: true, status: 200, json: async () => new Promise(() => {}) };
      },
      { timeoutMs: 20 },
    ),
    /scaduta.*richiesta e body JSON/,
  );
  assert.equal(bodySignal.aborted, true);
});

test("preflight 1.4 blocca feedback pending e output dichiarati divergenti", () => {
  const production = sampleContract({ production: true }).contentSnapshot.production;
  const live = {
    schema_version: "1.4",
    workflow_state: "rendering",
    feedback_pending: false,
    proof_approved: true,
    production,
  };
  assert.doesNotThrow(() => assertExportPreflight(live, {
    output: "/tmp/review.pdf",
    pngDir: null,
    contactSheet: null,
    resultJson: "/tmp/result.json",
  }));
  assert.throws(
    () => assertExportPreflight({ ...live, feedback_pending: true }, {}),
    /feedback_pending=false/,
  );
  assert.throws(
    () => assertExportPreflight({
      ...live,
      production: { ...production, expected_outputs: ["pdf", "png"] },
    }, { pngDir: null, contactSheet: null }),
    /expected_outputs/,
  );
  assert.doesNotThrow(() => assertExportPreflight({
    ...live,
    production: { ...production, expected_outputs: ["contact_sheet", "png", "pdf"] },
  }, { pngDir: "/tmp/png", contactSheet: "/tmp/contact.png" }));
});

test("main esegue il preflight prima di caricare browser e dipendenze", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-main-preflight-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const session = {
    schema_version: "1.4",
    workflow_state: "rendering",
    revision: 9,
    feedback_pending: true,
    proof_approved: true,
    proof: sampleContract().contentSnapshot.proof,
    production: sampleContract().contentSnapshot.production,
  };
  let dependenciesLoaded = false;
  const fetchImpl = async (url) => ({
    ok: true,
    status: 200,
    async json() {
      return new URL(url).pathname === "/api/status" ? {
        manifest_revision: session.revision,
        workflow_state: session.workflow_state,
        feedback_pending: true,
      } : session;
    },
  });
  await assert.rejects(main({
    argv: [
      "--url", "http://127.0.0.1:8765/?token=secret",
      "--output", path.join(directory, "review.pdf"),
      "--result-json", path.join(directory, "result.json"),
      "--node-modules", path.join(directory, "missing-node-modules"),
    ],
    fetchImpl,
    loadDependenciesImpl() {
      dependenciesLoaded = true;
      throw new Error("non deve essere chiamato");
    },
  }), /feedback_pending=false/);
  assert.equal(dependenciesLoaded, false);
});

test("samePath e pathContains normalizzano case e Unicode su Darwin e Windows", () => {
  const nfc = "/tmp/Caf\u00e9/Output.PDF";
  const nfd = "/tmp/cafe\u0301/output.pdf";
  assert.equal(samePath(nfc, nfd, "darwin"), true);
  assert.equal(samePath("/tmp/Stra\u00dfe.pdf", "/tmp/STRASSE.PDF", "darwin"), true);
  assert.equal(pathContains("/tmp/CAF\u00c9", "/tmp/cafe\u0301/Sub/one.pdf", "darwin"), true);
  assert.equal(samePath("C:\\OUT\\FILE.PDF", "c:\\out\\file.pdf", "win32"), true);
  assert.equal(pathContains("C:\\OUT", "c:\\out\\sub\\file.pdf", "win32"), true);
});

test("resolveOutputTargets canonicalizza un parent symlink prima dei confronti", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-canonical-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const realParent = path.join(directory, "real");
  const alias = path.join(directory, "alias");
  await fs.mkdir(realParent);
  await fs.symlink(realParent, alias, "dir");
  const targets = resolveOutputTargets({
    output: path.join(alias, "review.pdf"),
    "result-json": path.join(realParent, "result.json"),
  }, { cwd: directory, home: path.join(directory, "home"), platform: process.platform });
  const canonicalParent = await fs.realpath(realParent);
  assert.equal(path.dirname(targets.output), canonicalParent);
  assert.equal(path.dirname(targets.resultJson), canonicalParent);
});

test("Darwin identifica alias esistenti Unicode tramite realpath e inode", async (context) => {
  if (process.platform !== "darwin") {
    context.skip("richiede un volume Darwin");
    return;
  }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-darwin-alias-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const canonical = path.join(directory, "Caf\u00e9.PDF");
  const alias = path.join(directory, "cafe\u0301.pdf");
  await fs.writeFile(canonical, "pdf");
  let aliasStat;
  try {
    aliasStat = await fs.stat(alias);
  } catch (error) {
    if (error?.code === "ENOENT") {
      context.skip("il volume Darwin è case-sensitive e non espone l'alias Unicode");
      return;
    }
    throw error;
  }
  const canonicalStat = await fs.stat(canonical);
  if (canonicalStat.dev !== aliasStat.dev || canonicalStat.ino !== aliasStat.ino) {
    context.skip("il volume non tratta i nomi come alias dello stesso inode");
    return;
  }
  assert.equal(sameCanonicalTarget(canonical, alias, "darwin"), true);
  assert.equal(await fs.realpath(alias), await fs.realpath(canonical));
});

test("Darwin rifiuta collisioni case-fold conservative per target non esistenti", async (context) => {
  if (process.platform !== "darwin") {
    context.skip("richiede un volume Darwin");
    return;
  }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-darwin-probe-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const existing = path.join(directory, "Stra\u00dfe.pdf");
  const candidate = path.join(directory, "STRASSE.PDF");
  await fs.writeFile(existing, "pdf");
  try {
    const [existingStat, candidateStat] = await Promise.all([fs.stat(existing), fs.stat(candidate)]);
    assert.equal(existingStat.dev, candidateStat.dev);
    assert.equal(existingStat.ino, candidateStat.ino);
    assert.equal(sameCanonicalTarget(existing, candidate, "darwin"), true);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    assert.throws(
      () => resolveOutputTargets({
        output: candidate,
        "result-json": path.join(directory, "result.json"),
      }, { cwd: directory, home: path.join(directory, "home"), platform: "darwin" }),
      /Target Darwin ambiguo.*Stra\u00dfe\.pdf/i,
    );
  }
});

test("solo rendering è esportabile nel contratto attestante 1.4", () => {
  assert.deepEqual(
    [...APPROVED_WORKFLOW_STATES],
    ["rendering"],
  );
  for (const workflowState of APPROVED_WORKFLOW_STATES) {
    assert.doesNotThrow(() => validateContract(
      sampleContract({ workflowState }),
      sampleContract({ production: true, workflowState }),
    ));
  }
  for (const workflowState of ["prova_visuale_approvata", "qa", "consegnato", "approved"] ) {
    assert.throws(
      () => validateContract(
        sampleContract({ workflowState }),
        sampleContract({ production: true, workflowState }),
      ),
      /workflow_state=rendering/,
    );
  }
  for (const workflowState of ["bozza", "testi_approvati"]) {
    assert.throws(
      () => validateContract(
        sampleContract({ workflowState }),
        sampleContract({ production: true, workflowState }),
      ),
    /workflow_state=rendering/,
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
  assert.doesNotThrow(
    () => validateContract(
      sampleContract({ snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, style_system_verified: false } } }),
      sampleContract({ production: true, snapshotOverrides: { proof: { ...reference.contentSnapshot.proof, style_system_verified: false } } }),
    ),
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
  assert.equal(runtime.sharpStats.resizeCalls, 0, "i raster già 1440×1800 non vanno ricampionati");
  assert.equal(runtime.pdf.metadata.creationDate.toISOString(), "2000-01-01T00:00:00.000Z");
  assert.equal(runtime.pdf.metadata.modificationDate.toISOString(), "2000-01-01T00:00:00.000Z");
  assert.equal(runtime.pdf.metadata.title, "Carousel Builder export");
  assert.equal(runtime.pdf.metadata.producer, `Carousel Builder ${CONTRACT}`);
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
  assert.equal(result.contract.workflowState, "rendering");
  const referenceUrl = new URL(runtime.pagesForAssertions[0].visitedUrls[0]);
  const productionUrl = new URL(runtime.pagesForAssertions[1].visitedUrls[0]);
  assert.equal(referenceUrl.searchParams.get("capture"), "parity");
  assert.equal(productionUrl.searchParams.get("capture"), "parity");
  assert.equal(referenceUrl.searchParams.has("render"), false);
  assert.equal(productionUrl.searchParams.get("render"), "production");
  assert.equal(runtime.pagesForAssertions[0].gotoOptions[0].waitUntil, "domcontentloaded");
  assert.equal(runtime.pagesForAssertions[1].gotoOptions[0].waitUntil, "domcontentloaded");
  assert.equal(runtime.liveRequests[0].url, "http://127.0.0.1:8765/api/session?token=secret");
  assert.equal(runtime.liveRequests[1].url, "http://127.0.0.1:8765/api/status?token=secret");
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
  const resultJson = path.join(directory, "result.json");
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
    resultJson,
    resultJsonBytes: Buffer.from('{"status":"ok"}\n'),
    beforeReplace: async () => {},
  });

  assert.equal(await fs.readFile(output, "utf8"), "new-pdf");
  assert.equal(await fs.readFile(contactSheet, "utf8"), "new-sheet");
  assert.equal(await fs.readFile(resultJson, "utf8"), '{"status":"ok"}\n');
  assert.deepEqual(await fs.readdir(pngDir), ["01-cover.png", "02-slide.png"]);
  assert.equal(await fs.readFile(path.join(pngDir, "01-cover.png"), "utf8"), "cover");
  assert.deepEqual((await fs.readdir(directory)).sort(), ["carousel.pdf", "contact-sheet.png", "png", "result.json"]);
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
        if (!injected && path.basename(destination) === path.basename(pngDir) && source.includes(".tmp")) {
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

test("PDF e result JSON fanno rollback insieme se la pubblicazione del risultato fallisce", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-result-rollback-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const resultJson = path.join(directory, "result.json");
  await fs.writeFile(output, "old-pdf");
  await fs.writeFile(resultJson, "old-result");
  let injected = false;
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "rename") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (source, destination) => {
        if (!injected && path.basename(destination) === path.basename(resultJson) && path.basename(source).endsWith(".tmp")) {
          injected = true;
          const error = new Error("rename result simulata fallita");
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
      resultJson,
      resultJsonBytes: Buffer.from("new-result"),
      fsApi,
    }),
    /rename result simulata fallita/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "old-pdf");
  assert.equal(await fs.readFile(resultJson, "utf8"), "old-result");
  assert.deepEqual((await fs.readdir(directory)).sort(), ["carousel.pdf", "result.json"]);
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
          if (!killed && path.basename(destination) === path.basename(pngDir) && path.basename(source).endsWith(".tmp")) {
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

test("un crash pre-journal lascia ownership recuperabile e non cancella staging estranei", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-prejournal-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const foreign = path.join(directory, ".carousel.pdf.999.foreign.0.tmp");
  await fs.writeFile(foreign, "preserve");
  const exporterPath = path.resolve(__dirname, "../scripts/export_review_pdf.cjs");
  const childScript = String.raw`
    const { writeExportArtifactsAtomically } = require(process.argv[1]);
    writeExportArtifactsAtomically({
      output: process.argv[2],
      pdfBytes: Buffer.from("interrupted"),
      beforeReplace: async () => process.exit(78),
    }).catch(() => process.exit(2));
  `;
  const crashed = spawnSync(process.execPath, ["-e", childScript, exporterPath, output], {
    encoding: "utf8",
    timeout: 10_000,
  });
  assert.equal(crashed.status, 78, crashed.stderr);
  const interruptedEntries = await fs.readdir(directory);
  assert.ok(interruptedEntries.includes(".carousel.pdf.export-staging.json"));
  assert.ok(interruptedEntries.some((name) => name.endsWith(".tmp") && name !== path.basename(foreign)));

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("recovered"),
    beforeReplace: async () => {},
  });

  assert.equal(await fs.readFile(output, "utf8"), "recovered");
  assert.equal(await fs.readFile(foreign, "utf8"), "preserve");
  assert.deepEqual((await fs.readdir(directory)).sort(), [path.basename(foreign), "carousel.pdf"].sort());
});

test("un marker di staging appartenente a un processo attivo blocca senza cancellare", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-active-staging-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const runId = "active";
  const temporaryPath = path.join(directory, `.carousel.pdf.${process.pid}.${runId}.0.tmp`);
  const markerPath = path.join(directory, ".carousel.pdf.export-staging.json");
  await fs.writeFile(temporaryPath, "owned");
  await fs.writeFile(markerPath, `${JSON.stringify({
    version: 1,
    pid: process.pid,
    run_id: runId,
    primary_output: output,
    artifacts: [{ kind: "file", finalPath: output, temporaryPath }],
  })}\n`);

  await assert.rejects(
    writeExportArtifactsAtomically({ output, pdfBytes: Buffer.from("new") }),
    /export è ancora attivo/,
  );
  assert.equal(await fs.readFile(temporaryPath, "utf8"), "owned");
  assert.ok((await fs.readdir(directory)).includes(path.basename(markerPath)));
});

test("il publish atomico del marker non lascia un JSON parziale se il link fallisce", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-marker-fault-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "link") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async () => {
        const error = new Error("link marker fallito");
        error.code = "EIO";
        throw error;
      };
    },
  });
  await assert.rejects(
    writeExportArtifactsAtomically({ output, pdfBytes: Buffer.from("new"), fsApi }),
    /link marker fallito/,
  );
  assert.deepEqual(await fs.readdir(directory), []);
});

test("il publish atomico del commit marker fa rollback senza lasciare marker parziali", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-commit-fault-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "carousel.pdf");
  await fs.writeFile(output, "old");
  let links = 0;
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "link") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (...args) => {
        links += 1;
        if (links === 3) {
          const error = new Error("link commit fallito");
          error.code = "EIO";
          throw error;
        }
        return target.link(...args);
      };
    },
  });
  await assert.rejects(
    writeExportArtifactsAtomically({ output, pdfBytes: Buffer.from("new"), fsApi }),
    /link commit fallito/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "old");
  assert.deepEqual(await fs.readdir(directory), ["carousel.pdf"]);
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

test("claim per-target blocca due export con un target secondario condiviso", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-shared-secondary-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const sharedResult = path.join(directory, "shared-result.json");
  let arrived = 0;
  let releaseClaims;
  const claimsReady = new Promise((resolve) => { releaseClaims = resolve; });
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "link") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (source, destination) => {
        if (path.basename(destination).endsWith(".export-claim.json")) {
          arrived += 1;
          if (arrived === 2) releaseClaims();
          await claimsReady;
        }
        return target.link(source, destination);
      };
    },
  });
  const run = (name) => writeExportArtifactsAtomically({
    output: path.join(directory, `${name}.pdf`),
    pdfBytes: Buffer.from(name),
    resultJson: sharedResult,
    resultJsonBytes: Buffer.from(`{"run":"${name}"}\n`),
    fsApi,
  });

  const results = await Promise.allSettled([run("first"), run("second")]);
  assert.equal(results.filter(({ status }) => status === "fulfilled").length, 1);
  assert.equal(results.filter(({ status }) => status === "rejected").length, 1);
  assert.match(String(results.find(({ status }) => status === "rejected").reason), /EEXIST|in uso|exist/i);
  assert.equal((await fs.readdir(directory)).some((name) => name.endsWith(".export-claim.json")), false);
});

test("un recovery pending conserva l'intero claim-set e blocca un primary concorrente", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-claim-lifecycle-v2-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const outputA = path.join(directory, "a.pdf");
  const outputB = path.join(directory, "b.pdf");
  const sharedResult = path.join(directory, "shared-result.json");
  await fs.writeFile(outputA, "old-a");
  await fs.writeFile(sharedResult, "old-shared");
  let publishFailed = false;
  let rollbackFailed = false;
  const faultingFs = new Proxy(fs, {
    get(target, property) {
      if (property !== "rename") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (source, destination) => {
        if (
          !publishFailed
          && sameCanonicalTarget(destination, sharedResult)
          && path.basename(source).endsWith(".tmp")
        ) {
          publishFailed = true;
          const error = new Error("publish A fault");
          error.code = "EIO";
          throw error;
        }
        if (
          publishFailed
          && !rollbackFailed
          && sameCanonicalTarget(destination, sharedResult)
          && path.basename(source).endsWith(".previous")
        ) {
          rollbackFailed = true;
          const error = new Error("rollback A fault");
          error.code = "EIO";
          throw error;
        }
        return target.rename(source, destination);
      };
    },
  });

  await assert.rejects(
    writeExportArtifactsAtomically({
      output: outputA,
      pdfBytes: Buffer.from("broken-a"),
      resultJson: sharedResult,
      resultJsonBytes: Buffer.from("broken-shared"),
      fsApi: faultingFs,
    }),
    /anche il ripristino ha fallito.*rollback A fault/i,
  );
  assert.equal(publishFailed, true);
  assert.equal(rollbackFailed, true);
  const retainedClaimPath = path.join(directory, ".shared-result.json.export-claim.json");
  const retainedClaim = JSON.parse(await fs.readFile(retainedClaimPath, "utf8"));
  assert.equal(retainedClaim.version, 2);
  assert.equal(retainedClaim.primary_output, await fs.realpath(outputA));
  assert.deepEqual(
    retainedClaim.artifacts.map(({ kind, final_path: finalPath }) => [kind, finalPath]),
    [
      ["file", await fs.realpath(outputA)],
      ["file", await fs.realpath(path.dirname(sharedResult)).then((parent) => path.join(parent, path.basename(sharedResult)))],
    ],
  );
  assert.match(retainedClaim.artifact_set_sha256, /^[0-9a-f]{64}$/);

  await assert.rejects(
    writeExportArtifactsAtomically({
      output: outputB,
      pdfBytes: Buffer.from("blocked-b"),
      resultJson: sharedResult,
      resultJsonBytes: Buffer.from("blocked-shared"),
    }),
    /recovery pending.*shared-result\.json/i,
  );
  await assert.rejects(fs.lstat(outputB), { code: "ENOENT" });

  await writeExportArtifactsAtomically({
    output: outputA,
    pdfBytes: Buffer.from("recovered-a"),
    resultJson: sharedResult,
    resultJsonBytes: Buffer.from("recovered-shared"),
  });
  assert.equal(await fs.readFile(outputA, "utf8"), "recovered-a");
  assert.equal(await fs.readFile(sharedResult, "utf8"), "recovered-shared");

  await writeExportArtifactsAtomically({
    output: outputB,
    pdfBytes: Buffer.from("final-b"),
    resultJson: sharedResult,
    resultJsonBytes: Buffer.from("final-shared"),
  });
  assert.equal(await fs.readFile(outputA, "utf8"), "recovered-a");
  assert.equal(await fs.readFile(outputB, "utf8"), "final-b");
  assert.equal(await fs.readFile(sharedResult, "utf8"), "final-shared");
  assert.equal((await fs.readdir(directory)).some((name) => name.endsWith(".export-claim.json")), false);
});

test("un marker staging pending conserva i claim e consente il retry dello stesso set", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-staging-claim-retry-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  const stagingPath = path.join(directory, ".review.pdf.export-staging.json");
  const claimPath = path.join(directory, ".review.pdf.export-claim.json");
  const faultingFs = new Proxy(fs, {
    get(target, property) {
      if (property !== "rm") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (targetPath, options) => {
        if (sameCanonicalTarget(targetPath, stagingPath)) {
          const error = new Error("staging cleanup fault");
          error.code = "EIO";
          throw error;
        }
        return target.rm(targetPath, options);
      };
    },
  });
  await assert.rejects(
    writeExportArtifactsAtomically({
      output,
      pdfBytes: Buffer.from("first"),
      fsApi: faultingFs,
    }),
    /staging cleanup fault/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "first");
  assert.ok((await fs.readdir(directory)).includes(path.basename(stagingPath)));
  assert.ok((await fs.readdir(directory)).includes(path.basename(claimPath)));

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("retry"),
  });
  assert.equal(await fs.readFile(output, "utf8"), "retry");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);
});

test("i claim sono acquisiti in ordine canonico e rilasciati in ordine inverso", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-claim-order-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "z-review.pdf");
  const resultJson = path.join(directory, "a-result.json");
  const events = [];
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property === "link") {
        return async (source, destination) => {
          if (path.basename(destination).endsWith(".export-claim.json")) {
            events.push(["acquire", path.basename(destination)]);
          }
          return target.link(source, destination);
        };
      }
      if (property === "rm") {
        return async (targetPath, options) => {
          if (path.basename(targetPath).endsWith(".export-claim.json")) {
            events.push(["release", path.basename(targetPath)]);
          }
          return target.rm(targetPath, options);
        };
      }
      const value = target[property];
      return typeof value === "function" ? value.bind(target) : value;
    },
  });

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("pdf"),
    resultJson,
    resultJsonBytes: Buffer.from("{}\n"),
    fsApi,
  });

  assert.deepEqual(events, [
    ["acquire", ".a-result.json.export-claim.json"],
    ["acquire", ".z-review.pdf.export-claim.json"],
    ["release", ".z-review.pdf.export-claim.json"],
    ["release", ".a-result.json.export-claim.json"],
  ]);
});

test("il recupero di un claim stale è fenced contro una sostituzione concorrente", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-claim-fence-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const finalTarget = path.join(directory, "review.pdf");
  const claimPath = path.join(directory, ".review.pdf.export-claim.json");
  const oldClaimPath = `${claimPath}.old`;
  const binding = exportClaimBinding(
    finalTarget,
    [{ kind: "file", finalPath: finalTarget }],
  );
  const claim = (runId, pid) => ({
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
  });
  const staleClaim = claim("stale", 12345);
  const attackerClaim = claim("attacker", process.pid);
  await fs.writeFile(claimPath, `${JSON.stringify(staleClaim)}\n`);
  let swapped = false;
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property !== "link") {
        const value = target[property];
        return typeof value === "function" ? value.bind(target) : value;
      }
      return async (source, destination) => {
        if (
          !swapped
          && sameCanonicalTarget(source, claimPath)
          && String(destination).endsWith(".reap")
        ) {
          swapped = true;
          await target.rename(claimPath, oldClaimPath);
          await target.writeFile(claimPath, `${JSON.stringify(attackerClaim)}\n`);
        }
        return target.link(source, destination);
      };
    },
  });

  await assert.rejects(
    acquireExportClaims(
      [{ kind: "file", finalPath: finalTarget }],
      {
        fsApi,
        randomId: () => "challenger",
        isProcessRunning: () => false,
      },
    ),
    /claim export è cambiato durante il recupero/i,
  );
  assert.equal(swapped, true);
  assert.deepEqual(JSON.parse(await fs.readFile(claimPath, "utf8")), attackerClaim);
  assert.equal((await fs.readdir(directory)).some((name) => name.endsWith(".reap")), false);
});

test("il publish durevole mantiene il fd aperto e verifica il twin prima dell'unlink", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-durable-fd-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const targetPath = path.join(directory, ".review.pdf.export-staging.json");
  const bytes = Buffer.from('{"run_id":"durable"}\n');
  let temporaryHandleClosed = false;
  let chmodCalled = false;
  let syncCalled = false;
  let temporaryPath = null;
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property === "open") {
        return async (filePath, flags, mode) => {
          const handle = await target.open(filePath, flags, mode);
          if (flags !== "wx") return handle;
          temporaryPath = filePath;
          return new Proxy(handle, {
            get(handleTarget, handleProperty) {
              if (handleProperty === "chmod") {
                return async (...args) => {
                  chmodCalled = true;
                  return handleTarget.chmod(...args);
                };
              }
              if (handleProperty === "sync") {
                return async (...args) => {
                  syncCalled = true;
                  return handleTarget.sync(...args);
                };
              }
              if (handleProperty === "close") {
                return async (...args) => {
                  temporaryHandleClosed = true;
                  return handleTarget.close(...args);
                };
              }
              const value = handleTarget[handleProperty];
              return typeof value === "function" ? value.bind(handleTarget) : value;
            },
          });
        };
      }
      if (property === "link" || property === "unlink") {
        return async (...args) => {
          assert.equal(temporaryHandleClosed, false, `fd chiuso prima di ${property}`);
          return target[property](...args);
        };
      }
      const value = target[property];
      return typeof value === "function" ? value.bind(target) : value;
    },
  });

  await writeDurableBytesExclusive(targetPath, bytes, {
    fsApi,
    ownershipId: "durable",
  });
  assert.equal(chmodCalled, true);
  assert.equal(syncCalled, true);
  assert.equal(temporaryHandleClosed, true);
  assert.equal(await fs.readFile(targetPath, "utf8"), bytes.toString("utf8"));
  assert.equal((await fs.lstat(targetPath)).nlink, 1);
  await assert.rejects(fs.lstat(temporaryPath), { code: "ENOENT" });
});

test("crash child tra link e unlink recupera i twin owned di claim, staging, journal e commit", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-durable-twins-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const exporterPath = path.resolve(__dirname, "../scripts/export_review_pdf.cjs");
  const childScript = String.raw`
    const fs = require("node:fs/promises");
    const { writeDurableBytesExclusive } = require(process.argv[1]);
    const targetPath = process.argv[2];
    const runId = process.argv[3];
    const bytes = Buffer.from(process.argv[4], "base64");
    let killed = false;
    const fsApi = new Proxy(fs, {
      get(target, property) {
        if (property !== "link") {
          const value = target[property];
          return typeof value === "function" ? value.bind(target) : value;
        }
        return async (source, destination) => {
          await target.link(source, destination);
          if (!killed && destination === targetPath) {
            killed = true;
            process.exit(80);
          }
        };
      },
    });
    writeDurableBytesExclusive(targetPath, bytes, {
      fsApi,
      ownershipId: runId,
    }).then(() => process.exit(0), () => process.exit(2));
  `;
  const cases = [
    [".review.pdf.export-claim.json", "claimrun", Buffer.from('{"run_id":"claimrun"}\n')],
    [".review.pdf.export-staging.json", "stagingrun", Buffer.from('{"run_id":"stagingrun"}\n')],
    [".review.pdf.export-transaction.json", "txrun", Buffer.from('{"transaction_id":"txrun"}\n')],
    [".review.pdf.export-transaction.json.committed", "txrun", Buffer.from("txrun\n")],
  ];
  for (const [name, runId, bytes] of cases) {
    const targetPath = path.join(directory, name);
    const crashed = spawnSync(
      process.execPath,
      ["-e", childScript, exporterPath, targetPath, runId, bytes.toString("base64")],
      { encoding: "utf8", timeout: 10_000 },
    );
    assert.equal(crashed.error, undefined);
    assert.equal(crashed.status, 80, crashed.stderr);
    const twinName = (await fs.readdir(directory)).find(
      (entry) => entry.startsWith(`${name}.`) && entry.endsWith(`.${runId}.tmp`),
    );
    assert.ok(twinName, `twin owned mancante per ${name}`);
    const twinPath = path.join(directory, twinName);
    assert.equal((await fs.lstat(targetPath)).nlink, 2);
    assert.equal(
      (await readStableSidecar(targetPath, { label: `Twin ${name}` })).toString("utf8"),
      bytes.toString("utf8"),
    );
    assert.equal((await fs.lstat(targetPath)).nlink, 1);
    await assert.rejects(fs.lstat(twinPath), { code: "ENOENT" });
  }
});

test("un crash tra link e unlink del claim lascia un twin recuperabile dal retry", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-durable-child-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  const exporterPath = path.resolve(__dirname, "../scripts/export_review_pdf.cjs");
  const childScript = String.raw`
    const fs = require("node:fs/promises");
    const path = require("node:path");
    const { acquireExportClaims } = require(process.argv[1]);
    const output = process.argv[2];
    let killed = false;
    const fsApi = new Proxy(fs, {
      get(target, property) {
        if (property !== "link") {
          const value = target[property];
          return typeof value === "function" ? value.bind(target) : value;
        }
        return async (source, destination) => {
          await target.link(source, destination);
          if (!killed && path.basename(destination).endsWith(".export-claim.json")) {
            killed = true;
            process.exit(79);
          }
        };
      },
    });
    acquireExportClaims(
      [{ kind: "file", finalPath: output }],
      { fsApi, randomId: () => "crashrun" },
    ).then(() => process.exit(0), () => process.exit(2));
  `;
  const crashed = spawnSync(process.execPath, ["-e", childScript, exporterPath, output], {
    encoding: "utf8",
    timeout: 10_000,
  });
  assert.equal(crashed.error, undefined);
  assert.equal(crashed.status, 79, crashed.stderr);
  const claimPath = path.join(directory, ".review.pdf.export-claim.json");
  assert.equal((await fs.lstat(claimPath)).nlink, 2);
  assert.ok((await fs.readdir(directory)).some((name) => name.endsWith(".crashrun.tmp")));

  await writeExportArtifactsAtomically({
    output,
    pdfBytes: Buffer.from("recovered"),
  });
  assert.equal(await fs.readFile(output, "utf8"), "recovered");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);
});

test("sidecar JSON e commit marker rifiutano hardlink e formato non canonico", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-sidecar-secure-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const victim = path.join(directory, "victim.json");
  const sidecar = path.join(directory, ".review.pdf.export-staging.json");
  await fs.writeFile(victim, "{}\n");
  await fs.link(victim, sidecar);
  await assert.rejects(
    readStableSidecar(sidecar, { label: "Sidecar test" }),
    /non sicuro/,
  );
  assert.equal(await fs.readFile(victim, "utf8"), "{}\n");

  const output = path.join(directory, "review.pdf");
  const journalPath = path.join(directory, ".review.pdf.export-transaction.json");
  const commitPath = `${journalPath}.committed`;
  const transactionId = "tx";
  const temporaryPath = path.join(directory, ".review.pdf.tx.tmp");
  await fs.rm(sidecar);
  await fs.writeFile(output, "new");
  await fs.writeFile(journalPath, `${JSON.stringify({
    version: 1,
    transaction_id: transactionId,
    primary_output: output,
    artifacts: [{
      kind: "file",
      finalPath: output,
      temporaryPath,
      backupPath: null,
      hadOriginal: false,
    }],
  })}\n`);
  await fs.writeFile(commitPath, "tx");
  await assert.rejects(
    writeExportArtifactsAtomically({ output, pdfBytes: Buffer.from("other") }),
    /marker di commit export.*formato/i,
  );
  assert.equal(await fs.readFile(output, "utf8"), "new");
});

test("recovery è idempotente dopo un secondo fault di pulizia", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-double-fault-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "old");
  let publishFailed = false;
  let cleanupFailed = false;
  const fsApi = new Proxy(fs, {
    get(target, property) {
      if (property === "rename") {
        return async (source, destination) => {
          if (!publishFailed && path.basename(destination) === path.basename(output) && path.basename(source).endsWith(".tmp")) {
            publishFailed = true;
            const error = new Error("publish fault");
            error.code = "EIO";
            throw error;
          }
          return target.rename(source, destination);
        };
      }
      if (property === "rm") {
        return async (targetPath, options) => {
          if (!cleanupFailed && String(targetPath).endsWith(".export-transaction.json")) {
            cleanupFailed = true;
            const error = new Error("cleanup fault");
            error.code = "EIO";
            throw error;
          }
          return target.rm(targetPath, options);
        };
      }
      const value = target[property];
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  await assert.rejects(
    writeExportArtifactsAtomically({ output, pdfBytes: Buffer.from("new"), fsApi }),
    /publish fault|cleanup fault/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "old");
  await assert.doesNotReject(
    writeExportArtifactsAtomically({ output, pdfBytes: Buffer.from("recovered") }),
  );
  assert.equal(await fs.readFile(output, "utf8"), "recovered");
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
    schema_version: "1.4",
    proof_approved: true,
    feedback_pending: false,
    workflow_state: "rendering",
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
  assert.equal(runtime.liveRequests.length, 4);
});

test("feedback pending apparso al gate finale blocca il replace atomico", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-live-pending-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "previous-pdf");
  const contract = sampleContract({ production: true });
  const clean = {
    schema_version: "1.4",
    proof_approved: true,
    feedback_pending: false,
    workflow_state: contract.workflowState,
    revision: contract.revision,
    render_fingerprint: contract.contentSnapshot.render_fingerprint,
    proof: contract.contentSnapshot.proof,
    production: contract.contentSnapshot.production,
  };
  const runtime = mockExportRuntime({ liveSessions: [clean, { ...clean, feedback_pending: true }] });
  await assert.rejects(
    buildPdf({
      baseUrl: new URL("http://127.0.0.1:8765/?token=secret"),
      ...runtime,
      commitPdf: (bytes, beforeReplace) => writePdfAtomically(output, bytes, { beforeReplace }),
    }),
    /feedback_pending=false/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "previous-pdf");
});

test("un proof.browser live divergente blocca il replace atomico", async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-live-browser-"));
  context.after(async () => fs.rm(directory, { recursive: true, force: true }));
  const output = path.join(directory, "review.pdf");
  await fs.writeFile(output, "previous-pdf");
  const contract = sampleContract();
  const approvedLive = {
    schema_version: "1.4",
    proof_approved: true,
    feedback_pending: false,
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

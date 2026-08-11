"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  APPROVED_WORKFLOW_STATES,
  CONTRACT,
  browserCandidates,
  buildPdf,
  createExclusiveTemporaryOutput,
  launchBrowser,
  parseArgs,
  safeLocalUrl,
  validateContract,
  validateStableContract,
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
    { id: "slide-1", kind: "content", x: 12, y: 648, width: 480, height: 600 },
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
      logo_mode: "primary",
      slides: [
        { id: "cover", title: "Titolo" },
        { id: "slide-1", title: "Contenuto", body: "Testo" },
      ],
      format: { ratio: "4:5", width: 1080, height: 1350 },
      typography: { heading: "Barlow", body: "Barlow" },
      brand: { name: "Test" },
      cover_visual: { mode: "typographic" },
      render_fingerprint: renderFingerprint,
      ...snapshotOverrides,
    },
    frames: resolvedFrames,
    geometry: resolvedGeometry,
  };
}

function mockPage(contracts, pixels = ["cover-pixels", "slide-pixels"]) {
  const contractQueue = [...contracts];
  const pixelQueues = pixels.map((value) => (Array.isArray(value) ? [...value] : [value]));
  const visitedUrls = [];
  return {
    visitedUrls,
    async goto(url) {
      visitedUrls.push(url);
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
              return { width: 480, height: 600 };
            },
            async screenshot() {
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
    ["prova_visuale_approvata", "rendering", "qa", "consegnato"],
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
    /Parità pixel fallita per la slide slide-1/,
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
    /cover è cambiata dopo la prima cattura/,
  );
  assert.equal(await fs.readFile(output, "utf8"), "previous-pdf");
  assert.deepEqual(await fs.readdir(directory), ["review.pdf"]);
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

"use strict";

const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const { EventEmitter } = require("node:events");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "..");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

function withTimeout(promise, milliseconds, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} oltre ${milliseconds} ms`)), milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function executable(candidates) {
  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      await fs.access(candidate, fs.constants.X_OK);
      return candidate;
    } catch (_error) {
      // Continue with the next explicit candidate.
    }
  }
  for (const name of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    const located = spawnSync("sh", ["-c", `command -v ${name}`], { encoding: "utf8" });
    if (located.status === 0 && located.stdout.trim()) return located.stdout.trim();
  }
  throw new Error("Chrome/Chromium non disponibile: lo smoke browser non può essere eseguito.");
}

function lineReader(stream, onLine) {
  const reader = readline.createInterface({ input: stream });
  reader.on("line", onLine);
  return reader;
}

async function startChrome(directory) {
  const chrome = await executable([
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ]);
  const ready = deferred();
  const diagnostics = [];
  const processHandle = spawn(chrome, [
    "--headless=new",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-gpu",
    "--no-first-run",
    "--no-sandbox",
    "--remote-debugging-port=0",
    "--remote-allow-origins=*",
    `--user-data-dir=${directory}`,
    "about:blank",
  ], { stdio: ["ignore", "pipe", "pipe"] });
  const inspect = (line) => {
    diagnostics.push(line);
    if (diagnostics.length > 40) diagnostics.shift();
    const match = line.match(/DevTools listening on (ws:\/\/\S+)/);
    if (match) ready.resolve(match[1]);
  };
  const readers = [lineReader(processHandle.stdout, inspect), lineReader(processHandle.stderr, inspect)];
  processHandle.once("error", ready.reject);
  processHandle.once("exit", (code, signal) => {
    ready.reject(new Error(`Chrome terminato prima del DevTools endpoint (${code ?? signal}).\n${diagnostics.join("\n")}`));
  });
  try {
    return {
      processHandle,
      readers,
      webSocketUrl: await withTimeout(ready.promise, 20_000, "Avvio Chrome"),
    };
  } catch (error) {
    processHandle.kill("SIGKILL");
    throw error;
  }
}

async function startServer(manifestPath, sessionDirectory, returnThreadId = "") {
  const python = process.env.PYTHON || "python3";
  const args = [
    path.join(ROOT, "scripts", "review_server.py"),
    manifestPath,
    "--session-dir",
    sessionDirectory,
    "--port",
    "0",
  ];
  if (returnThreadId) args.push("--return-thread-id", returnThreadId);
  const processHandle = spawn(python, args, {
    cwd: ROOT,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const ready = deferred();
  const diagnostics = [];
  const stdoutReader = lineReader(processHandle.stdout, (line) => {
    diagnostics.push(line);
    try {
      const payload = JSON.parse(line);
      if (payload.url) ready.resolve(payload);
    } catch (_error) {
      // Non-JSON output is retained for diagnostics.
    }
  });
  const stderrReader = lineReader(processHandle.stderr, (line) => diagnostics.push(line));
  processHandle.once("error", ready.reject);
  processHandle.once("exit", (code, signal) => {
    ready.reject(new Error(`Server terminato prima del ready (${code ?? signal}).\n${diagnostics.join("\n")}`));
  });
  try {
    return {
      processHandle,
      readers: [stdoutReader, stderrReader],
      ready: await withTimeout(ready.promise, 15_000, "Avvio review server"),
    };
  } catch (error) {
    processHandle.kill("SIGKILL");
    throw error;
  }
}

class CdpClient {
  constructor(webSocketUrl) {
    this.socket = new WebSocket(webSocketUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.opened = deferred();
    this.socket.addEventListener("open", () => this.opened.resolve());
    this.socket.addEventListener("error", (event) => this.opened.reject(event.error || new Error("WebSocket CDP non disponibile")));
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
      else pending.resolve(message.result || {});
    });
    this.socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("Connessione CDP chiusa"));
      this.pending.clear();
    });
  }

  async connect() {
    await withTimeout(this.opened.promise, 10_000, "Connessione CDP");
  }

  async send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const response = deferred();
    this.pending.set(id, { ...response, method });
    this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return withTimeout(response.promise, 15_000, method);
  }

  close() {
    this.socket.close();
  }
}

async function newIncognitoPage(client) {
  const { browserContextId } = await client.send("Target.createBrowserContext", { disposeOnDetach: true });
  const { targetId } = await client.send("Target.createTarget", { url: "about:blank", browserContextId });
  const { sessionId } = await client.send("Target.attachToTarget", { targetId, flatten: true });
  await Promise.all([
    client.send("Page.enable", {}, sessionId),
    client.send("Runtime.enable", {}, sessionId),
    client.send("Network.enable", {}, sessionId),
    client.send("Emulation.setDeviceMetricsOverride", {
      width: 1800,
      height: 1200,
      deviceScaleFactor: 1,
      mobile: false,
    }, sessionId),
  ]);
  return { browserContextId, targetId, sessionId };
}

async function evaluate(client, page, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  }, page.sessionId);
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate fallita");
  }
  return result.result?.value;
}

async function waitFor(client, page, expression, label, milliseconds = 15_000) {
  const deadline = Date.now() + milliseconds;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      if (await evaluate(client, page, `Boolean(${expression})`)) return;
    } catch (error) {
      lastError = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`${label} non osservato entro ${milliseconds} ms${lastError ? `: ${lastError}` : ""}`);
}

async function navigate(client, page, url) {
  const result = await client.send("Page.navigate", { url }, page.sessionId);
  if (result.errorText) throw new Error(`Navigazione fallita: ${result.errorText}`);
  await waitFor(client, page, "document.readyState === 'complete'", "document.readyState");
}

async function closePage(client, page) {
  await client.send("Target.closeTarget", { targetId: page.targetId }).catch(() => {});
  await client.send("Target.disposeBrowserContext", { browserContextId: page.browserContextId }).catch(() => {});
}

async function captureReviewScreenshot(client, page, filename) {
  const directory = process.env.UX_SCREENSHOT_DIR;
  if (!directory) return;
  await fs.mkdir(directory, { recursive: true });
  const screenshot = await client.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  }, page.sessionId);
  await fs.writeFile(path.join(directory, filename), Buffer.from(screenshot.data, "base64"));
}

function manifestFixture() {
  return {
    schema_version: "1.4",
    source_type: "article",
    sequence_mode: "narrative",
    workflow_state: "bozza",
    revision: 1,
    workflow_receipts: [],
    visual_style_system: "editorial-frame",
    production: {
      mode: "renderer",
      producer: "approved-preview-dom-v2",
      supported_style_systems: ["editorial-frame", "editorial-halftone", "corporate-modular"],
      expected_outputs: ["png", "pdf"],
    },
    proof: {
      slide_ids: ["cover", "item-2", "outro"],
      style_system_verified: false,
      approved: false,
    },
    format: {
      ratio: "4:5",
      master_width: 1080,
      master_height: 1350,
      width: 1440,
      height: 1800,
      preview_width: 480,
      preview_height: 600,
    },
    cover_title: "Una prova browser reale",
    cover_alt_text: "Copertina tipografica di prova",
    brand: {
      name: "Browser Smoke",
      website: "https://example.test",
      signature: "Test",
      fonts: {
        display: { family: "Browser Smoke Display", source: "uploaded", file: "display.ttf" },
      },
      palette: {
        background_light: "#F5F1E8",
        background_dark: "#172033",
        text_on_light: "#172033",
        text_on_dark: "#FFFFFF",
        accent: "#FEBD08",
      },
    },
    items: [
      { id: "item-1", layout: "editorial", title: "", summary: "Prima frase.", alt_text: "Prima card" },
      { id: "item-2", layout: "editorial", title: "", summary: "Seconda frase più densa.", alt_text: "Seconda card" },
    ],
    outro: { enabled: true, title: "Chiusura", body: "Corpo della chiusura.", alt_text: "Chiusura" },
    accessibility: {
      reading_order: ["cover", "item-1", "item-2", "outro"],
      transcript: "Trascrizione di prova",
    },
  };
}

async function stopProcess(processHandle, milliseconds = 5_000) {
  if (processHandle.exitCode !== null || processHandle.signalCode !== null) return;
  const exited = new Promise((resolve) => processHandle.once("exit", resolve));
  processHandle.kill("SIGTERM");
  try {
    await withTimeout(exited, milliseconds, "Arresto processo figlio");
  } catch (_error) {
    if (processHandle.exitCode === null && processHandle.signalCode === null) {
      processHandle.kill("SIGKILL");
      await withTimeout(exited, milliseconds, "Arresto forzato processo figlio").catch(() => {});
    }
  }
}

async function readJsonWhen(filePath, predicate, label, milliseconds = 10_000) {
  const deadline = Date.now() + milliseconds;
  while (Date.now() < deadline) {
    try {
      const value = JSON.parse(await fs.readFile(filePath, "utf8"));
      if (predicate(value)) return value;
    } catch (_error) {
      // The durable replace may not have happened yet.
    }
    const remaining = deadline - Date.now();
    if (remaining > 0) {
      await new Promise((resolve) => setTimeout(resolve, Math.min(50, remaining)));
    }
  }
  throw new Error(`${label} oltre ${milliseconds} ms`);
}

test("readJsonWhen termina il polling alla deadline senza lasciare timer", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-json-poll-"));
  try {
    await assert.rejects(
      readJsonWhen(path.join(directory, "missing.json"), () => false, "Polling test", 75),
      /Polling test oltre 75 ms/,
    );
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("stopProcess cancella il timer sul termine rapido e forza SIGKILL dopo la deadline", async () => {
  const quick = new EventEmitter();
  quick.exitCode = null;
  quick.signalCode = null;
  quick.kill = (signal) => {
    quick.signalCode = signal;
    queueMicrotask(() => quick.emit("exit", null, signal));
  };
  const started = Date.now();
  await stopProcess(quick, 1_000);
  assert.ok(Date.now() - started < 250);

  const stuck = new EventEmitter();
  stuck.exitCode = null;
  stuck.signalCode = null;
  const signals = [];
  stuck.kill = (signal) => {
    signals.push(signal);
    if (signal === "SIGKILL") {
      stuck.signalCode = signal;
      queueMicrotask(() => stuck.emit("exit", null, signal));
    }
  };
  await stopProcess(stuck, 25);
  assert.deepEqual(signals, ["SIGTERM", "SIGKILL"]);
});

test("browser reale: i due consensi restano distinti e la prova visiva è read-first anche su mobile", { timeout: 90_000 }, async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-browser-proof-"));
  const manifestPath = path.join(directory, "manifest.json");
  const sessionDirectory = path.join(directory, "session");
  const chromeDirectory = path.join(directory, "chrome-profile");
  let server = null;
  let chrome = null;
  let client = null;
  context.after(async () => {
    if (client) {
      await client.send("Browser.close").catch(() => {});
      client.close();
    }
    await Promise.all([
      ...(chrome ? [stopProcess(chrome.processHandle)] : []),
      ...(server ? [stopProcess(server.processHandle)] : []),
    ]);
    for (const reader of [...(chrome?.readers || []), ...(server?.readers || [])]) reader.close();
    await fs.rm(directory, { recursive: true, force: true });
  });
  const twoCheckpointManifest = manifestFixture();
  twoCheckpointManifest.cover_mode = "generated";
  await fs.writeFile(manifestPath, `${JSON.stringify(twoCheckpointManifest, null, 2)}\n`, "utf8");
  await fs.copyFile(path.join(ROOT, "assets", "fonts", "Inter-Variable.ttf"), path.join(directory, "display.ttf"));
  await fs.mkdir(chromeDirectory);

  server = await startServer(manifestPath, sessionDirectory);
  chrome = await startChrome(chromeDirectory);
  client = new CdpClient(chrome.webSocketUrl);
  await client.connect();
  const page = await newIncognitoPage(client);
  await navigate(client, page, server.ready.url);
  await waitFor(client, page, "document.documentElement.dataset.previewReady === 'true'", "anteprima editoriale pronta");
  assert.deepEqual(
    await evaluate(client, page, `({
      cta: document.querySelector('#approve-button').textContent,
      title: document.querySelector('#workflow-journey-title').textContent,
      current: document.querySelector('#workflow-steps [aria-current="step"] strong').textContent,
    })`),
    { cta: "Approva i testi", title: "Revisione di profilo e testi", current: "Profilo e testi" },
  );

  await evaluate(client, page, `document.querySelector('#approve-button').click()`);
  await waitFor(client, page, "document.querySelector('#approval-dialog').open", "dialog primo consenso");
  assert.equal(
    await evaluate(client, page, "document.querySelector('#approval-dialog-copy').textContent.includes('primo consenso')"),
    true,
  );
  await evaluate(client, page, `document.querySelector('#confirm-approval').click()`);
  const feedbackPath = path.join(sessionDirectory, "feedback.json");
  const approval = await readJsonWhen(feedbackPath, (value) => value.action === "approve", "Persistenza primo consenso");
  assert.equal(approval.approval_scope, undefined);
  const sessionState = JSON.parse(await fs.readFile(path.join(sessionDirectory, "session-state.json"), "utf8"));
  const processed = spawnSync(process.env.PYTHON || "python3", [
    path.join(ROOT, "scripts", "process_review.py"),
    manifestPath,
    sessionState.last_feedback_path,
    "--session-dir",
    sessionDirectory,
  ], { cwd: ROOT, encoding: "utf8" });
  assert.equal(processed.status, 0, processed.stderr || processed.stdout);
  await waitFor(
    client,
    page,
    `document.querySelector('#editor').classList.contains('proof-mode')
      && !document.querySelector('#editor').classList.contains('proof-editing')
      && document.querySelector('#approve-button').textContent === 'Genera'`,
    "secondo checkpoint read-first",
  );
  assert.deepEqual(
    await evaluate(client, page, `({
      title: document.querySelector('#workflow-journey-title').textContent,
      current: document.querySelector('#workflow-steps [aria-current="step"] strong').textContent,
      formDisplay: getComputedStyle(document.querySelector('.slide-form')).display,
      filmstripFlow: getComputedStyle(document.querySelector('#slides')).gridAutoFlow,
      toggle: document.querySelector('#toggle-proof-editing').textContent,
      toast: document.querySelector('#toast').textContent,
    })`),
    {
      title: "Controlla la prova visiva",
      current: "Prova visiva",
      formDisplay: "none",
      filmstripFlow: "column",
      toggle: "Modifica contenuti o grafica",
      toast: "Testi approvati. Ora controlla la prova visiva.",
    },
  );
  await captureReviewScreenshot(client, page, "proof-desktop.png");
  await evaluate(client, page, `document.querySelector('#toggle-proof-editing').click()`);
  await waitFor(
    client,
    page,
    `document.querySelector('#editor').classList.contains('proof-editing')
      && getComputedStyle(document.querySelector('.slide-form')).display !== 'none'`,
    "riapertura esplicita delle modifiche",
  );
  assert.match(
    await evaluate(client, page, "document.querySelector('#proof-editing-note').textContent"),
    /riapriranno anche l’approvazione editoriale/,
  );
  await evaluate(client, page, `document.querySelector('#toggle-proof-editing').click()`);

  await client.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  }, page.sessionId);
  await waitFor(client, page, "window.innerWidth === 390", "viewport mobile 390 px");
  const mobile = await evaluate(client, page, `(() => {
    const journey = document.querySelector('#workflow-journey').getBoundingClientRect();
    const slides = document.querySelector('#slides');
    const preview = document.querySelector('.slide-preview').getBoundingClientRect();
    return {
      bodyWidth: document.body.scrollWidth,
      viewportWidth: window.innerWidth,
      journeyLeft: journey.left,
      journeyRight: journey.right,
      filmstripScrollable: slides.scrollWidth > slides.clientWidth,
      previewWidth: preview.width,
      desktopActions: getComputedStyle(document.querySelector('.actions')).display,
      mobileActions: getComputedStyle(document.querySelector('#mobile-actions-button')).display,
    };
  })()`);
  assert.ok(mobile.bodyWidth <= mobile.viewportWidth, JSON.stringify(mobile));
  assert.ok(mobile.journeyLeft >= 0 && mobile.journeyRight <= mobile.viewportWidth, JSON.stringify(mobile));
  assert.equal(mobile.filmstripScrollable, true);
  assert.ok(mobile.previewWidth >= 280 && mobile.previewWidth < 390, JSON.stringify(mobile));
  assert.equal(mobile.desktopActions, "none");
  assert.notEqual(mobile.mobileActions, "none");
  await captureReviewScreenshot(client, page, "proof-mobile.png");
  await closePage(client, page);
});

test("browser reale: consenso combinato, fresh production 480x600, riordino, submit e recovery", { timeout: 90_000 }, async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-browser-smoke-"));
  const manifestPath = path.join(directory, "manifest.json");
  const sessionDirectory = path.join(directory, "session");
  const chromeDirectory = path.join(directory, "chrome-profile");
  let server = null;
  let chrome = null;
  let client = null;
  context.after(async () => {
    if (client) {
      await client.send("Browser.close").catch(() => {});
      client.close();
    }
    await Promise.all([
      ...(chrome ? [stopProcess(chrome.processHandle)] : []),
      ...(server ? [stopProcess(server.processHandle)] : []),
    ]);
    for (const reader of [...(chrome?.readers || []), ...(server?.readers || [])]) reader.close();
    await fs.rm(directory, { recursive: true, force: true });
  });
  await fs.writeFile(manifestPath, `${JSON.stringify(manifestFixture(), null, 2)}\n`, "utf8");
  const displayFontPath = path.join(directory, "display.ttf");
  await fs.copyFile(path.join(ROOT, "assets", "fonts", "Inter-Variable.ttf"), displayFontPath);
  await fs.mkdir(chromeDirectory);

  const returnThreadId = "01a01e64-3e6e-7b71-950d-c425e032e34e";
  server = await startServer(manifestPath, sessionDirectory, returnThreadId);
  chrome = await startChrome(chromeDirectory);
  client = new CdpClient(chrome.webSocketUrl);
  await client.connect();

  const sessionUrl = new URL(server.ready.url);
  sessionUrl.pathname = "/api/session";
  const sessionResponse = await fetch(sessionUrl);
  assert.equal(sessionResponse.status, 200);
  const session = await sessionResponse.json();
  assert.equal(session.schema_version, "1.4");
  assert.equal(session.return_url, `codex://threads/${returnThreadId}`);
  assert.equal(session.production.producer, "approved-preview-dom-v2");
  assert.deepEqual(session.proof.required_slide_ids, ["cover", "item-2", "outro"]);

  const approvalPage = await newIncognitoPage(client);
  await client.send("Network.setBlockedURLs", { urls: ["*/api/font/display*"] }, approvalPage.sessionId);
  await navigate(client, approvalPage, server.ready.url);
  await waitFor(
    client,
    approvalPage,
    `!document.querySelector('#editor').classList.contains('hidden')
      && [...document.querySelectorAll('.slide-preview')].length === 4
      && [...document.querySelectorAll('.slide-preview')].every((preview) => {
        const box = preview.getBoundingClientRect();
        return box.width === 480 && box.height === 600;
      })`,
    "anteprima approvabile 480x600",
  );
  await waitFor(
    client,
    approvalPage,
    "document.documentElement.dataset.previewReady === 'true' || Boolean(document.documentElement.dataset.productionError)",
    "esito contratto anteprima approvabile",
  );
  const initialChoices = await evaluate(client, approvalPage, `({
    visualSystems: document.querySelectorAll('.visual-system-option').length,
    coverChoice: document.querySelector('[data-cover-choice][aria-checked="true"]').dataset.coverChoice,
  })`);
  assert.deepEqual(initialChoices, {
    visualSystems: 3,
    coverChoice: "typographic",
  });
  await evaluate(client, approvalPage, `document.querySelector('[data-visual-system="corporate-modular"]').click()`);
  assert.deepEqual(
    await evaluate(client, approvalPage, `({
      systems: [...document.querySelectorAll('.visual-system-option')].map((option) => option.dataset.visualSystem),
      selected: document.querySelector('.visual-system-option[aria-checked="true"]').dataset.visualSystem,
    })`),
    { systems: ["editorial-frame", "editorial-halftone", "corporate-modular"], selected: "corporate-modular" },
  );
  await evaluate(client, approvalPage, `document.querySelector('[data-visual-system="editorial-frame"]').click()`);
  await evaluate(client, approvalPage, `document.querySelector('[data-cover-choice="visual"]').click()`);
  await waitFor(
    client,
    approvalPage,
    `document.querySelector('[data-slide-id="cover"] .slide-preview').classList.contains('cover-split')
      && Boolean(document.querySelector('[data-slide-id="cover"] .preview-cover-placeholder'))`,
    "intenzione cover visuale in split",
  );
  await evaluate(client, approvalPage, `document.querySelector('[data-cover-choice="typographic"]').click()`);
  await waitFor(
    client,
    approvalPage,
    `!document.querySelector('[data-slide-id="cover"] .slide-preview').classList.contains('cover-split')`,
    "ripristino cover tipografica",
  );
  await waitFor(
    client,
    approvalPage,
    "document.documentElement.dataset.previewReady === 'true' || Boolean(document.documentElement.dataset.productionError)",
    "nuovo contratto dopo il ripristino della cover",
  );
  const approvalPreviewState = await evaluate(client, approvalPage, `({
    ready: document.documentElement.dataset.previewReady || "",
    error: document.documentElement.dataset.productionError || "",
    approveDisabled: document.querySelector('#approve-button').disabled,
    fontAlertHidden: document.querySelector('#font-status').hidden,
    fontAlert: document.querySelector('#font-status').textContent,
  })`);
  assert.equal(approvalPreviewState.ready, "true");
  assert.equal(approvalPreviewState.error, "");
  assert.equal(approvalPreviewState.approveDisabled, false);
  assert.equal(approvalPreviewState.fontAlertHidden, false);
  assert.match(approvalPreviewState.fontAlert, /fallback/);

  // The rejected promise must leave the cache. Restoring reachability and
  // asking for a fresh render must retry the same URL and certify it without
  // changing the manifest fingerprint.
  await client.send("Network.setBlockedURLs", { urls: [] }, approvalPage.sessionId);
  await evaluate(client, approvalPage, `document.querySelector('[data-slide-id="item-1"] [data-action="move-down"]').click()`);
  await waitFor(
    client,
    approvalPage,
    "document.documentElement.dataset.previewReady === 'true'",
    "retry del font corretto e contratto anteprima",
  );
  await evaluate(client, approvalPage, `document.querySelector('#undo-button').click()`);
  await waitFor(
    client,
    approvalPage,
    `document.documentElement.dataset.previewReady === 'true'
      && JSON.stringify([...document.querySelectorAll('.slide-row')].map((row) => row.dataset.slideId)) === '["cover","item-1","item-2","outro"]'`,
    "ripristino della bozza dopo il retry",
  );
  const retryPreviewState = await evaluate(client, approvalPage, `({
    ready: document.documentElement.dataset.previewReady || "",
    error: document.documentElement.dataset.productionError || "",
    fontAlertHidden: document.querySelector('#font-status').hidden,
  })`);
  assert.deepEqual(retryPreviewState, { ready: "true", error: "", fontAlertHidden: true });

  // Navigation intent alone does not mark the sample as viewed. This remains
  // an advisory and never prevents the explicit combined consent.
  await evaluate(client, approvalPage, `(() => {
    for (const slideId of ['cover', 'item-2', 'outro']) {
      document.querySelector('[data-sequence-slide="' + slideId + '"]').click();
    }
    document.querySelector('#approve-button').click();
  })()`);
  assert.equal(
    await evaluate(client, approvalPage, "document.querySelector('#approval-dialog').open"),
    true,
    "le slide campione non viste non devono bloccare l'approvazione esplicita",
  );
  assert.deepEqual(
    await evaluate(client, approvalPage, `({
      label: document.querySelector('#approve-button').textContent,
      scope: document.querySelector('#approval-dialog').dataset.approvalScope || "",
      title: document.querySelector('#approval-dialog-title').textContent,
      currentStep: document.querySelector('#workflow-steps [aria-current="step"] strong').textContent,
    })`),
    { label: "Genera", scope: "profile_text_and_visual", title: "Generare il carosello?", currentStep: "Profilo e testi" },
  );
  await evaluate(client, approvalPage, "document.querySelector('#approval-dialog').close()");

  // Bring every required preview into the viewport and wait for the real
  // >= 50% IntersectionObserver confirmation before approving.
  for (const slideId of ["cover", "item-2", "outro"]) {
    await evaluate(client, approvalPage, `document.querySelector('[data-slide-id="${slideId}"] .slide-preview').scrollIntoView({ block: 'center' })`);
    await waitFor(
      client,
      approvalPage,
      `document.querySelector('[data-slide-id="${slideId}"]').classList.contains('is-viewed')`,
      `osservazione reale della proof ${slideId}`,
    );
  }
  await waitFor(
    client,
    approvalPage,
    "document.querySelector('#approve-button').textContent === 'Genera'",
    "abilitazione consenso combinato",
  );
  assert.deepEqual(
    await evaluate(client, approvalPage, `({
      status: document.querySelector('#agent-status-label').textContent,
      copy: document.querySelector('#workflow-journey-copy').textContent,
    })`),
    {
      status: "Consenso unico disponibile",
      copy: "La prova tipografica è già definitiva: il prossimo consenso approverà insieme testi e grafica.",
    },
  );
  await evaluate(client, approvalPage, `document.querySelector('#approve-button').click()`);
  await waitFor(client, approvalPage, "document.querySelector('#approval-dialog').open === true", "dialog approvazione combinata");
  assert.equal(
    await evaluate(client, approvalPage, "document.querySelector('#approval-dialog').dataset.approvalScope"),
    "profile_text_and_visual",
  );
  await evaluate(client, approvalPage, `document.querySelector('#confirm-approval').click()`);
  const feedbackPath = path.join(sessionDirectory, "feedback.json");
  const approval = await readJsonWhen(feedbackPath, (value) => value.action === "approve", "Persistenza approvazione");
  assert.equal(approval.approval_scope, "profile_text_and_visual");
  assert.deepEqual(approval.proof_slide_ids, ["cover", "item-2", "outro"]);
  assert.equal(approval.style_system_verified, false);
  assert.equal(approval.proof_browser.engine, "chromium");
  assert.ok(Number.isInteger(approval.proof_browser.major) && approval.proof_browser.major > 0);

  const sessionState = JSON.parse(await fs.readFile(path.join(sessionDirectory, "session-state.json"), "utf8"));
  const processed = spawnSync(process.env.PYTHON || "python3", [
    path.join(ROOT, "scripts", "process_review.py"),
    manifestPath,
    sessionState.last_feedback_path,
    "--session-dir",
    sessionDirectory,
  ], { cwd: ROOT, encoding: "utf8" });
  assert.equal(processed.status, 0, processed.stderr || processed.stdout);
  const processResult = JSON.parse(processed.stdout);
  assert.equal(processResult.status, "advanced");
  assert.equal(processResult.advanced.to, "prova_visuale_approvata");
  const approvedManifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  assert.equal(approvedManifest.proof.approved, true);
  assert.deepEqual(approvedManifest.proof.browser, approval.proof_browser);
  const proofManifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  assert.equal(proofManifest.workflow_receipts.length, 2);
  assert.deepEqual(
    proofManifest.workflow_receipts.map((receipt) => [receipt.from, receipt.to]),
    [
      ["bozza", "testi_approvati"],
      ["testi_approvati", "prova_visuale_approvata"],
    ],
  );
  const approvedResponse = await fetch(sessionUrl);
  assert.equal(approvedResponse.status, 200);
  const approvedSession = await approvedResponse.json();
  assert.equal(approvedSession.proof_approved, true);
  assert.equal(approvedSession.workflow_state, "prova_visuale_approvata");
  await waitFor(
    client,
    approvalPage,
    "document.querySelector('#agent-status-label').textContent === 'Pronto per la produzione'",
    "stato pre-produzione non fuorviante",
  );
  assert.deepEqual(
    await evaluate(client, approvalPage, `({
      status: document.querySelector('#agent-status-label').textContent,
      detail: document.querySelector('#agent-status-detail').textContent,
      copy: document.querySelector('#workflow-journey-copy').textContent,
      returnHidden: document.querySelector('#return-chat-button').hidden,
      returnLabel: document.querySelector('#return-chat-button').textContent.trim(),
    })`),
    {
      status: "Pronto per la produzione",
      detail: "L’approvazione è registrata. Torna alla chat per avviare rendering e controlli.",
      copy: "I due consensi sono registrati. Il rendering non è ancora iniziato.",
      returnHidden: false,
      returnLabel: "Torna alla chat",
    },
  );
  await closePage(client, approvalPage);

  const productionPage = await newIncognitoPage(client);
  const productionUrl = new URL(server.ready.url);
  productionUrl.searchParams.set("render", "production");
  productionUrl.searchParams.set("capture", "smoke");
  await navigate(client, productionPage, productionUrl.toString());
  await waitFor(
    client,
    productionPage,
    "document.documentElement.dataset.productionReady === 'true' || Boolean(document.documentElement.dataset.productionError)",
    "esito contratto production",
  );
  const productionState = await evaluate(client, productionPage, `({
    ready: document.documentElement.dataset.productionReady || "",
    error: document.documentElement.dataset.productionError || "",
  })`);
  assert.deepEqual(productionState, { ready: "true", error: "" });
  const production = await evaluate(client, productionPage, `(() => {
    const previews = [...document.querySelectorAll('.slide-preview[data-production-source="approved-preview"]')];
    const contract = window.carouselBuilderPreview.getRenderContract();
    return {
      localStorageEntries: localStorage.length,
      contract: contract.contract,
      production: contract.production,
      proofApproved: contract.proofApproved,
      workflowState: contract.workflowState,
      frameIds: contract.frames.map((frame) => frame.id),
      bounds: previews.map((preview) => {
        const box = preview.getBoundingClientRect();
        return { width: box.width, height: box.height };
      }),
      error: document.documentElement.dataset.productionError || "",
    };
  })()`);
  assert.equal(production.localStorageEntries, 0, "un contesto production fresco non deve idratarsi da bozze locali");
  assert.equal(production.contract, "approved-preview-dom-v2");
  assert.equal(production.production, true);
  assert.equal(production.proofApproved, true);
  assert.equal(production.workflowState, "prova_visuale_approvata");
  assert.equal(production.error, "");
  assert.deepEqual(production.frameIds, ["cover", "item-1", "item-2", "outro"]);
  assert.deepEqual(production.bounds, Array(4).fill({ width: 480, height: 600 }));

  // In production mode the first 480x600 viewport surface is the first
  // already-validated preview box; this is a raster smoke, not a pixel golden.
  const productionViewportRaster = await client.send("Page.captureScreenshot", {
    format: "png",
    clip: { x: 0, y: 0, width: 480, height: 600, scale: 1 },
    captureBeyondViewport: false,
  }, productionPage.sessionId);
  const png = Buffer.from(productionViewportRaster.data, "base64");
  assert.equal(png.subarray(1, 4).toString("ascii"), "PNG");
  assert.equal(png.readUInt32BE(16), 480);
  assert.equal(png.readUInt32BE(20), 600);
  await closePage(client, productionPage);

  const editorPage = await newIncognitoPage(client);
  await navigate(client, editorPage, server.ready.url);
  await waitFor(client, editorPage, "!document.querySelector('#editor').classList.contains('hidden')", "editor caricato");
  assert.deepEqual(
    await evaluate(client, editorPage, `[...document.querySelectorAll('.slide-row')].map((row) => row.dataset.slideId)`),
    ["cover", "item-1", "item-2", "outro"],
  );
  await evaluate(client, editorPage, `document.querySelector('[data-slide-id="item-1"] [data-action="move-down"]').click()`);
  await waitFor(
    client,
    editorPage,
    `JSON.stringify([...document.querySelectorAll('.slide-row')].map((row) => row.dataset.slideId)) === '["cover","item-2","item-1","outro"]'`,
    "riordino UI",
  );
  await evaluate(client, editorPage, `document.querySelector('#send-button').click()`);
  await waitFor(
    client,
    editorPage,
    `document.querySelector('#editor').classList.contains('locked')`,
    "submit confermato e UI bloccata",
  );
  const feedback = await readJsonWhen(
    feedbackPath,
    (value) => value.action === "feedback" && value.feedback_id !== approval.feedback_id,
    "Persistenza feedback",
  );
  assert.equal(feedback.action, "feedback");
  assert.deepEqual(feedback.slides.map((slide) => slide.id), ["cover", "item-2", "item-1", "outro"]);

  const nextManifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  const feedbackBaseRevision = nextManifest.revision;
  nextManifest.revision += 1;
  await fs.writeFile(manifestPath, `${JSON.stringify(nextManifest, null, 2)}\n`, "utf8");
  await client.send("Page.reload", { ignoreCache: true }, editorPage.sessionId);
  await waitFor(
    client,
    editorPage,
    `document.querySelector('#revision-label')?.textContent === 'Revisione ${nextManifest.revision}'`,
    "nuova revisione",
  );
  await waitFor(
    client,
    editorPage,
    `document.querySelector('#export-recovery-button')?.hidden === false`,
    "recovery visibile",
  );
  const recovery = await evaluate(client, editorPage, `(() => {
    const values = Object.keys(localStorage).map((key) => {
      try { return JSON.parse(localStorage.getItem(key)); } catch (_error) { return null; }
    }).filter(Boolean);
    const records = values.filter((value) => value.schema === 'carousel-builder-feedback-recovery-v1');
    return {
      count: records.length,
      reasons: records.map((value) => value.reason),
      baseRevisions: records.map((value) => value.base_revision),
      orders: records.map((value) => value.payload?.slides?.map((slide) => slide.id) || []),
      buttonVisible: document.querySelector('#export-recovery-button')?.hidden === false,
    };
  })()`);
  assert.equal(recovery.buttonVisible, true);
  assert.ok(recovery.count >= 1, JSON.stringify(recovery));
  assert.ok(recovery.reasons.includes("pre-post-backup"), JSON.stringify(recovery));
  assert.ok(recovery.baseRevisions.includes(feedbackBaseRevision), JSON.stringify(recovery));
  assert.ok(
    recovery.orders.some((order) => JSON.stringify(order) === '["cover","item-2","item-1","outro"]'),
    JSON.stringify(recovery),
  );
  await closePage(client, editorPage);
});

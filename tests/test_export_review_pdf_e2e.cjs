"use strict";

const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "..");

function executable(candidates) {
  for (const candidate of candidates) {
    if (!candidate) continue;
    const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (probe.status === 0) return { path: candidate, version: probe.stdout || probe.stderr };
  }
  for (const name of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    const located = spawnSync("sh", ["-c", `command -v ${name}`], { encoding: "utf8" });
    if (located.status === 0 && located.stdout.trim()) {
      const candidate = located.stdout.trim();
      const probe = spawnSync(candidate, ["--version"], { encoding: "utf8" });
      if (probe.status === 0) return { path: candidate, version: probe.stdout || probe.stderr };
    }
  }
  throw new Error("Chrome/Chromium non disponibile per l'export E2E.");
}

function stopProcess(processHandle) {
  if (!processHandle || processHandle.exitCode !== null || processHandle.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(() => processHandle.kill("SIGKILL"), 3_000);
    processHandle.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    processHandle.kill("SIGTERM");
  });
}

async function startServer(manifestPath, sessionDirectory) {
  const child = spawn(process.env.PYTHON || "python3", [
    path.join(ROOT, "scripts", "review_server.py"),
    manifestPath,
    "--session-dir", sessionDirectory,
    "--port", "0",
  ], {
    cwd: ROOT,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const diagnostics = [];
  const stderr = readline.createInterface({ input: child.stderr });
  stderr.on("line", (line) => diagnostics.push(line));
  const stdout = readline.createInterface({ input: child.stdout });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server non pronto:\n${diagnostics.join("\n")}`)), 15_000);
    child.once("exit", (code) => reject(new Error(`Server terminato con ${code}:\n${diagnostics.join("\n")}`)));
    stdout.on("line", (line) => {
      try {
        const payload = JSON.parse(line);
        if (payload.url) {
          clearTimeout(timer);
          resolve(payload);
        }
      } catch (_error) {
        diagnostics.push(line);
      }
    });
  });
  return { child, readers: [stdout, stderr], ready: await ready };
}

function pngDimensions(bytes) {
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

test("export reale pubblica PDF, PNG, contact sheet e result JSON coerenti", { timeout: 120_000 }, async (context) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "carousel-export-e2e-"));
  let server = null;
  context.after(async () => {
    await stopProcess(server?.child);
    for (const reader of server?.readers || []) reader.close();
    await fs.rm(directory, { recursive: true, force: true });
  });

  const chrome = executable([
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ]);
  const majorMatch = chrome.version.match(/(\d+)(?:\.\d+){2,}/);
  assert.ok(majorMatch, `Versione Chromium non riconosciuta: ${chrome.version}`);
  const fixtureRoot = path.join(directory, "fixture");
  const fixture = spawnSync(process.env.PYTHON || "python3", [
    path.join(ROOT, "tests", "export_e2e_fixture.py"), fixtureRoot, majorMatch[1],
  ], { cwd: ROOT, encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  assert.equal(fixture.status, 0, fixture.stderr);
  const prepared = JSON.parse(fixture.stdout);
  server = await startServer(prepared.manifest, prepared.session_dir);

  const output = path.join(prepared.output_dir, "carousel.pdf");
  const pngDir = path.join(prepared.output_dir, "png");
  const contactSheet = path.join(prepared.output_dir, "contact-sheet.png");
  const resultJson = path.join(prepared.output_dir, "render-result.json");
  const exported = spawnSync(process.execPath, [
    path.join(ROOT, "scripts", "export_review_pdf.cjs"),
    "--url", server.ready.url,
    "--output", output,
    "--node-modules", path.join(ROOT, "node_modules"),
    "--chrome", chrome.path,
    "--png-dir", pngDir,
    "--contact-sheet", contactSheet,
    "--result-json", resultJson,
  ], { cwd: ROOT, encoding: "utf8", timeout: 100_000 });
  assert.equal(exported.status, 0, exported.stderr || exported.error?.message);
  const publicResult = JSON.parse(exported.stdout.trim());
  const durableResult = JSON.parse(await fs.readFile(resultJson, "utf8"));
  assert.deepEqual(publicResult, durableResult);
  assert.equal(durableResult.status, "ok");
  assert.equal(durableResult.contract, "approved-preview-dom-v2");
  assert.equal(durableResult.workflow_state, "rendering");
  assert.equal(durableResult.render_fingerprint, prepared.render_fingerprint);
  assert.equal(durableResult.artifact_sha256.length, prepared.slides + 2);

  const pdf = await fs.readFile(output);
  assert.equal(pdf.subarray(0, 4).toString("ascii"), "%PDF");
  const pngFiles = (await fs.readdir(pngDir)).sort();
  assert.equal(pngFiles.length, prepared.slides);
  for (const filename of pngFiles) {
    assert.deepEqual(pngDimensions(await fs.readFile(path.join(pngDir, filename))), [1440, 1800]);
  }
  assert.deepEqual(pngDimensions(await fs.readFile(contactSheet)), [1560, 498]);
  const residues = (await fs.readdir(prepared.output_dir)).filter((name) =>
    /(?:\.tmp|\.previous|export-(?:claim|staging|transaction))/.test(name)
  );
  assert.deepEqual(residues, []);
});

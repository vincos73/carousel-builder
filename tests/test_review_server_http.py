"""Test di integrazione sul server locale: autorizzazione, host e concorrenza."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from support import SCRIPTS, base_manifest, slide, write_json


def request(
    url: str, *, method: str = "GET", body: bytes | None = None, headers: dict | None = None
) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method=method)
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = response.read()
            return response.status, payload
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def json_request(url: str, **kwargs: object) -> tuple[int, dict]:
    status, payload = request(url, **kwargs)
    return status, json.loads(payload.decode("utf-8"))


class ReviewServerHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.manifest_path = self.workdir / "manifest.json"
        self.session_dir = self.workdir / "session"
        self.font_path = self.workdir / "brand.woff2"
        self.font_path.write_bytes(b"test font bytes")
        self.display_font_path = self.workdir / "display.ttf"
        self.display_font_path.write_bytes(b"display font bytes")
        self.cover_path = self.workdir / "cover.png"
        self.cover_path.write_bytes(b"test image bytes")
        self.logo_path = self.workdir / "logo.png"
        self.logo_path.write_bytes(b"test logo bytes")
        manifest = base_manifest()
        manifest["cover_image"] = "cover.png"
        manifest["brand"] = {
            "logos": {"on_light": "logo.png"},
            "fonts": {
                "display": {
                    "family": "Review Display",
                    "file": "display.ttf",
                    "source": "uploaded",
                },
                "sans": {
                    "family": "Review Sans",
                    "file": "brand.woff2",
                    "source": "uploaded",
                },
                "serif": {"family": "Missing Serif", "file": "missing.ttf"},
            }
        }
        write_json(self.manifest_path, manifest)
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPTS / "review_server.py"),
                str(self.manifest_path),
                "--session-dir",
                str(self.session_dir),
                "--port",
                "0",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.stop)
        ready = json.loads(self.process.stdout.readline())
        self.url = ready["url"]
        parsed = urlparse(self.url)
        self.origin = f"http://127.0.0.1:{parsed.port}"
        self.token = parse_qs(parsed.query)["token"][0]

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def api(self, path: str) -> str:
        return f"{self.origin}{path}?token={self.token}"

    def batch(self, **overrides: object) -> bytes:
        payload = {
            "action": "feedback",
            "base_revision": 1,
            "slides": [
                slide("cover", "cover", title="La lezione e operativa"),
                slide("item-1", "item", summary="Prima frase."),
                slide("item-2", "item", summary="Seconda frase."),
                slide("outro", "outro", title="Chiusura", summary="Corpo."),
            ],
            "comments": [],
            "overall_note": "",
        }
        payload.update(overrides)
        return json.dumps(payload).encode("utf-8")

    def test_serves_the_editor_with_a_valid_token(self) -> None:
        status, payload = request(self.url)
        self.assertEqual(status, 200)
        self.assertIn(b"Carousel Builder Editor", payload)

    def test_rejects_a_missing_or_wrong_token(self) -> None:
        self.assertEqual(request(f"{self.origin}/")[0], 403)
        self.assertEqual(request(f"{self.origin}/?token=sbagliato")[0], 403)
        self.assertEqual(request(f"{self.origin}/api/session")[0], 403)
        self.assertEqual(request(f"{self.origin}/api/status")[0], 403)

    def test_rejects_a_foreign_host_header(self) -> None:
        status, payload = json_request(
            self.api("/api/session"), headers={"Host": "attaccante.example"}
        )
        self.assertEqual(status, 403)
        self.assertIn("Host", payload["error"])

    def test_accepts_localhost_as_host(self) -> None:
        status, _ = request(self.api("/api/session"), headers={"Host": "localhost"})
        self.assertEqual(status, 200)

    def test_serves_the_static_assets(self) -> None:
        for path in (
            "/assets/styles.css",
            "/assets/app.js",
            "/assets/vincos-lockup-white.svg",
            "/styles.css",
            "/app.js",
            "/assets/fonts/Inter-Variable.ttf",
            "/assets/fonts/PlayfairDisplay-Variable.ttf",
            "/assets/fonts/PlayfairDisplay-Italic-Variable.ttf",
            "/assets/fonts/InstrumentSerif-Regular.ttf",
            "/assets/fonts/Onest-Regular.ttf",
            "/assets/fonts/Onest-Medium.ttf",
            "/assets/fonts/Onest-Semibold.ttf",
            "/assets/fonts/Onest-Bold.ttf",
            "/assets/fonts/Orbitron-Variable.ttf",
        ):
            status, payload = request(f"{self.origin}{path}")
            self.assertEqual(status, 200, path)
            self.assertTrue(payload)

    def test_serves_every_font_declared_by_the_editor_stylesheet(self) -> None:
        status, stylesheet = request(f"{self.origin}/assets/styles.css")
        self.assertEqual(status, 200)
        font_paths = {
            match.decode("utf-8")
            for match in re.findall(rb'url\("(/assets/fonts/[^\"]+)"\)', stylesheet)
        }
        self.assertEqual(
            font_paths,
            {
                "/assets/fonts/InstrumentSerif-Regular.ttf",
                "/assets/fonts/Inter-Variable.ttf",
                "/assets/fonts/Onest-Bold.ttf",
                "/assets/fonts/Onest-Medium.ttf",
                "/assets/fonts/Onest-Regular.ttf",
                "/assets/fonts/Onest-Semibold.ttf",
                "/assets/fonts/Orbitron-Variable.ttf",
                "/assets/fonts/PlayfairDisplay-Italic-Variable.ttf",
            },
        )
        for path in font_paths:
            font_status, payload = request(f"{self.origin}{path}")
            self.assertEqual(font_status, 200, path)
            self.assertTrue(payload)

    def test_serves_bundled_fonts_with_a_safe_mime_type(self) -> None:
        with urllib.request.urlopen(
            f"{self.origin}/assets/fonts/Inter-Variable.ttf", timeout=10
        ) as response:
            self.assertEqual(response.headers["Content-Type"], "font/ttf")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_sets_the_expected_security_headers(self) -> None:
        req = urllib.request.Request(self.url)
        with urllib.request.urlopen(req, timeout=10) as response:
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn("font-src 'self'", response.headers["Content-Security-Policy"])

    def test_serves_an_authorized_manifest_font_with_the_right_mime_type(self) -> None:
        with urllib.request.urlopen(self.api("/api/font/sans"), timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "font/woff2")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.read(), b"test font bytes")

    def test_serves_distinct_display_and_body_font_roles(self) -> None:
        with urllib.request.urlopen(self.api("/api/font/display"), timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "font/ttf")
            self.assertEqual(response.read(), b"display font bytes")
        with urllib.request.urlopen(self.api("/api/font/body"), timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "font/woff2")
            self.assertEqual(response.read(), b"test font bytes")

    def test_serves_the_resolved_italic_font_role(self) -> None:
        italic_path = self.workdir / "body-italic.ttf"
        italic_path.write_bytes(b"italic font bytes")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "body_italic": {
                    "family": "Review Body Italic",
                    "file": "body-italic.ttf",
                }
            }
        }
        write_json(self.manifest_path, manifest)
        with urllib.request.urlopen(self.api("/api/font/italic"), timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "font/ttf")
            self.assertEqual(response.read(), b"italic font bytes")

    def test_rejects_a_wrong_token_for_a_font(self) -> None:
        self.assertEqual(request(f"{self.origin}/api/font/sans?token=sbagliato")[0], 403)

    def test_serves_only_an_authorized_manifest_cover_image(self) -> None:
        with urllib.request.urlopen(self.api("/api/cover-image"), timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.read(), b"test image bytes")
        self.assertEqual(
            request(f"{self.origin}/api/cover-image?token=sbagliato")[0], 403
        )

    def test_serves_only_an_authorized_manifest_logo(self) -> None:
        with urllib.request.urlopen(self.api("/api/logo/on-light"), timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.read(), b"test logo bytes")
        self.assertEqual(request(self.api("/api/logo/on-dark"))[0], 404)
        self.assertEqual(request(f"{self.origin}/api/logo/on-light?token=sbagliato")[0], 403)

    def test_serves_a_png_preview_but_never_the_declared_svg_master(self) -> None:
        (self.workdir / "logo.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
        manifest = base_manifest()
        manifest["brand"] = {"logos": {"on_light": "logo.svg"}}
        write_json(self.manifest_path, manifest)
        status, session = json_request(self.api("/api/session"))
        self.assertEqual(status, 200)
        self.assertEqual(session["brand"]["logos"]["on_light"]["source"], "sibling_png")
        self.assertEqual(session["brand"]["logos"]["on_light"]["master_format"], "svg")
        with urllib.request.urlopen(self.api("/api/logo/on-light"), timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.read(), b"test logo bytes")

    def test_reports_a_missing_font_without_falling_back_to_a_path(self) -> None:
        self.assertEqual(request(self.api("/api/font/serif"))[0], 404)

    def test_rejects_an_unknown_route(self) -> None:
        self.assertEqual(request(self.api("/api/altro"))[0], 404)

    def test_rejects_a_non_json_content_type(self) -> None:
        status, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)
        self.assertIn("application/json", payload["error"])

    def test_accepts_a_batch_and_writes_the_session_files(self) -> None:
        status, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["event"], "feedback")
        feedback = json.loads((self.session_dir / "feedback.json").read_text(encoding="utf-8"))
        self.assertEqual(feedback["feedback_id"], payload["feedback_id"])
        state = json.loads((self.session_dir / "session-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["last_feedback_id"], payload["feedback_id"])
        self.assertEqual(state["last_action"], "feedback")
        status, durable = json_request(self.api("/api/status"))
        self.assertEqual(status, 200, durable)
        self.assertTrue(durable["feedback_pending"])
        self.assertEqual(durable["last_action"], "feedback")

    def test_accepts_logo_mode_and_emphasis_in_a_batch(self) -> None:
        payload = json.loads(self.batch().decode("utf-8"))
        payload["logo_mode"] = "hidden"
        payload["slides"][1].update(
            {
                "summary_bold": ["Prima"],
                "summary_italic": ["frase."],
                "summary_serif": [],
                "summary_accent": [],
                "summary_underline": [],
            }
        )
        status, response = json_request(
            self.api("/api/submit"),
            method="POST",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, response)
        feedback = json.loads((self.session_dir / "feedback.json").read_text(encoding="utf-8"))
        self.assertEqual(feedback["logo_mode"], "hidden")
        self.assertEqual(feedback["slides"][1]["summary_italic"], ["frase."])
        self.assertEqual(feedback["slides"][1]["summary_underline"], [])

    def test_comment_only_batch_keeps_sparse_manifest_defaults_implicit(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        emphasis_suffixes = ("_bold", "_italic", "_serif", "_accent", "_underline")
        for container in (manifest, *manifest["items"], manifest["outro"]):
            for key in list(container):
                if key.endswith(emphasis_suffixes):
                    del container[key]
        manifest["proof"]["approved"] = True
        write_json(self.manifest_path, manifest)

        payload = json.loads(self.batch().decode("utf-8"))
        payload["slides"][-1]["summary"] = "Corpo della chiusura."
        payload["comments"] = [
            {
                "id": "commento-brand",
                "kind": "brand",
                "slide_id": "",
                "feedback": "Solo un commento.",
            }
        ]
        status, submitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, submitted)

        applied = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(self.manifest_path),
                str(self.session_dir / "feedback.json"),
                "--session-dir",
                str(self.session_dir),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        result = json.loads(applied.stdout)
        written = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["manifest_revision"], 1)
        self.assertFalse(result["stale_transcript"])
        self.assertNotIn("logo_mode", written)
        self.assertEqual(
            [
                key
                for container in (written, *written["items"], written["outro"])
                for key in container
                if key.endswith(emphasis_suffixes)
            ],
            [],
        )
        self.assertEqual(list((self.session_dir / "backups").glob("*.json")), [])
        self.assertEqual(written["review"]["comments_pending"], 1)

    def test_reports_the_revision_in_the_status(self) -> None:
        status, payload = json_request(self.api("/api/status"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["manifest_revision"], 1)
        self.assertFalse(payload["feedback_pending"])
        self.assertIsNone(payload["last_action"])

    def test_session_exposes_the_three_visual_proof_options(self) -> None:
        status, payload = json_request(self.api("/api/session"))
        self.assertEqual(status, 200)
        proofs = payload["visual_proofs"]
        self.assertEqual(len(proofs["options"]), 3)
        self.assertEqual(proofs["selected_style_system"], "editorial-frame")
        self.assertEqual(proofs["identity"]["brand"], payload["brand"])
        self.assertEqual(proofs["identity"]["typography"], payload["typography"])

    def test_refuses_a_second_batch_until_the_first_is_applied(self) -> None:
        first, _ = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(first, 200)
        second, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(second, 409)
        self.assertIn("attende", payload["error"])

    def test_only_one_of_two_concurrent_batches_is_accepted(self) -> None:
        results: list[int] = []
        lock = threading.Lock()

        def submit() -> None:
            status, _ = json_request(
                self.api("/api/submit"),
                method="POST",
                body=self.batch(),
                headers={"Content-Type": "application/json"},
            )
            with lock:
                results.append(status)

        threads = [threading.Thread(target=submit) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual(len(results), 6)
        self.assertEqual(results.count(200), 1, results)
        self.assertEqual(results.count(409), 5, results)

    def test_refuses_a_second_server_for_the_same_session(self) -> None:
        duplicate = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "review_server.py"),
                str(self.manifest_path),
                "--session-dir",
                str(self.session_dir),
                "--port",
                "0",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(duplicate.returncode, 2, duplicate.stdout)
        self.assertIn("già in uso", json.loads(duplicate.stderr)["error"])

    def test_reemits_a_pending_batch_after_restart(self) -> None:
        status, submitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, submitted)
        self.stop()

        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPTS / "review_server.py"),
                str(self.manifest_path),
                "--session-dir",
                str(self.session_dir),
                "--port",
                "0",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = json.loads(self.process.stdout.readline())
        replayed = json.loads(self.process.stdout.readline())
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(replayed["event"], "feedback")
        self.assertEqual(replayed["feedback_id"], submitted["feedback_id"])


if __name__ == "__main__":
    unittest.main()

"""Test di integrazione sul server locale: autorizzazione, host e concorrenza."""

from __future__ import annotations

import http.client
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from support import SCRIPTS, base_manifest, set_workflow_state, slide, write_json


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


def request_without_content_type(url: str, body: bytes) -> tuple[int, dict]:
    parsed = urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    try:
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        connection.request("POST", path, body=body, headers={"Content-Length": str(len(body))})
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


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

    def restart(self) -> dict:
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
        ready_line = self.process.stdout.readline()
        ready = json.loads(ready_line)
        parsed = urlparse(ready["url"])
        self.url = ready["url"]
        self.origin = f"http://127.0.0.1:{parsed.port}"
        self.token = parse_qs(parsed.query)["token"][0]
        return ready

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

    def approved_snapshot_batch(self, workflow_state: str) -> bytes:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        set_workflow_state(manifest, workflow_state)
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        write_json(self.manifest_path, manifest)
        status, model = json_request(self.api("/api/session"))
        self.assertEqual(status, 200, model)
        payload = {
                "action": "approve",
                "base_revision": model["revision"],
                "base_workflow_state": model["workflow_state"],
                "render_fingerprint": model["render_fingerprint"],
                "slides": model["slides"],
                "comments": [],
                "overall_note": "",
            }
        if model["approval_checkpoint"] == "visual_proof":
            payload.update(
                {
                    "proof_slide_ids": model["proof"]["required_slide_ids"],
                    "style_system_verified": True,
                    "proof_browser": {"engine": "chromium", "major": 140},
                }
            )
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

    def test_only_one_live_server_can_own_a_manifest_across_session_dirs(self) -> None:
        second_session = self.workdir / "second-session"
        command = [
            sys.executable,
            str(SCRIPTS / "review_server.py"),
            str(self.manifest_path),
            "--session-dir",
            str(second_session),
            "--port",
            "0",
        ]
        blocked = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stdout)
        self.assertIn("già servito", json.loads(blocked.stderr)["error"])

        self.stop()
        replacement = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready = json.loads(replacement.stdout.readline())
            self.assertEqual(ready["manifest"], str(self.manifest_path))
        finally:
            replacement.terminate()
            replacement.wait(timeout=10)
            replacement.stdout.close()
            replacement.stderr.close()

    def test_serves_the_static_assets(self) -> None:
        for path in (
            "/assets/styles.css",
            "/assets/app.js",
            "/assets/vincos-lockup-white.svg",
            "/styles.css",
            "/app.js",
        ):
            status, payload = request(f"{self.origin}{path}")
            self.assertEqual(status, 200, path)
            self.assertTrue(payload)

    def test_static_assets_support_conditional_get_without_stale_caching(self) -> None:
        url = f"{self.origin}/assets/app.js"
        with urllib.request.urlopen(url, timeout=10) as response:
            etag = response.headers["ETag"]
            self.assertTrue(etag.startswith('"sha256-'))
            self.assertEqual(response.headers["Cache-Control"], "private, no-cache")
        conditional = urllib.request.Request(url, headers={"If-None-Match": etag})
        try:
            urllib.request.urlopen(conditional, timeout=10)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 304)
            self.assertEqual(error.headers["ETag"], etag)
            self.assertEqual(error.read(), b"")
        else:
            self.fail("Il conditional GET doveva restituire 304")

    def test_serves_every_font_declared_by_the_editor_stylesheet(self) -> None:
        status, stylesheet = request(f"{self.origin}/assets/styles.css")
        self.assertEqual(status, 200)
        font_paths = {
            match.decode("utf-8")
            for match in re.findall(rb'url\("(/assets/fonts/[^\"]+)"\)', stylesheet)
        }
        self.assertEqual(
            font_paths,
            set(),
        )
        for path in font_paths:
            font_status, payload = request(f"{self.origin}{path}")
            self.assertEqual(font_status, 200, path)
            self.assertTrue(payload)

    def test_does_not_serve_removed_bundled_fonts(self) -> None:
        self.assertEqual(
            request(f"{self.origin}/assets/fonts/Inter-Variable.ttf")[0],
            404,
        )

    def test_sets_the_expected_security_headers(self) -> None:
        req = urllib.request.Request(self.url)
        with urllib.request.urlopen(req, timeout=10) as response:
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(
                response.headers["Cross-Origin-Resource-Policy"], "same-origin"
            )
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

    def test_requires_content_type_and_accepts_json_with_charset(self) -> None:
        status, payload = request_without_content_type(
            self.api("/api/submit"), self.batch()
        )
        self.assertEqual(status, 415)
        self.assertIn("application/json", payload["error"])

        status, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(status, 200, payload)

    def test_rejects_non_finite_json_with_a_json_error(self) -> None:
        body = self.batch().replace(b'"overall_note": ""', b'"overall_note": NaN')
        status, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 422)
        self.assertIn("Costante JSON", payload["error"])

    def test_rejects_unhashable_json_fields_without_dropping_the_connection(self) -> None:
        cases = []
        action = json.loads(self.batch())
        action["action"] = ["feedback"]
        cases.append(action)

        slide_id = json.loads(self.batch())
        slide_id["slides"][1]["id"] = ["item-1"]
        cases.append(slide_id)

        comment_kind = json.loads(self.batch())
        comment_kind["comments"] = [
            {"kind": ["slide"], "slide_id": "item-1", "feedback": "Nota"}
        ]
        cases.append(comment_kind)

        for index, value in enumerate(cases):
            status, payload = json_request(
                self.api("/api/submit"),
                method="POST",
                body=json.dumps(value).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.subTest(index=index):
                self.assertEqual(status, 422)
                self.assertIsInstance(payload.get("error"), str)
                self.assertTrue(payload["error"])
                self.assertIsNone(self.process.poll())

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
        archive_path = Path(payload["archive_path"])
        self.assertEqual(
            json.loads(archive_path.read_text(encoding="utf-8")), feedback
        )
        state = json.loads((self.session_dir / "session-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["last_feedback_id"], payload["feedback_id"])
        self.assertEqual(state["last_feedback_path"], str(archive_path))
        self.assertEqual(state["last_action"], "feedback")
        status, durable = json_request(self.api("/api/status"))
        self.assertEqual(status, 200, durable)
        self.assertTrue(durable["feedback_pending"])
        self.assertEqual(durable["last_action"], "feedback")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.session_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(archive_path.parent.stat().st_mode), 0o700)
            for private_file in (
                self.session_dir / "session-state.json",
                self.session_dir / "feedback.json",
                archive_path,
            ):
                self.assertEqual(stat.S_IMODE(private_file.stat().st_mode), 0o600)

    def test_client_uuid_retry_is_idempotent_and_conflicting_reuse_is_rejected(self) -> None:
        feedback_id = str(uuid.uuid4())
        body = self.batch(
            feedback_id=feedback_id,
            overall_note="Nota da conservare",
            comments=[
                {
                    "id": "comment-1",
                    "kind": "brand",
                    "slide_id": "",
                    "feedback": "Più contrasto",
                }
            ],
        )
        first_status, first = json_request(
            self.api("/api/submit"),
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        second_status, second = json_request(
            self.api("/api/submit"),
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first, second)
        archives = list((self.session_dir / "feedback-batches").glob("*.json"))
        self.assertEqual(
            [path.resolve() for path in archives],
            [Path(first["archive_path"]).resolve()],
        )
        persisted = json.loads(archives[0].read_text(encoding="utf-8"))
        self.assertEqual(persisted["overall_note"], "Nota da conservare")
        self.assertEqual(persisted["comments"][0]["feedback"], "Più contrasto")

        conflicting = json.loads(body.decode("utf-8"))
        conflicting["overall_note"] = "Contenuto differente"
        conflict_status, conflict = json_request(
            self.api("/api/submit"),
            method="POST",
            body=json.dumps(conflicting).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(conflict_status, 409)
        self.assertIn("già usato", conflict["error"])
        self.assertEqual(json.loads(archives[0].read_text(encoding="utf-8")), persisted)

    def test_rejects_a_noncanonical_feedback_id(self) -> None:
        status, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(feedback_id="../feedback.json"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 422)
        self.assertIn("UUID", payload["error"])

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_rejects_a_symlinked_archive_directory_without_touching_outside(self) -> None:
        outside = self.workdir / "outside-archive"
        outside.mkdir(mode=0o755)
        outside.chmod(0o755)
        before_mode = stat.S_IMODE(outside.stat().st_mode)
        archive_dir = self.session_dir / "feedback-batches"
        archive_dir.symlink_to(outside, target_is_directory=True)

        status, payload = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(feedback_id=str(uuid.uuid4())),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 422)
        self.assertIn("collegamento simbolico", payload["error"])
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), before_mode)

    def test_same_uuid_can_be_retried_after_the_batch_was_applied(self) -> None:
        feedback_id = str(uuid.uuid4())
        body = self.batch(feedback_id=feedback_id)
        status, first = json_request(
            self.api("/api/submit"),
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, first)
        applied = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(self.manifest_path),
                first["archive_path"],
                "--session-dir",
                str(self.session_dir),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        status, replay = json_request(
            self.api("/api/submit"),
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["feedback_id"], feedback_id)
        status, durable = json_request(self.api("/api/status"))
        self.assertEqual(status, 200, durable)
        self.assertFalse(durable["feedback_pending"])
        self.assertEqual(durable["applied_feedback_id"], feedback_id)

    def test_profile_text_approval_never_approves_the_visual_proof(self) -> None:
        status, submitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.approved_snapshot_batch("bozza"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, submitted)
        batch = json.loads(Path(submitted["archive_path"]).read_text(encoding="utf-8"))
        self.assertEqual(batch["approval_stage"], "profile_text")
        applied = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(self.manifest_path),
                submitted["archive_path"],
                "--session-dir",
                str(self.session_dir),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(manifest["proof"]["approved"])
        self.assertNotIn("render_fingerprint", manifest["proof"])

    def test_visual_approval_binds_proof_and_asset_mutation_invalidates_it(self) -> None:
        status, submitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.approved_snapshot_batch("testi_approvati"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, submitted)
        batch = json.loads(Path(submitted["archive_path"]).read_text(encoding="utf-8"))
        self.assertEqual(batch["approval_stage"], "visual_proof")
        approved_model = None
        for _ in range(40):
            status, candidate = json_request(self.api("/api/session"))
            if (
                status == 200
                and candidate["applied_feedback_id"] == submitted["feedback_id"]
                and candidate["workflow_state"] == "prova_visuale_approvata"
                and candidate["proof_approved"]
            ):
                approved_model = candidate
                break
            self.assertIn(status, (200, 409), candidate)
            time.sleep(0.05)
        self.assertIsNotNone(approved_model)
        assert approved_model is not None
        self.assertEqual(status, 200, approved_model)
        self.assertTrue(approved_model["proof_approved"])
        approved_fingerprint = approved_model["render_fingerprint"]

        approved_fingerprint = approved_model["render_fingerprint"]
        for workflow_state in (
            "prova_visuale_approvata",
            "rendering",
            "qa",
            "consegnato",
        ):
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            set_workflow_state(manifest, workflow_state)
            write_json(self.manifest_path, manifest)
            status, later_model = json_request(self.api("/api/session"))
            self.assertEqual(status, 200, later_model)
            self.assertEqual(later_model["approval_checkpoint"], "visual_proof")
            self.assertEqual(later_model["render_fingerprint"], approved_fingerprint)
            self.assertTrue(later_model["proof_approved"])

        self.cover_path.write_bytes(b"mutated cover bytes")
        status, stale_model = json_request(self.api("/api/session"))
        self.assertEqual(status, 200, stale_model)
        self.assertFalse(stale_model["proof_approved"])
        self.assertNotEqual(
            stale_model["render_fingerprint"], approved_model["render_fingerprint"]
        )

        status, resubmitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.approved_snapshot_batch("prova_visuale_approvata"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, resubmitted)
        rebound_batch = json.loads(
            Path(resubmitted["archive_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(rebound_batch["approval_stage"], "visual_proof")
        reapplied = None
        for _ in range(40):
            reapplied = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "apply_review.py"),
                    str(self.manifest_path),
                    resubmitted["archive_path"],
                    "--session-dir",
                    str(self.session_dir),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if reapplied.returncode == 0:
                break
            time.sleep(0.05)
        self.assertIsNotNone(reapplied)
        assert reapplied is not None
        self.assertEqual(reapplied.returncode, 0, reapplied.stderr)
        rebound_model = None
        for _ in range(40):
            status, candidate = json_request(self.api("/api/session"))
            if status == 200 and candidate["proof_approved"]:
                rebound_model = candidate
                break
            self.assertIn(status, (200, 409), candidate)
            time.sleep(0.05)
        self.assertIsNotNone(rebound_model)
        assert rebound_model is not None
        self.assertTrue(rebound_model["proof_approved"])

    def test_visual_apply_rejects_assets_mutated_after_submission(self) -> None:
        status, submitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.approved_snapshot_batch("testi_approvati"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, submitted)
        self.cover_path.write_bytes(b"changed between submit and apply")
        applied = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(self.manifest_path),
                submitted["archive_path"],
                "--session-dir",
                str(self.session_dir),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(applied.returncode, 2)
        self.assertIn("cambiati dopo l'approvazione", json.loads(applied.stderr)["error"])
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(manifest["proof"]["approved"])

    def test_visual_approve_and_edit_requires_feedback_before_reapproval(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        set_workflow_state(manifest, "testi_approvati")
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        write_json(self.manifest_path, manifest)
        status, initial = json_request(self.api("/api/session"))
        self.assertEqual(status, 200, initial)
        manifest["proof"].update(
            {
                "approved": True,
                "render_fingerprint": initial["render_fingerprint"],
                "style_system_verified": True,
                "browser": {"engine": "chromium", "major": 140},
            }
        )
        write_json(self.manifest_path, manifest)
        status, approved = json_request(self.api("/api/session"))
        self.assertTrue(approved["proof_approved"])
        slides = approved["slides"]
        slides[1]["summary"] = "Testo visuale approvato e aggiornato."
        slides[1]["summary_serif"] = []
        status, rejected = json_request(
            self.api("/api/submit"),
            method="POST",
            body=json.dumps(
                {
                    "action": "approve",
                    "base_revision": approved["revision"],
                    "base_workflow_state": approved["workflow_state"],
                    "render_fingerprint": approved["render_fingerprint"],
                    "slides": slides,
                    "comments": [],
                    "overall_note": "",
                    "proof_slide_ids": approved["proof"]["required_slide_ids"],
                    "style_system_verified": True,
                    "proof_browser": {"engine": "chromium", "major": 140},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 422, rejected)
        self.assertIn("modifiche editoriali", rejected["error"])
        self.assertFalse((self.session_dir / "feedback.json").exists())

    def test_stale_profile_approval_cannot_cross_the_visual_checkpoint(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        write_json(self.manifest_path, manifest)
        status, profile_model = json_request(self.api("/api/session"))
        self.assertEqual(status, 200, profile_model)
        self.assertEqual(profile_model["approval_checkpoint"], "profile_text")
        stale_batch = json.dumps(
            {
                "action": "approve",
                "base_revision": profile_model["revision"],
                "base_workflow_state": profile_model["workflow_state"],
                "render_fingerprint": profile_model["render_fingerprint"],
                "slides": profile_model["slides"],
                "comments": [],
                "overall_note": "",
            }
        ).encode("utf-8")

        set_workflow_state(manifest, "testi_approvati")
        write_json(self.manifest_path, manifest)
        status, rejected = json_request(
            self.api("/api/submit"),
            method="POST",
            body=stale_batch,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 422, rejected)
        self.assertIn("base_workflow_state", rejected["error"])
        written = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertFalse(written["proof"]["approved"])
        self.assertFalse((self.session_dir / "feedback.json").exists())
        self.assertEqual(
            list((self.session_dir / "feedback-batches").glob("*.json")), []
        )

        status, durable = json_request(self.api("/api/status"))
        self.assertEqual(status, 200, durable)
        self.assertEqual(durable["manifest_revision"], profile_model["revision"])
        self.assertEqual(durable["workflow_state"], "testi_approvati")
        self.assertEqual(durable["approval_checkpoint"], "visual_proof")

    def test_new_batch_preserves_the_previous_append_only_history(self) -> None:
        first_id = str(uuid.uuid4())
        first_body = self.batch(
            feedback_id=first_id,
            overall_note="Prima nota persistente",
        )
        status, first = json_request(
            self.api("/api/submit"),
            method="POST",
            body=first_body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, first)
        first_archive = Path(first["archive_path"])
        first_bytes = first_archive.read_bytes()
        applied = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "apply_review.py"),
                str(self.manifest_path),
                str(first_archive),
                "--session-dir",
                str(self.session_dir),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)

        second_id = str(uuid.uuid4())
        status, second = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(
                feedback_id=second_id,
                base_revision=2,
                overall_note="Seconda nota persistente",
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, second)
        archives = list((self.session_dir / "feedback-batches").glob("*.json"))
        self.assertEqual(len(archives), 2)
        self.assertEqual(first_archive.read_bytes(), first_bytes)
        alias = json.loads(
            (self.session_dir / "feedback.json").read_text(encoding="utf-8")
        )
        self.assertEqual(alias["feedback_id"], second_id)
        self.assertEqual(
            json.loads(Path(second["archive_path"]).read_text(encoding="utf-8")),
            alias,
        )

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
        self.assertEqual(payload["workflow_state"], "bozza")
        self.assertEqual(payload["approval_checkpoint"], "profile_text")
        self.assertFalse(payload["feedback_pending"])
        self.assertIsNone(payload["last_action"])

    def test_session_and_status_report_filesystem_failures_as_json_500(self) -> None:
        self.manifest_path.unlink()
        self.manifest_path.mkdir()
        for route in ("/api/session", "/api/status"):
            with self.subTest(route=route):
                status, payload = json_request(self.api(route))
                self.assertEqual(status, 500, payload)
                self.assertIsInstance(payload.get("error"), str)
                self.assertTrue(payload["error"])

    def test_session_exposes_the_three_visual_proof_options(self) -> None:
        status, payload = json_request(self.api("/api/session"))
        self.assertEqual(status, 200)
        self.assertFalse(payload["feedback_pending"])
        self.assertIsNone(payload["last_feedback_id"])
        self.assertIsNone(payload["applied_feedback_id"])
        proofs = payload["visual_proofs"]
        self.assertEqual(len(proofs["options"]), 3)
        self.assertEqual(proofs["selected_style_system"], "editorial-frame")
        self.assertEqual(proofs["identity"]["brand"], payload["brand"])
        self.assertEqual(proofs["identity"]["typography"], payload["typography"])

    def test_refuses_a_second_batch_until_the_first_is_applied(self) -> None:
        first, accepted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(first, 200)
        session_status, session = json_request(self.api("/api/session"))
        self.assertEqual(session_status, 200, session)
        self.assertTrue(session["feedback_pending"])
        self.assertEqual(session["last_feedback_id"], accepted["feedback_id"])
        self.assertIsNone(session["applied_feedback_id"])
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
        ready = self.restart()
        replayed = json.loads(self.process.stdout.readline())
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(replayed["event"], "feedback")
        self.assertEqual(replayed["feedback_id"], submitted["feedback_id"])

    def test_restart_backfills_legacy_action_archive_and_rotates_an_invalid_token(self) -> None:
        status, submitted = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200, submitted)
        old_token = self.token
        self.stop()
        state_path = self.session_dir / "session-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.pop("last_action")
        state.pop("last_feedback_path")
        state["token"] = ""
        write_json(state_path, state)
        archive_path = Path(submitted["archive_path"])
        archive_path.unlink()

        ready = self.restart()
        replayed = json.loads(self.process.stdout.readline())
        self.assertEqual(ready["status"], "ready")
        self.assertNotEqual(self.token, old_token)
        self.assertGreaterEqual(len(self.token), 32)
        self.assertEqual(replayed["feedback_id"], submitted["feedback_id"])
        recovered = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered["last_action"], "feedback")
        self.assertEqual(recovered["last_feedback_path"], str(archive_path))
        self.assertTrue(archive_path.is_file())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(archive_path.stat().st_mode), 0o600)

    def test_restart_rejects_a_last_action_that_conflicts_with_the_batch(self) -> None:
        status, _ = json_request(
            self.api("/api/submit"),
            method="POST",
            body=self.batch(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.stop()
        state_path = self.session_dir / "session-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["last_action"] = "approve"
        write_json(state_path, state)
        conflicting = subprocess.run(
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
        self.assertEqual(conflicting.returncode, 2, conflicting.stdout)
        self.assertIn("last_action", json.loads(conflicting.stderr)["error"])


if __name__ == "__main__":
    unittest.main()

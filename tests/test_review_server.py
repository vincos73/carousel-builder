"""Test di review_server.py: modello editoriale e validazione dei batch."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from support import (
    base_manifest,
    legacy_manifest,
    set_workflow_state,
    slide,
    sync_derived_contract,
    write_json,
)

SPEC = importlib.util.spec_from_file_location(
    "review_server", Path(__file__).resolve().parent.parent / "scripts" / "review_server.py"
)
review_server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(review_server)


class ReturnUrlTest(unittest.TestCase):
    def test_accepts_only_canonical_codex_thread_urls(self) -> None:
        thread_id = "01a01e64-3e6e-7b71-950d-c425e032e34e"
        return_url = f"codex://threads/{thread_id}"
        self.assertEqual(review_server.return_url_for_thread(thread_id), return_url)
        self.assertEqual(review_server.valid_return_url(return_url), return_url)
        for invalid in (
            "",
            "not-a-thread",
            f"https://example.test/{thread_id}",
            f"codex://threads/{thread_id}/extra",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    review_server.return_url_for_thread(invalid)
                self.assertIsNone(review_server.valid_return_url(invalid))

    def test_resolves_codex_desktop_handoff_from_environment(self) -> None:
        thread_id = "01a01e64-3e6e-7b71-950d-c425e032e34e"
        environ = {
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "Codex Desktop",
            "CODEX_THREAD_ID": thread_id,
        }
        self.assertEqual(
            review_server.resolve_return_url(None, environ=environ),
            f"codex://threads/{thread_id}",
        )

    def test_codex_desktop_handoff_fails_closed_without_a_thread(self) -> None:
        with self.assertRaisesRegex(ValueError, "Codex Desktop richiede"):
            review_server.resolve_return_url(
                None,
                environ={"CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "Codex Desktop"},
            )

    def test_non_desktop_handoff_is_optional(self) -> None:
        self.assertIsNone(review_server.resolve_return_url(None, environ={}))


class ManifestModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def model(self, manifest: dict | None = None) -> dict:
        value = manifest if manifest is not None else base_manifest()
        if value.get("schema_version") == "1.4":
            sync_derived_contract(value)
        path = self.workdir / "manifest.json"
        path.write_text(
            json.dumps(value),
            encoding="utf-8",
        )
        return review_server.manifest_model(path)

    def test_builds_cover_items_and_outro(self) -> None:
        model = self.model()
        self.assertEqual(
            [entry["id"] for entry in model["slides"]],
            ["cover", "item-1", "item-2", "outro"],
        )
        self.assertFalse(model["slides"][0]["deletable"])
        self.assertTrue(model["slides"][1]["deletable"])
        self.assertFalse(model["slides"][-1]["deletable"])

    def test_accepts_supported_legacy_versions_and_rejects_future_schema(self) -> None:
        for version in (None, "1.0", "1.1", "1.2", "1.3"):
            with self.subTest(version=version):
                model = self.model(legacy_manifest(version))
                self.assertTrue(model["legacy_manifest"])
                self.assertFalse(model["proof_approved"])
        manifest = base_manifest()
        manifest["schema_version"] = "99.0"
        with self.assertRaisesRegex(ValueError, "non supportata"):
            self.model(manifest)

    def test_current_schema_rejects_legacy_workflow_states_only(self) -> None:
        for workflow_state in ("approved", "published", "draft"):
            current = base_manifest()
            current["workflow_state"] = workflow_state
            with self.subTest(schema="1.4", workflow_state=workflow_state):
                with self.assertRaisesRegex(ValueError, "workflow_state"):
                    self.model(current)

            for version in (None, "1.0", "1.1", "1.2", "1.3"):
                legacy = legacy_manifest(version)
                legacy["workflow_state"] = workflow_state
                with self.subTest(schema=version, workflow_state=workflow_state):
                    self.assertEqual(
                        self.model(legacy)["workflow_state"], workflow_state
                    )

    def test_current_schema_requires_a_complete_ledger_from_draft(self) -> None:
        for workflow_state in (
            "testi_approvati",
            "prova_visuale_approvata",
            "rendering",
            "qa",
            "consegnato",
        ):
            missing = base_manifest()
            missing["workflow_state"] = workflow_state
            with self.subTest(state=workflow_state, case="missing"), self.assertRaisesRegex(
                ValueError, "intera catena"
            ):
                review_server.validate_manifest_contract(missing)

            truncated = base_manifest()
            set_workflow_state(truncated, workflow_state)
            truncated["workflow_receipts"] = truncated["workflow_receipts"][1:]
            with self.subTest(state=workflow_state, case="truncated"), self.assertRaisesRegex(
                ValueError, "intera catena"
            ):
                review_server.validate_manifest_contract(truncated)

    def test_legacy_missing_item_id_gets_stable_fallback_but_current_rejects(self) -> None:
        for version in (None, "1.0", "1.1", "1.2", "1.3"):
            manifest = legacy_manifest(version)
            manifest["items"][0].pop("id")
            manifest["proof"]["slide_ids"] = ["cover", "item-1", "outro"]
            manifest["accessibility"]["reading_order"] = [
                "cover", "item-1", "item-2", "outro"
            ]
            with self.subTest(version=version):
                self.assertEqual(self.model(manifest)["slides"][1]["id"], "item-1")
        manifest = base_manifest()
        manifest["items"][0].pop("id")
        with self.assertRaisesRegex(ValueError, r"items\[\]\.id"):
            review_server.validate_manifest_contract(manifest)

    def test_rejects_reserved_unsafe_or_overlong_item_ids(self) -> None:
        for item_id in ("cover", "outro", "../escape", "x" * 65):
            manifest = base_manifest()
            manifest["items"][0]["id"] = item_id
            with self.subTest(item_id=item_id), self.assertRaises(ValueError):
                self.model(manifest)

    def test_rejects_more_than_max_slides(self) -> None:
        manifest = base_manifest()
        manifest["items"] = [
            {"id": f"item-{index}", "title": "", "summary": "Testo"}
            for index in range(review_server.MAX_SLIDES)
        ]
        with self.assertRaisesRegex(ValueError, "massimo 50"):
            self.model(manifest)

    def test_current_schema_rejects_empty_or_semantically_invalid_slides(self) -> None:
        cases = []
        empty_cover = base_manifest()
        empty_cover["cover_title"] = " "
        cases.append((empty_cover, "cover_title"))
        empty_item = base_manifest()
        empty_item["items"][0].update({"title": "", "summary": ""})
        cases.append((empty_item, "non può essere vuota"))
        narrative_title = base_manifest()
        narrative_title["items"][0]["title"] = "Titolo vietato"
        cases.append((narrative_title, "modalità narrative"))
        empty_outro = base_manifest()
        empty_outro["outro"].update({"title": "", "body": ""})
        cases.append((empty_outro, "chiusura"))
        for manifest, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.model(manifest)

    def test_manifest_enum_fields_reject_unhashable_json_values_cleanly(self) -> None:
        fields = (
            ("source_type", ["article"]),
            ("sequence_mode", {"value": "narrative"}),
            ("workflow_state", ["bozza"]),
        )
        for field, value in fields:
            manifest = base_manifest()
            manifest[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                review_server.validate_manifest_contract(manifest)

        manifest = base_manifest()
        manifest["production"]["mode"] = ["renderer"]
        with self.assertRaisesRegex(ValueError, "production.mode"):
            review_server.validate_manifest_contract(manifest)

    def test_current_schema_rejects_malformed_optional_contract_fields(self) -> None:
        cases = (
            ("outro.enabled", lambda manifest: manifest["outro"].update(enabled="yes")),
            ("visual_style_system", lambda manifest: manifest.update(visual_style_system=["editorial-frame"])),
            ("logo_mode", lambda manifest: manifest.update(logo_mode=["auto"])),
            ("cover_mode", lambda manifest: manifest.update(cover_mode=["generated"])),
            ("brand", lambda manifest: manifest.update(brand=[])),
            ("typography", lambda manifest: manifest.update(typography=[])),
            ("expected_outputs", lambda manifest: manifest["production"].update(expected_outputs=["pdf", "pdf"])),
            ("proof.approved", lambda manifest: manifest["proof"].update(approved=1)),
            ("proof.render_fingerprint", lambda manifest: manifest["proof"].update(render_fingerprint=["bad"])),
        )
        for field, mutate in cases:
            manifest = base_manifest()
            mutate(manifest)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                review_server.validate_manifest_contract(manifest)

        manifest = base_manifest()
        manifest["workflow_receipts"] = [{"from": "bozza", "to": "qa"}]
        with self.assertRaisesRegex(ValueError, "workflow_receipts"):
            review_server.validate_manifest_contract(manifest)

    def test_normalizes_and_exposes_expected_outputs(self) -> None:
        manifest = base_manifest()
        manifest["production"]["expected_outputs"] = [
            "pdf",
            "png",
            "contact-sheet",
        ]
        contract = review_server.validate_manifest_contract(manifest)
        self.assertEqual(
            contract["production"]["expected_outputs"],
            ["pdf", "png", "contact_sheet"],
        )
        self.assertEqual(
            self.model(manifest)["production"]["expected_outputs"],
            ["pdf", "png", "contact_sheet"],
        )

    def test_current_renderer_requires_supported_unique_expected_outputs(self) -> None:
        cases = (
            ([], "includere almeno pdf"),
            (["png"], "includere almeno pdf"),
            (["pdf", "svg"], "non è un output supportato"),
            (["pdf", "contact-sheet", "contact_sheet"], "duplicati"),
        )
        for outputs, message in cases:
            manifest = base_manifest()
            manifest["production"]["expected_outputs"] = outputs
            with self.subTest(outputs=outputs), self.assertRaisesRegex(
                ValueError, message
            ):
                review_server.validate_manifest_contract(manifest)

    def test_expected_outputs_are_bound_to_the_render_fingerprint(self) -> None:
        manifest = base_manifest()
        baseline = self.model(copy.deepcopy(manifest))["render_fingerprint"]
        manifest["production"]["expected_outputs"].append("contact_sheet")
        self.assertNotEqual(self.model(manifest)["render_fingerprint"], baseline)

    def test_current_schema_requires_explicit_480px_proof_width(self) -> None:
        for value in (None, 479, "480"):
            manifest = base_manifest()
            if value is None:
                manifest["format"].pop("preview_width")
            else:
                manifest["format"]["preview_width"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "preview_width"):
                self.model(manifest)

    def test_current_schema_requires_the_exact_render_dimensions(self) -> None:
        expected = {
            "ratio": "4:5",
            "master_width": 1080,
            "master_height": 1350,
            "width": 1440,
            "height": 1800,
            "preview_width": 480,
            "preview_height": 600,
        }
        for field, value in expected.items():
            manifest = base_manifest()
            manifest["format"][field] = value + 1 if isinstance(value, int) else "1:1"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"format.{field}"):
                self.model(manifest)

    def test_current_schema_requires_canonical_proof_and_supported_producer(self) -> None:
        manifest = base_manifest()
        manifest["proof"]["slide_ids"] = ["cover", "item-1", "outro"]
        with self.assertRaisesRegex(ValueError, "card più densa"):
            review_server.validate_manifest_contract(manifest)
        manifest = base_manifest()
        manifest["production"]["supported_style_systems"] = ["corporate-modular"]
        model = self.model(manifest)
        self.assertTrue(model["production"]["selected_style_supported"])
        self.assertEqual(
            model["production"]["supported_style_systems"],
            ["corporate-modular", "editorial-frame", "editorial-halftone"],
        )
        manifest = base_manifest()
        manifest["production"].update(
            {"mode": "adapter", "supported_style_systems": ["corporate-modular"]}
        )
        with self.assertRaisesRegex(ValueError, "deve includere"):
            self.model(manifest)
        for mode in ("renderer", "adapter"):
            manifest = base_manifest()
            manifest["production"].update({"mode": mode, "producer": ""})
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "producer"):
                self.model(manifest)

    def test_auto_apply_failure_is_persisted_for_browser_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            session_dir = root / "session"
            session_dir.mkdir()
            feedback_id = str(uuid.uuid4())
            write_json(manifest_path, {"schema_version": "1.4"})
            review_server.atomic_write_json(
                session_dir / "session-state.json",
                {
                    "manifest": str(manifest_path),
                    "last_feedback_id": feedback_id,
                    "applied_feedback_id": None,
                },
            )
            failed = mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {"status": "error", "error": "tema visuale non supportato"}
                ),
                stderr="",
            )
            with mock.patch.object(review_server.subprocess, "run", return_value=failed):
                result = review_server.auto_process_approval(
                    manifest_path=manifest_path,
                    session_dir=session_dir,
                    event={"feedback_id": feedback_id},
                )
            self.assertEqual(result["event"], "approval_processing_error")
            state = review_server.read_private_json(session_dir / "session-state.json")
            self.assertEqual(
                state["approval_processing_error"],
                {
                    "feedback_id": feedback_id,
                    "message": "tema visuale non supportato",
                    "recorded_at": mock.ANY,
                },
            )

    def test_auto_apply_blocked_is_not_reported_as_processed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            session_dir = root / "session"
            session_dir.mkdir()
            feedback_id = str(uuid.uuid4())
            write_json(manifest_path, {"schema_version": "1.4"})
            review_server.atomic_write_json(
                session_dir / "session-state.json",
                {
                    "manifest": str(manifest_path),
                    "last_feedback_id": feedback_id,
                    "applied_feedback_id": feedback_id,
                },
            )
            blocked = mock.Mock(
                returncode=3,
                stdout=json.dumps(
                    {
                        "status": "approval_blocked",
                        "workflow": {"workflow_state": "bozza", "revision": 1},
                    }
                ),
                stderr="",
            )
            with mock.patch.object(review_server.subprocess, "run", return_value=blocked):
                result = review_server.auto_process_approval(
                    manifest_path=manifest_path,
                    session_dir=session_dir,
                    event={"feedback_id": feedback_id},
                )
            self.assertEqual(result["event"], "approval_blocked")
            self.assertIsNone(result["processed_feedback_id"])
            state = review_server.read_private_json(session_dir / "session-state.json")
            self.assertEqual(
                state["approval_processing_status"]["status"], "approval_blocked"
            )
            self.assertNotIn("processed_feedback_id", state)

    def test_auto_apply_does_not_claim_processed_when_processing_commit_is_locked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            session_dir = root / "session"
            session_dir.mkdir()
            feedback_id = str(uuid.uuid4())
            write_json(manifest_path, {"schema_version": "1.4"})
            review_server.atomic_write_json(
                session_dir / "session-state.json",
                {
                    "manifest": str(manifest_path),
                    "last_feedback_id": feedback_id,
                    "applied_feedback_id": feedback_id,
                },
            )
            completed = mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": "advanced",
                        "workflow": {"workflow_state": "testi_approvati", "revision": 1},
                    }
                ),
                stderr="",
            )
            with mock.patch.object(review_server.subprocess, "run", return_value=completed), \
                mock.patch.object(
                    review_server,
                    "set_approval_processing_status",
                    side_effect=review_server.LockUnavailableError("busy"),
                ):
                result = review_server.auto_process_approval(
                    manifest_path=manifest_path,
                    session_dir=session_dir,
                    event={"feedback_id": feedback_id},
                )
            self.assertEqual(result["event"], "approval_processing_error")
            self.assertNotIn("processed_feedback_id", result)

    def test_auto_processing_holds_the_same_lock_as_live_session_reads(self) -> None:
        class RecordingLock:
            active = False

            def __enter__(self):
                self.active = True
                return self

            def __exit__(self, *_args):
                self.active = False

        lock = RecordingLock()

        def assert_locked(**_kwargs):
            self.assertTrue(lock.active)
            return {"event": "approval_processed"}

        with mock.patch.object(
            review_server,
            "auto_process_approval",
            side_effect=assert_locked,
        ) as process:
            result = review_server.auto_process_approval_serialized(
                submit_lock=lock,
                manifest_path=Path("manifest.json"),
                session_dir=Path("session"),
                event={"feedback_id": str(uuid.uuid4())},
            )
        self.assertEqual(result["event"], "approval_processed")
        process.assert_called_once()
        self.assertFalse(lock.active)

    def test_processing_status_rejects_a_changed_feedback_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            session_dir = root / "session"
            session_dir.mkdir()
            write_json(manifest_path, {"schema_version": "1.4"})
            write_json(
                session_dir / "session-state.json",
                {
                    "manifest": str(manifest_path),
                    "last_feedback_id": "new-feedback",
                },
            )
            with self.assertRaisesRegex(ValueError, "stato della sessione è cambiato"):
                review_server.set_approval_processing_status(
                    session_dir=session_dir,
                    manifest_path=manifest_path,
                    feedback_id="old-feedback",
                    status="processed",
                    action="approve",
                )

    def test_processing_status_propagates_lock_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            session_dir = root / "session"
            session_dir.mkdir()
            feedback_id = str(uuid.uuid4())
            write_json(manifest_path, {"schema_version": "1.4"})
            write_json(
                session_dir / "session-state.json",
                {"manifest": str(manifest_path), "last_feedback_id": feedback_id},
            )
            lock = review_server.InterprocessLock(
                session_dir / ".review-transaction.lock"
            )
            lock.acquire()
            self.addCleanup(lock.release)
            with self.assertRaises(review_server.LockUnavailableError):
                review_server.set_approval_processing_status(
                    session_dir=session_dir,
                    manifest_path=manifest_path,
                    feedback_id=feedback_id,
                    status="processed",
                    action="approve",
                )

    def test_renderer_bundle_byte_changes_invalidate_fingerprint(self) -> None:
        manifest = base_manifest()
        baseline = self.model(manifest)["render_fingerprint"]
        original = review_server.sha256_file

        def changed_digest(path: Path) -> str:
            if path.name == "styles.css":
                return "f" * 64
            return original(path)

        with mock.patch.object(review_server, "sha256_file", side_effect=changed_digest):
            self.assertNotEqual(self.model(manifest)["render_fingerprint"], baseline)

    def test_exposes_optional_cover_subtitle(self) -> None:
        manifest = base_manifest()
        manifest["cover_subtitle"] = "Ecco cosa puoi fare"
        cover = self.model(manifest)["slides"][0]
        self.assertEqual(cover["summary"], "Ecco cosa puoi fare")

    def test_exposes_only_a_strict_fingerprint_bound_proof_approval(self) -> None:
        manifest = base_manifest()
        manifest["proof"]["approved"] = True
        unbound = self.model(manifest)
        self.assertFalse(unbound["proof_approved"])
        manifest["proof"]["render_fingerprint"] = unbound["render_fingerprint"]
        self.assertFalse(self.model(manifest)["proof_approved"])
        manifest["proof"].update(
            {
                "style_system_verified": True,
                "browser": {"engine": "chromium", "major": 140},
            }
        )
        self.assertTrue(self.model(manifest)["proof_approved"])
        manifest["proof"]["approved"] = 1
        with self.assertRaisesRegex(ValueError, "proof.approved"):
            self.model(manifest)
        manifest["proof"] = "invalid"
        with self.assertRaisesRegex(ValueError, "proof deve essere"):
            self.model(manifest)

    def test_render_fingerprint_is_stable_across_approval_checkpoints(self) -> None:
        manifest = base_manifest()
        profile = self.model(manifest)
        self.assertEqual(profile["approval_checkpoint"], "profile_text")

        for workflow_state in (
            "draft",
            "in_revisione",
            "in_revisione_editoriale",
            "in_review",
            "feedback",
        ):
            legacy_manifest_value = copy.deepcopy(manifest)
            legacy_manifest_value["schema_version"] = "1.2"
            legacy_manifest_value["workflow_state"] = workflow_state
            legacy_manifest_value.pop("workflow_receipts", None)
            legacy_profile = self.model(legacy_manifest_value)
            self.assertEqual(legacy_profile["approval_checkpoint"], "profile_text")
            self.assertEqual(legacy_profile["render_fingerprint"], profile["render_fingerprint"])

        set_workflow_state(manifest, "testi_approvati")
        visual = self.model(manifest)
        self.assertEqual(visual["approval_checkpoint"], "visual_proof")
        self.assertEqual(visual["render_fingerprint"], profile["render_fingerprint"])
        manifest["proof"].update(
            {"approved": True, "render_fingerprint": visual["render_fingerprint"]}
        )
        manifest["proof"].update(
            {
                "style_system_verified": True,
                "browser": {"engine": "chromium", "major": 140},
            }
        )
        for workflow_state in (
            "prova_visuale_approvata",
            "rendering",
            "qa",
            "consegnato",
        ):
            set_workflow_state(manifest, workflow_state)
            later = self.model(manifest)
            self.assertEqual(later["approval_checkpoint"], "visual_proof")
            self.assertEqual(later["render_fingerprint"], visual["render_fingerprint"])

        for workflow_state in (
            "approvato",
            "approved",
            "pubblicato",
            "published",
        ):
            legacy_manifest_value = copy.deepcopy(manifest)
            legacy_manifest_value["schema_version"] = "1.2"
            legacy_manifest_value["workflow_state"] = workflow_state
            legacy_manifest_value.pop("workflow_receipts", None)
            later = self.model(legacy_manifest_value)
            self.assertEqual(later["approval_checkpoint"], "visual_proof")
            self.assertEqual(later["render_fingerprint"], visual["render_fingerprint"])
            self.assertTrue(later["proof_approved"])

    def test_capability_metadata_does_not_invalidate_render_fingerprint(self) -> None:
        manifest = base_manifest()
        baseline = self.model(manifest)["render_fingerprint"]
        manifest["production"]["supported_style_systems"] = [
            "editorial-frame",
            "corporate-modular",
        ]
        self.assertEqual(self.model(manifest)["render_fingerprint"], baseline)
        manifest["production"]["expected_outputs"].append("contact_sheet")
        self.assertNotEqual(self.model(manifest)["render_fingerprint"], baseline)

    def test_asset_byte_changes_invalidate_the_render_fingerprint(self) -> None:
        cover = self.workdir / "cover.png"
        logo = self.workdir / "logo.png"
        body = self.workdir / "body.woff2"
        cover.write_bytes(b"cover-a")
        logo.write_bytes(b"logo-a")
        body.write_bytes(b"font-a")
        manifest = base_manifest()
        manifest["cover_image"] = "cover.png"
        manifest["brand"] = {
            "logos": {"on_light": "logo.png"},
            "fonts": {
                "body": {
                    "family": "Test Body",
                    "file": "body.woff2",
                    "source": "uploaded",
                }
            },
        }
        manifest.pop("visual_style_system", None)
        initial = self.model(manifest)
        manifest["proof"].update(
            {
                "approved": True,
                "render_fingerprint": initial["render_fingerprint"],
                "style_system_verified": True,
                "browser": {"engine": "chromium", "major": 140},
            }
        )
        self.assertTrue(self.model(manifest)["proof_approved"])

        for path, replacement in (
            (cover, b"cover-b"),
            (logo, b"logo-b"),
            (body, b"font-b"),
        ):
            before = self.model(manifest)["render_fingerprint"]
            manifest["proof"]["render_fingerprint"] = before
            path.write_bytes(replacement)
            after = self.model(manifest)
            self.assertNotEqual(after["render_fingerprint"], before)
            self.assertFalse(after["proof_approved"])

    def test_dormant_cover_asset_does_not_change_a_typographic_fingerprint(self) -> None:
        cover = self.workdir / "cover.png"
        cover.write_bytes(b"cover-a")
        manifest = base_manifest()
        manifest.update(cover_image="cover.png", cover_mode="typographic")
        initial = self.model(manifest)["render_fingerprint"]

        cover.write_bytes(b"cover-b")
        self.assertEqual(self.model(manifest)["render_fingerprint"], initial)
        cover.unlink()
        self.assertEqual(self.model(manifest)["render_fingerprint"], initial)

        manifest["cover_mode"] = "provided"
        self.assertNotEqual(self.model(manifest)["render_fingerprint"], initial)

    def test_exposes_a_safe_cover_image_endpoint_without_a_local_path(self) -> None:
        image = self.workdir / "cover.png"
        image.write_bytes(b"png")
        manifest = base_manifest()
        manifest["cover_image"] = "cover.png"
        manifest["cover_image_position"] = "40% 60%"
        model = self.model(manifest)
        self.assertEqual(
            model["cover_visual"],
            {
                "available": True,
                "endpoint": "/api/cover-image",
                "position": "40% 60%",
                "mode": "provided",
            },
        )
        self.assertNotIn(str(image), json.dumps(model))
        self.assertEqual(model["cover_mode"], "provided")

    def test_exposes_three_same_identity_visual_proofs_and_brand_default(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "name": "Studio",
            "visual_signature": {"style_system": "corporate_modular"},
        }
        manifest.pop("visual_style_system", None)
        proofs = self.model(manifest)["visual_proofs"]
        self.assertEqual(proofs["presentation_mode"], "recommended")
        self.assertEqual(proofs["selected_style_system"], "corporate-modular")
        self.assertEqual(proofs["recommended_style_system"], "corporate-modular")
        self.assertEqual(proofs["alternate_style_system"], "editorial-frame")
        self.assertEqual(proofs["advanced_style_systems"], ["editorial-halftone"])
        self.assertEqual(
            [option["id"] for option in proofs["options"]],
            ["editorial-frame", "editorial-halftone", "corporate-modular"],
        )
        self.assertEqual(
            [option["label"] for option in proofs["options"]],
            ["Editoriale", "Geometrico", "Frame"],
        )
        self.assertEqual(proofs["identity"]["brand"]["name"], "Studio")
        self.assertEqual(proofs["identity"]["cover"]["mode"], "typographic")

    def test_visual_style_override_and_missing_cover_intent_are_preserved_safely(self) -> None:
        image = self.workdir / "cover.png"
        image.write_bytes(b"png")
        manifest = base_manifest()
        manifest.update(
            {
                "visual_style_system": "editorial-halftone",
                "cover_mode": "generated",
                "cover_image": "cover.png",
            }
        )
        proofs = self.model(manifest)["visual_proofs"]
        self.assertEqual(proofs["selected_style_system"], "editorial-halftone")
        self.assertEqual(proofs["identity"]["cover"]["mode"], "generated")

        del manifest["cover_mode"]
        manifest["cover_visual_mode"] = "generative"
        self.assertEqual(self.model(manifest)["cover_mode"], "generated")

        manifest["visual_style_system"] = "non-esiste"
        manifest["cover_image"] = "manca.png"
        with self.assertRaisesRegex(ValueError, "visual_style_system"):
            self.model(manifest)
        manifest["schema_version"] = "1.2"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-frame",
        )
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["identity"]["cover"]["mode"],
            "generated",
        )
        manifest["workflow_state"] = "testi_approvati"
        self.assertEqual(self.model(manifest)["cover_mode"], "generated")
        self.assertFalse(self.model(manifest)["cover_visual"]["available"])

    def test_accepts_new_visual_system_aliases_without_breaking_canonical_ids(self) -> None:
        manifest = base_manifest()
        manifest["visual_style_system"] = "campo-cromatico"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-halftone",
        )
        manifest["visual_style_system"] = "costellazione"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-halftone",
        )
        manifest["visual_style_system"] = "geometrico"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "editorial-halftone",
        )
        manifest["visual_style_system"] = "istituzionale"
        self.assertEqual(
            self.model(manifest)["visual_proofs"]["selected_style_system"],
            "corporate-modular",
        )

    def test_puts_complete_sentences_on_new_lines_but_preserves_versions(self) -> None:
        manifest = base_manifest()
        manifest["items"][0]["summary"] = (
            "È disponibile la versione 1.2. Ora puoi aggiornare. Ultima frase."
        )
        summary = self.model(manifest)["slides"][1]["summary"]
        self.assertEqual(
            summary,
            "È disponibile la versione 1.2.\nOra puoi aggiornare.\nUltima frase.",
        )

    def test_breaks_question_exclamation_and_ellipsis_without_splitting_urls_or_abbreviations(self) -> None:
        manifest = base_manifest()
        manifest["items"][0]["summary"] = (
            "Versione 1.2. Dott. Rossi chiede: funziona? Sì! Certo… "
            "Visita https://example.com. Fine."
        )
        summary = self.model(manifest)["slides"][1]["summary"]
        self.assertEqual(
            summary,
            "Versione 1.2.\nDott. Rossi chiede: funziona?\nSì!\nCerto…\n"
            "Visita https://example.com.\nFine.",
        )

    def test_rejects_non_finite_json_constants(self) -> None:
        path = self.workdir / "manifest-nan.json"
        path.write_text(
            '{"revision":1,"cover_title":"T","items":[{"id":"i","summary":"S"}],"format":{"master_width":NaN}}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Costante JSON"):
            review_server.manifest_model(path)

    def test_status_polling_does_not_hash_render_assets(self) -> None:
        path = self.workdir / "manifest.json"
        write_json(path, base_manifest())
        with mock.patch.object(
            review_server,
            "render_asset_digests",
            side_effect=AssertionError("asset hashing must not run"),
        ):
            self.assertEqual(
                review_server.manifest_status(path),
                {
                    "manifest_revision": 1,
                    "workflow_state": "bozza",
                    "approval_checkpoint": "profile_text",
                },
            )

    def test_omits_a_disabled_outro(self) -> None:
        manifest = base_manifest()
        manifest["outro"]["enabled"] = False
        self.assertNotIn("outro", [entry["id"] for entry in self.model(manifest)["slides"]])

    def test_rejects_a_manifest_without_items(self) -> None:
        manifest = base_manifest()
        manifest["items"] = []
        with self.assertRaises(ValueError):
            self.model(manifest)

    def test_rejects_duplicate_item_ids(self) -> None:
        manifest = base_manifest()
        manifest["items"][1]["id"] = "item-1"
        with self.assertRaises(ValueError):
            self.model(manifest)

    def test_rejects_an_unknown_sequence_mode_in_current_schema(self) -> None:
        manifest = base_manifest()
        manifest["sequence_mode"] = "qualcosa"
        with self.assertRaisesRegex(ValueError, "sequence_mode"):
            self.model(manifest)

    def test_exposes_only_the_brand_summary(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "name": "Studio",
            "fonts": {"sans": {"family": "Brand Sans"}},
            "palette": {"accent": "#C65A3A"},
            "logos": {"on_light": "assets/logo.svg"},
        }
        brand = self.model(manifest)["brand"]
        self.assertEqual(brand["name"], "Studio")
        self.assertEqual(brand["sans"], "Brand Sans")
        self.assertEqual(brand["palette"]["accent"], "#C65A3A")
        self.assertTrue(brand["palette_declared"]["accent"])
        self.assertFalse(brand["palette_declared"]["background_light"])
        self.assertFalse(brand["logos"]["on_light"]["available"])
        self.assertNotIn("assets/logo.svg", json.dumps(brand))

    def test_palette_provenance_distinguishes_missing_partial_and_fallback_colors(self) -> None:
        fields = {
            "background_light",
            "background_dark",
            "text_on_light",
            "text_on_dark",
            "accent",
        }
        missing = self.model(base_manifest())
        self.assertEqual(
            missing["brand"]["palette_declared"],
            {field: False for field in fields},
        )
        self.assertEqual(missing["brand"]["palette"]["background_light"], "#F8F7F4")
        self.assertEqual(missing["brand"]["palette"]["background_dark"], "#2D2E2F")
        self.assertEqual(missing["brand"]["palette"]["text_on_light"], "#2D2E2F")
        self.assertEqual(missing["brand"]["palette"]["accent"], "#6B3F5D")
        self.assertEqual(
            missing["visual_proofs"]["identity"]["brand"]["palette_declared"],
            missing["brand"]["palette_declared"],
        )
        self.assertEqual(
            missing["brand_profile"]["palette_declared"],
            missing["brand"]["palette_declared"],
        )

        manifest = base_manifest()
        manifest["brand"] = {
            "palette": {
                "accent": "#C65A3A",
                "background_dark": "not-a-hex",
            }
        }
        partial = self.model(manifest)["brand"]
        self.assertEqual(partial["palette"]["accent"], "#C65A3A")
        self.assertTrue(partial["palette_declared"]["accent"])
        self.assertTrue(partial["palette_declared"]["background_dark"])
        self.assertFalse(partial["palette_declared"]["text_on_dark"])

    def test_exposes_a_portable_brand_profile_without_local_asset_paths(self) -> None:
        manifest = base_manifest()
        manifest.update({"visual_style_system": "editorial-halftone"})
        manifest["brand"] = {
            "name": "Studio",
            "website": "https://studio.example",
            "logos": {"on_light": "assets/logo-dark.svg", "on_dark": "assets/logo-light.svg"},
            "fonts": {
                "display": {"family": "Studio Display", "file": "assets/display.ttf", "source": "uploaded"},
                "body": {"family": "Studio Text", "file": "assets/body.ttf", "source": "uploaded"},
            },
            "visual_direction": {"mode": "custom", "description": "Pulito", "internal_slides": "clean_typographic"},
        }
        model = self.model(manifest)
        profile = model["brand_profile"]
        self.assertEqual(model["editor_version"], "2.14.2")
        self.assertEqual(profile["profile_type"], "carousel-brand")
        self.assertEqual(profile["visual_signature"]["style_system"], "editorial-halftone")
        self.assertEqual(profile["fonts"]["display"], {"family": "Studio Display", "source": "uploaded"})
        self.assertEqual(profile["logos"], {})
        self.assertNotIn("assets/", json.dumps(profile))

    def test_exposes_safe_logo_metadata_without_local_paths(self) -> None:
        logo_path = self.workdir / "logo.png"
        logo_path.write_bytes(b"logo")
        manifest = base_manifest()
        manifest["brand"] = {
            "name": "Studio",
            "logos": {"on_light": "logo.png", "on_dark": "missing.png"},
        }
        brand = self.model(manifest)["brand"]
        self.assertEqual(
            brand["logos"]["on_light"],
            {
                "available": True,
                "endpoint": "/api/logo/on-light",
                "source": "manifest",
                "master_format": "png",
            },
        )
        self.assertEqual(
            brand["logos"]["on_dark"],
            {
                "available": False,
                "endpoint": "",
                "source": "",
                "master_format": "png",
            },
        )
        self.assertNotIn(str(logo_path), json.dumps(brand))

    def test_uses_a_sibling_png_preview_for_an_svg_logo_master(self) -> None:
        (self.workdir / "logo.svg").write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
        (self.workdir / "logo.png").write_bytes(b"safe preview")
        manifest = base_manifest()
        manifest["brand"] = {"logos": {"on_light": "logo.svg"}}
        logo = self.model(manifest)["brand"]["logos"]["on_light"]
        self.assertEqual(
            logo,
            {
                "available": True,
                "endpoint": "/api/logo/on-light",
                "source": "sibling_png",
                "master_format": "svg",
            },
        )

    def test_exposes_default_logo_mode_and_an_resolved_italic_role(self) -> None:
        italic_path = self.workdir / "body-italic.ttf"
        italic_path.write_bytes(b"italic")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "body_italic": {
                    "family": "Studio Body Italic",
                    "file": "body-italic.ttf",
                    "source": "uploaded",
                },
                "serif_italic": "Playfair Display",
            }
        }
        model = self.model(manifest)
        self.assertEqual(model["logo_mode"], "auto")
        self.assertEqual(model["brand"]["emphasis_italic"]["role"], "body_italic")
        self.assertEqual(model["brand"]["emphasis_italic"]["endpoint"], "/api/font/italic")

    def test_prefers_an_explicit_italic_role_over_body_or_legacy_serif(self) -> None:
        for name in ("explicit.ttf", "body-italic.ttf"):
            (self.workdir / name).write_bytes(name.encode("utf-8"))
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "emphasis_italic": {"family": "Explicit", "file": "explicit.ttf"},
                "body_italic": {"family": "Body", "file": "body-italic.ttf"},
                "serif_italic": "Playfair Display",
            }
        }
        italic = self.model(manifest)["brand"]["font_assets"]["italic"]
        self.assertEqual(italic["role"], "emphasis_italic")
        self.assertEqual(italic["family"], "Explicit")

    def test_exposes_distinct_display_and_body_roles(self) -> None:
        display_path = self.workdir / "display.ttf"
        body_path = self.workdir / "body.ttf"
        display_path.write_bytes(b"display")
        body_path.write_bytes(b"body")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "display": {
                    "family": "Studio Display",
                    "file": "display.ttf",
                    "source": "uploaded",
                },
                "body": {
                    "family": "Studio Body",
                    "file": "body.ttf",
                    "source": "uploaded",
                },
            }
        }
        brand = self.model(manifest)["brand"]
        self.assertEqual(brand["display"], "Studio Display")
        self.assertEqual(brand["body"], "Studio Body")
        self.assertEqual(brand["sans"], "Studio Body")
        self.assertEqual(brand["font_assets"]["display"]["endpoint"], "/api/font/display")
        self.assertEqual(brand["font_assets"]["body"]["endpoint"], "/api/font/body")
        self.assertEqual(brand["font_assets"]["sans"]["endpoint"], "/api/font/sans")

    def test_maps_legacy_sans_to_display_and_body(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {"fonts": {"sans": "Inter"}}
        brand = self.model(manifest)["brand"]
        self.assertEqual(brand["display"], "Arial")
        self.assertEqual(brand["body"], "Arial")
        self.assertTrue(brand["font_assets"]["display"]["available"])
        self.assertTrue(brand["font_assets"]["body"]["available"])
        self.assertEqual(brand["font_assets"]["display"]["source"], "system")
        self.assertEqual(brand["font_assets"]["display"]["endpoint"], "")

    def test_normalizes_typography_and_never_scales_below_documented_floor(self) -> None:
        manifest = base_manifest()
        manifest["typography"] = {
            "cover_px": "large",
            "section_title_px": 88,
            "body_px": True,
            "cover_weight": 700,
            "section_title_weight": None,
            "body_weight": 630,
            "body_line_height": "dense",
            "sentence_gap_em": "tight",
            "body_tracking_em": 2,
            "min_auto_scale": 0.4,
            "overflow_policy": "shrink_forever",
        }
        typography = self.model(manifest)["typography"]
        self.assertEqual(typography["cover_px"], 112)
        self.assertEqual(typography["cover_subtitle_px"], 56)
        self.assertEqual(typography["section_title_px"], 88)
        self.assertEqual(typography["body_px"], 64)
        self.assertEqual(typography["cover_weight"], 700)
        self.assertEqual(typography["cover_subtitle_weight"], 500)
        self.assertEqual(typography["section_title_weight"], 800)
        self.assertEqual(typography["body_weight"], 630)
        self.assertEqual(typography["body_line_height"], 1.12)
        self.assertEqual(typography["sentence_gap_em"], 0.6)
        self.assertEqual(typography["cover_subtitle_line_height"], 1.08)
        self.assertEqual(typography["body_tracking_em"], -0.025)
        self.assertEqual(typography["min_auto_scale"], 0.92)
        self.assertEqual(typography["overflow_policy"], "error_and_copy_revision")

    def test_default_cover_title_is_not_bolded_by_base_typography(self) -> None:
        typography = self.model(base_manifest())["typography"]
        self.assertEqual(typography["cover_weight"], 500)

    def test_exposes_only_exact_emphasis_for_each_slide_field(self) -> None:
        manifest = base_manifest()
        manifest["sequence_mode"] = "sectional"
        manifest["cover_title_bold"] = ["La lezione", "assente"]
        manifest["cover_title_accent"] = ["La lezione", "assente", "operativa"]
        manifest["cover_title_underline"] = ["operativa", "assente"]
        manifest["items"][0].update(
            {
                "title": "Titolo da evidenziare",
                "title_bold": ["evidenziare"],
                "title_serif": ["Titolo", "da evidenziare", "non presente"],
                "title_accent": "non e una lista",
                "title_underline": ["da"],
                "summary_bold": ["Prima frase."],
                "summary_serif": ["Prima frase.", "Prima frase.", 4],
                "summary_accent": ["assente"],
                "summary_underline": ["frase."],
            }
        )
        manifest["outro"].update(
            {"title_serif": ["Chiusura"], "summary_bold": ["Corpo"]}
        )
        slides = {entry["id"]: entry for entry in self.model(manifest)["slides"]}
        self.assertEqual(slides["cover"]["title_bold"], ["La lezione"])
        self.assertEqual(slides["cover"]["title_serif"], ["e operativa"])
        self.assertEqual(slides["cover"]["title_accent"], ["La lezione", "operativa"])
        self.assertEqual(slides["cover"]["title_underline"], ["operativa"])
        self.assertEqual(slides["cover"]["summary_serif"], [])
        self.assertEqual(slides["item-1"]["title_bold"], ["evidenziare"])
        self.assertEqual(slides["item-1"]["title_serif"], ["Titolo", "da evidenziare"])
        self.assertEqual(slides["item-1"]["title_accent"], [])
        self.assertEqual(slides["item-1"]["title_underline"], ["da"])
        self.assertEqual(slides["item-1"]["summary_bold"], ["Prima frase."])
        self.assertEqual(slides["item-1"]["summary_serif"], ["Prima frase."])
        self.assertEqual(slides["item-1"]["summary_accent"], [])
        self.assertEqual(slides["item-1"]["summary_underline"], ["frase."])
        self.assertEqual(slides["outro"]["title_serif"], ["Chiusura"])
        self.assertEqual(slides["outro"]["summary_bold"], ["Corpo"])
        self.assertEqual(slides["outro"]["summary_serif"], [])

    def test_exposes_font_metadata_without_local_paths(self) -> None:
        font_path = self.workdir / "brand.woff2"
        font_path.write_bytes(b"fake font")
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "sans": {
                    "family": "Studio Sans",
                    "file": "brand.woff2",
                    "source": "uploaded",
                },
                "serif": {"family": "Studio Serif", "file": "missing.ttf"},
            }
        }
        model = self.model(manifest)
        fonts = model["brand"]["font_assets"]
        self.assertEqual(model["brand"]["sans"], "Studio Sans")
        self.assertEqual(fonts["sans"], {
            "family": "Studio Sans",
            "source": "uploaded",
            "available": True,
            "endpoint": "/api/font/sans",
        })
        self.assertFalse(fonts["serif"]["available"])
        self.assertEqual(fonts["serif"]["endpoint"], "")
        self.assertNotIn(str(font_path), json.dumps(model))

    def test_migrates_legacy_neutral_families_to_system_fonts(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "display": {"family": "Inter", "source": "bundled"},
                "body": {"family": "Inter", "source": "bundled"},
                "emphasis_italic": {"family": "Playfair Display", "source": "bundled"},
            }
        }
        brand = self.model(manifest)["brand"]
        fonts = brand["font_assets"]
        self.assertEqual(brand["display"], "Arial")
        self.assertEqual(brand["body"], "Arial")
        self.assertEqual(fonts["display"], {
            "family": "Arial", "source": "system", "available": True, "endpoint": ""
        })
        self.assertEqual(fonts["body"], {
            "family": "Arial", "source": "system", "available": True, "endpoint": ""
        })
        self.assertEqual(fonts["italic"], {
            "family": "Times New Roman",
            "source": "system",
            "available": True,
            "endpoint": "",
            "role": "emphasis_italic",
            "fallbacks": [],
        })

    def test_exposes_default_system_italic_for_browser_verification(self) -> None:
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "display": {"family": "Arial", "source": "system"},
                "body": {"family": "Arial", "source": "system"},
                "emphasis_italic": {"family": "Times New Roman", "source": "system"},
            }
        }
        italic = self.model(manifest)["brand"]["font_assets"]["italic"]
        self.assertEqual(italic["family"], "Times New Roman")
        self.assertEqual(italic["source"], "system")
        self.assertTrue(italic["available"])
        self.assertEqual(italic["endpoint"], "")

    def test_rejects_a_font_path_outside_the_manifest_directory(self) -> None:
        outside = self.workdir.parent / f"{self.workdir.name}-outside-font.woff2"
        outside.write_bytes(b"private bytes")
        self.addCleanup(outside.unlink, missing_ok=True)
        manifest = base_manifest()
        manifest["brand"] = {
            "fonts": {
                "sans": {
                    "family": "Outside Sans",
                    "file": f"../{outside.name}",
                    "source": "uploaded",
                }
            }
        }
        font = self.model(manifest)["brand"]["font_assets"]["sans"]
        self.assertFalse(font["available"])
        self.assertEqual(font["endpoint"], "")

    def test_rejects_a_logo_path_outside_the_manifest_directory(self) -> None:
        outside = self.workdir.parent / f"{self.workdir.name}-outside-logo.png"
        outside.write_bytes(b"private logo")
        self.addCleanup(outside.unlink, missing_ok=True)
        manifest = base_manifest()
        manifest["brand"] = {"logos": {"on_light": f"../{outside.name}"}}
        logo = self.model(manifest)["brand"]["logos"]["on_light"]
        self.assertFalse(logo["available"])
        self.assertEqual(logo["endpoint"], "")


class ValidateFeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        path = self.workdir / "manifest.json"
        path.write_text(json.dumps(base_manifest()), encoding="utf-8")
        self.model = review_server.manifest_model(path, include_internal=True)

    def payload(self, slides: list[dict] | None = None, **overrides: object) -> dict:
        value = {
            "action": "feedback",
            "base_revision": 1,
            "slides": slides
            if slides is not None
            else [
                slide("cover", "cover", title="La lezione e operativa"),
                slide("item-1", "item", summary="Prima frase."),
                slide("item-2", "item", summary="Seconda frase."),
                slide("outro", "outro", title="Chiusura", summary="Corpo della chiusura."),
            ],
            "comments": [],
            "overall_note": "",
        }
        value.update(overrides)
        if value.get("action") == "approve" and "render_fingerprint" not in value:
            value["render_fingerprint"] = self.model["render_fingerprint"]
        if value.get("action") == "approve" and "base_workflow_state" not in value:
            value["base_workflow_state"] = self.model["workflow_state"]
        return value

    def test_accepts_a_well_formed_batch(self) -> None:
        result = review_server.validate_feedback(self.payload(), self.model)
        self.assertEqual(result["action"], "feedback")
        self.assertEqual(str(uuid.UUID(result["feedback_id"])), result["feedback_id"])
        self.assertEqual(len(result["slides"]), 4)

    def test_unhashable_json_fields_are_rejected_as_validation_errors(self) -> None:
        cases = []
        cases.append(self.payload(action=["feedback"]))

        bad_slide_id = self.payload()
        bad_slide_id["slides"][1]["id"] = ["item-1"]
        cases.append(bad_slide_id)

        bad_comment_kind = self.payload()
        bad_comment_kind["comments"] = [{"kind": ["slide"], "slide_id": "item-1"}]
        cases.append(bad_comment_kind)

        bad_comment_slide = self.payload()
        bad_comment_slide["comments"] = [{"kind": "slide", "slide_id": ["item-1"]}]
        cases.append(bad_comment_slide)

        for index, payload in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                review_server.validate_feedback(payload, self.model)

    def test_accepts_a_canonical_client_feedback_uuid_and_rejects_other_ids(self) -> None:
        feedback_id = str(uuid.uuid4())
        result = review_server.validate_feedback(
            self.payload(feedback_id=feedback_id), self.model
        )
        self.assertEqual(result["feedback_id"], feedback_id)
        for invalid in ("feedback-test", "../escape", feedback_id.upper(), ""):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "UUID"):
                review_server.validate_feedback(
                    self.payload(feedback_id=invalid), self.model
                )

    def test_accepts_three_distinct_emphasis_phrases_in_one_role(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "Uno due tre."
        slides[1]["summary_serif"] = []
        slides[1]["summary_accent"] = ["Uno", "due", "tre"]
        result = review_server.validate_feedback(self.payload(slides), self.model)
        self.assertEqual(
            result["slides"][1]["summary_accent"], ["Uno", "due", "tre"]
        )

    def test_approval_reports_documented_internal_copy_limits(self) -> None:
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1].update(
            {
                "title": "Titolo",
                "summary": "x" * 181,
                "summary_serif": [],
            }
        )
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertTrue(any("massimo 180" in warning for warning in approved["warnings"]))

        slides[1]["title"] = ""
        slides[1]["summary"] = "x" * 321
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertTrue(any("massimo 320" in warning for warning in approved["warnings"]))

        feedback = review_server.validate_feedback(self.payload(slides), self.model)
        self.assertTrue(any("massimo 320" in warning for warning in feedback["warnings"]))

    def test_visual_approval_rejects_editorial_changes_but_accepts_visual_selection(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        path = self.workdir / "visual-current.json"
        write_json(path, manifest)
        model = review_server.manifest_model(path, include_internal=True)
        baseline = [
            {
                "id": value["id"],
                "kind": value["kind"],
                "title": value.get("title", ""),
                "summary": value.get("summary", ""),
                **{
                    f"{field}_{role}": value.get(f"{field}_{role}", [])
                    for field in ("title", "summary")
                    for role in review_server.EMPHASIS_ROLES
                },
                **{
                    f"{field}_{role}_ranges": value.get(f"{field}_{role}_ranges", [])
                    for field in ("title", "summary")
                    for role in review_server.EMPHASIS_ROLES
                },
            }
            for value in model["slides"]
        ]
        common = {
            "action": "approve",
            "base_workflow_state": "testi_approvati",
            "render_fingerprint": model["render_fingerprint"],
            "proof_slide_ids": model["proof"]["required_slide_ids"],
            "style_system_verified": True,
            "proof_browser": {"engine": "chromium", "major": 140},
        }
        changed_copy = copy.deepcopy(baseline)
        changed_copy[1]["summary"] = "Prima frase corretta."
        with self.assertRaisesRegex(ValueError, "modifiche editoriali"):
            review_server.validate_feedback(
                self.payload(changed_copy, **common), model
            )

        selected = review_server.validate_feedback(
            self.payload(
                baseline,
                visual_style_system="corporate-modular",
                logo_mode="hidden",
                **common,
            ),
            model,
        )
        self.assertEqual(selected["visual_style_system"], "corporate-modular")
        self.assertEqual(selected["logo_mode"], "hidden")

    def test_transports_all_emphasis_roles_and_preserves_legacy_serif(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "Prima frase utile."
        slides[1].update(
            {
                "summary_bold": ["Prima"],
                "summary_italic": [],
                "summary_serif": ["frase"],
                "summary_accent": [],
                "summary_underline": ["utile"],
                "title_bold": [],
                "title_italic": [],
                "title_serif": [],
                "title_accent": [],
                "title_underline": [],
            }
        )
        result = review_server.validate_feedback(self.payload(slides), self.model)
        item = result["slides"][1]
        self.assertEqual(item["summary_bold"], ["Prima"])
        self.assertEqual(item["summary_serif"], ["frase"])
        self.assertIn("summary_italic", item)
        self.assertEqual(item["summary_underline"], ["utile"])

    def test_rejects_ambiguous_or_overlapping_emphasis(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary_bold"] = ["a"]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

        slides = self.payload()["slides"]
        slides[1]["summary_bold"] = ["Prima"]
        slides[1]["summary_italic"] = ["Prima frase."]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_same_selection_with_two_treatments_has_one_actionable_error(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary_serif"] = []
        slides[1]["summary_underline"] = ["Prima"]
        slides[1]["summary_accent"] = ["Prima"]
        with self.assertRaisesRegex(
            ValueError,
            "“Prima” ha più trattamenti.*Scegline uno",
        ):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_missing_bold_neither_warns_nor_blocks_approval(self) -> None:
        feedback = review_server.validate_feedback(self.payload(), self.model)
        self.assertFalse(any("summary_bold" in warning for warning in feedback["warnings"]))
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertEqual(approved["action"], "approve")
        self.assertEqual(approved["approval_stage"], "profile_text")
        self.assertEqual(
            approved["base_render_fingerprint"], self.model["render_fingerprint"]
        )
        self.assertEqual(len(approved["render_fingerprint"]), 64)

    def test_any_approval_with_pending_comment_or_note_is_rejected(self) -> None:
        comment = {
            "id": "comment-approval",
            "kind": "brand",
            "slide_id": "",
            "feedback": "Da rivedere",
        }
        for changes in (
            {"overall_note": "Non ancora approvato"},
            {"comments": [comment]},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                ValueError, "commenti o note pendenti"
            ):
                review_server.validate_feedback(
                    self.payload(action="approve", **changes), self.model
                )

    def test_combined_approval_requires_a_clean_final_proof(self) -> None:
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        common = {
            "action": "approve",
            "approval_scope": "profile_text_and_visual",
            "proof_slide_ids": self.model["proof"]["required_slide_ids"],
            "style_system_verified": True,
            "proof_browser": {"engine": "chromium", "major": 140},
        }
        approved = review_server.validate_feedback(
            self.payload(slides, **common), self.model
        )
        self.assertEqual(approved["approval_stage"], "profile_text")
        self.assertEqual(
            approved["approval_scope"], "profile_text_and_visual"
        )
        self.assertEqual(
            approved["proof_slide_ids"], self.model["proof"]["required_slide_ids"]
        )
        with self.assertRaisesRegex(ValueError, "commenti o note"):
            review_server.validate_feedback(
                self.payload(slides, overall_note="Da verificare", **common),
                self.model,
            )

    def test_visual_approval_stage_is_derived_and_stale_fingerprints_fail(self) -> None:
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        manifest_path = self.workdir / "visual-manifest.json"
        write_json(manifest_path, manifest)
        visual_model = review_server.manifest_model(
            manifest_path, include_internal=True
        )
        approved = review_server.validate_feedback(
            self.payload(
                slides,
                action="approve",
                base_workflow_state=visual_model["workflow_state"],
                render_fingerprint=visual_model["render_fingerprint"],
                proof_slide_ids=visual_model["proof"]["required_slide_ids"],
                style_system_verified=True,
                proof_browser={"engine": "chromium", "major": 140},
            ),
            visual_model,
        )
        self.assertEqual(approved["approval_stage"], "visual_proof")
        for workflow_state in (
            "prova_visuale_approvata",
            "rendering",
            "qa",
            "consegnato",
        ):
            set_workflow_state(manifest, workflow_state)
            write_json(manifest_path, manifest)
            reapproval_model = review_server.manifest_model(
                manifest_path, include_internal=True
            )
            reapproved = review_server.validate_feedback(
                self.payload(
                    slides,
                    action="approve",
                    base_workflow_state=workflow_state,
                    render_fingerprint=reapproval_model["render_fingerprint"],
                    proof_slide_ids=reapproval_model["proof"]["required_slide_ids"],
                    style_system_verified=True,
                    proof_browser={"engine": "chromium", "major": 140},
                ),
                reapproval_model,
            )
            self.assertEqual(reapproved["approval_stage"], "visual_proof")

        with self.assertRaisesRegex(ValueError, "base_workflow_state"):
            review_server.validate_feedback(
                self.payload(slides, action="approve"), visual_model
            )

        with self.assertRaisesRegex(ValueError, "render_fingerprint"):
            review_server.validate_feedback(
                self.payload(
                    slides,
                    action="approve",
                    base_workflow_state=visual_model["workflow_state"],
                    render_fingerprint="0" * 64,
                    proof_slide_ids=visual_model["proof"]["required_slide_ids"],
                    style_system_verified=True,
                    proof_browser={"engine": "chromium", "major": 140},
                ),
                visual_model,
            )
        with self.assertRaisesRegex(ValueError, "approval_stage"):
            review_server.validate_feedback(
                self.payload(
                    slides,
                    action="approve",
                    base_workflow_state=visual_model["workflow_state"],
                    render_fingerprint=visual_model["render_fingerprint"],
                    approval_stage="profile_text",
                    proof_slide_ids=visual_model["proof"]["required_slide_ids"],
                    style_system_verified=True,
                    proof_browser={"engine": "chromium", "major": 140},
                ),
                visual_model,
            )

    def test_visual_approval_requires_proof_attestation_and_supported_producer(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        path = self.workdir / "proof-contract.json"
        write_json(path, manifest)
        model = review_server.manifest_model(path, include_internal=True)
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        common = {
            "action": "approve",
            "base_workflow_state": model["workflow_state"],
            "render_fingerprint": model["render_fingerprint"],
        }
        for missing in ("proof_slide_ids", "proof_browser"):
            payload = self.payload(slides, **common)
            payload.update(
                {
                    "proof_slide_ids": model["proof"]["required_slide_ids"],
                    "style_system_verified": True,
                    "proof_browser": {"engine": "chromium", "major": 140},
                }
            )
            payload.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                review_server.validate_feedback(payload, model)

        advisory_payload = self.payload(
            slides,
            **common,
            proof_slide_ids=model["proof"]["required_slide_ids"],
            proof_browser={"engine": "chromium", "major": 140},
        )
        advisory_result = review_server.validate_feedback(advisory_payload, model)
        self.assertFalse(advisory_result["style_system_verified"])

        invalid_browser = self.payload(
            slides,
            **common,
            proof_slide_ids=model["proof"]["required_slide_ids"],
            style_system_verified=True,
            proof_browser={"engine": "firefox", "major": 141},
        )
        with self.assertRaisesRegex(ValueError, "chromium"):
            review_server.validate_feedback(invalid_browser, model)

        incompatible_manifest = base_manifest()
        set_workflow_state(incompatible_manifest, "testi_approvati")
        incompatible_manifest.pop("cover_title_serif", None)
        incompatible_manifest["items"][0].pop("summary_serif", None)
        incompatible_manifest["production"]["producer"] = "unrelated-renderer"
        incompatible_path = self.workdir / "incompatible-renderer.json"
        write_json(incompatible_path, incompatible_manifest)
        incompatible_model = review_server.manifest_model(
            incompatible_path, include_internal=True
        )
        with self.assertRaisesRegex(ValueError, "contratto renderer locale"):
            review_server.validate_feedback(
                self.payload(
                    slides,
                    action="approve",
                    base_workflow_state=incompatible_model["workflow_state"],
                    render_fingerprint=incompatible_model["render_fingerprint"],
                    proof_slide_ids=incompatible_model["proof"]["required_slide_ids"],
                    style_system_verified=True,
                    proof_browser={"engine": "chromium", "major": 140},
                ),
                incompatible_model,
            )

        approved = review_server.validate_feedback(
            self.payload(
                slides,
                **common,
                proof_slide_ids=model["proof"]["required_slide_ids"],
                style_system_verified=True,
                proof_browser={"engine": "chromium", "major": 140},
            ),
            model,
        )
        self.assertEqual(approved["proof_slide_ids"], ["cover", "item-2", "outro"])
        self.assertTrue(approved["style_system_verified"])
        self.assertEqual(approved["proof_browser"]["engine"], "chromium")

    def test_visual_approval_rejects_a_requested_cover_without_an_image(self) -> None:
        manifest = base_manifest()
        set_workflow_state(manifest, "testi_approvati")
        manifest.pop("cover_title_serif", None)
        manifest["items"][0].pop("summary_serif", None)
        manifest["cover_mode"] = "generated"
        path = self.workdir / "missing-cover-proof.json"
        write_json(path, manifest)
        model = review_server.manifest_model(path, include_internal=True)
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []

        with self.assertRaisesRegex(ValueError, "richiede un'immagine disponibile"):
            review_server.validate_feedback(
                self.payload(
                    slides,
                    action="approve",
                    base_workflow_state=model["workflow_state"],
                    render_fingerprint=model["render_fingerprint"],
                    cover_mode="generated",
                    proof_slide_ids=model["proof"]["required_slide_ids"],
                    style_system_verified=True,
                    proof_browser={"engine": "chromium", "major": 140},
                ),
                model,
            )

    def test_approval_requires_the_server_issued_workflow_echo(self) -> None:
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        payload = self.payload(slides, action="approve")
        payload.pop("base_workflow_state")
        with self.assertRaisesRegex(ValueError, "base_workflow_state"):
            review_server.validate_feedback(payload, self.model)

    def test_approve_allows_multiple_non_overlapping_emphasis_styles(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "Prima seconda terza."
        slides[1]["summary_bold"] = ["Prima"]
        slides[1]["summary_underline"] = ["seconda"]
        slides[1]["summary_accent"] = ["terza."]
        slides[0]["title_serif"] = []
        slides[1]["summary_serif"] = []
        slides[2]["summary_accent"] = []
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertEqual(approved["slides"][1]["summary_bold"], ["Prima"])
        self.assertEqual(approved["slides"][1]["summary_underline"], ["seconda"])
        self.assertEqual(approved["slides"][1]["summary_accent"], ["terza."])

    def test_approve_reports_missing_real_italic_font_as_an_advisory(self) -> None:
        slides = self.payload()["slides"]
        slides[0]["title_serif"] = []
        slides[1].update({"summary_bold": ["Prima"], "summary_serif": ["frase."]})
        slides[2]["summary_bold"] = ["Seconda"]
        slides[2]["summary_accent"] = []
        approved = review_server.validate_feedback(
            self.payload(slides, action="approve"), self.model
        )
        self.assertTrue(any("font corsivo reale" in warning for warning in approved["warnings"]))

    def test_validates_and_transports_logo_mode(self) -> None:
        result = review_server.validate_feedback(self.payload(logo_mode="hidden"), self.model)
        self.assertEqual(result["logo_mode"], "hidden")
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(logo_mode="always"), self.model)

    def test_accepts_a_visual_style_choice_and_rejects_unknown_ones(self) -> None:
        result = review_server.validate_feedback(
            self.payload(visual_style_system="corporate_modular"), self.model
        )
        self.assertEqual(result["visual_style_system"], "corporate-modular")
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(visual_style_system="non-esiste"), self.model
            )

    def test_accepts_deletion_and_reorder(self) -> None:
        slides = [
            slide("cover", "cover", title="La lezione e operativa"),
            slide("item-2", "item", summary="Seconda frase."),
            slide("outro", "outro", title="Chiusura", summary="Corpo."),
        ]
        result = review_server.validate_feedback(self.payload(slides), self.model)
        self.assertEqual(
            [entry["id"] for entry in result["slides"]], ["cover", "item-2", "outro"]
        )

    def test_rejects_a_stale_base_revision(self) -> None:
        with self.assertRaises(RuntimeError):
            review_server.validate_feedback(self.payload(base_revision=9), self.model)

    def test_rejects_an_unknown_slide(self) -> None:
        slides = self.payload()["slides"]
        slides[1] = slide("item-99", "item", summary="Testo.")
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_duplicated_slide(self) -> None:
        slides = self.payload()["slides"]
        slides[2] = dict(slides[1])
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_changed_slide_kind(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["kind"] = "cover"
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_cover_that_is_not_first(self) -> None:
        slides = self.payload()["slides"]
        slides[0], slides[1] = slides[1], slides[0]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_an_outro_that_is_not_last(self) -> None:
        slides = self.payload()["slides"]
        slides[2], slides[3] = slides[3], slides[2]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_a_batch_without_items(self) -> None:
        slides = [
            slide("cover", "cover", title="La lezione e operativa"),
            slide("outro", "outro", title="Chiusura", summary="Corpo."),
        ]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_an_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(action="delete"), self.model)

    def test_rejects_an_unknown_comment_kind(self) -> None:
        comment = {"kind": "altro", "slide_id": "item-1", "feedback": "x"}
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(comments=[comment]), self.model
            )

    def test_rejects_a_comment_on_an_unknown_slide(self) -> None:
        comment = {"kind": "slide", "slide_id": "item-99", "feedback": "x"}
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(comments=[comment]), self.model
            )

    def test_accepts_a_brand_comment_without_a_slide(self) -> None:
        comment = {"kind": "brand", "slide_id": "", "feedback": "Fondo più chiaro"}
        result = review_server.validate_feedback(
            self.payload(comments=[comment]), self.model
        )
        self.assertEqual(result["comments"][0]["kind"], "brand")

    def test_rejects_text_over_the_limit(self) -> None:
        slides = self.payload()["slides"]
        slides[1]["summary"] = "x" * (review_server.MAX_TEXT + 1)
        with self.assertRaises(ValueError):
            review_server.validate_feedback(self.payload(slides), self.model)

    def test_rejects_too_many_comments(self) -> None:
        comment = {"kind": "brand", "slide_id": "", "feedback": "x"}
        comments = [dict(comment) for _ in range(review_server.MAX_COMMENTS + 1)]
        with self.assertRaises(ValueError):
            review_server.validate_feedback(
                self.payload(comments=comments), self.model
            )


class StartupLockingTest(unittest.TestCase):
    def test_writes_and_recovers_state_while_holding_apply_compatible_locks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            manifest_path = (workdir / "manifest.json").resolve()
            session_dir = (workdir / "session").resolve()
            state_path = session_dir / "session-state.json"
            manifest_lock = manifest_path.with_name(
                f".{manifest_path.name}.review.lock"
            )
            transaction_lock = session_dir / ".review-transaction.lock"
            write_json(manifest_path, base_manifest())

            class TrackingLock:
                held: set[str] = set()

                def __init__(self, path: Path):
                    self.path = path

                def acquire(self):
                    self.held.add(str(self.path))
                    return self

                def release(self) -> None:
                    self.held.discard(str(self.path))

                def __enter__(self):
                    return self.acquire()

                def __exit__(self, *_args: object) -> None:
                    self.release()

            class FakeServer:
                server_address = ("127.0.0.1", 43210)

                def __init__(self, *_args: object, **_kwargs: object):
                    pass

                def serve_forever(self, **_kwargs: object) -> None:
                    pass

                def server_close(self) -> None:
                    pass

            original_atomic_write = review_server.atomic_write_json

            def checked_atomic_write(path: Path, value: dict) -> None:
                if path == state_path:
                    self.assertTrue(
                        {str(manifest_lock), str(transaction_lock)}.issubset(
                            TrackingLock.held
                        )
                    )
                original_atomic_write(path, value)

            argv = [
                "review_server.py",
                str(manifest_path),
                "--session-dir",
                str(session_dir),
                "--port",
                "0",
            ]
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(review_server, "InterprocessLock", TrackingLock)
                )
                stack.enter_context(
                    mock.patch.object(review_server, "ThreadingHTTPServer", FakeServer)
                )
                stack.enter_context(
                    mock.patch.object(
                        review_server, "atomic_write_json", checked_atomic_write
                    )
                )
                stack.enter_context(mock.patch("sys.argv", argv))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                self.assertEqual(review_server.main(), 0)

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_rejects_a_symlinked_session_directory_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            manifest_path = workdir / "manifest.json"
            write_json(manifest_path, base_manifest())
            target = workdir / "session-target"
            target.mkdir()
            sentinel = target / "sentinel.txt"
            sentinel.write_text("immutato", encoding="utf-8")
            target.chmod(0o755)
            before_mode = stat.S_IMODE(target.stat().st_mode)
            before_entries = sorted(path.name for path in target.iterdir())
            session_link = workdir / "session"
            session_link.symlink_to(target, target_is_directory=True)
            stderr = io.StringIO()

            argv = [
                "review_server.py",
                str(manifest_path),
                "--session-dir",
                str(session_link),
                "--port",
                "0",
            ]
            with mock.patch("sys.argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(review_server.main(), 2)

            self.assertIn("collegamento simbolico", json.loads(stderr.getvalue())["error"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutato")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), before_mode)
            self.assertEqual(sorted(path.name for path in target.iterdir()), before_entries)

    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_rejects_symlinked_parent_components_before_creating_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            manifest_path = workdir / "manifest.json"
            write_json(manifest_path, base_manifest())
            target_parent = workdir / "target-parent"
            target_parent.mkdir()
            sentinel = target_parent / "sentinel.txt"
            sentinel.write_text("immutato", encoding="utf-8")
            target_parent.chmod(0o755)
            before_mode = stat.S_IMODE(target_parent.stat().st_mode)
            alias = workdir / "alias"
            alias.symlink_to(target_parent, target_is_directory=True)
            stderr = io.StringIO()

            argv = [
                "review_server.py",
                str(manifest_path),
                "--session-dir",
                str(alias / "session"),
                "--port",
                "0",
            ]
            with mock.patch("sys.argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(review_server.main(), 2)

            self.assertIn("collegamento simbolico", json.loads(stderr.getvalue())["error"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutato")
            self.assertEqual(stat.S_IMODE(target_parent.stat().st_mode), before_mode)
            self.assertFalse((target_parent / "session").exists())

            manifest_target_dir = workdir / "manifest-target-parent"
            manifest_target = manifest_target_dir / "manifest.json"
            write_json(manifest_target, base_manifest())
            manifest_before = manifest_target.read_bytes()
            manifest_alias = workdir / "manifest-alias"
            manifest_alias.symlink_to(manifest_target_dir, target_is_directory=True)
            clean_session = workdir / "clean-session"
            stderr = io.StringIO()
            argv[1] = str(manifest_alias / "manifest.json")
            argv[3] = str(clean_session)

            with mock.patch("sys.argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(review_server.main(), 2)

            self.assertIn("collegamento simbolico", json.loads(stderr.getvalue())["error"])
            self.assertEqual(manifest_target.read_bytes(), manifest_before)
            self.assertFalse(clean_session.exists())

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_rejects_a_hardlinked_session_state_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            manifest_path = workdir / "manifest.json"
            session_dir = workdir / "session"
            write_json(manifest_path, base_manifest())
            victim = workdir / "state-victim.json"
            write_json(
                victim,
                {
                    "manifest": str(manifest_path.resolve()),
                    "manifest_revision": 1,
                },
            )
            victim.chmod(0o644)
            state_path = session_dir / "session-state.json"
            state_path.parent.mkdir(parents=True)
            os.link(victim, state_path)
            before = victim.read_bytes()
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            stderr = io.StringIO()

            argv = [
                "review_server.py",
                str(manifest_path),
                "--session-dir",
                str(session_dir),
                "--port",
                "0",
            ]
            with mock.patch("sys.argv", argv), contextlib.redirect_stderr(stderr):
                self.assertEqual(review_server.main(), 2)

            self.assertIn("hard link", json.loads(stderr.getvalue())["error"])
            self.assertEqual(victim.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)


class LockFileSecurityTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symlink non sempre disponibile su Windows")
    def test_lock_open_rejects_a_symlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            victim = workdir / "victim"
            victim.write_bytes(b"")
            victim.chmod(0o644)
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            lock_path = workdir / ".review-transaction.lock"
            lock_path.symlink_to(victim)

            with self.assertRaisesRegex(OSError, "collegamento simbolico"):
                review_server.InterprocessLock(lock_path).acquire()

            self.assertEqual(victim.read_bytes(), b"")
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)

    @unittest.skipIf(os.name == "nt", "hard link non sempre disponibile su Windows")
    def test_lock_open_rejects_a_hardlink_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            victim = workdir / "victim"
            victim.write_bytes(b"")
            victim.chmod(0o644)
            before_mode = stat.S_IMODE(victim.stat().st_mode)
            lock_path = workdir / ".review-transaction.lock"
            os.link(victim, lock_path)

            with self.assertRaisesRegex(OSError, "hard link"):
                review_server.InterprocessLock(lock_path).acquire()

            self.assertEqual(victim.read_bytes(), b"")
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), before_mode)


class FeedbackTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.manifest_path = (self.workdir / "manifest.json").resolve()
        self.session_dir = self.workdir / "session"
        self.state_path = self.session_dir / "session-state.json"
        self.feedback_path = self.session_dir / "feedback.json"
        self.journal_path = self.session_dir / "feedback-commit.json"
        self.state = {
            "manifest": str(self.manifest_path),
            "manifest_revision": 1,
            "last_feedback_id": None,
            "applied_feedback_id": None,
        }
        self.feedback = {
            "feedback_id": "feedback-transaction",
            "submitted_at": "2026-01-01T00:00:00+00:00",
            "action": "feedback",
        }
        write_json(self.manifest_path, base_manifest())
        write_json(self.state_path, self.state)

    def commit(self) -> dict:
        return review_server.commit_feedback(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
            current_state=self.state,
            feedback=self.feedback,
            manifest_revision=1,
        )

    def test_recovers_an_interrupted_feedback_commit(self) -> None:
        self.commit()
        self.feedback_path.unlink()
        write_json(self.state_path, self.state)

        event = review_server.recover_feedback_commit(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
        )

        self.assertEqual(event["feedback_id"], "feedback-transaction")
        recovered_feedback = json.loads(self.feedback_path.read_text(encoding="utf-8"))
        recovered_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered_feedback, self.feedback)
        self.assertEqual(recovered_state["last_feedback_id"], "feedback-transaction")
        self.assertEqual(recovered_state["last_action"], "feedback")

    def test_recovers_a_legacy_journal_without_last_action(self) -> None:
        self.commit()
        journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
        journal["state_patch"].pop("last_action")
        journal["state_before"].pop("last_action")
        write_json(self.journal_path, journal)
        self.feedback_path.unlink()
        write_json(self.state_path, self.state)

        event = review_server.recover_feedback_commit(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
        )

        self.assertEqual(event["action"], "feedback")
        recovered_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered_state["last_action"], "feedback")

    def test_recovers_a_pre_state_crash_when_the_new_action_alternates(self) -> None:
        self.state["last_action"] = "feedback"
        self.feedback["action"] = "approve"
        write_json(self.state_path, self.state)
        self.commit()
        write_json(self.state_path, self.state)

        event = review_server.recover_feedback_commit(
            journal_path=self.journal_path,
            feedback_path=self.feedback_path,
            state_path=self.state_path,
            manifest_path=self.manifest_path,
        )

        self.assertEqual(event["action"], "approve")
        recovered_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(recovered_state["last_action"], "approve")

    def test_rejects_recovery_after_an_unrelated_state_change(self) -> None:
        self.commit()
        conflicting = dict(self.state)
        conflicting["last_feedback_id"] = "feedback-unrelated"
        write_json(self.state_path, conflicting)

        with self.assertRaisesRegex(ValueError, "stato è cambiato"):
            review_server.recover_feedback_commit(
                journal_path=self.journal_path,
                feedback_path=self.feedback_path,
                state_path=self.state_path,
                manifest_path=self.manifest_path,
            )

    def test_rejects_recovery_when_last_action_conflicts_with_the_batch(self) -> None:
        self.commit()
        conflicting = json.loads(self.state_path.read_text(encoding="utf-8"))
        conflicting["last_action"] = "approve"
        write_json(self.state_path, conflicting)

        with self.assertRaisesRegex(ValueError, "last_action"):
            review_server.recover_feedback_commit(
                journal_path=self.journal_path,
                feedback_path=self.feedback_path,
                state_path=self.state_path,
                manifest_path=self.manifest_path,
            )

    def test_recovery_rejects_unhashable_journal_fields_as_validation_errors(self) -> None:
        self.commit()
        original = json.loads(self.journal_path.read_text(encoding="utf-8"))
        for field, value, message in (
            ("version", [2], "Journal feedback non valido"),
            ("feedback.action", ["feedback"], "Journal feedback incoerente"),
        ):
            journal = json.loads(json.dumps(original))
            if field == "version":
                journal["version"] = value
            else:
                journal["feedback"]["action"] = value
            write_json(self.journal_path, journal)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                review_server.recover_feedback_commit(
                    journal_path=self.journal_path,
                    feedback_path=self.feedback_path,
                    state_path=self.state_path,
                    manifest_path=self.manifest_path,
                )

    def test_journal_exists_before_state_revision_is_advanced(self) -> None:
        original = review_server.atomic_write_json
        observed = []

        def checked(path: Path, value: dict) -> None:
            if path == self.state_path and value.get("manifest_revision") == 2:
                observed.append(self.journal_path.exists())
            original(path, value)

        with mock.patch.object(review_server, "atomic_write_json", side_effect=checked):
            review_server.commit_feedback(
                journal_path=self.journal_path,
                feedback_path=self.feedback_path,
                state_path=self.state_path,
                manifest_path=self.manifest_path,
                current_state=self.state,
                feedback=self.feedback,
                manifest_revision=2,
            )
        self.assertEqual(observed, [True])


class EventTransportTest(unittest.TestCase):
    def test_stdout_event_is_best_effort(self) -> None:
        with mock.patch("builtins.print", side_effect=BrokenPipeError):
            self.assertFalse(review_server.emit_event({"event": "feedback"}))


if __name__ == "__main__":
    unittest.main()

"""Isolated safety regression tests; uses temporary folders and synthetic files."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.store import (E2E_DATABASE_PATH_ENV, E2E_MODE_ENV, E2E_WORKSPACE_ENV,
                       database_path as configured_database_path, validate_e2e_database_path)
from e2e_safety import E2EWorkspace, SafetyError, child_environment


class E2ESafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="story-connect-e2e-test-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = E2EWorkspace(self.temp.name)
        self.addCleanup(self.workspace.close_handles)
        self.root = self.workspace.create()

    def tearDown(self):
        # Leave synthetic workspace removal to TemporaryDirectory's scoped cleanup.
        self.workspace.path = None

    def test_database_path_requires_explicit_unique_disposable_location(self):
        for invalid in (None, "database/prototype.sqlite3", "database/.e2e-phase34.sqlite3",
                        "../data/e2e.sqlite3", Path(self.temp.name) / "outside.sqlite3"):
            with self.subTest(invalid=invalid), self.assertRaises(SafetyError):
                self.workspace.database_path(invalid)
        expected = self.root / "database" / "e2e.sqlite3"
        self.assertEqual(self.workspace.database_path(expected), expected)
        self.assertFalse(expected.exists())

    def test_child_environment_rejects_arbitrary_missing_and_default_paths(self):
        base = {"PATH": "runtime", "BASETEN_API_KEY": "synthetic", "AWS_SECRET_ACCESS_KEY": "synthetic",
                "ENABLE_BASETEN": "1", "HACKATHON_DB_PATH": "normal-db"}
        for configured in (None, Path(self.temp.name) / "database" / "e2e.sqlite3",
                           Path("C:/hackathon/data/e2e.sqlite3"),
                           Path("C:/hackathon/data/prototype.sqlite3")):
            with self.subTest(configured=configured), self.assertRaises(SafetyError):
                child_environment(base, self.workspace, configured)

    def test_child_environment_is_allowlisted_and_forces_e2e_database(self):
        database = self.workspace.database_path("database/e2e.sqlite3")
        env = child_environment(
            {"PATH": "runtime", "SYSTEMROOT": "windows", "BASETEN_API_KEY": "secret",
             "AWS_SECRET_ACCESS_KEY": "secret", "OPENAI_API_KEY": "secret", "ENABLE_BASETEN": "1"},
            self.workspace, database,
        )
        self.assertEqual(set(env), {"PATH", "SYSTEMROOT", "ENABLE_BASETEN", "STORY_CONNECT_E2E_MODE",
                                    "STORY_CONNECT_E2E_WORKSPACE", "STORY_CONNECT_E2E_DATABASE_PATH"})
        self.assertEqual(env["ENABLE_BASETEN"], "0")
        self.assertEqual(env["STORY_CONNECT_E2E_DATABASE_PATH"], str(database))

    def test_backend_e2e_boundary_accepts_only_marked_workspace_database(self):
        database = self.workspace.database_path("database/e2e.sqlite3")
        self.assertEqual(validate_e2e_database_path(database, self.root), database)
        for path in (self.root / "database" / "prototype.sqlite3", Path(self.temp.name) / "outside.sqlite3",
                     self.root / "database" / ".e2e-phase34.sqlite3"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_e2e_database_path(path, self.root)
        self.assertFalse(database.exists())

    def test_backend_selects_e2e_database_only_with_complete_explicit_configuration(self):
        database = self.workspace.database_path("database/e2e.sqlite3")
        e2e_env = {E2E_MODE_ENV: "1", E2E_WORKSPACE_ENV: str(self.root),
                   E2E_DATABASE_PATH_ENV: str(database)}
        with patch.dict(os.environ, e2e_env, clear=True):
            self.assertEqual(configured_database_path(), database)
        with patch.dict(os.environ, {E2E_MODE_ENV: "1"}, clear=True):
            with self.assertRaises(ValueError):
                configured_database_path()

    def test_backend_e2e_boundary_rejects_missing_or_replaced_manifest(self):
        database = self.workspace.database_path("database/e2e.sqlite3")
        manifest = self.root / ".story-connect-e2e-owner.json"
        original = manifest.read_text(encoding="utf-8")
        manifest.unlink()
        with self.assertRaises(ValueError):
            validate_e2e_database_path(database, self.root)
        manifest.write_text(original, encoding="utf-8")
        with self.assertRaises(SafetyError):
            self.workspace.database_path(database)

    def test_cleanup_refuses_registered_directory_with_unregistered_file(self):
        profile = self.workspace.register_created_artifact("profile")
        (profile / "foreign.txt").write_text("synthetic", encoding="utf-8")
        with self.assertRaises(SafetyError):
            self.workspace.cleanup()
        self.assertTrue((profile / "foreign.txt").exists())

    def test_cleanup_refuses_unregistered_nested_directory(self):
        profile = self.workspace.register_created_artifact("profile")
        (profile / "foreign").mkdir()
        with self.assertRaises(SafetyError):
            self.workspace.cleanup()
        self.assertTrue((profile / "foreign").is_dir())

    def test_cleanup_refuses_when_identity_is_uncertain(self):
        with self.assertRaisesRegex(SafetyError, "handle-relative cleanup"):
            self.workspace.cleanup()

    def test_workspace_replacement_is_detected(self):
        moved = self.root.with_name(self.root.name + "-old")
        if os.name == "nt":
            try:
                self.root.rename(moved)
            except OSError:
                self.assertEqual(self.workspace.database_path("database/e2e.sqlite3"),
                                 self.root / "database" / "e2e.sqlite3")
                return
        self.root.rename(moved)
        self.root.mkdir()
        (self.root / ".story-connect-e2e-owner.json").write_text(
            json.dumps({"schema": 1, "run_id": self.workspace.run_id, "workspace": str(self.root)}),
            encoding="utf-8",
        )
        with self.assertRaises(SafetyError):
            self.workspace.database_path("database/e2e.sqlite3")

    def test_ownership_manifest_replacement_is_detected(self):
        manifest = self.root / ".story-connect-e2e-owner.json"
        original = manifest.read_text(encoding="utf-8")
        if os.name == "nt":
            try:
                manifest.unlink()
            except OSError:
                self.assertEqual(self.workspace.database_path("database/e2e.sqlite3"),
                                 self.root / "database" / "e2e.sqlite3")
                return
        else:
            manifest.unlink()
        manifest.write_text(original, encoding="utf-8")
        with self.assertRaises(SafetyError):
            self.workspace.database_path("database/e2e.sqlite3")

    def test_registered_file_replacement_is_detected(self):
        artifact = self.workspace.register_created_artifact("owned.txt")
        replacement = self.root / "replacement.txt"
        replacement.write_text("synthetic", encoding="utf-8")
        if os.name == "nt":
            try:
                artifact.unlink()
            except OSError:
                self.assertEqual(self.workspace._identity(artifact), self.workspace._identities["owned.txt"])
                return
        else:
            artifact.unlink()
        replacement.rename(artifact)
        with self.assertRaises(SafetyError):
            self.workspace.cleanup()

    def test_registered_directory_replacement_is_detected(self):
        artifact = self.workspace.register_created_artifact("owned-dir")
        replacement = self.root / "replacement-dir"
        replacement.mkdir()
        if os.name == "nt":
            try:
                artifact.rename(self.root / "moved-dir")
            except OSError:
                self.assertEqual(self.workspace._identity(artifact), self.workspace._identities["owned-dir"])
                return
        else:
            artifact.rename(self.root / "moved-dir")
        replacement.rename(artifact)
        with self.assertRaises(SafetyError):
            self.workspace.cleanup()

    def test_symlink_escape_rejected_when_creation_is_available(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        try:
            (self.root / "database").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Directory symlinks are unavailable in this environment.")
        with self.assertRaises(SafetyError):
            self.workspace.database_path("database/e2e.sqlite3")

    @unittest.skipUnless(os.name == "nt", "Windows reparse point attributes are platform-specific")
    def test_reparse_point_attribute_is_rejected(self):
        import e2e_safety
        class ReparseInfo:
            st_file_attributes = 0x400
        self.assertTrue(e2e_safety._is_reparse_point(ReparseInfo()))


if __name__ == "__main__":
    unittest.main()

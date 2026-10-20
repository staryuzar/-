"""Release ZIP hygiene regression tests for ci_prepare_release.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).with_name("ci_prepare_release.py")
SPEC = importlib.util.spec_from_file_location("ci_prepare_release", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseArchiveHygieneTests(unittest.TestCase):
    def test_excludes_runtime_and_secret_artifacts(self):
        for value in (
            ".pytest_cache/README.md",
            "__pycache__/module.pyc",
            ".env",
            ".env.local",
            ".ENV.PRODUCTION",
            "data/aurora.sqlite3",
            "data/aurora.sqlite3-wal",
            "logs/app.log",
            "logs/app.log.1",
            "private/signing-key.pem",
            "private/client.p12",
            "credentials.json",
            "Secrets.JSON",
            "service_account.json",
            "config/backup_credentials.json",
            ".envrc",
            ".netrc",
            ".npmrc",
            ".pypirc",
            "git-credentials",
            ".aws/credentials",
            ".ssh/id_ecdsa",
            ".docker/config.json",
            ".kube/config",
            ".config/gcloud/application_default_credentials.json",
            ".config/gh/hosts.yml",
            ".venv/pyvenv.cfg",
            ".GIT/config",
        ):
            with self.subTest(value=value):
                self.assertTrue(MODULE.is_release_excluded(Path(value)))

    def test_keeps_template_docs_and_application_source(self):
        for value in (
            ".env.example",
            "docs/.env.example",
            "README_AR.md",
            "docs/MT5_FIELD_GUIDE_AR.md",
            "app.py",
            "tests/test_tool_executor.py",
        ):
            with self.subTest(value=value):
                self.assertFalse(MODULE.is_release_excluded(Path(value)))

    def test_manifest_and_zip_omit_excluded_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".env.example").write_text("AI_PROVIDER=gemini\n", encoding="utf-8")
            (root / ".env").write_text("GEMINI_API_KEY=secret-placeholder\n", encoding="utf-8")
            (root / "aurora.sqlite3").write_bytes(b"local db placeholder")
            cache = root / ".pytest_cache"
            cache.mkdir()
            (cache / "README.md").write_text("cache", encoding="utf-8")

            MODULE.rebuild_manifest(root)
            output = Path(temporary) / "release.zip"
            MODULE.build_zip(root, output)

            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
            self.assertEqual(
                names,
                {"app.py", ".env.example", "PACKAGE_SHA256SUMS_AR.txt"},
            )
            manifest = (root / "PACKAGE_SHA256SUMS_AR.txt").read_text(encoding="utf-8")
            self.assertIn("app.py", manifest)
            self.assertIn(".env.example", manifest)
            self.assertNotIn(".env  ", manifest)
            self.assertNotIn("aurora.sqlite3", manifest)
            self.assertNotIn(".pytest_cache", manifest)


if __name__ == "__main__":
    unittest.main()

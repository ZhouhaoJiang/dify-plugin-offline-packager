from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import profiles  # noqa: E402


class ProfileCatalogTest(unittest.TestCase):
    def test_repository_catalog_has_supported_profiles(self) -> None:
        catalog = profiles.load_catalog()
        selected = catalog.get("dify-compose-3.12.0")
        self.assertEqual(selected.name, "dify-compose-3.12.0")
        self.assertEqual(selected.python_version, "3.12")
        self.assertEqual(
            selected.platform_status("linux/amd64")["status"],
            "integration-tested",
        )

    def test_custom_image_invalidates_profile_validation_claim(self) -> None:
        catalog = profiles.load_catalog()
        selection = profiles.select_runtime(
            catalog,
            "dify-compose-3.9.2",
            runtime_image="registry.example.invalid/custom:3.9.2",
        )
        self.assertTrue(selection.customized)
        self.assertEqual(
            selection.validation("linux/amd64")["status"],
            "custom-runtime-not-validated",
        )

    def test_rejects_empty_profile_catalog(self) -> None:
        document = {
            "schema_version": 2,
            "profiles": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profiles.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(profiles.ProfileError):
                profiles.load_catalog(path)


if __name__ == "__main__":
    unittest.main()

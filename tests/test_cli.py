from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli  # noqa: E402


class CliTest(unittest.TestCase):
    def test_cli_version_matches_project_metadata(self) -> None:
        metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        self.assertIn(f'version = "{cli.VERSION}"', metadata)

    def test_default_output_contains_target_architecture(self) -> None:
        source = Path("plugin.difypkg")
        self.assertEqual(
            cli.default_output(source, "linux/amd64"),
            Path("plugin-offline-linux-amd64.difypkg"),
        )

    def test_runtime_errors_rejects_python_mismatch(self) -> None:
        selection = cli.select_runtime(cli.CATALOG, "enterprise-3.12.0")
        probe = {
            "python_version": "3.11.9",
            "uv_path": "/usr/bin/uv",
            "package_cli_exists": True,
            "package_cli_sha256": selection.validation("linux/amd64")["observed_cli_sha256"],
            "machine": "x86_64",
        }
        errors = cli.runtime_errors(
            selection,
            "linux/amd64",
            probe,
            require_cli=True,
        )
        self.assertTrue(any("Python 3.12" in error for error in errors))

    def test_runtime_errors_rejects_image_digest_mismatch(self) -> None:
        selection = cli.select_runtime(cli.CATALOG, "enterprise-3.12.0")
        probe = {
            "python_version": "3.12.13",
            "uv_path": "/usr/bin/uv",
            "package_cli_exists": True,
            "package_cli_sha256": selection.validation("linux/amd64")["observed_cli_sha256"],
            "machine": "x86_64",
        }
        errors = cli.runtime_errors(
            selection,
            "linux/amd64",
            probe,
            require_cli=True,
            identity={"repo_digests": ["example.invalid/repo@sha256:" + "0" * 64]},
        )
        self.assertTrue(any("image digest differs" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

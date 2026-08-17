from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import container_worker as worker  # noqa: E402


class SafeExtractTest(unittest.TestCase):
    def test_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "bad.difypkg"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../escape", "bad")
            with self.assertRaises(worker.PackagerError):
                worker.safe_extract(package, root / "output", 1024)

    def test_extracts_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "ok.difypkg"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("manifest.yaml", "type: plugin\n")
            worker.safe_extract(package, root / "output", 1024)
            self.assertEqual((root / "output/manifest.yaml").read_text(), "type: plugin\n")


class RequirementsTest(unittest.TestCase):
    def test_strips_network_options_but_keeps_dependencies(self) -> None:
        source = """--no-index --find-links=./wheels/
--index-url https://example.invalid/simple
--trusted-host example.invalid
requests==2.34.2
"""
        self.assertEqual(
            worker.strip_online_requirement_options(source),
            "requests==2.34.2\n",
        )


class WheelMetadataTest(unittest.TestCase):
    def test_builds_sorted_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheels = Path(temporary)
            self._wheel(wheels / "z_pkg-2.0-py3-none-any.whl", "Z_Pkg", "2.0")
            self._wheel(wheels / "a_pkg-1.0-py3-none-any.whl", "a.pkg", "1.0")
            self.assertEqual(worker.wheel_pins(wheels), ["a.pkg==1.0", "Z_Pkg==2.0"])

    def test_ignores_vendored_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheels = Path(temporary)
            wheel = wheels / "setuptools-83.0.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "setuptools-83.0.0.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: setuptools\nVersion: 83.0.0\n\n",
                )
                archive.writestr(
                    "setuptools/_vendor/wheel-0.46.3.dist-info/METADATA",
                    "Metadata-Version: 2.1\nName: wheel\nVersion: 0.46.3\n\n",
                )
            self.assertEqual(worker.wheel_pins(wheels), ["setuptools==83.0.0"])

    @staticmethod
    def _wheel(path: Path, name: str, version: str) -> None:
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{name}-{version}.dist-info/METADATA", io.BytesIO(metadata.encode()).getvalue())


if __name__ == "__main__":
    unittest.main()

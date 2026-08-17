from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli  # noqa: E402


class CliTest(unittest.TestCase):
    def test_default_output_contains_target_architecture(self) -> None:
        source = Path("plugin.difypkg")
        self.assertEqual(
            cli.default_output(source, "linux/amd64"),
            Path("plugin-offline-linux-amd64.difypkg"),
        )


if __name__ == "__main__":
    unittest.main()
